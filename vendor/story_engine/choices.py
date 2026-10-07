"""Strict, deterministic author choice semantics compiled to the platform projection."""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

CHOICE_CAPABILITY = "event.choice_set/1.0.0"
CHOICE_CONTRACT = "se-event-choice-semantics/1.0.0"
_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_CHOICE_REF_SETS = ({"A", "B", "C", "D"}, {"1", "2", "3", "4"})
_SET_FIELDS = {"checkpoint_ref", "phase_ref", "owner_binding", "guard_ref", "mode", "expiry_seconds", "cardinality", "choices"}
_CHOICE_FIELDS = {"choice_ref", "route_ref", "display_key", "label", "purpose", "cost", "risk", "limitations"}


class ChoiceContractError(ValueError):
    def __init__(self, code: str, path: str, reason: str) -> None:
        super().__init__(reason); self.code, self.path, self.reason = code, path, reason


def _fail(code: str, path: str, reason: str) -> None:
    raise ChoiceContractError(code, path, reason)


def _id(value: Any, path: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None: _fail("compiler.choice_ref_invalid", path, "stable lowercase ref is required")
    return value


def _text(value: Any, path: str, maximum: int) -> str:
    if not isinstance(value, str) or value != value.strip() or not value or len(value) > maximum or any(ord(character) < 32 or ord(character) == 127 for character in value): _fail("compiler.choice_text_invalid", path, "normalized bounded non-empty text without control characters is required")
    return value


def _digest(value: Any) -> str:
    def plain(item: Any) -> Any:
        if isinstance(item, Mapping): return {str(key): plain(child) for key, child in item.items()}
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)): return [plain(child) for child in item]
        return item
    raw = json.dumps(plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def choice_semantics_fingerprint(initial_checkpoint_ref: str, choice_sets: Sequence[Mapping[str, Any]]) -> str:
    return _digest({"schema": CHOICE_CONTRACT, "initial_checkpoint_ref": initial_checkpoint_ref, "choice_sets": choice_sets})


def compile_choice_semantics(*, initial_checkpoint_ref: str, choice_sets: Sequence[Mapping[str, Any]], graph: Mapping[str, Any], guard_tree_sha256: str, owner_policy: str = "actor") -> dict[str, Any]:
    nodes = {item["id"]: item for item in graph["nodes"]}
    edges = {item["id"]: item for item in graph["edges"]}
    if initial_checkpoint_ref not in nodes: _fail("compiler.initial_checkpoint_invalid", "initial_checkpoint_ref", "initial checkpoint does not exist")
    adjacency = {ref: [] for ref in nodes}
    for edge in edges.values(): adjacency[edge["from"]].append(edge["to"])
    seen = {initial_checkpoint_ref}; queue = deque([initial_checkpoint_ref])
    while queue:
        for target in adjacency[queue.popleft()]:
            if target not in seen: seen.add(target); queue.append(target)
    if seen != set(nodes): _fail("compiler.initial_checkpoint_unreachable", "initial_checkpoint_ref", "not every checkpoint is reachable from the explicit root")
    if not isinstance(choice_sets, Sequence) or isinstance(choice_sets, (str, bytes, bytearray)) or not choice_sets:
        _fail("compiler.choice_set_missing", "choice_sets", "at least one choice set is required")
    normalized: list[dict[str, Any]] = []; compiled: list[dict[str, Any]] = []; checkpoint_refs: set[str] = set()
    for index, raw in enumerate(choice_sets):
        path = f"choice_sets[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != _SET_FIELDS: _fail("compiler.choice_set_fields_invalid", path, "choice set fields must be exact")
        checkpoint = _id(raw["checkpoint_ref"], f"{path}.checkpoint_ref")
        if checkpoint not in nodes: _fail("compiler.choice_checkpoint_unknown", f"{path}.checkpoint_ref", "choice checkpoint is unknown")
        if checkpoint in checkpoint_refs: _fail("compiler.choice_checkpoint_duplicate", f"{path}.checkpoint_ref", "only one choice set is allowed per checkpoint")
        checkpoint_refs.add(checkpoint)
        phase = _id(raw["phase_ref"], f"{path}.phase_ref")
        if phase != nodes[checkpoint]["kind"]: _fail("compiler.choice_phase_mismatch", f"{path}.phase_ref", "phase must equal checkpoint kind")
        allowed_owners = {"binding.actor.current"} if owner_policy == "actor" else {"binding.account.current", "binding.slot.current"} if owner_policy == "pre_actor_build" else set()
        if raw["owner_binding"] not in allowed_owners: _fail("compiler.choice_owner_invalid", f"{path}.owner_binding", "owner binding is not valid for this exact profile lifecycle")
        owner_binding = raw["owner_binding"]
        if raw["guard_ref"] != "event.guard": _fail("compiler.choice_guard_invalid", f"{path}.guard_ref", "choice must bind the compiled event guard")
        if raw["mode"] != "choice_only": _fail("compiler.choice_mode_invalid", f"{path}.mode", "only choice_only is supported")
        expiry = raw["expiry_seconds"]
        if isinstance(expiry, bool) or not isinstance(expiry, int) or not 1 <= expiry <= 3600: _fail("compiler.choice_expiry_invalid", f"{path}.expiry_seconds", "expiry must be 1..3600 seconds")
        if raw["cardinality"] != {"minimum": 1, "maximum": 1}: _fail("compiler.choice_cardinality_invalid", f"{path}.cardinality", "cardinality must be exactly 1..1")
        choices = raw["choices"]
        if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes, bytearray)) or (len(choices) != 4 if owner_policy == "actor" else not 1 <= len(choices) <= 4): _fail("compiler.choice_cardinality_invalid", f"{path}.choices", "choice count is invalid for this exact profile lifecycle")
        full_choices: list[dict[str, str]] = []; refs: set[str] = set(); display_keys: set[str] = set(); routes: set[str] = set()
        for choice_index, choice in enumerate(choices):
            choice_path = f"{path}.choices[{choice_index}]"
            if not isinstance(choice, Mapping) or set(choice) != _CHOICE_FIELDS: _fail("compiler.choice_fields_invalid", choice_path, "choice fields must be exact")
            choice_ref = choice.get("choice_ref")
            if not isinstance(choice_ref, str) or choice_ref in refs: _fail("compiler.choice_duplicate", f"{choice_path}.choice_ref", "choice refs must be unique")
            refs.add(choice_ref)
            route_ref = _id(choice["route_ref"], f"{choice_path}.route_ref")
            edge = edges.get(route_ref)
            if edge is None or edge["from"] != checkpoint: _fail("compiler.choice_route_invalid", f"{choice_path}.route_ref", "route must be active and leave the current checkpoint")
            if route_ref in routes: _fail("compiler.choice_route_duplicate", f"{choice_path}.route_ref", "each choice must map to a unique route")
            routes.add(route_ref)
            display_key = choice.get("display_key")
            if not isinstance(display_key, str) or display_key in display_keys: _fail("compiler.choice_display_key_duplicate", f"{choice_path}.display_key", "display keys must be unique")
            display_keys.add(display_key)
            item = {"choice_ref": choice_ref, "route_ref": route_ref, "display_key": display_key}
            for field, maximum in (("label", 80), ("purpose", 240), ("cost", 160), ("risk", 160), ("limitations", 160)):
                item[field] = _text(choice[field], f"{choice_path}.{field}", maximum)
            full_choices.append(item)
        if owner_policy == "actor" and refs not in _CHOICE_REF_SETS: _fail("compiler.choice_ref_invalid", f"{path}.choices", "choice refs must be exactly A-D or 1-4")
        if owner_policy == "pre_actor_build" and any(_ID_RE.fullmatch(str(ref)) is None for ref in refs): _fail("compiler.choice_ref_invalid", f"{path}.choices", "pre-actor build choice refs must be stable lowercase refs")
        if not any(display_keys <= values and len(display_keys) == len(choices) for values in _CHOICE_REF_SETS): _fail("compiler.choice_display_key_invalid", f"{path}.choices", "display keys must be a unique canonical subset of A-D or 1-4")
        outgoing = {edge["id"] for edge in edges.values() if edge["from"] == checkpoint}
        if routes != outgoing: _fail("compiler.choice_route_set_mismatch", f"{path}.choices", "choice routes must exactly cover every active outgoing route")
        full_choices.sort(key=lambda item: item["display_key"])
        full = {"checkpoint_ref": checkpoint, "phase_ref": phase, "owner_binding": owner_binding, "guard_ref": "event.guard", "mode": "choice_only", "expiry_seconds": expiry, "cardinality": {"minimum": 1, "maximum": 1}, "choices": full_choices}
        normalized.append(full)
        compiled.append({"checkpoint_ref": checkpoint, "phase_ref": phase, "owner_binding": owner_binding, "guard_tree_sha256": guard_tree_sha256, "mode": "choice_only", "expiry_seconds": expiry, "cardinality": {"minimum": 1, "maximum": 1}, "choices": full_choices})
    normalized.sort(key=lambda item: item["checkpoint_ref"]); compiled.sort(key=lambda item: item["checkpoint_ref"])
    return {"schema": CHOICE_CONTRACT, "initial_checkpoint_ref": initial_checkpoint_ref, "choice_sets": compiled, "choice_semantics_sha256": choice_semantics_fingerprint(initial_checkpoint_ref, compiled)}


