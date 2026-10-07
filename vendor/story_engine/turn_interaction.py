"""Versioned turn-interaction authoring, IR, Port, and proposal-only runtime."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol

from .contracts.port import (
    CancellationCheck, PlatformBridge, PortContractError, Problem, ProblemCode,
    OperationEnvelope, canonical_fingerprint, freeze_json,
)

TURN_INTERACTION_POLICY_SCHEMA = "se-turn-interaction-policies/1.0.0"
ROOM_ACTION_POLICY_SCHEMA = 'se-turn-interaction-policies/1.1.0'
TURN_INTERACTION_CAPABILITY = "turn.interaction/1.0.0"
TURN_INTERACTION_SNAPSHOT_SCHEMA = "se-turn-interaction-snapshot/1.0.0"
PLAYER_TURN_INPUT_SCHEMA = "se-player-turn-input/1.0.0"
PLAYER_TURN_REFERENCED_INPUT_SCHEMA = 'se-player-turn-input/1.1.0'
TURN_INTERACTION_REFERENCE_FEATURE = 'turn_interaction.entity_refs/1.0.0'
TURN_INTERACTION_PROPOSAL_SCHEMA = "se-turn-interaction-proposal/1.0.0"
TURN_INTERACTION_RESULT_SCHEMA = "se-turn-interaction-evaluation/1.0.0"

_MODES = frozenset({"choice_only", "dialogue_only", "hybrid"})
_HYBRID_POLICIES = frozenset({"one_of", "choice_with_optional_dialogue"})
_INPUT_CAPABILITIES = frozenset({"choice", "dialogue"})
_META_COMMANDS = frozenset({"help", "cancel", "exit", "absence", "reconnect", "host_control"})
_POLICY_FIELDS = frozenset({"policy_ref", "applicable_profiles", "phases", "locale_text_limits", "accessibility", "fallback", "conformance_cases"})
_PHASE_FIELDS = frozenset({"allowed_modes", "default_mode", "hybrid_submission_policy", "choice_cardinality", "dialogue_constraints", "ambiguity_policy", "transition_targets", "fallback_mode"})


@dataclass(frozen=True, slots=True)
class TurnInteractionContractError(ValueError):
    code: str
    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.code}:{self.path}"


def _fail(code: str, path: str, reason: str) -> None:
    raise TurnInteractionContractError(code, path, reason)


def _text(value: object, path: str, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _fail("interaction.text_invalid", path, "字段必须是有界非空文本。")
    return value.strip()


def _ref(value: object, path: str) -> str:
    result = _text(value, path, 128)
    if not result[0].isalnum() or any(not (char.isalnum() or char in "_.:@-") for char in result):
        _fail("interaction.reference_invalid", path, "字段必须是稳定不透明引用。")
    return result


def _sequence(value: object, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("interaction.sequence_invalid", path, "字段必须是列表。")
    return value


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("interaction.object_invalid", path, "字段必须是对象。")
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(item) for item in value]
    return value


def normalize_attribute_selection_rules(value, path='attribute_selection_rules'):
    rules=_sequence(value,path)
    if len(rules)>32:_fail('interaction.attribute_rules_invalid',path,'属性关联规则过多。')
    result=[];offers=set()
    for index,raw in enumerate(rules):
        item=_mapping(raw,f'{path}[{index}]')
        if set(item)!={'offer_ref','associations','fallback_reason'}:_fail('interaction.attribute_rules_invalid',path,'属性关联规则字段无效。')
        ref=_ref(item['offer_ref'],path+'.offer_ref')
        if ref in offers:_fail('interaction.attribute_rules_invalid',path,'同一候选不得有重复属性关联规则。')
        offers.add(ref);associations=[];priorities=set()
        for association in _sequence(item['associations'],path+'.associations'):
            association=_mapping(association,path+'.association')
            if set(association)!={'attribute_ref','required_source_refs','priority','reason'}:_fail('interaction.attribute_rules_invalid',path,'关联项字段无效。')
            priority=association['priority'];sources=tuple(_ref(r,path+'.required_source_refs') for r in _sequence(association['required_source_refs'],path+'.required_source_refs'))
            if type(priority) is not int or not 0<=priority<=1000 or priority in priorities or not 1<=len(sources)<=8 or len(sources)!=len(set(sources)):_fail('interaction.attribute_rules_invalid',path,'关联优先级或实际来源要求无效。')
            priorities.add(priority);associations.append({'attribute_ref':_ref(association['attribute_ref'],path+'.attribute_ref'),'required_source_refs':list(sources),'priority':priority,'reason':_text(association['reason'],path+'.reason',300)})
        if len(associations)>16:_fail('interaction.attribute_rules_invalid',path,'同一候选的关联项过多。')
        result.append({'offer_ref':ref,'associations':sorted(associations,key=lambda a:a['priority']),'fallback_reason':_text(item['fallback_reason'],path+'.fallback_reason',300)})
    return result

def _phase(value: Mapping[str, Any], path: str, *, room_modes: bool = False) -> dict[str, Any]:
    optional={'attribute_selection_rules'} if room_modes and 'attribute_selection_rules' in value else set()
    if set(value) != _PHASE_FIELDS | ({'room_action_modes'} if room_modes else set()) | optional:
        _fail("interaction.phase_fields_invalid", path, "阶段政策字段不完整或包含未知字段。")
    modes = tuple(str(item) for item in _sequence(value["allowed_modes"], f"{path}.allowed_modes"))
    if not modes or len(modes) != len(set(modes)) or not set(modes) <= _MODES:
        _fail("interaction.mode_invalid", f"{path}.allowed_modes", "allowed_modes 为空、重复或未知。")
    default = str(value["default_mode"])
    if default not in modes:
        _fail("interaction.default_mode_invalid", f"{path}.default_mode", "default_mode 不在 allowed_modes。")
    hybrid_policy = value["hybrid_submission_policy"]
    if "hybrid" in modes:
        if hybrid_policy not in _HYBRID_POLICIES:
            _fail("interaction.hybrid_policy_invalid", f"{path}.hybrid_submission_policy", "hybrid 必须声明精确提交政策。")
    elif hybrid_policy is not None:
        _fail("interaction.hybrid_policy_unexpected", f"{path}.hybrid_submission_policy", "非 hybrid 阶段不得声明 hybrid policy。")
    cardinality = _mapping(value["choice_cardinality"], f"{path}.choice_cardinality")
    if set(cardinality) != {"minimum", "maximum"}:
        _fail("interaction.choice_cardinality_invalid", f"{path}.choice_cardinality", "choice 基数必须冻结 minimum/maximum。")
    minimum, maximum = cardinality["minimum"], cardinality["maximum"]
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in (minimum, maximum)) or maximum < minimum or maximum > 1:
        _fail("interaction.choice_cardinality_invalid", f"{path}.choice_cardinality", "choice 基数无效。")
    if "choice_only" in modes and minimum < 1:
        _fail("interaction.choice_required", f"{path}.choice_cardinality.minimum", "choice_only 必须至少选择一项。")
    dialogue = _mapping(value["dialogue_constraints"], f"{path}.dialogue_constraints")
    if set(dialogue) != {"maximum_characters", "allow_empty", "allow_ooc"}:
        _fail("interaction.dialogue_constraints_invalid", f"{path}.dialogue_constraints", "对话约束字段不完整。")
    maximum_characters = dialogue["maximum_characters"]
    if isinstance(maximum_characters, bool) or not isinstance(maximum_characters, int) or not 1 <= maximum_characters <= 4000 or not isinstance(dialogue["allow_empty"], bool) or not isinstance(dialogue["allow_ooc"], bool):
        _fail("interaction.dialogue_constraints_invalid", f"{path}.dialogue_constraints", "对话长度或布尔约束无效。")
    if dialogue["allow_empty"]:
        _fail("interaction.empty_dialogue_unsupported", f"{path}.dialogue_constraints.allow_empty", "1.0.0 不支持空 dialogue；必须明确为 false。")
    if value["ambiguity_policy"] != "needs_clarification":
        _fail("interaction.ambiguity_policy_invalid", f"{path}.ambiguity_policy", "歧义必须进入 needs_clarification。")
    fallback = value["fallback_mode"]
    if fallback is not None and fallback not in _MODES:
        _fail("interaction.fallback_invalid", f"{path}.fallback_mode", "fallback 必须为空或属于公开模式。")
    if fallback == "choice_only" and minimum < 1:
        _fail("interaction.fallback_choice_unavailable", f"{path}.choice_cardinality.minimum", "choice fallback 必须冻结至少一个必选 choice。")
    transitions = tuple(_ref(item, f"{path}.transition_targets") for item in _sequence(value["transition_targets"], f"{path}.transition_targets"))
    if not transitions or len(transitions) != len(set(transitions)):
        _fail("interaction.transition_invalid", f"{path}.transition_targets", "transition_targets 必须非空且不重复。")
    result = {
        "allowed_modes": list(modes), "default_mode": default, "hybrid_submission_policy": hybrid_policy,
        "choice_cardinality": {"minimum": minimum, "maximum": maximum},
        "dialogue_constraints": {"maximum_characters": maximum_characters, "allow_empty": dialogue["allow_empty"], "allow_ooc": dialogue["allow_ooc"]},
        "ambiguity_policy": "needs_clarification", "transition_targets": list(transitions), "fallback_mode": fallback,
    }
    if room_modes:
        control=_mapping(value['room_action_modes'],path+'.room_action_modes')
        if set(control)!={'allowed_modes','hybrid_strategies','critical','formal_confirmation','reason'}:
            _fail('interaction.room_modes_invalid',path+'.room_action_modes','房间推进方式须有精确的节点边界。')
        allowed=_sequence(control['allowed_modes'],path+'.room_action_modes.allowed_modes')
        strategies=_sequence(control['hybrid_strategies'],path+'.room_action_modes.hybrid_strategies')
        if any(not isinstance(v,str) for v in allowed) or not allowed or len(allowed)!=len(set(allowed)) or not set(allowed)<=_MODES or any(not isinstance(v,str) for v in strategies) or len(strategies)!=len(set(strategies)) or not set(strategies)<={'one_of','critical_choices'} or ('hybrid' in allowed)!=bool(strategies) or type(control['critical']) is not bool or type(control['formal_confirmation']) is not bool or control['formal_confirmation'] and not control['critical']:
            _fail('interaction.room_modes_invalid',path+'.room_action_modes','模式、混合策略或关键节点边界无效。')
        result['room_action_modes']={**_plain(control),'reason':_text(control['reason'],path+'.room_action_modes.reason',600)}
    if optional:result['attribute_selection_rules']=normalize_attribute_selection_rules(value['attribute_selection_rules'],path+'.attribute_selection_rules')
    return result


def compile_turn_interaction_policies(document: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the standalone Story Pack policy document without I/O."""
    if set(document) != {"schema", "policies"} or not isinstance(document.get('schema'),str) or document.get("schema") not in {TURN_INTERACTION_POLICY_SCHEMA,ROOM_ACTION_POLICY_SCHEMA}:
        _fail("interaction.document_incompatible", "$", "交互政策文档版本或字段不兼容。")
    policies: list[dict[str, Any]] = []
    seen: set[str] = set()
    room_modes=document['schema']==ROOM_ACTION_POLICY_SCHEMA
    for index, raw in enumerate(_sequence(document["policies"], "policies")):
        value = _mapping(raw, f"policies[{index}]")
        if set(value) != _POLICY_FIELDS:
            _fail("interaction.policy_fields_invalid", f"policies[{index}]", "政策字段不完整或包含未知字段。")
        policy_ref = _ref(value["policy_ref"], f"policies[{index}].policy_ref")
        if policy_ref in seen:
            _fail("interaction.policy_duplicate", f"policies[{index}].policy_ref", "policy_ref 重复。")
        seen.add(policy_ref)
        profiles = tuple(_ref(item, f"policies[{index}].applicable_profiles") for item in _sequence(value["applicable_profiles"], f"policies[{index}].applicable_profiles"))
        if not profiles or len(profiles) != len(set(profiles)) or any("@" not in item for item in profiles):
            _fail("interaction.profile_binding_invalid", f"policies[{index}].applicable_profiles", "适用 Profile 必须使用不重复的 profile@version。")
        phases_raw = _mapping(value["phases"], f"policies[{index}].phases")
        if not phases_raw:
            _fail("interaction.phases_empty", f"policies[{index}].phases", "政策必须包含阶段。")
        phases = {_ref(key, f"policies[{index}].phases"): _phase(_mapping(item, f"policies[{index}].phases.{key}"), f"policies[{index}].phases.{key}",room_modes=room_modes) for key, item in sorted(phases_raw.items())}
        for phase_ref, phase in phases.items():
            unknown = set(phase["transition_targets"]) - set(phases) - {"complete", "wait"}
            if unknown:
                _fail("interaction.transition_unknown", f"policies[{index}].phases.{phase_ref}.transition_targets", "模式转换引用未知阶段。")
        locale_limits = _mapping(value["locale_text_limits"], f"policies[{index}].locale_text_limits")
        if not locale_limits or any(isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= 4000 for item in locale_limits.values()):
            _fail("interaction.locale_limits_invalid", f"policies[{index}].locale_text_limits", "locale 文本上限无效。")
        accessibility = _mapping(value["accessibility"], f"policies[{index}].accessibility")
        fallback = _mapping(value["fallback"], f"policies[{index}].fallback")
        reserved = fallback.get("reserved_meta_commands")
        if not isinstance(reserved, Sequence) or isinstance(reserved, (str, bytes, bytearray)) or not reserved:
            _fail("interaction.reserved_commands_missing", f"policies[{index}].fallback.reserved_meta_commands", "政策必须冻结多语言平台保留命令。")
        normalized_reserved = tuple(_text(item, f"policies[{index}].fallback.reserved_meta_commands", 80).casefold() for item in reserved)
        if len(normalized_reserved) != len(set(normalized_reserved)):
            _fail("interaction.reserved_commands_invalid", f"policies[{index}].fallback.reserved_meta_commands", "平台保留命令不能重复。")
        fallback = {**_plain(fallback), "reserved_meta_commands": list(normalized_reserved)}
        cases = tuple(_ref(item, f"policies[{index}].conformance_cases") for item in _sequence(value["conformance_cases"], f"policies[{index}].conformance_cases"))
        material = {
            "schema": "se-turn-interaction-policy-ir/1.1.0" if room_modes else "se-turn-interaction-policy-ir/1.0.0", "policy_ref": policy_ref,
            "applicable_profiles": list(profiles), "phases": phases,
            "locale_text_limits": _plain(locale_limits), "accessibility": _plain(accessibility),
            "fallback": fallback, "conformance_cases": list(cases),
        }
        material["policy_sha256"] = canonical_fingerprint(material)
        policies.append(material)
    result = {"schema": "se-turn-interaction-policy-catalog-ir/1.1.0" if room_modes else "se-turn-interaction-policy-catalog-ir/1.0.0", "policies": sorted(policies, key=lambda item: item["policy_ref"])}
    result["catalog_sha256"] = canonical_fingerprint(result)
    return result


