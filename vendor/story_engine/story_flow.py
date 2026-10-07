"""Strict, deterministic StoryFlow Recipe to Engine IR compiler.

This unassigned contract slice compiles declarative author data only; it neither
owns a running StoryFlowInstance nor invokes a model or provider. Release-wheel
inclusion and dev6 integration remain separately unverified.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


STORY_FLOW_RECIPE_SCHEMA = "story-flow-recipe/1.0.0"
STORY_FLOW_IR_SCHEMA = "se-story-flow-ir/1.0.0"
SP_STORY_FLOW_CANDIDATE_SCHEMA = "sp-story-flow-recipe-candidate/0.2"

PHASE_KINDS = frozenset({"cooperative", "private_parallel", "regroup", "public_conflict", "finale", "epilogue"})
COMPLETION_KINDS = frozenset({"all_required", "quorum", "selected_subset", "deadline", "explicit_host_transition", "interrupt_condition"})
PUBLICATION_KINDS = frozenset({"private_only", "deferred_public", "mechanical_shared", "immediate_public_interrupt", "invalid_or_unresolved"})
ENDING_MODES = frozenset({"cooperative", "public_conflict", "hybrid", "epilogue"})

_RECIPE_FIELDS = frozenset({
    "schema", "recipe_ref", "recipe_version", "required_capabilities", "optional_capabilities",
    "entry_phase_ref", "phase_nodes", "transitions", "cycle_guards", "ending_modes",
    "absence_defaults", "public_summary",
})
_PHASE_FIELDS = frozenset({
    "phase_ref", "kind", "label", "summary", "participant_policy_ref", "interaction_policy_ref",
    "content_hook_refs", "completion_policy", "deadline_policy", "absence_policy",
    "result_publication_policy", "operation_budget", "required_capabilities", "optional_capabilities",
    "fallback",
})
_TRANSITION_FIELDS = frozenset({
    "transition_ref", "from_phase_ref", "to_phase_ref", "trigger_kind", "condition_refs",
    "rule_receipt_requirements", "priority", "consent_policy", "host_gate", "public_summary",
    "on_failure", "failure_phase_ref",
})
_CYCLE_FIELDS = frozenset({
    "guard_ref", "transition_refs", "max_repetitions", "progress_condition_refs",
    "no_progress_exit_ref", "public_summary",
})
_ENDING_FIELDS = frozenset({
    "mode", "finale_phase_ref", "epilogue_phase_ref", "required_capabilities", "consent_policy",
})
_SP_FIELDS = frozenset({"schema", "candidate_version", "installable", "recipe_ref", "locale", "requirement_refs", "phase_kinds", "opening_entries", "nodes", "transitions"})
_SP_ENTRY_FIELDS = frozenset({"opening_ref", "source_opening_id", "entry_node_ref", "first_chapter_node_ref"})
_SP_NODE_FIELDS = frozenset({"node_ref", "opening_ref", "role", "phase_kind", "player_name", "summary", "slice_terminal"})
_SP_TRANSITION_FIELDS = frozenset({"transition_ref", "from_node_ref", "to_node_ref", "outcome", "priority", "player_summary"})
_SP_FULL_FIELDS = frozenset({
    "schema", "candidate_version", "installable", "recipe_ref", "locale", "requirement_refs",
    "phase_kinds", "opening_entries", "policy_catalog", "lane_definitions", "finale_definitions",
    "nodes", "transitions",
})
_SP_FULL_NODE_FIELDS = frozenset({
    "node_ref", "opening_ref", "role", "phase_kind", "player_name", "summary", "slice_terminal",
    "participant_policy_ref", "interaction_policy_ref", "content_hooks", "completion_policy_ref",
    "deadline_absence_policy_ref", "result_visibility_policy_ref", "operation_budget_ref",
    "required_capabilities", "optional_capabilities", "fallback_node_ref", "exit_policy_ref",
    "merge_policy_ref", "recovery_policy_ref", "consent_policy_ref", "lane_refs", "finale_definition_ref",
})
_SP_FULL_TRANSITION_FIELDS = frozenset({
    "transition_ref", "from_node_ref", "to_node_ref", "outcomes", "trigger", "committed_conditions",
    "required_rule_receipts", "decision_mode", "priority", "player_summary", "failure_recovery",
})
_CATALOG_FIELDS = frozenset({
    "capability_refs", "participant_policy_refs", "interaction_policy_refs", "content_hook_refs",
    "condition_refs", "rule_receipt_requirement_refs", "progress_condition_refs",
})


@dataclass(frozen=True, slots=True)
class StoryFlowContractError(ValueError):
    code: str
    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.code}:{self.path}"


def _fail(code: str, path: str, reason: str) -> None:
    raise StoryFlowContractError(code, path, reason)


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("story_flow.object_invalid", path, "字段必须是 JSON 对象。")
    return value


def _sequence(value: object, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("story_flow.sequence_invalid", path, "字段必须是 JSON 数组。")
    return value


def _fields(value: Mapping[str, Any], expected: frozenset[str] | set[str], path: str) -> None:
    if set(value) != set(expected):
        _fail("story_flow.fields_invalid", path, "字段不完整或包含未知字段。")


def _text(value: object, path: str, maximum: int = 600) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        _fail("story_flow.text_invalid", path, "字段必须是有界非空文本。")
    return value.strip()


def _ref(value: object, path: str) -> str:
    result = _text(value, path, 160)
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:@-"
    if result[0] not in allowed[:62] or any(char not in allowed for char in result):
        _fail("story_flow.reference_invalid", path, "字段必须是稳定引用。")
    return result


def _integer(value: object, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail("story_flow.integer_invalid", path, f"字段必须是大于等于 {minimum} 的整数。")
    return value


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        _fail("story_flow.boolean_invalid", path, "字段必须是布尔值。")
    return value


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail("story_flow.non_canonical_value", "$", f"值无法形成 canonical JSON: {exc}")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _refs(value: object, path: str, *, required: bool = False) -> list[str]:
    result = [_ref(item, f"{path}[{index}]") for index, item in enumerate(_sequence(value, path))]
    if required and not result:
        _fail("story_flow.references_empty", path, "引用集合不得为空。")
    if len(result) != len(set(result)):
        _fail("story_flow.reference_duplicate", path, "引用不得重复。")
    return sorted(result)


def _catalog(value: Mapping[str, Any]) -> dict[str, set[str]]:
    catalog = _mapping(value, "reference_catalog")
    _fields(catalog, _CATALOG_FIELDS, "reference_catalog")
    return {key: set(_refs(catalog[key], f"reference_catalog.{key}")) for key in sorted(_CATALOG_FIELDS)}


def _catalog_material(catalog: Mapping[str, set[str]]) -> dict[str, list[str]]:
    return {key: sorted(catalog[key]) for key in sorted(_CATALOG_FIELDS)}


def _resolved(refs: Sequence[str], catalog: set[str], path: str) -> None:
    if set(refs) - catalog:
        _fail("story_flow.reference_unresolved", path, "引用未出现在冻结引用目录中。")


def _compile_phase(raw: object, index: int, required_recipe_capabilities: set[str], capabilities: set[str], catalog: dict[str, set[str]]) -> dict[str, Any]:
    path = f"phase_nodes[{index}]"
    phase = _mapping(raw, path)
    _fields(phase, _PHASE_FIELDS, path)
    phase_ref = _ref(phase["phase_ref"], f"{path}.phase_ref")
    kind = phase["kind"]
    if kind not in PHASE_KINDS:
        _fail("story_flow.phase_kind_invalid", f"{path}.kind", "phase kind 不属于冻结公共枚举。")
    required_capabilities = _refs(phase["required_capabilities"], f"{path}.required_capabilities")
    optional_capabilities = _refs(phase["optional_capabilities"], f"{path}.optional_capabilities")
    if set(required_capabilities) - required_recipe_capabilities or set(optional_capabilities) - capabilities:
        _fail("story_flow.capability_unresolved", path, "节点 capability 未在 Recipe 能力闭包中声明。")
    _resolved(required_capabilities + optional_capabilities, catalog["capability_refs"], f"{path}.capabilities")
    completion = _mapping(phase["completion_policy"], f"{path}.completion_policy")
    _fields(completion, {"kind", "threshold", "on_unmet"}, f"{path}.completion_policy")
    if completion["kind"] not in COMPLETION_KINDS or completion["on_unmet"] not in {"stay", "pause", "fallback"}:
        _fail("story_flow.completion_policy_invalid", f"{path}.completion_policy", "完成策略不受支持。")
    threshold = completion["threshold"]
    if threshold is not None:
        threshold = _integer(threshold, f"{path}.completion_policy.threshold", minimum=1)
    if completion["kind"] in {"quorum", "selected_subset"} and threshold is None:
        _fail("story_flow.completion_threshold_missing", f"{path}.completion_policy.threshold", "该完成策略必须声明阈值。")
    deadline = _mapping(phase["deadline_policy"], f"{path}.deadline_policy")
    _fields(deadline, {"mode", "seconds", "expiry_action"}, f"{path}.deadline_policy")
    if deadline["mode"] not in {"none", "bounded"} or deadline["expiry_action"] not in {"stay", "pause", "fallback", "transition"}:
        _fail("story_flow.deadline_policy_invalid", f"{path}.deadline_policy", "截止策略不受支持。")
    seconds = deadline["seconds"]
    if deadline["mode"] == "bounded":
        seconds = _integer(seconds, f"{path}.deadline_policy.seconds", minimum=1)
    elif seconds is not None:
        _fail("story_flow.deadline_policy_invalid", f"{path}.deadline_policy.seconds", "无截止模式不得夹带时长。")
    absence = _mapping(phase["absence_policy"], f"{path}.absence_policy")
    _fields(absence, {"suggested_action", "maximum_wait_seconds", "requires_actor_consent"}, f"{path}.absence_policy")
    if absence["suggested_action"] not in {"wait", "pass", "delegate_human", "temporary_ai", "pause"}:
        _fail("story_flow.absence_policy_invalid", f"{path}.absence_policy.suggested_action", "缺席建议不受支持。")
    maximum_wait = absence["maximum_wait_seconds"]
    if maximum_wait is not None:
        maximum_wait = _integer(maximum_wait, f"{path}.absence_policy.maximum_wait_seconds", minimum=1)
    publication = _refs(phase["result_publication_policy"], f"{path}.result_publication_policy", required=True)
    if set(publication) - PUBLICATION_KINDS:
        _fail("story_flow.publication_policy_invalid", f"{path}.result_publication_policy", "公开分类不属于冻结枚举。")
    budget = _mapping(phase["operation_budget"], f"{path}.operation_budget")
    budget_fields = {"max_interactions", "max_input_chars", "max_context_tokens", "max_model_calls", "wall_clock_ms", "repair_attempts"}
    _fields(budget, budget_fields, f"{path}.operation_budget")
    compiled_budget = {key: _integer(budget[key], f"{path}.operation_budget.{key}") for key in sorted(budget_fields)}
    fallback = _mapping(phase["fallback"], f"{path}.fallback")
    _fields(fallback, {"mode", "phase_ref", "public_summary"}, f"{path}.fallback")
    if fallback["mode"] not in {"block", "phase"}:
        _fail("story_flow.fallback_invalid", f"{path}.fallback.mode", "fallback mode 不受支持。")
    fallback_ref = None if fallback["phase_ref"] is None else _ref(fallback["phase_ref"], f"{path}.fallback.phase_ref")
    if (fallback["mode"] == "phase") != (fallback_ref is not None):
        _fail("story_flow.fallback_invalid", f"{path}.fallback.phase_ref", "phase fallback 必须且只能带目标引用。")
    participant_ref = _ref(phase["participant_policy_ref"], f"{path}.participant_policy_ref")
    interaction_ref = _ref(phase["interaction_policy_ref"], f"{path}.interaction_policy_ref")
    hook_refs = _refs(phase["content_hook_refs"], f"{path}.content_hook_refs", required=True)
    _resolved([participant_ref], catalog["participant_policy_refs"], f"{path}.participant_policy_ref")
    _resolved([interaction_ref], catalog["interaction_policy_refs"], f"{path}.interaction_policy_ref")
    _resolved(hook_refs, catalog["content_hook_refs"], f"{path}.content_hook_refs")
    return {
        "phase_ref": phase_ref, "kind": kind, "label": _text(phase["label"], f"{path}.label", 120),
        "summary": _text(phase["summary"], f"{path}.summary"),
        "participant_policy_ref": participant_ref, "interaction_policy_ref": interaction_ref,
        "content_hook_refs": hook_refs,
        "completion_policy": {"kind": completion["kind"], "threshold": threshold, "on_unmet": completion["on_unmet"]},
        "deadline_policy": {"mode": deadline["mode"], "seconds": seconds, "expiry_action": deadline["expiry_action"]},
        "absence_policy": {"suggested_action": absence["suggested_action"], "maximum_wait_seconds": maximum_wait, "requires_actor_consent": _boolean(absence["requires_actor_consent"], f"{path}.absence_policy.requires_actor_consent")},
        "result_publication_policy": publication, "operation_budget": compiled_budget,
        "required_capabilities": required_capabilities, "optional_capabilities": optional_capabilities,
        "fallback": {"mode": fallback["mode"], "phase_ref": fallback_ref, "public_summary": _text(fallback["public_summary"], f"{path}.fallback.public_summary")},
    }


def compile_story_flow_recipe(document: Mapping[str, Any], reference_catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Compile one strict declarative Recipe into byte-stable Engine-owned IR."""
    recipe = _mapping(document, "$")
    catalog = _catalog(reference_catalog)
    _fields(recipe, _RECIPE_FIELDS, "$")
    if recipe["schema"] != STORY_FLOW_RECIPE_SCHEMA:
        _fail("story_flow.schema_incompatible", "$.schema", "Recipe schema identity 不兼容。")
    required_capabilities = _refs(recipe["required_capabilities"], "required_capabilities")
    optional_capabilities = _refs(recipe["optional_capabilities"], "optional_capabilities")
    if set(required_capabilities) & set(optional_capabilities):
        _fail("story_flow.capability_duplicate", "optional_capabilities", "required/optional capability 不得重叠。")
    capabilities = set(required_capabilities + optional_capabilities)
    _resolved(required_capabilities + optional_capabilities, catalog["capability_refs"], "capabilities")
    phases = [_compile_phase(raw, index, set(required_capabilities), capabilities, catalog) for index, raw in enumerate(_sequence(recipe["phase_nodes"], "phase_nodes"))]
    if not phases:
        _fail("story_flow.phases_empty", "phase_nodes", "Recipe 至少需要一个 phase。")
    phase_refs = [phase["phase_ref"] for phase in phases]
    if len(phase_refs) != len(set(phase_refs)):
        _fail("story_flow.phase_duplicate", "phase_nodes", "phase_ref 不得重复。")
    phase_by_ref = {phase["phase_ref"]: phase for phase in phases}
    for phase in phases:
        fallback_ref = phase["fallback"]["phase_ref"]
        if fallback_ref is not None and fallback_ref not in phase_by_ref:
            _fail("story_flow.fallback_unresolved", f"phase_nodes[{phase['phase_ref']}].fallback.phase_ref", "fallback phase 不存在。")
    entry = _ref(recipe["entry_phase_ref"], "entry_phase_ref")
    if entry not in phase_by_ref:
        _fail("story_flow.entry_unresolved", "entry_phase_ref", "入口 phase 不存在。")
    if phase_by_ref[entry]["kind"] not in {"cooperative", "private_parallel"}:
        _fail("story_flow.entry_kind_invalid", "entry_phase_ref", "入口必须是可行动阶段。")
    for capability, kind in (("story_flow.private_parallel", "private_parallel"), ("story_flow.public_conflict", "public_conflict")):
        if any(phase["kind"] == kind for phase in phases) and capability not in required_capabilities:
            _fail("story_flow.capability_missing", "required_capabilities", f"{kind} 必须声明 required capability。")

    transitions: list[dict[str, Any]] = []
    transition_refs: set[str] = set()
    priorities: set[tuple[str, int]] = set()
    adjacency: dict[str, list[str]] = {ref: [] for ref in phase_refs}
    for index, raw in enumerate(_sequence(recipe["transitions"], "transitions")):
        path = f"transitions[{index}]"; transition = _mapping(raw, path); _fields(transition, _TRANSITION_FIELDS, path)
        transition_ref = _ref(transition["transition_ref"], f"{path}.transition_ref")
        if transition_ref in transition_refs:
            _fail("story_flow.transition_duplicate", f"{path}.transition_ref", "transition_ref 不得重复。")
        transition_refs.add(transition_ref)
        source = _ref(transition["from_phase_ref"], f"{path}.from_phase_ref")
        target = _ref(transition["to_phase_ref"], f"{path}.to_phase_ref")
        if source not in phase_by_ref or target not in phase_by_ref:
            _fail("story_flow.transition_endpoint_unresolved", path, "转换端点不存在。")
        # A self-loop is accepted only when the graph's exact cyclic-transition
        # closure is subsequently covered by one bounded cycle guard.
        priority = _integer(transition["priority"], f"{path}.priority")
        if (source, priority) in priorities:
            _fail("story_flow.priority_ambiguous", f"{path}.priority", "同一来源的转换优先级必须唯一。")
        priorities.add((source, priority))
        trigger = transition["trigger_kind"]
        if trigger not in {"phase_complete", "rule_receipt", "player_choice", "host_confirm", "interrupt"}:
            _fail("story_flow.trigger_kind_invalid", f"{path}.trigger_kind", "触发类型不受支持。")
        receipt_requirements = _refs(transition["rule_receipt_requirements"], f"{path}.rule_receipt_requirements")
        condition_refs = _refs(transition["condition_refs"], f"{path}.condition_refs")
        _resolved(condition_refs, catalog["condition_refs"], f"{path}.condition_refs")
        _resolved(receipt_requirements, catalog["rule_receipt_requirement_refs"], f"{path}.rule_receipt_requirements")
        host_gate = _boolean(transition["host_gate"], f"{path}.host_gate")
        if trigger == "rule_receipt" and not receipt_requirements:
            _fail("story_flow.rule_receipt_missing", f"{path}.rule_receipt_requirements", "rule_receipt 触发必须声明正式回执要求。")
        if trigger == "host_confirm" and host_gate is not True:
            _fail("story_flow.host_gate_missing", f"{path}.host_gate", "host_confirm 触发必须开启房主确认门。")
        consent = transition["consent_policy"]
        if consent not in {"none", "all_participants", "affected_participants", "explicit_pvp"}:
            _fail("story_flow.consent_policy_invalid", f"{path}.consent_policy", "同意策略不受支持。")
        if phase_by_ref[target]["kind"] == "public_conflict" and consent != "explicit_pvp":
            _fail("story_flow.public_conflict_consent_missing", f"{path}.consent_policy", "进入公开冲突必须显式同意。")
        on_failure = transition["on_failure"]
        if on_failure not in {"stay", "pause", "fallback_phase"}:
            _fail("story_flow.failure_policy_invalid", f"{path}.on_failure", "失败恢复策略不受支持。")
        failure_ref = None if transition["failure_phase_ref"] is None else _ref(transition["failure_phase_ref"], f"{path}.failure_phase_ref")
        if (on_failure == "fallback_phase") != (failure_ref is not None) or (failure_ref is not None and failure_ref not in phase_by_ref):
            _fail("story_flow.failure_phase_invalid", f"{path}.failure_phase_ref", "fallback_phase 必须且只能引用存在的阶段。")
        compiled = {
            "transition_ref": transition_ref, "from_phase_ref": source, "to_phase_ref": target,
            "trigger_kind": trigger, "condition_refs": condition_refs,
            "rule_receipt_requirements": receipt_requirements,
            "priority": priority, "consent_policy": consent, "host_gate": host_gate,
            "public_summary": _text(transition["public_summary"], f"{path}.public_summary"),
            "on_failure": on_failure, "failure_phase_ref": failure_ref,
        }
        transitions.append(compiled); adjacency[source].append(target)
    if not transitions:
        _fail("story_flow.transitions_empty", "transitions", "Recipe 至少需要一条转换。")

    reachable: set[str] = set(); queue = deque([entry])
    while queue:
        current = queue.popleft()
        if current in reachable: continue
        reachable.add(current); queue.extend(adjacency[current])
    if reachable != set(phase_refs):
        _fail("story_flow.phase_unreachable", "phase_nodes", "所有 phase 必须从入口可达。")

    def reaches(start: str, goal: str) -> bool:
        pending = list(adjacency[start]); seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current == goal: return True
            if current not in seen: seen.add(current); pending.extend(adjacency[current])
        return False

    cyclic_transition_refs = {item["transition_ref"] for item in transitions if reaches(item["to_phase_ref"], item["from_phase_ref"])}
    guards: list[dict[str, Any]] = []; guarded: set[str] = set(); guard_refs: set[str] = set()
    for index, raw in enumerate(_sequence(recipe["cycle_guards"], "cycle_guards")):
        path = f"cycle_guards[{index}]"; guard = _mapping(raw, path); _fields(guard, _CYCLE_FIELDS, path)
        guard_ref = _ref(guard["guard_ref"], f"{path}.guard_ref")
        if guard_ref in guard_refs: _fail("story_flow.cycle_guard_duplicate", f"{path}.guard_ref", "cycle guard 不得重复。")
        guard_refs.add(guard_ref)
        refs = _refs(guard["transition_refs"], f"{path}.transition_refs", required=True)
        if set(refs) - transition_refs or not set(refs).issubset(cyclic_transition_refs):
            _fail("story_flow.cycle_guard_reference_invalid", f"{path}.transition_refs", "cycle guard 只能引用真实回路上的转换。")
        if guarded & set(refs): _fail("story_flow.cycle_guard_overlap", path, "一条循环转换只能由一个 guard 管理。")
        guarded.update(refs)
        exit_ref = _ref(guard["no_progress_exit_ref"], f"{path}.no_progress_exit_ref")
        if exit_ref not in transition_refs: _fail("story_flow.cycle_exit_unresolved", f"{path}.no_progress_exit_ref", "无进展出口转换不存在。")
        if exit_ref in cyclic_transition_refs:
            _fail("story_flow.cycle_exit_invalid", f"{path}.no_progress_exit_ref", "无进展出口本身不得留在循环中。")
        transition_by_ref = {item["transition_ref"]: item for item in transitions}
        guarded_nodes = {transition_by_ref[ref][side] for ref in refs for side in ("from_phase_ref", "to_phase_ref")}
        anchor = next(iter(guarded_nodes))
        if any(not reaches(anchor, node) or not reaches(node, anchor) for node in guarded_nodes):
            _fail("story_flow.cycle_guard_component_invalid", f"{path}.transition_refs", "一个 cycle guard 只能管理同一强连通分量。")
        if transition_by_ref[exit_ref]["from_phase_ref"] not in guarded_nodes:
            _fail("story_flow.cycle_exit_disconnected", f"{path}.no_progress_exit_ref", "无进展出口必须从受守卫循环的节点出发。")
        progress_refs = _refs(guard["progress_condition_refs"], f"{path}.progress_condition_refs", required=True)
        _resolved(progress_refs, catalog["progress_condition_refs"], f"{path}.progress_condition_refs")
        guards.append({"guard_ref": guard_ref, "transition_refs": refs, "max_repetitions": _integer(guard["max_repetitions"], f"{path}.max_repetitions", minimum=1), "progress_condition_refs": progress_refs, "no_progress_exit_ref": exit_ref, "public_summary": _text(guard["public_summary"], f"{path}.public_summary")})
    if guarded != cyclic_transition_refs:
        _fail("story_flow.cycle_guard_incomplete", "cycle_guards", "每条循环转换都必须恰好受一个有限 guard 约束。")

    endings: list[dict[str, Any]] = []; modes: set[str] = set()
    for index, raw in enumerate(_sequence(recipe["ending_modes"], "ending_modes")):
        path = f"ending_modes[{index}]"; ending = _mapping(raw, path); _fields(ending, _ENDING_FIELDS, path)
        mode = ending["mode"]
        if mode not in ENDING_MODES or mode in modes: _fail("story_flow.ending_mode_invalid", f"{path}.mode", "ending mode 无效或重复。")
        modes.add(mode)
        finale_ref = _ref(ending["finale_phase_ref"], f"{path}.finale_phase_ref"); epilogue_ref = _ref(ending["epilogue_phase_ref"], f"{path}.epilogue_phase_ref")
        if phase_by_ref.get(finale_ref, {}).get("kind") != "finale" or phase_by_ref.get(epilogue_ref, {}).get("kind") != "epilogue":
            _fail("story_flow.ending_phase_invalid", path, "ending 必须引用 finale 与 epilogue 阶段。")
        required = _refs(ending["required_capabilities"], f"{path}.required_capabilities")
        if set(required) - set(required_capabilities): _fail("story_flow.capability_unresolved", path, "ending required capability 必须由 Recipe required 闭包保证。")
        _resolved(required, catalog["capability_refs"], f"{path}.required_capabilities")
        consent = ending["consent_policy"]
        if consent not in {"none", "all_participants", "explicit_pvp"} or (mode == "public_conflict" and consent != "explicit_pvp"):
            _fail("story_flow.ending_consent_invalid", f"{path}.consent_policy", "终局同意策略无效。")
        if not reaches(finale_ref, epilogue_ref):
            _fail("story_flow.ending_path_missing", path, "finale 必须存在通往对应 epilogue 的合法路径。")
        endings.append({"mode": mode, "finale_phase_ref": finale_ref, "epilogue_phase_ref": epilogue_ref, "required_capabilities": required, "consent_policy": consent})
    if not endings: _fail("story_flow.ending_modes_empty", "ending_modes", "至少需要一种 ending mode。")
    terminal_refs = {ref for ref, edges in adjacency.items() if not edges}
    if not terminal_refs or any(phase_by_ref[ref]["kind"] != "epilogue" for ref in terminal_refs):
        _fail("story_flow.terminal_phase_invalid", "phase_nodes", "所有且至少一个终止节点必须是 epilogue。")
    absence = _mapping(recipe["absence_defaults"], "absence_defaults")
    _fields(absence, {"suggested_action", "maximum_wait_seconds", "requires_actor_consent"}, "absence_defaults")
    if absence["suggested_action"] not in {"wait", "pass", "delegate_human", "temporary_ai", "pause"}:
        _fail("story_flow.absence_policy_invalid", "absence_defaults.suggested_action", "默认缺席建议不受支持。")
    maximum_wait = absence["maximum_wait_seconds"]
    if maximum_wait is not None: maximum_wait = _integer(maximum_wait, "absence_defaults.maximum_wait_seconds", minimum=1)

    source_sha256 = _digest(recipe)
    source_map = [{"ir_ref": _ref(recipe["recipe_ref"], "recipe_ref"), "source_path": "$"}]
    source_map.extend({"ir_ref": phase["phase_ref"], "source_path": f"$.phase_nodes[{index}]"} for index, phase in enumerate(phases))
    source_map.extend({"ir_ref": transition["transition_ref"], "source_path": f"$.transitions[{index}]"} for index, transition in enumerate(transitions))
    source_map.extend({"ir_ref": guard["guard_ref"], "source_path": f"$.cycle_guards[{index}]"} for index, guard in enumerate(guards))
    source_map.extend({"ir_ref": f"ending:{ending['mode']}", "source_path": f"$.ending_modes[{index}]"} for index, ending in enumerate(endings))
    graph_summary = {
        "phase_count": len(phases), "transition_count": len(transitions),
        "reachable_phase_refs": sorted(reachable), "cyclic_transition_refs": sorted(cyclic_transition_refs),
        "terminal_phase_refs": sorted(terminal_refs),
    }
    runtime_slice = {
        "entry_phase_ref": entry, "phase_nodes": sorted(phases, key=lambda item: item["phase_ref"]),
        "transitions": sorted(transitions, key=lambda item: item["transition_ref"]),
        "cycle_guards": sorted(guards, key=lambda item: item["guard_ref"]),
        "ending_modes": sorted(endings, key=lambda item: item["mode"]),
    }
    material = {
        "schema": STORY_FLOW_IR_SCHEMA, "recipe_ref": _ref(recipe["recipe_ref"], "recipe_ref"),
        "recipe_version": _ref(recipe["recipe_version"], "recipe_version"), "source_schema": STORY_FLOW_RECIPE_SCHEMA,
        "source_sha256": source_sha256, "reference_catalog_sha256": _digest(_catalog_material(catalog)),
        "source_map": sorted(source_map, key=lambda item: item["ir_ref"]), "required_capabilities": required_capabilities,
        "optional_capabilities": optional_capabilities, **runtime_slice,
        "absence_defaults": {"suggested_action": absence["suggested_action"], "maximum_wait_seconds": maximum_wait, "requires_actor_consent": _boolean(absence["requires_actor_consent"], "absence_defaults.requires_actor_consent")},
        "public_summary": _text(recipe["public_summary"], "public_summary"), "graph_summary": graph_summary,
        "runtime_slice_sha256": _digest(runtime_slice),
    }
    material["ir_sha256"] = _digest(material)
    return material