def validate_compiled_choice_event(event: Mapping[str, Any]) -> None:
    nodes_value = event.get("checkpoint_graph", {}).get("nodes") if isinstance(event.get("checkpoint_graph"), Mapping) else None
    edges_value = event.get("checkpoint_graph", {}).get("edges") if isinstance(event.get("checkpoint_graph"), Mapping) else None
    choice_sets = event.get("choice_sets")
    initial = event.get("initial_checkpoint_ref")
    platform_features = event.get("required_platform_features")
    if event.get("choice_contract") != CHOICE_CONTRACT or event.get("choice_capability") != CHOICE_CAPABILITY or not isinstance(platform_features, Sequence) or isinstance(platform_features, (str, bytes, bytearray)) or tuple(platform_features) != (CHOICE_CAPABILITY,):
        _fail("engine.choice_contract_invalid", "required_platform_features", "choice platform feature identity is invalid")
    if not isinstance(nodes_value, Sequence) or not isinstance(edges_value, Sequence) or not isinstance(choice_sets, Sequence) or isinstance(choice_sets, (str, bytes, bytearray)) or not choice_sets or not isinstance(initial, str):
        _fail("engine.choice_contract_invalid", "choice_sets", "compiled choice structure is invalid")
    nodes = {item.get("id"): item for item in nodes_value if isinstance(item, Mapping) and isinstance(item.get("id"), str)}
    if len(nodes) != len(nodes_value) or initial not in nodes:
        _fail("engine.choice_contract_invalid", "checkpoint_graph", "compiled checkpoint graph is invalid")
    edge_fields = {"id", "from", "to", "outcome", "public_meaning", "required_capability"}
    edges: dict[str, Mapping[str, Any]] = {}
    for edge_index, edge in enumerate(edges_value):
        edge_path = f"checkpoint_graph.edges[{edge_index}]"
        if not isinstance(edge, Mapping) or set(edge) != edge_fields or any(not isinstance(edge.get(field), str) for field in ("id", "from", "to")) or edge["from"] not in nodes or edge["to"] not in nodes or edge["id"] in edges:
            _fail("engine.choice_contract_invalid", edge_path, "compiled route edge is invalid")
        edges[edge["id"]] = edge
    adjacency = {ref: [] for ref in nodes}
    for edge in edges.values(): adjacency[edge["from"]].append(edge["to"])
    seen = {initial}; queue = deque([initial])
    while queue:
        for target in adjacency[queue.popleft()]:
            if target not in seen: seen.add(target); queue.append(target)
    if seen != set(nodes): _fail("engine.choice_contract_invalid", "initial_checkpoint_ref", "compiled activation root does not reach every checkpoint")
    guard_hash = event.get("guard_tree_sha256")
    checkpoint_refs: set[str] = set()
    for index, item in enumerate(choice_sets):
        path = f"choice_sets[{index}]"
        expected = {"checkpoint_ref", "phase_ref", "owner_binding", "guard_tree_sha256", "mode", "expiry_seconds", "cardinality", "choices"}
        if not isinstance(item, Mapping) or set(item) != expected: _fail("engine.choice_contract_invalid", path, "compiled choice set fields are invalid")
        checkpoint = item["checkpoint_ref"]
        if checkpoint not in nodes or checkpoint in checkpoint_refs or item["phase_ref"] != nodes[checkpoint].get("kind"): _fail("engine.choice_contract_invalid", path, "compiled checkpoint or phase is invalid")
        checkpoint_refs.add(checkpoint)
        owner_policy = "pre_actor_build" if event.get("profile") == "character_build_event" and event.get("profile_version") == "1.0.0" else "actor"
        allowed_owners = {"binding.account.current", "binding.slot.current"} if owner_policy == "pre_actor_build" else {"binding.actor.current"}
        if item["owner_binding"] not in allowed_owners or item["guard_tree_sha256"] != guard_hash or item["mode"] != "choice_only" or item["cardinality"] != {"minimum": 1, "maximum": 1}:
            _fail("engine.choice_contract_invalid", path, "compiled owner guard mode or cardinality is invalid")
        expiry = item["expiry_seconds"]
        choices = item["choices"]
        if isinstance(expiry, bool) or not isinstance(expiry, int) or not 1 <= expiry <= 3600 or not isinstance(choices, Sequence) or isinstance(choices, (str, bytes, bytearray)) or (len(choices) != 4 if owner_policy == "actor" else not 1 <= len(choices) <= 4):
            _fail("engine.choice_contract_invalid", path, "compiled expiry or choices are invalid")
        refs: set[str] = set(); displays: set[str] = set(); routes: set[str] = set()
        for choice_index, choice in enumerate(choices):
            choice_path = f"{path}.choices[{choice_index}]"
            if not isinstance(choice, Mapping) or set(choice) != _CHOICE_FIELDS: _fail("engine.choice_contract_invalid", choice_path, "compiled choice fields are invalid")
            refs.add(choice.get("choice_ref")); displays.add(choice.get("display_key")); routes.add(choice.get("route_ref"))
            if len(refs) != choice_index + 1 or len(displays) != choice_index + 1 or len(routes) != choice_index + 1: _fail("engine.choice_contract_invalid", choice_path, "compiled choice refs must be unique")
            for field, maximum in (("label", 80), ("purpose", 240), ("cost", 160), ("risk", 160), ("limitations", 160)):
                raw_text = choice.get(field)
                if _text(raw_text, f"{choice_path}.{field}", maximum) != raw_text: _fail("engine.choice_contract_invalid", f"{choice_path}.{field}", "compiled rich text is not normalized")
        outgoing = {edge["id"] for edge in edges.values() if edge.get("from") == checkpoint}
        refs_valid = refs in _CHOICE_REF_SETS if owner_policy == "actor" else all(_ID_RE.fullmatch(str(ref)) is not None for ref in refs)
        displays_valid = any(displays <= values and len(displays) == len(choices) for values in _CHOICE_REF_SETS)
        if not refs_valid or not displays_valid or routes != outgoing: _fail("engine.choice_contract_invalid", path, "compiled choice sets are not closed")
        if [choice["display_key"] for choice in choices] != sorted(displays): _fail("engine.choice_contract_invalid", f"{path}.choices", "compiled choices are not in canonical display order")
    if [item["checkpoint_ref"] for item in choice_sets] != sorted(checkpoint_refs): _fail("engine.choice_contract_invalid", "choice_sets", "compiled choice sets are not in canonical checkpoint order")
    if event.get("choice_semantics_sha256") != choice_semantics_fingerprint(initial, choice_sets):
        _fail("engine.choice_contract_invalid", "choice_semantics_sha256", "compiled choice fingerprint mismatches")


__all__ = ["CHOICE_CAPABILITY", "CHOICE_CONTRACT", "ChoiceContractError", "choice_semantics_fingerprint", "compile_choice_semantics", "validate_compiled_choice_event"]