def bind_turn_interaction_policy(extension: Mapping[str, Any], catalog: Mapping[str, Any], graph: Mapping[str, Any], profile: str, version: str) -> dict[str, Any]:
    if set(extension) != {"policy_ref"}:
        _fail("interaction.extension_invalid", "extensions.turn.interaction/1.0.0", "扩展必须且只能包含 policy_ref。")
    policy_ref = _ref(extension["policy_ref"], "extensions.turn.interaction/1.0.0.policy_ref")
    policy = next((item for item in catalog["policies"] if item["policy_ref"] == policy_ref), None)
    if policy is None:
        _fail("interaction.policy_unknown", "extensions.turn.interaction/1.0.0.policy_ref", "事件引用了未知交互政策。")
    if f"{profile}@{version}" not in policy["applicable_profiles"]:
        _fail("interaction.policy_profile_mismatch", "extensions.turn.interaction/1.0.0.policy_ref", "政策不适用于当前精确 Profile。")
    nodes = {str(item["id"]): item for item in graph["nodes"]}
    outgoing = {node: [edge for edge in graph["edges"] if edge["from"] == node] for node in nodes}
    player_phases = {node for node, edges in outgoing.items() if edges}
    if not player_phases <= set(policy["phases"]):
        _fail("interaction.phase_policy_missing", "turn_interaction.phases", "有玩家输入的检查点缺少交互政策。")
    for phase_ref in player_phases:
        phase = policy["phases"][phase_ref]
        route_count = len(outgoing[phase_ref])
        if set(phase["allowed_modes"]) & {"choice_only", "hybrid"}:
            cardinality = phase["choice_cardinality"]
            if not cardinality["minimum"] <= route_count or route_count < 1:
                _fail("interaction.choice_dead_end", f"turn_interaction.phases.{phase_ref}", "choice/hybrid 阶段缺少合法路线。")
        graph_targets = {
            "complete" if nodes[str(edge["to"])].get("exit_kind") else str(edge["to"])
            for edge in outgoing[phase_ref]
        }
        declared = set(phase["transition_targets"])
        if not graph_targets <= declared | {"complete", "wait"}:
            _fail("interaction.transition_graph_mismatch", f"turn_interaction.phases.{phase_ref}.transition_targets", "政策转换与检查点图不一致。")
    graph_transitions = {
        phase_ref: sorted({
            "complete" if nodes[str(edge["to"])].get("exit_kind") else str(edge["to"])
            for edge in outgoing[phase_ref]
        })
        for phase_ref in sorted(player_phases)
    }
    return {
        "schema": "se-turn-interaction-binding-ir/1.0.0", "policy_ref": policy_ref,
        "policy_sha256": policy["policy_sha256"], "phases": policy["phases"],
        "graph_transition_targets": graph_transitions,
    }


