"""Immutable Profile Registry and the frozen SE 1 P0 profile set."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from story_engine.contracts.authoring import AuthoringContractError, _fail, parse_author_envelope, parse_semver, version_satisfies
from story_engine.versions import PROFILE_CONTRACT_VERSION, PROFILE_REGISTRY_SCHEMA

_PROFILE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DEFAULT_BUDGETS = MappingProxyType(
    {
        "max_rounds": 12,
        "max_checkpoints": 12,
        "max_loop_iterations": 4,
        "max_concurrent_fronts": 1,
        "max_cascade_events": 8,
        "max_cross_module_effects": 16,
        "max_local_ms": 500,
        "max_context_tokens": 8_000,
        "max_pressure_rounds": 6,
        "recovery_window_rounds": 3,
    }
)


@dataclass(frozen=True, slots=True)
class ProfileContract:
    profile_id: str
    version: str
    phase: str
    contract_owner: str
    evaluation_owner: str
    authority_owner: str
    execution_owner: str
    projection_owner: str
    late_result_policy: str
    allowed_scope_kinds: frozenset[str]
    required_capabilities: tuple[str, ...]
    allowed_capabilities: tuple[str, ...]
    min_checkpoints: int
    max_checkpoints: int
    required_profile_fields: frozenset[str]
    allowed_profile_fields: frozenset[str]
    budget_limits: Mapping[str, int]
    safety_boundaries: tuple[str, ...]
    required_capability_ranges: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if _PROFILE_RE.fullmatch(self.profile_id) is None:
            raise ValueError("profile.id_invalid")
        parse_semver(self.version, path=f"profiles.{self.profile_id}.version")
        if self.phase != "P0":
            raise ValueError("profile.phase_invalid")
        if self.min_checkpoints < 0 or self.max_checkpoints < self.min_checkpoints:
            raise ValueError("profile.checkpoint_bounds_invalid")
        if not self.required_profile_fields <= self.allowed_profile_fields:
            raise ValueError("profile.required_fields_invalid")
        if set(self.budget_limits) != set(_DEFAULT_BUDGETS):
            raise ValueError("profile.budget_fields_invalid")
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in self.budget_limits.values()):
            raise ValueError("profile.budget_values_invalid")
        if len(self.required_capabilities) != len(set(self.required_capabilities)):
            raise ValueError("profile.capability_duplicate")
        if not set(self.required_capabilities) <= set(self.allowed_capabilities):
            raise ValueError("profile.capability_not_allowed")
        ranges = dict(self.required_capability_ranges)
        if not set(ranges) <= set(self.required_capabilities):
            raise ValueError("profile.capability_range_not_required")
        for capability_id, requirement in ranges.items():
            if not isinstance(requirement, str) or not requirement.strip():
                raise ValueError("profile.capability_range_invalid")
            version_satisfies("0.0.0", requirement, path=f"profiles.{self.profile_id}.required_capability_ranges.{capability_id}")
        object.__setattr__(self, "required_capability_ranges", MappingProxyType(dict(sorted(ranges.items()))))
        if not self.allowed_scope_kinds:
            raise ValueError("profile.scope_empty")
        if any(not value.strip() for value in (
            self.contract_owner, self.evaluation_owner, self.authority_owner,
            self.execution_owner, self.projection_owner, self.late_result_policy,
        )):
            raise ValueError("profile.owner_missing")
        if not self.safety_boundaries or any(not item.strip() for item in self.safety_boundaries):
            raise ValueError("profile.safety_boundary_missing")

    def validate_profile_data(self, value: Mapping[str, Any]) -> None:
        unknown = set(value) - set(self.allowed_profile_fields)
        if unknown:
            _fail("profile.field_unknown", "profile_data", "当前 profile 包含未知字段：" + "、".join(sorted(unknown)), "仅使用 Profile Registry 允许的字段。")
        missing = set(self.required_profile_fields) - set(value)
        if missing:
            _fail("profile.field_missing", "profile_data", "当前 profile 缺少字段：" + "、".join(sorted(missing)), "补齐 Profile Registry 要求的字段。")

    def contract_material(self) -> dict[str, Any]:
        material = {
            "profile_id": self.profile_id,
            "version": self.version,
            "phase": self.phase,
            "contract_owner": self.contract_owner,
            "evaluation_owner": self.evaluation_owner,
            "authority_owner": self.authority_owner,
            "execution_owner": self.execution_owner,
            "projection_owner": self.projection_owner,
            "late_result_policy": self.late_result_policy,
            "allowed_scope_kinds": sorted(self.allowed_scope_kinds),
            "required_capabilities": list(self.required_capabilities),
            "allowed_capabilities": list(self.allowed_capabilities),
            "min_checkpoints": self.min_checkpoints,
            "max_checkpoints": self.max_checkpoints,
            "required_profile_fields": sorted(self.required_profile_fields),
            "allowed_profile_fields": sorted(self.allowed_profile_fields),
            "budget_limits": dict(self.budget_limits),
            "safety_boundaries": list(self.safety_boundaries),
        }
        # Append-only successor metadata: an empty map is omitted so every P0
        # contract and the se1-p0/3 Registry fingerprint remain byte-identical.
        if self.required_capability_ranges:
            material["required_capability_ranges"] = dict(self.required_capability_ranges)
        return material

    @property
    def contract_sha256(self) -> str:
        """Fingerprint one exact profile version; registry ordering cannot change this identity."""
        canonical = json.dumps(self.contract_material(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(canonical).hexdigest()

    def to_mapping(self) -> dict[str, Any]:
        return {**self.contract_material(), "contract_sha256": self.contract_sha256}


class ProfileRegistry:
    """Frozen registry keyed by the exact (profile_id, version) pair.

    No implicit default/latest lookup exists: old and new profile contracts may coexist
    without changing the meaning of already compiled Story Packs.
    """

    schema = PROFILE_REGISTRY_SCHEMA
    registry_version = "1.1.0"
    selection_policy = "exact_version_required"

    def __init__(self, contracts: Iterable[ProfileContract], *, revision: str) -> None:
        if not isinstance(revision, str) or not revision.strip() or len(revision) > 128:
            raise ValueError("profile.registry_revision_invalid")
        material = tuple(contracts)
        by_key: dict[tuple[str, str], ProfileContract] = {}
        for contract in material:
            key = (contract.profile_id, contract.version)
            if key in by_key:
                raise ValueError("engine.profile_version_unsupported")
            by_key[key] = contract
        if not by_key:
            raise ValueError("profile.registry_empty")
        self._contracts = MappingProxyType(dict(sorted(by_key.items())))
        self.revision = revision.strip()
        fingerprint_material = {
            "schema": self.schema,
            "registry_version": self.registry_version,
            "revision": self.revision,
            "selection_policy": self.selection_policy,
            "profiles": [item.to_mapping() for item in self._contracts.values()],
        }
        canonical = json.dumps(fingerprint_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.fingerprint = "sha256:" + hashlib.sha256(canonical).hexdigest()

    @property
    def profile_ids(self) -> tuple[str, ...]:
        return tuple(sorted({profile_id for profile_id, _ in self._contracts}))

    @property
    def profile_keys(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._contracts)

    def resolve(self, profile_id: str, version: str) -> ProfileContract:
        known_ids = {item[0] for item in self._contracts}
        if str(profile_id) not in known_ids:
            _fail("profile.unknown", "profile", "事件 profile 未注册。", "选择 Profile Registry 中的 profile。")
        if not isinstance(version, str) or not version.strip():
            _fail("engine.profile_version_unsupported", "profile_version", "事件 profile 必须声明精确版本。", "提供 Registry 中存在的 profile_version；禁止使用 latest 或默认版本。")
        contract = self._contracts.get((str(profile_id), version.strip()))
        if contract is None:
            _fail("engine.profile_version_unsupported", "profile_version", "事件 profile 精确版本不受支持。", "选择 Registry 中存在的精确版本；禁止回退到其他版本。")
        return contract

    def parse(self, source: Mapping[str, Any]):
        profile_id = str(source.get("profile") or "")
        version = str(source.get("profile_version") or "")
        return parse_author_envelope(source, profile_contract=self.resolve(profile_id, version))

    def verify_fingerprint(self, fingerprint: str) -> None:
        """Reject a Registry identity that does not match the exact frozen contents."""
        if fingerprint != self.fingerprint:
            raise ValueError("engine.profile_fingerprint_mismatch")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "registry_version": self.registry_version,
            "revision": self.revision,
            "selection_policy": self.selection_policy,
            "fingerprint": self.fingerprint,
            "profiles": [item.to_mapping() for item in self._contracts.values()],
        }


def _budget(**overrides: int) -> Mapping[str, int]:
    result = dict(_DEFAULT_BUDGETS)
    result.update(overrides)
    return MappingProxyType(result)


_OWNER = {
    "contract_owner": "321 Story Engine Profile Registry",
    "evaluation_owner": "321 Story Engine deterministic event evaluator",
    "authority_owner": "321 Roll platform and specialized fate/rescue/terminal services",
    "execution_owner": "321 Roll TurnCommitPlan executor",
    "projection_owner": "321 Roll PlayView/ModulePlayView projectors",
    "late_result_policy": "platform rejects cancelled, expired, fingerprint-mismatched, or stale-revision proposals; no partial commit",
}


P0_PROFILE_REGISTRY = ProfileRegistry(
    (
        ProfileContract(
            "ambient_event", PROFILE_CONTRACT_VERSION, "P0", **_OWNER,
            allowed_scope_kinds=frozenset({"scene", "site", "region"}),
            required_capabilities=("event.orchestrate",),
            allowed_capabilities=("event.orchestrate", "event.project"),
            min_checkpoints=0, max_checkpoints=1,
            required_profile_fields=frozenset(),
            allowed_profile_fields=frozenset({"weight"}),
            budget_limits=_budget(max_rounds=1, max_checkpoints=1, max_loop_iterations=1, max_cascade_events=1, max_cross_module_effects=1, max_pressure_rounds=1, recovery_window_rounds=1),
            safety_boundaries=("low risk only", "no actor fate", "no campaign terminal", "mechanical risk above threshold requires profile upgrade"),
        ),
        ProfileContract(
            "omen_event", PROFILE_CONTRACT_VERSION, "P0", **_OWNER,
            allowed_scope_kinds=frozenset({"scene", "site", "region", "faction", "campaign"}),
            required_capabilities=("event.orchestrate", "event.omen"),
            allowed_capabilities=("event.orchestrate", "event.omen", "event.project", "event.pressure"),
            min_checkpoints=0, max_checkpoints=2,
            required_profile_fields=frozenset({"signal_audience", "truth_refs"}),
            allowed_profile_fields=frozenset({"signal_audience", "truth_refs", "investigation_routes"}),
            budget_limits=_budget(max_rounds=4, max_checkpoints=2, max_loop_iterations=1, max_cascade_events=2, max_cross_module_effects=2, max_pressure_rounds=2, recovery_window_rounds=1),
            safety_boundaries=("may signal or alter preparation only", "hidden truth must reference authoritative facts", "no irreversible catastrophe effect"),
        ),
        ProfileContract(
            "crisis_event", PROFILE_CONTRACT_VERSION, "P0", **_OWNER,
            allowed_scope_kinds=frozenset({"scene", "site", "region", "faction", "quest", "actor_group"}),
            required_capabilities=("event.orchestrate",),
            allowed_capabilities=("event.orchestrate", "event.consequence", "event.project", "event.pressure"),
            min_checkpoints=1, max_checkpoints=3,
            required_profile_fields=frozenset({"risk_summary"}),
            allowed_profile_fields=frozenset({"risk_summary", "tactical_entry"}),
            budget_limits=_budget(max_rounds=6, max_checkpoints=3, max_loop_iterations=2, max_cascade_events=3, max_cross_module_effects=6, max_pressure_rounds=4, recovery_window_rounds=2),
            safety_boundaries=("failure-forward remains inside declared local scope", "at least one handling route", "campaign terminal disabled by default"),
        ),
        ProfileContract(
            "crisis_event", "1.1.0", "P0", **_OWNER,
            allowed_scope_kinds=frozenset({"scene", "site", "region", "faction", "quest", "actor_group"}),
            required_capabilities=("event.orchestrate",),
            allowed_capabilities=("event.orchestrate", "event.consequence", "event.project", "event.pressure", "actor.resource_pool", "actor.vitality"),
            min_checkpoints=1, max_checkpoints=3,
            required_profile_fields=frozenset({"risk_summary"}),
            allowed_profile_fields=frozenset({"risk_summary", "tactical_entry"}),
            budget_limits=_budget(max_rounds=6, max_checkpoints=3, max_loop_iterations=2, max_cascade_events=3, max_cross_module_effects=6, max_pressure_rounds=4, recovery_window_rounds=2),
            safety_boundaries=(
                "resource and vitality effects are proposal-only",
                "vitality depletion is signal-only",
                "failure-forward remains inside declared local scope",
            ),
        ),
        ProfileContract(
            "catastrophic_event", PROFILE_CONTRACT_VERSION, "P0", **_OWNER,
            allowed_scope_kinds=frozenset({"site", "region", "faction", "quest", "actor_group", "campaign"}),
            required_capabilities=("event.orchestrate", "event.consequence"),
            allowed_capabilities=("event.orchestrate", "event.omen", "event.consequence", "event.aftermath", "event.causal_ledger", "event.project", "event.pressure"),
            min_checkpoints=2, max_checkpoints=12,
            required_profile_fields=frozenset({"warning", "recovery_windows"}),
            allowed_profile_fields=frozenset({"warning", "recovery_windows", "terminal_candidate_policy"}),
            budget_limits=_budget(),
            safety_boundaries=("warnings and meaningful agency precede irreversible gates", "fate and terminal are proposals to specialized authority owners", "recovery and human takeover remain explicit"),
        ),
        ProfileContract(
            "catastrophic_event", "1.1.0", "P0", **_OWNER,
            allowed_scope_kinds=frozenset({"site", "region", "faction", "quest", "actor_group", "campaign"}),
            required_capabilities=("event.orchestrate", "event.consequence", "event.omen", "event.aftermath"),
            allowed_capabilities=("event.orchestrate", "event.omen", "event.consequence", "event.aftermath", "event.causal_ledger", "event.project", "event.pressure"),
            min_checkpoints=4, max_checkpoints=12,
            required_profile_fields=frozenset({
                "schema", "category", "public_risk", "known_consequences", "deadline",
                "response_routes", "consequence_classes", "human_dm_checkpoint_ref",
                "aftermath_checkpoint_ref", "recovery_windows", "capability_mode",
            }),
            allowed_profile_fields=frozenset({
                "schema", "category", "public_risk", "known_consequences", "deadline",
                "response_routes", "consequence_classes", "human_dm_checkpoint_ref",
                "aftermath_checkpoint_ref", "recovery_windows", "capability_mode",
                "fate_checkpoint_ref", "terminal_checkpoint_ref",
            }),
            budget_limits=_budget(),
            safety_boundaries=(
                "maximum and subset chains share one deterministic event evaluator",
                "ordinary failure never creates actor fate or terminal authority",
                "fate requires actor consent and terminal arbitration requires host authority",
                "public omen deadline safe exit recovery and aftermath are mandatory",
            ),
        ),
        ProfileContract(
            "interlude_event", PROFILE_CONTRACT_VERSION, "P0", **_OWNER,
            allowed_scope_kinds=frozenset({"scene", "site", "actor_group"}),
            required_capabilities=("event.orchestrate", "event.aftermath"),
            allowed_capabilities=("event.orchestrate", "event.aftermath", "event.project"),
            min_checkpoints=1, max_checkpoints=3,
            required_profile_fields=frozenset({"participant_policy", "action_allowance", "skip_consequence", "completion_condition"}),
            allowed_profile_fields=frozenset({"participant_policy", "action_allowance", "skip_consequence", "completion_condition", "costs", "timeout"}),
            budget_limits=_budget(max_rounds=3, max_checkpoints=3, max_loop_iterations=1, max_cascade_events=1, max_cross_module_effects=6, max_pressure_rounds=1, recovery_window_rounds=1),
            safety_boundaries=("non-participants are not assigned actions", "cannot undo confirmed permanent consequences", "participation costs skip and completion are explicit"),
        ),
        ProfileContract(
            "aftermath_event", PROFILE_CONTRACT_VERSION, "P0", **_OWNER,
            allowed_scope_kinds=frozenset({"scene", "site", "region", "faction", "quest", "actor_group", "campaign"}),
            required_capabilities=("event.orchestrate", "event.aftermath", "event.causal_ledger"),
            allowed_capabilities=("event.orchestrate", "event.aftermath", "event.causal_ledger", "event.project"),
            min_checkpoints=1, max_checkpoints=3,
            required_profile_fields=frozenset({"cause_event_ref", "participant_policy", "action_allowance", "skip_consequence", "completion_condition"}),
            allowed_profile_fields=frozenset({"cause_event_ref", "participant_policy", "action_allowance", "skip_consequence", "completion_condition", "costs", "timeout"}),
            budget_limits=_budget(max_rounds=3, max_checkpoints=3, max_loop_iterations=1, max_cascade_events=1, max_cross_module_effects=8, max_pressure_rounds=1, recovery_window_rounds=1),
            safety_boundaries=("must reference a committed cause event", "non-participants are not assigned actions", "cannot undo confirmed permanent consequences"),
        ),
        ProfileContract(
            "character_build_event", "1.0.0", "P0", **_OWNER,
            allowed_scope_kinds=frozenset({"campaign", "actor_group"}),
            required_capabilities=("event.orchestrate",),
            allowed_capabilities=("event.orchestrate", "character.build", "event.project"),
            min_checkpoints=3, max_checkpoints=8,
            required_profile_fields=frozenset({"recipe_ref"}),
            allowed_profile_fields=frozenset({"recipe_ref"}),
            budget_limits=_budget(max_rounds=16, max_checkpoints=8, max_loop_iterations=8, max_cascade_events=1, max_cross_module_effects=1, max_pressure_rounds=1, recovery_window_rounds=16),
            safety_boundaries=(
                "platform owns account slot actor identity draft persistence and ownership receipt",
                "random outcomes require platform receipts",
                "final actor creation requires explicit self confirmation",
            ),
        ),
        ProfileContract(
            "advancement_event", "1.0.0", "P0", **_OWNER,
            allowed_scope_kinds=frozenset({"actor_group", "campaign"}),
            required_capabilities=("event.orchestrate",),
            allowed_capabilities=("event.orchestrate", "character.progression", "event.project"),
            min_checkpoints=3, max_checkpoints=8,
            required_profile_fields=frozenset({"progression_ref"}),
            allowed_profile_fields=frozenset({"progression_ref"}),
            budget_limits=_budget(max_rounds=16, max_checkpoints=8, max_loop_iterations=8, max_cascade_events=2, max_cross_module_effects=8, max_pressure_rounds=1, recovery_window_rounds=16),
            safety_boundaries=(
                "only committed reward milestone or cause receipts create eligibility",
                "duplicate cause and dedupe keys never produce repeated growth",
                "platform owns xp level rank points unlock state commits receipts events and outbox",
                "permanent respec requires actor self confirmation and platform gate",
            ),
        ),
    ),
    revision="se1-p0/3",
)


_P0_PRESERVED_IDENTITIES = {
    ("crisis_event", "1.0.0"): "sha256:5b644ff0288a5391e9d28bec1e98ac2eab44c5ef0dae1bfff690096adbfd65f2",
    ("crisis_event", "1.1.0"): "sha256:190309912c1f65e6a81f7f4eada4ed444f6d0d965cc972943ae638f1510aec9d",
}
if P0_PROFILE_REGISTRY.fingerprint != "sha256:ecf4f307653b826aff0b723c1d665faed70611627d00faa888f1ff28456674bc":
    raise RuntimeError("profile.p0_registry_identity_mutated")
if any(P0_PROFILE_REGISTRY.resolve(*key).contract_sha256 != expected for key, expected in _P0_PRESERVED_IDENTITIES.items()):
    raise RuntimeError("profile.crisis_contract_identity_mutated")


# Every successor below is an explicit next-version opt-in. The formal P0
# registry above remains byte-for-byte compatible with already compiled packs.
_CONFLICT_V3_PROFILE_CONTRACT = ProfileContract(
    "conflict_event", "1.0.0", "P0", **_OWNER,
    allowed_scope_kinds=frozenset({"scene", "site", "region", "faction", "quest", "actor_group"}),
    required_capabilities=("event.orchestrate", "conflict.procedure"),
    allowed_capabilities=(
        "event.orchestrate", "event.consequence", "event.project", "event.pressure",
        "actor.resource_pool", "actor.vitality", "turn.interaction", "resolution.check",
        "ability.execution", "conflict.procedure",
    ),
    min_checkpoints=1, max_checkpoints=8,
    required_profile_fields=frozenset({"risk_summary"}),
    allowed_profile_fields=frozenset({"risk_summary", "tactical_entry"}),
    budget_limits=_budget(max_rounds=16, max_checkpoints=8, max_loop_iterations=8, max_cascade_events=4, max_cross_module_effects=16, max_pressure_rounds=8, recovery_window_rounds=8),
    safety_boundaries=(
        "conflict procedure is system-neutral and proposal-only",
        "negotiation retreat and surrender remain explicit exits",
        "vitality depletion is signal-only and permanent fate requires its dedicated authority chain",
        "platform owns priority receipts state commits cause receipts and aftermath commits",
    ),
)

_RECOVERY_V2_PROFILE_CONTRACT = ProfileContract(
    "recovery_event", "1.0.0", "P0", **_OWNER,
    allowed_scope_kinds=frozenset({"scene", "site", "actor_group"}),
    required_capabilities=("event.orchestrate", "recovery.cycle"),
    allowed_capabilities=("event.orchestrate", "event.aftermath", "event.project", "recovery.cycle"),
    min_checkpoints=1, max_checkpoints=5,
    required_profile_fields=frozenset({"recovery_ref"}),
    allowed_profile_fields=frozenset({"recovery_ref"}),
    budget_limits=_budget(max_rounds=8, max_checkpoints=5, max_loop_iterations=4, max_cascade_events=2, max_cross_module_effects=12, max_pressure_rounds=1, recovery_window_rounds=8),
    safety_boundaries=(
        "recovery evaluation is proposal-only and the platform owns every authoritative commit receipt event and outbox record",
        "committed partial progress survives cancellation interruption restart and replay",
        "ordinary recovery cannot revive vitality zero or erase permanent fate terminal injury or departure state",
        "vitality zero requires a platform rescue or fate gate and actor consent before any specialized authority action",
    ),
    required_capability_ranges={"recovery.cycle": "==1.1.0"},
)

CONFLICT_V3_PROFILE_REGISTRY = ProfileRegistry(
    (*P0_PROFILE_REGISTRY._contracts.values(), _CONFLICT_V3_PROFILE_CONTRACT),
    revision="se1-p0-conflict-v3/1",
)

RECOVERY_V2_PROFILE_REGISTRY = ProfileRegistry(
    (*P0_PROFILE_REGISTRY._contracts.values(), _RECOVERY_V2_PROFILE_CONTRACT),
    revision="se1-p0-recovery-v2/1",
)

# The union is built once from P0, not by extending either lane successor.
CONFLICT_RECOVERY_UNION_PROFILE_REGISTRY = ProfileRegistry(
    (
        *P0_PROFILE_REGISTRY._contracts.values(),
        _CONFLICT_V3_PROFILE_CONTRACT,
        _RECOVERY_V2_PROFILE_CONTRACT,
    ),
    revision="se1-p0-conflict-recovery-union/1",
)

_RECOVERY_2_PROFILE_CONTRACT = ProfileContract(
    "recovery_event", "2.0.0", "P0", **_OWNER,
    allowed_scope_kinds=frozenset({"scene", "site", "actor_group"}),
    required_capabilities=("event.orchestrate", "recovery.cycle"),
    allowed_capabilities=("event.orchestrate", "event.aftermath", "event.project", "recovery.cycle"),
    min_checkpoints=1, max_checkpoints=5,
    required_profile_fields=frozenset({"recovery_ref"}),
    allowed_profile_fields=frozenset({"recovery_ref"}),
    budget_limits=_budget(max_rounds=8, max_checkpoints=5, max_loop_iterations=4, max_cascade_events=2, max_cross_module_effects=12, max_pressure_rounds=1, recovery_window_rounds=8),
    safety_boundaries=(
        "recovery 2.0 is proposal-only and selects exact provider and resource identities",
        "platform runtime snapshots facts proposals and receipts own inventory revisions",
        "status eligibility is an explicit status_ref and recovery_class pair",
        "ordinary recovery cannot decide vitality-zero or terminal outcomes",
    ),
    required_capability_ranges={"recovery.cycle": "==2.0.0"},
)

RECOVERY_2_PROFILE_REGISTRY = ProfileRegistry(
    (*P0_PROFILE_REGISTRY._contracts.values(), _RECOVERY_2_PROFILE_CONTRACT),
    revision="se1-p0-recovery-v2/2",
)

CONFLICT_RECOVERY_UNION_V2_PROFILE_REGISTRY = ProfileRegistry(
    (
        *P0_PROFILE_REGISTRY._contracts.values(),
        _CONFLICT_V3_PROFILE_CONTRACT,
        _RECOVERY_2_PROFILE_CONTRACT,
    ),
    revision="se1-p0-conflict-recovery-union/2",
)

if _CONFLICT_V3_PROFILE_CONTRACT.contract_sha256 != "sha256:4a94f7cad67e01682985e7e95575a7148c37120a48d254161b5189d62a71c580":
    raise RuntimeError("profile.conflict_contract_identity_mutated")
if _RECOVERY_V2_PROFILE_CONTRACT.contract_sha256 != "sha256:d823555651f9d092a8bf08dab39fd0f7bc4608eed10beff1ec447a4d34d1ae34":
    raise RuntimeError("profile.recovery_contract_identity_mutated")
if _RECOVERY_2_PROFILE_CONTRACT.contract_sha256 != "sha256:dcc54fa772d2859f502704a77cab20c646e3ccbf7c167c4e953ec72dc9c9160c":
    raise RuntimeError("profile.recovery_2_contract_identity_mutated")
if CONFLICT_RECOVERY_UNION_V2_PROFILE_REGISTRY.fingerprint != "sha256:c72c428b0cf84b1e281e57c6314e21e11c2c390b8d568b3ba3da44a0f5b3f697":
    raise RuntimeError("profile.conflict_recovery_union_2_identity_mutated")


__all__ = [
    "CONFLICT_RECOVERY_UNION_PROFILE_REGISTRY", "CONFLICT_RECOVERY_UNION_V2_PROFILE_REGISTRY", "CONFLICT_V3_PROFILE_REGISTRY",
    "P0_PROFILE_REGISTRY", "RECOVERY_V2_PROFILE_REGISTRY", "RECOVERY_2_PROFILE_REGISTRY", "ProfileContract", "ProfileRegistry",
]
