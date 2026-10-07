"""Append-only recovery.cycle/1.1.0 proposal and receipt-reconciliation contract."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Any, Protocol

from .contracts.port import (
    CancellationCheck, OperationEnvelope, PlatformBridge, PortContractError,
    Problem, ProblemCode, canonical_fingerprint, freeze_json,
)
from .versions import STORY_ENGINE_DISTRIBUTION_VERSION, STORY_ENGINE_PORT_VERSION

RECOVERY_CYCLE_CAPABILITY = "recovery.cycle/1.1.0"
RECOVERY_AUTHOR_SCHEMA = "se-recovery-cycle-definitions/1.1.0"
RECOVERY_SNAPSHOT_SCHEMA = "se-recovery-cycle-snapshot/1.1.0"
RECOVERY_REQUEST_SCHEMA = "se-recovery-cycle-evaluation/1.1.0"
RECOVERY_PROPOSAL_SCHEMA = "se-recovery-cycle-proposal/1.1.0"
RECOVERY_RESULT_SCHEMA = "se-recovery-cycle-result/1.1.0"
RECOVERY_PROGRESS_FACT_SCHEMA = "platform-recovery-progress-fact/1.1.0"
RECOVERY_COMMIT_RECEIPT_SCHEMA = "platform-recovery-commit-receipt/1.1.0"
RECOVERY_AUTHORIZATION_RECEIPT_SCHEMA = "platform-recovery-authorization-receipt/1.1.0"

_KINDS = frozenset({"rest", "treat", "resupply", "allocate", "resume"})
_ACTIONS = frozenset({"preview", "start", "allocate", "interrupt", "complete", "cancel", "resume", "reconcile"})
_PHASES = frozenset({"idle", "started", "progressed", "interrupted", "completed", "cancelled"})
_RECONCILIATION = frozenset({"NONE", "UNKNOWN", "VERIFY_REQUIRED", "COMMITTED", "RECONCILED"})
_RESOURCE_KINDS = frozenset({"vitality", "energy", "mana", "stress", "custom"})
_STATUS_CLASSES = frozenset({"recoverable", "terminal", "protected"})
_INTERRUPTION = frozenset({"preserve_committed", "discard_uncommitted", "partial_by_receipt"})
_TERMINAL = frozenset({"dead", "archived", "permanently_departed"})
_REVISION_KEYS = frozenset({"actor", "room", "resource", "status", "inventory", "time", "recovery"})
_SOURCE_BINDING_KEYS = frozenset({"resource_catalog_ref", "resource_catalog_sha256", "status_catalog_ref", "status_catalog_sha256", "vitality_contract_ref", "vitality_contract_sha256"})
_PIN_KEYS = frozenset({"story_pack_ref", "canonical_sha256", "artifact_ref", "artifact_sha256", "engine_version", "port_version", "schema_version", "source_ref", "source_sha256"}) | _SOURCE_BINDING_KEYS
_ASCII_REF = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-")
_RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_PUBLIC_MESSAGE = "Platform confirmation is required; uncertain effects must be reconciled and ordinary recovery never changes terminal outcomes."


class RecoveryCycleContractError(ValueError):
    def __init__(self, code: str, path: str, reason: str) -> None:
        self.code, self.path, self.reason = code, path, reason
        super().__init__(f"{code}:{path}")


def _fail(code: str, path: str, reason: str) -> None:
    raise RecoveryCycleContractError(code, path, reason)


def _object(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping): _fail("recovery.object_invalid", path, "object required")
    if any(not isinstance(k, str) for k in value): _fail("recovery.property_invalid", path, "string properties required")
    return value


def _array(value: object, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)): _fail("recovery.array_invalid", path, "array required")
    return value


def _text(value: object, path: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum: _fail("recovery.text_invalid", path, "bounded non-empty text required")
    return value.strip()


def _ref(value: object, path: str) -> str:
    result = _text(value, path, 128)
    if result[0] not in _ASCII_REF or not result[0].isalnum() or any(c not in _ASCII_REF for c in result): _fail("recovery.ref_invalid", path, "ASCII opaque ref required")
    return result


def _digest(value: object, path: str) -> str:
    result = _text(value, path, 71)
    if len(result) != 71 or not result.startswith("sha256:") or any(c not in "0123456789abcdef" for c in result[7:]): _fail("recovery.hash_invalid", path, "sha256 required")
    return result


def _integer(value: object, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum: _fail("recovery.integer_invalid", path, "bounded integer required")
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping): return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)): return [_plain(v) for v in value]
    if isinstance(value, StrEnum): return value.value
    return value


def _exact(value: Mapping[str, Any], fields: set[str] | frozenset[str], path: str) -> None:
    if set(value) != set(fields): _fail("recovery.fields_invalid", path, "exact fields required")


def _revisions(value: object, path: str) -> dict[str, int]:
    raw = _object(value, path); _exact(raw, _REVISION_KEYS, path)
    return {key: _integer(raw[key], f"{path}.{key}") for key in sorted(_REVISION_KEYS)}


def _timestamp(value: object, path: str) -> str:
    text = _text(value, path, 64)
    if _RFC3339_RE.fullmatch(text) is None: _fail("recovery.timestamp_invalid", path, "strict RFC3339 timestamp required")
    try: parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError: _fail("recovery.timestamp_invalid", path, "RFC3339 timestamp required")
    if parsed.tzinfo is None: _fail("recovery.timestamp_invalid", path, "timezone required")
    return text


def _pins(value: object, path: str) -> dict[str, str]:
    raw = _object(value, path); _exact(raw, _PIN_KEYS, path)
    result = {}
    for key in sorted(_PIN_KEYS):
        result[key] = _digest(raw[key], f"{path}.{key}") if key.endswith("_sha256") else _text(raw[key], f"{path}.{key}", 64) if key in {"engine_version", "port_version", "schema_version"} else _ref(raw[key], f"{path}.{key}")
    if result["schema_version"] != "1.1.0": _fail("recovery.pin_schema_invalid", path, "schema pin must be 1.1.0")
    return result


def _delta(raw: object, path: str) -> dict[str, Any]:
    value = _object(raw, path); _exact(value, {"resource_ref", "kind", "before", "delta", "after", "minimum", "maximum"}, path)
    result = {"resource_ref": _ref(value["resource_ref"], path), "kind": value["kind"]}
    if result["kind"] not in _RESOURCE_KINDS: _fail("recovery.resource_kind_invalid", path, "typed resource kind required")
    for key in ("before", "delta", "after", "minimum", "maximum"):
        if isinstance(value[key], bool) or not isinstance(value[key], int): _fail("recovery.resource_value_invalid", path, "integer resource value required")
        result[key] = value[key]
    if result["minimum"] > result["maximum"] or result["after"] != result["before"] + result["delta"] or not result["minimum"] <= result["after"] <= result["maximum"]: _fail("recovery.resource_math_invalid", path, "exact delta/caps required")
    return result


def _cost(raw: object, path: str) -> dict[str, Any]:
    value = _object(raw, path); _exact(value, {"item_ref", "quantity", "inventory_revision"}, path)
    return {"item_ref": _ref(value["item_ref"], path), "quantity": _integer(value["quantity"], path, 1), "inventory_revision": _integer(value["inventory_revision"], path)}


def compile_recovery_cycle_definitions(document: Mapping[str, Any]) -> Mapping[str, Any]:
    root = _object(document, "$")
    _exact(root, {"schema", "trusted_manifest", "source_bindings", "policies", "definitions"}, "$")
    if root["schema"] != RECOVERY_AUTHOR_SCHEMA: _fail("recovery.schema_invalid", "schema", "1.1.0 required")
    manifest = _object(root["trusted_manifest"], "trusted_manifest")
    _exact(manifest, {"source_ref", "source_sha256", "real_sp_active_consumer"}, "trusted_manifest")
    trusted = {"source_ref": _ref(manifest["source_ref"], "trusted_manifest.source_ref"), "source_sha256": _digest(manifest["source_sha256"], "trusted_manifest.source_sha256"), "real_sp_active_consumer": manifest["real_sp_active_consumer"]}
    if trusted["real_sp_active_consumer"] is not False: _fail("recovery.active_consumer_forbidden", "trusted_manifest.real_sp_active_consumer", "current SP is not an active consumer")
    source_bindings = _object(root["source_bindings"], "source_bindings"); _exact(source_bindings, _SOURCE_BINDING_KEYS, "source_bindings")
    source_ir = {key: (_digest(source_bindings[key], f"source_bindings.{key}") if key.endswith("_sha256") else _ref(source_bindings[key], f"source_bindings.{key}")) for key in sorted(_SOURCE_BINDING_KEYS)}
    policies = _object(root["policies"], "policies")
    _exact(policies, {"commit_owner", "progress_fact_owner", "terminal_owner", "unknown_policy", "ordinary_recovery_revives"}, "policies")
    if policies != {"commit_owner": "platform", "progress_fact_owner": "platform", "terminal_owner": "platform", "unknown_policy": "reconcile_only", "ordinary_recovery_revives": False}: _fail("recovery.authority_invalid", "policies", "platform authority and reconcile-only unknown required")
    author_definitions = _array(root["definitions"], "definitions")
    if len(author_definitions) > 256: _fail("recovery.definitions_too_many", "definitions", "at most 256 recovery definitions are allowed")
    definitions, seen = [], set()
    for index, raw in enumerate(author_definitions):
        path = f"definitions[{index}]"; value = _object(raw, path)
        fields = {"recovery_ref", "label", "kind", "policy_version", "typed_policies", "allowed_phases", "interruption_policy", "hp0_policy", "zero_crossing_policy"}
        _exact(value, fields, path)
        ref = _ref(value["recovery_ref"], path)
        if ref in seen: _fail("recovery.duplicate_definition", path, "duplicate recovery_ref")
        seen.add(ref)
        kind = value["kind"]
        if kind not in _KINDS: _fail("recovery.kind_invalid", path, "typed recovery kind required")
        phases = [_text(x, path, 32) for x in _array(value["allowed_phases"], path)]
        if not phases or len(phases) != len(set(phases)) or any(x not in _PHASES for x in phases): _fail("recovery.phases_invalid", path, "allowed phases invalid")
        if value["policy_version"] != "recovery-policy/1.1.0": _fail("recovery.policy_version_invalid", f"{path}.policy_version", "typed policy version 1.1.0 required")
        typed = _object(value["typed_policies"], f"{path}.typed_policies"); _exact(typed, {"resource", "status", "rest", "treat", "resupply", "allocate", "resume"}, f"{path}.typed_policies")
        resource = _object(typed["resource"], f"{path}.typed_policies.resource"); _exact(resource, {"kind", "resources"}, f"{path}.typed_policies.resource")
        if resource["kind"] != "exact_restore": _fail("recovery.typed_resource_kind_invalid", f"{path}.typed_policies.resource.kind", "exact_restore required")
        resource_entries = _object(resource["resources"], f"{path}.typed_policies.resource.resources")
        resource_kinds = [_text(x, path, 32) for x in resource_entries]
        if not resource_kinds or len(resource_kinds) != len(set(resource_kinds)) or any(x not in _RESOURCE_KINDS for x in resource_kinds): _fail("recovery.resources_invalid", path, "unique eligible resource kinds required")
        amount_ir, cap_ir = {}, {}
        for resource_kind in sorted(resource_kinds):
            entry = _object(resource_entries[resource_kind], f"{path}.typed_policies.resource.resources.{resource_kind}"); _exact(entry, {"exact_amount", "cap"}, f"{path}.typed_policies.resource.resources.{resource_kind}")
            amount_ir[resource_kind] = _integer(entry["exact_amount"], path, 1); cap_ir[resource_kind] = _integer(entry["cap"], path, 1)
        status = _object(typed["status"], f"{path}.typed_policies.status"); _exact(status, {"kind", "status_refs", "allowed_classes"}, f"{path}.typed_policies.status")
        if status["kind"] != "eligible_remove": _fail("recovery.typed_status_kind_invalid", f"{path}.typed_policies.status.kind", "eligible_remove required")
        status_refs = [_ref(x, path) for x in _array(status["status_refs"], path)]; status_classes = [_text(x, path, 32) for x in _array(status["allowed_classes"], path)]
        if len(status_refs) != len(set(status_refs)) or len(status_classes) != len(set(status_classes)) or any(x != "recoverable" for x in status_classes): _fail("recovery.statuses_invalid", path, "only explicitly recoverable statuses are eligible")
        rest = _object(typed["rest"], f"{path}.typed_policies.rest"); _exact(rest, {"kind", "duration_seconds"}, f"{path}.typed_policies.rest")
        if rest["kind"] != "duration": _fail("recovery.typed_rest_kind_invalid", f"{path}.typed_policies.rest.kind", "duration policy required")
        duration = _integer(rest["duration_seconds"], path, 1)
        if duration > 604800: _fail("recovery.duration_invalid", f"{path}.typed_policies.rest.duration_seconds", "duration cannot exceed seven days")
        treat = _object(typed["treat"], f"{path}.typed_policies.treat"); _exact(treat, {"kind", "receipt_required"}, f"{path}.typed_policies.treat")
        if treat != {"kind": "platform_receipt", "receipt_required": True}: _fail("recovery.typed_treat_invalid", f"{path}.typed_policies.treat", "platform receipt treatment required")
        resupply = _object(typed["resupply"], f"{path}.typed_policies.resupply"); _exact(resupply, {"kind", "costs"}, f"{path}.typed_policies.resupply")
        if resupply["kind"] != "exact_inventory_cost": _fail("recovery.typed_resupply_kind_invalid", f"{path}.typed_policies.resupply.kind", "exact inventory cost required")
        cost_entries = _object(resupply["costs"], f"{path}.typed_policies.resupply.costs"); costs = []
        for item_ref in sorted(cost_entries):
            _ref(item_ref, f"{path}.typed_policies.resupply.costs.property"); entry = _object(cost_entries[item_ref], path); _exact(entry, {"quantity", "inventory_revision"}, path)
            costs.append(_cost({"item_ref": item_ref, **entry}, path))
        allocate = _object(typed["allocate"], f"{path}.typed_policies.allocate"); _exact(allocate, {"kind", "engine_allocates"}, f"{path}.typed_policies.allocate")
        if allocate != {"kind": "platform_only", "engine_allocates": False}: _fail("recovery.typed_allocate_invalid", f"{path}.typed_policies.allocate", "allocation must remain platform-only")
        resume_typed = _object(typed["resume"], f"{path}.typed_policies.resume"); _exact(resume_typed, {"kind", "allowed", "requires_same_definition", "requires_committed_elapsed"}, f"{path}.typed_policies.resume")
        if resume_typed["kind"] != "same_definition_committed_elapsed" or not all(isinstance(resume_typed[k], bool) for k in ("allowed", "requires_same_definition", "requires_committed_elapsed")): _fail("recovery.resume_policy_invalid", path, "typed resume policy required")
        resume = {k: resume_typed[k] for k in ("allowed", "requires_same_definition", "requires_committed_elapsed")}
        interruption = value["interruption_policy"]
        if interruption not in _INTERRUPTION: _fail("recovery.interruption_invalid", path, "interruption policy invalid")
        if value["hp0_policy"] != "require_rescue_or_fate_receipt" or value["zero_crossing_policy"] != "require_consent_and_rescue_or_fate_receipt": _fail("recovery.zero_crossing_invalid", path, "HP0 and either-direction zero crossing require authorization receipts")
        expected_typed = {
            "resource": {"kind": "exact_restore", "resources": {key: {"exact_amount": amount_ir[key], "cap": cap_ir[key]} for key in sorted(resource_kinds)}},
            "status": {"kind": "eligible_remove", "status_refs": sorted(status_refs), "allowed_classes": sorted(status_classes)},
            "rest": {"kind": "duration", "duration_seconds": duration},
            "treat": {"kind": "platform_receipt", "receipt_required": True},
            "resupply": {"kind": "exact_inventory_cost", "costs": {x["item_ref"]: {"quantity": x["quantity"], "inventory_revision": x["inventory_revision"]} for x in sorted(costs, key=lambda x: x["item_ref"])}},
            "allocate": {"kind": "platform_only", "engine_allocates": False},
            "resume": {"kind": "same_definition_committed_elapsed", **_plain(resume)},
        }
        if kind == "rest" and "idle" not in phases or kind == "treat" and not status_refs or kind == "resupply" and not costs or kind == "resume" and not resume["allowed"]:
            _fail("recovery.kind_policy_invalid", path, "recovery kind requires its corresponding typed policy inputs")
        material = {"schema": "se-recovery-cycle-definition-ir/1.1.0", "recovery_ref": ref, "label": _text(value["label"], path, 160), "kind": kind, "policy_version": value["policy_version"], "typed_policies": expected_typed, "eligible_resource_kinds": sorted(resource_kinds), "eligible_status_refs": sorted(status_refs), "eligible_status_classes": sorted(status_classes), "exact_amounts": amount_ir, "caps": cap_ir, "supply_costs": sorted(costs, key=lambda x: x["item_ref"]), "duration_seconds": duration, "allowed_phases": sorted(phases), "interruption_policy": interruption, "hp0_policy": value["hp0_policy"], "zero_crossing_policy": value["zero_crossing_policy"], "resume_policy": _plain(resume)}
        material["definition_sha256"] = canonical_fingerprint(material); definitions.append(material)
    if not definitions: _fail("recovery.definitions_empty", "definitions", "at least one definition required")
    catalog = {"schema": "se-recovery-cycle-catalog-ir/1.1.0", "trusted_manifest": trusted, "source_bindings": source_ir, "policies": _plain(policies), "definitions": sorted(definitions, key=lambda x: x["recovery_ref"])}
    catalog["catalog_sha256"] = canonical_fingerprint(catalog); return catalog


def bind_recovery_cycle(extension: Mapping[str, Any], catalog: Mapping[str, Any]) -> Mapping[str, Any]:
    value = _object(extension, "extension"); _exact(value, {"recovery_ref"}, "extension")
    ref = _ref(value["recovery_ref"], "extension.recovery_ref")
    definition = next((x for x in catalog["definitions"] if x["recovery_ref"] == ref), None)
    if definition is None: _fail("recovery.definition_unknown", "extension.recovery_ref", "definition is not registered")
    return {"schema": "se-recovery-cycle-binding-ir/1.1.0", "recovery_ref": ref, "definition_sha256": definition["definition_sha256"], "catalog_sha256": catalog["catalog_sha256"]}


class RecoveryAction(StrEnum):
    PREVIEW="preview"; START="start"; ALLOCATE="allocate"; INTERRUPT="interrupt"; COMPLETE="complete"; CANCEL="cancel"; RESUME="resume"; RECONCILE="reconcile"
class RecoveryStatus(StrEnum):
    PROPOSED="proposed"; REPLAYED="replayed"; BLOCKED="blocked"; INVALID="invalid"; UNKNOWN="UNKNOWN"; VERIFY_REQUIRED="VERIFY_REQUIRED"; RECONCILED="reconciled"; CANCELLED="cancelled"; TIMED_OUT="timed_out"
class RecoveryProposalKind(StrEnum):
    PREVIEW="preview"; START="start"; ALLOCATE="allocate"; INTERRUPT="interrupt"; COMPLETE="complete"; CANCEL="cancel"; RESUME="resume"; RECONCILE="reconcile"; VALIDATION="validation"


def _validate_fact(value: Mapping[str, Any] | None, snapshot: "RecoverySnapshot") -> None:
    if value is None: return
    fields = {"schema", "fact_ref", "operation_ref", "idempotency_key", "request_fingerprint", "recovery_ref", "definition_sha256", "manifest_pins", "base_revisions", "result_revisions", "phase_before", "phase_after", "elapsed_before", "elapsed_after", "resource_deltas", "removed_status_refs", "supply_costs", "time_advanced_seconds", "interrupted", "observed_at", "fingerprint"}
    _exact(value, fields, "progress_fact")
    if value["schema"] != RECOVERY_PROGRESS_FACT_SCHEMA: _fail("recovery.fact_schema_invalid", "progress_fact.schema", "progress fact 1.1.0 required")
    for key in ("fact_ref", "operation_ref", "idempotency_key", "recovery_ref"): _ref(value[key], f"progress_fact.{key}")
    for key in ("request_fingerprint", "definition_sha256", "fingerprint"): _digest(value[key], f"progress_fact.{key}")
    base, result = _revisions(value["base_revisions"], "progress_fact.base_revisions"), _revisions(value["result_revisions"], "progress_fact.result_revisions")
    if base != _plain(snapshot.revisions): _fail("recovery.fact_revision_invalid", "progress_fact.base_revisions", "fact must bind snapshot revisions")
    if _pins(value["manifest_pins"], "progress_fact.manifest_pins") != _plain(snapshot.manifest_pins): _fail("recovery.fact_pin_invalid", "progress_fact.manifest_pins", "fact pins must match snapshot")
    if value["phase_before"] != snapshot.phase or value["phase_after"] not in _PHASES: _fail("recovery.fact_phase_invalid", "progress_fact", "phase transition invalid")
    before, after = _integer(value["elapsed_before"], "progress_fact"), _integer(value["elapsed_after"], "progress_fact")
    advanced = _integer(value["time_advanced_seconds"], "progress_fact")
    if before != snapshot.elapsed_seconds or after != before + advanced: _fail("recovery.fact_time_invalid", "progress_fact", "elapsed time must be exact")
    deltas = [_delta(x, "progress_fact.resource_deltas") for x in _array(value["resource_deltas"], "progress_fact.resource_deltas")]
    removed = [_ref(x, "progress_fact.removed_status_refs") for x in _array(value["removed_status_refs"], "progress_fact.removed_status_refs")]
    costs = [_cost(x, "progress_fact.supply_costs") for x in _array(value["supply_costs"], "progress_fact.supply_costs")]
    if len({x["resource_ref"] for x in deltas}) != len(deltas) or len(removed) != len(set(removed)) or len({x["item_ref"] for x in costs}) != len(costs): _fail("recovery.fact_duplicate", "progress_fact", "duplicate effects forbidden")
    for delta in deltas:
        state = snapshot.resources.get(delta["resource_ref"])
        if state is None or state["kind"] != delta["kind"] or state["value"] != delta["before"] or state["minimum"] != delta["minimum"] or state["maximum"] != delta["maximum"]: _fail("recovery.fact_resource_state_invalid", "progress_fact.resource_deltas", "delta before/caps must match snapshot state")
    if any(ref not in {x["status_ref"] for x in snapshot.statuses} for ref in removed): _fail("recovery.fact_status_state_invalid", "progress_fact.removed_status_refs", "removed status must exist in snapshot")
    expected_changed = {"resource": bool(deltas), "status": bool(removed), "inventory": bool(costs), "time": advanced > 0, "recovery": True}
    for key in _REVISION_KEYS:
        expected = base[key] + (1 if expected_changed.get(key, False) else 0)
        if result[key] != expected: _fail("recovery.fact_result_revision_invalid", f"progress_fact.result_revisions.{key}", "result revision must advance exactly once for changed domains and remain exact for unchanged domains")
    if not isinstance(value["interrupted"], bool): _fail("recovery.fact_interrupted_invalid", "progress_fact.interrupted", "boolean required")
    if (value["phase_after"] == "interrupted") != value["interrupted"]: _fail("recovery.fact_interruption_invalid", "progress_fact", "interrupted flag and resulting phase must agree in both directions")
    _timestamp(value["observed_at"], "progress_fact.observed_at")
    material = {k: _plain(v) for k, v in value.items() if k != "fingerprint"}
    if canonical_fingerprint(material) != value["fingerprint"]: _fail("recovery.fact_fingerprint_invalid", "progress_fact.fingerprint", "fact fingerprint mismatch")
    if any(result[k] < base[k] for k in _REVISION_KEYS): _fail("recovery.fact_result_revision_invalid", "progress_fact.result_revisions", "result revisions cannot go backwards")


def _validate_receipt(value: Mapping[str, Any] | None, snapshot: "RecoverySnapshot" | None) -> None:
    if value is None: return
    fields = {"schema", "receipt_ref", "proposal_ref", "proposal_fingerprint", "operation_ref", "idempotency_key", "request_fingerprint", "progress_fact_fingerprint", "recovery_ref", "definition_sha256", "manifest_pins", "base_revisions", "result_revisions", "phase_after", "elapsed_after", "resource_deltas", "removed_status_refs", "supply_costs", "time_advanced_seconds", "interrupted", "commit_state", "committed_at", "fingerprint"}
    _exact(value, fields, "commit_receipt")
    if value["schema"] != RECOVERY_COMMIT_RECEIPT_SCHEMA or value["commit_state"] not in {"committed", "rejected", "unknown", "verify_required"}: _fail("recovery.receipt_status_invalid", "commit_receipt", "platform commit state required")
    for key in ("receipt_ref", "proposal_ref", "operation_ref", "idempotency_key", "recovery_ref"): _ref(value[key], f"commit_receipt.{key}")
    for key in ("proposal_fingerprint", "request_fingerprint", "progress_fact_fingerprint", "definition_sha256", "fingerprint"): _digest(value[key], f"commit_receipt.{key}")
    receipt_pins = _pins(value["manifest_pins"], "commit_receipt.manifest_pins")
    if snapshot is not None and receipt_pins != _plain(snapshot.manifest_pins): _fail("recovery.receipt_pin_invalid", "commit_receipt.manifest_pins", "receipt pins must match snapshot")
    _revisions(value["base_revisions"], "commit_receipt.base_revisions"); _revisions(value["result_revisions"], "commit_receipt.result_revisions")
    [_delta(x, "commit_receipt.resource_deltas") for x in _array(value["resource_deltas"], "commit_receipt.resource_deltas")]
    [_ref(x, "commit_receipt.removed_status_refs") for x in _array(value["removed_status_refs"], "commit_receipt.removed_status_refs")]
    [_cost(x, "commit_receipt.supply_costs") for x in _array(value["supply_costs"], "commit_receipt.supply_costs")]
    _integer(value["elapsed_after"], "commit_receipt.elapsed_after"); _integer(value["time_advanced_seconds"], "commit_receipt.time_advanced_seconds"); _timestamp(value["committed_at"], "commit_receipt.committed_at")
    if value["phase_after"] not in _PHASES or not isinstance(value["interrupted"], bool): _fail("recovery.receipt_phase_invalid", "commit_receipt", "receipt state invalid")
    if value["commit_state"] == "rejected" and (value["resource_deltas"] or value["removed_status_refs"] or value["supply_costs"] or value["time_advanced_seconds"]): _fail("recovery.rejected_receipt_effect_invalid", "commit_receipt", "rejected receipt cannot report committed effects")
    if canonical_fingerprint({k: _plain(v) for k, v in value.items() if k != "fingerprint"}) != value["fingerprint"]: _fail("recovery.receipt_fingerprint_invalid", "commit_receipt.fingerprint", "receipt fingerprint mismatch")


def recovery_authorization_request_fingerprint(request: "RecoveryRequest") -> str:
    envelope = {name: getattr(request.envelope, name) for name in request.envelope.__dataclass_fields__ if name != "request_fingerprint"}
    snapshot_material = request.snapshot.material()
    for key in ("operation_journal", "rescue_receipt", "fate_receipt", "consent_receipt"): snapshot_material.pop(key)
    return canonical_fingerprint({"schema": "platform-recovery-authorization-request/1.1.0", "request_schema": request.schema, "envelope": envelope, "action": request.action.value, "snapshot_material": snapshot_material, "input": _plain(request.input)})


def recovery_authorization_subject_fingerprint(operation_ref: str, idempotency_key: str, authorization_request_fingerprint: str, progress_fact_fingerprint: str, resource_ref: str, transition: str, actor_ref: str, recovery_ref: str, base_revisions: Mapping[str, int]) -> str:
    for name, value in (("operation_ref", operation_ref), ("idempotency_key", idempotency_key), ("resource_ref", resource_ref), ("actor_ref", actor_ref), ("recovery_ref", recovery_ref)): _ref(value, name)
    _digest(authorization_request_fingerprint, "authorization_request_fingerprint"); _digest(progress_fact_fingerprint, "progress_fact_fingerprint"); revisions = _revisions(base_revisions, "base_revisions")
    if transition not in {"to_zero", "from_zero"}: _fail("recovery.authorization_transition_invalid", "transition", "zero crossing direction required")
    return canonical_fingerprint({"schema": "platform-recovery-authorization-subject/1.1.0", "operation_ref": operation_ref, "idempotency_key": idempotency_key, "authorization_request_fingerprint": authorization_request_fingerprint, "progress_fact_fingerprint": progress_fact_fingerprint, "resource_ref": resource_ref, "transition": transition, "actor_ref": actor_ref, "recovery_ref": recovery_ref, "base_revisions": revisions})


def _validate_authorization_receipt_shape(value: Mapping[str, Any] | None, kind: str, snapshot: "RecoverySnapshot") -> None:
    if value is None: return
    value = _object(value, f"{kind}_receipt")
    fields = {"schema", "receipt_ref", "kind", "actor_ref", "recovery_ref", "operation_ref", "idempotency_key", "authorization_request_fingerprint", "authorization_subject_fingerprint", "progress_fact_fingerprint", "resource_ref", "transition", "base_revisions", "authorized", "issued_at", "fingerprint"}; _exact(value, fields, f"{kind}_receipt")
    if value["schema"] != RECOVERY_AUTHORIZATION_RECEIPT_SCHEMA or value["kind"] != kind or value["actor_ref"] != snapshot.actor_ref or value["recovery_ref"] != snapshot.recovery_ref or value["authorized"] is not True or _revisions(value["base_revisions"], f"{kind}_receipt.base_revisions") != _plain(snapshot.revisions): _fail("recovery.authorization_identity_invalid", f"{kind}_receipt", "authorization receipt identity/revisions invalid")
    for key in ("receipt_ref", "actor_ref", "recovery_ref", "operation_ref", "idempotency_key", "resource_ref"): _ref(value[key], f"{kind}_receipt.{key}")
    for key in ("authorization_request_fingerprint", "authorization_subject_fingerprint", "progress_fact_fingerprint", "fingerprint"): _digest(value[key], f"{kind}_receipt.{key}")
    if value["transition"] not in {"to_zero", "from_zero"}: _fail("recovery.authorization_transition_invalid", f"{kind}_receipt.transition", "zero crossing direction invalid")
    _timestamp(value["issued_at"], f"{kind}_receipt.issued_at")
    if value["fingerprint"] != canonical_fingerprint({k: _plain(v) for k, v in value.items() if k != "fingerprint"}): _fail("recovery.authorization_fingerprint_invalid", f"{kind}_receipt.fingerprint", "authorization receipt fingerprint invalid")


def _authorization(value: Mapping[str, Any] | None, kind: str, snapshot: "RecoverySnapshot", request: "RecoveryRequest", fact: Mapping[str, Any], resource_ref: str, transition: str) -> bool:
    if value is None: return False
    fields = {"schema", "receipt_ref", "kind", "actor_ref", "recovery_ref", "operation_ref", "idempotency_key", "authorization_request_fingerprint", "authorization_subject_fingerprint", "progress_fact_fingerprint", "resource_ref", "transition", "base_revisions", "authorized", "issued_at", "fingerprint"}; _exact(value, fields, f"{kind}_receipt")
    request_subject = recovery_authorization_request_fingerprint(request)
    subject = recovery_authorization_subject_fingerprint(request.envelope.operation_ref, request.envelope.idempotency_key, request_subject, fact["fingerprint"], resource_ref, transition, snapshot.actor_ref, snapshot.recovery_ref, snapshot.revisions)
    if value["schema"] != RECOVERY_AUTHORIZATION_RECEIPT_SCHEMA or value["kind"] != kind or value["actor_ref"] != snapshot.actor_ref or value["recovery_ref"] != snapshot.recovery_ref or value["operation_ref"] != request.envelope.operation_ref or value["idempotency_key"] != request.envelope.idempotency_key or value["authorization_request_fingerprint"] != request_subject or value["authorization_subject_fingerprint"] != subject or value["progress_fact_fingerprint"] != fact["fingerprint"] or value["resource_ref"] != resource_ref or value["transition"] != transition or value["authorized"] is not True or _revisions(value["base_revisions"], f"{kind}_receipt.base_revisions") != _plain(snapshot.revisions): return False
    for key in ("receipt_ref", "operation_ref", "idempotency_key", "resource_ref"): _ref(value[key], f"{kind}_receipt.{key}")
    for key in ("authorization_request_fingerprint", "authorization_subject_fingerprint", "progress_fact_fingerprint", "fingerprint"): _digest(value[key], f"{kind}_receipt.{key}")
    if value["transition"] not in {"to_zero", "from_zero"}: return False
    _timestamp(value["issued_at"], f"{kind}_receipt.issued_at")
    return canonical_fingerprint({k: _plain(v) for k, v in value.items() if k != "fingerprint"}) == value["fingerprint"]


@dataclass(frozen=True, slots=True)
class RecoverySnapshot:
    schema: str; actor_ref: str; room_ref: str; recovery_ref: str; definition_sha256: str
    definition_label: str; definition_kind: str; definition_duration_seconds: int; definition_supply_quantities: tuple[int, ...]
    manifest_pins: Mapping[str, str]; revisions: Mapping[str, int]; resources: Mapping[str, Mapping[str, Any]]; statuses: tuple[Mapping[str, Any], ...]; inventory: Mapping[str, Mapping[str, Any]]
    phase: str; elapsed_seconds: int; pending_operation: Mapping[str, Any] | None; progress_fact: Mapping[str, Any] | None; committed_receipt: Mapping[str, Any] | None
    reconciliation_state: str; rescue_receipt: Mapping[str, Any] | None; fate_receipt: Mapping[str, Any] | None; consent_receipt: Mapping[str, Any] | None
    operation_journal: Mapping[str, Mapping[str, Any]]; terminal_status: str | None; expected_session_revision: int; fingerprint: str

    def __post_init__(self) -> None:
        if self.schema != RECOVERY_SNAPSHOT_SCHEMA: raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "recovery_snapshot.schema", "recovery snapshot 1.1.0 required")
        for key in ("actor_ref", "room_ref", "recovery_ref"): _ref(getattr(self, key), key)
        _digest(self.definition_sha256, "definition_sha256"); _digest(self.fingerprint, "fingerprint")
        _text(self.definition_label, "definition_label", 160)
        if self.definition_kind not in _KINDS: _fail("recovery.definition_kind_invalid", "definition_kind", "typed recovery definition kind required")
        _integer(self.definition_duration_seconds, "definition_duration_seconds", 1)
        quantities = tuple(_integer(value, "definition_supply_quantities[]", 1) for value in _array(self.definition_supply_quantities, "definition_supply_quantities"))
        object.__setattr__(self, "definition_supply_quantities", quantities)
        pins = _pins(self.manifest_pins, "manifest_pins"); revisions = _revisions(self.revisions, "revisions")
        if self.phase not in _PHASES or self.reconciliation_state not in _RECONCILIATION or self.terminal_status is not None and self.terminal_status not in _TERMINAL: _fail("recovery.snapshot_state_invalid", "snapshot", "phase/reconciliation/terminal state invalid")
        _integer(self.elapsed_seconds, "elapsed_seconds"); _integer(self.expected_session_revision, "expected_session_revision")
        resources = _object(self.resources, "resources")
        for ref, raw in resources.items():
            _ref(ref, "resources.property"); value = _object(raw, f"resources.{ref}"); _exact(value, {"kind", "value", "minimum", "maximum", "revision"}, f"resources.{ref}")
            if value["kind"] not in _RESOURCE_KINDS or any(isinstance(value[k], bool) or not isinstance(value[k], int) for k in ("value", "minimum", "maximum", "revision")) or not value["minimum"] <= value["value"] <= value["maximum"]: _fail("recovery.resource_state_invalid", f"resources.{ref}", "typed bounded resource state required")
        statuses = []
        for raw in self.statuses:
            value = _object(raw, "statuses[]"); _exact(value, {"status_ref", "class", "revision"}, "statuses[]")
            if value["class"] not in _STATUS_CLASSES: _fail("recovery.status_state_invalid", "statuses[]", "typed status class required")
            statuses.append({"status_ref": _ref(value["status_ref"], "statuses[].status_ref"), "class": value["class"], "revision": _integer(value["revision"], "statuses[].revision")})
        if len({x["status_ref"] for x in statuses}) != len(statuses): _fail("recovery.status_duplicate", "statuses", "duplicate status")
        inventory = _object(self.inventory, "inventory")
        for ref, raw in inventory.items():
            _ref(ref, "inventory.property"); value = _object(raw, f"inventory.{ref}"); _exact(value, {"quantity", "revision"}, f"inventory.{ref}"); _integer(value["quantity"], f"inventory.{ref}.quantity"); _integer(value["revision"], f"inventory.{ref}.revision")
        if self.pending_operation is not None:
            pending = _object(self.pending_operation, "pending_operation"); _exact(pending, {"operation_ref", "idempotency_key", "request_fingerprint", "definition_sha256", "manifest_pins", "base_revisions", "phase", "commit_state", "proposal_ref", "proposal_fingerprint", "started_at", "committed_elapsed_seconds"}, "pending_operation")
            for key in ("operation_ref", "idempotency_key"): _ref(pending[key], f"pending_operation.{key}")
            for key in ("request_fingerprint", "definition_sha256"): _digest(pending[key], f"pending_operation.{key}")
            if pending["proposal_ref"] is not None: _ref(pending["proposal_ref"], "pending_operation.proposal_ref")
            if pending["proposal_fingerprint"] is not None: _digest(pending["proposal_fingerprint"], "pending_operation.proposal_fingerprint")
            if pending["commit_state"] not in {"proposed", "committed", "rejected", "unknown", "verify_required"}: _fail("recovery.pending_commit_state_invalid", "pending_operation.commit_state", "pending commit state invalid")
            if _pins(pending["manifest_pins"], "pending_operation.manifest_pins") != pins: _fail("recovery.pending_pin_invalid", "pending_operation.manifest_pins", "pending pins must match snapshot")
            if pending["definition_sha256"] != self.definition_sha256 or _revisions(pending["base_revisions"], "pending_operation.base_revisions") != revisions or pending["phase"] != self.phase: _fail("recovery.pending_state_invalid", "pending_operation", "pending definition, base revisions and phase must match snapshot")
            _timestamp(pending["started_at"], "pending_operation.started_at"); _integer(pending["committed_elapsed_seconds"], "pending_operation.committed_elapsed_seconds")
            if pending["phase"] not in _PHASES - {"idle", "completed", "cancelled"}: _fail("recovery.pending_phase_invalid", "pending_operation.phase", "pending phase invalid")
        _validate_fact(self.progress_fact, self); _validate_receipt(self.committed_receipt, self)
        _validate_authorization_receipt_shape(self.rescue_receipt, "rescue", self); _validate_authorization_receipt_shape(self.fate_receipt, "fate", self); _validate_authorization_receipt_shape(self.consent_receipt, "consent", self)
        if self.reconciliation_state == "COMMITTED" and (self.committed_receipt is None or self.committed_receipt["commit_state"] != "committed" or self.pending_operation is None or self.pending_operation["commit_state"] != "committed"):
            _fail("recovery.committed_state_invalid", "reconciliation_state", "COMMITTED requires matching committed pending state and receipt")
        if self.reconciliation_state == "RECONCILED" and (self.pending_operation is not None or self.progress_fact is not None or self.committed_receipt is None or self.committed_receipt["commit_state"] not in {"committed", "rejected"}):
            _fail("recovery.reconciled_state_invalid", "reconciliation_state", "RECONCILED is terminal read-only and retains only its conclusive committed or rejected receipt")
        journal = _object(self.operation_journal, "operation_journal")
        for key, raw in journal.items():
            _ref(key, "operation_journal.property"); item = _object(raw, f"operation_journal.{key}"); _exact(item, {"request_fingerprint", "result_fingerprint", "status"}, f"operation_journal.{key}"); _digest(item["request_fingerprint"], "journal.request_fingerprint"); _digest(item["result_fingerprint"], "journal.result_fingerprint")
            if item["status"] not in {"proposed", "committed", "reconciled", "UNKNOWN", "VERIFY_REQUIRED"}: _fail("recovery.journal_status_invalid", "journal.status", "journal status invalid")
        object.__setattr__(self, "manifest_pins", freeze_json(pins, "manifest_pins")); object.__setattr__(self, "revisions", freeze_json(revisions, "revisions")); object.__setattr__(self, "resources", freeze_json(resources, "resources")); object.__setattr__(self, "statuses", tuple(freeze_json(x, "status") for x in statuses)); object.__setattr__(self, "inventory", freeze_json(inventory, "inventory")); object.__setattr__(self, "operation_journal", freeze_json(journal, "operation_journal"))
        for name in ("pending_operation", "progress_fact", "committed_receipt", "rescue_receipt", "fate_receipt", "consent_receipt"):
            if getattr(self, name) is not None: object.__setattr__(self, name, freeze_json(getattr(self, name), name))

    def to_mapping(self) -> dict[str, Any]: return {name: _plain(getattr(self, name)) for name in self.__dataclass_fields__}
    def material(self) -> dict[str, Any]: return {k: v for k, v in self.to_mapping().items() if k != "fingerprint"}


def recovery_snapshot_fingerprint(value: RecoverySnapshot) -> str: return canonical_fingerprint(value.material())


@dataclass(frozen=True, slots=True)
class RecoveryRequest:
    schema: str; envelope: OperationEnvelope; action: RecoveryAction; snapshot: RecoverySnapshot; input: Mapping[str, Any]
    def __post_init__(self) -> None:
        if self.schema != RECOVERY_REQUEST_SCHEMA or self.envelope.operation_type != "evaluate_recovery_cycle" or self.envelope.expected_revision != self.snapshot.expected_session_revision: raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "recovery_request", "request envelope invalid")
        if not isinstance(self.input, Mapping) or self.input: raise PortContractError(ProblemCode.INPUT_INVALID, "recovery_request.input", "recovery actions accept an exact empty input object")
        object.__setattr__(self, "input", freeze_json(self.input, "recovery_input"))


def recovery_request_fingerprint(value: RecoveryRequest) -> str:
    envelope = {name: getattr(value.envelope, name) for name in value.envelope.__dataclass_fields__ if name != "request_fingerprint"}
    # The append-only replay journal records this fingerprint, so it cannot also
    # participate in its own fingerprint material. All state/CAS facts remain bound.
    snapshot_material = value.snapshot.material(); snapshot_material.pop("operation_journal")
    return canonical_fingerprint({"schema": value.schema, "envelope": envelope, "action": value.action.value, "snapshot_material": snapshot_material, "input": _plain(value.input)})


def _public_material(action: RecoveryAction, snapshot: RecoverySnapshot, definition: Mapping[str, Any], outcome: str) -> dict[str, Any]:
    fact = None if outcome == "rejected" else snapshot.progress_fact
    changes = [] if fact is None else [{"resource": item["kind"], "amount": item["delta"], "after": item["after"]} for item in fact["resource_deltas"]]
    statuses = [] if fact is None else [{"status": "recoverable condition", "change": "removed"} for _ in fact["removed_status_refs"]]
    costs = [{"item": "required supply", "quantity": item["quantity"]} for item in definition["supply_costs"]]
    return {"label": definition["label"], "action": action.value, "kind": definition["kind"], "phase": snapshot.phase, "duration_seconds": definition["duration_seconds"], "elapsed_seconds": snapshot.elapsed_seconds, "remaining_seconds": max(0, definition["duration_seconds"] - snapshot.elapsed_seconds), "resource_changes": changes, "status_changes": statuses, "supply_costs": costs, "outcome": outcome, "message": _PUBLIC_MESSAGE}


@dataclass(frozen=True, slots=True)
class RecoveryProposal:
    schema: str; proposal_ref: str; proposal_fingerprint: str; operation_ref: str; request_fingerprint: str; idempotency_key: str; actor_ref: str; room_ref: str; recovery_ref: str; definition_sha256: str; kind: RecoveryProposalKind; manifest_pins: Mapping[str, str]; source_revisions: Mapping[str, int]; result_revisions: Mapping[str, int] | None; public_preview: Mapping[str, Any]; private_reconciliation: Mapping[str, Any] | None; requires_platform_commit: bool; commits_state: bool; reconcile_only: bool; validation_errors: tuple[str, ...]
    def __post_init__(self) -> None:
        if self.schema != RECOVERY_PROPOSAL_SCHEMA or self.commits_state is not False: raise PortContractError(ProblemCode.OUTPUT_INVALID, "recovery_proposal", "proposal authority invalid")
        _ref(self.proposal_ref, "proposal_ref"); _digest(self.proposal_fingerprint, "proposal_fingerprint"); _ref(self.operation_ref, "operation_ref"); _digest(self.request_fingerprint, "request_fingerprint"); _ref(self.idempotency_key, "idempotency_key")
        for key in ("actor_ref", "room_ref", "recovery_ref"): _ref(getattr(self, key), key)
        _digest(self.definition_sha256, "definition_sha256"); _pins(self.manifest_pins, "manifest_pins"); _revisions(self.source_revisions, "source_revisions")
        if self.result_revisions is not None: _revisions(self.result_revisions, "result_revisions")
        public = _object(self.public_preview, "public_preview"); _exact(public, {"label", "action", "kind", "phase", "duration_seconds", "elapsed_seconds", "remaining_seconds", "resource_changes", "status_changes", "supply_costs", "outcome", "message"}, "public_preview")
        _text(public["label"], "public_preview.label", 160); _text(public["outcome"], "public_preview.outcome", 64); _text(public["message"], "public_preview.message", 512)
        if public["action"] not in _ACTIONS or public["kind"] not in _KINDS or public["phase"] not in _PHASES: _fail("recovery.preview_state_invalid", "public_preview", "preview state invalid")
        if self.kind not in {RecoveryProposalKind.VALIDATION, RecoveryProposalKind.RECONCILE} and public["action"] != self.kind.value: _fail("recovery.preview_action_invalid", "public_preview.action", "public action must match proposal kind")
        for key in ("duration_seconds", "elapsed_seconds", "remaining_seconds"): _integer(public[key], f"public_preview.{key}")
        if any(key.endswith("_ref") or key.endswith("_sha256") for key in public): _fail("recovery.preview_leak", "public_preview", "public preview cannot expose internal refs")
        for index, item in enumerate(_array(public["resource_changes"], "public_preview.resource_changes")):
            item = _object(item, f"public_preview.resource_changes[{index}]"); _exact(item, {"resource", "amount", "after"}, f"public_preview.resource_changes[{index}]")
            if item["resource"] not in _RESOURCE_KINDS or any(isinstance(item[k], bool) or not isinstance(item[k], int) for k in ("amount", "after")): _fail("recovery.preview_resource_invalid", "public_preview.resource_changes", "safe typed resource summary required")
        for index, item in enumerate(_array(public["status_changes"], "public_preview.status_changes")):
            item = _object(item, f"public_preview.status_changes[{index}]"); _exact(item, {"status", "change"}, f"public_preview.status_changes[{index}]")
            if item != {"status": "recoverable condition", "change": "removed"}: _fail("recovery.preview_status_invalid", "public_preview.status_changes", "safe status summary required")
        for index, item in enumerate(_array(public["supply_costs"], "public_preview.supply_costs")):
            item = _object(item, f"public_preview.supply_costs[{index}]"); _exact(item, {"item", "quantity"}, f"public_preview.supply_costs[{index}]")
            if item["item"] != "required supply" or isinstance(item["quantity"], bool) or not isinstance(item["quantity"], int) or item["quantity"] < 1: _fail("recovery.preview_supply_invalid", "public_preview.supply_costs", "safe supply summary required")
        if self.kind is RecoveryProposalKind.RECONCILE:
            if self.requires_platform_commit is not False or self.reconcile_only is not True: _fail("recovery.reconcile_authority_invalid", "proposal", "reconcile must be read-only")
        elif self.kind in {RecoveryProposalKind.PREVIEW, RecoveryProposalKind.VALIDATION}:
            if self.requires_platform_commit is not False: _fail("recovery.preview_authority_invalid", "proposal", "preview is read-only")
        elif self.requires_platform_commit is not True or self.reconcile_only is not False: _fail("recovery.commit_authority_invalid", "proposal", "mutation proposal requires platform commit")
        private = self.private_reconciliation
        intent_fields = {"actor_ref", "room_ref", "recovery_ref", "definition_sha256", "manifest_pins", "base_revisions", "phase_before", "phase_after", "resource_deltas", "removed_status_refs", "supply_costs", "time_advanced_seconds", "terminal_outcome", "platform_commit_required"}
        if self.kind in {RecoveryProposalKind.PREVIEW, RecoveryProposalKind.VALIDATION}:
            if private is not None: _fail("recovery.private_shape_invalid", "private_reconciliation", "read-only/validation private value must be null")
        elif self.kind in {RecoveryProposalKind.START, RecoveryProposalKind.RESUME, RecoveryProposalKind.CANCEL} or self.kind is RecoveryProposalKind.INTERRUPT and isinstance(private, Mapping) and set(private) == intent_fields:
            if not isinstance(private, Mapping) or set(private) != intent_fields: _fail("recovery.private_shape_invalid", "private_reconciliation", "exact intent fields required")
            if private["platform_commit_required"] is not True or private["terminal_outcome"] is not None: _fail("recovery.private_authority_invalid", "private_reconciliation", "intent cannot commit or decide terminal outcome")
            for key in ("actor_ref", "room_ref", "recovery_ref"): _ref(private[key], f"private_reconciliation.{key}")
            _digest(private["definition_sha256"], "private_reconciliation.definition_sha256")
            if _pins(private["manifest_pins"], "private_reconciliation.manifest_pins") != _plain(self.manifest_pins) or _revisions(private["base_revisions"], "private_reconciliation.base_revisions") != _plain(self.source_revisions): _fail("recovery.private_binding_invalid", "private_reconciliation", "intent pins/revisions must bind proposal")
            if private["phase_before"] not in _PHASES or private["phase_after"] not in _PHASES: _fail("recovery.private_phase_invalid", "private_reconciliation", "intent phase invalid")
            if self.kind is RecoveryProposalKind.START and (private["phase_before"], private["phase_after"]) != ("idle", "started"): _fail("recovery.private_phase_invalid", "private_reconciliation", "start must transition idle to started")
            if self.kind is RecoveryProposalKind.RESUME and (private["phase_before"], private["phase_after"]) != ("interrupted", "started"): _fail("recovery.private_phase_invalid", "private_reconciliation", "resume must transition interrupted to started")
            if self.kind is RecoveryProposalKind.CANCEL and private["phase_after"] != "cancelled": _fail("recovery.private_phase_invalid", "private_reconciliation", "cancel must transition to cancelled")
            if self.kind is RecoveryProposalKind.INTERRUPT and private["phase_after"] != "interrupted": _fail("recovery.private_phase_invalid", "private_reconciliation", "zero-effect interrupt must transition to interrupted")
            [_delta(x, "private_reconciliation.resource_deltas") for x in _array(private["resource_deltas"], "private_reconciliation.resource_deltas")]
            [_ref(x, "private_reconciliation.removed_status_refs") for x in _array(private["removed_status_refs"], "private_reconciliation.removed_status_refs")]
            [_cost(x, "private_reconciliation.supply_costs") for x in _array(private["supply_costs"], "private_reconciliation.supply_costs")]
            _integer(private["time_advanced_seconds"], "private_reconciliation.time_advanced_seconds")
            if self.kind in {RecoveryProposalKind.CANCEL, RecoveryProposalKind.INTERRUPT} and (private["resource_deltas"] or private["removed_status_refs"] or private["supply_costs"] or private["time_advanced_seconds"]): _fail("recovery.cancel_effect_invalid", "private_reconciliation", "cancel/discard interrupt emits zero effects")
        elif self.kind in {RecoveryProposalKind.ALLOCATE, RecoveryProposalKind.INTERRUPT, RecoveryProposalKind.COMPLETE}:
            if not isinstance(private, Mapping) or set(private) != {"progress_fact", "expected_commit_receipt_schema", "apply_exactly_once", "blind_retry_forbidden"} or private["expected_commit_receipt_schema"] != RECOVERY_COMMIT_RECEIPT_SCHEMA or private["apply_exactly_once"] is not True or private["blind_retry_forbidden"] is not True: _fail("recovery.private_shape_invalid", "private_reconciliation", "exact fact-bound commit intent required")
            _object(private["progress_fact"], "private_reconciliation.progress_fact")
            fact = private["progress_fact"]
            fact_fields = {"schema", "fact_ref", "operation_ref", "idempotency_key", "request_fingerprint", "recovery_ref", "definition_sha256", "manifest_pins", "base_revisions", "result_revisions", "phase_before", "phase_after", "elapsed_before", "elapsed_after", "resource_deltas", "removed_status_refs", "supply_costs", "time_advanced_seconds", "interrupted", "observed_at", "fingerprint"}
            _exact(fact, fact_fields, "private_reconciliation.progress_fact")
            if fact["schema"] != RECOVERY_PROGRESS_FACT_SCHEMA or _pins(fact["manifest_pins"], "private_reconciliation.progress_fact.manifest_pins") != _plain(self.manifest_pins) or _revisions(fact["base_revisions"], "private_reconciliation.progress_fact.base_revisions") != _plain(self.source_revisions): _fail("recovery.private_fact_binding_invalid", "private_reconciliation.progress_fact", "fact must bind proposal pins and source revisions")
            for key in ("fact_ref", "operation_ref", "idempotency_key", "recovery_ref"): _ref(fact[key], f"private_reconciliation.progress_fact.{key}")
            for key in ("request_fingerprint", "definition_sha256", "fingerprint"): _digest(fact[key], f"private_reconciliation.progress_fact.{key}")
            _revisions(fact["result_revisions"], "private_reconciliation.progress_fact.result_revisions")
            if self.result_revisions is None or _plain(self.result_revisions) != _plain(fact["result_revisions"]): _fail("recovery.private_fact_result_revision_invalid", "result_revisions", "proposal result revisions must equal progress fact result revisions")
            if fact["phase_before"] not in _PHASES or fact["phase_after"] not in _PHASES or (fact["phase_after"] == "interrupted") != fact["interrupted"]: _fail("recovery.private_fact_phase_invalid", "private_reconciliation.progress_fact", "fact phase invalid")
            expected_phase = {RecoveryProposalKind.ALLOCATE: "progressed", RecoveryProposalKind.INTERRUPT: "interrupted", RecoveryProposalKind.COMPLETE: "completed"}[self.kind]
            if fact["phase_after"] != expected_phase: _fail("recovery.private_fact_phase_invalid", "private_reconciliation.progress_fact", "fact phase must match proposal kind")
            for key in ("elapsed_before", "elapsed_after", "time_advanced_seconds"): _integer(fact[key], f"private_reconciliation.progress_fact.{key}")
            [_delta(x, "private_reconciliation.progress_fact.resource_deltas") for x in _array(fact["resource_deltas"], "private_reconciliation.progress_fact.resource_deltas")]
            [_ref(x, "private_reconciliation.progress_fact.removed_status_refs") for x in _array(fact["removed_status_refs"], "private_reconciliation.progress_fact.removed_status_refs")]
            [_cost(x, "private_reconciliation.progress_fact.supply_costs") for x in _array(fact["supply_costs"], "private_reconciliation.progress_fact.supply_costs")]
            _timestamp(fact["observed_at"], "private_reconciliation.progress_fact.observed_at")
            if fact["fingerprint"] != canonical_fingerprint({k: _plain(v) for k, v in fact.items() if k != "fingerprint"}): _fail("recovery.private_fact_fingerprint_invalid", "private_reconciliation.progress_fact.fingerprint", "fact fingerprint invalid")
        elif self.kind is RecoveryProposalKind.RECONCILE:
            shapes = ({"journal_result_fingerprint", "receipt"}, {"receipt", "apply_effects", "reconcile_only"})
            if not isinstance(private, Mapping) or set(private) not in shapes or "apply_effects" in private and (private["apply_effects"] is not False or private["reconcile_only"] is not True): _fail("recovery.private_shape_invalid", "private_reconciliation", "exact read-only reconciliation required")
            if private.get("receipt") is not None: _validate_receipt(private["receipt"], None)
            if "journal_result_fingerprint" in private: _digest(private["journal_result_fingerprint"], "private_reconciliation.journal_result_fingerprint")
        if self.private_reconciliation is not None: object.__setattr__(self, "private_reconciliation", freeze_json(self.private_reconciliation, "private_reconciliation"))
        object.__setattr__(self, "manifest_pins", freeze_json(self.manifest_pins, "manifest_pins")); object.__setattr__(self, "source_revisions", freeze_json(self.source_revisions, "source_revisions")); object.__setattr__(self, "public_preview", freeze_json(public, "public_preview"))


def recovery_proposal_fingerprint(value: RecoveryProposal) -> str:
    return canonical_fingerprint({name: to_json_value(getattr(value, name)) for name in value.__dataclass_fields__ if name != "proposal_fingerprint"})


def recovery_fact_proposal_identity(snapshot: RecoverySnapshot, definition: Mapping[str, Any], fact: Mapping[str, Any], operation_ref: str, request_fingerprint: str, idempotency_key: str) -> tuple[str, str]:
    """Rebuild the exact fact-bound Engine proposal identity for receipt auditing."""
    phase_kind = {"progressed": RecoveryProposalKind.ALLOCATE, "interrupted": RecoveryProposalKind.INTERRUPT, "completed": RecoveryProposalKind.COMPLETE}
    try: kind = phase_kind[fact["phase_after"]]
    except (KeyError, TypeError) as exc: raise RecoveryCycleContractError("recovery.fact_phase_invalid", "progress_fact.phase_after", "fact does not map to a commit-capable proposal") from exc
    operation_ref = _ref(operation_ref, "proposal_operation_ref"); request_fingerprint = _digest(request_fingerprint, "proposal_request_fingerprint"); idempotency_key = _ref(idempotency_key, "proposal_idempotency_key")
    proposal_ref = f"proposal.recovery.{kind.value}.{operation_ref}"
    proposal = RecoveryProposal(
        RECOVERY_PROPOSAL_SCHEMA, proposal_ref, "sha256:" + "0" * 64,
        operation_ref, request_fingerprint, idempotency_key, snapshot.actor_ref, snapshot.room_ref,
        snapshot.recovery_ref, snapshot.definition_sha256, kind, snapshot.manifest_pins,
        snapshot.revisions, fact["result_revisions"], _public_material(RecoveryAction(kind.value), snapshot, definition, fact["phase_after"]),
        {"progress_fact": _plain(fact), "expected_commit_receipt_schema": RECOVERY_COMMIT_RECEIPT_SCHEMA, "apply_exactly_once": True, "blind_retry_forbidden": True},
        True, False, False, (),
    )
    return proposal_ref, recovery_proposal_fingerprint(proposal)


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    schema: str; operation_ref: str; request_fingerprint: str; expected_revision: int; status: RecoveryStatus; proposal: RecoveryProposal | None; problems: tuple[Problem, ...]; result_fingerprint: str
    def __post_init__(self) -> None:
        if self.schema != RECOVERY_RESULT_SCHEMA: raise PortContractError(ProblemCode.OUTPUT_INVALID, "recovery_result.schema", "result 1.1.0 required")
        _ref(self.operation_ref, "operation_ref"); _digest(self.request_fingerprint, "request_fingerprint"); _digest(self.result_fingerprint, "result_fingerprint"); _integer(self.expected_revision, "expected_revision")
        if self.proposal is not None and not isinstance(self.proposal, RecoveryProposal) or not isinstance(self.problems, tuple) or any(not isinstance(problem, Problem) for problem in self.problems): raise PortContractError(ProblemCode.OUTPUT_INVALID, "recovery_result", "typed proposal/problems required")
        terminal = {RecoveryStatus.CANCELLED, RecoveryStatus.TIMED_OUT, RecoveryStatus.BLOCKED, RecoveryStatus.UNKNOWN, RecoveryStatus.VERIFY_REQUIRED}
        if self.status in terminal and (self.proposal is not None or not self.problems): raise PortContractError(ProblemCode.OUTPUT_INVALID, "recovery_result", "terminal result requires no proposal and at least one problem")
        if self.status is RecoveryStatus.PROPOSED and (self.proposal is None or self.proposal.kind in {RecoveryProposalKind.VALIDATION, RecoveryProposalKind.RECONCILE} or self.problems): raise PortContractError(ProblemCode.OUTPUT_INVALID, "recovery_result", "proposed requires a normal proposal and no problems")
        if self.status is RecoveryStatus.INVALID and (self.proposal is None or self.proposal.kind is not RecoveryProposalKind.VALIDATION or self.problems): raise PortContractError(ProblemCode.OUTPUT_INVALID, "recovery_result", "invalid requires a validation proposal and no problems")
        if self.status in {RecoveryStatus.REPLAYED, RecoveryStatus.RECONCILED} and (self.proposal is None or self.proposal.kind is not RecoveryProposalKind.RECONCILE or self.problems): raise PortContractError(ProblemCode.OUTPUT_INVALID, "recovery_result", "replayed/reconciled requires a reconcile proposal and no problems")
        if self.proposal is not None and (self.proposal.operation_ref != self.operation_ref or self.proposal.request_fingerprint != self.request_fingerprint): raise PortContractError(ProblemCode.OUTPUT_INVALID, "recovery_result", "proposal identity must bind outer result")


def recovery_result_fingerprint(value: RecoveryResult) -> str:
    return canonical_fingerprint({"schema": value.schema, "operation_ref": value.operation_ref, "request_fingerprint": value.request_fingerprint, "expected_revision": value.expected_revision, "status": value.status.value, "proposal": None if value.proposal is None else to_json_value(value.proposal), "problems": [to_json_value(x) for x in value.problems]})


class RecoveryCycleEvaluator:
    def __init__(self, artifact: Mapping[str, Any], artifact_ref: str) -> None:
        artifact_ref = _ref(artifact_ref, "artifact_ref")
        if not isinstance(artifact, Mapping): raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "artifact", "recovery evaluator requires a complete Artifact mapping")
        try:
            package = _object(artifact["package"], "artifact.package"); _exact(package, {"package_id", "content_version"}, "artifact.package")
            package_id = _ref(package["package_id"], "artifact.package.package_id")
            _text(package["content_version"], "artifact.package.content_version", 128)
            canonical_sha256 = _digest(artifact["canonical_ir_sha256"], "artifact.canonical_ir_sha256")
            artifact_sha256 = _digest(artifact["artifact_sha256"], "artifact.artifact_sha256")
            if artifact_sha256 != canonical_fingerprint({k: _plain(v) for k, v in artifact.items() if k != "artifact_sha256"}): raise ValueError("artifact digest")
        except (KeyError, TypeError, RecoveryCycleContractError, ValueError) as exc:
            raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "artifact", "complete self-verifying Artifact identity required") from exc
        catalog = artifact.get("recovery_cycle_definitions")
        if not isinstance(catalog, Mapping) or catalog.get("schema") != "se-recovery-cycle-catalog-ir/1.1.0" or catalog.get("catalog_sha256") != canonical_fingerprint({k: _plain(v) for k, v in catalog.items() if k != "catalog_sha256"}) or catalog.get("trusted_manifest", {}).get("real_sp_active_consumer") is not False: raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "recovery_cycle_definitions", "trusted recovery catalog invalid")
        try:
            trusted = catalog["trusted_manifest"]
            _exact(trusted, {"source_ref", "source_sha256", "real_sp_active_consumer"}, "catalog.trusted_manifest")
            _ref(trusted["source_ref"], "catalog.trusted_manifest.source_ref"); _digest(trusted["source_sha256"], "catalog.trusted_manifest.source_sha256")
            source_bindings = catalog["source_bindings"]; _exact(source_bindings, _SOURCE_BINDING_KEYS, "catalog.source_bindings")
            for key in _SOURCE_BINDING_KEYS: (_digest if key.endswith("_sha256") else _ref)(source_bindings[key], f"catalog.source_bindings.{key}")
            for definition in catalog["definitions"]:
                if definition.get("schema") != "se-recovery-cycle-definition-ir/1.1.0" or definition.get("definition_sha256") != canonical_fingerprint({k: _plain(v) for k, v in definition.items() if k != "definition_sha256"}): raise ValueError("definition digest")
        except (KeyError, TypeError, RecoveryCycleContractError, ValueError) as exc:
            raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "recovery_cycle_definitions", "trusted source or definition digest invalid") from exc
        self.definitions = MappingProxyType({x["recovery_ref"]: freeze_json(x, "recovery_definition") for x in catalog["definitions"]})
        self.trusted_manifest = freeze_json(trusted, "trusted_manifest")
        self.source_bindings = freeze_json(source_bindings, "source_bindings")
        self.expected_artifact_pins = freeze_json({
            "story_pack_ref": package_id, "canonical_sha256": canonical_sha256,
            "artifact_ref": artifact_ref, "artifact_sha256": artifact_sha256,
            "engine_version": STORY_ENGINE_DISTRIBUTION_VERSION,
            "port_version": STORY_ENGINE_PORT_VERSION, "schema_version": "1.1.0",
        }, "expected_artifact_pins")

    def evaluate(self, request: RecoveryRequest) -> RecoveryResult:
        snapshot = request.snapshot; definition = self.definitions.get(snapshot.recovery_ref)
        if snapshot.fingerprint != recovery_snapshot_fingerprint(snapshot) or request.envelope.request_fingerprint != recovery_request_fingerprint(request): return self._blocked(request, ProblemCode.RESULT_STALE, "snapshot or request fingerprint stale")
        if snapshot.manifest_pins["source_ref"] != self.trusted_manifest["source_ref"] or snapshot.manifest_pins["source_sha256"] != self.trusted_manifest["source_sha256"]: return self._blocked(request, ProblemCode.STORY_PACK_INCOMPATIBLE, "snapshot trusted source pin differs from compiled catalog")
        if any(snapshot.manifest_pins[key] != self.source_bindings[key] for key in _SOURCE_BINDING_KEYS): return self._blocked(request, ProblemCode.STORY_PACK_INCOMPATIBLE, "snapshot resource/status/vitality source pins differ from compiled catalog")
        if any(snapshot.manifest_pins[key] != expected for key, expected in self.expected_artifact_pins.items()): return self._blocked(request, ProblemCode.STORY_PACK_INCOMPATIBLE, "snapshot package/canonical/artifact/Engine/Port/Schema pins differ from evaluator identity")
        expected_definition_public = None if definition is None else (definition["label"], definition["kind"], definition["duration_seconds"], tuple(cost["quantity"] for cost in definition["supply_costs"]))
        if definition is None or definition["definition_sha256"] != snapshot.definition_sha256 or expected_definition_public != (snapshot.definition_label, snapshot.definition_kind, snapshot.definition_duration_seconds, snapshot.definition_supply_quantities): return self._blocked(request, ProblemCode.RESULT_STALE, "definition identity and public projection binding are stale")
        if request.action not in {RecoveryAction.PREVIEW, RecoveryAction.RECONCILE} and snapshot.phase not in definition["allowed_phases"]: return self._blocked(request, ProblemCode.INPUT_INVALID, "snapshot phase is not allowed by recovery definition")
        journal = snapshot.operation_journal.get(request.envelope.idempotency_key)
        if journal is not None:
            if journal["request_fingerprint"] != request.envelope.request_fingerprint: return self._blocked(request, ProblemCode.GUARD_REVISION_CONFLICT, "idempotency key reused with different request")
            if journal["status"] in {"UNKNOWN", "VERIFY_REQUIRED"}: return self._uncertain(request, RecoveryStatus(journal["status"]), "prior effect may have committed; reconcile receipt before retry")
            return self._proposal(request, definition, RecoveryProposalKind.RECONCILE, "replay", {"journal_result_fingerprint": journal["result_fingerprint"], "receipt": _plain(snapshot.committed_receipt)}, False, True, RecoveryStatus.REPLAYED)
        if snapshot.reconciliation_state in {"UNKNOWN", "VERIFY_REQUIRED"}: return self._uncertain(request, RecoveryStatus(snapshot.reconciliation_state), "platform state uncertain; only receipt reconciliation is safe")
        if snapshot.reconciliation_state == "RECONCILED": return self._blocked(request, ProblemCode.RESULT_STALE, "recovery operation is already reconciled and cannot emit another proposal")
        if snapshot.committed_receipt is not None:
            receipt_state = snapshot.committed_receipt["commit_state"]
            if receipt_state in {"unknown", "verify_required"}: return self._uncertain(request, RecoveryStatus.UNKNOWN if receipt_state == "unknown" else RecoveryStatus.VERIFY_REQUIRED, "platform receipt is not conclusive; query by idempotency key")
            if request.action is not RecoveryAction.RECONCILE: return self._uncertain(request, RecoveryStatus.VERIFY_REQUIRED, "committed receipt must be reconciled before another action")
            mismatch = self._receipt_mismatch(snapshot, definition)
            if mismatch: return self._uncertain(request, RecoveryStatus.VERIFY_REQUIRED, mismatch)
            outcome = "rejected" if receipt_state == "rejected" else "committed"
            return self._proposal(request, definition, RecoveryProposalKind.RECONCILE, outcome, {"receipt": _plain(snapshot.committed_receipt), "apply_effects": False, "reconcile_only": True}, False, True, RecoveryStatus.RECONCILED)
        if request.action is RecoveryAction.RECONCILE: return self._blocked(request, ProblemCode.INPUT_INVALID, "no committed receipt to reconcile")
        if request.action is RecoveryAction.PREVIEW: return self._proposal(request, definition, RecoveryProposalKind.PREVIEW, "preview", None, False, False)
        if snapshot.terminal_status is not None: return self._blocked(request, ProblemCode.INPUT_INVALID, "ordinary recovery cannot overwrite terminal status")
        pending = snapshot.pending_operation
        if request.action is RecoveryAction.START:
            if pending is not None or snapshot.phase != "idle": return self._blocked(request, ProblemCode.GUARD_REVISION_CONFLICT, "recovery is already active")
            for cost in definition["supply_costs"]:
                state = snapshot.inventory.get(cost["item_ref"])
                if state is None or state["revision"] != cost["inventory_revision"] or state["quantity"] < cost["quantity"]: return self._blocked(request, ProblemCode.INPUT_INVALID, "required supply is missing, stale, or insufficient")
            return self._proposal(request, definition, RecoveryProposalKind.START, "started", self._intent(request, snapshot, definition, "started"), True, False)
        if request.action is RecoveryAction.RESUME:
            policy = definition["resume_policy"]
            if snapshot.phase != "interrupted" or not policy["allowed"] or pending is None or policy["requires_same_definition"] and pending["definition_sha256"] != snapshot.definition_sha256 or policy["requires_committed_elapsed"] and pending["committed_elapsed_seconds"] != snapshot.elapsed_seconds: return self._blocked(request, ProblemCode.INPUT_INVALID, "resume policy not satisfied")
            for cost in definition["supply_costs"]:
                state = snapshot.inventory.get(cost["item_ref"])
                if state is None or state["revision"] != cost["inventory_revision"] or state["quantity"] < cost["quantity"]: return self._blocked(request, ProblemCode.INPUT_INVALID, "required supply is missing, stale, or insufficient")
            return self._proposal(request, definition, RecoveryProposalKind.RESUME, "resumed", self._intent(request, snapshot, definition, "started"), True, False)
        if pending is None: return self._blocked(request, ProblemCode.GUARD_REVISION_CONFLICT, "no active recovery operation")
        if pending["commit_state"] in {"committed", "rejected"}: return self._uncertain(request, RecoveryStatus.VERIFY_REQUIRED, "pending commit state requires a bound platform receipt and reconcile")
        if pending["commit_state"] in {"unknown", "verify_required"}: return self._uncertain(request, RecoveryStatus.UNKNOWN if pending["commit_state"] == "unknown" else RecoveryStatus.VERIFY_REQUIRED, "pending commit is uncertain; reconcile only")
        if request.action is RecoveryAction.CANCEL:
            return self._proposal(request, definition, RecoveryProposalKind.CANCEL, "cancelled", self._intent(request, snapshot, definition, "cancelled", empty=True), True, False)
        fact = snapshot.progress_fact
        if request.action is RecoveryAction.INTERRUPT and definition["interruption_policy"] in {"discard_uncommitted", "preserve_committed"}:
            if fact is not None: return self._blocked(request, ProblemCode.INPUT_INVALID, "zero-effect interruption policies reject a progress fact")
            if definition["interruption_policy"] == "preserve_committed" and (pending["committed_elapsed_seconds"] <= 0 or pending["committed_elapsed_seconds"] != snapshot.elapsed_seconds): return self._blocked(request, ProblemCode.INPUT_INVALID, "preserve_committed requires exact positive committed elapsed state")
            return self._proposal(request, definition, RecoveryProposalKind.INTERRUPT, "interrupted", self._intent(request, snapshot, definition, "interrupted", empty=True), True, False)
        if fact is None: return self._blocked(request, ProblemCode.GUARD_FACT_MISSING, "precommit platform progress fact required")
        if request.action is RecoveryAction.INTERRUPT and definition["interruption_policy"] != "partial_by_receipt": return self._blocked(request, ProblemCode.INPUT_INVALID, "progress fact is incompatible with interruption policy")
        if fact["operation_ref"] != pending["operation_ref"] or fact["idempotency_key"] != pending["idempotency_key"] or fact["request_fingerprint"] != pending["request_fingerprint"] or fact["recovery_ref"] != snapshot.recovery_ref or fact["definition_sha256"] != snapshot.definition_sha256: return self._blocked(request, ProblemCode.GUARD_REVISION_CONFLICT, "progress fact identity mismatch")
        if request.action is RecoveryAction.ALLOCATE and fact["phase_after"] != "progressed": return self._blocked(request, ProblemCode.INPUT_INVALID, "allocate requires exactly progressed fact")
        if request.action is RecoveryAction.INTERRUPT and not fact["interrupted"]: return self._blocked(request, ProblemCode.INPUT_INVALID, "interrupt requires interrupted fact")
        if request.action is RecoveryAction.COMPLETE and (fact["phase_after"] != "completed" or fact["elapsed_after"] < definition["duration_seconds"]): return self._blocked(request, ProblemCode.INPUT_INVALID, "complete requires duration-satisfied fact")
        crossings = [x for x in fact["resource_deltas"] if x["kind"] == "vitality" and (x["before"] == 0) != (x["after"] == 0)]
        if len(crossings) > 1: return self._blocked(request, ProblemCode.SEMANTIC_VALIDATION_FAILED, "multiple vitality zero crossings require separate platform-authorized transactions")
        zero = bool(crossings)
        hp0 = any(x["kind"] == "vitality" and x["after"] == 0 for x in fact["resource_deltas"]) or any(x["kind"] == "vitality" and x["value"] == 0 for x in snapshot.resources.values())
        if request.action is RecoveryAction.COMPLETE and hp0: return self._blocked(request, ProblemCode.SEMANTIC_VALIDATION_FAILED, "HP0 cannot complete through ordinary recovery; use platform rescue or fate flow")
        if hp0 and not crossings: return self._blocked(request, ProblemCode.SEMANTIC_VALIDATION_FAILED, "existing HP0 requires the separate platform rescue or fate flow")
        if crossings:
            crossing = crossings[0]; transition = "to_zero" if crossing["after"] == 0 else "from_zero"
            rescue_or_fate = _authorization(snapshot.rescue_receipt, "rescue", snapshot, request, fact, crossing["resource_ref"], transition) or _authorization(snapshot.fate_receipt, "fate", snapshot, request, fact, crossing["resource_ref"], transition)
            consent = _authorization(snapshot.consent_receipt, "consent", snapshot, request, fact, crossing["resource_ref"], transition)
            if not rescue_or_fate or not consent: return self._blocked(request, ProblemCode.SEMANTIC_VALIDATION_FAILED, "zero crossing requires operation/fact/direction-bound rescue-or-fate and consent receipts")
        active = {x["status_ref"]: x for x in snapshot.statuses}
        for ref in fact["removed_status_refs"]:
            item = active.get(ref)
            if item is None or ref not in definition["eligible_status_refs"] or item["class"] not in definition["eligible_status_classes"] or item["class"] in {"terminal", "protected"}: return self._blocked(request, ProblemCode.INPUT_INVALID, "status is not eligible for ordinary recovery")
        for delta in fact["resource_deltas"]:
            if delta["kind"] not in definition["eligible_resource_kinds"] or delta["maximum"] != definition["caps"][delta["kind"]] or delta["delta"] != min(definition["exact_amounts"][delta["kind"]], delta["maximum"] - delta["before"]): return self._blocked(request, ProblemCode.INPUT_INVALID, "recovery must apply the exact positive restore amount capped by the frozen definition")
        expected_costs = []
        for cost in definition["supply_costs"]:
            state = snapshot.inventory.get(cost["item_ref"])
            if state is None or state["revision"] != cost["inventory_revision"] or state["quantity"] < cost["quantity"]: return self._blocked(request, ProblemCode.INPUT_INVALID, "required supply is missing, stale, or insufficient")
            expected_costs.append({**_plain(cost), "inventory_revision": state["revision"]})
        if _plain(fact["supply_costs"]) != expected_costs: return self._blocked(request, ProblemCode.INPUT_INVALID, "supply costs do not exactly match definition and inventory revisions")
        kind = {RecoveryAction.ALLOCATE: RecoveryProposalKind.ALLOCATE, RecoveryAction.INTERRUPT: RecoveryProposalKind.INTERRUPT, RecoveryAction.COMPLETE: RecoveryProposalKind.COMPLETE}[request.action]
        return self._proposal(request, definition, kind, fact["phase_after"], {"progress_fact": _plain(fact), "expected_commit_receipt_schema": RECOVERY_COMMIT_RECEIPT_SCHEMA, "apply_exactly_once": True, "blind_retry_forbidden": True}, True, False)

    def _receipt_mismatch(self, snapshot: RecoverySnapshot, definition: Mapping[str, Any]) -> str | None:
        receipt, fact = snapshot.committed_receipt, snapshot.progress_fact
        if receipt is None or fact is None: return "commit receipt and original progress fact are both required"
        exact = ("result_revisions", "phase_after", "elapsed_after", "resource_deltas", "removed_status_refs", "supply_costs", "time_advanced_seconds", "interrupted")
        pending = snapshot.pending_operation
        if receipt["progress_fact_fingerprint"] != fact["fingerprint"] or pending is None or receipt["proposal_ref"] != pending["proposal_ref"] or receipt["proposal_fingerprint"] != pending["proposal_fingerprint"]: return "platform receipt differs from bound progress fact/proposal"
        identity = ("recovery_ref", "definition_sha256", "manifest_pins", "base_revisions")
        if any(_plain(receipt[key]) != _plain(fact[key]) for key in identity): return "platform receipt identity differs from the exact progress fact"
        try: expected_ref, expected_fingerprint = recovery_fact_proposal_identity(snapshot, definition, fact, receipt["operation_ref"], receipt["request_fingerprint"], receipt["idempotency_key"])
        except (RecoveryCycleContractError, PortContractError): return "platform receipt does not identify a valid fact-bound Engine proposal"
        if receipt["proposal_ref"] != expected_ref or receipt["proposal_fingerprint"] != expected_fingerprint: return "platform receipt does not bind the deterministic Engine proposal"
        if receipt["commit_state"] == "rejected":
            if receipt["base_revisions"] != receipt["result_revisions"] or receipt["elapsed_after"] != fact["elapsed_before"] or receipt["phase_after"] != fact["phase_before"] or receipt["interrupted"] is not False: return "rejected receipt must preserve exact revisions, phase, and elapsed state"
            return None
        if any(_plain(receipt[k]) != _plain(fact[k]) for k in exact): return "committed receipt differs from exact progress fact effects"
        return None

    def _intent(self, request: RecoveryRequest, snapshot: RecoverySnapshot, definition: Mapping[str, Any], phase: str, empty: bool = False) -> Mapping[str, Any]:
        return {"actor_ref": snapshot.actor_ref, "room_ref": snapshot.room_ref, "recovery_ref": snapshot.recovery_ref, "definition_sha256": snapshot.definition_sha256, "manifest_pins": _plain(snapshot.manifest_pins), "base_revisions": _plain(snapshot.revisions), "phase_before": snapshot.phase, "phase_after": phase, "resource_deltas": [], "removed_status_refs": [], "supply_costs": [] if empty else [{**_plain(x), "inventory_revision": snapshot.inventory[x["item_ref"]]["revision"]} for x in definition["supply_costs"]], "time_advanced_seconds": 0, "terminal_outcome": None, "platform_commit_required": True}

    def _public(self, request: RecoveryRequest, definition: Mapping[str, Any], outcome: str) -> Mapping[str, Any]:
        return _public_material(request.action, request.snapshot, definition, outcome)

    def _proposal(self, request: RecoveryRequest, definition: Mapping[str, Any], kind: RecoveryProposalKind, outcome: str, private: Mapping[str, Any] | None, commit: bool, reconcile: bool, status: RecoveryStatus = RecoveryStatus.PROPOSED) -> RecoveryResult:
        result_revisions = private["progress_fact"]["result_revisions"] if isinstance(private, Mapping) and isinstance(private.get("progress_fact"), Mapping) else None
        proposal = RecoveryProposal(RECOVERY_PROPOSAL_SCHEMA, f"proposal.recovery.{kind.value}.{request.envelope.operation_ref}", "sha256:" + "0" * 64, request.envelope.operation_ref, request.envelope.request_fingerprint, request.envelope.idempotency_key, request.snapshot.actor_ref, request.snapshot.room_ref, request.snapshot.recovery_ref, request.snapshot.definition_sha256, kind, request.snapshot.manifest_pins, request.snapshot.revisions, result_revisions, self._public(request, definition, outcome), private, commit, False, reconcile, ())
        proposal = replace(proposal, proposal_fingerprint=recovery_proposal_fingerprint(proposal))
        result = RecoveryResult(RECOVERY_RESULT_SCHEMA, request.envelope.operation_ref, request.envelope.request_fingerprint, request.envelope.expected_revision, status, proposal, (), "sha256:" + "0" * 64)
        return replace(result, result_fingerprint=recovery_result_fingerprint(result))

    def _blocked(self, request: RecoveryRequest, code: ProblemCode, reason: str) -> RecoveryResult: return self._terminal(request, RecoveryStatus.BLOCKED, code, reason)
    def _uncertain(self, request: RecoveryRequest, status: RecoveryStatus, reason: str) -> RecoveryResult: return self._terminal(request, status, ProblemCode.GUARD_FACT_UNKNOWN, reason)
    def _terminal(self, request: RecoveryRequest, status: RecoveryStatus, code: ProblemCode, reason: str) -> RecoveryResult:
        problem = Problem(code, "evaluate recovery cycle", reason, "no proposal emitted and no effect retried", "query the platform receipt and submit reconcile")
        result = RecoveryResult(RECOVERY_RESULT_SCHEMA, request.envelope.operation_ref, request.envelope.request_fingerprint, request.envelope.expected_revision, status, None, (problem,), "sha256:" + "0" * 64)
        return replace(result, result_fingerprint=recovery_result_fingerprint(result))


class RecoveryCycleService:
    def __init__(self, evaluator: RecoveryCycleEvaluator, clock) -> None: self.evaluator, self.clock = evaluator, clock
    async def evaluate_recovery_cycle(self, request: RecoveryRequest, bridge: PlatformBridge) -> RecoveryResult:
        check = CancellationCheck(request.envelope.operation_ref, request.envelope.request_fingerprint)
        deadline = datetime.fromisoformat(request.envelope.deadline_at.replace("Z", "+00:00"))
        cancelled_before = (await bridge.is_cancelled(check)).cancelled
        timed_out_before = self.clock() >= deadline
        if cancelled_before or timed_out_before:
            # The evaluator is pure. Evaluate an already-uncertain/read-only request
            # so cancellation cannot erase evidence that forbids a blind retry.
            result = self.evaluator.evaluate(request)
            if self._sticky_read_only(result): return result
            return self._late(
                request,
                RecoveryStatus.CANCELLED if cancelled_before else RecoveryStatus.TIMED_OUT,
                ProblemCode.CANCELLED if cancelled_before else ProblemCode.DEADLINE_EXCEEDED,
            )
        result = self.evaluator.evaluate(request)
        cancelled_after = (await bridge.is_cancelled(check)).cancelled
        timed_out_after = self.clock() >= deadline
        if self._sticky_read_only(result): return result
        if cancelled_after: return self._late(request, RecoveryStatus.CANCELLED, ProblemCode.CANCELLED)
        if timed_out_after: return self._late(request, RecoveryStatus.TIMED_OUT, ProblemCode.DEADLINE_EXCEEDED)
        return result
    @staticmethod
    def _sticky_read_only(result: RecoveryResult) -> bool:
        return result.status in {
            RecoveryStatus.UNKNOWN, RecoveryStatus.VERIFY_REQUIRED,
            RecoveryStatus.RECONCILED, RecoveryStatus.REPLAYED,
        }
    def _late(self, request: RecoveryRequest, status: RecoveryStatus, code: ProblemCode) -> RecoveryResult:
        problem = Problem(code, "evaluate recovery cycle", "cancelled or deadline exceeded", "discarded all proposals", "reconcile platform state before retry")
        result = RecoveryResult(RECOVERY_RESULT_SCHEMA, request.envelope.operation_ref, request.envelope.request_fingerprint, request.envelope.expected_revision, status, None, (problem,), "sha256:" + "0" * 64)
        return replace(result, result_fingerprint=recovery_result_fingerprint(result))


class RecoveryCycleStoryEnginePort(Protocol):
    async def evaluate_recovery_cycle(self, request: RecoveryRequest, bridge: PlatformBridge) -> RecoveryResult: ...


class RecoveryCycleRemoteEndpoint:
    def __init__(self, service: RecoveryCycleService) -> None: self.service = service
    async def dispatch(self, operation: str, payload: Mapping[str, Any], bridge: PlatformBridge) -> Mapping[str, Any]:
        if operation != "evaluate_recovery_cycle": raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "operation", "unsupported operation")
        return to_json_value(await self.service.evaluate_recovery_cycle(decode_recovery_request(payload), bridge))


def decode_recovery_snapshot(value: Mapping[str, Any]) -> RecoverySnapshot:
    if not isinstance(value, Mapping) or set(value) != set(RecoverySnapshot.__dataclass_fields__): raise PortContractError(ProblemCode.INPUT_INVALID, "recovery_snapshot", "snapshot fields invalid")
    data = dict(value); data["statuses"] = tuple(data["statuses"]); data["definition_supply_quantities"] = tuple(data["definition_supply_quantities"]); return RecoverySnapshot(**data)


def decode_recovery_request(value: Mapping[str, Any]) -> RecoveryRequest:
    if not isinstance(value, Mapping) or set(value) != {"schema", "envelope", "action", "snapshot", "input"}: raise PortContractError(ProblemCode.INPUT_INVALID, "recovery_request", "request fields invalid")
    envelope = value["envelope"]
    if not isinstance(envelope, Mapping) or set(envelope) != set(OperationEnvelope.__dataclass_fields__): raise PortContractError(ProblemCode.INPUT_INVALID, "recovery_request.envelope", "envelope fields invalid")
    _timestamp(envelope["deadline_at"], "recovery_request.envelope.deadline_at")
    return RecoveryRequest(value["schema"], OperationEnvelope(**envelope), RecoveryAction(value["action"]), decode_recovery_snapshot(value["snapshot"]), value["input"])


def decode_recovery_proposal(value: Mapping[str, Any]) -> RecoveryProposal:
    if not isinstance(value, Mapping) or set(value) != set(RecoveryProposal.__dataclass_fields__): raise PortContractError(ProblemCode.OUTPUT_INVALID, "recovery_proposal", "proposal fields invalid")
    data = dict(value); data["kind"] = RecoveryProposalKind(data["kind"]); data["validation_errors"] = tuple(data["validation_errors"]); result = RecoveryProposal(**data)
    if result.proposal_fingerprint != recovery_proposal_fingerprint(result): raise PortContractError(ProblemCode.OUTPUT_INVALID, "proposal_fingerprint", "proposal fingerprint invalid")
    return result


def decode_recovery_result(value: Mapping[str, Any], expected_request: RecoveryRequest) -> RecoveryResult:
    if not isinstance(expected_request, RecoveryRequest): raise PortContractError(ProblemCode.INPUT_INVALID, "expected_request", "typed expected recovery request required")
    if not isinstance(value, Mapping) or set(value) != set(RecoveryResult.__dataclass_fields__): raise PortContractError(ProblemCode.OUTPUT_INVALID, "recovery_result", "result fields invalid")
    data = dict(value); data["status"] = RecoveryStatus(data["status"]); data["proposal"] = None if data["proposal"] is None else decode_recovery_proposal(data["proposal"])
    problems = []
    for raw in data["problems"]:
        if not isinstance(raw, Mapping) or set(raw) != set(Problem.__dataclass_fields__): raise PortContractError(ProblemCode.OUTPUT_INVALID, "recovery_result.problems", "problem fields invalid")
        if type(raw["retryable"]) is not bool: raise PortContractError(ProblemCode.OUTPUT_INVALID, "recovery_result.problems.retryable", "retryable must be a boolean")
        item = dict(raw); item["code"] = ProblemCode(item["code"]); problems.append(Problem(**item))
    data["problems"] = tuple(problems); result = RecoveryResult(**data)
    if result.result_fingerprint != recovery_result_fingerprint(result): raise PortContractError(ProblemCode.OUTPUT_INVALID, "result_fingerprint", "result fingerprint invalid")
    snapshot = expected_request.snapshot
    if result.operation_ref != expected_request.envelope.operation_ref or result.request_fingerprint != expected_request.envelope.request_fingerprint or result.expected_revision != expected_request.envelope.expected_revision: raise PortContractError(ProblemCode.RESULT_STALE, "recovery_result", "result does not bind expected request")
    proposal = result.proposal
    if proposal is not None:
        expected_kind = RecoveryProposalKind.VALIDATION if result.status is RecoveryStatus.INVALID else RecoveryProposalKind.RECONCILE if result.status in {RecoveryStatus.REPLAYED, RecoveryStatus.RECONCILED} else {
            RecoveryAction.PREVIEW: RecoveryProposalKind.PREVIEW,
            RecoveryAction.START: RecoveryProposalKind.START,
            RecoveryAction.ALLOCATE: RecoveryProposalKind.ALLOCATE,
            RecoveryAction.INTERRUPT: RecoveryProposalKind.INTERRUPT,
            RecoveryAction.COMPLETE: RecoveryProposalKind.COMPLETE,
            RecoveryAction.CANCEL: RecoveryProposalKind.CANCEL,
            RecoveryAction.RESUME: RecoveryProposalKind.RESUME,
            RecoveryAction.RECONCILE: RecoveryProposalKind.RECONCILE,
        }[expected_request.action]
        if proposal.kind is not expected_kind or proposal.public_preview["action"] != expected_request.action.value or proposal.idempotency_key != expected_request.envelope.idempotency_key: raise PortContractError(ProblemCode.OUTPUT_INVALID, "recovery_proposal.kind", "proposal kind, public action, and idempotency key must exactly match the expected request")
        if result.status is not RecoveryStatus.INVALID:
            expected_outcome = {
                RecoveryProposalKind.PREVIEW: "preview",
                RecoveryProposalKind.START: "started",
                RecoveryProposalKind.RESUME: "resumed",
                RecoveryProposalKind.CANCEL: "cancelled",
                RecoveryProposalKind.ALLOCATE: snapshot.progress_fact["phase_after"] if snapshot.progress_fact is not None else "progressed",
                RecoveryProposalKind.INTERRUPT: "interrupted",
                RecoveryProposalKind.COMPLETE: "completed",
                RecoveryProposalKind.RECONCILE: "replay" if result.status is RecoveryStatus.REPLAYED else "rejected" if snapshot.committed_receipt is not None and snapshot.committed_receipt["commit_state"] == "rejected" else "committed",
            }[proposal.kind]
            public_fact = None if expected_outcome == "rejected" else snapshot.progress_fact
            expected_public = {
                "label": snapshot.definition_label,
                "action": expected_request.action.value,
                "kind": snapshot.definition_kind,
                "phase": snapshot.phase,
                "duration_seconds": snapshot.definition_duration_seconds,
                "elapsed_seconds": snapshot.elapsed_seconds,
                "remaining_seconds": max(0, snapshot.definition_duration_seconds - snapshot.elapsed_seconds),
                "resource_changes": [] if public_fact is None else [{"resource": item["kind"], "amount": item["delta"], "after": item["after"]} for item in public_fact["resource_deltas"]],
                "status_changes": [] if public_fact is None else [{"status": "recoverable condition", "change": "removed"} for _ in public_fact["removed_status_refs"]],
                "supply_costs": [{"item": "required supply", "quantity": quantity} for quantity in snapshot.definition_supply_quantities],
                "outcome": expected_outcome,
                "message": _PUBLIC_MESSAGE,
            }
            if _plain(proposal.public_preview) != expected_public: raise PortContractError(ProblemCode.OUTPUT_INVALID, "recovery_proposal.public_preview", "public preview must exactly match the expected snapshot, definition, fact, and action")
        if (proposal.actor_ref, proposal.room_ref, proposal.recovery_ref, proposal.definition_sha256) != (snapshot.actor_ref, snapshot.room_ref, snapshot.recovery_ref, snapshot.definition_sha256) or _plain(proposal.manifest_pins) != _plain(snapshot.manifest_pins) or _plain(proposal.source_revisions) != _plain(snapshot.revisions): raise PortContractError(ProblemCode.RESULT_STALE, "recovery_proposal", "proposal identity, pins or source revisions do not bind expected snapshot")
        private = proposal.private_reconciliation
        if isinstance(private, Mapping) and (proposal.kind in {RecoveryProposalKind.START, RecoveryProposalKind.RESUME, RecoveryProposalKind.CANCEL} or proposal.kind is RecoveryProposalKind.INTERRUPT and "actor_ref" in private):
            expected_identity = (snapshot.actor_ref, snapshot.room_ref, snapshot.recovery_ref, snapshot.definition_sha256)
            expected_phase_after = {RecoveryProposalKind.START: "started", RecoveryProposalKind.RESUME: "started", RecoveryProposalKind.CANCEL: "cancelled", RecoveryProposalKind.INTERRUPT: "interrupted"}[proposal.kind]
            if private["phase_before"] != snapshot.phase or private["phase_after"] != expected_phase_after or tuple(private[k] for k in ("actor_ref", "room_ref", "recovery_ref", "definition_sha256")) != expected_identity or _plain(private["base_revisions"]) != _plain(snapshot.revisions) or _plain(private["manifest_pins"]) != _plain(snapshot.manifest_pins): raise PortContractError(ProblemCode.RESULT_STALE, "private_reconciliation", "intent phase and identity do not bind the expected snapshot/action")
        if isinstance(private, Mapping) and (proposal.kind in {RecoveryProposalKind.ALLOCATE, RecoveryProposalKind.COMPLETE} or proposal.kind is RecoveryProposalKind.INTERRUPT and "progress_fact" in private):
            fact = private["progress_fact"]; pending = snapshot.pending_operation
            if snapshot.progress_fact is None or _plain(fact) != _plain(snapshot.progress_fact) or fact["recovery_ref"] != snapshot.recovery_ref or fact["definition_sha256"] != snapshot.definition_sha256 or _plain(fact["base_revisions"]) != _plain(snapshot.revisions) or _plain(fact["manifest_pins"]) != _plain(snapshot.manifest_pins) or pending is None or tuple(fact[k] for k in ("operation_ref", "idempotency_key", "request_fingerprint")) != tuple(pending[k] for k in ("operation_ref", "idempotency_key", "request_fingerprint")): raise PortContractError(ProblemCode.RESULT_STALE, "private_reconciliation.progress_fact", "fact must exactly equal the platform fact in the expected snapshot and bind its pending operation")
        if isinstance(private, Mapping) and proposal.kind is RecoveryProposalKind.RECONCILE and isinstance(private.get("receipt"), Mapping):
            receipt = private["receipt"]; pending = snapshot.pending_operation
            if snapshot.committed_receipt is None or canonical_fingerprint(_plain(receipt)) != canonical_fingerprint(_plain(snapshot.committed_receipt)): raise PortContractError(ProblemCode.RESULT_STALE, "private_reconciliation.receipt", "receipt must exactly equal the platform receipt in the expected snapshot")
            pending_bound = pending is not None and (receipt["proposal_ref"], receipt["proposal_fingerprint"]) == (pending["proposal_ref"], pending["proposal_fingerprint"])
            terminal_bound = snapshot.reconciliation_state == "RECONCILED" and snapshot.committed_receipt is not None and receipt["fingerprint"] == snapshot.committed_receipt["fingerprint"]
            if receipt["recovery_ref"] != snapshot.recovery_ref or receipt["definition_sha256"] != snapshot.definition_sha256 or _plain(receipt["base_revisions"]) != _plain(snapshot.revisions) or _plain(receipt["manifest_pins"]) != _plain(snapshot.manifest_pins) or not (pending_bound or terminal_bound): raise PortContractError(ProblemCode.RESULT_STALE, "private_reconciliation.receipt", "receipt identity does not bind the expected recovery operation")
    return result


def to_json_value(value: Any) -> Any:
    if isinstance(value, StrEnum): return value.value
    if hasattr(value, "__dataclass_fields__"): return {name: to_json_value(getattr(value, name)) for name in value.__dataclass_fields__}
    if isinstance(value, Mapping): return {str(k): to_json_value(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)): return [to_json_value(x) for x in value]
    return value


__all__ = [name for name in globals() if name.startswith("RECOVERY_") or name.startswith("Recovery") or name in {"compile_recovery_cycle_definitions", "bind_recovery_cycle", "decode_recovery_snapshot", "decode_recovery_request", "decode_recovery_proposal", "decode_recovery_result", "recovery_snapshot_fingerprint", "recovery_request_fingerprint", "recovery_authorization_request_fingerprint", "recovery_authorization_subject_fingerprint", "recovery_fact_proposal_identity", "recovery_proposal_fingerprint", "recovery_result_fingerprint", "to_json_value"}]