@dataclass(frozen=True, slots=True)
class ChoiceSemantics:
    choice_ref: str
    label: str
    purpose: str
    cost: str
    risk: str
    limitations: str
    next_phase_ref: str
    allow_optional_dialogue: bool = False

    def __post_init__(self) -> None:
        for name in ("choice_ref",):
            _ref(getattr(self, name), name)
        _ref(self.next_phase_ref, "next_phase_ref")
        for name in ("label", "purpose", "cost", "risk", "limitations"):
            _text(getattr(self, name), name, 400)

    def to_mapping(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class DialogueIntent:
    intent_ref: str
    accepted_utterances: tuple[str, ...]
    next_phase_ref: str

    def __post_init__(self) -> None:
        _ref(self.intent_ref, "intent_ref")
        _ref(self.next_phase_ref, "next_phase_ref")
        if not self.accepted_utterances:
            raise PortContractError(ProblemCode.INPUT_INVALID, "dialogue_intents", "合法对话意图不能为空。")
        normalized = tuple(_text(item, "accepted_utterances", 400) for item in self.accepted_utterances)
        if len({item.casefold() for item in normalized}) != len(normalized):
            raise PortContractError(ProblemCode.INPUT_INVALID, "accepted_utterances", "对话匹配文本不能重复。")
        object.__setattr__(self, "accepted_utterances", normalized)

    def to_mapping(self) -> dict[str, Any]:
        return {"intent_ref": self.intent_ref, "accepted_utterances": list(self.accepted_utterances), "next_phase_ref": self.next_phase_ref}


@dataclass(frozen=True, slots=True)
class TurnInteractionSnapshot:
    schema: str
    interaction_revision: int
    policy_ref: str
    policy_sha256: str
    phase_ref: str
    mode: str
    hybrid_submission_policy: str | None
    choices: tuple[ChoiceSemantics, ...]
    choice_minimum: int
    choice_maximum: int
    dialogue_maximum_characters: int
    allow_empty_dialogue: bool
    allow_ooc: bool
    ambiguity_policy: str
    fallback_mode: str | None
    dialogue_intents: tuple[DialogueIntent, ...]
    available_input_capabilities: tuple[str, ...]
    actor_ref: str
    control_lease_ref: str
    action_roster_revision: int
    expected_session_revision: int
    fingerprint: str

    def __post_init__(self) -> None:
        if self.schema != TURN_INTERACTION_SNAPSHOT_SCHEMA or self.mode not in _MODES or self.ambiguity_policy != "needs_clarification":
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "turn_interaction", "交互快照版本、模式或歧义政策不兼容。")
        for name in ("policy_ref", "phase_ref", "actor_ref", "control_lease_ref"):
            _ref(getattr(self, name), name)
        for name in ("policy_sha256", "fingerprint"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
                raise PortContractError(ProblemCode.INPUT_INVALID, name, "指纹无效。")
        revisions = (self.interaction_revision, self.action_roster_revision, self.expected_session_revision)
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in revisions):
            raise PortContractError(ProblemCode.INPUT_INVALID, "revision", "交互 revision 无效。")
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in (self.choice_minimum, self.choice_maximum, self.dialogue_maximum_characters)) or self.choice_maximum < self.choice_minimum:
            raise PortContractError(ProblemCode.INPUT_INVALID, "constraints", "交互输入约束无效。")
        capabilities = tuple(sorted(set(self.available_input_capabilities)))
        if set(capabilities) - _INPUT_CAPABILITIES or len(capabilities) != len(self.available_input_capabilities):
            raise PortContractError(ProblemCode.INPUT_INVALID, "available_input_capabilities", "输入能力未知或重复。")
        object.__setattr__(self, "available_input_capabilities", capabilities)
        choice_refs = [item.choice_ref for item in self.choices]
        intent_refs = [item.intent_ref for item in self.dialogue_intents]
        if len(choice_refs) != len(set(choice_refs)) or len(intent_refs) != len(set(intent_refs)):
            raise PortContractError(ProblemCode.INPUT_INVALID, "turn_interaction_snapshot.roster", "choice 或 intent ref 不能重复。")
        if self.choice_maximum > 1 or self.allow_empty_dialogue:
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "turn_interaction_snapshot.constraints", "1.0.0 只支持单 choice 且不支持空 dialogue。")
        if self.mode == "hybrid" and self.hybrid_submission_policy not in _HYBRID_POLICIES:
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "hybrid_submission_policy", "hybrid snapshot 缺少精确提交政策。")

    def fingerprint_material(self) -> Mapping[str, Any]:
        return {key: value for key, value in self.to_mapping().items() if key != "fingerprint"}

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "interaction_revision": self.interaction_revision, "policy_ref": self.policy_ref,
            "policy_sha256": self.policy_sha256, "phase_ref": self.phase_ref, "mode": self.mode,
            "hybrid_submission_policy": self.hybrid_submission_policy, "choices": [item.to_mapping() for item in self.choices],
            "choice_cardinality": {"minimum": self.choice_minimum, "maximum": self.choice_maximum},
            "dialogue_constraints": {"maximum_characters": self.dialogue_maximum_characters, "allow_empty": self.allow_empty_dialogue, "allow_ooc": self.allow_ooc},
            "ambiguity_policy": self.ambiguity_policy, "fallback_mode": self.fallback_mode,
            "dialogue_intents": [item.to_mapping() for item in self.dialogue_intents],
            "available_input_capabilities": list(self.available_input_capabilities), "actor_ref": self.actor_ref,
            "control_lease_ref": self.control_lease_ref, "action_roster_revision": self.action_roster_revision,
            "expected_session_revision": self.expected_session_revision, "fingerprint": self.fingerprint,
        }


