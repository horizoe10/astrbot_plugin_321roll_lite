"""Pack-authored resource/vitality contracts and deterministic proposal-only evaluation.

This module intentionally has no PlatformBridge, storage, identity, renderer or clock
dependency. It validates frozen author semantics and converts one frozen intent into a
typed proposal. The 321 platform remains the only authority that may validate current
state, perform CAS, commit the effect, or publish receipts/views.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .contracts.port import (
    CancellationCheck, OperationEnvelope, PlatformBridge, Problem, ProblemCode,
    STORY_ENGINE_PORT_VERSION, canonical_fingerprint, freeze_json,
)

_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_RESOURCE_KINDS = frozenset({"vitality", "stamina", "mana", "shield", "stress", "custom"})
_TARGET_BINDINGS = frozenset({"binding.actor.current", "binding.actor.selected"})
_VITALITY_REQUIRES = ("actor.resource_pool/1.0.0", "character.state.effects/1")
_FORBIDDEN_VITALITY_OUTCOMES = ("archive", "death", "permanent_departure", "permanent_injury", "terminal")
_STANDARD_EFFECT_TYPES = frozenset({
    "actor.attribute.set", "actor.attribute.delta", "actor.resource.set", "actor.resource.delta",
    "actor.resource.set_limit", "actor.progress.set", "actor.progress.advance", "actor.status.upsert",
    "actor.status.remove", "actor.descriptor.set",
})
_EFFECT_SCHEMA_FILES = {
    "actor.resource_pool/1.0.0": "actor.resource_pool-1.0.0.schema.json",
    "actor.vitality/1.0.0": "actor.vitality-1.0.0.schema.json",
    "character.state.effects/1": "typed-effect-proposal-1.0.0.schema.json",
}
_RESOURCE_EVALUATOR_CAPABILITIES = frozenset({
    "actor.resource_pool/1.0.0", "actor.vitality/1.0.0", "character.state.effects/1",
})
RESOURCE_EFFECT_EVALUATION_CONTRACT = "se-resource-effect-evaluation/1.0.0"
_ZERO_DIGEST = "sha256:" + "0" * 64


def effect_contract_identities() -> tuple[dict[str, str], ...]:
    """Bind Artifact identities to the exact schemas shipped with the active source."""
    root = Path(__file__).with_name("schemas")
    return tuple({
        "capability_ref": capability,
        "provider_contract_sha256": "sha256:" + hashlib.sha256((root / filename).read_bytes()).hexdigest(),
    } for capability, filename in _EFFECT_SCHEMA_FILES.items())


class ResourceContractError(ValueError):
    """Stable Engine-owned author/evaluator failure category."""

    def __init__(self, code: str, path: str, reason: str) -> None:
        super().__init__(code)
        self.code = code
        self.path = path
        self.reason = reason


def _fail(code: str, path: str, reason: str) -> None:
    raise ResourceContractError(code, path, reason)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _digest(value: Mapping[str, Any] | list[Any]) -> str:
    payload = json.dumps(_plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _exact_fields(value: Mapping[str, Any], required: set[str], path: str) -> None:
    if set(value) != required:
        _fail("engine.resource_definition_invalid", path, "fields do not match the fixed author contract")


def _integer(value: Any, path: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or (minimum is not None and value < minimum):
        _fail("engine.effect_payload_invalid", path, "an integer in the allowed range is required")
    return value


@dataclass(frozen=True, slots=True)
class ResourceDefinition:
    value: Mapping[str, Any]
    definition_sha256: str

    def to_mapping(self) -> dict[str, Any]:
        return _plain(self.value)

    def to_ir_identity(self) -> dict[str, str]:
        return {
            "resource_id": str(self.value["resource_id"]),
            "kind": str(self.value["kind"]),
            "definition_sha256": self.definition_sha256,
        }


class ResourceCatalog:
    schema = "se-actor-resource-definitions/1.0.0"
    capability = "actor.resource_pool/1.0.0"

    def __init__(self, definitions: Iterable[ResourceDefinition]) -> None:
        by_id: dict[str, ResourceDefinition] = {}
        for definition in definitions:
            resource_id = str(definition.value["resource_id"])
            if resource_id in by_id:
                _fail("engine.resource_definition_invalid", "definitions", "resource_id must be unique")
            by_id[resource_id] = definition
        if not by_id:
            _fail("engine.resource_definition_invalid", "definitions", "at least one resource is required")
        self._definitions = MappingProxyType(dict(sorted(by_id.items())))
        self.fingerprint = _digest([item.to_ir_identity() for item in self._definitions.values()])

    @classmethod
    def from_author_document(cls, value: Mapping[str, Any]) -> "ResourceCatalog":
        if not isinstance(value, Mapping) or set(value) != {"schema", "capability", "definitions"}:
            _fail("engine.resource_definition_invalid", "$", "resource document fields are invalid")
        if value.get("schema") != cls.schema or value.get("capability") != cls.capability:
            _fail("engine.resource_definition_invalid", "schema", "resource schema or capability is unsupported")
        raw = value.get("definitions")
        if not isinstance(raw, list) or not raw:
            _fail("engine.resource_definition_invalid", "definitions", "definitions must be a non-empty list")
        return cls(cls._parse_definition(item, index) for index, item in enumerate(raw))

    @staticmethod
    def _parse_definition(value: Any, index: int) -> ResourceDefinition:
        path = f"definitions[{index}]"
        required = {
            "resource_id", "label", "kind", "numeric_type", "minimum", "base_maximum", "initialization",
            "clamp_policy", "overflow_policy", "temporary_layers", "thresholds", "visibility", "tags",
        }
        if not isinstance(value, Mapping):
            _fail("engine.resource_definition_invalid", path, "resource definition must be an object")
        _exact_fields(value, required, path)
        resource_id = value.get("resource_id")
        if not isinstance(resource_id, str) or _ID_RE.fullmatch(resource_id) is None:
            _fail("engine.resource_definition_invalid", f"{path}.resource_id", "resource_id is invalid")
        if not isinstance(value.get("label"), str) or not 1 <= len(value["label"]) <= 80:
            _fail("engine.resource_definition_invalid", f"{path}.label", "label is invalid")
        if value.get("kind") not in _RESOURCE_KINDS or value.get("numeric_type") != "integer":
            _fail("engine.resource_definition_invalid", f"{path}.kind", "kind or numeric type is invalid")
        minimum = value.get("minimum")
        maximum = value.get("base_maximum")
        if any(isinstance(item, bool) or not isinstance(item, int) for item in (minimum, maximum)) or minimum > maximum:
            _fail("engine.resource_definition_invalid", path, "minimum must not exceed base_maximum")
        initialization = value.get("initialization")
        if not isinstance(initialization, Mapping) or initialization.get("mode") not in {"full", "minimum", "fixed"}:
            _fail("engine.resource_definition_invalid", f"{path}.initialization", "initialization mode is invalid")
        if initialization["mode"] == "fixed":
            if set(initialization) != {"mode", "value"} or isinstance(initialization.get("value"), bool) or not isinstance(initialization.get("value"), int) or not minimum <= initialization["value"] <= maximum:
                _fail("engine.resource_definition_invalid", f"{path}.initialization", "fixed initialization is outside the resource range")
        elif set(initialization) != {"mode"}:
            _fail("engine.resource_definition_invalid", f"{path}.initialization", "initialization contains unknown fields")
        if value.get("clamp_policy") not in {"clamp", "reject"} or value.get("overflow_policy") not in {"discard", "reject"}:
            _fail("engine.resource_definition_invalid", path, "clamp or overflow policy is invalid")
        temporary = value.get("temporary_layers")
        if not isinstance(temporary, Mapping) or set(temporary) != {"enabled", "absorb_order", "expiry_policy"} or not isinstance(temporary.get("enabled"), bool) or temporary.get("absorb_order") != "highest_priority_then_oldest" or temporary.get("expiry_policy") != "explicit_receipt_only":
            _fail("engine.resource_definition_invalid", f"{path}.temporary_layers", "temporary layer policy is invalid")
        ResourceCatalog._validate_thresholds(value.get("thresholds"), minimum, maximum, path)
        ResourceCatalog._validate_visibility(value.get("visibility"), path)
        tags = value.get("tags")
        if not isinstance(tags, list) or len(tags) != len(set(tags)) or any(not isinstance(tag, str) or _ID_RE.fullmatch(tag) is None for tag in tags):
            _fail("engine.resource_definition_invalid", f"{path}.tags", "tags must be unique identifiers")
        frozen = freeze_json(_plain(value), path)
        return ResourceDefinition(frozen, _digest(_plain(value)))

    @staticmethod
    def _validate_thresholds(value: Any, minimum: int, maximum: int, path: str) -> None:
        if not isinstance(value, list):
            _fail("engine.resource_definition_invalid", f"{path}.thresholds", "thresholds must be a list")
        seen: set[str] = set()
        for index, item in enumerate(value):
            if not isinstance(item, Mapping) or set(item) not in ({"id", "at_or_below", "signal", "repeat_policy"}, {"id", "at_or_above", "signal", "repeat_policy"}):
                _fail("engine.resource_definition_invalid", f"{path}.thresholds[{index}]", "threshold boundary is invalid")
            if item["id"] in seen or any(not isinstance(item.get(key), str) or _ID_RE.fullmatch(item[key]) is None for key in ("id", "signal")):
                _fail("engine.resource_definition_invalid", f"{path}.thresholds[{index}]", "threshold identifiers must be unique")
            boundary = item.get("at_or_below", item.get("at_or_above"))
            if isinstance(boundary, bool) or not isinstance(boundary, int) or not minimum <= boundary <= maximum or item.get("repeat_policy") not in {"on_crossing", "once_per_operation"}:
                _fail("engine.resource_definition_invalid", f"{path}.thresholds[{index}]", "threshold value or repeat policy is invalid")
            seen.add(item["id"])

    @staticmethod
    def _validate_visibility(value: Any, path: str) -> None:
        if not isinstance(value, Mapping) or value.get("default") != "hidden" or not isinstance(value.get("audiences"), Mapping):
            _fail("engine.resource_definition_invalid", f"{path}.visibility", "visibility must default to hidden")
        audiences = value["audiences"]
        if any(key not in {"actor", "party", "public", "dm", "admin"} or mode not in {"exact", "band", "hidden"} for key, mode in audiences.items()):
            _fail("engine.resource_definition_invalid", f"{path}.visibility.audiences", "audience mode is invalid")
        allowed_fields = {"default", "audiences", "band_basis", "bands"} if "band" in audiences.values() else {"default", "audiences"}
        if set(value) != allowed_fields:
            _fail("engine.resource_definition_invalid", f"{path}.visibility", "band fields must exist only when a band audience is declared")
        if "band" not in audiences.values():
            return
        if value.get("band_basis") != "effective_range_basis_points_floor" or not isinstance(value.get("bands"), list):
            _fail("engine.resource_definition_invalid", f"{path}.visibility.bands", "band basis is invalid")
        cursor = 0
        seen: set[str] = set()
        for index, band in enumerate(sorted(value["bands"], key=lambda item: item.get("minimum_basis_points", -1))):
            if not isinstance(band, Mapping) or set(band) != {"band_id", "minimum_basis_points", "maximum_basis_points", "label"}:
                _fail("engine.resource_definition_invalid", f"{path}.visibility.bands[{index}]", "band fields are invalid")
            lower, upper = band["minimum_basis_points"], band["maximum_basis_points"]
            if band["band_id"] in seen or not isinstance(lower, int) or isinstance(lower, bool) or not isinstance(upper, int) or isinstance(upper, bool) or lower != cursor or upper < lower or upper > 10000:
                _fail("engine.resource_definition_invalid", f"{path}.visibility.bands[{index}]", "bands must cover 0..10000 exactly without gaps or overlap")
            if not isinstance(band["label"], str) or not band["label"]:
                _fail("engine.resource_definition_invalid", f"{path}.visibility.bands[{index}].label", "band label is required")
            seen.add(str(band["band_id"])); cursor = upper + 1
        if cursor != 10001:
            _fail("engine.resource_definition_invalid", f"{path}.visibility.bands", "bands must end at 10000")

    def resolve(self, resource_ref: str) -> ResourceDefinition:
        definition = self._definitions.get(resource_ref)
        if definition is None:
            _fail("engine.resource_definition_invalid", "resource_ref", "resource is not in the frozen catalog")
        return definition

    def to_mapping(self) -> dict[str, Any]:
        return {"schema": self.schema, "capability": self.capability, "definitions": [item.to_mapping() for item in self._definitions.values()]}

    def to_ir(self) -> list[dict[str, str]]:
        return [item.to_ir_identity() for item in self._definitions.values()]

    @classmethod
    def from_artifact(cls, artifact: Mapping[str, Any]) -> "ResourceCatalog":
        contract = next((item for item in artifact.get("effect_contracts", ()) if item.get("capability_ref") == cls.capability), None)
        if not isinstance(contract, Mapping) or not isinstance(contract.get("contract"), Mapping):
            _fail("engine.resource_definition_invalid", "artifact.effect_contracts", "Artifact does not freeze the resource author contract")
        if contract.get("contract_sha256") != _digest(contract["contract"]):
            _fail("engine.resource_definition_invalid", "artifact.effect_contracts", "frozen resource contract fingerprint mismatches")
        catalog = cls.from_author_document(contract["contract"])
        if catalog.to_ir() != artifact.get("resource_definitions") or catalog.fingerprint != artifact.get("resource_catalog_sha256"):
            _fail("engine.resource_definition_invalid", "artifact.resource_definitions", "resource catalog identity mismatches the frozen contract")
        return catalog


@dataclass(frozen=True, slots=True)
class VitalityContract:
    value: Mapping[str, Any]

    @classmethod
    def from_author_document(cls, value: Mapping[str, Any], resources: ResourceCatalog) -> "VitalityContract":
        required_fields = {
            "schema", "capability", "requires", "vitality_resources", "damage_tags", "healing_rules",
            "temporary_vitality", "depletion_policy", "allowed_followups", "forbidden_outcomes", "intent_mappings",
        }
        if not isinstance(value, Mapping) or set(value) != required_fields or value.get("schema") != "se-actor-vitality-authoring/1.0.0" or value.get("capability") != "actor.vitality/1.0.0":
            _fail("engine.resource_definition_invalid", "vitality", "vitality document fields are invalid")
        if tuple(value.get("requires", ())) != _VITALITY_REQUIRES:
            _fail("engine.vitality_dependency_missing", "vitality.requires", "resource_pool and character effects are required in fixed order")
        refs = value.get("vitality_resources")
        if not isinstance(refs, list) or not refs or len(refs) != len(set(refs)):
            _fail("engine.resource_definition_invalid", "vitality.vitality_resources", "vitality resources must be unique")
        for resource_ref in refs:
            if resources.resolve(str(resource_ref)).value["kind"] != "vitality":
                _fail("engine.resource_definition_invalid", "vitality.vitality_resources", "every vitality resource must have kind vitality")
        if value.get("depletion_policy") != "signal_only" or tuple(value.get("forbidden_outcomes", ())) != _FORBIDDEN_VITALITY_OUTCOMES:
            _fail("engine.vitality_terminal_forbidden", "vitality.depletion_policy", "Engine may emit a depletion signal but never a terminal outcome")
        if value.get("healing_rules") != {"base_clamp": "effective_maximum", "temporary_replenishment": "explicit_temporary_intent_only"} or value.get("temporary_vitality") != {"damage_absorb_order": "temporary_before_base", "healing_target": "base_only"}:
            _fail("engine.resource_definition_invalid", "vitality", "healing or temporary vitality policy is invalid")
        expected_mappings = {"damage": "actor.resource.delta", "heal": "actor.resource.delta", "temporary_add": "actor.resource.delta", "temporary_remove": "actor.resource.delta", "depleted": "actor.status.upsert"}
        if value.get("intent_mappings") != expected_mappings:
            _fail("engine.resource_definition_invalid", "vitality.intent_mappings", "intent mappings must target standard effects")
        if set(value.get("allowed_followups", ())) - {"rescue", "actor_fate_candidate", "human_dm"}:
            _fail("engine.vitality_terminal_forbidden", "vitality.allowed_followups", "unsupported follow-up could claim platform authority")
        if not value.get("allowed_followups") or len(value["allowed_followups"]) != len(set(value["allowed_followups"])):
            _fail("engine.vitality_terminal_forbidden", "vitality.allowed_followups", "follow-ups must be a non-empty unique list")
        tags = value.get("damage_tags")
        if not isinstance(tags, list) or len(tags) != len(set(tags)) or any(not isinstance(tag, str) or _ID_RE.fullmatch(tag) is None for tag in tags):
            _fail("engine.resource_definition_invalid", "vitality.damage_tags", "damage tags must be unique identifiers")
        return cls(freeze_json(_plain(value), "vitality"))

    def to_mapping(self) -> dict[str, Any]:
        return _plain(self.value)

    @classmethod
    def from_artifact(cls, artifact: Mapping[str, Any], resources: ResourceCatalog) -> "VitalityContract | None":
        contract = next((item for item in artifact.get("effect_contracts", ()) if item.get("capability_ref") == "actor.vitality/1.0.0"), None)
        if contract is None:
            return None
        if not isinstance(contract, Mapping) or not isinstance(contract.get("contract"), Mapping) or contract.get("contract_sha256") != _digest(contract["contract"]):
            _fail("engine.resource_definition_invalid", "artifact.effect_contracts", "frozen vitality contract fingerprint mismatches")
        return cls.from_author_document(contract["contract"], resources)


@dataclass(frozen=True, slots=True)
class ActorResourceSnapshot:
    """Read-only platform-frozen resource state used only for deterministic preview."""

    actor_binding: str
    resource_ref: str
    definition_sha256: str
    base_current: int
    base_maximum: int
    effective_maximum: int
    temporary_layers: tuple[Mapping[str, Any], ...]
    modifier_receipt_refs: tuple[str, ...]
    threshold_states: Mapping[str, bool]
    audience_policy_sha256: str
    actor_revision: int
    snapshot_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "temporary_layers", tuple(freeze_json(item, "temporary_layers") for item in self.temporary_layers))
        object.__setattr__(self, "modifier_receipt_refs", tuple(self.modifier_receipt_refs))
        object.__setattr__(self, "threshold_states", freeze_json(self.threshold_states, "threshold_states"))
        if self.actor_binding not in _TARGET_BINDINGS or _REF_RE.fullmatch(self.resource_ref) is None:
            _fail("engine.resource_snapshot_invalid", "snapshot", "actor binding or resource reference is invalid")
        if any(_HASH_RE.fullmatch(item) is None for item in (self.definition_sha256, self.audience_policy_sha256, self.snapshot_fingerprint)):
            _fail("engine.resource_snapshot_invalid", "snapshot", "snapshot hashes are invalid")
        resource_numbers = (self.base_current, self.base_maximum, self.effective_maximum)
        if (
            any(isinstance(item, bool) or not isinstance(item, int) for item in resource_numbers)
            or isinstance(self.actor_revision, bool)
            or not isinstance(self.actor_revision, int)
            or self.actor_revision < 0
            or self.base_current > self.effective_maximum
            or self.base_maximum > self.effective_maximum
        ):
            _fail("engine.resource_snapshot_invalid", "snapshot", "snapshot numeric bounds are invalid")
        seen_layers: set[str] = set()
        for index, layer in enumerate(self.temporary_layers):
            if set(layer) != {"layer_ref", "amount", "priority", "created_order"} or _REF_RE.fullmatch(str(layer.get("layer_ref", ""))) is None:
                _fail("engine.resource_snapshot_invalid", f"temporary_layers[{index}]", "temporary layer fields are invalid")
            if layer["layer_ref"] in seen_layers or any(isinstance(layer.get(key), bool) or not isinstance(layer.get(key), int) or layer[key] < 0 for key in ("amount", "priority", "created_order")):
                _fail("engine.resource_snapshot_invalid", f"temporary_layers[{index}]", "temporary layer values are invalid")
            seen_layers.add(str(layer["layer_ref"]))
        if len(self.modifier_receipt_refs) != len(set(self.modifier_receipt_refs)) or any(_REF_RE.fullmatch(item) is None for item in self.modifier_receipt_refs):
            _fail("engine.resource_snapshot_invalid", "modifier_receipt_refs", "modifier receipts must be unique references")
        if any(not isinstance(value, bool) for value in self.threshold_states.values()):
            _fail("engine.resource_snapshot_invalid", "threshold_states", "threshold states must be boolean")
        if self.snapshot_fingerprint != _digest(self.fingerprint_material()):
            _fail("engine.resource_snapshot_invalid", "snapshot_fingerprint", "snapshot fingerprint mismatches its frozen fields")

    def fingerprint_material(self) -> dict[str, Any]:
        return {
            "schema": "se-actor-resource-snapshot/1.0.0",
            "actor_binding": self.actor_binding,
            "resource_ref": self.resource_ref,
            "definition_sha256": self.definition_sha256,
            "base_current": self.base_current,
            "base_maximum": self.base_maximum,
            "effective_maximum": self.effective_maximum,
            "temporary_layers": _plain(self.temporary_layers),
            "modifier_receipt_refs": list(self.modifier_receipt_refs),
            "threshold_states": _plain(self.threshold_states),
            "audience_policy_sha256": self.audience_policy_sha256,
            "actor_revision": self.actor_revision,
        }

    def to_mapping(self) -> dict[str, Any]:
        return {**self.fingerprint_material(), "snapshot_fingerprint": self.snapshot_fingerprint}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ActorResourceSnapshot":
        required = {
            "schema", "actor_binding", "resource_ref", "definition_sha256", "base_current", "base_maximum",
            "effective_maximum", "temporary_layers", "modifier_receipt_refs", "threshold_states",
            "audience_policy_sha256", "actor_revision", "snapshot_fingerprint",
        }
        if not isinstance(value, Mapping) or set(value) != required or value.get("schema") != "se-actor-resource-snapshot/1.0.0":
            _fail("engine.resource_snapshot_invalid", "snapshot", "snapshot fields are invalid")
        return cls(**{key: value[key] for key in required if key != "schema"})


@dataclass(frozen=True, slots=True)
class TypedEffectProposal:
    proposal_ref: str
    operation_ref: str
    request_fingerprint: str
    source_capability_ref: str
    effect_type: str
    target_binding: str
    expected_revisions: Mapping[str, int]
    payload: Mapping[str, Any]
    source: Mapping[str, Any]
    reversible: bool
    dedupe_key: str
    atomic_group_ref: str

    def __post_init__(self) -> None:
        # Freeze caller-owned containers so proposal equality and retry replay remain stable.
        object.__setattr__(self, "expected_revisions", freeze_json(self.expected_revisions, "expected_revisions"))
        object.__setattr__(self, "payload", freeze_json(self.payload, "payload"))
        object.__setattr__(self, "source", freeze_json(self.source, "source"))
        for name in ("proposal_ref", "operation_ref", "dedupe_key", "atomic_group_ref"):
            if _REF_RE.fullmatch(str(getattr(self, name))) is None:
                _fail("engine.effect_payload_invalid", name, "proposal reference is invalid")
        if _HASH_RE.fullmatch(self.request_fingerprint) is None:
            _fail("engine.effect_payload_invalid", "request_fingerprint", "request fingerprint is invalid")
        if self.source_capability_ref not in {"actor.resource_pool/1.0.0", "actor.vitality/1.0.0"} or self.effect_type not in _STANDARD_EFFECT_TYPES:
            _fail("engine.effect_payload_invalid", "effect_type", "effect capability or type is invalid")
        if self.target_binding not in _TARGET_BINDINGS:
            _fail("engine.target_binding_invalid", "target_binding", "only frozen actor bindings are accepted")
        if set(self.expected_revisions) != {"actor_revision", "room_revision"} or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in self.expected_revisions.values()):
            _fail("engine.effect_payload_invalid", "expected_revisions", "actor and room revisions are required")
        if not isinstance(self.reversible, bool):
            _fail("engine.effect_payload_invalid", "reversible", "reversible must be boolean")
        if set(self.source) != {"source_ref", "reason_code", "cause_refs"} or any(_REF_RE.fullmatch(str(self.source.get(key, ""))) is None for key in ("source_ref", "reason_code")):
            _fail("engine.effect_payload_invalid", "source", "source fields are invalid")
        cause_refs = self.source.get("cause_refs")
        if not isinstance(cause_refs, tuple) or not cause_refs or len(cause_refs) != len(set(cause_refs)) or any(_REF_RE.fullmatch(str(item)) is None for item in cause_refs):
            _fail("engine.effect_payload_invalid", "source.cause_refs", "cause_refs must be non-empty unique references")
        self._validate_payload()

    def _validate_payload(self) -> None:
        payload = self.payload
        if self.effect_type in {"actor.resource.set", "actor.resource.delta"}:
            required = {"resource_ref", "amount", "layer", "threshold_handling"}
            optional = {"temporary_layer_ref", "temporary_priority"}
            if not required <= set(payload) or set(payload) - required - optional or payload.get("layer") not in {"base", "temporary"} or payload.get("threshold_handling") != "propose_crossing_signals":
                _fail("engine.effect_payload_invalid", "payload", "resource value effect payload is invalid")
            _integer(payload.get("amount"), "payload.amount")
            if payload["layer"] == "temporary" and _REF_RE.fullmatch(str(payload.get("temporary_layer_ref", ""))) is None:
                _fail("engine.effect_payload_invalid", "payload.temporary_layer_ref", "temporary layer reference is required")
        elif self.effect_type == "actor.resource.set_limit":
            if set(payload) != {"resource_ref", "maximum", "current_overflow"} or payload.get("current_overflow") not in {"clamp", "reject"}:
                _fail("engine.effect_payload_invalid", "payload", "resource limit effect payload is invalid")
            _integer(payload.get("maximum"), "payload.maximum")
        elif self.effect_type == "actor.status.upsert":
            if set(payload) != {"status_ref", "state", "stacks"} or payload.get("state") not in {"active", "suppressed"} or _integer(payload.get("stacks"), "payload.stacks", minimum=1) < 1:
                _fail("engine.effect_payload_invalid", "payload", "status upsert payload is invalid")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": "se-character-effect-proposal/1.0.0",
            "proposal_ref": self.proposal_ref,
            "operation_ref": self.operation_ref,
            "request_fingerprint": self.request_fingerprint,
            "source_capability_ref": self.source_capability_ref,
            "effect_contract": "character.state.effects/1",
            "effect_type": self.effect_type,
            "target_binding": self.target_binding,
            "expected_revisions": _plain(self.expected_revisions),
            "payload": _plain(self.payload),
            "source": _plain(self.source),
            "reversible": self.reversible,
            "dedupe_key": self.dedupe_key,
            "atomic_group_ref": self.atomic_group_ref,
        }


class ResourceEffectEvaluationStatus(StrEnum):
    PROPOSED = "proposed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


_INTENT_PAYLOAD_FIELDS = {
    "actor.resource_pool.delta": {"resource_ref", "source_ref", "reason_code", "amount"},
    "actor.resource_pool.set": {"resource_ref", "source_ref", "reason_code", "amount", "layer"},
    "actor.resource_pool.set_limit": {"resource_ref", "source_ref", "reason_code", "maximum", "current_overflow"},
    "actor.vitality.damage": {"resource_ref", "source_ref", "reason_code", "operation", "base_amount", "damage_tags", "modifier_policy", "threshold_handling"},
    "actor.vitality.heal": {"resource_ref", "source_ref", "reason_code", "operation", "base_amount", "modifier_policy", "threshold_handling"},
    "actor.vitality.temporary.add": {"resource_ref", "source_ref", "reason_code", "operation", "base_amount", "temporary_layer_ref", "temporary_priority", "modifier_policy", "threshold_handling"},
    "actor.vitality.temporary.remove": {"resource_ref", "source_ref", "reason_code", "operation", "base_amount", "temporary_layer_ref", "modifier_policy", "threshold_handling"},
    "actor.vitality.depleted": {"resource_ref", "source_ref", "reason_code"},
}


def _validate_intent_payload_fields(intent_type: str, payload: Mapping[str, Any]) -> None:
    exact = _INTENT_PAYLOAD_FIELDS.get(intent_type)
    if exact is None or set(payload) != exact:
        _fail("engine.effect_payload_invalid", "intent.payload", "payload fields do not match the exact typed intent contract")
    for name in ("resource_ref", "source_ref", "reason_code"):
        if _REF_RE.fullmatch(str(payload.get(name, ""))) is None:
            _fail("engine.effect_payload_invalid", f"intent.payload.{name}", "payload reference is invalid")
    if "amount" in payload and (isinstance(payload["amount"], bool) or not isinstance(payload["amount"], int)):
        _fail("engine.effect_payload_invalid", "intent.payload.amount", "amount must be an integer")
    if "base_amount" in payload and (isinstance(payload["base_amount"], bool) or not isinstance(payload["base_amount"], int) or payload["base_amount"] < 1):
        _fail("engine.effect_payload_invalid", "intent.payload.base_amount", "base_amount must be a positive integer")
    if "maximum" in payload and (isinstance(payload["maximum"], bool) or not isinstance(payload["maximum"], int)):
        _fail("engine.effect_payload_invalid", "intent.payload.maximum", "maximum must be an integer")
    operations = {
        "actor.vitality.damage": "damage", "actor.vitality.heal": "heal",
        "actor.vitality.temporary.add": "temporary_add", "actor.vitality.temporary.remove": "temporary_remove",
    }
    if intent_type in operations and payload.get("operation") != operations[intent_type]:
        _fail("engine.effect_payload_invalid", "intent.payload.operation", "operation does not match intent_type")
    if "damage_tags" in payload:
        tags = payload["damage_tags"]
        if not isinstance(tags, (list, tuple)) or len(tags) != len(set(tags)) or any(_REF_RE.fullmatch(str(tag)) is None for tag in tags):
            _fail("engine.effect_payload_invalid", "intent.payload.damage_tags", "damage tags must be unique references")
    if "modifier_policy" in payload and payload["modifier_policy"] != "consume_frozen_rule_receipts":
        _fail("engine.effect_payload_invalid", "intent.payload.modifier_policy", "modifier policy is invalid")
    if "threshold_handling" in payload and payload["threshold_handling"] != "emit_signals":
        _fail("engine.effect_payload_invalid", "intent.payload.threshold_handling", "threshold handling is invalid")
    if "layer" in payload and payload["layer"] not in {"base", "temporary"}:
        _fail("engine.effect_payload_invalid", "intent.payload.layer", "resource layer is invalid")
    if "current_overflow" in payload and payload["current_overflow"] not in {"clamp", "reject"}:
        _fail("engine.effect_payload_invalid", "intent.payload.current_overflow", "overflow policy is invalid")
    if "temporary_layer_ref" in payload and _REF_RE.fullmatch(str(payload["temporary_layer_ref"])) is None:
        _fail("engine.effect_payload_invalid", "intent.payload.temporary_layer_ref", "temporary layer reference is invalid")
    if "temporary_priority" in payload and (isinstance(payload["temporary_priority"], bool) or not isinstance(payload["temporary_priority"], int) or payload["temporary_priority"] < 0):
        _fail("engine.effect_payload_invalid", "intent.payload.temporary_priority", "temporary priority is invalid")


@dataclass(frozen=True, slots=True)
class ResourceEffectEvaluationRequest:
    """Public Port extension request; platform callers never import evaluator internals."""

    envelope: OperationEnvelope
    artifact_ref: str
    artifact_sha256: str
    allowed_capability_refs: tuple[str, ...]
    capability_closure_sha256: str
    intent: Mapping[str, Any]
    resource_snapshot: ActorResourceSnapshot
    proposal_ref: str
    dedupe_key: str
    atomic_group_ref: str

    def __post_init__(self) -> None:
        if self.envelope.operation_type != "evaluate_resource_effect":
            _fail("engine.effect_payload_invalid", "envelope.operation_type", "resource evaluator operation type is invalid")
        for name in ("artifact_ref", "proposal_ref", "dedupe_key", "atomic_group_ref"):
            if _REF_RE.fullmatch(str(getattr(self, name))) is None:
                _fail("engine.effect_payload_invalid", name, "resource evaluator reference is invalid")
        if _HASH_RE.fullmatch(self.artifact_sha256) is None:
            _fail("engine.effect_payload_invalid", "artifact_sha256", "Artifact fingerprint is invalid")
        refs = tuple(self.allowed_capability_refs)
        if not refs or len(refs) != len(set(refs)) or not set(refs) <= _RESOURCE_EVALUATOR_CAPABILITIES:
            _fail("engine.effect_capability_missing", "allowed_capability_refs", "unique registered versioned capability closure is required")
        object.__setattr__(self, "allowed_capability_refs", refs)
        if self.capability_closure_sha256 != canonical_fingerprint({"allowed_capability_refs": refs}):
            _fail("engine.result_stale", "capability_closure_sha256", "capability closure fingerprint mismatches")
        object.__setattr__(self, "intent", freeze_json(self.intent, "intent"))
        required_intent_fields = {"capability_ref", "intent_type", "target_binding", "payload", "expected_revisions", "operation_ref", "request_fingerprint"}
        if set(self.intent) != required_intent_fields:
            _fail("engine.effect_payload_invalid", "intent", "intent fields do not match the exact typed contract")
        payload = self.intent.get("payload")
        if not isinstance(payload, Mapping):
            _fail("engine.effect_payload_invalid", "intent.payload", "typed intent payload is required")
        forbidden = {"death", "archive", "terminal", "permanent_injury", "permanent_departure"}
        if any(str(key).casefold() in forbidden or str(item).casefold() in forbidden for key, item in payload.items()):
            _fail("engine.vitality_terminal_forbidden", "intent.payload", "terminal actor outcomes are platform-owned and forbidden")
        _validate_intent_payload_fields(str(self.intent.get("intent_type") or ""), payload)
        if not isinstance(self.resource_snapshot, ActorResourceSnapshot):
            _fail("engine.resource_snapshot_invalid", "resource_snapshot", "typed resource snapshot is required")
        if self.envelope.expected_revision != self.resource_snapshot.actor_revision:
            _fail("engine.revision_conflict", "envelope.expected_revision", "request revision differs from the frozen actor snapshot")
        intent_revisions = self.intent.get("expected_revisions")
        if (
            not isinstance(intent_revisions, Mapping)
            or set(intent_revisions) != {"actor_revision", "room_revision"}
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in intent_revisions.values())
            or intent_revisions.get("actor_revision") != self.resource_snapshot.actor_revision
        ):
            _fail("engine.revision_conflict", "intent.expected_revisions.actor_revision", "intent revision differs from the frozen actor snapshot")
        if self.intent.get("operation_ref") != self.envelope.operation_ref:
            _fail("engine.result_stale", "intent.operation_ref", "intent operation does not match the envelope")
        if self.intent.get("request_fingerprint") != self.envelope.request_fingerprint:
            _fail("engine.result_stale", "intent.request_fingerprint", "intent fingerprint does not match the envelope")
        if self.intent.get("capability_ref") not in refs or "character.state.effects/1" not in refs:
            _fail("engine.effect_capability_missing", "allowed_capability_refs", "intent and character effect capabilities must be explicitly frozen")
        capability_base = str(self.intent.get("capability_ref")).rsplit("/", 1)[0]
        if not str(self.intent.get("intent_type")).startswith(capability_base + "."):
            _fail("engine.effect_payload_invalid", "intent.intent_type", "intent type does not belong to its capability")
        if self.envelope.request_fingerprint != resource_effect_request_fingerprint(self):
            _fail("engine.result_stale", "envelope.request_fingerprint", "resource evaluator request fingerprint mismatches")

    def fingerprint_material(self) -> dict[str, Any]:
        intent_material = _plain(self.intent)
        intent_material.pop("request_fingerprint", None)
        return {
            "schema": RESOURCE_EFFECT_EVALUATION_CONTRACT,
            "envelope": {
                "engine_contract_version": self.envelope.engine_contract_version,
                "operation_ref": self.envelope.operation_ref,
                "trace_ref": self.envelope.trace_ref,
                "idempotency_key": self.envelope.idempotency_key,
                "deadline_at": self.envelope.deadline_at,
                "session_ref": self.envelope.session_ref,
                "expected_revision": self.envelope.expected_revision,
                "operation_type": self.envelope.operation_type,
            },
            "artifact_ref": self.artifact_ref,
            "artifact_sha256": self.artifact_sha256,
            "allowed_capability_refs": self.allowed_capability_refs,
            "capability_closure_sha256": self.capability_closure_sha256,
            "intent": intent_material,
            "resource_snapshot": self.resource_snapshot.to_mapping(),
            "proposal_ref": self.proposal_ref,
            "dedupe_key": self.dedupe_key,
            "atomic_group_ref": self.atomic_group_ref,
        }


def resource_effect_request_fingerprint(request: ResourceEffectEvaluationRequest | Mapping[str, Any]) -> str:
    """Calculate the extension fingerprint from either the public DTO or raw JSON payload."""
    if isinstance(request, ResourceEffectEvaluationRequest):
        material = request.fingerprint_material()
    else:
        value = _plain(request)
        envelope = dict(value["envelope"])
        envelope.pop("request_fingerprint", None)
        intent = dict(value["intent"])
        intent.pop("request_fingerprint", None)
        material = {
            "schema": RESOURCE_EFFECT_EVALUATION_CONTRACT,
            "envelope": envelope,
            "artifact_ref": value["artifact_ref"],
            "artifact_sha256": value["artifact_sha256"],
            "allowed_capability_refs": value["allowed_capability_refs"],
            "capability_closure_sha256": value["capability_closure_sha256"],
            "intent": intent,
            "resource_snapshot": value["resource_snapshot"],
            "proposal_ref": value["proposal_ref"],
            "dedupe_key": value["dedupe_key"],
            "atomic_group_ref": value["atomic_group_ref"],
        }
    return canonical_fingerprint(material)


@dataclass(frozen=True, slots=True)
class ResourceEffectEvaluationResult:
    engine_contract_version: str
    operation_ref: str
    request_fingerprint: str
    expected_revision: int
    status: ResourceEffectEvaluationStatus
    character_effect_proposal: TypedEffectProposal | None
    preview: Mapping[str, Any] | None
    problems: tuple[Problem, ...]
    result_fingerprint: str

    def __post_init__(self) -> None:
        if self.engine_contract_version != STORY_ENGINE_PORT_VERSION:
            _fail("engine.contract_incompatible", "engine_contract_version", "Engine Port contract is incompatible")
        if self.status is ResourceEffectEvaluationStatus.PROPOSED and (self.character_effect_proposal is None or self.preview is None):
            _fail("engine.output_invalid", "result", "proposed result requires a proposal and preview")
        if self.status in {ResourceEffectEvaluationStatus.CANCELLED, ResourceEffectEvaluationStatus.TIMED_OUT} and (self.character_effect_proposal is not None or self.preview is not None):
            _fail("engine.output_invalid", "result", "cancelled or timed out result cannot carry proposals")
        if _HASH_RE.fullmatch(self.result_fingerprint) is None:
            _fail("engine.output_invalid", "result_fingerprint", "result fingerprint is invalid")
        if self.preview is not None:
            object.__setattr__(self, "preview", freeze_json(self.preview, "preview"))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": RESOURCE_EFFECT_EVALUATION_CONTRACT,
            "engine_contract_version": self.engine_contract_version,
            "operation_ref": self.operation_ref,
            "request_fingerprint": self.request_fingerprint,
            "expected_revision": self.expected_revision,
            "status": self.status.value,
            "character_effect_proposal": None if self.character_effect_proposal is None else self.character_effect_proposal.to_mapping(),
            "preview": None if self.preview is None else _plain(self.preview),
            "problems": [_problem_mapping(item) for item in self.problems],
            "result_fingerprint": self.result_fingerprint,
        }


def _problem_mapping(problem: Problem) -> dict[str, Any]:
    return {
        "code": problem.code.value,
        "failed_operation": problem.failed_operation,
        "reason": problem.reason,
        "automatic_handling": problem.automatic_handling,
        "next_action": problem.next_action,
        "retryable": problem.retryable,
    }


def resource_effect_result_fingerprint(result: ResourceEffectEvaluationResult) -> str:
    value = result.to_mapping()
    value.pop("schema")
    value.pop("engine_contract_version")
    value.pop("result_fingerprint")
    return canonical_fingerprint(value)


class ResourceEffectEvaluationService:
    """Pack-bound public evaluator with cancellation/deadline and late-result closure."""

    def __init__(self, evaluator: "DeterministicResourceEvaluator", *, artifact_ref: str, artifact_sha256: str, clock: Callable[[], datetime] | None = None) -> None:
        self.evaluator = evaluator
        self.artifact_ref = artifact_ref
        self.artifact_sha256 = artifact_sha256
        self._clock = clock or (lambda: datetime.now(UTC))

    async def evaluate(self, request: ResourceEffectEvaluationRequest, bridge: PlatformBridge) -> ResourceEffectEvaluationResult:
        if (request.artifact_ref, request.artifact_sha256) != (self.artifact_ref, self.artifact_sha256):
            _fail("engine.result_stale", "artifact", "request Artifact does not match the configured pack")
        check = CancellationCheck(request.envelope.operation_ref, request.envelope.request_fingerprint)
        if (await bridge.is_cancelled(check)).cancelled:
            return self._terminal(request, ResourceEffectEvaluationStatus.CANCELLED, ProblemCode.CANCELLED, "platform cancelled the operation")
        if self._clock() >= datetime.fromisoformat(request.envelope.deadline_at.replace("Z", "+00:00")):
            return self._terminal(request, ResourceEffectEvaluationStatus.TIMED_OUT, ProblemCode.DEADLINE_EXCEEDED, "resource evaluation deadline expired")
        proposal = self.evaluator.evaluate(
            request.intent, proposal_ref=request.proposal_ref, dedupe_key=request.dedupe_key,
            atomic_group_ref=request.atomic_group_ref, allowed_capabilities=request.allowed_capability_refs,
            snapshot=request.resource_snapshot,
        )
        preview = self.evaluator.preview(request.intent, request.resource_snapshot)
        if (await bridge.is_cancelled(check)).cancelled:
            return self._terminal(request, ResourceEffectEvaluationStatus.CANCELLED, ProblemCode.CANCELLED, "platform cancelled before result delivery")
        if self._clock() >= datetime.fromisoformat(request.envelope.deadline_at.replace("Z", "+00:00")):
            return self._terminal(request, ResourceEffectEvaluationStatus.TIMED_OUT, ProblemCode.DEADLINE_EXCEEDED, "resource evaluation result expired")
        return self._finalize(request, ResourceEffectEvaluationStatus.PROPOSED, proposal=proposal, preview=preview)

    def _terminal(self, request: ResourceEffectEvaluationRequest, status: ResourceEffectEvaluationStatus, code: ProblemCode, reason: str) -> ResourceEffectEvaluationResult:
        problem = Problem(code, "evaluate resource effect", reason, "no proposal was returned", "refresh the frozen snapshot and start a new operation")
        return self._finalize(request, status, problems=(problem,))

    @staticmethod
    def _finalize(request: ResourceEffectEvaluationRequest, status: ResourceEffectEvaluationStatus, *, proposal: TypedEffectProposal | None = None, preview: Mapping[str, Any] | None = None, problems: tuple[Problem, ...] = ()) -> ResourceEffectEvaluationResult:
        result = ResourceEffectEvaluationResult(
            STORY_ENGINE_PORT_VERSION, request.envelope.operation_ref, request.envelope.request_fingerprint,
            request.envelope.expected_revision, status, proposal, preview, problems, _ZERO_DIGEST,
        )
        return replace(result, result_fingerprint=resource_effect_result_fingerprint(result))


class DeterministicResourceEvaluator:
    """Pure intent-to-proposal mapper; it never reads or mutates authoritative actor state."""

    def __init__(self, resources: ResourceCatalog, vitality: VitalityContract | None = None) -> None:
        self.resources = resources
        self.vitality = vitality

    @classmethod
    def from_artifact(cls, artifact: Mapping[str, Any]) -> "DeterministicResourceEvaluator":
        """Rebuild only from frozen Artifact semantics, enabling safe process restart/retry."""
        resources = ResourceCatalog.from_artifact(artifact)
        return cls(resources, VitalityContract.from_artifact(artifact, resources))

    def evaluate(
        self,
        intent: Mapping[str, Any],
        *,
        proposal_ref: str,
        dedupe_key: str,
        atomic_group_ref: str,
        allowed_capabilities: Iterable[str] = (),
        snapshot: ActorResourceSnapshot | Mapping[str, Any] | None = None,
    ) -> TypedEffectProposal:
        # Capability closure is checked before payload mapping, preventing an intent from
        # smuggling a standard state effect when the platform did not freeze that capability.
        allowed = set(allowed_capabilities)
        if "character.state.effects/1" not in allowed:
            _fail("engine.effect_capability_missing", "allowed_capabilities", "character.state.effects/1 is required")
        required = {"capability_ref", "intent_type", "target_binding", "payload", "expected_revisions", "operation_ref", "request_fingerprint"}
        if not isinstance(intent, Mapping) or set(intent) != required or not isinstance(intent.get("payload"), Mapping):
            _fail("engine.effect_payload_invalid", "intent", "intent fields are invalid")
        capability = str(intent["capability_ref"])
        intent_type = str(intent["intent_type"])
        if capability not in {"actor.resource_pool/1.0.0", "actor.vitality/1.0.0"} or not intent_type.startswith(capability.split("/", 1)[0] + "."):
            _fail("engine.effect_payload_invalid", "intent_type", "intent does not belong to its source capability")
        if capability not in allowed:
            _fail("engine.effect_capability_missing", "allowed_capabilities", "intent capability is not in the frozen closure")
        if capability == "actor.vitality/1.0.0" and self.vitality is None:
            _fail("engine.vitality_dependency_missing", "intent.capability_ref", "vitality contract is not configured")
        if snapshot is not None:
            frozen_snapshot = snapshot if isinstance(snapshot, ActorResourceSnapshot) else ActorResourceSnapshot.from_mapping(snapshot)
            self._validate_snapshot_binding(intent, frozen_snapshot)
        forbidden = {"death", "archive", "terminal", "permanent_injury", "permanent_departure"}
        if any(str(key).casefold() in forbidden or str(item).casefold() in forbidden for key, item in intent["payload"].items()):
            _fail("engine.vitality_terminal_forbidden", "intent.payload", "terminal actor outcomes are platform-owned and forbidden")
        _validate_intent_payload_fields(intent_type, intent["payload"])
        effect_type, payload = self._map_payload(intent_type, intent["payload"])
        source_ref = intent["payload"].get("source_ref")
        reason_code = intent["payload"].get("reason_code")
        if any(not isinstance(item, str) or _REF_RE.fullmatch(item) is None for item in (source_ref, reason_code)):
            _fail("engine.effect_payload_invalid", "intent.payload.source", "source_ref and reason_code are required")
        return TypedEffectProposal(
            proposal_ref, str(intent["operation_ref"]), str(intent["request_fingerprint"]), capability,
            effect_type, str(intent["target_binding"]), freeze_json(intent["expected_revisions"], "expected_revisions"),
            freeze_json(payload, "payload"),
            freeze_json({"source_ref": source_ref, "reason_code": reason_code, "cause_refs": [str(intent["operation_ref"])]}, "source"),
            True, dedupe_key, atomic_group_ref,
        )

    def _validate_snapshot_binding(self, intent: Mapping[str, Any], snapshot: ActorResourceSnapshot) -> None:
        resource_ref = str(intent["payload"].get("resource_ref") or "")
        definition = self.resources.resolve(resource_ref)
        if snapshot.actor_binding != intent["target_binding"] or snapshot.resource_ref != resource_ref or snapshot.definition_sha256 != definition.definition_sha256:
            _fail("engine.resource_snapshot_invalid", "snapshot", "snapshot does not bind the requested actor/resource definition")
        minimum = int(definition.value["minimum"])
        if (
            snapshot.base_maximum != int(definition.value["base_maximum"])
            or snapshot.effective_maximum < minimum
            or not minimum <= snapshot.base_current <= snapshot.effective_maximum
        ):
            _fail("engine.resource_snapshot_invalid", "snapshot", "snapshot values exceed the frozen resource definition")
        expected = intent.get("expected_revisions")
        if not isinstance(expected, Mapping) or expected.get("actor_revision") != snapshot.actor_revision:
            _fail("engine.revision_conflict", "expected_revisions.actor_revision", "snapshot actor revision differs from the frozen request")

    def preview(self, intent: Mapping[str, Any], snapshot: ActorResourceSnapshot | Mapping[str, Any]) -> Mapping[str, Any]:
        """Calculate a non-authoritative before/after preview without changing the snapshot."""
        frozen = snapshot if isinstance(snapshot, ActorResourceSnapshot) else ActorResourceSnapshot.from_mapping(snapshot)
        self._validate_snapshot_binding(intent, frozen)
        intent_type = str(intent.get("intent_type") or "")
        payload = intent.get("payload")
        if not isinstance(payload, Mapping):
            _fail("engine.effect_payload_invalid", "intent.payload", "payload is required")
        definition = self.resources.resolve(frozen.resource_ref)
        base_after = frozen.base_current
        layers = [dict(item) for item in frozen.temporary_layers]
        absorbed = 0
        if intent_type == "actor.vitality.damage":
            remaining = _integer(payload.get("base_amount"), "payload.base_amount", minimum=1)
            # Stable ordering makes retries independent of input container order.
            for layer in sorted(layers, key=lambda item: (-item["priority"], item["created_order"], item["layer_ref"])):
                taken = min(layer["amount"], remaining)
                layer["amount"] -= taken; remaining -= taken; absorbed += taken
                if remaining == 0:
                    break
            base_after = frozen.base_current - remaining
        elif intent_type == "actor.vitality.heal":
            base_after = frozen.base_current + _integer(payload.get("base_amount"), "payload.base_amount", minimum=1)
        elif intent_type in {"actor.resource_pool.delta", "actor.resource_pool.set"}:
            amount = _integer(payload.get("amount"), "payload.amount")
            base_after = frozen.base_current + amount if intent_type.endswith("delta") else amount
        else:
            _fail("engine.effect_payload_invalid", "intent_type", "this intent has no numeric preview")
        minimum = int(definition.value["minimum"])
        if definition.value["clamp_policy"] == "clamp":
            base_after = max(minimum, min(frozen.effective_maximum, base_after))
        elif not minimum <= base_after <= frozen.effective_maximum:
            _fail("engine.effect_payload_invalid", "preview", "proposed value exceeds a reject-bound resource")
        signals: list[str] = []
        for threshold in definition.value["thresholds"]:
            if "at_or_below" in threshold and frozen.base_current > threshold["at_or_below"] >= base_after:
                signals.append(str(threshold["signal"]))
            if "at_or_above" in threshold and frozen.base_current < threshold["at_or_above"] <= base_after:
                signals.append(str(threshold["signal"]))
        return freeze_json({
            "schema": "se-actor-resource-change-preview/1.0.0",
            "resource_ref": frozen.resource_ref,
            "actor_binding": frozen.actor_binding,
            "actor_revision": frozen.actor_revision,
            "base_before": frozen.base_current,
            "base_after": base_after,
            "temporary_absorbed": absorbed,
            "temporary_layers_after": sorted(layers, key=lambda item: (item["created_order"], item["layer_ref"])),
            "threshold_signal_proposals": sorted(set(signals)),
            "authoritative": False,
        }, "preview")

    def _map_payload(self, intent_type: str, payload: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        resource_ref = str(payload.get("resource_ref") or "")
        definition = self.resources.resolve(resource_ref)
        common = {"resource_ref": resource_ref, "threshold_handling": "propose_crossing_signals"}
        if intent_type in {"actor.resource_pool.delta", "actor.vitality.damage", "actor.vitality.heal", "actor.vitality.temporary.add", "actor.vitality.temporary.remove"}:
            field = "base_amount" if intent_type.startswith("actor.vitality.") else "amount"
            amount = _integer(payload.get(field), f"payload.{field}")
            if intent_type.startswith("actor.vitality.") and amount <= 0:
                _fail("engine.effect_payload_invalid", f"payload.{field}", "vitality amounts must be positive")
            sign = -1 if intent_type in {"actor.vitality.damage", "actor.vitality.temporary.remove"} else 1
            layer = "temporary" if ".temporary." in intent_type else "base"
            mapped = {**common, "amount": sign * amount, "layer": layer}
            if layer == "temporary":
                layer_ref = payload.get("temporary_layer_ref")
                if not isinstance(layer_ref, str) or _REF_RE.fullmatch(layer_ref) is None:
                    _fail("engine.effect_payload_invalid", "payload.temporary_layer_ref", "temporary layer reference is required")
                mapped["temporary_layer_ref"] = layer_ref
                if intent_type.endswith("add"):
                    mapped["temporary_priority"] = _integer(payload.get("temporary_priority"), "payload.temporary_priority")
            return "actor.resource.delta", mapped
        if intent_type == "actor.resource_pool.set":
            return "actor.resource.set", {**common, "amount": _integer(payload.get("amount"), "payload.amount"), "layer": str(payload.get("layer") or "base")}
        if intent_type == "actor.resource_pool.set_limit":
            maximum = _integer(payload.get("maximum"), "payload.maximum")
            if maximum < int(definition.value["minimum"]):
                _fail("engine.effect_payload_invalid", "payload.maximum", "maximum is below the resource minimum")
            overflow = payload.get("current_overflow")
            if overflow not in {"clamp", "reject"}:
                _fail("engine.effect_payload_invalid", "payload.current_overflow", "overflow policy is invalid")
            return "actor.resource.set_limit", {"resource_ref": resource_ref, "maximum": maximum, "current_overflow": overflow}
        if intent_type == "actor.vitality.depleted":
            # Depletion is a reversible signal proposal only; no death/archive semantics exist here.
            return "actor.status.upsert", {"status_ref": "vitality.depleted", "state": "active", "stacks": 1}
        _fail("engine.effect_payload_invalid", "intent_type", "intent type is unsupported")



__all__ = [
    "DeterministicResourceEvaluator", "effect_contract_identities", "ResourceCatalog", "ResourceContractError",
    "ResourceDefinition", "ActorResourceSnapshot", "TypedEffectProposal", "VitalityContract",
    "RESOURCE_EFFECT_EVALUATION_CONTRACT", "ResourceEffectEvaluationRequest",
    "ResourceEffectEvaluationResult", "ResourceEffectEvaluationService", "ResourceEffectEvaluationStatus",
    "resource_effect_request_fingerprint", "resource_effect_result_fingerprint",
]
