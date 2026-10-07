"""Versioned catastrophic-event author, IR, and runtime invariants.

This module validates declarative material only.  It deliberately does not add a
parallel evaluator or claim platform fate/terminal authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

CATASTROPHIC_PROFILE_VERSION = "1.1.0"
CATASTROPHIC_CONTRACT = "se-catastrophic-profile/1.0.0"

_REF_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_CATEGORIES = frozenset({"regional", "campaign", "existential"})
_ROUTE_KINDS = frozenset({"challenge", "tactical", "procedure", "safe_exit", "resource_tradeoff"})
_NON_COMBAT_KINDS = frozenset({"procedure", "safe_exit", "resource_tradeoff"})
_CONSEQUENCE_CLASSES = frozenset({
    "reversible", "costly_reversible", "persistent", "consent_required",
    "host_confirmation_required", "terminal_candidate",
})
_BASE_CAPABILITIES = frozenset({"event.orchestrate", "event.consequence", "event.omen", "event.aftermath"})
_MODES = frozenset({"maximum", "subset_without_fate_terminal"})
_PROFILE_FIELDS = frozenset({
    "schema", "category", "public_risk", "known_consequences", "deadline",
    "response_routes", "consequence_classes", "human_dm_checkpoint_ref",
    "aftermath_checkpoint_ref", "recovery_windows", "capability_mode",
    "fate_checkpoint_ref", "terminal_checkpoint_ref",
})


@dataclass(frozen=True, slots=True)
class CatastrophicContractError(ValueError):
    code: str
    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.code}:{self.path}"


def _fail(code: str, path: str, reason: str) -> None:
    raise CatastrophicContractError(code, path, reason)


def _ref(value: object, path: str) -> str:
    if not isinstance(value, str) or _REF_RE.fullmatch(value) is None:
        _fail("catastrophic.reference_invalid", path, "字段必须是稳定引用。")
    return value


def _text(value: object, path: str, maximum: int = 600) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _fail("catastrophic.text_invalid", path, "字段必须是有界非空文本。")
    return value.strip()


def _sequence(value: object, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("catastrophic.sequence_invalid", path, "字段必须是列表。")
    return value


def _digest(value: Mapping[str, Any]) -> str:
    def plain(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {key: plain(child) for key, child in item.items()}
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            return [plain(child) for child in item]
        return item

    encoded = json.dumps(plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _author_material(author: Mapping[str, Any]) -> dict[str, Any]:
    profile_data = author.get("profile_data")
    if not isinstance(profile_data, Mapping):
        _fail("catastrophic.profile_data_invalid", "profile_data", "灾难 profile_data 必须是对象。")
    unknown = set(profile_data) - _PROFILE_FIELDS
    missing = _PROFILE_FIELDS - {"fate_checkpoint_ref", "terminal_checkpoint_ref"} - set(profile_data)
    if unknown:
        _fail("catastrophic.field_unknown", "profile_data", "灾难合同包含未知字段。")
    if missing:
        _fail("catastrophic.field_missing", "profile_data", "灾难合同缺少必需字段。")
    if profile_data.get("schema") != CATASTROPHIC_CONTRACT:
        _fail("catastrophic.schema_incompatible", "profile_data.schema", "灾难合同版本不兼容。")
    category = str(profile_data.get("category") or "")
    if category not in _CATEGORIES:
        _fail("catastrophic.category_invalid", "profile_data.category", "category 必须是 regional、campaign 或 existential。")
    mode = str(profile_data.get("capability_mode") or "")
    if mode not in _MODES:
        _fail("catastrophic.mode_invalid", "profile_data.capability_mode", "能力模式不受支持。")

    known = tuple(_text(item, f"profile_data.known_consequences[{index}]") for index, item in enumerate(_sequence(profile_data.get("known_consequences"), "profile_data.known_consequences")))
    if not known or len(known) != len(set(known)):
        _fail("catastrophic.known_consequences_invalid", "profile_data.known_consequences", "已知后果必须非空且不重复。")
    omens = _sequence(author.get("omens"), "omens")
    if not omens:
        _fail("catastrophic.omen_missing", "omens", "灾难必须至少有一个公开预兆。")
    normalized_omens: list[dict[str, str]] = []
    for index, omen in enumerate(omens):
        if not isinstance(omen, Mapping) or set(omen) != {"id", "public_warning"}:
            _fail("catastrophic.omen_invalid", f"omens[{index}]", "预兆必须且只能包含 id 与 public_warning。")
        normalized_omens.append({"id": _ref(omen.get("id"), f"omens[{index}].id"), "public_warning": _text(omen.get("public_warning"), f"omens[{index}].public_warning")})
    if len({item["id"] for item in normalized_omens}) != len(normalized_omens):
        _fail("catastrophic.omen_duplicate", "omens", "预兆 ID 不能重复。")

    deadline = profile_data.get("deadline")
    if not isinstance(deadline, Mapping) or set(deadline) != {"kind", "ref", "maximum_rounds"}:
        _fail("catastrophic.deadline_invalid", "profile_data.deadline", "deadline 必须冻结 kind/ref/maximum_rounds。")
    if deadline.get("kind") not in {"clock", "checkpoints"}:
        _fail("catastrophic.deadline_invalid", "profile_data.deadline.kind", "deadline kind 不受支持。")
    deadline_ref = _ref(deadline.get("ref"), "profile_data.deadline.ref")
    maximum_rounds = deadline.get("maximum_rounds")
    if isinstance(maximum_rounds, bool) or not isinstance(maximum_rounds, int) or maximum_rounds < 1:
        _fail("catastrophic.deadline_invalid", "profile_data.deadline.maximum_rounds", "maximum_rounds 必须是正整数。")

    responses = _sequence(profile_data.get("response_routes"), "profile_data.response_routes")
    normalized_routes: list[dict[str, str]] = []
    for index, item in enumerate(responses):
        if not isinstance(item, Mapping) or set(item) != {"route_ref", "kind"}:
            _fail("catastrophic.response_route_invalid", f"profile_data.response_routes[{index}]", "响应路线必须冻结 route_ref 与 kind。")
        kind = str(item.get("kind") or "")
        if kind not in _ROUTE_KINDS:
            _fail("catastrophic.response_route_invalid", f"profile_data.response_routes[{index}].kind", "响应路线类型不受支持。")
        normalized_routes.append({"route_ref": _ref(item.get("route_ref"), f"profile_data.response_routes[{index}].route_ref"), "kind": kind})
    if len(normalized_routes) < 2 or len({item["route_ref"] for item in normalized_routes}) != len(normalized_routes) or len({item["kind"] for item in normalized_routes}) < 2:
        _fail("catastrophic.response_routes_insufficient", "profile_data.response_routes", "必须有至少两条引用和玩法均不同的实质路线。")
    if not any(item["kind"] in _NON_COMBAT_KINDS for item in normalized_routes):
        _fail("catastrophic.non_combat_route_missing", "profile_data.response_routes", "灾难必须有非战斗路线。")
    if not any(item["kind"] == "safe_exit" for item in normalized_routes):
        _fail("catastrophic.safe_exit_missing", "profile_data.response_routes", "灾难必须有明确安全出口。")

    classes = tuple(str(item) for item in _sequence(profile_data.get("consequence_classes"), "profile_data.consequence_classes"))
    if not classes or len(classes) != len(set(classes)) or not set(classes) <= _CONSEQUENCE_CLASSES:
        _fail("catastrophic.consequence_class_invalid", "profile_data.consequence_classes", "后果分类为空、重复或未知。")
    fate_ref = profile_data.get("fate_checkpoint_ref")
    terminal_ref = profile_data.get("terminal_checkpoint_ref")
    if mode == "maximum":
        if not {"consent_required", "terminal_candidate"} <= set(classes):
            _fail("catastrophic.maximum_consequence_missing", "profile_data.consequence_classes", "最大链必须包含 consent_required 与 terminal_candidate。")
        fate_ref = _ref(fate_ref, "profile_data.fate_checkpoint_ref")
        terminal_ref = _ref(terminal_ref, "profile_data.terminal_checkpoint_ref")
    elif fate_ref is not None or terminal_ref is not None or set(classes) & {"consent_required", "terminal_candidate"}:
        _fail("catastrophic.subset_fate_terminal_forbidden", "profile_data", "能力子集链不得声明 fate/terminal 检查点或后果。")

    recoveries = tuple(_ref(item, f"profile_data.recovery_windows[{index}]") for index, item in enumerate(_sequence(profile_data.get("recovery_windows"), "profile_data.recovery_windows")))
    if not recoveries or len(recoveries) != len(set(recoveries)):
        _fail("catastrophic.recovery_window_invalid", "profile_data.recovery_windows", "恢复窗口必须非空且不重复。")
    return {
        "schema": CATASTROPHIC_CONTRACT,
        "capability_mode": mode,
        "category": category,
        "omens": normalized_omens,
        "public_risk": _text(profile_data.get("public_risk"), "profile_data.public_risk"),
        "known_consequences": list(known),
        "deadline": {"kind": deadline["kind"], "ref": deadline_ref, "maximum_rounds": maximum_rounds},
        "response_routes": normalized_routes,
        "consequence_classes": list(classes),
        "human_dm_checkpoint_ref": _ref(profile_data.get("human_dm_checkpoint_ref"), "profile_data.human_dm_checkpoint_ref"),
        "aftermath_checkpoint_ref": _ref(profile_data.get("aftermath_checkpoint_ref"), "profile_data.aftermath_checkpoint_ref"),
        "recovery_windows": list(recoveries),
        "fate_checkpoint_ref": fate_ref,
        "terminal_checkpoint_ref": terminal_ref,
    }


def validate_catastrophic_author(author: Mapping[str, Any]) -> None:
    """Validate the profile-specific author surface before compilation."""
    _author_material(author)


def compile_catastrophic_contract(author: Mapping[str, Any], graph: Mapping[str, Any], required_capability_refs: Sequence[str]) -> dict[str, Any]:
    """Bind author intent to the post-pruning checkpoint graph and exact providers."""
    material = _author_material(author)
    nodes = {str(item["id"]): item for item in graph["nodes"]}
    routes = {str(item["id"]): item for item in graph["edges"]}
    required_bases = {item.rsplit("/", 1)[0] for item in required_capability_refs}
    if not _BASE_CAPABILITIES <= required_bases:
        _fail("catastrophic.capability_missing", "requires_capabilities", "灾难链缺少必需的 orchestrate/consequence/omen/aftermath provider。")
    for item in material["response_routes"]:
        route = routes.get(item["route_ref"])
        if route is None:
            _fail("catastrophic.response_route_pruned", "profile_data.response_routes", "实质路线在能力解析后缺失。")
        if item["kind"] == "safe_exit" and not nodes[str(route["to"])].get("exit_kind"):
            _fail("catastrophic.safe_exit_not_terminal", "profile_data.response_routes", "安全出口必须到达声明式事件出口。")
    for field in ("human_dm_checkpoint_ref", "aftermath_checkpoint_ref", "fate_checkpoint_ref", "terminal_checkpoint_ref"):
        ref = material.get(field)
        if ref is not None and ref not in nodes:
            _fail("catastrophic.checkpoint_unknown", f"profile_data.{field}", "灾难合同引用了未知检查点。")
    for ref in material["recovery_windows"]:
        if ref not in nodes:
            _fail("catastrophic.recovery_window_unknown", "profile_data.recovery_windows", "恢复窗口引用了未知检查点。")
    human = nodes[material["human_dm_checkpoint_ref"]]
    aftermath = nodes[material["aftermath_checkpoint_ref"]]
    if human.get("required_gate") != "host":
        _fail("catastrophic.human_dm_gate_missing", "profile_data.human_dm_checkpoint_ref", "human-DM 检查点必须使用 host gate。")
    if aftermath.get("kind") != "aftermath" or not aftermath.get("exit_kind"):
        _fail("catastrophic.aftermath_invalid", "profile_data.aftermath_checkpoint_ref", "aftermath 必须是可达事件出口。")
    if material["capability_mode"] == "maximum":
        fate = nodes[str(material["fate_checkpoint_ref"])]
        terminal = nodes[str(material["terminal_checkpoint_ref"])]
        if fate.get("required_gate") != "consent" or terminal.get("required_gate") != "host":
            _fail("catastrophic.authority_gate_missing", "profile_data", "最大链 fate/terminal 必须分别绑定 consent/host gate。")
    compiled = {
        **material,
        "required_capability_refs": sorted(required_capability_refs),
        "safety_invariants": [
            "ordinary_failure_never_terminal",
            "fate_requires_actor_consent",
            "terminal_requires_host_authority",
            "aftermath_and_safe_exit_required",
        ],
    }
    compiled["contract_sha256"] = _digest(compiled)
    return compiled


def validate_compiled_catastrophic_event(event: Mapping[str, Any]) -> None:
    """Reject mutated or incomplete catastrophic IR before any request is evaluated."""
    if event.get("profile") != "catastrophic_event" or event.get("profile_version") != CATASTROPHIC_PROFILE_VERSION:
        return
    contract = event.get("catastrophic_contract")
    if not isinstance(contract, Mapping) or contract.get("schema") != CATASTROPHIC_CONTRACT:
        _fail("catastrophic.compiled_contract_missing", "catastrophic_contract", "编译灾难合同缺失或版本不兼容。")
    expected = _digest({key: value for key, value in contract.items() if key != "contract_sha256"})
    if contract.get("contract_sha256") != expected:
        _fail("catastrophic.compiled_fingerprint_mismatch", "catastrophic_contract.contract_sha256", "编译灾难合同指纹不匹配。")
    graph = event.get("checkpoint_graph")
    if not isinstance(graph, Mapping):
        _fail("catastrophic.compiled_graph_missing", "checkpoint_graph", "灾难 IR 缺少检查点图。")
    closure = event.get("capability_closure")
    if not isinstance(closure, Mapping) or not isinstance(closure.get("required"), Sequence):
        _fail("catastrophic.compiled_capability_missing", "capability_closure", "灾难 IR 缺少精确能力闭包。")
    closure_refs = sorted(f"{item.get('id')}/{item.get('version')}" for item in closure["required"] if isinstance(item, Mapping))
    if closure_refs != sorted(contract.get("required_capability_refs", ())):
        _fail("catastrophic.compiled_capability_mismatch", "catastrophic_contract.required_capability_refs", "灾难合同与 IR 能力闭包不一致。")
    # Re-run cross-field validation against IR rather than trusting a self-consistent hash.
    author_like = {"profile_data": {key: value for key, value in contract.items() if key in _PROFILE_FIELDS}, "omens": contract.get("omens")}
    compile_catastrophic_contract(author_like, graph, tuple(contract.get("required_capability_refs", ())))


__all__ = [
    "CATASTROPHIC_CONTRACT", "CATASTROPHIC_PROFILE_VERSION", "CatastrophicContractError",
    "compile_catastrophic_contract", "validate_catastrophic_author", "validate_compiled_catastrophic_event",
]
