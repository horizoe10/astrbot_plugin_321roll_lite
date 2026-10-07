"""Bridge-only ordinary-turn narrative resolution with proposal-only closure."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from collections.abc import Mapping, Sequence
from concurrent.futures import Future
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Callable

from .contracts.port import (
    AnonymousProgress,
    CancellationCheck,
    EngineTurnRequest,
    EngineTurnResult,
    ModelInvocationRequest,
    ModelInvocationResult,
    ModelPurpose,
    NarrativePolicyReceipt,
    PlatformBridge,
    PortContractError,
    Problem,
    ProblemCode,
    ProviderMode,
    ReadinessStatus,
    StoryEngineReadiness,
    TurnResultStatus,
    _digest,
    _ref,
    canonical_fingerprint,
    freeze_json,
)
from .contracts.proposals import (
    StoryChunk,
    StoryStreamEvent,
    StreamFinality,
    StreamKind,
)
from .versions import PLATFORM_BRIDGE_VERSION, STORY_ENGINE_PORT_VERSION

NARRATIVE_OUTPUT_CONTRACT = "se-turn-narrative-proposal/1.0.0"
NARRATIVE_STREAM_CONTRACT = "story-stream/1.0.0"
NARRATIVE_REQUEST_CAPABILITIES = frozenset({
    "base.narrative",
    "narrative.stream",
    "narrative.structured_output",
})
NARRATIVE_REQUIRED_CAPABILITIES = frozenset({"base.narrative"})
NARRATIVE_OPTIONAL_CAPABILITIES = frozenset({"narrative.stream", "narrative.structured_output"})
NARRATIVE_PROVIDER_REQUIRED_CAPABILITIES = frozenset({"structured_output"})
_PROVIDER_STATES = frozenset({"available", "unavailable", "unknown"})


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {name: _plain(getattr(value, name)) for name in value.__dataclass_fields__}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_plain(item) for item in value]
    return value


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _visible_chars(blocks: Sequence[Mapping[str, Any]]) -> int:
    return len("".join(str(block["text"]) for block in blocks).replace(" ", "").replace("\n", "").replace("\t", ""))


def _problem(
    code: ProblemCode,
    failed_operation: str,
    reason: str,
    next_action: str,
    *,
    retryable: bool = False,
) -> Problem:
    return Problem(
        code,
        failed_operation,
        reason,
        "没有生成或提交正文、事实或事件提案。",
        next_action,
        retryable,
    )


def _sequence_of_refs(value: object, path: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise PortContractError(ProblemCode.INPUT_INVALID, path, "capability 或引用集合必须是数组。")
    result = tuple(_ref(item, path) for item in value)
    if len(result) != len(set(result)):
        raise PortContractError(ProblemCode.INPUT_INVALID, path, "capability 或引用不能重复。")
    return result


def _bridge_problem_code(value: object) -> tuple[ProblemCode, bool]:
    category = str(getattr(value, "category", "")).lower()
    code = str(getattr(value, "code", "")).lower()
    material = f"{category} {code} {value}".lower()
    if "rate" in material and "limit" in material:
        return ProblemCode.PROVIDER_RATE_LIMITED, True
    if "timeout" in material or "timed_out" in material:
        return ProblemCode.PROVIDER_TIMEOUT, True
    if "cancel" in material:
        return ProblemCode.CANCELLED, False
    if "artifact" in material and ("authorized" in material or "authorised" in material):
        return ProblemCode.STORY_PACK_INCOMPATIBLE, False
    if "output" in material and "invalid" in material:
        return ProblemCode.OUTPUT_INVALID, False
    if "provider" in material or isinstance(value, (ConnectionError, OSError)):
        return ProblemCode.PROVIDER_UNAVAILABLE, True
    return ProblemCode.BRIDGE_UNAVAILABLE, True


@dataclass(frozen=True, slots=True)
class NarrativeArtifactIdentity:
    artifact_ref: str
    artifact_sha256: str
    canonical_sha256: str

    def __post_init__(self) -> None:
        _ref(self.artifact_ref, "artifact_ref")
        _digest(self.artifact_sha256, "artifact_sha256")
        _digest(self.canonical_sha256, "canonical_sha256")


class NarrativeResolutionService:
    """One primary model call per ordinary turn; all output remains provisional."""

    def __init__(
        self,
        artifact: NarrativeArtifactIdentity,
        *,
        provider_status: str = "unknown",
        clock: Callable[[], datetime] | None = None,
        cancellation_poll_seconds: float = 0.01,
    ) -> None:
        if provider_status not in _PROVIDER_STATES:
            raise ValueError("provider_status must be available, unavailable, or unknown")
        if cancellation_poll_seconds <= 0:
            raise ValueError("cancellation_poll_seconds must be positive")
        self.artifact = artifact
        self.provider_status = provider_status
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cancellation_poll_seconds = cancellation_poll_seconds
        self._identity_lock = threading.Lock()
        self._identities: dict[str, tuple[str, str, int, str, str, str]] = {}
        self._results: dict[str, EngineTurnResult] = {}
        self._inflight: dict[str, Future[EngineTurnResult]] = {}

    def readiness(self, *, event_ready: bool) -> StoryEngineReadiness:
        provider_ready = self.provider_status == "available"
        narrative_status = "ready" if provider_ready else "degraded"
        provider_reason = None if provider_ready else f"provider_{self.provider_status}"
        accepted = {"describe", "readiness", "evaluate_event"} if event_ready else {"describe", "readiness"}
        if provider_ready:
            accepted.update({"resolve_turn", "resolve_turn_stream"})
        missing = () if provider_ready else ("platform model provider through PlatformBridge.invoke_model",)
        reasons = () if provider_ready else (("narrative_provider_unavailable",) if self.provider_status == "unavailable" else ("narrative_provider_status_unknown",))
        components = {
            "engine_runtime": {"status": "ready"},
            "event": {"status": "ready" if event_ready else "not_configured"},
            "narrative": {"status": narrative_status, "operation": "resolve_turn", "reason": provider_reason},
            "stream": {
                "status": narrative_status,
                "operation": "resolve_turn_stream",
                "first_readable_segment": "first validated block after the unary bridge model result",
                "reason": provider_reason,
            },
            "platform_bridge": {
                "status": "contract_ready",
                "version": PLATFORM_BRIDGE_VERSION,
                "allowlist": ["invoke_model", "publish_progress", "is_cancelled", "read_authorized_artifact"],
            },
            "provider": {
                "status": self.provider_status,
                "required_capabilities": sorted(NARRATIVE_PROVIDER_REQUIRED_CAPABILITIES),
                "credentials_owner": "321_platform",
            },
            "story_artifact": {
                "status": "ready",
                "artifact_ref": self.artifact.artifact_ref,
                "artifact_sha256": self.artifact.artifact_sha256,
                "canonical_sha256": self.artifact.canonical_sha256,
            },
        }
        return StoryEngineReadiness(
            ReadinessStatus.READY if provider_ready and event_ready else ReadinessStatus.DEGRADED,
            ProviderMode.PLATFORM_BRIDGE if provider_ready else ProviderMode.UNAVAILABLE,
            frozenset(accepted),
            frozenset({"event-evaluate/1", "narrative-resolve-turn/1", "narrative-stream/1", "single-primary-model-call/1", "proposal-only/1"}),
            missing,
            reasons,
            components=components,
            required_capabilities=NARRATIVE_REQUIRED_CAPABILITIES,
            optional_capabilities=NARRATIVE_OPTIONAL_CAPABILITIES,
        )

    async def resolve_turn(self, request: EngineTurnRequest, bridge: PlatformBridge) -> EngineTurnResult:
        identity = (
            request.envelope.operation_ref,
            request.envelope.request_fingerprint,
            request.envelope.expected_revision,
            request.artifact_sha256,
            request.canonical_sha256,
            canonical_fingerprint({
                "story_pack_ref": request.story_pack_ref,
                "actor_snapshot": _plain(request.actor_snapshot),
                "action_roster_snapshot": _plain(request.action_roster_snapshot),
                "next_actor_ref": request.next_actor_ref,
                "player_input": _plain(request.player_input),
                "rule_and_module_snapshot": _plain(request.rule_and_module_snapshot),
                "narrative_policy": _plain(request.narrative_policy),
                "generation_policy": _plain(request.generation_policy),
                "visibility_policy": _plain(request.visibility_policy),
                "fact_snapshot": _plain(request.fact_snapshot),
            }),
        )
        idempotency_key = request.envelope.idempotency_key
        with self._identity_lock:
            previous = self._identities.get(idempotency_key)
            if previous is not None and previous != identity:
                return self._terminal_result(
                    request,
                    TurnResultStatus.BLOCKED,
                    _problem(
                        ProblemCode.RESULT_STALE,
                        "解析普通回合",
                        "相同幂等键对应了不同输入、指纹、Artifact 或 revision。",
                        "请保留原操作，使用新的幂等键重新发起当前 revision 的行动。",
                    ),
                )
            self._identities.setdefault(idempotency_key, identity)
            cached = self._results.get(idempotency_key)
            if cached is not None:
                return cached
            shared = self._inflight.get(idempotency_key)
            owner = shared is None
            if owner:
                shared = Future()
                self._inflight[idempotency_key] = shared
        assert shared is not None
        if not owner:
            return await asyncio.wrap_future(shared)
        try:
            result = await self._resolve_uncached(request, bridge)
        except asyncio.CancelledError:
            result = self._terminal_result(
                request,
                TurnResultStatus.CANCELLED,
                _problem(ProblemCode.CANCELLED, "解析普通回合", "Engine 调用任务已取消。", "如仍需继续，请重新发起行动。"),
            )
        except Exception:
            result = self._terminal_result(
                request,
                TurnResultStatus.BLOCKED,
                _problem(ProblemCode.INTERNAL_ERROR, "解析普通回合", "Engine 内部处理异常。", "请检查 Engine 日志和 readiness 后安全重试。", retryable=True),
            )
        cacheable = not any(problem.retryable for problem in result.problems)
        with self._identity_lock:
            self._inflight.pop(idempotency_key, None)
            if cacheable:
                self._results[idempotency_key] = result
            if not shared.done():
                shared.set_result(result)
        return result

    async def resolve_turn_stream(self, request: EngineTurnRequest, bridge: PlatformBridge):
        result = await self.resolve_turn(request, bridge)
        sequence = 0
        audience = request.visibility_policy.get("audience", "room")
        try:
            audience = _ref(audience, "visibility_policy.audience")
        except PortContractError:
            result = self._terminal_result(
                request,
                TurnResultStatus.BLOCKED,
                _problem(ProblemCode.INPUT_INVALID, "流式解析普通回合", "冻结 audience 无效。", "请修正 visibility_policy 后重新发起行动。"),
            )
        if result.status is TurnResultStatus.PROPOSED and result.narrative_document is not None:
            fragments: list[dict[str, str]] = []
            for index, block in enumerate(result.narrative_document["blocks"], start=1):
                sequence += 1
                fragments.append({"kind": "paragraph", "text": str(block["text"])})
                chunk = StoryChunk(
                    self._fragment_ref(request.envelope.operation_ref, index),
                    "paragraph",
                    str(block["text"]),
                    canonical_fingerprint({"fragments": fragments}),
                )
                yield StoryStreamEvent(
                    NARRATIVE_STREAM_CONTRACT,
                    request.envelope.operation_ref,
                    request.envelope.request_fingerprint,
                    request.envelope.expected_revision,
                    sequence,
                    StreamKind.STORY_CHUNK,
                    StreamFinality.PROVISIONAL_STORY,
                    str(audience),
                    self._timestamp(),
                    story_chunk=chunk,
                )
                interruption = await self._stream_interruption(request, bridge)
                if interruption is not None:
                    result = interruption
                    break
        sequence += 1
        yield StoryStreamEvent(
            NARRATIVE_STREAM_CONTRACT,
            request.envelope.operation_ref,
            request.envelope.request_fingerprint,
            request.envelope.expected_revision,
            sequence,
            StreamKind.FINAL_RESULT,
            StreamFinality.TERMINAL,
            str(audience),
            self._timestamp(),
            final_result=result,
        )

    async def _resolve_uncached(self, request: EngineTurnRequest, bridge: PlatformBridge) -> EngineTurnResult:
        mismatch = self._artifact_mismatch(request)
        if mismatch is not None:
            return mismatch
        if self._deadline_expired(request):
            return self._terminal_result(
                request,
                TurnResultStatus.TIMED_OUT,
                _problem(ProblemCode.DEADLINE_EXCEEDED, "解析普通回合", "操作在开始前已超过冻结截止时间。", "请刷新房间后重新发起行动。"),
            )
        capability_result = self._validate_capabilities(request)
        if isinstance(capability_result, EngineTurnResult):
            return capability_result
        required, optional, capability_warnings = capability_result
        generation = request.generation_policy
        primary_calls = generation.get("primary_model_calls", 1)
        if isinstance(primary_calls, bool) or primary_calls != 1:
            return self._terminal_result(
                request,
                TurnResultStatus.BLOCKED,
                _problem(ProblemCode.INPUT_INVALID, "解析普通回合", "普通回合必须固定为一次主模型调用。", "请将 generation_policy.primary_model_calls 设为 1。"),
            )
        if self.provider_status == "unavailable":
            return self._terminal_result(
                request,
                TurnResultStatus.BLOCKED,
                _problem(ProblemCode.PROVIDER_UNAVAILABLE, "生成普通回合正文", "PlatformBridge 没有可用 provider。", "请由平台所有者完成 provider 连接测试后重试。", retryable=True),
            )
        cancellation = await self._cancellation_state(request, bridge)
        if isinstance(cancellation, EngineTurnResult):
            return cancellation
        if cancellation:
            return self._cancelled_result(request, "操作在 provider 调用前已取消。")
        progress_warnings: list[str] = []
        await self._publish_progress(request, bridge, True, progress_warnings)
        try:
            invocation = self._model_request(request)
        except PortContractError as exc:
            return self._terminal_result(
                request,
                TurnResultStatus.BLOCKED,
                _problem(ProblemCode.INPUT_INVALID, "建立 provider 请求", exc.safe_message, "请修正 generation_policy 后重新发起行动。"),
            )
        outcome, value = await self._invoke_with_cancellation(request, bridge, invocation)
        await self._publish_progress(request, bridge, False, progress_warnings)
        if outcome == "cancelled":
            return self._cancelled_result(request, "操作在 provider 调用期间已取消；迟到结果必须由平台丢弃。")
        if outcome == "timed_out":
            return self._terminal_result(
                request,
                TurnResultStatus.TIMED_OUT,
                _problem(ProblemCode.PROVIDER_TIMEOUT, "生成普通回合正文", "provider 调用超过冻结超时预算。", "请检查 provider 延迟后以新操作安全重试。", retryable=True),
            )
        if outcome == "error":
            code, retryable = _bridge_problem_code(value)
            status = TurnResultStatus.CANCELLED if code is ProblemCode.CANCELLED else TurnResultStatus.BLOCKED
            return self._terminal_result(
                request,
                status,
                _problem(code, "通过 PlatformBridge 调用 provider", "provider 或 Bridge 调用失败。", "请检查平台 provider/Bridge 状态后安全重试。", retryable=retryable),
            )
        model_result = value
        if not isinstance(model_result, ModelInvocationResult):
            return self._invalid_output(request, "PlatformBridge 返回的 provider 结果类型无效。")
        validated = self._validate_model_result(request, model_result, required, optional)
        if isinstance(validated, EngineTurnResult):
            return validated
        blocks, proposals, fact_refs, receipt_refs, used_capabilities, provider_warnings = validated
        cancellation = await self._cancellation_state(request, bridge)
        if isinstance(cancellation, EngineTurnResult):
            return cancellation
        if cancellation:
            return self._cancelled_result(request, "provider 返回后操作已取消；结果未进入提案收束。")
        if self._deadline_expired(request):
            return self._terminal_result(
                request,
                TurnResultStatus.TIMED_OUT,
                _problem(ProblemCode.DEADLINE_EXCEEDED, "生成普通回合正文", "provider 结果到达时已超过冻结截止时间。", "请刷新房间后以新操作重试。"),
            )
        visible = _visible_chars(blocks)
        policy = request.narrative_policy
        length_status = "within_bounds"
        if visible < policy.min_visible_chars:
            length_status = "below_minimum"
        elif visible > policy.max_visible_chars:
            length_status = "above_maximum"
        receipt = NarrativePolicyReceipt(
            policy.policy_fingerprint,
            policy.mode,
            policy.preset,
            visible,
            length_status,
            policy.compiled_instruction[:256],
            tuple(provider_warnings),
        )
        warnings = tuple(capability_warnings + progress_warnings + provider_warnings + ([] if length_status == "within_bounds" else [f"narrative_{length_status}"]))
        return EngineTurnResult(
            STORY_ENGINE_PORT_VERSION,
            request.envelope.operation_ref,
            request.envelope.request_fingerprint,
            request.envelope.expected_revision,
            TurnResultStatus.PROPOSED,
            {"blocks": [dict(block) for block in blocks]},
            receipt,
            tuple(proposals),
            fact_refs,
            receipt_refs,
            used_capabilities,
            {
                "model_calls": 1,
                "input_tokens": model_result.input_tokens,
                "output_tokens": model_result.output_tokens,
                "finish_reason": model_result.finish_reason,
            },
            (
                {"stage": "provider", "started_at": model_result.started_at, "completed_at": model_result.completed_at},
            ),
            warnings,
            (),
        )

    def _artifact_mismatch(self, request: EngineTurnRequest) -> EngineTurnResult | None:
        if (request.artifact_ref, request.artifact_sha256, request.canonical_sha256) == (
            self.artifact.artifact_ref,
            self.artifact.artifact_sha256,
            self.artifact.canonical_sha256,
        ):
            return None
        return self._terminal_result(
            request,
            TurnResultStatus.BLOCKED,
            _problem(ProblemCode.STORY_PACK_INCOMPATIBLE, "解析普通回合", "冻结请求与已加载 Story Artifact 不一致。", "请重新固定通过校验的 Story Pack/Artifact 后再试。"),
        )

    def _validate_capabilities(self, request: EngineTurnRequest):
        try:
            required = frozenset(_sequence_of_refs(request.rule_and_module_snapshot.get("required_capabilities"), "required_capabilities"))
            optional = frozenset(_sequence_of_refs(request.rule_and_module_snapshot.get("optional_capabilities"), "optional_capabilities"))
        except PortContractError as exc:
            return self._terminal_result(
                request,
                TurnResultStatus.BLOCKED,
                _problem(exc.code if isinstance(exc.code, ProblemCode) else ProblemCode.INPUT_INVALID, "协商正文 capability", exc.safe_message, "请修正冻结 capability 集合后重新发起行动。"),
            )
        unknown_required = required - NARRATIVE_REQUEST_CAPABILITIES
        if unknown_required:
            return self._terminal_result(
                request,
                TurnResultStatus.BLOCKED,
                _problem(ProblemCode.CONTRACT_INCOMPATIBLE, "协商正文 capability", f"存在不兼容的必需 capability：{', '.join(sorted(unknown_required))}。", "请升级 Engine/provider 或选择兼容 Story Pack。"),
            )
        unknown_optional = optional - NARRATIVE_REQUEST_CAPABILITIES
        warnings = [f"optional_capability_unavailable:{item}" for item in sorted(unknown_optional)]
        return required, optional & NARRATIVE_REQUEST_CAPABILITIES, warnings

    def _model_request(self, request: EngineTurnRequest) -> ModelInvocationRequest:
        generation = request.generation_policy
        max_tokens = generation.get("max_output_tokens", max(256, min(8192, request.narrative_policy.max_visible_chars * 2)))
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
            raise PortContractError(ProblemCode.INPUT_INVALID, "generation_policy.max_output_tokens", "模型输出预算必须是正整数。")
        sampling = generation.get("sampling", {})
        if not isinstance(sampling, Mapping):
            raise PortContractError(ProblemCode.INPUT_INVALID, "generation_policy.sampling", "sampling 必须是对象。")
        policy = _plain(request.narrative_policy)
        system_input = (
            "生成普通回合的结构化提案。只能依据冻结输入；正文、事实和事件只能作为提案返回，"
            "不得声称已提交、不得写平台状态、不得加入渠道 renderer。严格返回 "
            f"{NARRATIVE_OUTPUT_CONTRACT}。冻结 narrative_policy="
            + json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        user_payload = {
            "story_pack_ref": request.story_pack_ref,
            "artifact_ref": request.artifact_ref,
            "actor_snapshot": _plain(request.actor_snapshot),
            "action_roster_snapshot": _plain(request.action_roster_snapshot),
            "next_actor_ref": request.next_actor_ref,
            "player_input": _plain(request.player_input),
            "rule_and_module_snapshot": _plain(request.rule_and_module_snapshot),
            "visibility_policy": _plain(request.visibility_policy),
            "fact_snapshot": _plain(request.fact_snapshot),
        }
        model_idempotency = "model." + hashlib.sha256(
            f"{request.envelope.idempotency_key}|{request.envelope.request_fingerprint}|1".encode("utf-8")
        ).hexdigest()[:40]
        return ModelInvocationRequest(
            request.envelope.operation_ref,
            1,
            ModelPurpose.TURN_NARRATIVE,
            system_input,
            json.dumps(user_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False),
            NARRATIVE_OUTPUT_CONTRACT,
            max_tokens,
            sampling,
            request.envelope.deadline_at,
            model_idempotency,
        )

    async def _invoke_with_cancellation(self, request: EngineTurnRequest, bridge: PlatformBridge, invocation: ModelInvocationRequest):
        task = asyncio.create_task(bridge.invoke_model(invocation))
        loop = asyncio.get_running_loop()
        remaining = max(0.0, (_parse_time(request.envelope.deadline_at) - self._clock()).total_seconds())
        configured_ms = request.generation_policy.get("provider_timeout_ms")
        if configured_ms is not None:
            if isinstance(configured_ms, bool) or not isinstance(configured_ms, int) or configured_ms <= 0:
                task.cancel()
                with suppress(BaseException):
                    await task
                return "error", PortContractError(ProblemCode.INPUT_INVALID, "provider_timeout_ms", "provider_timeout_ms 必须为正整数。")
            remaining = min(remaining, configured_ms / 1000)
        expires = loop.time() + remaining
        while True:
            timeout = max(0.0, min(self._cancellation_poll_seconds, expires - loop.time()))
            if timeout <= 0:
                task.cancel()
                with suppress(BaseException):
                    await task
                return "timed_out", None
            done, _ = await asyncio.wait({task}, timeout=timeout)
            if task in done:
                try:
                    return "result", task.result()
                except asyncio.CancelledError:
                    return "cancelled", None
                except Exception as exc:
                    return "error", exc
            cancellation = await self._cancellation_state(request, bridge)
            if isinstance(cancellation, EngineTurnResult):
                task.cancel()
                with suppress(BaseException):
                    await task
                return "error", RuntimeError(cancellation.problems[0].reason)
            if cancellation:
                task.cancel()
                with suppress(BaseException):
                    await task
                return "cancelled", None

    def _validate_model_result(self, request: EngineTurnRequest, result: ModelInvocationResult, required: frozenset[str], optional: frozenset[str]):
        if (result.operation_ref, result.call_sequence) != (request.envelope.operation_ref, 1):
            return self._invalid_output(request, "provider 结果不属于当前操作或主调用序号。")
        if _parse_time(result.completed_at) < _parse_time(result.started_at):
            return self._invalid_output(request, "provider 完成时间早于开始时间。")
        if result.problem is not None:
            code, retryable = _bridge_problem_code(result.problem)
            return self._terminal_result(
                request,
                TurnResultStatus.BLOCKED,
                _problem(code, "生成普通回合正文", result.problem.reason, result.problem.next_action, retryable=retryable or result.problem.retryable),
            )
        failed_finish = result.finish_reason.lower() in {"error", "failed", "timeout", "timed_out", "rate_limit", "rate_limited"}
        if failed_finish:
            code = ProblemCode.PROVIDER_RATE_LIMITED if "rate" in result.finish_reason.lower() else ProblemCode.PROVIDER_TIMEOUT if "time" in result.finish_reason.lower() else ProblemCode.OUTPUT_INVALID
            return self._terminal_result(
                request,
                TurnResultStatus.TIMED_OUT if code is ProblemCode.PROVIDER_TIMEOUT else TurnResultStatus.BLOCKED,
                _problem(code, "生成普通回合正文", "provider 以失败 finish_reason 结束。", "请检查 provider 状态后安全重试。", retryable=code is not ProblemCode.OUTPUT_INVALID),
            )
        missing_provider = NARRATIVE_PROVIDER_REQUIRED_CAPABILITIES - result.provider_capabilities
        if missing_provider:
            return self._terminal_result(
                request,
                TurnResultStatus.BLOCKED,
                _problem(ProblemCode.CONTRACT_INCOMPATIBLE, "验证 provider capability", f"provider 缺少必需 capability：{', '.join(sorted(missing_provider))}。", "请切换到支持结构化输出的 provider。"),
            )
        if not isinstance(result.output, Mapping):
            return self._invalid_output(request, "provider 必须返回结构化对象，不能返回空值或裸文本。")
        try:
            output = freeze_json(result.output, "provider_output")
            direct = set(output) == {"blocks"}
            allowed = {"narrative_document", "proposals", "used_fact_refs", "used_receipt_refs", "used_capability_refs", "warnings"}
            if not direct and ("narrative_document" not in output or not set(output) <= allowed):
                raise PortContractError(ProblemCode.OUTPUT_INVALID, "provider_output", "provider 根对象字段不符合固定输出合同。")
            document = output if direct else output["narrative_document"]
            if not isinstance(document, Mapping) or set(document) != {"blocks"}:
                raise PortContractError(ProblemCode.OUTPUT_INVALID, "narrative_document", "正文对象必须且只能包含 blocks。")
            blocks_value = document["blocks"]
            if not isinstance(blocks_value, Sequence) or isinstance(blocks_value, (str, bytes, bytearray)) or not blocks_value or len(blocks_value) > 64:
                raise PortContractError(ProblemCode.OUTPUT_INVALID, "narrative_document.blocks", "正文块数量无效。")
            blocks: list[dict[str, str]] = []
            for block in blocks_value:
                if not isinstance(block, Mapping) or set(block) != {"text"} or not isinstance(block["text"], str) or not block["text"].strip():
                    raise PortContractError(ProblemCode.OUTPUT_INVALID, "narrative_document.blocks", "每个正文块必须且只能包含非空 text。")
                blocks.append({"text": block["text"].strip()})
            proposals_value = () if direct else output.get("proposals", ())
            if not isinstance(proposals_value, Sequence) or isinstance(proposals_value, (str, bytes, bytearray)) or len(proposals_value) > 128:
                raise PortContractError(ProblemCode.OUTPUT_INVALID, "proposals", "提案集合无效或超出上限。")
            proposals: list[dict[str, Any]] = []
            for proposal in proposals_value:
                if not isinstance(proposal, Mapping) or set(proposal) != {"type", "value"} or not isinstance(proposal["value"], Mapping):
                    raise PortContractError(ProblemCode.OUTPUT_INVALID, "proposals", "每个提案必须且只能包含 type 和 value。")
                proposals.append({"type": _ref(proposal["type"], "proposal.type"), "value": _plain(proposal["value"])})
            fact_refs = _sequence_of_refs(None if direct else output.get("used_fact_refs"), "used_fact_refs")
            receipt_refs = _sequence_of_refs(None if direct else output.get("used_receipt_refs"), "used_receipt_refs")
            declared_capabilities = _sequence_of_refs(None if direct else output.get("used_capability_refs"), "used_capability_refs")
            used_capabilities = declared_capabilities or tuple(sorted({"base.narrative"} | required))
            negotiated_capabilities = {"base.narrative"} | required | optional
            if not set(used_capabilities) <= negotiated_capabilities:
                raise PortContractError(ProblemCode.OUTPUT_INVALID, "used_capability_refs", "provider 声称使用了未协商 capability。")
            available_facts = set(_sequence_of_refs(request.fact_snapshot.get("fact_refs"), "fact_snapshot.fact_refs"))
            available_receipts = set(_sequence_of_refs(request.fact_snapshot.get("receipt_refs"), "fact_snapshot.receipt_refs"))
            available_receipts.update(_sequence_of_refs(request.rule_and_module_snapshot.get("committed_receipt_refs"), "committed_receipt_refs"))
            if not set(fact_refs) <= available_facts or not set(receipt_refs) <= available_receipts:
                raise PortContractError(ProblemCode.SEMANTIC_VALIDATION_FAILED, "provider_output.refs", "provider 引用了冻结输入之外的事实或正式回执。")
            warnings_value = () if direct else output.get("warnings", ())
            if not isinstance(warnings_value, Sequence) or isinstance(warnings_value, (str, bytes, bytearray)):
                raise PortContractError(ProblemCode.OUTPUT_INVALID, "warnings", "warnings 必须是数组。")
            if any(not isinstance(item, str) or not item.strip() for item in warnings_value):
                raise PortContractError(ProblemCode.OUTPUT_INVALID, "warnings", "warnings 只能包含非空字符串。")
            warnings = [item.strip() for item in warnings_value]
        except PortContractError as exc:
            return self._terminal_result(
                request,
                TurnResultStatus.BLOCKED,
                _problem(exc.code if isinstance(exc.code, ProblemCode) else ProblemCode.OUTPUT_INVALID, "验证 provider 输出", exc.safe_message, "请检查 provider 输出合同后重试。"),
            )
        return tuple(blocks), tuple(proposals), fact_refs, receipt_refs, tuple(used_capabilities), warnings

    async def _stream_interruption(self, request: EngineTurnRequest, bridge: PlatformBridge) -> EngineTurnResult | None:
        if self._deadline_expired(request):
            return self._terminal_result(
                request,
                TurnResultStatus.TIMED_OUT,
                _problem(ProblemCode.DEADLINE_EXCEEDED, "流式输出正文", "正文流在收束前超过冻结截止时间。", "平台必须丢弃所有 provisional 段；请刷新后重试。"),
            )
        cancellation = await self._cancellation_state(request, bridge)
        if isinstance(cancellation, EngineTurnResult):
            return cancellation
        if cancellation:
            return self._cancelled_result(request, "正文流在中途取消；所有已发段仍为 provisional。")
        return None

    async def _cancellation_state(self, request: EngineTurnRequest, bridge: PlatformBridge) -> bool | EngineTurnResult:
        try:
            state = await bridge.is_cancelled(CancellationCheck(request.envelope.operation_ref, request.envelope.request_fingerprint))
        except Exception:
            return self._terminal_result(
                request,
                TurnResultStatus.BLOCKED,
                _problem(ProblemCode.BRIDGE_UNAVAILABLE, "检查取消状态", "PlatformBridge 无法确认操作是否已取消。", "请恢复 Bridge 后安全重试。", retryable=True),
            )
        if not hasattr(state, "cancelled"):
            return self._terminal_result(
                request,
                TurnResultStatus.BLOCKED,
                _problem(ProblemCode.OUTPUT_INVALID, "检查取消状态", "PlatformBridge 返回了无效取消状态。", "请检查 Bridge 合同实现。"),
            )
        return bool(state.cancelled)

    async def _publish_progress(self, request: EngineTurnRequest, bridge: PlatformBridge, active: bool, warnings: list[str]) -> None:
        try:
            await bridge.publish_progress(
                AnonymousProgress(request.envelope.operation_ref, "provider_running", self._timestamp(), True, active, None)
            )
        except Exception:
            warnings.append("progress_publish_failed")

    def _deadline_expired(self, request: EngineTurnRequest) -> bool:
        return self._clock() >= _parse_time(request.envelope.deadline_at)

    def _timestamp(self) -> str:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat().replace("+00:00", "Z")

    @staticmethod
    def _fragment_ref(operation_ref: str, index: int) -> str:
        material = hashlib.sha256(f"{operation_ref}|{index}".encode("utf-8")).hexdigest()[:24]
        return f"fragment.{index}.{material}"

    def _invalid_output(self, request: EngineTurnRequest, reason: str) -> EngineTurnResult:
        return self._terminal_result(
            request,
            TurnResultStatus.BLOCKED,
            _problem(ProblemCode.OUTPUT_INVALID, "验证 provider 输出", reason, "请检查 provider 连接器和固定输出合同后重试。"),
        )

    def _cancelled_result(self, request: EngineTurnRequest, reason: str) -> EngineTurnResult:
        return self._terminal_result(
            request,
            TurnResultStatus.CANCELLED,
            _problem(ProblemCode.CANCELLED, "生成普通回合正文", reason, "如仍需继续，请重新发起行动。"),
        )

    @staticmethod
    def _terminal_result(request: EngineTurnRequest, status: TurnResultStatus, problem: Problem) -> EngineTurnResult:
        return EngineTurnResult(
            STORY_ENGINE_PORT_VERSION,
            request.envelope.operation_ref,
            request.envelope.request_fingerprint,
            request.envelope.expected_revision,
            status,
            None,
            None,
            (),
            (),
            (),
            (),
            {"model_calls": 0},
            (),
            (),
            (problem,),
        )


__all__ = [
    "NARRATIVE_OPTIONAL_CAPABILITIES",
    "NARRATIVE_OUTPUT_CONTRACT",
    "NARRATIVE_PROVIDER_REQUIRED_CAPABILITIES",
    "NARRATIVE_REQUEST_CAPABILITIES",
    "NARRATIVE_REQUIRED_CAPABILITIES",
    "NarrativeArtifactIdentity",
    "NarrativeResolutionService",
]