def turn_interaction_snapshot_fingerprint(snapshot: TurnInteractionSnapshot) -> str:
    return canonical_fingerprint(snapshot.fingerprint_material())


def decode_turn_interaction_snapshot(value: Mapping[str, Any]) -> TurnInteractionSnapshot:
    required = {
        "schema", "interaction_revision", "policy_ref", "policy_sha256", "phase_ref", "mode",
        "hybrid_submission_policy", "choices", "choice_cardinality", "dialogue_constraints",
        "ambiguity_policy", "fallback_mode", "dialogue_intents", "available_input_capabilities",
        "actor_ref", "control_lease_ref", "action_roster_revision", "expected_session_revision", "fingerprint",
    }
    if set(value) != required:
        raise PortContractError(ProblemCode.INPUT_INVALID, "turn_interaction_snapshot", "交互快照字段不完整或包含未知字段。")
    cardinality, dialogue = value["choice_cardinality"], value["dialogue_constraints"]
    if not isinstance(cardinality, Mapping) or set(cardinality) != {"minimum", "maximum"} or not isinstance(dialogue, Mapping) or set(dialogue) != {"maximum_characters", "allow_empty", "allow_ooc"}:
        raise PortContractError(ProblemCode.INPUT_INVALID, "turn_interaction_snapshot.constraints", "交互约束字段无效。")
    choice_fields = {"choice_ref", "label", "purpose", "cost", "risk", "limitations", "next_phase_ref", "allow_optional_dialogue"}
    choices = tuple(ChoiceSemantics(**item) for item in value["choices"] if isinstance(item, Mapping) and set(item) == choice_fields)
    intents = tuple(DialogueIntent(str(item["intent_ref"]), tuple(item["accepted_utterances"]), str(item["next_phase_ref"])) for item in value["dialogue_intents"] if isinstance(item, Mapping) and set(item) == {"intent_ref", "accepted_utterances", "next_phase_ref"})
    if len(choices) != len(value["choices"]) or len(intents) != len(value["dialogue_intents"]):
        raise PortContractError(ProblemCode.INPUT_INVALID, "turn_interaction_snapshot.roster", "choice 或 dialogue intent roster 无效。")
    return TurnInteractionSnapshot(
        str(value["schema"]), value["interaction_revision"], str(value["policy_ref"]), str(value["policy_sha256"]),
        str(value["phase_ref"]), str(value["mode"]), value["hybrid_submission_policy"], choices,
        cardinality["minimum"], cardinality["maximum"], dialogue["maximum_characters"], dialogue["allow_empty"], dialogue["allow_ooc"],
        str(value["ambiguity_policy"]), value["fallback_mode"], intents, tuple(value["available_input_capabilities"]),
        str(value["actor_ref"]), str(value["control_lease_ref"]), value["action_roster_revision"], value["expected_session_revision"], str(value["fingerprint"]),
    )