def validate_story_flow_ir(value: Mapping[str, Any], reference_catalog: Mapping[str, Any], source_document: Mapping[str, Any]) -> None:
    ir = _mapping(value, "$")
    expected = {"schema", "recipe_ref", "recipe_version", "source_schema", "source_sha256", "reference_catalog_sha256", "source_map", "required_capabilities", "optional_capabilities", "entry_phase_ref", "phase_nodes", "transitions", "cycle_guards", "ending_modes", "absence_defaults", "public_summary", "graph_summary", "runtime_slice_sha256", "ir_sha256"}
    _fields(ir, expected, "$")
    if ir["schema"] != STORY_FLOW_IR_SCHEMA or ir["source_schema"] != STORY_FLOW_RECIPE_SCHEMA:
        _fail("story_flow.ir_schema_incompatible", "$.schema", "IR schema identity 不兼容。")
    catalog = _catalog(reference_catalog)
    if ir["reference_catalog_sha256"] != _digest(_catalog_material(catalog)):
        _fail("story_flow.reference_catalog_mismatch", "$.reference_catalog_sha256", "IR 未绑定当前冻结引用目录。")
    runtime_slice = {key: ir[key] for key in ("entry_phase_ref", "phase_nodes", "transitions", "cycle_guards", "ending_modes")}
    if ir["runtime_slice_sha256"] != _digest(runtime_slice) or ir["ir_sha256"] != _digest({key: item for key, item in ir.items() if key != "ir_sha256"}):
        _fail("story_flow.digest_mismatch", "$", "IR 摘要与内容不一致。")
    rebuilt = compile_story_flow_recipe(source_document, reference_catalog)
    if ir != rebuilt:
        _fail("story_flow.product_mismatch", "$", "IR 必须逐字段匹配原 Recipe 与冻结引用目录的确定性重编译结果。")


