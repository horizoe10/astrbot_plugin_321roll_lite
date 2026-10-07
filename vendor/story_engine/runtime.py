"""Deterministic EventCompositionIR evaluator; returns proposals and never commits state."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from .catastrophic import CatastrophicContractError, validate_compiled_catastrophic_event
from .compiler import Artifact
from .contracts.events import (
    CausalLinkProposal, EffectProposal, EventActivationRequest, EventAdvanceRequest, EventAdvanceResult, EventAdvanceStatus, EventLifecycleStatus,
    GateDecision,
    EventStateProposal, EventStateSnapshot, PendingGateProposal, event_result_fingerprint,
    validate_event_advance, validate_event_snapshot_fingerprint, validate_gate_response_fingerprint,
)
from .contracts.port import (
    AnonymousProgress, CancellationCheck, PlatformBridge, PortContractError, Problem,
    ProblemCode, STORY_ENGINE_PORT_VERSION, canonical_fingerprint, freeze_json,
)
from .contracts.proposals import EventProjectionFragment
from .resources import ActorResourceSnapshot, DeterministicResourceEvaluator, TypedEffectProposal
from .conditions import ConditionContractError, FactCatalog, GuardFactSnapshot, GUARD_CAPABILITY, evaluate_condition_tree, normalize_condition_tree
from .choices import ChoiceContractError, validate_compiled_choice_event
from .versions import EVENT_COMPOSITION_IR_CHOICE_SCHEMA, EVENT_COMPOSITION_IR_GUARD_SCHEMA, EVENT_COMPOSITION_IR_SCHEMA

_ZERO_DIGEST = "sha256:" + "0" * 64
_TERMINAL_STATES = frozenset({EventLifecycleStatus.RESOLVED, EventLifecycleStatus.ARCHIVED, EventLifecycleStatus.CANCELLED})
_GATE_TYPES = MappingProxyType({"preview": "player_choice", "consent": "actor_consent", "host": "human_dm"})


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _problem(code: ProblemCode, operation: str, reason: str, next_action: str) -> Problem:
    return Problem(code, operation, reason, "没有生成可提交状态或效果提案。", next_action)


def _finalize(result: EventAdvanceResult) -> EventAdvanceResult:
    finalized = replace(result, result_fingerprint=event_result_fingerprint(result))
    return finalized


@dataclass(frozen=True, slots=True)
class RuntimeEventDefinition:
    artifact_ref: str
    artifact_sha256: str
    canonical_sha256: str
    value: Mapping[str, Any]
    narrative_documents: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        frozen = freeze_json(self.value, "event_ir")
        if frozen.get("schema") not in {EVENT_COMPOSITION_IR_SCHEMA, EVENT_COMPOSITION_IR_GUARD_SCHEMA, EVENT_COMPOSITION_IR_CHOICE_SCHEMA}:
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "event_ir.schema", "事件 IR 版本不兼容。")
        required = ("identity", "source", "profile", "profile_version", "capability_closure", "checkpoint_graph", "resource_budgets", "cancellation_policy", "event_ir_sha256")
        if any(name not in frozen for name in required):
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "event_ir", "事件 IR 缺少运行字段。")
        expected_event_sha = canonical_fingerprint({key: item for key, item in frozen.items() if key != "event_ir_sha256"})
        if frozen["event_ir_sha256"] != expected_event_sha:
            raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "event_ir.event_ir_sha256", "事件 IR 内容指纹不匹配。")
        if frozen["schema"] == EVENT_COMPOSITION_IR_CHOICE_SCHEMA:
            try:
                validate_compiled_choice_event(frozen)
            except ChoiceContractError as exc:
                raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, exc.path, exc.reason) from exc
        try:
            validate_compiled_catastrophic_event(frozen)
        except CatastrophicContractError as exc:
            raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, exc.path, exc.reason) from exc
        object.__setattr__(self, "value", frozen)
        object.__setattr__(self, 'narrative_documents', tuple(freeze_json(item,'event_narrative') for item in self.narrative_documents))

    @property
    def definition_ref(self) -> str:
        return str(self.value["identity"]["id"])

    @property
    def definition_sha256(self) -> str:
        return str(self.value["source"]["definition_hash"])

    @property
    def capability_closure_sha256(self) -> str:
        return canonical_fingerprint(self.value["capability_closure"])


class RuntimeEventCatalog:
    """Immutable lookup compiled from one or more verified Artifacts."""

    def __init__(self, definitions: Iterable[RuntimeEventDefinition]) -> None:
        values: dict[tuple[str, str], RuntimeEventDefinition] = {}
        for definition in definitions:
            key = (definition.artifact_ref, definition.definition_ref)
            if key in values:
                raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "event_catalog", "事件运行定义重复。")
            values[key] = definition
        self._values = MappingProxyType(dict(sorted(values.items())))
        self.fingerprint = canonical_fingerprint({"definitions": [
            {"artifact_ref": item.artifact_ref, "artifact_sha256": item.artifact_sha256, "definition_ref": item.definition_ref, "event_ir_sha256": item.value["event_ir_sha256"]}
            for item in self._values.values()
        ]})

    @classmethod
    def from_artifact(cls, artifact: Artifact, *, artifact_ref: str) -> "RuntimeEventCatalog":
        value = artifact.to_mapping()
        expected_artifact_sha = canonical_fingerprint({key: item for key, item in value.items() if key != "artifact_sha256"})
        if artifact.artifact_sha256 != expected_artifact_sha:
            raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "artifact.artifact_sha256", "Artifact 内容指纹不匹配。")
        from .event_narrative_annotations import event_annotation_index
        try:annotations=event_annotation_index(value.get('v02_extension',{}).get('products',{}).get('narrative_style'),value['event_compositions'])
        except (KeyError,TypeError,ValueError) as exc:raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE,'event_narratives',str(exc)) from exc
        return cls(RuntimeEventDefinition(artifact_ref, artifact.artifact_sha256, str(value["canonical_ir_sha256"]), item, tuple(doc for (event_ref,_),doc in annotations.items() if event_ref==item['identity']['id'])) for item in value["event_compositions"])

    def resolve(self, snapshot: EventStateSnapshot) -> RuntimeEventDefinition:
        definition = self._values.get((snapshot.artifact_ref, snapshot.definition_ref))
        if definition is None:
            raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "event_state.definition_ref", "事件定义不在当前 Artifact 目录中。")
        expected = (
            definition.artifact_sha256, definition.definition_sha256, definition.value["profile"],
            definition.value["profile_version"], definition.capability_closure_sha256,
        )
        actual = (
            snapshot.artifact_sha256, snapshot.definition_sha256, snapshot.profile,
            snapshot.profile_version, snapshot.capability_closure_sha256,
        )
        if actual != expected:
            raise PortContractError(ProblemCode.RESULT_STALE, "event_state", "事件快照与当前 Artifact 或能力闭包不一致。")
        return definition


class DeterministicEventEvaluator:
    def __init__(self, catalog: RuntimeEventCatalog, *, resource_evaluator: DeterministicResourceEvaluator | None = None, clock: Callable[[], datetime] | None = None) -> None:
        self.catalog = catalog
        self.resource_evaluator = resource_evaluator
        self._clock = clock or (lambda: datetime.now(UTC))

    def evaluate(self, request: EventAdvanceRequest) -> EventAdvanceResult:
        definition = self.catalog.resolve(request.event_state)
        state = request.event_state
        catastrophic = definition.value.get("catastrophic_contract")
        if isinstance(catastrophic, Mapping):
            missing = set(catastrophic["required_capability_refs"]) - set(request.allowed_capability_refs)
            if missing:
                return self._blocked(
                    request,
                    ProblemCode.CONTRACT_INCOMPATIBLE,
                    "灾难请求缺少 Artifact 冻结的必需能力：" + "、".join(sorted(missing)),
                    "刷新平台能力快照；未知或缺失能力不得降级执行。",
                )
        if self._clock() >= min(_parse_time(request.envelope.deadline_at), _parse_time(state.deadline_at)):
            return self._terminal(request, EventAdvanceStatus.TIMED_OUT, ProblemCode.DEADLINE_EXCEEDED, "事件评估已超过冻结截止时间。", "请刷新事件状态后重试。")
        if state.status in _TERMINAL_STATES:
            return self._result(request, EventAdvanceStatus.NO_CHANGE, warnings=("事件已经处于终止状态。",))
        action = request.selected_action_ref
        if action == "event.instance.pause":
            if state.status is EventLifecycleStatus.PAUSED:
                return self._result(request, EventAdvanceStatus.NO_CHANGE, warnings=("事件已经暂停。",))
            return self._state_change(request, EventLifecycleStatus.PAUSED, state.phase, state.current_checkpoint_ref, state.locked_route_ref, state.eligible_route_refs, "事件将在当前检查点暂停。")
        if action == "event.instance.resume":
            if state.status is not EventLifecycleStatus.PAUSED:
                raise PortContractError(ProblemCode.INPUT_INVALID, "selected_action_ref", "只有暂停事件可以恢复。")
            return self._state_change(request, EventLifecycleStatus.ACTIVE, state.phase, state.current_checkpoint_ref, state.locked_route_ref, state.eligible_route_refs, "事件将从当前检查点恢复。")
        if action == "event.instance.cancel":
            if not self._cancellable(definition.value, state):
                return self._blocked(request, ProblemCode.SEMANTIC_VALIDATION_FAILED, "当前事件阶段不可撤销。", "请选择补救、救援或主持处理。")
            return self._state_change(request, EventLifecycleStatus.CANCELLED, "cancelled", state.current_checkpoint_ref, state.locked_route_ref, (), "事件取消提案已生成。")
        if state.status is EventLifecycleStatus.PAUSED:
            return self._blocked(request, ProblemCode.SEMANTIC_VALIDATION_FAILED, "事件仍处于暂停状态。", "请先选择恢复或由主持处理。")
        if definition.value["schema"] in {EVENT_COMPOSITION_IR_GUARD_SCHEMA, EVENT_COMPOSITION_IR_CHOICE_SCHEMA}:
            guarded = self._evaluate_guard(request, definition)
            if guarded is not None:
                return guarded
        return self._advance_route(request, definition.value,definition.narrative_documents)

    def activate(self, request: EventActivationRequest) -> EventAdvanceResult:
        definition = self.catalog.resolve(request.event_state)
        state = request.event_state
        validate_event_snapshot_fingerprint(state)
        if self._clock() >= min(_parse_time(request.envelope.deadline_at), _parse_time(state.deadline_at)):
            return self._terminal(request, EventAdvanceStatus.TIMED_OUT, ProblemCode.DEADLINE_EXCEEDED, "事件激活已超过冻结截止时间。", "刷新 provisional state 后重试。")
        event = definition.value
        if event["schema"] != EVENT_COMPOSITION_IR_CHOICE_SCHEMA or state.current_checkpoint_ref != event["initial_checkpoint_ref"]:
            return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "provisional state 未绑定 Artifact 1.3 的显式 activation root。", "使用匹配 Artifact 的 latent provisional state。")
        guarded = self._evaluate_guard(request, definition)
        if guarded is not None:
            return guarded
        nodes = {str(item["id"]): item for item in event["checkpoint_graph"]["nodes"]}
        current = nodes[str(event["initial_checkpoint_ref"])]
        outgoing = tuple(item["id"] for item in event["checkpoint_graph"]["edges"] if item["from"] == current["id"])
        choice_set = next((item for item in event["choice_sets"] if item["checkpoint_ref"] == current["id"]), None)
        if not outgoing or choice_set is None:
            return self._blocked(request, ProblemCode.STORY_PACK_INCOMPATIBLE, "激活 root 缺少完整 choice routes。", "修复 Artifact choice semantics 后重试。")
        gate = str(current.get("required_gate") or "")
        if gate and request.gate_response is None:
            gate_ref = f"gate.{state.instance_ref}.{current['id']}"
            proposal = PendingGateProposal(gate_ref, _GATE_TYPES[gate], state.audience_hint, str(current["public_summary"]), outgoing)
            return self._result(request, EventAdvanceStatus.NEEDS_INPUT, pending_gate_proposals=(proposal,))
        if gate:
            response = request.gate_response
            assert response is not None
            validate_gate_response_fingerprint(response)
            expected_gate_ref = f"gate.{state.instance_ref}.{current['id']}"
            if response.gate_ref != expected_gate_ref or response.gate_type != _GATE_TYPES[gate] or response.source_revision != state.revision:
                raise PortContractError(ProblemCode.RESULT_STALE, "gate_response", "激活 gate 回应与 provisional state 不一致。")
            if response.decision_receipt_ref not in request.committed_receipt_refs:
                raise PortContractError(ProblemCode.SEMANTIC_VALIDATION_FAILED, "gate_response.decision_receipt_ref", "激活 gate 缺少已提交回执。")
            if response.decision is GateDecision.REJECTED:
                return self._result(request, EventAdvanceStatus.NO_CHANGE, used_receipt_refs=(response.decision_receipt_ref,), warnings=("激活 gate 未获批准。",))
        proposal = EventStateProposal(state.revision, EventLifecycleStatus.ACTIVE, str(current["kind"]), str(current["id"]), None, outgoing, (), {}, "事件已通过 Artifact 显式 root 生成激活提案。")
        return self._result(request, EventAdvanceStatus.PROPOSED, next_event_state_proposal=proposal, available_action_semantics=tuple(choice_set["choices"]), used_receipt_refs=(() if request.gate_response is None else (request.gate_response.decision_receipt_ref,)))

    def _evaluate_guard(self, request: EventAdvanceRequest, definition: RuntimeEventDefinition) -> EventAdvanceResult | None:
        if GUARD_CAPABILITY not in request.allowed_capability_refs:
            return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "事件 guard required capability 未获平台冻结授权。", "刷新 capability snapshot 后重试。")
        value = request.rule_snapshot
        if not isinstance(value, Mapping) or set(value) != {"revision", "event_guard"} or isinstance(value.get("revision"), bool) or not isinstance(value.get("revision"), int) or value["revision"] < 0 or not isinstance(value.get("event_guard"), Mapping):
            return self._blocked(request, ProblemCode.GUARD_SNAPSHOT_MISSING, "事件 guard 冻结事实快照缺失或字段无效。", "由平台提供精确 event_guard snapshot。")
        world_revision = request.world_snapshot.get("revision")
        if isinstance(world_revision, bool) or not isinstance(world_revision, int) or world_revision < 0 or value["revision"] != world_revision:
            return self._blocked(request, ProblemCode.GUARD_REVISION_CONFLICT, "guard rule revision 与平台冻结 world/room revision 不一致。", "刷新权威 world/room revision 后重试。")
        try:
            catalog = FactCatalog.from_mapping(definition.value["fact_catalog"])
            if catalog.fingerprint != definition.value["fact_catalog_sha256"]:
                raise ConditionContractError("engine.guard_fingerprint_mismatch", "fact_catalog_sha256", "Artifact fact catalog fingerprint mismatches")
            tree = normalize_condition_tree(definition.value["guard_tree"], catalog)
            if tree.tree_sha256 != definition.value["guard_tree_sha256"]:
                raise ConditionContractError("engine.guard_fingerprint_mismatch", "guard_tree_sha256", "Artifact guard fingerprint mismatches")
            snapshot = GuardFactSnapshot.from_mapping(value["event_guard"], catalog)
            expected_identity = (
                definition.artifact_ref, definition.artifact_sha256, definition.definition_ref, definition.definition_sha256,
                tree.tree_sha256, catalog.fingerprint, request.event_state.revision, world_revision,
            )
            actual_identity = (
                snapshot.artifact_ref, snapshot.artifact_sha256, snapshot.definition_ref, snapshot.definition_sha256,
                snapshot.guard_tree_sha256, snapshot.fact_catalog_sha256, snapshot.event_revision, snapshot.rule_revision,
            )
            if actual_identity[:6] != expected_identity[:6]:
                raise ConditionContractError("engine.guard_fingerprint_mismatch", "event_guard", "guard snapshot identity mismatches Artifact")
            if actual_identity[6:] != expected_identity[6:]:
                raise ConditionContractError("engine.guard_revision_conflict", "event_guard", "guard snapshot revision is stale")
            accepted = evaluate_condition_tree(tree, snapshot, catalog)
        except ConditionContractError as exc:
            try:
                code = ProblemCode(exc.code)
            except ValueError:
                code = ProblemCode.SEMANTIC_VALIDATION_FAILED
            return self._blocked(request, code, exc.reason, "刷新 Artifact、revision 和已注册 facts 后重试。")
        if not accepted:
            return self._result(request, EventAdvanceStatus.NO_CHANGE, warnings=("事件 guard 条件为 false，未生成任何提案。",))
        return None

    def _advance_route(self, request: EventAdvanceRequest, event: Mapping[str, Any],narrative_documents=()) -> EventAdvanceResult:
        state = request.event_state
        nodes = {str(item["id"]): item for item in event["checkpoint_graph"]["nodes"]}
        edges = {str(item["id"]): item for item in event["checkpoint_graph"]["edges"]}
        current = nodes.get(str(state.current_checkpoint_ref or ""))
        if current is None:
            return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "当前检查点不在编译事件图中。", "请使用匹配 Artifact 的正式快照恢复事件。")
        gate = str(current.get("required_gate") or "")
        if gate and request.gate_response is None:
            gate_ref = f"gate.{state.instance_ref}.{current['id']}"
            proposal = PendingGateProposal(gate_ref, _GATE_TYPES[gate], state.audience_hint, str(current["public_summary"]), request.legal_action_refs)
            return self._result(request, EventAdvanceStatus.NEEDS_INPUT, pending_gate_proposals=(proposal,))
        if gate:
            response = request.gate_response
            assert response is not None
            expected_gate_ref = f"gate.{state.instance_ref}.{current['id']}"
            validate_gate_response_fingerprint(response)
            if response.gate_ref != expected_gate_ref or response.gate_type != _GATE_TYPES[gate]:
                raise PortContractError(ProblemCode.INPUT_INVALID, "gate_response.gate_ref", "gate 回应不属于当前检查点。")
            if response.source_revision != state.revision:
                raise PortContractError(ProblemCode.RESULT_STALE, "gate_response.source_revision", "gate 回应基于过期事件 revision。")
            if response.decision_receipt_ref not in request.committed_receipt_refs:
                raise PortContractError(ProblemCode.SEMANTIC_VALIDATION_FAILED, "gate_response.decision_receipt_ref", "gate 回应没有引用已提交平台回执。")
            if state.pending_gate_refs and response.gate_ref not in state.pending_gate_refs:
                raise PortContractError(ProblemCode.INPUT_INVALID, "gate_response.gate_ref", "gate 回应不在当前冻结待处理集合中。")
            if response.decision is GateDecision.REJECTED:
                return self._result(request, EventAdvanceStatus.NO_CHANGE, used_receipt_refs=(response.decision_receipt_ref,), warnings=("当前 gate 未获批准，事件保持原状态。",))
        route_ref = request.route_choice_ref or request.selected_action_ref
        if route_ref is None:
            return self._result(request, EventAdvanceStatus.NEEDS_INPUT, available_action_semantics=self._actions(event, str(current["id"])))
        route = edges.get(route_ref)
        if route is None or route["from"] != current["id"] or route_ref not in state.eligible_route_refs:
            raise PortContractError(ProblemCode.INPUT_INVALID, "route_choice_ref", "路线不属于当前冻结检查点。")
        if event["checkpoint_graph"]["bounded_loops"]:
            if not state.visit_counts:
                return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "事件快照缺少循环检查点访问计数。", "请由平台补齐冻结 visit_counts 后恢复。")
            known_nodes = set(nodes)
            if not set(state.visit_counts) <= known_nodes:
                return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "事件快照包含未知检查点访问计数。", "请使用匹配 Artifact 的 visit_counts 重试。")
            next_visits = int(state.visit_counts.get(str(route["to"]), 0)) + 1
            target_limit = int(nodes[str(route["to"])]["max_visits"])
            global_limit = int(event["resource_budgets"]["max_loop_iterations"])
            total_loop_visits = sum(int(value) for value in state.visit_counts.values()) + 1
            if (event['profile'],event['profile_version'])==('crisis_event','1.2.0'):
                # R2's finite scene chain is not a loop. Charge only revisits;
                # the existing versions retain their frozen counting policy.
                total_loop_visits = sum(max(0,int(value)-1) for value in state.visit_counts.values()) + int(next_visits>1)
            if next_visits > target_limit or total_loop_visits > global_limit:
                return self._blocked(request, ProblemCode.BUDGET_EXHAUSTED, "循环检查点访问预算已耗尽。", "请选择 timeout exit、安全出口或由主持处理。")
        used = int(state.budgets_used.get("checkpoints", state.budgets_used.get("turns", 0)))
        maximum = int(event["resource_budgets"]["max_checkpoints"])
        if used + 1 > maximum:
            return self._blocked(request, ProblemCode.BUDGET_EXHAUSTED, "事件检查点预算已耗尽。", "请选择安全出口或由主持处理。")
        target = nodes[str(route["to"])]
        next_status = EventLifecycleStatus.AFTERMATH if target.get("exit_kind") else EventLifecycleStatus.ACTIVE
        next_routes = tuple(item["id"] for item in event["checkpoint_graph"]["edges"] if item["from"] == target["id"])
        proposal = EventStateProposal(state.revision, next_status, str(target["kind"]), str(target["id"]), str(route["id"]), next_routes, (), {"checkpoints": 1}, str(route["public_meaning"]))
        effect_proposals: list[EffectProposal | TypedEffectProposal] = []
        causal_proposals: list[CausalLinkProposal] = []
        for template in event["effects"]:
            if template["route_id"] != route_ref:
                continue
            if template["capability_ref"] not in request.allowed_capability_refs:
                return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "路线 effect 所需能力不在平台冻结允许集合中。", "请刷新能力快照或选择其他路线。")
            revision_source = template["revision_source"]
            revision_value: object = state.revision if revision_source == "event" else (request.world_snapshot if revision_source == "world" else request.actor_snapshot).get("revision")
            if not isinstance(revision_value, int) or isinstance(revision_value, bool) or revision_value < 0:
                return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "路线 effect 缺少冻结的目标 revision。", "请由平台补齐对应 world/actor revision 后重试。")
            stable = canonical_fingerprint({"operation_ref": request.envelope.operation_ref, "effect_id": template["id"]})[7:39]
            proposal_ref, dedupe_key = f"effect.{stable}", f"dedupe.{stable}"
            gate_checkpoint_ref = template["gate_checkpoint_ref"]
            gate_ref = f"gate.{state.instance_ref}.{gate_checkpoint_ref}" if gate_checkpoint_ref is not None else None
            capability_ref = str(template["capability_ref"])
            effect_type = str(template["effect_type"])
            capability_base = capability_ref.rsplit("/", 1)[0]
            if capability_base in {"actor.resource_pool", "actor.vitality"}:
                if self.resource_evaluator is None:
                    return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "Artifact 资源 effect 缺少 pack-bound evaluator。", "请使用同一 Artifact 重建 Engine 实例后重试。")
                resource_ref = str(template["payload"].get("resource_ref") or "")
                snapshots = request.actor_snapshot.get("resource_snapshots")
                snapshot_value = snapshots.get(resource_ref) if isinstance(snapshots, Mapping) else None
                if not isinstance(snapshot_value, Mapping):
                    return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "角色快照缺少 effect 所需的冻结资源快照。", "请按 resource_ref 提供 ActorResourceSnapshot 后重试。")
                snapshot = ActorResourceSnapshot.from_mapping(snapshot_value)
                room_revision = request.actor_snapshot.get("room_revision")
                if isinstance(room_revision, bool) or not isinstance(room_revision, int) or room_revision < 0:
                    return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "角色快照缺少冻结 room revision。", "请补齐 actor_snapshot.room_revision 后重试。")
                intent = {
                    "capability_ref": capability_ref,
                    "intent_type": effect_type,
                    "target_binding": str(template["target_ref"]),
                    "payload": template["payload"],
                    "expected_revisions": {"actor_revision": snapshot.actor_revision, "room_revision": room_revision},
                    "operation_ref": request.envelope.operation_ref,
                    "request_fingerprint": request.envelope.request_fingerprint,
                }
                effect_proposals.append(self.resource_evaluator.evaluate(
                    intent,
                    proposal_ref=proposal_ref,
                    dedupe_key=dedupe_key,
                    atomic_group_ref=f"atomic.{stable}",
                    allowed_capabilities=request.allowed_capability_refs,
                    snapshot=snapshot,
                ))
            else:
                effect_proposals.append(EffectProposal(proposal_ref, capability_ref, effect_type, str(template["target_ref"]), revision_value, template["payload"], bool(template["reversible"]), gate_ref, dedupe_key))
            causal_proposals.append(CausalLinkProposal(f"causal.{stable}", (request.envelope.operation_ref,), "causes", proposal_ref))
        freshness = canonical_fingerprint({"operation_ref": request.envelope.operation_ref, "revision": state.revision, "route_ref": route_ref, "audience": state.audience_hint})
        annotations=tuple(doc for doc in narrative_documents if doc['route_ref']==route_ref)
        projection = EventProjectionFragment("se-event-projection-fragment/1.0.0", "checkpoint_advanced", state.audience_hint, str(event["identity"]["label"]), (str(route["public_meaning"]),), annotations, self._actions(event, str(target["id"])), (state.definition_ref, request.envelope.operation_ref), (), freshness)
        return self._result(request, EventAdvanceStatus.PROPOSED, next_event_state_proposal=proposal, effect_proposals=tuple(effect_proposals), causal_link_proposals=tuple(causal_proposals), available_action_semantics=self._actions(event, str(target["id"])), projection_fragments=(projection,))

    @staticmethod
    def _actions(event: Mapping[str, Any], checkpoint_ref: str) -> tuple[Mapping[str, Any], ...]:
        return tuple({"action_ref": item["id"], "label": item["public_meaning"], "route_outcome": item["outcome"]} for item in event["checkpoint_graph"]["edges"] if item["from"] == checkpoint_ref)

    @staticmethod
    def _cancellable(event: Mapping[str, Any], state: EventStateSnapshot) -> bool:
        policy = event["cancellation_policy"]
        if policy == "until_triggered": return state.status in {EventLifecycleStatus.LATENT, EventLifecycleStatus.ARMED}
        if policy == "host_only_after_trigger": return True  # platform legal-action freeze already enforced host authority
        nodes = {str(item["id"]): item for item in event["checkpoint_graph"]["nodes"]}
        node = nodes.get(str(state.current_checkpoint_ref or ""))
        return node is not None and not bool(node["irreversible"])

    def _state_change(self, request: EventAdvanceRequest, status: EventLifecycleStatus, phase: str, checkpoint: str | None, route: str | None, eligible: tuple[str, ...], reason: str) -> EventAdvanceResult:
        proposal = EventStateProposal(request.event_state.revision, status, phase, checkpoint, route, eligible, request.event_state.pending_gate_refs, {}, reason)
        return self._result(request, EventAdvanceStatus.PROPOSED, next_event_state_proposal=proposal)

    def _blocked(self, request: EventAdvanceRequest, code: ProblemCode, reason: str, next_action: str) -> EventAdvanceResult:
        return self._result(request, EventAdvanceStatus.BLOCKED, problems=(_problem(code, "评估事件检查点", reason, next_action),))

    def _terminal(self, request: EventAdvanceRequest, status: EventAdvanceStatus, code: ProblemCode, reason: str, next_action: str) -> EventAdvanceResult:
        return self._result(request, status, problems=(_problem(code, "评估事件检查点", reason, next_action),))

    @staticmethod
    def _result(request: EventAdvanceRequest, status: EventAdvanceStatus, *, next_event_state_proposal: EventStateProposal | None = None, effect_proposals: tuple[EffectProposal | TypedEffectProposal, ...] = (), causal_link_proposals: tuple[CausalLinkProposal, ...] = (), available_action_semantics: tuple[Mapping[str, Any], ...] = (), pending_gate_proposals: tuple[PendingGateProposal, ...] = (), projection_fragments: tuple[EventProjectionFragment, ...] = (), used_receipt_refs: tuple[str, ...] = (), warnings: tuple[str, ...] = (), problems: tuple[Problem, ...] = ()) -> EventAdvanceResult:
        return _finalize(EventAdvanceResult(STORY_ENGINE_PORT_VERSION, request.envelope.operation_ref, request.envelope.request_fingerprint, request.envelope.expected_revision, status, next_event_state_proposal, effect_proposals, causal_link_proposals, available_action_semantics, pending_gate_proposals, projection_fragments, used_receipt_refs, warnings, problems, _ZERO_DIGEST))


class EventEvaluationService:
    """StoryEnginePort.evaluate_event implementation with cooperative cancellation."""

    def __init__(self, evaluator: DeterministicEventEvaluator, *, clock: Callable[[], datetime] | None = None) -> None:
        self.evaluator = evaluator
        self._clock = clock or (lambda: datetime.now(UTC))

    async def evaluate_event(self, request: EventAdvanceRequest, bridge: PlatformBridge) -> EventAdvanceResult:
        check = CancellationCheck(request.envelope.operation_ref, request.envelope.request_fingerprint)
        if (await bridge.is_cancelled(check)).cancelled:
            return self.evaluator._terminal(request, EventAdvanceStatus.CANCELLED, ProblemCode.CANCELLED, "平台已取消当前操作。", "如仍需继续，请重新发起行动。")
        result = self.evaluator.evaluate(request)
        if (await bridge.is_cancelled(check)).cancelled:
            return self.evaluator._terminal(request, EventAdvanceStatus.CANCELLED, ProblemCode.CANCELLED, "事件评估完成前操作已取消。", "如仍需继续，请重新发起行动。")
        validate_event_advance(request, result)
        if result.status not in {EventAdvanceStatus.NO_CHANGE, EventAdvanceStatus.BLOCKED, EventAdvanceStatus.CANCELLED, EventAdvanceStatus.TIMED_OUT}:
            await bridge.publish_progress(AnonymousProgress(request.envelope.operation_ref, "event_evaluating", self._clock().isoformat(), True, True, 0))
            await bridge.publish_progress(AnonymousProgress(request.envelope.operation_ref, "event_evaluated", self._clock().isoformat(), False, False, 1))
        return result


class EventActivationService:
    """Versioned activation seam reusing the same deterministic event evaluator/catalog."""

    def __init__(self, evaluator: DeterministicEventEvaluator, *, clock: Callable[[], datetime] | None = None) -> None:
        self.evaluator = evaluator
        self._clock = clock or (lambda: datetime.now(UTC))

    async def activate_event(self, request: EventActivationRequest, bridge: PlatformBridge) -> EventAdvanceResult:
        check = CancellationCheck(request.envelope.operation_ref, request.envelope.request_fingerprint)
        if (await bridge.is_cancelled(check)).cancelled:
            return self.evaluator._terminal(request, EventAdvanceStatus.CANCELLED, ProblemCode.CANCELLED, "事件激活已取消。", "刷新 provisional state 后重试。")
        result = self.evaluator.activate(request)
        if (await bridge.is_cancelled(check)).cancelled:
            return self.evaluator._terminal(request, EventAdvanceStatus.CANCELLED, ProblemCode.CANCELLED, "事件激活结果在返回前已取消。", "刷新 provisional state 后重试。")
        validate_event_advance(request, result)
        return result


__all__ = ["DeterministicEventEvaluator", "EventEvaluationService", "RuntimeEventCatalog", "RuntimeEventDefinition"]