@dataclass(frozen=True, slots=True)
class PlayerTurnInput:
    schema: str
    kind: str
    expected_interaction_revision: int
    choice_ref: str | None = None
    utterance: str | None = None
    locale: str | None = None
    client_input_ref: str | None = None

    def __post_init__(self) -> None:
        expected_schema=PLAYER_TURN_REFERENCED_INPUT_SCHEMA if isinstance(self,ReferencedPlayerTurnInput) else PLAYER_TURN_INPUT_SCHEMA
        if self.schema != expected_schema or self.kind not in {"choice", "dialogue", "hybrid"}:
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "player_input", "玩家输入版本或 kind 不兼容。")
        if type(self.expected_interaction_revision) is not int or self.expected_interaction_revision < 0:
            raise PortContractError(ProblemCode.INPUT_INVALID, "expected_interaction_revision", "交互 revision 无效。")
        if self.choice_ref is not None:
            _ref(self.choice_ref, "choice_ref")
        if self.utterance is not None:
            _text(self.utterance, "utterance", 4000)
        if self.locale is not None:
            _ref(self.locale, "locale")
        if self.client_input_ref is not None:
            _ref(self.client_input_ref, "client_input_ref")
        if self.kind == "choice" and (self.choice_ref is None or self.utterance is not None):
            raise PortContractError(ProblemCode.INPUT_INVALID, "player_input", "choice 输入必须只含 choice_ref。")
        if self.kind == "dialogue" and (self.utterance is None or self.choice_ref is not None):
            raise PortContractError(ProblemCode.INPUT_INVALID, "player_input", "dialogue 输入必须只含 utterance。")
        if self.kind == "hybrid" and self.choice_ref is None:
            raise PortContractError(ProblemCode.INPUT_INVALID, "player_input", "hybrid 输入必须包含 choice_ref。")

    def semantic_material(self) -> Mapping[str, Any]:
        return {"schema": self.schema, "kind": self.kind, "expected_interaction_revision": self.expected_interaction_revision, "choice_ref": self.choice_ref, "utterance": self.utterance, "locale": self.locale}


@dataclass(frozen=True,slots=True)
class PlayerActionReference:
    entity_ref: str
    kind: str
    label: str
    description: str
    source_receipt_refs: tuple[str,...]
    start: int
    end: int

    def to_mapping(self):
        return {'entity_ref':self.entity_ref,'kind':self.kind,'label':self.label,'description':self.description,'source_receipt_refs':list(self.source_receipt_refs),'start':self.start,'end':self.end}


@dataclass(frozen=True,slots=True)
class ReferencedPlayerTurnInput(PlayerTurnInput):
    references: tuple[PlayerActionReference,...] = ()

    def __post_init__(self):
        PlayerTurnInput.__post_init__(self)
        from .action_references import validate
        if not isinstance(self.references,(tuple,list)):
            raise PortContractError(ProblemCode.INPUT_INVALID,'player_input.references','引用必须是有界列表。')
        raw=[ref.to_mapping() if isinstance(ref,PlayerActionReference) else _plain(ref) for ref in self.references]
        if raw and self.utterance is None:
            raise PortContractError(ProblemCode.INPUT_INVALID,'player_input.references','引用必须属于本人提交的对白。')
        try:
            values=validate(self.utterance or '',raw)
            if canonical_fingerprint(values)!=canonical_fingerprint(raw):raise ValueError('reference context exceeds budget')
        except (TypeError,KeyError,ValueError) as exc:
            raise PortContractError(ProblemCode.INPUT_INVALID,'player_input.references','引用范围、称谓、来源或上下文预算无效。') from exc
        object.__setattr__(self,'references',tuple(PlayerActionReference(**{**ref,'source_receipt_refs':tuple(ref['source_receipt_refs'])}) for ref in values))

    def semantic_material(self):
        return {**PlayerTurnInput.semantic_material(self),'references':[ref.to_mapping() for ref in self.references]}


def decode_player_turn_input(value: Mapping[str, Any]) -> PlayerTurnInput:
    allowed = {"schema", "kind", "expected_interaction_revision", "choice_ref", "utterance", "locale", "client_input_ref"}
    required = {"schema", "kind", "expected_interaction_revision"}
    referenced=value.get('schema')==PLAYER_TURN_REFERENCED_INPUT_SCHEMA
    if referenced:allowed.add('references');required.add('references')
    if not required <= set(value) or set(value) - allowed:
        raise PortContractError(ProblemCode.INPUT_INVALID, "player_input", "玩家输入字段缺失或包含未知字段。")
    cls=ReferencedPlayerTurnInput if referenced else PlayerTurnInput
    return cls(
        str(value["schema"]), str(value["kind"]), value["expected_interaction_revision"],
        value.get("choice_ref"), value.get("utterance"), value.get("locale"), value.get("client_input_ref"),
        **({'references':value['references']} if referenced else {}),
    )


class TurnInteractionProposalKind(StrEnum):
    ADVANCE = "advance"
    CLARIFICATION = "clarification"
    WAIT = "wait"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class TurnInteractionProposal:
    schema: str
    proposal_ref: str
    operation_ref: str
    kind: TurnInteractionProposalKind
    consumed_input_digest: str
    source_interaction_revision: int
    selected_choice_ref: str | None = None
    resolved_intent_ref: str | None = None
    next_phase_ref: str | None = None
    next_mode: str | None = None
    clarification_question: str | None = None
    clarification_candidates: tuple[str, ...] = ()
    choice_semantics: tuple[ChoiceSemantics, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema != TURN_INTERACTION_PROPOSAL_SCHEMA:
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "proposal.schema", "交互提案版本不兼容。")
        _ref(self.proposal_ref, "proposal_ref"); _ref(self.operation_ref, "operation_ref")
        if self.kind is TurnInteractionProposalKind.CLARIFICATION:
            if not self.clarification_question or self.selected_choice_ref is not None or self.resolved_intent_ref is not None:
                raise PortContractError(ProblemCode.OUTPUT_INVALID, "clarification", "澄清提案形状无效。")
        if self.kind is TurnInteractionProposalKind.ADVANCE and (self.selected_choice_ref is None) == (self.resolved_intent_ref is None):
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "advance", "推进提案必须且只能绑定一个机械意图。")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "proposal_ref": self.proposal_ref, "operation_ref": self.operation_ref,
            "kind": self.kind.value, "consumed_input_digest": self.consumed_input_digest,
            "source_interaction_revision": self.source_interaction_revision, "selected_choice_ref": self.selected_choice_ref,
            "resolved_intent_ref": self.resolved_intent_ref, "next_phase_ref": self.next_phase_ref,
            "next_mode": self.next_mode, "clarification_question": self.clarification_question,
            "clarification_candidates": list(self.clarification_candidates),
            "choice_semantics": [item.to_mapping() for item in self.choice_semantics], "warnings": list(self.warnings),
        }


