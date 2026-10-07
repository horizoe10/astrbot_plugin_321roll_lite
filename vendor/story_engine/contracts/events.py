"""Frozen platform-owned event snapshots and bounded advance proposals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum, StrEnum
import re
from typing import Any

from .port import (
    OperationEnvelope, PortContractError, Problem, ProblemCode, STORY_ENGINE_PORT_VERSION,
    _digest, _ref, _text, _time, canonical_fingerprint, freeze_json,
)
from .proposals import EventProjectionFragment

_CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}(?:/(?:[0-9]+|[0-9]+\.[0-9]+\.[0-9]+))?$")


def _refs(values: tuple[str, ...], path: str) -> tuple[str, ...]:
    result = tuple(_ref(value, path) for value in values)
    if len(result) != len(set(result)):
        raise PortContractError(ProblemCode.INPUT_INVALID, path, "引用不能重复。")
    return result


def _capability_refs(values: tuple[str, ...], path: str) -> tuple[str, ...]:
    result = tuple(_text(value, path, 160) for value in values)
    if len(result) != len(set(result)) or any(_CAPABILITY_RE.fullmatch(value) is None for value in result):
        raise PortContractError(ProblemCode.INPUT_INVALID, path, "能力引用必须是唯一精确版本身份。")
    if any(value in {"actor.resource_pool", "actor.vitality"} for value in result):
        raise PortContractError(ProblemCode.INPUT_INVALID, path, "资源与生命力能力必须使用精确版本身份。")
    return result


class EventLifecycleStatus(StrEnum):
    LATENT = "latent"; ARMED = "armed"; TRIGGERED = "triggered"; ACTIVE = "active"
    PAUSED = "paused"; RESOLVING = "resolving"; AFTERMATH = "aftermath"
    RESOLVED = "resolved"; ARCHIVED = "archived"; BLOCKED = "blocked"; CANCELLED = "cancelled"


class EventAdvanceStatus(StrEnum):
    PROPOSED = "proposed"; NO_CHANGE = "no_change"; NEEDS_INPUT = "needs_input"
    BLOCKED = "blocked"; CANCELLED = "cancelled"; TIMED_OUT = "timed_out"


class GateDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class GateResponseSnapshot:
    contract_version: str
    gate_ref: str
    gate_type: str
    decision: GateDecision
    source_revision: int
    decided_by_ref: str
    decision_receipt_ref: str
    decided_at: str
    response_fingerprint: str

    def __post_init__(self) -> None:
        if self.contract_version != "event-gate-response/1.0.0":
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "gate_response.contract_version", "gate 回应版本不兼容。")
        for name in ("gate_ref", "gate_type", "decided_by_ref", "decision_receipt_ref"):
            _ref(getattr(self, name), f"gate_response.{name}")
        if self.gate_type not in {"player_choice", "vote", "actor_consent", "rescue", "terminal", "ending", "human_dm"}:
            raise PortContractError(ProblemCode.INPUT_INVALID, "gate_response.gate_type", "gate 类型无效。")
        if isinstance(self.source_revision, bool) or not isinstance(self.source_revision, int) or self.source_revision < 0:
            raise PortContractError(ProblemCode.INPUT_INVALID, "gate_response.source_revision", "gate 来源 revision 必须非负。")
        _time(self.decided_at, "gate_response.decided_at")
        _digest(self.response_fingerprint, "gate_response.response_fingerprint")

    def fingerprint_material(self) -> Mapping[str, Any]:
        return {
            "contract_version": self.contract_version,
            "gate_ref": self.gate_ref,
            "gate_type": self.gate_type,
            "decision": self.decision.value,
            "source_revision": self.source_revision,
            "decided_by_ref": self.decided_by_ref,
            "decision_receipt_ref": self.decision_receipt_ref,
            "decided_at": self.decided_at,
        }


@dataclass(frozen=True, slots=True)
class EventStateSnapshot:
    contract_version: str
    instance_ref: str
    definition_ref: str
    definition_sha256: str
    artifact_ref: str
    artifact_sha256: str
    profile: str
    profile_version: str
    capability_closure_sha256: str
    status: EventLifecycleStatus
    phase: str
    current_checkpoint_ref: str | None
    revision: int
    locked_route_ref: str | None
    eligible_route_refs: tuple[str, ...]
    pending_gate_refs: tuple[str, ...]
    child_receipt_refs: tuple[str, ...]
    budgets_used: Mapping[str, int]
    deadline_at: str
    audience_hint: str
    last_authoritative_reason_ref: str | None
    snapshot_fingerprint: str
    visit_counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.contract_version != "event-state/1.0.0":
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "contract_version", "事件快照版本不兼容。")
        for name in ("instance_ref", "definition_ref", "artifact_ref", "profile", "profile_version", "phase", "audience_hint"):
            _ref(getattr(self, name), name)
        for name in ("definition_sha256", "artifact_sha256", "capability_closure_sha256", "snapshot_fingerprint"):
            _digest(getattr(self, name), name)
        _time(self.deadline_at, "deadline_at")
        if isinstance(self.revision, bool) or self.revision < 0:
            raise PortContractError(ProblemCode.INPUT_INVALID, "revision", "事件 revision 必须非负。")
        for name in ("current_checkpoint_ref", "locked_route_ref", "last_authoritative_reason_ref"):
            if getattr(self, name) is not None: _ref(getattr(self, name), name)
        for name in ("eligible_route_refs", "pending_gate_refs", "child_receipt_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        budgets = freeze_json(self.budgets_used, "budgets_used")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in budgets.values()):
            raise PortContractError(ProblemCode.INPUT_INVALID, "budgets_used", "事件预算用量必须是非负整数。")
        object.__setattr__(self, "budgets_used", budgets)
        visits = freeze_json(self.visit_counts, "visit_counts")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in visits.values()):
            raise PortContractError(ProblemCode.INPUT_INVALID, "visit_counts", "检查点访问次数必须是非负整数。")
        for checkpoint_ref in visits:
            _ref(checkpoint_ref, "visit_counts")
        object.__setattr__(self, "visit_counts", visits)

    def fingerprint_material(self) -> Mapping[str, Any]:
        return {
            "contract_version": self.contract_version, "instance_ref": self.instance_ref,
            "definition_ref": self.definition_ref, "definition_sha256": self.definition_sha256,
            "artifact_ref": self.artifact_ref, "artifact_sha256": self.artifact_sha256,
            "profile": self.profile, "profile_version": self.profile_version,
            "capability_closure_sha256": self.capability_closure_sha256, "status": self.status.value,
            "phase": self.phase, "current_checkpoint_ref": self.current_checkpoint_ref,
            "revision": self.revision, "locked_route_ref": self.locked_route_ref,
            "eligible_route_refs": self.eligible_route_refs, "pending_gate_refs": self.pending_gate_refs,
            "child_receipt_refs": self.child_receipt_refs, "budgets_used": self.budgets_used,
            "deadline_at": self.deadline_at, "audience_hint": self.audience_hint,
            "last_authoritative_reason_ref": self.last_authoritative_reason_ref,
            "visit_counts": self.visit_counts,
        }


@dataclass(frozen=True, slots=True)
class EventAdvanceRequest:
    envelope: OperationEnvelope
    event_state: EventStateSnapshot
    actor_snapshot: Mapping[str, Any]
    action_roster_snapshot: tuple[Mapping[str, Any], ...]
    legal_action_refs: tuple[str, ...]
    allowed_capability_refs: tuple[str, ...]
    selected_action_ref: str | None
    route_choice_ref: str | None
    gate_response: GateResponseSnapshot | None
    world_snapshot: Mapping[str, Any]
    rule_snapshot: Mapping[str, Any]
    narrative_snapshot: Mapping[str, Any]
    committed_receipt_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.envelope.operation_type != "evaluate_event":
            raise PortContractError(ProblemCode.INPUT_INVALID, "operation_type", "事件操作类型无效。")
        if self.envelope.expected_revision != self.event_state.revision:
            raise PortContractError(ProblemCode.RESULT_STALE, "expected_revision", "请求 revision 与事件快照不一致。")
        if not self.action_roster_snapshot or not self.legal_action_refs:
            raise PortContractError(ProblemCode.INPUT_INVALID, "action_roster_snapshot", "事件请求缺少行动 roster 或合法行动。")
        for name in ("legal_action_refs", "committed_receipt_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        object.__setattr__(self, "allowed_capability_refs", _capability_refs(self.allowed_capability_refs, "allowed_capability_refs"))
        for name in ("selected_action_ref", "route_choice_ref"):
            if getattr(self, name) is not None: _ref(getattr(self, name), name)
        if self.selected_action_ref is not None and self.selected_action_ref not in self.legal_action_refs:
            raise PortContractError(ProblemCode.INPUT_INVALID, "selected_action_ref", "所选行动不在冻结合法集合中。")
        if self.route_choice_ref is not None and self.route_choice_ref not in self.event_state.eligible_route_refs:
            raise PortContractError(ProblemCode.INPUT_INVALID, "route_choice_ref", "所选路线不在冻结合法集合中。")
        for name in ("actor_snapshot", "world_snapshot", "rule_snapshot", "narrative_snapshot"):
            object.__setattr__(self, name, freeze_json(getattr(self, name), name))
        object.__setattr__(self, "action_roster_snapshot", tuple(freeze_json(item, "action_roster_snapshot") for item in self.action_roster_snapshot))
        if self.gate_response is not None and not isinstance(self.gate_response, GateResponseSnapshot):
            raise PortContractError(ProblemCode.INPUT_INVALID, "gate_response", "gate 回应必须使用类型化冻结快照。")


@dataclass(frozen=True, slots=True)
class EventActivationRequest:
    schema: str
    envelope: OperationEnvelope
    event_state: EventStateSnapshot
    actor_snapshot: Mapping[str, Any]
    action_roster_snapshot: tuple[Mapping[str, Any], ...]
    allowed_capability_refs: tuple[str, ...]
    gate_response: GateResponseSnapshot | None
    world_snapshot: Mapping[str, Any]
    rule_snapshot: Mapping[str, Any]
    narrative_snapshot: Mapping[str, Any]
    committed_receipt_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema != "se-event-activation/1.0.0" or self.envelope.operation_type != "activate_event":
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "activation.schema", "事件激活合同或操作类型不兼容。")
        if self.envelope.expected_revision != self.event_state.revision or self.event_state.status is not EventLifecycleStatus.LATENT:
            raise PortContractError(ProblemCode.RESULT_STALE, "event_state", "激活请求必须基于 latent provisional state 的精确 revision。")
        if self.event_state.current_checkpoint_ref is None or not self.action_roster_snapshot:
            raise PortContractError(ProblemCode.INPUT_INVALID, "event_state.current_checkpoint_ref", "激活请求缺少显式 root 或行动 roster。")
        state = self.event_state
        if state.revision != 0 or state.phase != "latent":
            raise PortContractError(ProblemCode.INPUT_INVALID, "event_state.phase", "provisional state 必须是 revision 0 的 latent phase。")
        if state.locked_route_ref is not None or state.eligible_route_refs or state.pending_gate_refs or state.child_receipt_refs:
            raise PortContractError(ProblemCode.INPUT_INVALID, "event_state.route_and_gate_state", "provisional state 不得预置 route、gate 或 child receipt。")
        if state.visit_counts or any(value != 0 for value in state.budgets_used.values()):
            raise PortContractError(ProblemCode.INPUT_INVALID, "event_state.usage", "provisional state 不得预置 visit 或非零预算使用量。")
        if state.last_authoritative_reason_ref is not None:
            raise PortContractError(ProblemCode.INPUT_INVALID, "event_state.last_authoritative_reason_ref", "provisional state 不得预置权威原因引用。")
        object.__setattr__(self, "allowed_capability_refs", _capability_refs(self.allowed_capability_refs, "allowed_capability_refs"))
        object.__setattr__(self, "committed_receipt_refs", _refs(self.committed_receipt_refs, "committed_receipt_refs"))
        for name in ("actor_snapshot", "world_snapshot", "rule_snapshot", "narrative_snapshot"):
            object.__setattr__(self, name, freeze_json(getattr(self, name), name))
        object.__setattr__(self, "action_roster_snapshot", tuple(freeze_json(item, "action_roster_snapshot") for item in self.action_roster_snapshot))
        if self.gate_response is not None and not isinstance(self.gate_response, GateResponseSnapshot):
            raise PortContractError(ProblemCode.INPUT_INVALID, "gate_response", "gate 回应必须使用类型化冻结快照。")


@dataclass(frozen=True, slots=True)
class EventStateProposal:
    source_revision: int
    next_status: EventLifecycleStatus
    next_phase: str
    next_checkpoint_ref: str | None
    locked_route_ref: str | None
    eligible_route_refs: tuple[str, ...]
    pending_gate_refs: tuple[str, ...]
    budget_deltas: Mapping[str, int]
    public_reason: str

    def __post_init__(self) -> None:
        if isinstance(self.source_revision, bool) or self.source_revision < 0: raise PortContractError(ProblemCode.OUTPUT_INVALID, "source_revision", "提案 revision 无效。")
        _ref(self.next_phase, "next_phase"); _text(self.public_reason, "public_reason", 1024)
        for name in ("next_checkpoint_ref", "locked_route_ref"):
            if getattr(self, name) is not None: _ref(getattr(self, name), name)
        for name in ("eligible_route_refs", "pending_gate_refs"):
            object.__setattr__(self, name, _refs(getattr(self, name), name))
        deltas = freeze_json(self.budget_deltas, "budget_deltas")
        if any(not isinstance(value, int) or isinstance(value, bool) for value in deltas.values()): raise PortContractError(ProblemCode.OUTPUT_INVALID, "budget_deltas", "预算变化必须是整数。")
        object.__setattr__(self, "budget_deltas", deltas)


@dataclass(frozen=True, slots=True)
class EffectProposal:
    proposal_ref: str; capability_ref: str; effect_type: str; target_ref: str
    expected_revision: int; payload: Mapping[str, Any]; reversible: bool
    gate_ref: str | None; dedupe_key: str

    def __post_init__(self) -> None:
        for name in ("proposal_ref", "effect_type", "target_ref", "dedupe_key"): _ref(getattr(self, name), name)
        _capability_refs((self.capability_ref,), "capability_ref")
        if self.gate_ref is not None: _ref(self.gate_ref, "gate_ref")
        if isinstance(self.expected_revision, bool) or self.expected_revision < 0: raise PortContractError(ProblemCode.OUTPUT_INVALID, "expected_revision", "effect revision 无效。")
        object.__setattr__(self, "payload", freeze_json(self.payload, "effect_payload"))


@dataclass(frozen=True, slots=True)
class CausalLinkProposal:
    link_ref: str; cause_refs: tuple[str, ...]; relation: str; effect_proposal_ref: str

    def __post_init__(self) -> None:
        _ref(self.link_ref, "link_ref"); _ref(self.relation, "relation"); _ref(self.effect_proposal_ref, "effect_proposal_ref")
        object.__setattr__(self, "cause_refs", _refs(self.cause_refs, "cause_refs"))
        if not self.cause_refs: raise PortContractError(ProblemCode.OUTPUT_INVALID, "cause_refs", "因果提案必须包含原因。")


@dataclass(frozen=True, slots=True)
class PendingGateProposal:
    gate_ref: str; gate_type: str; audience_hint: str; prompt: str; legal_action_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.gate_type not in {"player_choice", "vote", "actor_consent", "rescue", "terminal", "ending", "human_dm"}: raise PortContractError(ProblemCode.OUTPUT_INVALID, "gate_type", "gate 类型无效。")
        _ref(self.gate_ref, "gate_ref"); _ref(self.audience_hint, "audience_hint"); _text(self.prompt, "prompt", 1024)
        object.__setattr__(self, "legal_action_refs", _refs(self.legal_action_refs, "legal_action_refs"))


@dataclass(frozen=True, slots=True)
class EventAdvanceResult:
    engine_contract_version: str
    operation_ref: str
    request_fingerprint: str
    expected_revision: int
    status: EventAdvanceStatus
    next_event_state_proposal: EventStateProposal | None
    effect_proposals: tuple[Any, ...] = ()
    causal_link_proposals: tuple[CausalLinkProposal, ...] = ()
    available_action_semantics: tuple[Mapping[str, Any], ...] = ()
    pending_gate_proposals: tuple[PendingGateProposal, ...] = ()
    projection_fragments: tuple[EventProjectionFragment, ...] = ()
    used_receipt_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    problems: tuple[Problem, ...] = ()
    result_fingerprint: str = ""

    def __post_init__(self) -> None:
        if self.engine_contract_version != STORY_ENGINE_PORT_VERSION: raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "engine_contract_version", "事件结果合同版本不兼容。")
        _ref(self.operation_ref, "operation_ref"); _digest(self.request_fingerprint, "request_fingerprint"); _digest(self.result_fingerprint, "result_fingerprint")
        if isinstance(self.expected_revision, bool) or self.expected_revision < 0: raise PortContractError(ProblemCode.OUTPUT_INVALID, "expected_revision", "事件结果 revision 无效。")
        _validate_event_result_shape(self)
        object.__setattr__(self, "available_action_semantics", tuple(freeze_json(item, "available_action_semantics") for item in self.available_action_semantics))
        object.__setattr__(self, "used_receipt_refs", _refs(self.used_receipt_refs, "used_receipt_refs"))


def _material(value: Any) -> Any:
    if type(value).__name__ == "TypedEffectProposal" and callable(getattr(value, "to_mapping", None)):
        return value.to_mapping()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _material(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _material(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_material(item) for item in value]
    return value


def _validate_event_result_shape(result: EventAdvanceResult) -> None:
    proposal_fields = (
        result.next_event_state_proposal is not None, bool(result.effect_proposals), bool(result.causal_link_proposals),
        bool(result.available_action_semantics), bool(result.pending_gate_proposals), bool(result.projection_fragments),
    )
    if result.status is EventAdvanceStatus.PROPOSED and result.next_event_state_proposal is None:
        raise PortContractError(ProblemCode.OUTPUT_INVALID, "next_event_state_proposal", "推进结果缺少状态提案。")
    if result.status in {EventAdvanceStatus.NO_CHANGE, EventAdvanceStatus.BLOCKED, EventAdvanceStatus.CANCELLED, EventAdvanceStatus.TIMED_OUT} and any(proposal_fields):
        raise PortContractError(ProblemCode.OUTPUT_INVALID, "status_shape", "当前状态不得携带状态、效果、因果、gate、投影或行动提案。")
    if result.status is EventAdvanceStatus.NEEDS_INPUT and any((proposal_fields[0], proposal_fields[1], proposal_fields[2], proposal_fields[5])):
        raise PortContractError(ProblemCode.OUTPUT_INVALID, "status_shape", "needs_input 只能携带待输入 gate 或可用行动。")


def event_snapshot_fingerprint(snapshot: EventStateSnapshot) -> str:
    return canonical_fingerprint(snapshot.fingerprint_material())


def gate_response_fingerprint(response: GateResponseSnapshot) -> str:
    return canonical_fingerprint(response.fingerprint_material())


def validate_gate_response_fingerprint(response: GateResponseSnapshot) -> None:
    if response.response_fingerprint != gate_response_fingerprint(response):
        raise PortContractError(ProblemCode.INPUT_INVALID, "gate_response.response_fingerprint", "gate 回应指纹不匹配。")


def validate_event_snapshot_fingerprint(snapshot: EventStateSnapshot) -> None:
    if snapshot.snapshot_fingerprint != event_snapshot_fingerprint(snapshot):
        raise PortContractError(ProblemCode.INPUT_INVALID, "snapshot_fingerprint", "事件快照指纹不匹配。")


def event_result_fingerprint(result: EventAdvanceResult) -> str:
    return canonical_fingerprint({
        "operation_ref": result.operation_ref, "request_fingerprint": result.request_fingerprint,
        "expected_revision": result.expected_revision, "status": result.status.value,
        "next_event_state_proposal": _material(result.next_event_state_proposal),
        "effect_proposals": _material(result.effect_proposals),
        "causal_link_proposals": _material(result.causal_link_proposals),
        "available_action_semantics": _material(result.available_action_semantics),
        "pending_gate_proposals": _material(result.pending_gate_proposals),
        "projection_fragments": _material(result.projection_fragments),
        "used_receipt_refs": result.used_receipt_refs, "warnings": result.warnings,
        "problems": _material(result.problems),
    })


def validate_event_advance(request: EventAdvanceRequest, result: EventAdvanceResult) -> None:
    _validate_event_result_shape(result)
    if (result.operation_ref, result.request_fingerprint, result.expected_revision) != (request.envelope.operation_ref, request.envelope.request_fingerprint, request.envelope.expected_revision):
        raise PortContractError(ProblemCode.RESULT_STALE, "event_result", "事件结果不属于当前冻结请求。")
    if result.next_event_state_proposal is not None and result.next_event_state_proposal.source_revision != request.event_state.revision:
        raise PortContractError(ProblemCode.RESULT_STALE, "source_revision", "状态提案基于过期事件 revision。")
    effect_refs = {item.proposal_ref for item in result.effect_proposals}
    if len(effect_refs) != len(result.effect_proposals) or len({item.dedupe_key for item in result.effect_proposals}) != len(result.effect_proposals):
        raise PortContractError(ProblemCode.SEMANTIC_VALIDATION_FAILED, "effect_proposals", "effect 引用或去重键重复。")
    for item in result.effect_proposals:
        if isinstance(item, EffectProposal):
            capability = item.capability_ref.rsplit("/", 1)[0]
            if capability in {"actor.resource_pool", "actor.vitality"} or item.effect_type.startswith(("actor.resource", "actor.vitality")):
                raise PortContractError(ProblemCode.SEMANTIC_VALIDATION_FAILED, "effect_proposals", "资源与生命力 effect 必须使用 typed CharacterEffectProposal。")
    if any(
        getattr(item, "capability_ref", getattr(item, "source_capability_ref", None)) not in request.allowed_capability_refs
        for item in result.effect_proposals
    ):
        raise PortContractError(ProblemCode.SEMANTIC_VALIDATION_FAILED, "effect_proposals.capability_ref", "effect 使用了未授权能力。")
    if any(item.effect_proposal_ref not in effect_refs for item in result.causal_link_proposals):
        raise PortContractError(ProblemCode.SEMANTIC_VALIDATION_FAILED, "causal_link_proposals", "因果链接引用了不存在的 effect。")
    if not set(result.used_receipt_refs) <= set(request.committed_receipt_refs):
        raise PortContractError(ProblemCode.SEMANTIC_VALIDATION_FAILED, "used_receipt_refs", "结果引用了未提交回执。")
    expected = event_result_fingerprint(result)
    if result.result_fingerprint != expected: raise PortContractError(ProblemCode.OUTPUT_INVALID, "result_fingerprint", "事件结果指纹不匹配。")


__all__ = ["CausalLinkProposal", "EffectProposal", "EventActivationRequest", "EventAdvanceRequest", "EventAdvanceResult", "EventAdvanceStatus", "EventLifecycleStatus", "EventStateProposal", "EventStateSnapshot", "GateDecision", "GateResponseSnapshot", "PendingGateProposal", "event_result_fingerprint", "event_snapshot_fingerprint", "gate_response_fingerprint", "validate_event_advance", "validate_event_snapshot_fingerprint", "validate_gate_response_fingerprint"]
