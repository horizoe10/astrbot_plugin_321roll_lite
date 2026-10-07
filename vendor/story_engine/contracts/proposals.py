"""Typed bounded proposals and stream closure contracts for every SE 1 Port method."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from .port import (
    EngineTurnResult, NarrativePolicyReceipt, NarrativePolicySnapshot, PortContractError,
    Problem, ProblemCode, _digest, _ref, _text, _time, canonical_fingerprint, freeze_json,
)


def _refs(values: tuple[str, ...], path: str) -> tuple[str, ...]:
    normalized = tuple(_ref(value, path) for value in values)
    if len(normalized) != len(set(normalized)):
        raise PortContractError(ProblemCode.INPUT_INVALID, path, "引用不能重复。")
    return normalized


@dataclass(frozen=True, slots=True)
class NarrativeBlockProposal:
    block_kind: str
    text: str

    def __post_init__(self) -> None:
        if self.block_kind not in {"paragraph", "dialogue", "heading", "aside"}:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "block_kind", "叙事块类型无效。")
        _text(self.text, "text", 20_000)


@dataclass(frozen=True, slots=True)
class NarrativeDocumentProposal:
    blocks: tuple[NarrativeBlockProposal, ...]
    fact_refs: tuple[str, ...]
    receipt_refs: tuple[str, ...]
    policy_fingerprint: str
    narrative_digest: str

    def __post_init__(self) -> None:
        if not self.blocks:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "blocks", "叙事提案不能为空。")
        object.__setattr__(self, "fact_refs", _refs(self.fact_refs, "fact_refs"))
        object.__setattr__(self, "receipt_refs", _refs(self.receipt_refs, "receipt_refs"))
        _digest(self.policy_fingerprint, "policy_fingerprint")
        expected = canonical_fingerprint({"blocks": [{"kind": item.block_kind, "text": item.text} for item in self.blocks], "fact_refs": self.fact_refs, "receipt_refs": self.receipt_refs, "policy_fingerprint": self.policy_fingerprint})
        if self.narrative_digest != expected:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "narrative_digest", "叙事摘要与正文不匹配。")


@dataclass(frozen=True, slots=True)
class NarrativeSummaryProposal:
    summary_purpose: str
    text: str
    min_chars: int
    max_chars: int
    source_narrative_digest: str
    retained_fact_refs: tuple[str, ...]
    retained_receipt_refs: tuple[str, ...]
    safety_warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ref(self.summary_purpose, "summary_purpose"); _digest(self.source_narrative_digest, "source_narrative_digest")
        _text(self.text, "summary.text", 20_000)
        if any(isinstance(value, bool) or value < 0 for value in (self.min_chars, self.max_chars)) or self.max_chars < self.min_chars:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "summary_chars", "摘要字符边界无效。")
        visible = len("".join(self.text.split()))
        if not self.min_chars <= visible <= self.max_chars:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "summary.text", "摘要超出字符边界。")
        object.__setattr__(self, "retained_fact_refs", _refs(self.retained_fact_refs, "retained_fact_refs"))
        object.__setattr__(self, "retained_receipt_refs", _refs(self.retained_receipt_refs, "retained_receipt_refs"))


class StreamKind(StrEnum):
    STORY_CHUNK = "story_chunk"
    PROGRESS = "progress"
    FINAL_RESULT = "final_result"
    TERMINAL_PROBLEM = "terminal_problem"


class StreamFinality(StrEnum):
    PROVISIONAL_STORY = "provisional_story"
    TRANSIENT = "transient"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class StoryChunk:
    fragment_ref: str
    block_kind: str
    text: str
    cumulative_digest: str

    def __post_init__(self) -> None:
        _ref(self.fragment_ref, "fragment_ref"); _digest(self.cumulative_digest, "cumulative_digest")
        NarrativeBlockProposal(self.block_kind, self.text)


@dataclass(frozen=True, slots=True)
class StreamProgress:
    stage: str
    started_at: str
    cancellable: bool
    active: bool
    measured_units: int | None = None

    def __post_init__(self) -> None:
        _ref(self.stage, "stage"); _time(self.started_at, "started_at")
        if self.measured_units is not None and (isinstance(self.measured_units, bool) or self.measured_units < 0):
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "measured_units", "进度单位无效。")


@dataclass(frozen=True, slots=True)
class StoryStreamEvent:
    contract_version: str
    operation_ref: str
    request_fingerprint: str
    expected_revision: int
    sequence: int
    kind: StreamKind
    finality: StreamFinality
    audience_hint: str
    emitted_at: str
    story_chunk: StoryChunk | None = None
    progress: StreamProgress | None = None
    final_result: EngineTurnResult | None = None
    terminal_problem: Problem | None = None
    last_valid_sequence: int | None = None

    def __post_init__(self) -> None:
        if self.contract_version != "story-stream/1.0.0":
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "contract_version", "流合同版本不兼容。")
        _ref(self.operation_ref, "operation_ref"); _digest(self.request_fingerprint, "request_fingerprint"); _ref(self.audience_hint, "audience_hint"); _time(self.emitted_at, "emitted_at")
        if any(isinstance(value, bool) or value < 1 for value in (self.sequence,)) or isinstance(self.expected_revision, bool) or self.expected_revision < 0:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "stream_sequence", "流序号或 revision 无效。")
        payloads = {StreamKind.STORY_CHUNK: self.story_chunk, StreamKind.PROGRESS: self.progress, StreamKind.FINAL_RESULT: self.final_result, StreamKind.TERMINAL_PROBLEM: self.terminal_problem}
        if payloads[self.kind] is None or sum(value is not None for value in payloads.values()) != 1:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "stream_payload", "流事件载荷与 kind 不匹配。")
        expected_finality = {StreamKind.STORY_CHUNK: StreamFinality.PROVISIONAL_STORY, StreamKind.PROGRESS: StreamFinality.TRANSIENT, StreamKind.FINAL_RESULT: StreamFinality.TERMINAL, StreamKind.TERMINAL_PROBLEM: StreamFinality.TERMINAL}[self.kind]
        if self.finality is not expected_finality:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "stream_finality", "流事件 finality 不匹配。")
        if self.kind is StreamKind.TERMINAL_PROBLEM and (self.last_valid_sequence is None or self.last_valid_sequence < 0 or self.last_valid_sequence >= self.sequence):
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "last_valid_sequence", "终止问题缺少合法末序号。")


class StreamAccumulator:
    """Deterministically validates sequence, cumulative digest and unique closure."""

    def __init__(self, operation_ref: str, request_fingerprint: str, expected_revision: int) -> None:
        self.operation_ref = _ref(operation_ref, "operation_ref")
        self.request_fingerprint = _digest(request_fingerprint, "request_fingerprint")
        self.expected_revision = expected_revision
        self.sequence = 0
        self.fragments: list[dict[str, str]] = []
        self.terminal = False

    def accept(self, event: StoryStreamEvent) -> None:
        if self.terminal:
            raise PortContractError(ProblemCode.RESULT_STALE, "stream", "流已收束。")
        if (event.operation_ref, event.request_fingerprint, event.expected_revision) != (self.operation_ref, self.request_fingerprint, self.expected_revision):
            raise PortContractError(ProblemCode.RESULT_STALE, "stream_envelope", "流事件不属于当前冻结请求。")
        if event.sequence != self.sequence + 1:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "sequence", "流事件序号不连续。")
        if event.story_chunk is not None:
            self.fragments.append({"kind": event.story_chunk.block_kind, "text": event.story_chunk.text})
            expected = canonical_fingerprint({"fragments": self.fragments})
            if event.story_chunk.cumulative_digest != expected:
                self.fragments.pop()
                raise PortContractError(ProblemCode.OUTPUT_INVALID, "cumulative_digest", "流累计摘要不匹配。")
        if event.final_result is not None and (event.final_result.operation_ref, event.final_result.request_fingerprint, event.final_result.expected_revision) != (self.operation_ref, self.request_fingerprint, self.expected_revision):
            raise PortContractError(ProblemCode.RESULT_STALE, "final_result", "最终结果不属于当前冻结请求。")
        self.sequence = event.sequence
        self.terminal = event.finality is StreamFinality.TERMINAL


@dataclass(frozen=True, slots=True)
class ParagraphRewriteRequest:
    operation_ref: str
    request_fingerprint: str
    expected_revision: int
    paragraph_ref: str
    canonical_text: str
    committed_corrections: tuple[Mapping[str, Any], ...]
    narrative_policy: NarrativePolicySnapshot
    safety_boundaries: tuple[str, ...]
    deadline_at: str

    def __post_init__(self) -> None:
        _ref(self.operation_ref, "operation_ref"); _digest(self.request_fingerprint, "request_fingerprint"); _ref(self.paragraph_ref, "paragraph_ref"); _text(self.canonical_text, "canonical_text", 20_000); _time(self.deadline_at, "deadline_at")
        if not self.committed_corrections or not self.safety_boundaries:
            raise PortContractError(ProblemCode.INPUT_INVALID, "rewrite", "重写必须包含已提交纠错和安全边界。")
        if isinstance(self.expected_revision, bool) or self.expected_revision < 0:
            raise PortContractError(ProblemCode.INPUT_INVALID, "expected_revision", "重写 revision 无效。")
        object.__setattr__(self, "committed_corrections", tuple(freeze_json(item, "committed_corrections") for item in self.committed_corrections))


@dataclass(frozen=True, slots=True)
class ParagraphRewriteResult:
    operation_ref: str
    request_fingerprint: str
    expected_revision: int
    paragraph_ref: str
    replacement_text: str
    supersedes_digest: str
    policy_receipt: NarrativePolicyReceipt
    visible_chars: int
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ref(self.operation_ref, "operation_ref"); _digest(self.request_fingerprint, "request_fingerprint"); _ref(self.paragraph_ref, "paragraph_ref"); _text(self.replacement_text, "replacement_text", 20_000); _digest(self.supersedes_digest, "supersedes_digest")
        if isinstance(self.expected_revision, bool) or self.expected_revision < 0 or self.visible_chars != len("".join(self.replacement_text.split())):
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "visible_chars", "替换段字符数不匹配。")


@dataclass(frozen=True, slots=True)
class CompanionMemoryEvent:
    event_ref: str
    receipt_ref: str
    revision: int
    visibility: str
    committed_fact: str

    def __post_init__(self) -> None:
        _ref(self.event_ref, "event_ref"); _ref(self.receipt_ref, "receipt_ref"); _ref(self.visibility, "visibility"); _text(self.committed_fact, "committed_fact", 4096)
        if isinstance(self.revision, bool) or self.revision < 0:
            raise PortContractError(ProblemCode.INPUT_INVALID, "revision", "记忆事件 revision 无效。")


@dataclass(frozen=True, slots=True)
class CompanionMemorySummaryRequest:
    operation_ref: str
    request_fingerprint: str
    actor_ref: str
    actor_revision: int
    audience: str
    events: tuple[CompanionMemoryEvent, ...]
    min_chars: int
    max_chars: int
    deadline_at: str

    def __post_init__(self) -> None:
        _ref(self.operation_ref, "operation_ref"); _digest(self.request_fingerprint, "request_fingerprint"); _ref(self.actor_ref, "actor_ref"); _ref(self.audience, "audience"); _time(self.deadline_at, "deadline_at")
        if not self.events or any(isinstance(value, bool) or value < 0 for value in (self.actor_revision, self.min_chars, self.max_chars)) or self.max_chars < self.min_chars:
            raise PortContractError(ProblemCode.INPUT_INVALID, "memory_summary", "记忆来源或字符边界无效。")


@dataclass(frozen=True, slots=True)
class CompanionMemorySummaryResult:
    operation_ref: str
    request_fingerprint: str
    actor_ref: str
    actor_revision: int
    summary: str
    source_event_refs: tuple[str, ...]
    source_receipt_refs: tuple[str, ...]
    visibility: str
    result_fingerprint: str

    def __post_init__(self) -> None:
        _ref(self.operation_ref, "operation_ref"); _digest(self.request_fingerprint, "request_fingerprint"); _ref(self.actor_ref, "actor_ref"); _text(self.summary, "summary", 10_000); _ref(self.visibility, "visibility"); _digest(self.result_fingerprint, "result_fingerprint")
        if isinstance(self.actor_revision, bool) or self.actor_revision < 0:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "actor_revision", "记忆结果 revision 无效。")
        object.__setattr__(self, "source_event_refs", _refs(self.source_event_refs, "source_event_refs")); object.__setattr__(self, "source_receipt_refs", _refs(self.source_receipt_refs, "source_receipt_refs"))


class CompanionIntentType(StrEnum):
    CHOOSE = "choose"; FREE_ACTION = "free_action"; ASSIST = "assist"; USE_ITEM = "use_item"; VOTE = "vote"; SPEAK = "speak"; WAIT = "wait"


@dataclass(frozen=True, slots=True)
class CompanionIntent:
    intent_type: CompanionIntentType
    actor_ref: str
    candidate_ref: str | None
    public_reason: str
    speech: str | None
    confidence: float
    risk_acknowledged: bool
    goal_refs: tuple[str, ...] = ()
    memory_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ref(self.actor_ref, "actor_ref"); _text(self.public_reason, "public_reason", 1024)
        if self.candidate_ref is not None: _ref(self.candidate_ref, "candidate_ref")
        if self.speech is not None: _text(self.speech, "speech", 1024)
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 1:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "confidence", "置信度必须在 0 到 1。")
        object.__setattr__(self, "goal_refs", _refs(self.goal_refs, "goal_refs")); object.__setattr__(self, "memory_refs", _refs(self.memory_refs, "memory_refs"))


@dataclass(frozen=True, slots=True)
class CompanionDecisionRequest:
    operation_ref: str
    request_fingerprint: str
    expected_revision: int
    actor_ref: str
    actor_revision: int
    control_mode: str
    control_mode_revision: int
    actor_snapshot: Mapping[str, Any]
    known_facts: tuple[str, ...]
    legal_candidate_refs: tuple[str, ...]
    goal_refs: tuple[str, ...]
    memory_refs: tuple[str, ...]
    deadline_at: str

    def __post_init__(self) -> None:
        _ref(self.operation_ref, "operation_ref"); _digest(self.request_fingerprint, "request_fingerprint"); _ref(self.actor_ref, "actor_ref"); _time(self.deadline_at, "deadline_at")
        if self.control_mode not in {"automatic", "confirm", "paused"} or not self.legal_candidate_refs or any(isinstance(value, bool) or value < 0 for value in (self.expected_revision, self.actor_revision, self.control_mode_revision)):
            raise PortContractError(ProblemCode.INPUT_INVALID, "companion_decision", "控制模式或合法候选无效。")
        object.__setattr__(self, "known_facts", tuple(_text(item, "known_facts", 4096) for item in self.known_facts)); object.__setattr__(self, "actor_snapshot", freeze_json(self.actor_snapshot, "actor_snapshot")); object.__setattr__(self, "legal_candidate_refs", _refs(self.legal_candidate_refs, "legal_candidate_refs")); object.__setattr__(self, "goal_refs", _refs(self.goal_refs, "goal_refs")); object.__setattr__(self, "memory_refs", _refs(self.memory_refs, "memory_refs"))


@dataclass(frozen=True, slots=True)
class CompanionDecisionResult:
    operation_ref: str
    request_fingerprint: str
    expected_revision: int
    control_mode_revision: int
    primary_intent: CompanionIntent
    alternatives: tuple[CompanionIntent, ...]
    warnings: tuple[str, ...]
    result_fingerprint: str

    def __post_init__(self) -> None:
        _ref(self.operation_ref, "operation_ref"); _digest(self.request_fingerprint, "request_fingerprint"); _digest(self.result_fingerprint, "result_fingerprint")
        if len(self.alternatives) > 2 or any(isinstance(value, bool) or value < 0 for value in (self.expected_revision, self.control_mode_revision)):
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "alternatives", "伙伴备选意图最多两个。")


@dataclass(frozen=True, slots=True)
class EventProjectionRequest:
    operation_ref: str
    request_fingerprint: str
    expected_revision: int
    event_snapshot_fingerprint: str
    audience_hint: str
    source_refs: tuple[str, ...]
    projection_policy: Mapping[str, Any]
    deadline_at: str

    def __post_init__(self) -> None:
        _ref(self.operation_ref, "operation_ref"); _digest(self.request_fingerprint, "request_fingerprint")
        _digest(self.event_snapshot_fingerprint, "event_snapshot_fingerprint"); _ref(self.audience_hint, "audience_hint"); _time(self.deadline_at, "deadline_at")
        if isinstance(self.expected_revision, bool) or self.expected_revision < 0:
            raise PortContractError(ProblemCode.INPUT_INVALID, "expected_revision", "投影请求 revision 无效。")
        object.__setattr__(self, "source_refs", _refs(self.source_refs, "source_refs"))
        object.__setattr__(self, "projection_policy", freeze_json(self.projection_policy, "projection_policy"))


@dataclass(frozen=True, slots=True)
class EventProjectionFragment:
    schema: str
    fragment_kind: str
    audience_hint: str
    title: str
    body: tuple[str, ...]
    semantic_items: tuple[Mapping[str, Any], ...]
    available_action_semantics: tuple[Mapping[str, Any], ...]
    source_refs: tuple[str, ...]
    redaction_hints: tuple[str, ...]
    freshness_fingerprint: str

    def __post_init__(self) -> None:
        if self.schema != "se-event-projection-fragment/1.0.0":
            raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "schema", "投影片段版本不兼容。")
        _ref(self.fragment_kind, "fragment_kind"); _ref(self.audience_hint, "audience_hint"); _text(self.title, "title", 256); _digest(self.freshness_fingerprint, "freshness_fingerprint")
        if not self.body: raise PortContractError(ProblemCode.OUTPUT_INVALID, "body", "投影片段正文不能为空。")
        object.__setattr__(self, "body", tuple(_text(item, "body", 4096) for item in self.body))
        object.__setattr__(self, "semantic_items", tuple(freeze_json(item, "semantic_items") for item in self.semantic_items)); object.__setattr__(self, "available_action_semantics", tuple(freeze_json(item, "available_action_semantics") for item in self.available_action_semantics)); object.__setattr__(self, "source_refs", _refs(self.source_refs, "source_refs"))


def validate_narrative_summary(document: NarrativeDocumentProposal, summary: NarrativeSummaryProposal) -> None:
    if summary.source_narrative_digest != document.narrative_digest:
        raise PortContractError(ProblemCode.RESULT_STALE, "source_narrative_digest", "摘要不属于当前叙事提案。")
    if not set(summary.retained_fact_refs) <= set(document.fact_refs) or not set(summary.retained_receipt_refs) <= set(document.receipt_refs):
        raise PortContractError(ProblemCode.SEMANTIC_VALIDATION_FAILED, "summary.refs", "摘要引入了正文之外的事实或回执。")


def validate_paragraph_rewrite(request: ParagraphRewriteRequest, result: ParagraphRewriteResult) -> None:
    if (result.operation_ref, result.request_fingerprint, result.expected_revision, result.paragraph_ref) != (request.operation_ref, request.request_fingerprint, request.expected_revision, request.paragraph_ref):
        raise PortContractError(ProblemCode.RESULT_STALE, "rewrite_result", "段落重写结果不属于当前冻结请求。")
    expected = canonical_fingerprint({"paragraph_ref": request.paragraph_ref, "canonical_text": request.canonical_text})
    if result.supersedes_digest != expected or result.replacement_text == request.canonical_text:
        raise PortContractError(ProblemCode.SEMANTIC_VALIDATION_FAILED, "rewrite_result", "替换段未正确绑定原段或没有产生变化。")


def validate_memory_summary(request: CompanionMemorySummaryRequest, result: CompanionMemorySummaryResult) -> None:
    if (result.operation_ref, result.request_fingerprint, result.actor_ref, result.actor_revision) != (request.operation_ref, request.request_fingerprint, request.actor_ref, request.actor_revision):
        raise PortContractError(ProblemCode.RESULT_STALE, "memory_result", "记忆摘要不属于当前角色快照。")
    event_refs = {item.event_ref for item in request.events}; receipt_refs = {item.receipt_ref for item in request.events}
    if not set(result.source_event_refs) <= event_refs or not set(result.source_receipt_refs) <= receipt_refs:
        raise PortContractError(ProblemCode.SEMANTIC_VALIDATION_FAILED, "memory_result.refs", "记忆摘要引用了未提交来源。")
    visible = len("".join(result.summary.split()))
    if result.visibility != request.audience or not request.min_chars <= visible <= request.max_chars:
        raise PortContractError(ProblemCode.SEMANTIC_VALIDATION_FAILED, "memory_result.visibility", "记忆摘要可见性或字符边界不匹配。")
    expected = canonical_fingerprint({"actor_ref": result.actor_ref, "actor_revision": result.actor_revision, "summary": result.summary, "source_event_refs": result.source_event_refs, "source_receipt_refs": result.source_receipt_refs, "visibility": result.visibility})
    if result.result_fingerprint != expected:
        raise PortContractError(ProblemCode.OUTPUT_INVALID, "result_fingerprint", "记忆摘要指纹不匹配。")


def _intent_material(intent: CompanionIntent) -> dict[str, Any]:
    return {"intent_type": intent.intent_type.value, "actor_ref": intent.actor_ref, "candidate_ref": intent.candidate_ref, "public_reason": intent.public_reason, "speech": intent.speech, "confidence": intent.confidence, "risk_acknowledged": intent.risk_acknowledged, "goal_refs": intent.goal_refs, "memory_refs": intent.memory_refs}


def validate_companion_decision(request: CompanionDecisionRequest, result: CompanionDecisionResult) -> None:
    if (result.operation_ref, result.request_fingerprint, result.expected_revision, result.control_mode_revision) != (request.operation_ref, request.request_fingerprint, request.expected_revision, request.control_mode_revision):
        raise PortContractError(ProblemCode.RESULT_STALE, "companion_result", "伙伴意图不属于当前控制快照。")
    allowed_candidates, allowed_goals, allowed_memories = set(request.legal_candidate_refs), set(request.goal_refs), set(request.memory_refs)
    intents = (result.primary_intent,) + result.alternatives
    for intent in intents:
        if intent.actor_ref != request.actor_ref or (intent.candidate_ref is not None and intent.candidate_ref not in allowed_candidates) or not set(intent.goal_refs) <= allowed_goals or not set(intent.memory_refs) <= allowed_memories:
            raise PortContractError(ProblemCode.SEMANTIC_VALIDATION_FAILED, "companion_intent.refs", "伙伴意图使用了请求之外的引用。")
    expected = canonical_fingerprint({"operation_ref": result.operation_ref, "request_fingerprint": result.request_fingerprint, "expected_revision": result.expected_revision, "control_mode_revision": result.control_mode_revision, "primary_intent": _intent_material(result.primary_intent), "alternatives": [_intent_material(item) for item in result.alternatives], "warnings": result.warnings})
    if result.result_fingerprint != expected:
        raise PortContractError(ProblemCode.OUTPUT_INVALID, "result_fingerprint", "伙伴意图指纹不匹配。")


__all__ = [name for name in globals() if name in {
    "CompanionDecisionRequest", "CompanionDecisionResult", "CompanionIntent", "CompanionIntentType",
    "CompanionMemoryEvent", "CompanionMemorySummaryRequest", "CompanionMemorySummaryResult",
    "EventProjectionFragment", "EventProjectionRequest", "NarrativeBlockProposal", "NarrativeDocumentProposal",
    "NarrativeSummaryProposal", "ParagraphRewriteRequest", "ParagraphRewriteResult",
    "StoryChunk", "StoryStreamEvent", "StreamAccumulator", "StreamFinality", "StreamKind", "StreamProgress",
    "validate_companion_decision", "validate_memory_summary", "validate_narrative_summary", "validate_paragraph_rewrite",
}]