class TurnInteractionResultStatus(StrEnum):
    PROPOSED = "proposed"
    NEEDS_CLARIFICATION = "needs_clarification"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class TurnInteractionEvaluationRequest:
    envelope: OperationEnvelope
    snapshot: TurnInteractionSnapshot
    player_input: PlayerTurnInput

    def __post_init__(self) -> None:
        if self.envelope.operation_type != "evaluate_turn_interaction":
            raise PortContractError(ProblemCode.INPUT_INVALID, "operation_type", "交互操作类型无效。")
        if self.envelope.expected_revision != self.snapshot.expected_session_revision:
            raise PortContractError(ProblemCode.RESULT_STALE, "expected_revision", "session revision 已过期。")


def turn_interaction_request_fingerprint(request: TurnInteractionEvaluationRequest) -> str:
    return canonical_fingerprint({
        "operation_ref": request.envelope.operation_ref,
        "snapshot_fingerprint": request.snapshot.fingerprint,
        "player_input": request.player_input.semantic_material(),
    })


@dataclass(frozen=True, slots=True)
class TurnInteractionEvaluationResult:
    schema: str
    operation_ref: str
    request_fingerprint: str
    expected_revision: int
    status: TurnInteractionResultStatus
    effective_mode: str
    proposal: TurnInteractionProposal | None = None
    warnings: tuple[str, ...] = ()
    problems: tuple[Problem, ...] = ()
    result_fingerprint: str = "sha256:" + "0" * 64

    def __post_init__(self) -> None:
        if self.schema != TURN_INTERACTION_RESULT_SCHEMA:
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "result.schema", "交互结果版本不兼容。")
        if self.status in {TurnInteractionResultStatus.PROPOSED, TurnInteractionResultStatus.NEEDS_CLARIFICATION} and self.proposal is None:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "result.proposal", "成功或澄清结果必须包含一个提案。")
        if self.status in {TurnInteractionResultStatus.BLOCKED, TurnInteractionResultStatus.CANCELLED, TurnInteractionResultStatus.TIMED_OUT} and self.proposal is not None:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "result.proposal", "失败结果不得携带可提交提案。")


def turn_interaction_result_fingerprint(result: TurnInteractionEvaluationResult) -> str:
    value = {
        "schema": result.schema, "operation_ref": result.operation_ref, "request_fingerprint": result.request_fingerprint,
        "expected_revision": result.expected_revision, "status": result.status.value, "effective_mode": result.effective_mode,
        "proposal": None if result.proposal is None else result.proposal.to_mapping(),
        "warnings": list(result.warnings), "problems": [problem.code.value for problem in result.problems],
    }
    return canonical_fingerprint(value)


