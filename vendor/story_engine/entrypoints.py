"""Stable embedded and remote-dispatch entrypoints for proposal-only SE engines."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from .compiler import Artifact
from .contracts.events import (
    EventActivationRequest,
    EventAdvanceRequest,
    EventLifecycleStatus,
    EventStateSnapshot,
    GateDecision,
    GateResponseSnapshot,
)
from .contracts.port import (
    EngineTurnRequest,
    NarrativeMode,
    NarrativePolicySnapshot,
    NarrativePreset,
    OperationEnvelope,
    PlatformBridge,
    ProviderMode,
    ReadinessStatus,
    StoryEngineHandshake,
    StoryEngineReadiness,
    default_handshake,
    freeze_json,
)
from .narrative import NarrativeArtifactIdentity, NarrativeResolutionService
from .post_resolution import (
    POST_RESOLUTION_SNAPSHOT_CONTRACT,
    PostResolutionGenerationResult,
    PostResolutionGenerationService,
    PostResolutionGenerationSnapshot,
)
from .story_evolution import (
    STORY_EVOLUTION_CONTEXT_SCHEMA,
    STORY_EVOLUTION_PROPOSAL_BATCH_SCHEMA,
    StoryEvolutionGenerationService,
)
from .resources import (
    RESOURCE_EFFECT_EVALUATION_CONTRACT, ActorResourceSnapshot, DeterministicResourceEvaluator,
    ResourceEffectEvaluationRequest, ResourceEffectEvaluationResult, ResourceEffectEvaluationService,
    TypedEffectProposal,
)
from .runtime import DeterministicEventEvaluator, EventActivationService, EventEvaluationService, RuntimeEventCatalog
from .turn_interaction import (
    TURN_INTERACTION_CAPABILITY, PLAYER_TURN_INPUT_SCHEMA, TURN_INTERACTION_RESULT_SCHEMA,
    TURN_INTERACTION_SNAPSHOT_SCHEMA, TurnInteractionEvaluationRequest, TurnInteractionEvaluationResult, TurnInteractionSnapshot,
    TurnInteractionEvaluator, TurnInteractionService, decode_player_turn_input, decode_turn_interaction_snapshot,
)
from .resolution_check import (
    RESOLUTION_CHECK_CAPABILITY, RESOLUTION_CHECK_REQUEST_SCHEMA, RESOLUTION_CHECK_RESULT_SCHEMA,
    RESOLUTION_CHECK_SNAPSHOT_SCHEMA, ResolutionCheckEvaluator, ResolutionCheckRequest,
    ResolutionCheckResult, ResolutionCheckService, ResolutionCheckSnapshot,
    decode_resolution_check_request as decode_resolution_request,
)
from .character_build import CHARACTER_BUILD_CAPABILITY, CHARACTER_BUILD_REQUEST_SCHEMA, CHARACTER_BUILD_RESULT_SCHEMA, CHARACTER_BUILD_SNAPSHOT_SCHEMA, CharacterBuildDraftSnapshot, CharacterBuildEvaluator, CharacterBuildRequest, CharacterBuildResult, CharacterBuildService, decode_character_build_request
from .character_build_v11_runtime import (
    CHARACTER_BUILD_V11_REQUEST_SCHEMA, CHARACTER_BUILD_V11_RESULT_SCHEMA,
    CHARACTER_BUILD_V11_SNAPSHOT_SCHEMA, CharacterBuildV11Evaluator,
)
from .character_progression import CHARACTER_PROGRESSION_CAPABILITY, CHARACTER_PROGRESSION_REQUEST_SCHEMA, CHARACTER_PROGRESSION_RESULT_SCHEMA, CHARACTER_PROGRESSION_SNAPSHOT_SCHEMA, CharacterProgressionEvaluator, CharacterProgressionService, ProgressionRequest, ProgressionResult, ProgressionSnapshot, decode_progression_request
from .reward_settlement import REWARD_SETTLEMENT_CAPABILITY, REWARD_SETTLEMENT_REQUEST_SCHEMA, REWARD_SETTLEMENT_RESULT_SCHEMA, REWARD_SETTLEMENT_SNAPSHOT_SCHEMA, RewardRequest, RewardResult, RewardSettlementEvaluator, RewardSettlementService, RewardSnapshot, decode_reward_request
from .inventory_equipment import INVENTORY_EQUIPMENT_CAPABILITY, INVENTORY_REQUEST_SCHEMA, INVENTORY_RESULT_SCHEMA, INVENTORY_SNAPSHOT_SCHEMA, InventoryEquipmentEvaluator, InventoryEquipmentService, decode_inventory_request
from .ability_execution import ABILITY_EXECUTION_CAPABILITY, ABILITY_REQUEST_SCHEMA, ABILITY_RESULT_SCHEMA, ABILITY_SNAPSHOT_SCHEMA, AbilityExecutionEvaluator, AbilityExecutionService, decode_ability_request
from .conflict_procedure import CONFLICT_PROCEDURE_CAPABILITY, CONFLICT_REQUEST_SCHEMA, CONFLICT_RESULT_SCHEMA, CONFLICT_SNAPSHOT_SCHEMA, ConflictProcedureEvaluator, ConflictProcedureService, decode_conflict_request, validate_conflict_result_for_request
from .recovery_cycle import (
    RECOVERY_CYCLE_CAPABILITY, RECOVERY_REQUEST_SCHEMA, RECOVERY_RESULT_SCHEMA,
    RECOVERY_SNAPSHOT_SCHEMA, RecoveryAction, RecoveryCycleEvaluator,
    RecoveryCycleService, decode_recovery_request,
)
from .recovery_cycle_v2 import (
    RECOVERY_CYCLE_CAPABILITY as RECOVERY_CYCLE_V2_CAPABILITY,
    RECOVERY_REQUEST_SCHEMA as RECOVERY_V2_REQUEST_SCHEMA,
    RECOVERY_RESULT_SCHEMA as RECOVERY_V2_RESULT_SCHEMA,
    RECOVERY_SNAPSHOT_SCHEMA as RECOVERY_V2_SNAPSHOT_SCHEMA,
    RecoveryAction as RecoveryV2Action,
    RecoveryCycleEvaluator as RecoveryCycleV2Evaluator,
    RecoveryCycleService as RecoveryCycleV2Service,
    decode_recovery_request as decode_recovery_v2_request,
)
from .versions import PLATFORM_BRIDGE_VERSION, STORY_ENGINE_DISTRIBUTION_VERSION

REMOTE_DISPATCH_VERSION = "se-remote-dispatch/1.0.0"
NARRATIVE_REMOTE_DISPATCH_VERSION = "se-remote-dispatch/1.2.0"
RESOURCE_REMOTE_DISPATCH_VERSION = "se-remote-dispatch/1.3.0"
TURN_INTERACTION_REMOTE_DISPATCH_VERSION = "se-remote-dispatch/1.5.0"
RESOLUTION_CHECK_REMOTE_DISPATCH_VERSION = "se-remote-dispatch/1.6.0"
CHARACTER_BUILD_REMOTE_DISPATCH_VERSION = "se-remote-dispatch/1.7.0"
CHARACTER_PROGRESSION_REMOTE_DISPATCH_VERSION = "se-remote-dispatch/1.8.0"
REWARD_SETTLEMENT_REMOTE_DISPATCH_VERSION = "se-remote-dispatch/1.9.0"
INVENTORY_EQUIPMENT_REMOTE_DISPATCH_VERSION = "se-remote-dispatch/1.10.0"
ABILITY_EXECUTION_REMOTE_DISPATCH_VERSION = "se-remote-dispatch/1.11.0"
CONFLICT_PROCEDURE_REMOTE_DISPATCH_VERSION = "se-remote-dispatch/1.12.0"
RECOVERY_CYCLE_REMOTE_DISPATCH_VERSION = "se-remote-dispatch/1.13.0"
RECOVERY_CYCLE_V2_REMOTE_DISPATCH_VERSION = "se-remote-dispatch/1.14.0"
POST_RESOLUTION_REMOTE_DISPATCH_VERSION = "se-post-resolution-remote-dispatch/1.0.0"
STORY_EVOLUTION_REMOTE_DISPATCH_VERSION = "se-story-evolution-remote-dispatch/1.0.0"
_HANDSHAKE_FEATURES = frozenset({
    "base.handshake/1", "capability-reporting/1", "pack-independent-handshake/1", "proposal-only/1",
})
_ENGINE_CAPABILITIES = frozenset({
    "actor.resource_pool/1.0.0", "actor.vitality/1.0.0", "base.handshake/1", "base.narrative/1",
    "character.state.effects/1", "event.evaluate/1", "narrative.stream/1",
    "event.guard.evaluate/1.0.0",
})
_PROVIDER_REQUIREMENTS = {
    "credential_owner": "321_platform", "required": ["structured_output"], "optional": ["streaming"],
}
_EVENT_REQUEST_FIELDS = frozenset({
    "envelope", "event_state", "actor_snapshot", "action_roster_snapshot", "legal_action_refs",
    "allowed_capability_refs", "selected_action_ref", "route_choice_ref", "gate_response",
    "world_snapshot", "rule_snapshot", "narrative_snapshot", "committed_receipt_refs",
})
_ACTIVATION_REQUEST_FIELDS = frozenset({
    "schema", "envelope", "event_state", "actor_snapshot", "action_roster_snapshot",
    "allowed_capability_refs", "gate_response", "world_snapshot", "rule_snapshot",
    "narrative_snapshot", "committed_receipt_refs",
})
_TURN_REQUEST_FIELDS = frozenset({
    "envelope", "story_pack_ref", "canonical_sha256", "artifact_ref", "artifact_sha256",
    "actor_snapshot", "action_roster_snapshot", "next_actor_ref", "player_input",
    "rule_and_module_snapshot", "narrative_policy", "generation_policy",
    "visibility_policy", "fact_snapshot",
})
_POLICY_FIELDS = frozenset({
    "contract_version", "mode", "min_visible_chars", "max_visible_chars", "mode_revision",
    "preset", "compiled_instruction", "world_voice_summary", "source_world_style_sha256",
    "style_revision", "policy_fingerprint",
})
_RESOURCE_EFFECT_REQUEST_FIELDS = frozenset({
    "schema", "envelope", "artifact_ref", "artifact_sha256", "allowed_capability_refs", "capability_closure_sha256", "intent", "resource_snapshot",
    "proposal_ref", "dedupe_key", "atomic_group_ref",
})


def _json_value(value: Any) -> Any:
    if isinstance(value, (TurnInteractionSnapshot, ResolutionCheckSnapshot, CharacterBuildDraftSnapshot, ProgressionSnapshot)):
        return value.to_mapping()
    if isinstance(value, (TypedEffectProposal, ResourceEffectEvaluationResult)):
        return value.to_mapping()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


class EngineContractError(RuntimeError):
    """Stable fail-closed error raised before request decoding or Bridge access."""

    def __init__(self, code: str, failed_operation: str, reason: str, next_action: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.failed_operation = failed_operation
        self.reason = reason
        self.next_action = next_action
        self.retryable = retryable

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": "se-engine-problem/1.0.0",
            "code": self.code,
            "failed_operation": self.failed_operation,
            "reason": self.reason,
            "automatic_handling": "Engine stopped before reading the request or calling PlatformBridge.",
            "next_action": self.next_action,
            "retryable": self.retryable,
            "bridge_calls": 0,
            "provider_calls": 0,
        }


def _artifact_unavailable(operation: str) -> EngineContractError:
    return EngineContractError(
        "engine.artifact_unavailable",
        operation,
        "The Story Artifact is not configured for this Engine instance.",
        "Supply both artifact and artifact_ref from the fixed, authorized installation before retrying.",
        retryable=True,
    )


def _input_invalid(operation: str, reason: str) -> EngineContractError:
    return EngineContractError(
        "engine.input_invalid", operation, reason,
        "Supply both artifact and artifact_ref, or omit both for handshake-only mode.", retryable=False,
    )


def decode_event_advance_request(payload: Mapping[str, Any]) -> EventAdvanceRequest:
    """Decode the complete public JSON DTO; missing or extra semantic data fails in DTO constructors."""

    value = freeze_json(payload, "event_advance_request")
    if set(value) != _EVENT_REQUEST_FIELDS:
        raise ValueError("event advance request fields do not match the frozen contract")
    envelope = OperationEnvelope(**dict(value["envelope"]))
    state_value = dict(value["event_state"])
    state_value["status"] = EventLifecycleStatus(state_value["status"])
    state = EventStateSnapshot(**state_value)
    gate_value = value.get("gate_response")
    gate = None
    if gate_value is not None:
        gate_data = dict(gate_value)
        gate_data["decision"] = GateDecision(gate_data["decision"])
        gate = GateResponseSnapshot(**gate_data)
    return EventAdvanceRequest(
        envelope=envelope,
        event_state=state,
        actor_snapshot=value["actor_snapshot"],
        action_roster_snapshot=tuple(value["action_roster_snapshot"]),
        legal_action_refs=tuple(value["legal_action_refs"]),
        allowed_capability_refs=tuple(value["allowed_capability_refs"]),
        selected_action_ref=value.get("selected_action_ref"),
        route_choice_ref=value.get("route_choice_ref"),
        gate_response=gate,
        world_snapshot=value["world_snapshot"],
        rule_snapshot=value["rule_snapshot"],
        narrative_snapshot=value["narrative_snapshot"],
        committed_receipt_refs=tuple(value["committed_receipt_refs"]),
    )


def decode_event_activation_request(payload: Mapping[str, Any]) -> EventActivationRequest:
    value = freeze_json(payload, "event_activation_request")
    if set(value) != _ACTIVATION_REQUEST_FIELDS or value.get("schema") != "se-event-activation/1.0.0":
        raise ValueError("event activation request fields do not match the frozen extension contract")
    envelope = OperationEnvelope(**dict(value["envelope"]))
    state_value = dict(value["event_state"]); state_value["status"] = EventLifecycleStatus(state_value["status"])
    gate_value = value.get("gate_response")
    gate = None
    if gate_value is not None:
        gate_data = dict(gate_value); gate_data["decision"] = GateDecision(gate_data["decision"]); gate = GateResponseSnapshot(**gate_data)
    return EventActivationRequest(
        str(value["schema"]), envelope, EventStateSnapshot(**state_value), value["actor_snapshot"], tuple(value["action_roster_snapshot"]),
        tuple(value["allowed_capability_refs"]), gate, value["world_snapshot"], value["rule_snapshot"], value["narrative_snapshot"], tuple(value["committed_receipt_refs"]),
    )


def decode_turn_request(payload: Mapping[str, Any]) -> EngineTurnRequest:
    """Decode the exact public EngineTurnRequest DTO and reject unknown fields."""

    value = freeze_json(payload, "engine_turn_request")
    if set(value) != _TURN_REQUEST_FIELDS:
        raise ValueError("engine turn request fields do not match the frozen contract")
    envelope = OperationEnvelope(**dict(value["envelope"]))
    policy_value = value["narrative_policy"]
    if not isinstance(policy_value, Mapping) or set(policy_value) != _POLICY_FIELDS:
        raise ValueError("narrative policy fields do not match the frozen contract")
    policy = NarrativePolicySnapshot(
        str(policy_value["contract_version"]),
        NarrativeMode(str(policy_value["mode"])),
        int(policy_value["min_visible_chars"]),
        int(policy_value["max_visible_chars"]),
        int(policy_value["mode_revision"]),
        NarrativePreset(str(policy_value["preset"])),
        str(policy_value["compiled_instruction"]),
        str(policy_value["world_voice_summary"]),
        str(policy_value["source_world_style_sha256"]),
        int(policy_value["style_revision"]),
        str(policy_value["policy_fingerprint"]),
    )
    return EngineTurnRequest(
        envelope,
        str(value["story_pack_ref"]),
        str(value["canonical_sha256"]),
        str(value["artifact_ref"]),
        str(value["artifact_sha256"]),
        value["actor_snapshot"],
        tuple(value["action_roster_snapshot"]),
        str(value["next_actor_ref"]),
        value["player_input"],
        value["rule_and_module_snapshot"],
        policy,
        value["generation_policy"],
        value["visibility_policy"],
        value["fact_snapshot"],
    )


def decode_resource_effect_request(payload: Mapping[str, Any]) -> ResourceEffectEvaluationRequest:
    value = freeze_json(payload, "resource_effect_evaluation_request")
    if set(value) != _RESOURCE_EFFECT_REQUEST_FIELDS or value.get("schema") != RESOURCE_EFFECT_EVALUATION_CONTRACT:
        raise ValueError("resource effect request fields do not match the frozen extension contract")
    return ResourceEffectEvaluationRequest(
        OperationEnvelope(**dict(value["envelope"])),
        str(value["artifact_ref"]),
        str(value["artifact_sha256"]),
        tuple(value["allowed_capability_refs"]),
        str(value["capability_closure_sha256"]),
        value["intent"],
        ActorResourceSnapshot.from_mapping(value["resource_snapshot"]),
        str(value["proposal_ref"]),
        str(value["dedupe_key"]),
        str(value["atomic_group_ref"]),
    )


def decode_turn_interaction_request(payload: Mapping[str, Any]) -> TurnInteractionEvaluationRequest:
    value = freeze_json(payload, "turn_interaction_request")
    if set(value) != {"envelope", "snapshot", "player_input"}:
        raise ValueError("turn interaction request fields do not match the frozen extension contract")
    if not all(isinstance(value[name], Mapping) for name in ("envelope", "snapshot", "player_input")):
        raise ValueError("turn interaction request values must be objects")
    return TurnInteractionEvaluationRequest(
        OperationEnvelope(**dict(value["envelope"])),
        decode_turn_interaction_snapshot(value["snapshot"]),
        decode_player_turn_input(value["player_input"]),
    )


def decode_resolution_check_request(payload: Mapping[str, Any]) -> ResolutionCheckRequest:
    return decode_resolution_request(payload)


class EmbeddedEventEngine:
    """Concrete embedded event subset; authority and commits remain outside this object."""

    def __init__(self, evaluator: DeterministicEventEvaluator, *, clock: Callable[[], Any] | None = None) -> None:
        self._service = EventEvaluationService(evaluator, clock=clock)
        self._activation_service = EventActivationService(evaluator, clock=clock)

    async def describe(self) -> StoryEngineHandshake:
        base = default_handshake()
        return replace(
            base,
            supported_features=base.supported_features | frozenset({"event-evaluate/1", "bounded-loop/1", "typed-gate-response/1"}),
            required_platform_features=base.required_platform_features | frozenset({"event-visit-counts/1", "event-gate-response/1"}),
            transports=frozenset({"embedded", "remote-dispatch"}),
        )

    async def readiness(self) -> StoryEngineReadiness:
        return StoryEngineReadiness(
            ReadinessStatus.DEGRADED,
            ProviderMode.UNAVAILABLE,
            frozenset({"describe", "readiness", "evaluate_event"}),
            frozenset({"event-evaluate/1", "bounded-loop/1", "typed-gate-response/1"}),
            ("model provider bridge for narrative operations",),
            ("narrative_provider_unavailable",),
        )

    async def evaluate_event(self, request: EventAdvanceRequest, bridge: PlatformBridge):
        return await self._service.evaluate_event(request, bridge)


class EmbeddedEventActivationEngine:
    def __init__(self, event: EmbeddedEventEngine) -> None: self._event = event
    async def activate_event(self, request: EventActivationRequest, bridge: PlatformBridge):
        return await self._event._activation_service.activate_event(request, bridge)


class RemoteEventActivationEngine:
    contract_version = "se-remote-dispatch/1.4.0"
    def __init__(self, embedded: EmbeddedEventActivationEngine) -> None: self._embedded = embedded
    async def dispatch(self, method: str, payload: Mapping[str, Any], bridge: PlatformBridge | None = None) -> Mapping[str, Any]:
        if method != "activate_event" and payload: raise ValueError("this activation remote method does not accept a payload")
        if method == "health": return {"status": "alive", "contract_version": self.contract_version}
        if method != "activate_event": raise ValueError("unsupported activation remote method")
        if bridge is None: raise ValueError("activate_event requires a platform-owned PlatformBridge")
        return _json_value(await self._embedded.activate_event(decode_event_activation_request(payload), bridge))

class RemoteEventEngine:
    """Transport-neutral JSON dispatcher; the platform owns HTTP/RPC/auth and supplies PlatformBridge."""

    contract_version = REMOTE_DISPATCH_VERSION

    def __init__(self, embedded: EmbeddedEventEngine) -> None:
        self._embedded = embedded

    async def dispatch(self, method: str, payload: Mapping[str, Any], bridge: PlatformBridge | None = None) -> Mapping[str, Any]:
        if method != "evaluate_event" and payload:
            raise ValueError("this remote engine method does not accept a payload")
        if method == "health":
            return {"status": "alive", "contract_version": self.contract_version}
        if method == "describe":
            return _json_value(await self._embedded.describe())
        if method == "readiness":
            return _json_value(await self._embedded.readiness())
        if method == "capabilities":
            readiness = await self._embedded.readiness()
            return {"contract_version": self.contract_version, "operations": sorted(readiness.accepted_operations), "features": sorted(readiness.enabled_features)}
        if method == "evaluate_event":
            if bridge is None:
                raise ValueError("evaluate_event requires a platform-owned PlatformBridge")
            request = decode_event_advance_request(payload)
            return _json_value(await self._embedded.evaluate_event(request, bridge))
        raise ValueError("unsupported remote engine method")


class EmbeddedStoryEngine:
    """Combined event and ordinary-turn engine; every platform mutation remains a proposal."""

    def __init__(self, event: EmbeddedEventEngine | None, narrative: NarrativeResolutionService | None, resource_effect: ResourceEffectEvaluationService | None, *, provider_status: str) -> None:
        self._event = event
        self._narrative = narrative
        self._resource_effect = resource_effect
        self._provider_status = provider_status

    @property
    def artifact_configured(self) -> bool:
        return self._event is not None and self._narrative is not None

    async def describe(self) -> Mapping[str, Any]:
        # Handshake discovery is deliberately independent from Pack, Artifact and provider state.
        features = set(_HANDSHAKE_FEATURES)
        if self.artifact_configured:
            features.update({"event-evaluate/1", "narrative-resolve-turn/1", "narrative-stream/1", "single-primary-model-call/1"})
        return freeze_json({
            "schema": "se-engine-handshake/1.1.0",
            "story_engine_product": "321 Story Engine",
            "story_engine_version": STORY_ENGINE_DISTRIBUTION_VERSION,
            "story_engine_port_range": "story-engine-port/1.0.0",
            "platform_bridge_range": PLATFORM_BRIDGE_VERSION,
            "supported_features": sorted(features),
            "required_platform_features": ["operation-envelope/1", "proposal-validation/1"],
            "transports": ["embedded", "remote-dispatch"],
            "deterministic_replay": True,
            "security_policy_fingerprint": default_handshake().security_policy_fingerprint,
        }, "handshake")

    async def readiness(self) -> StoryEngineReadiness | Mapping[str, Any]:
        if self.artifact_configured:
            assert self._narrative is not None
            current = self._narrative.readiness(event_ready=True)
            return replace(current, accepted_operations=current.accepted_operations | frozenset({"capabilities"}))
        missing = ["story_artifact"]
        reasons = ["story_artifact_unavailable"]
        narrative_reason = "story_artifact_unavailable"
        if self._provider_status != "available":
            missing.insert(0, "provider:structured_output")
            reasons.insert(0, "narrative_provider_unavailable")
            narrative_reason = "story_artifact_and_provider_unavailable"
        return freeze_json({
            "schema": "se-engine-readiness/1.1.0",
            "engine_version": STORY_ENGINE_DISTRIBUTION_VERSION,
            "status": "degraded",
            "provider_mode": "platform_bridge" if self._provider_status == "available" else "unavailable",
            "accepted_operations": ["capabilities", "describe", "readiness"],
            "enabled_features": sorted(_HANDSHAKE_FEATURES),
            "missing_dependencies": missing,
            "reason_codes": reasons,
            "components": {
                "engine_runtime": {"status": "ready"},
                "event": {"status": "unavailable", "reason": "story_artifact_unavailable"},
                "narrative": {"status": "degraded", "reason": narrative_reason},
                "stream": {"status": "degraded", "reason": narrative_reason},
                "platform_bridge": {"status": "contract_ready", "version": PLATFORM_BRIDGE_VERSION},
                "provider": {
                    "status": self._provider_status,
                    "reason": "provider_not_configured" if self._provider_status != "available" else "story_artifact_unavailable",
                    "requirements": _PROVIDER_REQUIREMENTS,
                },
                "story_artifact": {"status": "unavailable", "reason": "story_artifact_not_configured"},
            },
            "provider_requirements": _PROVIDER_REQUIREMENTS,
        }, "readiness")

    async def capabilities(self) -> Mapping[str, Any]:
        artifact_ready = self.artifact_configured
        provider_ready = self._provider_status == "available"
        narrative_ready = artifact_ready and provider_ready
        narrative_reason = None if narrative_ready else (
            "story_artifact_and_provider_unavailable" if not artifact_ready and not provider_ready
            else "story_artifact_unavailable" if not artifact_ready else "provider_unavailable"
        )
        operations: dict[str, dict[str, Any]] = {
            "describe": {"available": True, "requires": []},
            "readiness": {"available": True, "requires": []},
            "capabilities": {"available": True, "requires": []},
            "resolve_turn": {"available": narrative_ready, "requires": ["platform_bridge", "provider:structured_output", "story_artifact"]},
            "resolve_turn_stream": {"available": narrative_ready, "requires": ["platform_bridge", "provider:structured_output", "story_artifact"]},
            "evaluate_event": {"available": artifact_ready, "requires": ["platform_bridge", "story_artifact"]},
        }
        if narrative_reason is not None:
            operations["resolve_turn"]["reason"] = narrative_reason
            operations["resolve_turn_stream"]["reason"] = narrative_reason
        if not artifact_ready:
            operations["evaluate_event"]["reason"] = "story_artifact_unavailable"
        return freeze_json({
            "schema": "se-engine-capabilities/1.0.0",
            "engine_version": STORY_ENGINE_DISTRIBUTION_VERSION,
            "operations": operations,
            "engine_capabilities": sorted(_ENGINE_CAPABILITIES),
            "provider_requirements": _PROVIDER_REQUIREMENTS,
            "unknown_required_policy": "fail_closed",
            "unknown_optional_policy": "ignore_with_warning",
        }, "capabilities")

    def _require_artifact(self, operation: str) -> None:
        # Dependency order is security relevant: never decode attacker-controlled payloads or touch Bridge first.
        if not self.artifact_configured:
            raise _artifact_unavailable(operation)

    async def resolve_turn(self, request: EngineTurnRequest, bridge: PlatformBridge):
        self._require_artifact("resolve_turn")
        assert self._narrative is not None
        return await self._narrative.resolve_turn(request, bridge)

    def resolve_turn_stream(self, request: EngineTurnRequest, bridge: PlatformBridge):
        if not self.artifact_configured:
            async def unavailable():
                raise _artifact_unavailable("resolve_turn_stream")
                yield  # pragma: no cover - marks the closure as an async iterator
            return unavailable()
        assert self._narrative is not None
        return self._narrative.resolve_turn_stream(request, bridge)

    async def evaluate_event(self, request: EventAdvanceRequest, bridge: PlatformBridge):
        self._require_artifact("evaluate_event")
        assert self._event is not None
        return await self._event.evaluate_event(request, bridge)

    async def _evaluate_resource_effect(self, request: ResourceEffectEvaluationRequest, bridge: PlatformBridge):
        self._require_artifact("evaluate_resource_effect")
        if self._resource_effect is None:
            raise EngineContractError(
                "engine.resource_effect_contract_unavailable", "evaluate_resource_effect",
                "The configured Artifact does not freeze actor.resource_pool/1.0.0.",
                "Use a pack Artifact that freezes the resource/effect contracts.", retryable=False,
            )
        return await self._resource_effect.evaluate(request, bridge)


class RemoteStoryEngine:
    """Transport-neutral combined dispatcher; transport/auth/callback lifecycle stay platform-owned."""

    contract_version = NARRATIVE_REMOTE_DISPATCH_VERSION

    def __init__(self, embedded: EmbeddedStoryEngine) -> None:
        self._embedded = embedded

    async def dispatch(self, method: str, payload: Mapping[str, Any], bridge: PlatformBridge | None = None) -> Mapping[str, Any]:
        if method not in {"resolve_turn", "evaluate_event"} and payload:
            raise ValueError("this remote engine method does not accept a payload")
        if method == "health":
            return {"status": "alive", "contract_version": self.contract_version, "engine_version": STORY_ENGINE_DISTRIBUTION_VERSION}
        if method == "describe":
            return _json_value(await self._embedded.describe())
        if method == "readiness":
            return _json_value(await self._embedded.readiness())
        if method == "capabilities":
            return _json_value(await self._embedded.capabilities())
        if method in {"resolve_turn", "evaluate_event"}:
            self._embedded._require_artifact(method)
        if bridge is None:
            raise ValueError(f"{method} requires a platform-owned PlatformBridge")
        if method == "resolve_turn":
            return _json_value(await self._embedded.resolve_turn(decode_turn_request(payload), bridge))
        if method == "evaluate_event":
            return _json_value(await self._embedded.evaluate_event(decode_event_advance_request(payload), bridge))
        if method == "resolve_turn_stream":
            raise ValueError("resolve_turn_stream must use dispatch_stream")
        raise ValueError("unsupported remote engine method")

    async def dispatch_stream(self, method: str, payload: Mapping[str, Any], bridge: PlatformBridge | None = None):
        if method != "resolve_turn_stream":
            raise ValueError("unsupported remote stream method")
        self._embedded._require_artifact(method)
        if bridge is None:
            raise ValueError("resolve_turn_stream requires a platform-owned PlatformBridge")
        async for event in self._embedded.resolve_turn_stream(decode_turn_request(payload), bridge):
            yield _json_value(event)


class EmbeddedPostResolutionEngine:
    """Proposal-only runtime for narrative generation after a committed check."""

    def __init__(self, service: PostResolutionGenerationService) -> None:
        self._service = service

    async def generate_post_resolution(
        self,
        snapshot: PostResolutionGenerationSnapshot | Mapping[str, Any],
        bridge: PlatformBridge,
        **bindings: Any,
    ) -> PostResolutionGenerationResult:
        return await self._service.generate_post_resolution(snapshot, bridge, **bindings)


class RemotePostResolutionEngine:
    """JSON dispatch facade; transport, authentication and delivery remain platform-owned."""

    contract_version = POST_RESOLUTION_REMOTE_DISPATCH_VERSION

    def __init__(self, embedded: EmbeddedPostResolutionEngine) -> None:
        self._embedded = embedded

    async def dispatch(self, method: str, payload: Mapping[str, Any], bridge: PlatformBridge | None = None) -> Mapping[str, Any]:
        if method == "health":
            if payload:
                raise ValueError("health does not accept a payload")
            return {"status": "alive", "contract_version": self.contract_version, "snapshot_contract": POST_RESOLUTION_SNAPSHOT_CONTRACT}
        if method != "generate_post_resolution":
            raise ValueError("unsupported post-resolution remote method")
        if bridge is None:
            raise ValueError("generate_post_resolution requires a platform-owned PlatformBridge")
        if set(payload) != {"snapshot", "bindings"} or not isinstance(payload["snapshot"], Mapping) or not isinstance(payload["bindings"], Mapping):
            raise ValueError("generate_post_resolution requires strict snapshot/bindings envelope")
        bindings = payload["bindings"]
        expected_fields = {
            "expected_receipt_sha256", "expected_committed_revision", "expected_audience_ref",
            "expected_resolution_rule_ref", "expected_modifier_receipt_refs",
        }
        if set(bindings) != expected_fields:
            raise ValueError("generate_post_resolution bindings fields are not exact")
        snapshot = PostResolutionGenerationSnapshot.from_mapping(payload["snapshot"])
        return (await self._embedded.generate_post_resolution(snapshot, bridge, **dict(bindings))).to_mapping()


class EmbeddedStoryEvolutionEngine:
    """Proposal-only StoryEvolution facade over the Artifact-pinned Definition and IR."""

    def __init__(self, service: StoryEvolutionGenerationService, ir: Mapping[str, Any]) -> None:
        self._service = service
        self._ir = freeze_json(ir, "story_evolution_ir")

    async def generate_story_evolution(
        self, context: Mapping[str, Any], bridge: PlatformBridge, *, deadline_at: str,
    ) -> Mapping[str, Any]:
        return await self._service.generate_story_evolution(
            context, self._ir, bridge, deadline_at=deadline_at,
        )


class RemoteStoryEvolutionEngine:
    """Strict JSON facade; transport, model execution, commit and recovery stay platform-owned."""

    contract_version = STORY_EVOLUTION_REMOTE_DISPATCH_VERSION

    def __init__(self, embedded: EmbeddedStoryEvolutionEngine) -> None:
        self._embedded = embedded

    async def dispatch(
        self, method: str, payload: Mapping[str, Any], bridge: PlatformBridge | None = None,
    ) -> Mapping[str, Any]:
        if method == "health":
            if payload:
                raise ValueError("health does not accept a payload")
            return {
                "status": "alive", "contract_version": self.contract_version,
                "context_contract": STORY_EVOLUTION_CONTEXT_SCHEMA,
                "proposal_contract": STORY_EVOLUTION_PROPOSAL_BATCH_SCHEMA,
            }
        if method != "generate_story_evolution":
            raise ValueError("unsupported StoryEvolution remote method")
        if bridge is None:
            raise ValueError("generate_story_evolution requires a platform-owned PlatformBridge")
        if set(payload) != {"context", "deadline_at"} or not isinstance(payload["context"], Mapping) or not isinstance(payload["deadline_at"], str):
            raise ValueError("generate_story_evolution requires a strict context/deadline envelope")
        return await self._embedded.generate_story_evolution(
            payload["context"], bridge, deadline_at=payload["deadline_at"],
        )

class EmbeddedResourceStoryEngine:
    """New minor entrypoint for the resource evaluator; legacy narrative ABI stays exact."""

    def __init__(self, embedded: EmbeddedStoryEngine) -> None:
        self._embedded = embedded

    async def describe(self) -> Mapping[str, Any]:
        value = _json_value(await self._embedded.describe())
        value["supported_features"] = sorted(set(value["supported_features"]) | {"actor.resource_pool.evaluate_effect/1.0.0"})
        return freeze_json(value, "resource_handshake")

    async def readiness(self) -> Mapping[str, Any]:
        available = self._embedded._resource_effect is not None
        return freeze_json({
            "schema": "se-resource-engine-readiness/1.0.0", "engine_version": STORY_ENGINE_DISTRIBUTION_VERSION,
            "status": "ready" if available else "degraded",
            "accepted_operations": ["capabilities", "describe", "evaluate_resource_effect", "readiness"] if available else ["capabilities", "describe", "readiness"],
            "missing_dependencies": [] if available else ["story_artifact:actor.resource_pool/1.0.0"],
        }, "resource_readiness")

    async def capabilities(self) -> Mapping[str, Any]:
        available = self._embedded._resource_effect is not None
        operation = {
            "available": available,
            "request_contract": RESOURCE_EFFECT_EVALUATION_CONTRACT,
            "requires": ["platform_bridge", "story_artifact", "actor.resource_pool/1.0.0", "character.state.effects/1"],
        }
        if not available:
            operation["reason"] = "resource_effect_contract_unavailable"
        return freeze_json({
            "schema": "se-resource-engine-capabilities/1.0.0", "engine_version": STORY_ENGINE_DISTRIBUTION_VERSION,
            "remote_dispatch_contract": RESOURCE_REMOTE_DISPATCH_VERSION,
            "operations": {"evaluate_resource_effect": operation},
            "engine_capabilities": ["actor.resource_pool.evaluate_effect/1.0.0"],
            "unknown_required_policy": "fail_closed",
        }, "resource_capabilities")

    async def evaluate_resource_effect(self, request: ResourceEffectEvaluationRequest, bridge: PlatformBridge):
        return await self._embedded._evaluate_resource_effect(request, bridge)


class RemoteResourceStoryEngine:
    contract_version = RESOURCE_REMOTE_DISPATCH_VERSION

    def __init__(self, embedded: EmbeddedResourceStoryEngine) -> None:
        self._embedded = embedded

    async def dispatch(self, method: str, payload: Mapping[str, Any], bridge: PlatformBridge | None = None) -> Mapping[str, Any]:
        if method != "evaluate_resource_effect" and payload:
            raise ValueError("this resource remote method does not accept a payload")
        if method == "health":
            return {"status": "alive", "contract_version": self.contract_version, "engine_version": STORY_ENGINE_DISTRIBUTION_VERSION}
        if method == "describe":
            return _json_value(await self._embedded.describe())
        if method == "readiness":
            return _json_value(await self._embedded.readiness())
        if method == "capabilities":
            return _json_value(await self._embedded.capabilities())
        if method == "evaluate_resource_effect":
            if bridge is None:
                raise ValueError("evaluate_resource_effect requires a platform-owned PlatformBridge")
            return _json_value(await self._embedded.evaluate_resource_effect(decode_resource_effect_request(payload), bridge))
        raise ValueError("unsupported resource remote method")


class EmbeddedTurnInteractionEngine:
    """Proposal-only interaction extension built from one immutable Artifact."""

    def __init__(self, artifact: Artifact, *, clock: Callable[[], Any] | None = None) -> None:
        self._artifact_sha256 = artifact.artifact_sha256
        self._service = TurnInteractionService(TurnInteractionEvaluator(artifact.to_mapping()), clock=clock)

    async def describe(self) -> Mapping[str, Any]:
        from .turn_interaction import PLAYER_TURN_REFERENCED_INPUT_SCHEMA,TURN_INTERACTION_REFERENCE_FEATURE
        return freeze_json({
            "schema": "se-turn-interaction-engine-handshake/1.1.0", "engine_version": STORY_ENGINE_DISTRIBUTION_VERSION,
            "capability": TURN_INTERACTION_CAPABILITY, "snapshot_contract": TURN_INTERACTION_SNAPSHOT_SCHEMA,
            "input_contract": PLAYER_TURN_INPUT_SCHEMA, "result_contract": TURN_INTERACTION_RESULT_SCHEMA,
            "artifact_sha256": self._artifact_sha256, "authority_owner": "321_platform",
            'supported_input_contracts':[PLAYER_TURN_INPUT_SCHEMA,PLAYER_TURN_REFERENCED_INPUT_SCHEMA],
            'features':[TURN_INTERACTION_REFERENCE_FEATURE],
        }, "turn_interaction_handshake")

    async def readiness(self) -> Mapping[str, Any]:
        return freeze_json({
            "schema": "se-turn-interaction-readiness/1.0.0", "status": "ready", "proposal_only": True,
            "accepted_operations": ["capabilities", "describe", "evaluate_turn_interaction", "readiness"], "missing_dependencies": [],
        }, "turn_interaction_readiness")

    async def capabilities(self) -> Mapping[str, Any]:
        from .turn_interaction import PLAYER_TURN_REFERENCED_INPUT_SCHEMA,TURN_INTERACTION_REFERENCE_FEATURE
        return freeze_json({
            "schema": "se-turn-interaction-capabilities/1.1.0", "capability": TURN_INTERACTION_CAPABILITY,
            "modes": ["choice_only", "dialogue_only", "hybrid"],
            "hybrid_submission_policies": ["one_of", "choice_with_optional_dialogue"],
            "writes": False, "platform_commit_required": True,
            'supported_input_contracts':[PLAYER_TURN_INPUT_SCHEMA,PLAYER_TURN_REFERENCED_INPUT_SCHEMA],
            'features':[TURN_INTERACTION_REFERENCE_FEATURE],
        }, "turn_interaction_capabilities")

    async def evaluate_turn_interaction(self, request: TurnInteractionEvaluationRequest, bridge: PlatformBridge) -> TurnInteractionEvaluationResult:
        return await self._service.evaluate_turn_interaction(request, bridge)


class RemoteTurnInteractionEngine:
    contract_version = TURN_INTERACTION_REMOTE_DISPATCH_VERSION

    def __init__(self, embedded: EmbeddedTurnInteractionEngine) -> None:
        self._embedded = embedded

    async def dispatch(self, method: str, payload: Mapping[str, Any], bridge: PlatformBridge | None = None) -> Mapping[str, Any]:
        if method != "evaluate_turn_interaction" and payload:
            raise ValueError("this turn interaction method does not accept payload")
        if method == "health":
            return {"status": "alive", "contract_version": self.contract_version, "engine_version": STORY_ENGINE_DISTRIBUTION_VERSION}
        if method == "describe":
            return _json_value(await self._embedded.describe())
        if method == "readiness":
            return _json_value(await self._embedded.readiness())
        if method == "capabilities":
            return _json_value(await self._embedded.capabilities())
        if method == "evaluate_turn_interaction":
            if bridge is None:
                raise ValueError("evaluate_turn_interaction requires a platform-owned PlatformBridge")
            request = decode_turn_interaction_request(payload)
            return _json_value(await self._embedded.evaluate_turn_interaction(request, bridge))
        raise ValueError("unsupported turn interaction method")


class EmbeddedResolutionCheckEngine:
    """Proposal-only system-neutral check evaluator built from one immutable Artifact."""

    def __init__(self, artifact: Artifact, *, clock: Callable[[], Any] | None = None) -> None:
        self._artifact_sha256 = artifact.artifact_sha256
        self._service = ResolutionCheckService(ResolutionCheckEvaluator(artifact.to_mapping()), clock=clock)

    async def describe(self) -> Mapping[str, Any]:
        return freeze_json({
            "schema": "se-resolution-check-engine-handshake/1.0.0", "engine_version": STORY_ENGINE_DISTRIBUTION_VERSION,
            "capability": RESOLUTION_CHECK_CAPABILITY, "snapshot_contract": RESOLUTION_CHECK_SNAPSHOT_SCHEMA,
            "request_contract": RESOLUTION_CHECK_REQUEST_SCHEMA, "result_contract": RESOLUTION_CHECK_RESULT_SCHEMA,
            "artifact_sha256": self._artifact_sha256, "authority_owner": "321_platform",
        }, "resolution_check_handshake")

    async def readiness(self) -> Mapping[str, Any]:
        return freeze_json({
            "schema": "se-resolution-check-readiness/1.0.0", "status": "ready", "proposal_only": True,
            "accepted_operations": ["capabilities", "describe", "evaluate_resolution_check", "readiness"], "missing_dependencies": [],
        }, "resolution_check_readiness")

    async def capabilities(self) -> Mapping[str, Any]:
        return freeze_json({
            "schema": "se-resolution-check-capabilities/1.0.0", "capability": RESOLUTION_CHECK_CAPABILITY,
            "actions": ["preview", "prepare_roll", "interpret_receipt"], "seed_owner": "321_platform",
            "roll_owner": "321_platform", "receipt_owner": "321_platform", "writes": False,
        }, "resolution_check_capabilities")

    async def evaluate_resolution_check(self, request: ResolutionCheckRequest, bridge: PlatformBridge) -> ResolutionCheckResult:
        return await self._service.evaluate_resolution_check(request, bridge)


class RemoteResolutionCheckEngine:
    contract_version = RESOLUTION_CHECK_REMOTE_DISPATCH_VERSION

    def __init__(self, embedded: EmbeddedResolutionCheckEngine) -> None:
        self._embedded = embedded

    async def dispatch(self, method: str, payload: Mapping[str, Any], bridge: PlatformBridge | None = None) -> Mapping[str, Any]:
        if method != "evaluate_resolution_check" and payload:
            raise ValueError("this resolution check method does not accept payload")
        if method == "health": return {"status": "alive", "contract_version": self.contract_version, "engine_version": STORY_ENGINE_DISTRIBUTION_VERSION}
        if method == "describe": return _json_value(await self._embedded.describe())
        if method == "readiness": return _json_value(await self._embedded.readiness())
        if method == "capabilities": return _json_value(await self._embedded.capabilities())
        if method == "evaluate_resolution_check":
            if bridge is None: raise ValueError("evaluate_resolution_check requires a platform-owned PlatformBridge")
            return _json_value(await self._embedded.evaluate_resolution_check(decode_resolution_check_request(payload), bridge))
        raise ValueError("unsupported resolution check method")

class EmbeddedCharacterBuildEngine:
    def __init__(self,artifact:Artifact,clock=None):
        value=artifact.to_mapping();self._artifact_sha256=artifact.artifact_sha256;self._service=CharacterBuildService(CharacterBuildEvaluator(value),clock)
        catalog=value.get("character_build_definitions");self._v11=CharacterBuildV11Evaluator(catalog) if isinstance(catalog,Mapping) and catalog.get("schema") in ("se-character-build-catalog-ir/1.1.0","se-character-build-catalog-ir/1.2.0") else None
    async def describe(self):return freeze_json({"schema":"se-character-build-engine-handshake/1.1.0" if self._v11 else "se-character-build-engine-handshake/1.0.0","engine_version":STORY_ENGINE_DISTRIBUTION_VERSION,"capability":CHARACTER_BUILD_CAPABILITY,"snapshot_contract":CHARACTER_BUILD_V11_SNAPSHOT_SCHEMA if self._v11 else CHARACTER_BUILD_SNAPSHOT_SCHEMA,"request_contract":CHARACTER_BUILD_V11_REQUEST_SCHEMA if self._v11 else CHARACTER_BUILD_REQUEST_SCHEMA,"result_contract":CHARACTER_BUILD_V11_RESULT_SCHEMA if self._v11 else CHARACTER_BUILD_RESULT_SCHEMA,"artifact_sha256":self._artifact_sha256,"authority_owner":"321_platform"},"build_handshake")
    async def readiness(self):return freeze_json({"schema":"se-character-build-readiness/1.0.0","status":"ready","proposal_only":True,"accepted_operations":["describe","readiness","capabilities","evaluate_character_build"]},"build_readiness")
    async def capabilities(self):return freeze_json({"schema":"se-character-build-capabilities/1.1.0" if self._v11 else "se-character-build-capabilities/1.0.0","capability":CHARACTER_BUILD_CAPABILITY,"modes":["sequential_messages","step_choices"] if self._v11 else ["preset","step_choices","point_buy","platform_random","hybrid"],"actions":["preview","submit_text","choose","skip","back","reset","pause","resume","confirm_candidate"] if self._v11 else [],"writes":False,"actor_create_owner":"321_platform"},"build_capabilities")
    async def evaluate_character_build(self,request,bridge):
        if isinstance(request,Mapping) and request.get("schema")==CHARACTER_BUILD_V11_REQUEST_SCHEMA:
            if self._v11 is None:raise ValueError("Artifact does not provide character build 1.1")
            return self._v11.evaluate(request)
        return await self._service.evaluate_character_build(request,bridge)
class RemoteCharacterBuildEngine:
    contract_version=CHARACTER_BUILD_REMOTE_DISPATCH_VERSION
    def __init__(self,embedded):self._embedded=embedded
    async def dispatch(self,method,payload,bridge=None):
        if method!="evaluate_character_build" and payload:raise ValueError("method does not accept payload")
        if method=="health":return {"status":"alive","contract_version":self.contract_version,"engine_version":STORY_ENGINE_DISTRIBUTION_VERSION}
        if method in {"describe","readiness","capabilities"}:return _json_value(await getattr(self._embedded,method)())
        if method=="evaluate_character_build":
            if bridge is None:raise ValueError("platform bridge required")
            request=payload if payload.get("schema")==CHARACTER_BUILD_V11_REQUEST_SCHEMA else decode_character_build_request(payload)
            return _json_value(await self._embedded.evaluate_character_build(request,bridge))
        raise ValueError("unsupported character build method")
class EmbeddedCharacterProgressionEngine:
    def __init__(self,artifact:Artifact,clock=None):self._artifact_sha256=artifact.artifact_sha256;self._service=CharacterProgressionService(CharacterProgressionEvaluator(artifact.to_mapping()),clock)
    async def describe(self):return freeze_json({"schema":"se-character-progression-engine-handshake/1.0.0","engine_version":STORY_ENGINE_DISTRIBUTION_VERSION,"capability":CHARACTER_PROGRESSION_CAPABILITY,"snapshot_contract":CHARACTER_PROGRESSION_SNAPSHOT_SCHEMA,"request_contract":CHARACTER_PROGRESSION_REQUEST_SCHEMA,"result_contract":CHARACTER_PROGRESSION_RESULT_SCHEMA,"artifact_sha256":self._artifact_sha256,"authority_owner":"321_platform"},"progression_handshake")
    async def readiness(self):return freeze_json({"schema":"se-character-progression-readiness/1.0.0","status":"ready","proposal_only":True,"accepted_operations":["describe","readiness","capabilities","evaluate_character_progression"]},"progression_readiness")
    async def capabilities(self):return freeze_json({"schema":"se-character-progression-capabilities/1.0.0","capability":CHARACTER_PROGRESSION_CAPABILITY,"models":["none","xp","level","milestone","rank","mixed"],"writes":False,"commit_owner":"321_platform"},"progression_capabilities")
    async def evaluate_character_progression(self,request,bridge):return await self._service.evaluate_character_progression(request,bridge)
class RemoteCharacterProgressionEngine:
    contract_version=CHARACTER_PROGRESSION_REMOTE_DISPATCH_VERSION
    def __init__(self,embedded):self._embedded=embedded
    async def dispatch(self,method,payload,bridge=None):
        if method!="evaluate_character_progression" and payload:raise ValueError("method does not accept payload")
        if method=="health":return {"status":"alive","contract_version":self.contract_version,"engine_version":STORY_ENGINE_DISTRIBUTION_VERSION}
        if method in {"describe","readiness","capabilities"}:return _json_value(await getattr(self._embedded,method)())
        if method=="evaluate_character_progression":
            if bridge is None:raise ValueError("platform bridge required")
            return _json_value(await self._embedded.evaluate_character_progression(decode_progression_request(payload),bridge))
        raise ValueError("unsupported progression method")
class EmbeddedRewardSettlementEngine:
    def __init__(self,artifact:Artifact,clock=None):self._artifact_sha256=artifact.artifact_sha256;self._service=RewardSettlementService(RewardSettlementEvaluator(artifact.to_mapping()),clock)
    async def describe(self):return freeze_json({"schema":"se-reward-settlement-engine-handshake/1.0.0","engine_version":STORY_ENGINE_DISTRIBUTION_VERSION,"capability":REWARD_SETTLEMENT_CAPABILITY,"snapshot_contract":REWARD_SETTLEMENT_SNAPSHOT_SCHEMA,"request_contract":REWARD_SETTLEMENT_REQUEST_SCHEMA,"result_contract":REWARD_SETTLEMENT_RESULT_SCHEMA,"artifact_sha256":self._artifact_sha256,"authority_owner":"321_platform"},"reward_handshake")
    async def readiness(self):return freeze_json({"schema":"se-reward-settlement-readiness/1.0.0","status":"ready","proposal_only":True,"accepted_operations":["describe","readiness","capabilities","evaluate_reward_settlement"]},"reward_readiness")
    async def capabilities(self):return freeze_json({"schema":"se-reward-settlement-capabilities/1.0.0","capability":REWARD_SETTLEMENT_CAPABILITY,"actions":["preview","allocate","choose","claim","decline","defer","expire"],"writes":False,"commit_owner":"321_platform"},"reward_capabilities")
    async def evaluate_reward_settlement(self,request,bridge):return await self._service.evaluate_reward_settlement(request,bridge)
class RemoteRewardSettlementEngine:
    contract_version=REWARD_SETTLEMENT_REMOTE_DISPATCH_VERSION
    def __init__(self,embedded):self._embedded=embedded
    async def dispatch(self,method,payload,bridge=None):
        if method!="evaluate_reward_settlement" and payload:raise ValueError("method does not accept payload")
        if method=="health":return {"status":"alive","contract_version":self.contract_version,"engine_version":STORY_ENGINE_DISTRIBUTION_VERSION}
        if method in {"describe","readiness","capabilities"}:return _json_value(await getattr(self._embedded,method)())
        if method=="evaluate_reward_settlement":
            if bridge is None:raise ValueError("platform bridge required")
            return _json_value(await self._embedded.evaluate_reward_settlement(decode_reward_request(payload),bridge))
        raise ValueError("unsupported reward settlement method")
class EmbeddedInventoryEquipmentEngine:
    def __init__(self,artifact:Artifact,clock=None):self._artifact_sha256=artifact.artifact_sha256;self._service=InventoryEquipmentService(InventoryEquipmentEvaluator(artifact.to_mapping()),clock)
    async def describe(self):return freeze_json({"schema":"se-inventory-equipment-engine-handshake/1.0.0","engine_version":STORY_ENGINE_DISTRIBUTION_VERSION,"capability":INVENTORY_EQUIPMENT_CAPABILITY,"snapshot_contract":INVENTORY_SNAPSHOT_SCHEMA,"request_contract":INVENTORY_REQUEST_SCHEMA,"result_contract":INVENTORY_RESULT_SCHEMA,"artifact_sha256":self._artifact_sha256,"authority_owner":"321_platform"},"inventory_handshake")
    async def readiness(self):return freeze_json({"schema":"se-inventory-equipment-readiness/1.0.0","status":"ready","proposal_only":True},"inventory_readiness")
    async def capabilities(self):return freeze_json({"schema":"se-inventory-equipment-capabilities/1.0.0","capability":INVENTORY_EQUIPMENT_CAPABILITY,"writes":False,"instance_owner":"321_platform"},"inventory_capabilities")
    async def evaluate_inventory_equipment(self,request,bridge):return await self._service.evaluate_inventory_equipment(request,bridge)
class RemoteInventoryEquipmentEngine:
    contract_version=INVENTORY_EQUIPMENT_REMOTE_DISPATCH_VERSION
    def __init__(self,embedded):self._embedded=embedded
    async def dispatch(self,method,payload,bridge=None):
        if method=="evaluate_inventory_equipment":return _json_value(await self._embedded.evaluate_inventory_equipment(decode_inventory_request(payload),bridge))
        if method in {"describe","readiness","capabilities"}:return _json_value(await getattr(self._embedded,method)())
        if method=="health":return {"status":"alive","contract_version":self.contract_version}
        raise ValueError("unsupported inventory method")
class EmbeddedAbilityExecutionEngine:
    def __init__(self,artifact:Artifact,clock=None):self._artifact_sha256=artifact.artifact_sha256;self._service=AbilityExecutionService(AbilityExecutionEvaluator(artifact.to_mapping()),clock)
    async def describe(self):return freeze_json({"schema":"se-ability-execution-engine-handshake/1.0.0","engine_version":STORY_ENGINE_DISTRIBUTION_VERSION,"capability":ABILITY_EXECUTION_CAPABILITY,"snapshot_contract":ABILITY_SNAPSHOT_SCHEMA,"request_contract":ABILITY_REQUEST_SCHEMA,"result_contract":ABILITY_RESULT_SCHEMA,"artifact_sha256":self._artifact_sha256,"authority_owner":"321_platform"},"ability_handshake")
    async def readiness(self):return freeze_json({"schema":"se-ability-execution-readiness/1.0.0","status":"ready","proposal_only":True},"ability_readiness")
    async def capabilities(self):return freeze_json({"schema":"se-ability-execution-capabilities/1.0.0","capability":ABILITY_EXECUTION_CAPABILITY,"actions":["preview","select_target","activate","cast","use","cancel","interrupt","resolve"],"writes":False,"random_owner":"321_platform","commit_owner":"321_platform"},"ability_capabilities")
    async def evaluate_ability_execution(self,request,bridge):return await self._service.evaluate_ability_execution(request,bridge)
class RemoteAbilityExecutionEngine:
    contract_version=ABILITY_EXECUTION_REMOTE_DISPATCH_VERSION
    def __init__(self,embedded):self._embedded=embedded
    async def dispatch(self,method,payload,bridge=None):
        if method=="evaluate_ability_execution":return _json_value(await self._embedded.evaluate_ability_execution(decode_ability_request(payload),bridge))
        if method in {"describe","readiness","capabilities"}:return _json_value(await getattr(self._embedded,method)())
        if method=="health":return {"status":"alive","contract_version":self.contract_version}
        raise ValueError("unsupported ability method")
class EmbeddedConflictProcedureEngine:
    def __init__(self,artifact:Artifact,clock=None):self._artifact_sha256=artifact.artifact_sha256;self._service=ConflictProcedureService(ConflictProcedureEvaluator(artifact.to_mapping()),clock)
    async def describe(self):return freeze_json({"schema":"se-conflict-procedure-engine-handshake/1.0.0","engine_version":STORY_ENGINE_DISTRIBUTION_VERSION,"capability":CONFLICT_PROCEDURE_CAPABILITY,"snapshot_contract":CONFLICT_SNAPSHOT_SCHEMA,"request_contract":CONFLICT_REQUEST_SCHEMA,"result_contract":CONFLICT_RESULT_SCHEMA,"artifact_sha256":self._artifact_sha256,"authority_owner":"321_platform"},"conflict_handshake")
    async def readiness(self):return freeze_json({"schema":"se-conflict-procedure-readiness/1.0.0","status":"ready","proposal_only":True},"conflict_readiness")
    async def capabilities(self):return freeze_json({"schema":"se-conflict-procedure-capabilities/1.0.0","capability":CONFLICT_PROCEDURE_CAPABILITY,"actions":["preview","enter","act","assist","react","negotiate","retreat","surrender","resolve","aftermath","cancel"],"writes":False,"priority_owner":"321_platform","commit_owner":"321_platform","terminal_owner":"fate_rescue_owner"},"conflict_capabilities")
    async def evaluate_conflict_procedure(self,request,bridge):return validate_conflict_result_for_request(await self._service.evaluate_conflict_procedure(request,bridge),request)
class RemoteConflictProcedureEngine:
    contract_version=CONFLICT_PROCEDURE_REMOTE_DISPATCH_VERSION
    def __init__(self,embedded):self._embedded=embedded
    async def dispatch(self,method,payload,bridge=None):
        if method=="evaluate_conflict_procedure":return _json_value(await self._embedded.evaluate_conflict_procedure(decode_conflict_request(payload),bridge))
        if method in {"describe","readiness","capabilities"}:return _json_value(await getattr(self._embedded,method)())
        if method=="health":return {"status":"alive","contract_version":self.contract_version}
        raise ValueError("unsupported conflict procedure method")


class EmbeddedRecoveryCycleEngine:
    """Artifact-bound, proposal-only recovery endpoint."""

    def __init__(self, artifact: Artifact, artifact_ref: str, clock: Callable[[], Any] | None = None) -> None:
        self._artifact_sha256 = artifact.artifact_sha256
        self._artifact_ref = artifact_ref
        fixed_clock = clock or (lambda: datetime.now(UTC))
        self._service = RecoveryCycleService(RecoveryCycleEvaluator(artifact.to_mapping(), artifact_ref), fixed_clock)

    async def describe(self):
        return freeze_json({
            "schema": "se-recovery-cycle-engine-handshake/1.1.0",
            "engine_version": STORY_ENGINE_DISTRIBUTION_VERSION,
            "capability": RECOVERY_CYCLE_CAPABILITY,
            "snapshot_contract": RECOVERY_SNAPSHOT_SCHEMA,
            "request_contract": RECOVERY_REQUEST_SCHEMA,
            "result_contract": RECOVERY_RESULT_SCHEMA,
            "artifact_sha256": self._artifact_sha256,
            "artifact_ref": self._artifact_ref,
            "engine_role": "proposal_only",
            "authority_owner": "321_platform",
            "real_sp_active_consumer": False,
        }, "recovery_handshake")

    async def readiness(self):
        return freeze_json({
            "schema": "se-recovery-cycle-readiness/1.1.0", "status": "ready",
            "proposal_only": True,
            "accepted_operations": ["describe", "readiness", "capabilities", "evaluate_recovery_cycle"],
            "commit_owner": "321_platform",
        }, "recovery_readiness")

    async def capabilities(self):
        return freeze_json({
            "schema": "se-recovery-cycle-capabilities/1.1.0", "capability": RECOVERY_CYCLE_CAPABILITY,
            "actions": [item.value for item in RecoveryAction], "writes": False, "commits_state": False,
            "unknown_policy": "reconcile_only",
            "hp0_policy": "platform_rescue_or_fate_receipt_and_consent_required",
        }, "recovery_capabilities")

    async def evaluate_recovery_cycle(self, request, bridge):
        return await self._service.evaluate_recovery_cycle(request, bridge)


class RemoteRecoveryCycleEngine:
    contract_version = RECOVERY_CYCLE_REMOTE_DISPATCH_VERSION

    def __init__(self, embedded: EmbeddedRecoveryCycleEngine) -> None:
        self._embedded = embedded

    async def dispatch(self, method: str, payload: Mapping[str, Any], bridge: PlatformBridge | None = None) -> Mapping[str, Any]:
        if method != "evaluate_recovery_cycle" and payload:
            raise ValueError("this recovery cycle method does not accept payload")
        if method == "health":
            return {"status": "alive", "contract_version": self.contract_version, "engine_version": STORY_ENGINE_DISTRIBUTION_VERSION}
        if method in {"describe", "readiness", "capabilities"}:
            return _json_value(await getattr(self._embedded, method)())
        if method == "evaluate_recovery_cycle":
            if bridge is None:
                raise ValueError("evaluate_recovery_cycle requires a platform-owned PlatformBridge")
            return _json_value(await self._embedded.evaluate_recovery_cycle(decode_recovery_request(payload), bridge))
        raise ValueError("unsupported recovery cycle method")


class EmbeddedRecoveryCycleV2Engine:
    """Artifact-bound Recovery 2.0 endpoint; active-consumer is manifest data, not acceptance."""

    def __init__(self, artifact: Artifact, artifact_ref: str, clock: Callable[[], Any] | None = None) -> None:
        value = artifact.to_mapping()
        self._artifact_sha256 = artifact.artifact_sha256
        self._artifact_ref = artifact_ref
        self._real_sp_active_consumer = value["recovery_cycle_definitions"]["trusted_manifest"]["real_sp_active_consumer"]
        fixed_clock = clock or (lambda: datetime.now(UTC))
        self._service = RecoveryCycleV2Service(RecoveryCycleV2Evaluator(value, artifact_ref), fixed_clock)

    async def describe(self):
        return freeze_json({
            "schema": "se-recovery-cycle-engine-handshake/2.0.0",
            "engine_version": STORY_ENGINE_DISTRIBUTION_VERSION,
            "capability": RECOVERY_CYCLE_V2_CAPABILITY,
            "snapshot_contract": RECOVERY_V2_SNAPSHOT_SCHEMA,
            "request_contract": RECOVERY_V2_REQUEST_SCHEMA,
            "result_contract": RECOVERY_V2_RESULT_SCHEMA,
            "artifact_sha256": self._artifact_sha256,
            "artifact_ref": self._artifact_ref,
            "engine_role": "proposal_only",
            "authority_owner": "321_platform",
            "real_sp_active_consumer": self._real_sp_active_consumer,
        }, "recovery_v2_handshake")

    async def readiness(self):
        return freeze_json({"schema": "se-recovery-cycle-readiness/2.0.0", "status": "ready", "proposal_only": True, "accepted_operations": ["describe", "readiness", "capabilities", "evaluate_recovery_cycle"], "commit_owner": "321_platform"}, "recovery_v2_readiness")

    async def capabilities(self):
        return freeze_json({"schema": "se-recovery-cycle-capabilities/2.0.0", "capability": RECOVERY_CYCLE_V2_CAPABILITY, "actions": [item.value for item in RecoveryV2Action], "writes": False, "commits_state": False, "unknown_policy": "reconcile_only", "resource_identity": "resource_ref_exact", "status_identity": "status_ref_recovery_class_exact"}, "recovery_v2_capabilities")

    async def evaluate_recovery_cycle(self, request, bridge):
        return await self._service.evaluate_recovery_cycle(request, bridge)


class RemoteRecoveryCycleV2Engine:
    contract_version = RECOVERY_CYCLE_V2_REMOTE_DISPATCH_VERSION

    def __init__(self, embedded: EmbeddedRecoveryCycleV2Engine) -> None: self._embedded = embedded

    async def dispatch(self, method: str, payload: Mapping[str, Any], bridge: PlatformBridge | None = None) -> Mapping[str, Any]:
        if method != "evaluate_recovery_cycle" and payload: raise ValueError("this recovery 2.0 method does not accept payload")
        if method == "health": return {"status": "alive", "contract_version": self.contract_version, "engine_version": STORY_ENGINE_DISTRIBUTION_VERSION}
        if method in {"describe", "readiness", "capabilities"}: return _json_value(await getattr(self._embedded, method)())
        if method == "evaluate_recovery_cycle":
            if bridge is None: raise ValueError("evaluate_recovery_cycle requires a platform-owned PlatformBridge")
            return _json_value(await self._embedded.evaluate_recovery_cycle(decode_recovery_v2_request(payload), bridge))
        raise ValueError("unsupported recovery 2.0 method")


def _resource_evaluator(frozen_artifact: Artifact) -> DeterministicResourceEvaluator | None:
    value = frozen_artifact.to_mapping()
    if not any(item.get("capability_ref") == "actor.resource_pool/1.0.0" for item in value.get("effect_contracts", ())):
        return None
    return DeterministicResourceEvaluator.from_artifact(value)


def create_embedded_event_engine(*, artifact: Artifact | Mapping[str, Any], artifact_ref: str, clock: Callable[[], Any] | None = None) -> EmbeddedEventEngine:
    frozen_artifact = artifact if isinstance(artifact, Artifact) else Artifact(artifact)
    catalog = RuntimeEventCatalog.from_artifact(frozen_artifact, artifact_ref=artifact_ref)
    return EmbeddedEventEngine(DeterministicEventEvaluator(catalog, resource_evaluator=_resource_evaluator(frozen_artifact), clock=clock), clock=clock)


def create_remote_event_engine(*, artifact: Artifact | Mapping[str, Any], artifact_ref: str, clock: Callable[[], Any] | None = None) -> RemoteEventEngine:
    return RemoteEventEngine(create_embedded_event_engine(artifact=artifact, artifact_ref=artifact_ref, clock=clock))


def create_embedded_event_activation_engine(*, artifact: Artifact | Mapping[str, Any], artifact_ref: str, clock: Callable[[], Any] | None = None) -> EmbeddedEventActivationEngine:
    return EmbeddedEventActivationEngine(create_embedded_event_engine(artifact=artifact, artifact_ref=artifact_ref, clock=clock))


def create_remote_event_activation_engine(*, artifact: Artifact | Mapping[str, Any], artifact_ref: str, clock: Callable[[], Any] | None = None) -> RemoteEventActivationEngine:
    return RemoteEventActivationEngine(create_embedded_event_activation_engine(artifact=artifact, artifact_ref=artifact_ref, clock=clock))


def create_embedded_story_engine(
    *,
    artifact: Artifact | Mapping[str, Any] | None = None,
    artifact_ref: str | None = None,
    provider_status: str = "unavailable",
    clock: Callable[[], Any] | None = None,
    cancellation_poll_seconds: float = 0.01,
) -> EmbeddedStoryEngine:
    if (artifact is None) != (artifact_ref is None):
        raise _input_invalid("construct", "artifact and artifact_ref must be supplied together")
    if provider_status not in {"available", "unavailable", "unknown"}:
        raise _input_invalid("construct", "provider_status must be available, unavailable, or unknown")
    if artifact is None:
        return EmbeddedStoryEngine(None, None, None, provider_status=provider_status)
    assert artifact_ref is not None
    frozen_artifact = artifact if isinstance(artifact, Artifact) else Artifact(artifact)
    event = create_embedded_event_engine(artifact=frozen_artifact, artifact_ref=artifact_ref, clock=clock)
    value = frozen_artifact.to_mapping()
    narrative = NarrativeResolutionService(
        NarrativeArtifactIdentity(artifact_ref, frozen_artifact.artifact_sha256, str(value["canonical_ir_sha256"])),
        provider_status=provider_status,
        clock=clock,
        cancellation_poll_seconds=cancellation_poll_seconds,
    )
    evaluator = _resource_evaluator(frozen_artifact)
    resource_effect = None if evaluator is None else ResourceEffectEvaluationService(
        evaluator, artifact_ref=artifact_ref, artifact_sha256=frozen_artifact.artifact_sha256, clock=clock,
    )
    return EmbeddedStoryEngine(event, narrative, resource_effect, provider_status=provider_status)


def create_remote_story_engine(
    *,
    artifact: Artifact | Mapping[str, Any] | None = None,
    artifact_ref: str | None = None,
    provider_status: str = "unavailable",
    clock: Callable[[], Any] | None = None,
    cancellation_poll_seconds: float = 0.01,
) -> RemoteStoryEngine:
    return RemoteStoryEngine(create_embedded_story_engine(
        artifact=artifact,
        artifact_ref=artifact_ref,
        provider_status=provider_status,
        clock=clock,
        cancellation_poll_seconds=cancellation_poll_seconds,
    ))


def create_embedded_post_resolution_engine(
    *,
    artifact: Artifact | Mapping[str, Any],
    artifact_ref: str,
    provider_capabilities: tuple[str, ...] | frozenset[str],
    clock: Callable[[], datetime] | None = None,
    cancellation_poll_seconds: float = 0.01,
) -> EmbeddedPostResolutionEngine:
    frozen_artifact = artifact if isinstance(artifact, Artifact) else Artifact(artifact)
    value = frozen_artifact.to_mapping()
    service = PostResolutionGenerationService(
        loaded_artifact_ref=artifact_ref,
        loaded_artifact_sha256=frozen_artifact.artifact_sha256,
        loaded_canonical_sha256=str(value["canonical_ir_sha256"]),
        provider_capabilities=provider_capabilities,
        loaded_story_pack_ref=str(value["package"]["package_id"]),
        loaded_resolution_rule_definitions=value["resolution_rule_definitions"],
        clock=clock,
        cancellation_poll_seconds=cancellation_poll_seconds,
    )
    return EmbeddedPostResolutionEngine(service)


def create_remote_post_resolution_engine(
    *,
    artifact: Artifact | Mapping[str, Any],
    artifact_ref: str,
    provider_capabilities: tuple[str, ...] | frozenset[str],
    clock: Callable[[], datetime] | None = None,
    cancellation_poll_seconds: float = 0.01,
) -> RemotePostResolutionEngine:
    return RemotePostResolutionEngine(create_embedded_post_resolution_engine(
        artifact=artifact,
        artifact_ref=artifact_ref,
        provider_capabilities=provider_capabilities,
        clock=clock,
        cancellation_poll_seconds=cancellation_poll_seconds,
    ))


def create_embedded_story_evolution_engine(
    *, artifact: Artifact | Mapping[str, Any], artifact_ref: str,
    provider_capabilities: tuple[str, ...] | frozenset[str],
    clock: Callable[[], datetime] | None = None,
) -> EmbeddedStoryEvolutionEngine:
    frozen_artifact = artifact if isinstance(artifact, Artifact) else Artifact(artifact)
    value = frozen_artifact.to_mapping()
    extension = value.get("v02_extension")
    products = extension.get("products") if isinstance(extension, Mapping) else None
    product = products.get("story_evolution") if isinstance(products, Mapping) else None
    if not isinstance(product, Mapping) or set(product) != {"definition", "ir"}:
        raise ValueError("Artifact lacks the exact StoryEvolution Definition/IR product")
    service = StoryEvolutionGenerationService(
        provider_capabilities=provider_capabilities,
        definition=product["definition"],
        clock=clock,
    )
    return EmbeddedStoryEvolutionEngine(service, product["ir"])


def create_remote_story_evolution_engine(
    *, artifact: Artifact | Mapping[str, Any], artifact_ref: str,
    provider_capabilities: tuple[str, ...] | frozenset[str],
    clock: Callable[[], datetime] | None = None,
) -> RemoteStoryEvolutionEngine:
    return RemoteStoryEvolutionEngine(create_embedded_story_evolution_engine(
        artifact=artifact, artifact_ref=artifact_ref,
        provider_capabilities=provider_capabilities, clock=clock,
    ))


def create_embedded_resource_story_engine(
    *, artifact: Artifact | Mapping[str, Any] | None = None, artifact_ref: str | None = None,
    clock: Callable[[], Any] | None = None,
) -> EmbeddedResourceStoryEngine:
    return EmbeddedResourceStoryEngine(create_embedded_story_engine(
        artifact=artifact, artifact_ref=artifact_ref, provider_status="unavailable", clock=clock,
    ))


def create_remote_resource_story_engine(
    *, artifact: Artifact | Mapping[str, Any] | None = None, artifact_ref: str | None = None,
    clock: Callable[[], Any] | None = None,
) -> RemoteResourceStoryEngine:
    return RemoteResourceStoryEngine(create_embedded_resource_story_engine(
        artifact=artifact, artifact_ref=artifact_ref, clock=clock,
    ))


def create_embedded_turn_interaction_engine(*, artifact: Artifact | Mapping[str, Any], clock: Callable[[], Any] | None = None) -> EmbeddedTurnInteractionEngine:
    frozen = artifact if isinstance(artifact, Artifact) else Artifact(artifact)
    return EmbeddedTurnInteractionEngine(frozen, clock=clock)


def create_remote_turn_interaction_engine(*, artifact: Artifact | Mapping[str, Any], clock: Callable[[], Any] | None = None) -> RemoteTurnInteractionEngine:
    return RemoteTurnInteractionEngine(create_embedded_turn_interaction_engine(artifact=artifact, clock=clock))


def create_embedded_resolution_check_engine(*, artifact: Artifact | Mapping[str, Any], clock: Callable[[], Any] | None = None) -> EmbeddedResolutionCheckEngine:
    frozen = artifact if isinstance(artifact, Artifact) else Artifact(artifact)
    return EmbeddedResolutionCheckEngine(frozen, clock=clock)


def create_remote_resolution_check_engine(*, artifact: Artifact | Mapping[str, Any], clock: Callable[[], Any] | None = None) -> RemoteResolutionCheckEngine:
    return RemoteResolutionCheckEngine(create_embedded_resolution_check_engine(artifact=artifact, clock=clock))
def create_embedded_character_build_engine(*,artifact:Artifact|Mapping[str,Any],clock=None):
    frozen=artifact if isinstance(artifact,Artifact) else Artifact(artifact);return EmbeddedCharacterBuildEngine(frozen,clock)
def create_remote_character_build_engine(*,artifact:Artifact|Mapping[str,Any],clock=None):return RemoteCharacterBuildEngine(create_embedded_character_build_engine(artifact=artifact,clock=clock))
def create_embedded_character_progression_engine(*,artifact:Artifact|Mapping[str,Any],clock=None):
    frozen=artifact if isinstance(artifact,Artifact) else Artifact(artifact);return EmbeddedCharacterProgressionEngine(frozen,clock)
def create_remote_character_progression_engine(*,artifact:Artifact|Mapping[str,Any],clock=None):return RemoteCharacterProgressionEngine(create_embedded_character_progression_engine(artifact=artifact,clock=clock))
def create_embedded_reward_settlement_engine(*,artifact:Artifact|Mapping[str,Any],clock=None):
    frozen=artifact if isinstance(artifact,Artifact) else Artifact(artifact);return EmbeddedRewardSettlementEngine(frozen,clock)
def create_remote_reward_settlement_engine(*,artifact:Artifact|Mapping[str,Any],clock=None):return RemoteRewardSettlementEngine(create_embedded_reward_settlement_engine(artifact=artifact,clock=clock))
def create_embedded_inventory_equipment_engine(*,artifact:Artifact|Mapping[str,Any],clock=None):
    frozen=artifact if isinstance(artifact,Artifact) else Artifact(artifact);return EmbeddedInventoryEquipmentEngine(frozen,clock)
def create_remote_inventory_equipment_engine(*,artifact:Artifact|Mapping[str,Any],clock=None):return RemoteInventoryEquipmentEngine(create_embedded_inventory_equipment_engine(artifact=artifact,clock=clock))
def create_embedded_ability_execution_engine(*,artifact:Artifact|Mapping[str,Any],clock=None):
    frozen=artifact if isinstance(artifact,Artifact) else Artifact(artifact);return EmbeddedAbilityExecutionEngine(frozen,clock)
def create_remote_ability_execution_engine(*,artifact:Artifact|Mapping[str,Any],clock=None):return RemoteAbilityExecutionEngine(create_embedded_ability_execution_engine(artifact=artifact,clock=clock))
def create_embedded_conflict_procedure_engine(*,artifact:Artifact|Mapping[str,Any],clock=None):
    frozen=artifact if isinstance(artifact,Artifact) else Artifact(artifact);return EmbeddedConflictProcedureEngine(frozen,clock)
def create_remote_conflict_procedure_engine(*,artifact:Artifact|Mapping[str,Any],clock=None):return RemoteConflictProcedureEngine(create_embedded_conflict_procedure_engine(artifact=artifact,clock=clock))
def create_embedded_recovery_cycle_engine(*, artifact: Artifact | Mapping[str, Any], artifact_ref: str, clock: Callable[[], Any] | None = None) -> EmbeddedRecoveryCycleEngine:
    frozen = artifact if isinstance(artifact, Artifact) else Artifact(artifact)
    return EmbeddedRecoveryCycleEngine(frozen, artifact_ref, clock)
def create_remote_recovery_cycle_engine(*, artifact: Artifact | Mapping[str, Any], artifact_ref: str, clock: Callable[[], Any] | None = None) -> RemoteRecoveryCycleEngine:
    return RemoteRecoveryCycleEngine(create_embedded_recovery_cycle_engine(artifact=artifact, artifact_ref=artifact_ref, clock=clock))
def create_embedded_recovery_cycle_v2_engine(*, artifact: Artifact | Mapping[str, Any], artifact_ref: str, clock: Callable[[], Any] | None = None) -> EmbeddedRecoveryCycleV2Engine:
    frozen = artifact if isinstance(artifact, Artifact) else Artifact(artifact)
    return EmbeddedRecoveryCycleV2Engine(frozen, artifact_ref, clock)
def create_remote_recovery_cycle_v2_engine(*, artifact: Artifact | Mapping[str, Any], artifact_ref: str, clock: Callable[[], Any] | None = None) -> RemoteRecoveryCycleV2Engine:
    return RemoteRecoveryCycleV2Engine(create_embedded_recovery_cycle_v2_engine(artifact=artifact, artifact_ref=artifact_ref, clock=clock))


__all__ = [
    "EmbeddedEventEngine",
    "EmbeddedEventActivationEngine",
    "EmbeddedStoryEngine",
    "EmbeddedPostResolutionEngine",
    "EmbeddedStoryEvolutionEngine",
    "EmbeddedResourceStoryEngine",
    "EmbeddedTurnInteractionEngine",
    "EmbeddedResolutionCheckEngine",
    "EmbeddedCharacterBuildEngine",
    "EmbeddedCharacterProgressionEngine",
    "EmbeddedRewardSettlementEngine",
    "EmbeddedInventoryEquipmentEngine",
    "EmbeddedAbilityExecutionEngine",
    "EmbeddedConflictProcedureEngine",
    "EmbeddedRecoveryCycleEngine",
    "EmbeddedRecoveryCycleV2Engine",
    "EngineContractError",
    "NARRATIVE_REMOTE_DISPATCH_VERSION",
    "POST_RESOLUTION_REMOTE_DISPATCH_VERSION",
    "STORY_EVOLUTION_REMOTE_DISPATCH_VERSION",
    "RESOURCE_REMOTE_DISPATCH_VERSION",
    "TURN_INTERACTION_REMOTE_DISPATCH_VERSION",
    "RESOLUTION_CHECK_REMOTE_DISPATCH_VERSION",
    "CHARACTER_BUILD_REMOTE_DISPATCH_VERSION",
    "CHARACTER_PROGRESSION_REMOTE_DISPATCH_VERSION",
    "REWARD_SETTLEMENT_REMOTE_DISPATCH_VERSION",
    "INVENTORY_EQUIPMENT_REMOTE_DISPATCH_VERSION",
    "ABILITY_EXECUTION_REMOTE_DISPATCH_VERSION",
    "CONFLICT_PROCEDURE_REMOTE_DISPATCH_VERSION",
    "RECOVERY_CYCLE_REMOTE_DISPATCH_VERSION",
    "RECOVERY_CYCLE_V2_REMOTE_DISPATCH_VERSION",
    "REMOTE_DISPATCH_VERSION",
    "RemoteEventEngine",
    "RemoteEventActivationEngine",
    "RemoteStoryEngine",
    "RemotePostResolutionEngine",
    "RemoteStoryEvolutionEngine",
    "RemoteResourceStoryEngine",
    "RemoteTurnInteractionEngine",
    "RemoteResolutionCheckEngine",
    "RemoteCharacterBuildEngine",
    "RemoteCharacterProgressionEngine",
    "RemoteRewardSettlementEngine",
    "RemoteInventoryEquipmentEngine",
    "RemoteAbilityExecutionEngine",
    "RemoteConflictProcedureEngine",
    "RemoteRecoveryCycleEngine",
    "RemoteRecoveryCycleV2Engine",
    "create_embedded_event_engine",
    "create_embedded_event_activation_engine",
    "create_embedded_story_engine",
    "create_embedded_post_resolution_engine",
    "create_embedded_story_evolution_engine",
    "create_embedded_resource_story_engine",
    "create_embedded_turn_interaction_engine",
    "create_embedded_resolution_check_engine",
    "create_embedded_character_build_engine",
    "create_embedded_character_progression_engine",
    "create_embedded_reward_settlement_engine",
    "create_embedded_inventory_equipment_engine",
    "create_embedded_ability_execution_engine",
    "create_embedded_conflict_procedure_engine",
    "create_embedded_recovery_cycle_engine",
    "create_embedded_recovery_cycle_v2_engine",
    "create_remote_event_engine",
    "create_remote_event_activation_engine",
    "create_remote_story_engine",
    "create_remote_post_resolution_engine",
    "create_remote_story_evolution_engine",
    "create_remote_resource_story_engine",
    "create_remote_turn_interaction_engine",
    "create_remote_resolution_check_engine",
    "create_remote_character_build_engine",
    "create_remote_character_progression_engine",
    "create_remote_reward_settlement_engine",
    "create_remote_inventory_equipment_engine",
    "create_remote_ability_execution_engine",
    "create_remote_conflict_procedure_engine",
    "create_remote_recovery_cycle_engine",
    "create_remote_recovery_cycle_v2_engine",
    "decode_event_advance_request",
    "decode_event_activation_request",
    "decode_resource_effect_request",
    "decode_turn_interaction_request",
    "decode_resolution_check_request",
    "decode_character_build_request",
    "decode_progression_request",
    "decode_reward_request",
    "decode_inventory_request",
    "decode_ability_request",
    "decode_conflict_request",
    "decode_recovery_request",
    "decode_turn_request",
]