def _projected_phase(node: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "phase_ref": node["node_ref"], "kind": "cooperative", "label": node["player_name"],
        "summary": node["summary"], "participant_policy_ref": "participant.all-present.v1",
        "interaction_policy_ref": "interaction.standard.v1", "content_hook_refs": [f"content-hook:{node['node_ref']}"],
        "completion_policy": {"kind": "all_required", "threshold": None, "on_unmet": "stay"},
        "deadline_policy": {"mode": "none", "seconds": None, "expiry_action": "stay"},
        "absence_policy": {"suggested_action": "wait", "maximum_wait_seconds": 300, "requires_actor_consent": True},
        "result_publication_policy": ["mechanical_shared"],
        "operation_budget": {"max_interactions": 1, "max_input_chars": 4000, "max_context_tokens": 8000, "max_model_calls": 0, "wall_clock_ms": 30000, "repair_attempts": 0},
        "required_capabilities": [], "optional_capabilities": [],
        "fallback": {"mode": "block", "phase_ref": None, "public_summary": "当前阶段无法继续时暂停，并保留已经提交的结果。"},
    }


def _compile_sp_story_flow_full_candidate(
    candidate: Mapping[str, Any], opening_catalog: Mapping[str, Any]
) -> list[dict[str, Any]]:
    _fields(candidate, _SP_FULL_FIELDS, "$")
    base_recipe_ref = _ref(candidate["recipe_ref"], "recipe_ref")
    if candidate["phase_kinds"] != ["cooperative", "private_parallel", "regroup", "public_conflict", "finale", "epilogue"]:
        _fail("story_flow.sp_contract_invalid", "phase_kinds", "完整候选必须精确声明六阶段。")
    policies = _mapping(candidate["policy_catalog"], "policy_catalog")
    policy_fields = {
        "participant_policies", "interaction_policies", "completion_policies", "deadline_absence_policies",
        "result_visibility_policies", "operation_budgets", "exit_policies", "merge_policies",
        "recovery_policies", "consent_policies",
    }
    _fields(policies, policy_fields, "policy_catalog")

    authority = _mapping(opening_catalog, "opening_catalog")
    source_by_id: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(_sequence(authority["openings"], "opening_catalog.openings")):
        source = _mapping(raw, f"opening_catalog.openings[{index}]")
        source_by_id[_ref(source["id"], f"opening_catalog.openings[{index}].id")] = source
    if len(source_by_id) != 10:
        _fail("story_flow.sp_opening_catalog_invalid", "opening_catalog.openings", "权威开场必须精确包含十项。")

    node_by_ref: dict[str, Mapping[str, Any]] = {}
    nodes_by_opening: dict[str, list[Mapping[str, Any]]] = {}
    for index, raw in enumerate(_sequence(candidate["nodes"], "nodes")):
        path = f"nodes[{index}]"; node = _mapping(raw, path); _fields(node, _SP_FULL_NODE_FIELDS, path)
        ref = _ref(node["node_ref"], f"{path}.node_ref")
        if ref in node_by_ref or not isinstance(node["role"], str) or node["phase_kind"] not in PHASE_KINDS:
            _fail("story_flow.sp_node_invalid", path, "节点 identity 或 phase kind 无效。")
        _text(node["player_name"], f"{path}.player_name", 120); _text(node["summary"], f"{path}.summary")
        node_by_ref[ref] = node
        nodes_by_opening.setdefault(_ref(node["opening_ref"], f"{path}.opening_ref"), []).append(node)
    if len(node_by_ref) != 70:
        _fail("story_flow.sp_counts_invalid", "nodes", "完整候选必须精确包含 70 个节点。")

    transitions_by_opening: dict[str, list[Mapping[str, Any]]] = {key: [] for key in nodes_by_opening}
    transition_refs: set[str] = set()
    for index, raw in enumerate(_sequence(candidate["transitions"], "transitions")):
        path = f"transitions[{index}]"; item = _mapping(raw, path); _fields(item, _SP_FULL_TRANSITION_FIELDS, path)
        ref = _ref(item["transition_ref"], f"{path}.transition_ref")
        source = node_by_ref.get(item["from_node_ref"]); target = node_by_ref.get(item["to_node_ref"])
        if ref in transition_refs or source is None or target is None:
            _fail("story_flow.sp_transition_endpoint_invalid", path, "转换端点必须存在且 identity 唯一。")
        if source["opening_ref"] != target["opening_ref"]:
            _fail("story_flow.sp_outcome_coverage_invalid", path, "转换不得越过 opening 子图。")
        outcomes = item["outcomes"]
        allowed_outcomes = {"completed", "continue_private", "conflict_declined", "cooperative", "exit", "failure", "private_unavailable", "pvp_consented", "pvp_declined", "retreat"}
        if not isinstance(outcomes, Sequence) or isinstance(outcomes, (str, bytes, bytearray)) or not outcomes or any(value not in allowed_outcomes for value in outcomes):
            _fail("story_flow.sp_outcome_invalid", f"{path}.outcomes", "outcomes 必须是冻结非空枚举集合。")
        _text(item["player_summary"], f"{path}.player_summary")
        transition_refs.add(ref); transitions_by_opening[source["opening_ref"]].append(item)
    if len(transition_refs) != 120:
        _fail("story_flow.sp_counts_invalid", "transitions", "完整候选必须精确包含 120 条转换。")

    opening_catalog_sha256 = _digest(authority)
    products: list[dict[str, Any]] = []; source_ids: set[str] = set()
    entries = list(_sequence(candidate["opening_entries"], "opening_entries"))
    if len(entries) != 10:
        _fail("story_flow.sp_counts_invalid", "opening_entries", "完整候选必须精确包含十个 opening。")
    for index, raw in enumerate(entries):
        path = f"opening_entries[{index}]"; entry = _mapping(raw, path); _fields(entry, _SP_ENTRY_FIELDS, path)
        opening_ref = _ref(entry["opening_ref"], f"{path}.opening_ref")
        source = source_by_id.get(entry["source_opening_id"])
        if source is None:
            _fail("story_flow.sp_source_opening_unresolved", f"{path}.source_opening_id", "source opening 未解析。")
        source_ids.add(entry["source_opening_id"])
        opening_nodes = sorted(nodes_by_opening.get(opening_ref, []), key=lambda item: item["node_ref"])
        if len(opening_nodes) != 7:
            _fail("story_flow.sp_entry_shape_invalid", path, "每个 opening 必须解析一个权威源和七阶段节点。")
        by_role = {node["role"]: node for node in opening_nodes}
        if set(by_role) != {"opening", "first_chapter", "private_action", "regroup", "public_conflict", "finale", "epilogue"}:
            _fail("story_flow.sp_entry_shape_invalid", path, "opening 子图角色不闭合。")
        if by_role["opening"]["node_ref"] != entry["entry_node_ref"] or by_role["first_chapter"]["node_ref"] != entry["first_chapter_node_ref"]:
            _fail("story_flow.sp_entry_endpoint_invalid", path, "opening/first chapter 锚点不匹配。")

        phases: list[dict[str, Any]] = []
        for node in opening_nodes:
            completion = policies["completion_policies"][node["completion_policy_ref"]]
            absence = policies["deadline_absence_policies"][node["deadline_absence_policy_ref"]]
            visibility = policies["result_visibility_policies"][node["result_visibility_policy_ref"]]
            budget = policies["operation_budgets"][node["operation_budget_ref"]]
            suggested = next((value for value in absence["allowed_absence_actions"] if value in {"wait", "pause", "delegate_human"}), "wait")
            publication = "private_only" if visibility["default_audience"] == "actor" else "mechanical_shared"
            hook_refs = ["content-hook." + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24] for value in node["content_hooks"]]
            fallback_ref = node["fallback_node_ref"]
            has_fallback = fallback_ref is not None and fallback_ref != node["node_ref"]
            phases.append({
                "phase_ref": node["node_ref"], "kind": node["phase_kind"], "label": node["player_name"],
                "summary": node["summary"], "participant_policy_ref": node["participant_policy_ref"],
                "interaction_policy_ref": node["interaction_policy_ref"], "content_hook_refs": hook_refs,
                "completion_policy": {"kind": completion["kind"], "threshold": completion["threshold"], "on_unmet": "stay"},
                "deadline_policy": {"mode": "none", "seconds": None, "expiry_action": "stay"},
                "absence_policy": {"suggested_action": suggested, "maximum_wait_seconds": 300, "requires_actor_consent": bool(absence["critical_decisions_require_human"])},
                "result_publication_policy": [publication],
                "operation_budget": {"max_interactions": budget["max_rounds"], "max_input_chars": budget["max_input_chars"], "max_context_tokens": 12000, "max_model_calls": budget["main_model_calls"], "wall_clock_ms": 45000, "repair_attempts": 2},
                "required_capabilities": list(node["required_capabilities"]), "optional_capabilities": list(node["optional_capabilities"]),
                "fallback": {"mode": "phase" if has_fallback else "block", "phase_ref": fallback_ref if has_fallback else None, "public_summary": "当前阶段无法安全继续时，保留已提交结果并转入已登记恢复路径。"},
            })

        projected_transitions: list[dict[str, Any]] = []
        priority_stride=max(len(item["outcomes"]) for item in transitions_by_opening[opening_ref])+1
        for item in sorted(transitions_by_opening[opening_ref], key=lambda value: value["transition_ref"]):
            target_kind = node_by_ref[item["to_node_ref"]]["phase_kind"]
            # Source outcomes are alternatives; the standard IR conditions are
            # conjunctive. Give each outcome its own independently provable edge.
            outcomes=sorted(item["outcomes"])
            for outcome_index,outcome in enumerate(outcomes):
                conditions = [f"condition.outcome.{outcome}"]
                conditions += [f"condition.commit.{value}" for value in item["committed_conditions"]]
                transition_ref=item["transition_ref"] if len(outcomes)==1 else item["transition_ref"]+".outcome."+outcome
                projected_transitions.append({
                    "transition_ref": transition_ref, "from_phase_ref": item["from_node_ref"],
                    "to_phase_ref": item["to_node_ref"], "trigger_kind": "rule_receipt",
                    "condition_refs": conditions, "rule_receipt_requirements": list(item["required_rule_receipts"]),
                    "priority": item["priority"]*priority_stride+len(outcomes)-outcome_index-1, "consent_policy": "explicit_pvp" if target_kind == "public_conflict" else "none",
                    "host_gate": False, "public_summary": item["player_summary"], "on_failure": "pause", "failure_phase_ref": None,
                })

        self_loops = [item for item in projected_transitions if item["from_phase_ref"] == item["to_phase_ref"]]
        guards: list[dict[str, Any]] = []
        for loop in self_loops:
            exits = [item for item in projected_transitions if item["from_phase_ref"] == loop["from_phase_ref"] and item["to_phase_ref"] != loop["from_phase_ref"]]
            exit_item = next((item for item in exits if "condition.outcome.exit" in item["condition_refs"]), exits[0] if exits else None)
            if exit_item is None:
                _fail("story_flow.sp_cycle_exit_missing", loop["transition_ref"], "私人循环缺少有界退出。")
            progress_ref = loop["transition_ref"] + ".progress"
            guards.append({"guard_ref": loop["transition_ref"] + ".guard", "transition_refs": [loop["transition_ref"]], "max_repetitions": 3, "progress_condition_refs": [progress_ref], "no_progress_exit_ref": exit_item["transition_ref"], "public_summary": "私人行动最多循环三次；无进展时转入公开安全路径。"})

        required_caps = sorted({cap for phase in phases for cap in phase["required_capabilities"]} | {"story_flow.private_parallel", "story_flow.public_conflict"})
        optional_caps = sorted({cap for phase in phases for cap in phase["optional_capabilities"]} - set(required_caps))
        recipe = {
            "schema": STORY_FLOW_RECIPE_SCHEMA, "recipe_ref": opening_ref + ".projection", "recipe_version": "0.2-unassigned",
            "required_capabilities": required_caps, "optional_capabilities": optional_caps,
            "entry_phase_ref": entry["entry_node_ref"], "phase_nodes": phases, "transitions": projected_transitions,
            "cycle_guards": guards,
            "ending_modes": [{"mode": "hybrid", "finale_phase_ref": by_role["finale"]["node_ref"], "epilogue_phase_ref": by_role["epilogue"]["node_ref"], "required_capabilities": [], "consent_policy": "all_participants"}],
            "absence_defaults": {"suggested_action": "wait", "maximum_wait_seconds": 300, "requires_actor_consent": True},
            "public_summary": f"《{source['title']}》完整六阶段候选投影。",
        }
        catalog = {
            "capability_refs": sorted(set(required_caps + optional_caps)),
            "participant_policy_refs": sorted({phase["participant_policy_ref"] for phase in phases}),
            "interaction_policy_refs": sorted({phase["interaction_policy_ref"] for phase in phases}),
            "content_hook_refs": sorted({ref for phase in phases for ref in phase["content_hook_refs"]}),
            "condition_refs": sorted({ref for item in projected_transitions for ref in item["condition_refs"]}),
            "rule_receipt_requirement_refs": sorted({ref for item in projected_transitions for ref in item["rule_receipt_requirements"]}),
            "progress_condition_refs": sorted({ref for guard in guards for ref in guard["progress_condition_refs"]}),
        }
        ir = compile_story_flow_recipe(recipe, catalog)
        projection = {"recipe": recipe, "reference_catalog": catalog, "ir": ir, "opening_catalog_sha256": opening_catalog_sha256}
        products.append({"opening_ref": opening_ref, "source_opening_id": entry["source_opening_id"], **projection, "projection_sha256": _digest(projection)})
    if source_ids != set(source_by_id):
        _fail("story_flow.sp_source_opening_closure_invalid", "opening_entries", "十个 opening 必须与权威目录闭合。")
    if any(not item["opening_ref"].startswith(base_recipe_ref + ".opening.") for item in products):
        _fail("story_flow.sp_entry_shape_invalid", "opening_entries", "opening ref 必须位于 recipe 命名空间。")
    return sorted(products, key=lambda item: item["opening_ref"])