class TurnInteractionEvaluator:
    def __init__(self, artifact: Mapping[str, Any]) -> None:
        catalog = artifact.get("turn_interaction_policies")
        if not isinstance(catalog, Mapping) or catalog.get("schema") not in {"se-turn-interaction-policy-catalog-ir/1.0.0","se-turn-interaction-policy-catalog-ir/1.1.0"}:
            raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "turn_interaction_policies", "Artifact 缺少交互政策目录。")
        if catalog.get("catalog_sha256") != canonical_fingerprint({key: item for key, item in catalog.items() if key != "catalog_sha256"}):
            raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "turn_interaction_policies.catalog_sha256", "交互政策目录指纹不匹配。")
        for item in catalog["policies"]:
            expected = canonical_fingerprint({key: value for key, value in item.items() if key != "policy_sha256"})
            if item.get("policy_sha256") != expected:
                raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "turn_interaction_policies.policy_sha256", "交互政策指纹不匹配。")
        self._policies = MappingProxyType({str(item["policy_ref"]): freeze_json(item, "turn_interaction_policy") for item in catalog["policies"]})
        bindings: dict[tuple[str, str], tuple[str, ...]] = {}
        for event in artifact.get("event_compositions", ()):
            binding = event.get("turn_interaction") if isinstance(event, Mapping) else None
            if not isinstance(binding, Mapping):
                continue
            policy_ref = str(binding.get("policy_ref") or "")
            policy = self._policies.get(policy_ref)
            if policy is None or binding.get("policy_sha256") != policy["policy_sha256"]:
                raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "event.turn_interaction", "事件交互 binding 与政策目录不一致。")
            graph_targets = binding.get("graph_transition_targets")
            if not isinstance(graph_targets, Mapping):
                raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "event.turn_interaction.graph_transition_targets", "事件交互 binding 缺少真实图目标。")
            graph = event.get("checkpoint_graph")
            if not isinstance(graph, Mapping):
                raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "event.checkpoint_graph", "交互事件缺少检查点图。")
            nodes = {str(item["id"]): item for item in graph.get("nodes", ())}
            actual_targets: dict[str, list[str]] = {}
            for edge in graph.get("edges", ()):
                source, target = str(edge["from"]), str(edge["to"])
                actual_targets.setdefault(source, []).append("complete" if nodes[target].get("exit_kind") else target)
            actual_targets = {key: sorted(set(value)) for key, value in actual_targets.items()}
            if _plain(graph_targets) != actual_targets:
                raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "event.turn_interaction.graph_transition_targets", "交互 binding 目标与 Artifact 检查点图不一致。")
            for phase_ref, targets in graph_targets.items():
                key = (policy_ref, str(phase_ref))
                value = tuple(sorted(str(item) for item in targets))
                if key in bindings and bindings[key] != value:
                    raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "event.turn_interaction.graph_transition_targets", "同一政策阶段绑定到不同机械图。")
                bindings[key] = value
        self._bindings = MappingProxyType(bindings)

    def evaluate(self, request: TurnInteractionEvaluationRequest) -> TurnInteractionEvaluationResult:
        snapshot, player_input = request.snapshot, request.player_input
        operation = request.envelope.operation_ref
        if request.envelope.request_fingerprint != turn_interaction_request_fingerprint(request):
            return self._blocked(request, snapshot.mode, ProblemCode.RESULT_STALE, "玩家输入 request fingerprint 不匹配。")
        if snapshot.fingerprint != turn_interaction_snapshot_fingerprint(snapshot):
            return self._blocked(request, snapshot.mode, ProblemCode.RESULT_STALE, "交互快照指纹不匹配。")
        policy = self._policies.get(snapshot.policy_ref)
        if policy is None or policy["policy_sha256"] != snapshot.policy_sha256 or snapshot.phase_ref not in policy["phases"]:
            return self._blocked(request, snapshot.mode, ProblemCode.CONTRACT_INCOMPATIBLE, "交互快照没有绑定 Artifact 精确政策。")
        phase = policy["phases"][snapshot.phase_ref]
        if snapshot.mode not in phase["allowed_modes"] or snapshot.hybrid_submission_policy != phase["hybrid_submission_policy"]:
            return self._blocked(request, snapshot.mode, ProblemCode.CONTRACT_INCOMPATIBLE, "交互模式或 hybrid 政策与 Artifact 不一致。")
        if (
            {"minimum": snapshot.choice_minimum, "maximum": snapshot.choice_maximum} != phase["choice_cardinality"]
            or {"maximum_characters": snapshot.dialogue_maximum_characters, "allow_empty": snapshot.allow_empty_dialogue, "allow_ooc": snapshot.allow_ooc} != phase["dialogue_constraints"]
            or snapshot.fallback_mode != phase["fallback_mode"]
        ):
            return self._blocked(request, snapshot.mode, ProblemCode.CONTRACT_INCOMPATIBLE, "交互约束或 fallback 与 Artifact 不一致。")
        if len(snapshot.choices) < snapshot.choice_minimum:
            return self._blocked(request, snapshot.mode, ProblemCode.CONTRACT_INCOMPATIBLE, "冻结 choice roster 不能满足政策基数。")
        if snapshot.mode == "choice_only" and "choice" not in snapshot.available_input_capabilities:
            return self._blocked(request, snapshot.mode, ProblemCode.CONTRACT_INCOMPATIBLE, "目标表面缺少 required choice 输入能力。")
        if (snapshot.mode == "dialogue_only" or (snapshot.mode == "hybrid" and snapshot.hybrid_submission_policy == "one_of")) and "dialogue" in snapshot.available_input_capabilities and not snapshot.dialogue_intents:
            return self._blocked(request, snapshot.mode, ProblemCode.CONTRACT_INCOMPATIBLE, "dialogue 模式缺少冻结合法意图 roster。")
        graph_targets = self._bindings.get((snapshot.policy_ref, snapshot.phase_ref))
        if graph_targets is None:
            return self._blocked(request, snapshot.mode, ProblemCode.CONTRACT_INCOMPATIBLE, "交互政策阶段没有 Artifact 机械图 binding。")
        roster_targets = {item.next_phase_ref for item in snapshot.choices} | {item.next_phase_ref for item in snapshot.dialogue_intents}
        if not roster_targets <= set(graph_targets):
            return self._blocked(request, snapshot.mode, ProblemCode.CONTRACT_INCOMPATIBLE, "choice/dialogue target 不属于当前阶段 Artifact 图。")
        if player_input.expected_interaction_revision != snapshot.interaction_revision:
            return self._blocked(request, snapshot.mode, ProblemCode.RESULT_STALE, "玩家输入基于过期 interaction revision。")
        meta_value = (player_input.choice_ref or player_input.utterance or "").strip().casefold()
        reserved = set(_META_COMMANDS) | {str(item).casefold() for item in policy["fallback"]["reserved_meta_commands"]}
        if meta_value.startswith("/") or meta_value in reserved:
            return self._blocked(request, snapshot.mode, ProblemCode.INPUT_INVALID, "平台元命令不得作为故事内 PlayerTurnInput 进入 Engine。")
        effective_mode = snapshot.mode
        needs_dialogue = effective_mode == "dialogue_only" or effective_mode == "hybrid"
        if needs_dialogue and "dialogue" not in snapshot.available_input_capabilities:
            fallback = phase["fallback_mode"]
            if fallback != "choice_only" or phase["choice_cardinality"]["minimum"] < 1 or snapshot.choice_minimum < 1 or "choice" not in snapshot.available_input_capabilities or not snapshot.choices:
                return self._blocked(request, effective_mode, ProblemCode.CONTRACT_INCOMPATIBLE, "目标表面无法安全表达 required 交互，也没有声明式 fallback。")
            effective_mode = "choice_only"
        if effective_mode == "choice_only" and player_input.kind != "choice":
            return self._blocked(request, effective_mode, ProblemCode.INPUT_INVALID, "choice_only 只接受 choice 输入。")
        if effective_mode == "dialogue_only" and player_input.kind != "dialogue":
            return self._blocked(request, effective_mode, ProblemCode.INPUT_INVALID, "dialogue_only 只接受 dialogue 输入。")
        if effective_mode == "hybrid":
            policy_name = snapshot.hybrid_submission_policy
            if policy_name == "one_of" and player_input.kind not in {"choice", "dialogue"}:
                return self._blocked(request, effective_mode, ProblemCode.INPUT_INVALID, "hybrid/one_of 禁止双重输入。")
            if policy_name == "choice_with_optional_dialogue" and player_input.kind != "hybrid":
                return self._blocked(request, effective_mode, ProblemCode.INPUT_INVALID, "当前 hybrid 必须提交一个 choice 和可选 dialogue。")
        if player_input.utterance is not None:
            if len(player_input.utterance) > snapshot.dialogue_maximum_characters or (not snapshot.allow_ooc and player_input.utterance.startswith("[OOC]")):
                return self._blocked(request, effective_mode, ProblemCode.INPUT_INVALID, "自由文本超过约束或 OOC 不被允许。")
        choice = next((item for item in snapshot.choices if item.choice_ref == player_input.choice_ref), None)
        if player_input.choice_ref is not None and choice is None:
            return self._blocked(request, effective_mode, ProblemCode.RESULT_STALE, "choice 不在当前冻结 roster。")
        if player_input.kind == "hybrid" and choice is not None and not choice.allow_optional_dialogue:
            return self._blocked(request, effective_mode, ProblemCode.INPUT_INVALID, "所选动作不允许附加 dialogue。")
        intent_ref = None
        next_phase_ref = choice.next_phase_ref if choice is not None else None
        if player_input.kind == "dialogue":
            matches = [item for item in snapshot.dialogue_intents if player_input.utterance.casefold() in {text.casefold() for text in item.accepted_utterances}]
            if len(matches) != 1:
                return self._clarification(request, effective_mode, tuple(sorted([item.intent_ref for item in matches] or [item.intent_ref for item in snapshot.dialogue_intents])))
            intent_ref = matches[0].intent_ref
            next_phase_ref = matches[0].next_phase_ref
        next_mode = policy["phases"][next_phase_ref]["default_mode"] if next_phase_ref in policy["phases"] else None
        digest = canonical_fingerprint(player_input.semantic_material())
        stable = canonical_fingerprint({"operation_ref": operation, "input": digest})[7:39]
        proposal = TurnInteractionProposal(
            TURN_INTERACTION_PROPOSAL_SCHEMA, f"interaction.{stable}", operation, TurnInteractionProposalKind.ADVANCE,
            digest, snapshot.interaction_revision, choice.choice_ref if choice is not None else None, intent_ref,
            next_phase_ref, next_mode, None, (), (), ("fallback_applied:choice_only",) if effective_mode != snapshot.mode else (),
        )
        return self._final(TurnInteractionEvaluationResult(TURN_INTERACTION_RESULT_SCHEMA, operation, request.envelope.request_fingerprint, request.envelope.expected_revision, TurnInteractionResultStatus.PROPOSED, effective_mode, proposal, proposal.warnings))

    def _clarification(self, request: TurnInteractionEvaluationRequest, mode: str, candidates: tuple[str, ...]) -> TurnInteractionEvaluationResult:
        digest = canonical_fingerprint(request.player_input.semantic_material())
        stable = canonical_fingerprint({"operation_ref": request.envelope.operation_ref, "clarification": digest})[7:39]
        proposal = TurnInteractionProposal(
            TURN_INTERACTION_PROPOSAL_SCHEMA, f"interaction.{stable}", request.envelope.operation_ref,
            TurnInteractionProposalKind.CLARIFICATION, digest, request.snapshot.interaction_revision,
            clarification_question="请从当前合法行动中明确你的意图。", clarification_candidates=candidates,
        )
        return self._final(TurnInteractionEvaluationResult(TURN_INTERACTION_RESULT_SCHEMA, request.envelope.operation_ref, request.envelope.request_fingerprint, request.envelope.expected_revision, TurnInteractionResultStatus.NEEDS_CLARIFICATION, mode, proposal))

    def _blocked(self, request: TurnInteractionEvaluationRequest, mode: str, code: ProblemCode, reason: str) -> TurnInteractionEvaluationResult:
        problem = Problem(code, "评估玩家回合交互", reason, "没有生成状态、效果或交互推进提案。", "刷新交互 View/lease/revision 后重新提交。")
        return self._final(TurnInteractionEvaluationResult(TURN_INTERACTION_RESULT_SCHEMA, request.envelope.operation_ref, request.envelope.request_fingerprint, request.envelope.expected_revision, TurnInteractionResultStatus.BLOCKED, mode, problems=(problem,)))

    @staticmethod
    def _final(result: TurnInteractionEvaluationResult) -> TurnInteractionEvaluationResult:
        return replace(result, result_fingerprint=turn_interaction_result_fingerprint(result))


