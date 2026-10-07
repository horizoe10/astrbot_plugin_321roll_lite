"""Typed SE 1 Port/Bridge contracts and fail-closed platform mapping."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from story_engine.resources import ResourceEffectEvaluationRequest, ResourceEffectEvaluationResult

from story_engine.versions import (
    CANONICAL_IR_SCHEMA, MODULE_API_VERSION, PLATFORM_BRIDGE_VERSION,
    PLATFORM_CONTRACT_BASELINE, STORY_ENGINE_PORT_VERSION, STORY_ENGINE_SPEC_VERSION,
)

_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_FORBIDDEN_KEYS = frozenset({"astrbot_event", "http_request", "database", "database_session", "repository", "provider_credentials", "provider_key", "user_id", "qq_subject", "adapter_id"})


class ProblemCode(StrEnum):
    CONTRACT_INCOMPATIBLE = "engine.contract_incompatible"
    STORY_PACK_INCOMPATIBLE = "engine.story_pack_incompatible"
    INPUT_INVALID = "engine.input_invalid"
    BUDGET_EXHAUSTED = "engine.budget_exhausted"
    PROVIDER_TIMEOUT = "engine.provider_timeout"
    PROVIDER_RATE_LIMITED = "engine.provider_rate_limited"
    PROVIDER_UNAVAILABLE = "engine.provider_unavailable"
    OUTPUT_INVALID = "engine.output_invalid"
    SEMANTIC_VALIDATION_FAILED = "engine.semantic_validation_failed"
    CANCELLED = "engine.cancelled"
    DEADLINE_EXCEEDED = "engine.deadline_exceeded"
    BRIDGE_UNAVAILABLE = "engine.bridge_unavailable"
    RESULT_STALE = "engine.result_stale"
    INTERNAL_ERROR = "engine.internal_error"
    GUARD_SNAPSHOT_MISSING = "engine.guard_snapshot_missing"
    GUARD_FACT_MISSING = "engine.guard_fact_missing"
    GUARD_FACT_TYPE_INVALID = "engine.guard_fact_type_invalid"
    GUARD_FACT_UNKNOWN = "engine.guard_fact_unknown"
    GUARD_FINGERPRINT_MISMATCH = "engine.guard_fingerprint_mismatch"
    GUARD_REVISION_CONFLICT = "engine.guard_revision_conflict"


class PortContractError(ValueError):
    def __init__(self, code: str | ProblemCode, path: str, safe_message: str) -> None:
        self.code, self.path, self.safe_message = str(code), path, safe_message
        super().__init__(f"{self.code}:{path}")


def _text(value: object, path: str, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise PortContractError(ProblemCode.INPUT_INVALID, path, "字段必须是非空字符串。")
    return value.strip()


def _ref(value: object, path: str) -> str:
    result = _text(value, path, 128)
    if _REF_RE.fullmatch(result) is None:
        raise PortContractError(ProblemCode.INPUT_INVALID, path, "字段不是合法不透明引用。")
    return result


def _digest(value: object, path: str) -> str:
    result = _text(value, path, 71)
    if _HASH_RE.fullmatch(result) is None:
        raise PortContractError(ProblemCode.INPUT_INVALID, path, "字段必须是 sha256 摘要。")
    return result


def _time(value: object, path: str) -> str:
    result = _text(value, path, 64)
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PortContractError(ProblemCode.INPUT_INVALID, path, "字段必须是带时区时间。") from exc
    if parsed.tzinfo is None:
        raise PortContractError(ProblemCode.INPUT_INVALID, path, "字段必须包含时区。")
    return result


def freeze_json(value: object, path: str = "payload") -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PortContractError(ProblemCode.INPUT_INVALID, path, "对象键必须是字符串。")
            if key.lower() in _FORBIDDEN_KEYS:
                raise PortContractError(ProblemCode.INPUT_INVALID, f"{path}.{key}", "输入包含禁止跨端口宿主字段。")
            frozen[key] = freeze_json(item, f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(freeze_json(item, f"{path}[]") for item in value)
    raise PortContractError(ProblemCode.INPUT_INVALID, path, "输入必须是纯 JSON 数据。")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def canonical_fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(_thaw(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class Problem:
    code: ProblemCode
    failed_operation: str
    reason: str
    automatic_handling: str
    next_action: str
    retryable: bool = False

    def __post_init__(self) -> None:
        for name in ("failed_operation", "reason", "automatic_handling", "next_action"):
            _text(getattr(self, name), name, 512)


# Exact semantic subset of the real 321 Roll 0.1.0 stable-error file.
PLATFORM_0_1_ERROR_CATEGORIES = frozenset({"engine_contract_incompatible", "engine_not_ready", "engine_unavailable", "invalid_proposal", "late_result_discarded", "required_capability_missing", "revision_conflict"})
_PLATFORM_ERROR_MAP = MappingProxyType({ProblemCode.CONTRACT_INCOMPATIBLE: "engine_contract_incompatible", ProblemCode.OUTPUT_INVALID: "invalid_proposal", ProblemCode.SEMANTIC_VALIDATION_FAILED: "invalid_proposal", ProblemCode.RESULT_STALE: "late_result_discarded"})


def platform_error_category(problem: Problem) -> str:
    try:
        return _PLATFORM_ERROR_MAP[problem.code]
    except KeyError as exc:
        raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "problem.code", f"{PLATFORM_CONTRACT_BASELINE} 尚无 {problem.code} 的等义稳定类别。") from exc


class ReadinessStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    DRAINING = "draining"
    NOT_READY = "not_ready"


class ProviderMode(StrEnum):
    PLATFORM_BRIDGE = "platform_bridge"
    ENGINE_MANAGED = "engine_managed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class StoryEngineHandshake:
    story_engine_product: str
    story_engine_version: str
    se_spec_range: str
    story_engine_port_range: str
    platform_bridge_range: str
    canonical_ir_range: str
    event_ir_range: str
    module_api_ranges: tuple[str, ...]
    supported_features: frozenset[str]
    required_platform_features: frozenset[str]
    transports: frozenset[str]
    max_request_bytes: int
    max_result_bytes: int
    max_artifact_bytes: int
    deterministic_replay: bool
    security_policy_fingerprint: str

    def __post_init__(self) -> None:
        for name in ("story_engine_product", "story_engine_version", "se_spec_range", "story_engine_port_range", "platform_bridge_range", "canonical_ir_range", "event_ir_range"):
            _text(getattr(self, name), name, 128)
        _digest(self.security_policy_fingerprint, "security_policy_fingerprint")
        if not self.module_api_ranges or not self.transports or any(isinstance(value, bool) or value <= 0 for value in (self.max_request_bytes, self.max_result_bytes, self.max_artifact_bytes)):
            raise PortContractError(ProblemCode.INPUT_INVALID, "handshake", "握手范围或载荷边界无效。")


@dataclass(frozen=True, slots=True)
class StoryEngineReadiness:
    status: ReadinessStatus
    provider_mode: ProviderMode
    accepted_operations: frozenset[str]
    enabled_features: frozenset[str]
    missing_dependencies: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    retry_after_seconds: int | None = None
    components: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    required_capabilities: frozenset[str] = frozenset()
    optional_capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.status is ReadinessStatus.READY and self.missing_dependencies:
            raise PortContractError(ProblemCode.INPUT_INVALID, "readiness", "ready 状态不能缺少依赖。")
        if self.status in {ReadinessStatus.DRAINING, ReadinessStatus.NOT_READY} and self.accepted_operations:
            raise PortContractError(ProblemCode.INPUT_INVALID, "readiness", "当前状态不能接受新操作。")
        if self.required_capabilities & self.optional_capabilities:
            raise PortContractError(ProblemCode.INPUT_INVALID, "readiness.capabilities", "required 与 optional capability 不能重叠。")
        object.__setattr__(self, "components", freeze_json(self.components, "readiness.components"))


@dataclass(frozen=True, slots=True)
class OperationEnvelope:
    engine_contract_version: str
    operation_ref: str
    trace_ref: str
    idempotency_key: str
    request_fingerprint: str
    deadline_at: str
    session_ref: str
    expected_revision: int
    operation_type: str

    def __post_init__(self) -> None:
        for name in ("operation_ref", "trace_ref", "idempotency_key", "session_ref", "operation_type"):
            _ref(getattr(self, name), name)
        _digest(self.request_fingerprint, "request_fingerprint")
        _time(self.deadline_at, "deadline_at")
        if self.engine_contract_version != STORY_ENGINE_PORT_VERSION:
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "engine_contract_version", "Engine Port 合同版本不兼容。")
        if isinstance(self.expected_revision, bool) or self.expected_revision < 0:
            raise PortContractError(ProblemCode.INPUT_INVALID, "expected_revision", "revision 必须非负。")


class NarrativeMode(StrEnum):
    MINIMAL = "minimal"
    BALANCED = "balanced"
    EPIC = "epic"


class NarrativePreset(StrEnum):
    DIALOGUE_HIGH = "dialogue_high"
    DIALOGUE_SOFT = "dialogue_soft"
    BALANCED = "balanced"
    DESCRIPTION_SOFT = "description_soft"
    DESCRIPTION_HIGH = "description_high"


_MODE_BOUNDS = {NarrativeMode.MINIMAL: (350, 600), NarrativeMode.BALANCED: (700, 1200), NarrativeMode.EPIC: (1400, 2600)}


@dataclass(frozen=True, slots=True)
class NarrativePolicySnapshot:
    contract_version: str
    mode: NarrativeMode
    min_visible_chars: int
    max_visible_chars: int
    mode_revision: int
    preset: NarrativePreset
    compiled_instruction: str
    world_voice_summary: str
    source_world_style_sha256: str
    style_revision: int
    policy_fingerprint: str

    def __post_init__(self) -> None:
        if self.contract_version != "narrative-policy/1" or (self.min_visible_chars, self.max_visible_chars) != _MODE_BOUNDS[self.mode]:
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "narrative_policy", "叙事政策版本或字符边界不兼容。")
        _digest(self.source_world_style_sha256, "source_world_style_sha256")
        _digest(self.policy_fingerprint, "policy_fingerprint")
        _text(self.compiled_instruction, "compiled_instruction", 2048)
        _text(self.world_voice_summary, "world_voice_summary", 1024)
        if any(isinstance(value, bool) or value < 0 for value in (self.mode_revision, self.style_revision)):
            raise PortContractError(ProblemCode.INPUT_INVALID, "policy_revision", "政策 revision 必须非负。")


@dataclass(frozen=True, slots=True)
class NarrativePolicyReceipt:
    policy_fingerprint: str
    applied_mode: NarrativeMode
    applied_preset: NarrativePreset
    visible_chars: int
    length_status: str
    instruction_summary: str
    safety_warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _digest(self.policy_fingerprint, "policy_fingerprint")
        _text(self.instruction_summary, "instruction_summary", 256)
        if self.length_status not in {"within_bounds", "below_minimum", "above_maximum"} or isinstance(self.visible_chars, bool) or self.visible_chars < 0:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "narrative_policy_receipt", "叙事政策回执无效。")


@dataclass(frozen=True, slots=True)
class EngineTurnRequest:
    envelope: OperationEnvelope
    story_pack_ref: str
    canonical_sha256: str
    artifact_ref: str
    artifact_sha256: str
    actor_snapshot: Mapping[str, Any]
    action_roster_snapshot: tuple[Mapping[str, Any], ...]
    next_actor_ref: str
    player_input: Mapping[str, Any]
    rule_and_module_snapshot: Mapping[str, Any]
    narrative_policy: NarrativePolicySnapshot
    generation_policy: Mapping[str, Any]
    visibility_policy: Mapping[str, Any]
    fact_snapshot: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.envelope.operation_type != "resolve_turn":
            raise PortContractError(ProblemCode.INPUT_INVALID, "envelope.operation_type", "普通回合必须使用 resolve_turn 操作。")
        _ref(self.story_pack_ref, "story_pack_ref"); _digest(self.canonical_sha256, "canonical_sha256")
        _ref(self.artifact_ref, "artifact_ref"); _digest(self.artifact_sha256, "artifact_sha256"); _ref(self.next_actor_ref, "next_actor_ref")
        if not self.action_roster_snapshot:
            raise PortContractError(ProblemCode.INPUT_INVALID, "action_roster_snapshot", "行动 roster 不能为空。")
        for name in ("actor_snapshot", "player_input", "rule_and_module_snapshot", "generation_policy", "visibility_policy", "fact_snapshot"):
            object.__setattr__(self, name, freeze_json(getattr(self, name), name))
        object.__setattr__(self, "action_roster_snapshot", tuple(freeze_json(item, "action_roster_snapshot") for item in self.action_roster_snapshot))


class TurnResultStatus(StrEnum):
    PROPOSED = "proposed"
    NO_CHANGE = "no_change"
    NEEDS_INPUT = "needs_input"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class EngineTurnResult:
    engine_contract_version: str
    operation_ref: str
    request_fingerprint: str
    expected_revision: int
    status: TurnResultStatus
    narrative_document: Mapping[str, Any] | None
    narrative_policy_receipt: NarrativePolicyReceipt | None
    proposals: tuple[Mapping[str, Any], ...] = ()
    used_fact_refs: tuple[str, ...] = ()
    used_receipt_refs: tuple[str, ...] = ()
    used_capability_refs: tuple[str, ...] = ()
    usage_summary: Mapping[str, Any] = field(default_factory=dict)
    stage_metrics: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    problems: tuple[Problem, ...] = ()

    def __post_init__(self) -> None:
        _ref(self.operation_ref, "operation_ref"); _digest(self.request_fingerprint, "request_fingerprint")
        if self.engine_contract_version != STORY_ENGINE_PORT_VERSION:
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "engine_contract_version", "Engine Port 合同版本不兼容。")
        if isinstance(self.expected_revision, bool) or self.expected_revision < 0 or (self.status is TurnResultStatus.PROPOSED and self.narrative_document is None and not self.proposals):
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "result", "结果 revision 或提案为空。")
        if self.status in {TurnResultStatus.CANCELLED, TurnResultStatus.TIMED_OUT} and (self.narrative_document is not None or self.proposals):
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "result", "取消或超时结果不得携带可提交正文或提案。")
        if self.narrative_document is not None:
            object.__setattr__(self, "narrative_document", freeze_json(self.narrative_document, "narrative_document"))
        object.__setattr__(self, "proposals", tuple(freeze_json(item, "proposals") for item in self.proposals))
        object.__setattr__(self, "usage_summary", freeze_json(self.usage_summary, "usage_summary"))
        object.__setattr__(self, "stage_metrics", tuple(freeze_json(item, "stage_metrics") for item in self.stage_metrics))
        for name in ("used_fact_refs", "used_receipt_refs", "used_capability_refs"):
            object.__setattr__(self, name, tuple(_ref(item, name) for item in getattr(self, name)))


class ModelPurpose(StrEnum):
    TURN_NARRATIVE = "turn_narrative"
    COMPANION_DECISION = "companion_decision"
    PARAGRAPH_REWRITE = "paragraph_rewrite"
    MEMORY_SUMMARY = "memory_summary"
    STORY_EVOLUTION = "story_evolution"
    # ENG02-120: static visual proposals negotiate this purpose explicitly.
    # Every published value above keeps its exact string, so existing readers
    # and stored requests stay valid; a peer that does not advertise
    # visual.static_svg/1.0.0 never receives this request.
    VISUAL_PROPOSAL = "visual_proposal"


@dataclass(frozen=True, slots=True)
class ModelInvocationRequest:
    operation_ref: str
    call_sequence: int
    purpose: ModelPurpose
    system_input: str
    user_input: str
    output_contract: str
    max_output_tokens: int
    sampling: Mapping[str, Any]
    deadline_at: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _ref(self.operation_ref, "operation_ref"); _ref(self.idempotency_key, "idempotency_key"); _time(self.deadline_at, "deadline_at")
        _text(self.system_input, "system_input", 100_000); _text(self.user_input, "user_input", 100_000); _text(self.output_contract, "output_contract", 128)
        if any(isinstance(value, bool) or value < 1 for value in (self.call_sequence, self.max_output_tokens)):
            raise PortContractError(ProblemCode.INPUT_INVALID, "model_invocation", "调用序号和输出预算必须为正整数。")
        object.__setattr__(self, "sampling", freeze_json(self.sampling, "sampling"))


@dataclass(frozen=True, slots=True)
class ModelInvocationResult:
    operation_ref: str
    call_sequence: int
    output: Mapping[str, Any] | str | None
    provider_capabilities: frozenset[str]
    input_tokens: int
    output_tokens: int
    finish_reason: str
    started_at: str
    completed_at: str
    problem: Problem | None = None

    def __post_init__(self) -> None:
        _ref(self.operation_ref, "operation_ref"); _time(self.started_at, "started_at"); _time(self.completed_at, "completed_at")
        _text(self.finish_reason, "finish_reason", 64)
        if isinstance(self.call_sequence, bool) or self.call_sequence < 1 or any(isinstance(value, bool) or value < 0 for value in (self.input_tokens, self.output_tokens)):
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "model_result", "调用序号或 token 用量无效。")
        if self.output is None and self.problem is None:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "model_result", "模型结果缺少输出或问题。")
        if isinstance(self.output, Mapping): object.__setattr__(self, "output", freeze_json(self.output, "model_output"))


@dataclass(frozen=True, slots=True)
class AnonymousProgress:
    operation_ref: str; stage: str; started_at: str; cancellable: bool; active: bool; measured_units: int | None = None

    def __post_init__(self) -> None:
        _ref(self.operation_ref, "operation_ref"); _ref(self.stage, "stage"); _time(self.started_at, "started_at")
        if self.measured_units is not None and (isinstance(self.measured_units, bool) or self.measured_units < 0):
            raise PortContractError(ProblemCode.INPUT_INVALID, "measured_units", "进度单位必须非负。")


@dataclass(frozen=True, slots=True)
class CancellationCheck:
    operation_ref: str; request_fingerprint: str

    def __post_init__(self) -> None:
        _ref(self.operation_ref, "operation_ref"); _digest(self.request_fingerprint, "request_fingerprint")


@dataclass(frozen=True, slots=True)
class CancellationState:
    cancelled: bool; checked_at: str

    def __post_init__(self) -> None:
        _time(self.checked_at, "checked_at")


@dataclass(frozen=True, slots=True)
class ArtifactSliceRequest:
    operation_ref: str; artifact_ref: str; artifact_sha256: str; offset: int; length: int

    def __post_init__(self) -> None:
        _ref(self.operation_ref, "operation_ref"); _ref(self.artifact_ref, "artifact_ref"); _digest(self.artifact_sha256, "artifact_sha256")
        if any(isinstance(value, bool) or value < 0 for value in (self.offset, self.length)) or self.length == 0:
            raise PortContractError(ProblemCode.INPUT_INVALID, "artifact_slice", "Artifact slice 边界无效。")


@dataclass(frozen=True, slots=True)
class ArtifactSlice:
    artifact_ref: str; artifact_sha256: str; offset: int; content: bytes

    def __post_init__(self) -> None:
        _ref(self.artifact_ref, "artifact_ref"); _digest(self.artifact_sha256, "artifact_sha256")
        if isinstance(self.offset, bool) or self.offset < 0 or not isinstance(self.content, bytes):
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "artifact_slice", "Artifact slice 结果无效。")


from .events import EventAdvanceRequest, EventAdvanceResult
from .proposals import (
    CompanionDecisionRequest, CompanionDecisionResult, CompanionMemorySummaryRequest,
    CompanionMemorySummaryResult, EventProjectionFragment, EventProjectionRequest,
    ParagraphRewriteRequest, ParagraphRewriteResult, StoryStreamEvent,
)


class StoryEnginePort(Protocol):
    async def describe(self) -> StoryEngineHandshake | Mapping[str, Any]: ...
    async def readiness(self) -> StoryEngineReadiness | Mapping[str, Any]: ...
    # Capability discovery is Pack-independent; unknown required capabilities fail closed.
    async def capabilities(self) -> Mapping[str, Any]: ...
    async def compile_story_pack(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
    async def resolve_turn(self, request: EngineTurnRequest, bridge: "PlatformBridge") -> EngineTurnResult: ...
    def resolve_turn_stream(self, request: EngineTurnRequest, bridge: "PlatformBridge") -> AsyncIterator[StoryStreamEvent]: ...
    async def evaluate_event(self, request: EventAdvanceRequest, bridge: "PlatformBridge") -> EventAdvanceResult: ...
    async def decide_companion(self, request: CompanionDecisionRequest, bridge: "PlatformBridge") -> CompanionDecisionResult: ...
    async def rewrite_paragraph(self, request: ParagraphRewriteRequest, bridge: "PlatformBridge") -> ParagraphRewriteResult: ...
    async def summarize_companion_memory(self, request: CompanionMemorySummaryRequest, bridge: "PlatformBridge") -> CompanionMemorySummaryResult: ...
    async def project_fragment(self, request: EventProjectionRequest) -> EventProjectionFragment: ...


class ResourceStoryEnginePort(Protocol):
    """Explicit compatible extension; it does not mutate StoryEnginePort 1.0.0."""
    async def describe(self) -> StoryEngineHandshake | Mapping[str, Any]: ...
    async def readiness(self) -> StoryEngineReadiness | Mapping[str, Any]: ...
    async def capabilities(self) -> Mapping[str, Any]: ...
    async def evaluate_resource_effect(self, request: "ResourceEffectEvaluationRequest", bridge: "PlatformBridge") -> "ResourceEffectEvaluationResult": ...


class PlatformBridge(Protocol):
    async def invoke_model(self, request: ModelInvocationRequest) -> ModelInvocationResult: ...
    async def publish_progress(self, progress: AnonymousProgress) -> None: ...
    async def is_cancelled(self, request: CancellationCheck) -> CancellationState: ...
    async def read_authorized_artifact(self, request: ArtifactSliceRequest) -> ArtifactSlice: ...


PLATFORM_0_1_LEGACY_TURN_FIELDS = frozenset({"operation_id", "room_id", "room_revision", "actor", "roster", "narrative", "action"})
PLATFORM_0_1_REQUIRED_TURN_FIELDS = frozenset({"envelope", "story_pack_ref", "canonical_sha256", "artifact_ref", "artifact_sha256", "actor_snapshot", "action_roster_snapshot", "next_actor_ref", "player_input", "rule_and_module_snapshot", "narrative_policy", "generation_policy", "visibility_policy", "fact_snapshot"})
SE1_REQUIRED_ENVELOPE_FIELDS = frozenset({"engine_contract_version", "operation_ref", "trace_ref", "idempotency_key", "request_fingerprint", "deadline_at", "session_ref", "expected_revision", "operation_type"})
SE1_REQUIRED_TURN_FIELDS = PLATFORM_0_1_REQUIRED_TURN_FIELDS | SE1_REQUIRED_ENVELOPE_FIELDS


def inspect_platform_0_1_turn_vector(value: Mapping[str, Any]) -> Mapping[str, Any]:
    keys = set(value)
    if keys == PLATFORM_0_1_LEGACY_TURN_FIELDS:
        if not isinstance(value.get("roster"), Sequence) or not value["roster"]:
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "EngineTurnRequest", "平台旧向量 roster 无效。")
        freeze_json(value, "platform_turn_request")
        return MappingProxyType({"platform_contract": PLATFORM_CONTRACT_BASELINE, "platform_vector_valid": True, "se1_upgrade_ready": False, "missing_se1_fields": tuple(sorted(SE1_REQUIRED_TURN_FIELDS - keys)), "late_result_policy": "fail_closed_until_complete_request_result_vectors"})
    envelope = value.get("envelope")
    if keys != PLATFORM_0_1_REQUIRED_TURN_FIELDS or not isinstance(envelope, Mapping) or set(envelope) != SE1_REQUIRED_ENVELOPE_FIELDS or not isinstance(value.get("action_roster_snapshot"), Sequence) or not value["action_roster_snapshot"]:
        raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "EngineTurnRequest", "平台向量不符合当前 0.1.0 Schema。")
    freeze_json(value, "platform_turn_request")
    return MappingProxyType({"platform_contract": PLATFORM_CONTRACT_BASELINE, "platform_vector_valid": True, "se1_upgrade_ready": True, "missing_se1_fields": (), "late_result_policy": "reject_fingerprint_or_revision_mismatch"})


def default_handshake() -> StoryEngineHandshake:
    security = canonical_fingerprint({"bridge_allowlist": ["invoke_model", "publish_progress", "is_cancelled", "read_authorized_artifact"], "forbidden": sorted(_FORBIDDEN_KEYS), "authority_owner": "321 Roll platform"})
    return StoryEngineHandshake("321 Story Engine", STORY_ENGINE_SPEC_VERSION, ">=1.0.0 <2.0.0", STORY_ENGINE_PORT_VERSION, PLATFORM_BRIDGE_VERSION, CANONICAL_IR_SCHEMA, "se-event-composition-ir/1.0.0", (MODULE_API_VERSION,), frozenset({"readiness/1", "typed-problem/1", "module-registry/1"}), frozenset({"operation-envelope/1", "proposal-validation/1"}), frozenset({"embedded"}), 4_000_000, 4_000_000, 64_000_000, True, security)


def default_readiness() -> StoryEngineReadiness:
    return StoryEngineReadiness(
        ReadinessStatus.DEGRADED,
        ProviderMode.UNAVAILABLE,
        frozenset({"compile_story_pack", "describe", "readiness"}),
        frozenset({"readiness/1", "typed-problem/1", "module-registry/1"}),
        ("platform complete EngineTurnRequest/Result conformance vectors", "model provider bridge"),
        ("platform_contract_incomplete", "provider_unavailable"),
        components={
            "engine_runtime": {"status": "ready"},
            "event": {"status": "not_configured"},
            "narrative": {"status": "degraded", "reason": "provider_unavailable"},
            "stream": {"status": "degraded", "reason": "provider_unavailable"},
            "platform_bridge": {"status": "contract_ready", "version": PLATFORM_BRIDGE_VERSION},
            "provider": {"status": "unavailable"},
            "story_artifact": {"status": "not_configured"},
        },
        required_capabilities=frozenset({"base.narrative"}),
        optional_capabilities=frozenset({"narrative.stream", "narrative.structured_output"}),
    )


__all__ = [
    "AnonymousProgress", "ArtifactSlice", "ArtifactSliceRequest", "CancellationCheck",
    "CancellationState", "EngineTurnRequest", "EngineTurnResult", "ModelInvocationRequest",
    "ModelInvocationResult", "ModelPurpose", "NarrativeMode", "NarrativePolicyReceipt",
    "NarrativePolicySnapshot", "NarrativePreset", "OperationEnvelope",
    "PLATFORM_0_1_ERROR_CATEGORIES", "PLATFORM_0_1_LEGACY_TURN_FIELDS", "PLATFORM_0_1_REQUIRED_TURN_FIELDS",
    "PlatformBridge", "PortContractError", "Problem", "ProblemCode", "ProviderMode",
    "ReadinessStatus", "ResourceStoryEnginePort", "SE1_REQUIRED_ENVELOPE_FIELDS", "SE1_REQUIRED_TURN_FIELDS", "StoryEngineHandshake", "StoryEnginePort",
    "StoryEngineReadiness", "TurnResultStatus", "canonical_fingerprint", "default_handshake",
    "default_readiness", "freeze_json", "inspect_platform_0_1_turn_vector",
    "platform_error_category",
]
