"""Strict deterministic condition trees and platform-frozen event guard facts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .contracts.port import canonical_fingerprint, freeze_json

CONDITION_TREE_SCHEMA = "se-condition-tree/1.0.0"
GUARD_FACT_SNAPSHOT_SCHEMA = "se-event-guard-fact-snapshot/1.0.0"
GUARD_FACT_CATALOG_SCHEMA = "se-event-guard-fact-catalog/1.0.0"
GUARD_CAPABILITY = "event.guard.evaluate/1.0.0"
_REF_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$")
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_VALUE_TYPES = frozenset({"boolean", "integer", "ref", "ref_set"})
_COMPARE = frozenset({"eq", "ne", "lt", "lte", "gt", "gte", "contains", "not_contains"})
_LOGICAL = frozenset({"all", "any", "not"})


class ConditionContractError(ValueError):
    def __init__(self, code: str, path: str, reason: str) -> None:
        super().__init__(code)
        self.code, self.path, self.reason = code, path, reason


def _fail(code: str, path: str, reason: str) -> None:
    raise ConditionContractError(code, path, reason)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _literal(value_type: str, value: Any, path: str) -> Any:
    if value_type == "boolean":
        if not isinstance(value, bool): _fail("engine.guard_fact_type_invalid", path, "boolean fact is required")
        return value
    if value_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int): _fail("engine.guard_fact_type_invalid", path, "integer fact is required")
        return value
    if value_type == "ref":
        if not isinstance(value, str) or _REF_RE.fullmatch(value) is None: _fail("engine.guard_fact_type_invalid", path, "stable ref is required")
        return value
    if value_type == "ref_set":
        if not isinstance(value, (list, tuple)) or len(value) != len(set(value)) or any(not isinstance(item, str) or _REF_RE.fullmatch(item) is None for item in value):
            _fail("engine.guard_fact_type_invalid", path, "unique stable ref set is required")
        return tuple(sorted(value))
    _fail("engine.guard_fact_type_invalid", path, "fact type is unsupported")


@dataclass(frozen=True, slots=True)
class FactDefinition:
    fact_ref: str
    value_type: str

    def __post_init__(self) -> None:
        if _REF_RE.fullmatch(self.fact_ref) is None or self.value_type not in _VALUE_TYPES:
            _fail("engine.guard_fact_catalog_invalid", "fact_catalog", "fact definition is invalid")

    def to_mapping(self) -> dict[str, str]:
        return {"fact_ref": self.fact_ref, "value_type": self.value_type}


class FactCatalog:
    def __init__(self, definitions: Sequence[FactDefinition]) -> None:
        ordered = tuple(sorted(definitions, key=lambda item: item.fact_ref))
        if not ordered or len({item.fact_ref for item in ordered}) != len(ordered):
            _fail("engine.guard_fact_catalog_invalid", "fact_catalog", "fact refs must be non-empty and unique")
        self.definitions = ordered
        self._by_ref = MappingProxyType({item.fact_ref: item for item in ordered})
        self.fingerprint = canonical_fingerprint(self.to_mapping())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FactCatalog":
        if not isinstance(value, Mapping) or set(value) != {"schema", "facts"} or value.get("schema") != GUARD_FACT_CATALOG_SCHEMA:
            _fail("engine.guard_fact_catalog_invalid", "fact_catalog", "fact catalog fields are invalid")
        raw = value.get("facts")
        if not isinstance(raw, (list, tuple)):
            _fail("engine.guard_fact_catalog_invalid", "fact_catalog.facts", "facts must be a list")
        definitions = []
        for index, item in enumerate(raw):
            if not isinstance(item, Mapping) or set(item) != {"fact_ref", "value_type"}:
                _fail("engine.guard_fact_catalog_invalid", f"fact_catalog.facts[{index}]", "fact fields are invalid")
            definitions.append(FactDefinition(str(item["fact_ref"]), str(item["value_type"])))
        return cls(definitions)

    def resolve(self, fact_ref: str) -> FactDefinition:
        item = self._by_ref.get(fact_ref)
        if item is None: _fail("engine.guard_fact_unknown", "condition.fact_ref", "fact ref is not registered in the Artifact catalog")
        return item

    def to_mapping(self) -> dict[str, Any]:
        return {"schema": GUARD_FACT_CATALOG_SCHEMA, "facts": [item.to_mapping() for item in self.definitions]}


@dataclass(frozen=True, slots=True)
class ConditionTree:
    value: Mapping[str, Any]
    tree_sha256: str
    node_count: int
    max_depth: int

    def to_mapping(self) -> dict[str, Any]:
        return {"schema": CONDITION_TREE_SCHEMA, "root": _plain(self.value), "guard_tree_sha256": self.tree_sha256, "node_count": self.node_count, "max_depth": self.max_depth}


def normalize_condition_tree(value: Mapping[str, Any], catalog: FactCatalog) -> ConditionTree:
    counter = [0]
    maximum = [0]

    def visit(node: Any, depth: int, path: str) -> Mapping[str, Any]:
        if depth > 8: _fail("engine.guard_limit_exceeded", path, "condition depth exceeds 8")
        counter[0] += 1; maximum[0] = max(maximum[0], depth)
        if counter[0] > 64: _fail("engine.guard_limit_exceeded", path, "condition nodes exceed 64")
        if not isinstance(node, Mapping) or not isinstance(node.get("op"), str):
            _fail("engine.guard_condition_invalid", path, "condition node must declare op")
        op = str(node["op"])
        if op in {"all", "any"}:
            if set(node) != {"op", "args"} or not isinstance(node.get("args"), (list, tuple)) or not 1 <= len(node["args"]) <= 16:
                _fail("engine.guard_condition_invalid", path, "all/any requires 1..16 args")
            args = [visit(item, depth + 1, f"{path}.args[{index}]") for index, item in enumerate(node["args"])]
            args.sort(key=lambda item: json.dumps(_plain(item), sort_keys=True, separators=(",", ":")))
            return freeze_json({"op": op, "args": args}, path)
        if op == "not":
            if set(node) != {"op", "arg"}: _fail("engine.guard_condition_invalid", path, "not requires one arg")
            return freeze_json({"op": op, "arg": visit(node["arg"], depth + 1, f"{path}.arg")}, path)
        if op not in _COMPARE or set(node) != {"op", "fact_ref", "value"}:
            _fail("engine.guard_operator_unsupported", path, "operator or fields are unsupported")
        fact_ref = str(node["fact_ref"])
        definition = catalog.resolve(fact_ref)
        if op in {"lt", "lte", "gt", "gte"} and definition.value_type != "integer":
            _fail("engine.guard_type_mismatch", path, "ordered comparison requires integer fact")
        if op in {"contains", "not_contains"}:
            if definition.value_type != "ref_set": _fail("engine.guard_type_mismatch", path, "contains requires ref_set fact")
            normalized = _literal("ref", node["value"], f"{path}.value")
        else:
            normalized = _literal(definition.value_type, node["value"], f"{path}.value")
        return freeze_json({"op": op, "fact_ref": fact_ref, "value": normalized}, path)

    root = visit(value, 1, "guard")
    digest = canonical_fingerprint({"schema": CONDITION_TREE_SCHEMA, "root": root})
    return ConditionTree(root, digest, counter[0], maximum[0])


@dataclass(frozen=True, slots=True)
class GuardFactSnapshot:
    artifact_ref: str
    artifact_sha256: str
    definition_ref: str
    definition_sha256: str
    guard_tree_sha256: str
    fact_catalog_sha256: str
    event_revision: int
    rule_revision: int
    facts: Mapping[str, Any]
    snapshot_fingerprint: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], catalog: FactCatalog) -> "GuardFactSnapshot":
        fields = {"schema", "artifact_ref", "artifact_sha256", "definition_ref", "definition_sha256", "guard_tree_sha256", "fact_catalog_sha256", "event_revision", "rule_revision", "facts", "snapshot_fingerprint"}
        if not isinstance(value, Mapping) or set(value) != fields or value.get("schema") != GUARD_FACT_SNAPSHOT_SCHEMA:
            _fail("engine.guard_snapshot_missing", "rule_snapshot.event_guard", "guard snapshot fields are invalid")
        facts = value.get("facts")
        if not isinstance(facts, Mapping): _fail("engine.guard_fact_type_invalid", "facts", "facts must be an object")
        normalized: dict[str, Any] = {}
        for fact_ref, raw in facts.items():
            if not isinstance(fact_ref, str) or _REF_RE.fullmatch(fact_ref) is None:
                _fail("engine.guard_fact_unknown", "facts", "fact ref is invalid")
            definition = catalog.resolve(fact_ref)
            normalized[fact_ref] = _literal(definition.value_type, raw, f"facts.{fact_ref}")
        ref_fields = ("artifact_ref", "definition_ref")
        hash_fields = ("artifact_sha256", "definition_sha256", "guard_tree_sha256", "fact_catalog_sha256", "snapshot_fingerprint")
        if any(not isinstance(value[name], str) or _REF_RE.fullmatch(value[name]) is None for name in ref_fields) or any(not isinstance(value[name], str) or _HASH_RE.fullmatch(value[name]) is None for name in hash_fields):
            _fail("engine.guard_fingerprint_mismatch", "guard_snapshot", "guard snapshot identity is invalid")
        item = cls(
            value["artifact_ref"], value["artifact_sha256"], value["definition_ref"], value["definition_sha256"],
            value["guard_tree_sha256"], value["fact_catalog_sha256"], value["event_revision"], value["rule_revision"],
            freeze_json(normalized, "facts"), value["snapshot_fingerprint"],
        )
        if any(isinstance(rev, bool) or not isinstance(rev, int) or rev < 0 for rev in (item.event_revision, item.rule_revision)):
            _fail("engine.guard_revision_conflict", "guard_snapshot", "guard revisions are invalid")
        if item.snapshot_fingerprint != canonical_fingerprint(item.fingerprint_material()):
            _fail("engine.guard_fingerprint_mismatch", "snapshot_fingerprint", "guard snapshot fingerprint mismatches")
        return item

    def fingerprint_material(self) -> Mapping[str, Any]:
        return {"schema": GUARD_FACT_SNAPSHOT_SCHEMA, "artifact_ref": self.artifact_ref, "artifact_sha256": self.artifact_sha256, "definition_ref": self.definition_ref, "definition_sha256": self.definition_sha256, "guard_tree_sha256": self.guard_tree_sha256, "fact_catalog_sha256": self.fact_catalog_sha256, "event_revision": self.event_revision, "rule_revision": self.rule_revision, "facts": self.facts}


def evaluate_condition_tree(tree: ConditionTree, snapshot: GuardFactSnapshot, catalog: FactCatalog) -> bool:
    required_refs: set[str] = set()

    def collect(node: Mapping[str, Any]) -> None:
        op = str(node["op"])
        if op in {"all", "any"}:
            for item in node["args"]: collect(item)
        elif op == "not":
            collect(node["arg"])
        else:
            fact_ref = str(node["fact_ref"])
            catalog.resolve(fact_ref)
            required_refs.add(fact_ref)

    collect(tree.value)
    missing = sorted(required_refs - set(snapshot.facts))
    if missing:
        _fail("engine.guard_fact_missing", "facts", "required guard facts are missing: " + ",".join(missing))

    def evaluate(node: Mapping[str, Any]) -> bool:
        op = str(node["op"])
        if op == "all": return all(evaluate(item) for item in node["args"])
        if op == "any": return any(evaluate(item) for item in node["args"])
        if op == "not": return not evaluate(node["arg"])
        fact_ref = str(node["fact_ref"])
        actual, expected = snapshot.facts[fact_ref], node["value"]
        if op == "eq": return actual == expected
        if op == "ne": return actual != expected
        if op == "lt": return actual < expected
        if op == "lte": return actual <= expected
        if op == "gt": return actual > expected
        if op == "gte": return actual >= expected
        if op == "contains": return expected in actual
        if op == "not_contains": return expected not in actual
        _fail("engine.guard_operator_unsupported", "guard", "operator is unsupported")
    return evaluate(tree.value)


__all__ = ["CONDITION_TREE_SCHEMA", "GUARD_CAPABILITY", "GUARD_FACT_CATALOG_SCHEMA", "GUARD_FACT_SNAPSHOT_SCHEMA", "ConditionContractError", "ConditionTree", "FactCatalog", "FactDefinition", "GuardFactSnapshot", "evaluate_condition_tree", "normalize_condition_tree"]