class TurnInteractionService:
    def __init__(self, evaluator: TurnInteractionEvaluator, *, clock=None) -> None:
        self.evaluator = evaluator
        self._clock = clock or (lambda: datetime.now(UTC))

    async def evaluate_turn_interaction(self, request: TurnInteractionEvaluationRequest, bridge: PlatformBridge) -> TurnInteractionEvaluationResult:
        check = CancellationCheck(request.envelope.operation_ref, request.envelope.request_fingerprint)
        if (await bridge.is_cancelled(check)).cancelled:
            return self._terminal(request, TurnInteractionResultStatus.CANCELLED, ProblemCode.CANCELLED, "平台已取消交互操作。")
        deadline = datetime.fromisoformat(request.envelope.deadline_at.replace("Z", "+00:00"))
        if self._clock() >= deadline:
            return self._terminal(request, TurnInteractionResultStatus.TIMED_OUT, ProblemCode.DEADLINE_EXCEEDED, "交互操作已超过 deadline。")
        result = self.evaluator.evaluate(request)
        if (await bridge.is_cancelled(check)).cancelled:
            return self._terminal(request, TurnInteractionResultStatus.CANCELLED, ProblemCode.CANCELLED, "交互结果返回前操作已取消。")
        if self._clock() >= deadline:
            return self._terminal(request, TurnInteractionResultStatus.TIMED_OUT, ProblemCode.DEADLINE_EXCEEDED, "交互结果在返回前已超过 deadline。")
        return result

    def _terminal(self, request: TurnInteractionEvaluationRequest, status: TurnInteractionResultStatus, code: ProblemCode, reason: str) -> TurnInteractionEvaluationResult:
        problem = Problem(code, "评估玩家回合交互", reason, "没有生成可提交交互提案。", "刷新权威交互状态后重新发起。")
        return TurnInteractionEvaluator._final(TurnInteractionEvaluationResult(TURN_INTERACTION_RESULT_SCHEMA, request.envelope.operation_ref, request.envelope.request_fingerprint, request.envelope.expected_revision, status, request.snapshot.mode, problems=(problem,)))


class TurnInteractionStoryEnginePort(Protocol):
    async def evaluate_turn_interaction(self, request: TurnInteractionEvaluationRequest, bridge: PlatformBridge) -> TurnInteractionEvaluationResult: ...


__all__ = [name for name in globals() if name.startswith("TURN_INTERACTION") or name in {
    "ChoiceSemantics", "DialogueIntent", "PlayerTurnInput", "ReferencedPlayerTurnInput", "PlayerActionReference", "PLAYER_TURN_INPUT_SCHEMA", "PLAYER_TURN_REFERENCED_INPUT_SCHEMA", "TurnInteractionContractError",
    "TurnInteractionEvaluationRequest", "TurnInteractionEvaluationResult", "TurnInteractionEvaluator",
    "TurnInteractionProposal", "TurnInteractionProposalKind", "TurnInteractionResultStatus",
    "TurnInteractionService", "TurnInteractionSnapshot", "TurnInteractionStoryEnginePort",
    "bind_turn_interaction_policy", "compile_turn_interaction_policies", "decode_player_turn_input",
    "decode_turn_interaction_snapshot", "turn_interaction_result_fingerprint",
    "turn_interaction_request_fingerprint", "turn_interaction_snapshot_fingerprint",
}]