def compile_sp_story_flow_candidate(document: Mapping[str, Any], opening_catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Strictly project each SP 0.2 opening slice and compile its standard IR.

    The deterministic finale/epilogue tail marks the boundary of this
    non-installable conformance projection; it is not a platform runtime route.
    """
    candidate = _mapping(document, "$")
    if set(candidate) == set(_SP_FULL_FIELDS):
        if candidate["schema"] != SP_STORY_FLOW_CANDIDATE_SCHEMA or candidate["candidate_version"] != "unassigned" or candidate["installable"] is not False or candidate["locale"] != "zh-CN":
            _fail("story_flow.sp_identity_invalid", "$", "完整候选 identity 无效。")
        return _compile_sp_story_flow_full_candidate(candidate, opening_catalog)
    _fields(candidate, _SP_FIELDS, "$")
    if candidate["schema"] != SP_STORY_FLOW_CANDIDATE_SCHEMA or candidate["candidate_version"] != "unassigned" or candidate["installable"] is not False:
        _fail("story_flow.sp_identity_invalid", "$", "只接受明确 unassigned 且 non-installable 的 SP 0.2 candidate。")
    if candidate["locale"] != "zh-CN" or candidate["phase_kinds"] != ["cooperative"]:
        _fail("story_flow.sp_contract_invalid", "$", "首片只接受冻结的 zh-CN cooperative 候选。")
    base_recipe_ref = _ref(candidate["recipe_ref"], "recipe_ref")
    authority = _mapping(opening_catalog, "opening_catalog")
    _fields(authority, {"schema", "story_pack_ref", "version", "selection_policy", "openings", "counts", "known_gap"}, "opening_catalog")
    if authority["schema"] != "thirteenth-seat.openings-routes/1":
        _fail("story_flow.sp_opening_catalog_invalid", "opening_catalog.schema", "开场目录 Schema 不兼容。")
    _ref(authority["story_pack_ref"], "opening_catalog.story_pack_ref"); _ref(authority["version"], "opening_catalog.version")
    _text(authority["selection_policy"], "opening_catalog.selection_policy"); _text(authority["known_gap"], "opening_catalog.known_gap")
    source_by_id: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(_sequence(authority["openings"], "opening_catalog.openings")):
        path = f"opening_catalog.openings[{index}]"; source = _mapping(raw, path)
        _fields(source, {"id", "title", "region", "crisis", "initial_state", "actions", "route", "prologue_story"}, path)
        source_id = _ref(source["id"], f"{path}.id")
        if source_id in source_by_id: _fail("story_flow.sp_opening_catalog_invalid", f"{path}.id", "权威开场 id 重复。")
        _text(source["title"], f"{path}.title", 120); _text(source["crisis"], f"{path}.crisis")
        route = _mapping(source["route"], f"{path}.route")
        _fields(route, {"title", "scenes", "resource", "mutually_exclusive", "fail_forward", "exits"}, f"{path}.route")
        _text(route["title"], f"{path}.route.title", 120); _text(route["fail_forward"], f"{path}.route.fail_forward")
        source_by_id[source_id] = source
    if len(source_by_id) != 10:
        _fail("story_flow.sp_opening_catalog_invalid", "opening_catalog.openings", "权威开场目录必须精确包含十个开场。")
    opening_catalog_sha256 = _digest(authority)
    requirements = _refs(candidate["requirement_refs"], "requirement_refs", required=True)
    if len(requirements) != len(candidate["requirement_refs"]):
        _fail("story_flow.sp_requirements_invalid", "requirement_refs", "需求引用必须唯一。")
    required_requirement_refs = {"TSFLOW02-001", "TSFLOW02-002", "TSFLOW02-003", "TSFLOW02-004", "TSFLOW02-006", "TSFLOW02-007"}
    if not required_requirement_refs.issubset(requirements):
        _fail("story_flow.sp_requirements_invalid", "requirement_refs", "候选缺少入口、独立子图、阶段枚举或转换合同引用。")
    entries = list(_sequence(candidate["opening_entries"], "opening_entries"))
    nodes = list(_sequence(candidate["nodes"], "nodes"))
    transitions = list(_sequence(candidate["transitions"], "transitions"))
    if len(entries) != 10 or len(nodes) != 20 or len(transitions) != 30:
        _fail("story_flow.sp_counts_invalid", "$", "候选必须精确包含十入口、二十节点与三十 outcome 转换。")

    node_by_ref: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(nodes):
        path = f"nodes[{index}]"; node = _mapping(raw, path); _fields(node, _SP_NODE_FIELDS, path)
        node_ref = _ref(node["node_ref"], f"{path}.node_ref")
        if node_ref in node_by_ref: _fail("story_flow.sp_node_duplicate", f"{path}.node_ref", "节点引用重复。")
        if not isinstance(node["role"], str) or node["role"] not in {"opening", "first_chapter"} or not isinstance(node["phase_kind"], str) or node["phase_kind"] != "cooperative" or not isinstance(node["slice_terminal"], bool):
            _fail("story_flow.sp_node_invalid", path, "节点 role、phase_kind 或 slice_terminal 无效。")
        node_opening_ref = _ref(node["opening_ref"], f"{path}.opening_ref")
        player_name = _text(node["player_name"], f"{path}.player_name", 120); summary = _text(node["summary"], f"{path}.summary")
        if len(player_name) < 2 or len(summary) < 20 or not node_ref.startswith(f"{base_recipe_ref}.node.") or not node_opening_ref.startswith(f"{base_recipe_ref}.opening."):
            _fail("story_flow.sp_node_invalid", path, "节点身份或玩家可读名称/摘要不满足冻结候选合同。")
        node_by_ref[node_ref] = node

    transition_by_source: dict[str, list[Mapping[str, Any]]] = {}
    transition_refs: set[str] = set()
    for index, raw in enumerate(transitions):
        path = f"transitions[{index}]"; transition = _mapping(raw, path); _fields(transition, _SP_TRANSITION_FIELDS, path)
        ref = _ref(transition["transition_ref"], f"{path}.transition_ref")
        if ref in transition_refs: _fail("story_flow.sp_transition_duplicate", f"{path}.transition_ref", "转换引用重复。")
        transition_refs.add(ref)
        source = _ref(transition["from_node_ref"], f"{path}.from_node_ref"); target = _ref(transition["to_node_ref"], f"{path}.to_node_ref")
        if source not in node_by_ref or target not in node_by_ref or source == target:
            _fail("story_flow.sp_transition_endpoint_invalid", path, "转换端点必须存在且不同。")
        if not isinstance(transition["outcome"], str) or transition["outcome"] not in {"completed", "failure", "retreat"}:
            _fail("story_flow.sp_outcome_invalid", f"{path}.outcome", "outcome 必须属于冻结三值。")
        _integer(transition["priority"], f"{path}.priority"); player_summary = _text(transition["player_summary"], f"{path}.player_summary")
        if len(player_summary) < 15 or not ref.startswith(f"{base_recipe_ref}.transition."):
            _fail("story_flow.sp_transition_invalid", path, "转换身份或玩家摘要不满足冻结候选合同。")
        transition_by_source.setdefault(source, []).append(transition)

    products: list[dict[str, Any]] = []; opening_refs: set[str] = set(); source_ids: set[str] = set()
    for index, raw in enumerate(entries):
        path = f"opening_entries[{index}]"; entry = _mapping(raw, path); _fields(entry, _SP_ENTRY_FIELDS, path)
        opening_ref = _ref(entry["opening_ref"], f"{path}.opening_ref"); source_id = _ref(entry["source_opening_id"], f"{path}.source_opening_id")
        entry_ref = _ref(entry["entry_node_ref"], f"{path}.entry_node_ref"); chapter_ref = _ref(entry["first_chapter_node_ref"], f"{path}.first_chapter_node_ref")
        if opening_ref in opening_refs or source_id in source_ids: _fail("story_flow.sp_entry_duplicate", path, "opening/source 引用必须唯一。")
        if not opening_ref.startswith(f"{base_recipe_ref}.opening."):
            _fail("story_flow.sp_entry_shape_invalid", f"{path}.opening_ref", "opening_ref 必须位于候选 Recipe 命名空间。")
        opening_refs.add(opening_ref); source_ids.add(source_id)
        opening_node = node_by_ref.get(entry_ref); chapter_node = node_by_ref.get(chapter_ref)
        if opening_node is None or chapter_node is None:
            _fail("story_flow.sp_entry_endpoint_invalid", path, "入口节点不存在。")
        if opening_node["opening_ref"] != opening_ref or chapter_node["opening_ref"] != opening_ref or opening_node["role"] != "opening" or chapter_node["role"] != "first_chapter" or opening_node["slice_terminal"] is not False or chapter_node["slice_terminal"] is not True:
            _fail("story_flow.sp_entry_shape_invalid", path, "入口必须绑定一个 opening 与一个 slice-terminal first_chapter。")
        source = source_by_id.get(source_id)
        if source is None:
            _fail("story_flow.sp_source_opening_unresolved", f"{path}.source_opening_id", "source_opening_id 未在权威开场目录解析。")
        route = _mapping(source["route"], f"opening_catalog.openings[{source_id}].route")
        if opening_node["player_name"] != source["title"] or opening_node["summary"] != source["crisis"] or chapter_node["player_name"] != route["title"] or chapter_node["summary"] != route["fail_forward"]:
            _fail("story_flow.sp_source_binding_mismatch", path, "开场与第一章名称/摘要未精确绑定权威开场目录。")
        outgoing = sorted(transition_by_source.get(entry_ref, []), key=lambda item: item["transition_ref"])
        if len(outgoing) != 3 or {item["outcome"] for item in outgoing} != {"completed", "failure", "retreat"} or {item["to_node_ref"] for item in outgoing} != {chapter_ref}:
            _fail("story_flow.sp_outcome_coverage_invalid", path, "每个入口必须精确覆盖 completed/failure/retreat 并进入自己的第一章。")
        if {item["outcome"]: item["priority"] for item in outgoing} != {"completed": 300, "failure": 200, "retreat": 100}:
            _fail("story_flow.sp_priority_invalid", path, "三类 outcome 优先级必须精确冻结。")
        finale_ref = f"{opening_ref}.projection.finale"; epilogue_ref = f"{opening_ref}.projection.epilogue"
        projected_nodes = [_projected_phase(opening_node), _projected_phase(chapter_node)]
        projected_nodes.extend([
            {**_projected_phase({"node_ref": finale_ref, "player_name": "阶段切片结束确认", "summary": "当前开场与第一章入口的候选切片已经完整投影，等待后续正式阶段图接续。"}), "kind": "finale"},
            {**_projected_phase({"node_ref": epilogue_ref, "player_name": "阶段切片投影完成", "summary": "本次确定性合同验证在此结束，不向平台提交运行中的故事阶段状态。"}), "kind": "epilogue"},
        ])
        projected_transitions = []
        for item in outgoing:
            outcome = item["outcome"]
            projected_transitions.append({
                "transition_ref": item["transition_ref"], "from_phase_ref": entry_ref, "to_phase_ref": chapter_ref,
                "trigger_kind": "rule_receipt", "condition_refs": [f"condition.outcome.{outcome}"],
                "rule_receipt_requirements": [f"receipt.outcome.{outcome}"], "priority": item["priority"],
                "consent_policy": "none", "host_gate": False, "public_summary": item["player_summary"],
                "on_failure": "stay", "failure_phase_ref": None,
            })
        projected_transitions.extend([
            {"transition_ref": f"{opening_ref}.projection.chapter-finale", "from_phase_ref": chapter_ref, "to_phase_ref": finale_ref, "trigger_kind": "phase_complete", "condition_refs": [], "rule_receipt_requirements": [], "priority": 10, "consent_policy": "none", "host_gate": False, "public_summary": "第一章入口切片验证完成。", "on_failure": "pause", "failure_phase_ref": None},
            {"transition_ref": f"{opening_ref}.projection.finale-epilogue", "from_phase_ref": finale_ref, "to_phase_ref": epilogue_ref, "trigger_kind": "phase_complete", "condition_refs": [], "rule_receipt_requirements": [], "priority": 10, "consent_policy": "none", "host_gate": False, "public_summary": "阶段切片确定性投影完成。", "on_failure": "pause", "failure_phase_ref": None},
        ])
        recipe = {
            "schema": STORY_FLOW_RECIPE_SCHEMA, "recipe_ref": f"{opening_ref}.projection", "recipe_version": "0.2-unassigned",
            "required_capabilities": [], "optional_capabilities": [], "entry_phase_ref": entry_ref,
            "phase_nodes": projected_nodes, "transitions": projected_transitions, "cycle_guards": [],
            "ending_modes": [{"mode": "cooperative", "finale_phase_ref": finale_ref, "epilogue_phase_ref": epilogue_ref, "required_capabilities": [], "consent_policy": "all_participants"}],
            "absence_defaults": {"suggested_action": "wait", "maximum_wait_seconds": 300, "requires_actor_consent": True},
            "public_summary": f"《{opening_node['player_name']}》至《{chapter_node['player_name']}》的候选阶段切片。",
        }
        outcomes = sorted({item["outcome"] for item in outgoing})
        catalog = {
            "capability_refs": [], "participant_policy_refs": ["participant.all-present.v1"],
            "interaction_policy_refs": ["interaction.standard.v1"],
            "content_hook_refs": sorted(phase["content_hook_refs"][0] for phase in projected_nodes),
            "condition_refs": [f"condition.outcome.{outcome}" for outcome in outcomes],
            "rule_receipt_requirement_refs": [f"receipt.outcome.{outcome}" for outcome in outcomes],
            "progress_condition_refs": [],
        }
        ir = compile_story_flow_recipe(recipe, catalog)
        projection = {"recipe": recipe, "reference_catalog": catalog, "ir": ir, "opening_catalog_sha256": opening_catalog_sha256}
        products.append({"opening_ref": opening_ref, "source_opening_id": source_id, **projection, "projection_sha256": _digest(projection)})
    if source_ids != set(source_by_id):
        _fail("story_flow.sp_source_opening_closure_invalid", "opening_entries", "candidate source_opening_id 必须与权威十开场精确闭包。")
    if set(node_by_ref) != {ref for product in products for ref in (product["recipe"]["phase_nodes"][0]["phase_ref"], product["recipe"]["phase_nodes"][1]["phase_ref"])}:
        _fail("story_flow.sp_orphan_node", "nodes", "所有 SP 节点必须且只能属于一个 opening 投影。")
    if transition_refs != {item["transition_ref"] for product in products for item in product["recipe"]["transitions"][:3]}:
        _fail("story_flow.sp_orphan_transition", "transitions", "所有 SP 转换必须且只能属于一个 opening 投影。")
    return sorted(products, key=lambda item: item["opening_ref"])


__all__ = ["SP_STORY_FLOW_CANDIDATE_SCHEMA", "STORY_FLOW_IR_SCHEMA", "STORY_FLOW_RECIPE_SCHEMA", "StoryFlowContractError", "compile_sp_story_flow_candidate", "compile_story_flow_recipe", "validate_story_flow_ir"]
