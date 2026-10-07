"""System-neutral resolution-check author, IR, and proposal-only runtime."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol

from .contracts.port import CancellationCheck, OperationEnvelope, PlatformBridge, PortContractError, Problem, ProblemCode, canonical_fingerprint, freeze_json

RESOLUTION_CHECK_CAPABILITY = "resolution.check/1.0.0"
RESOLUTION_CHECK_AUTHOR_SCHEMA = "se-resolution-check-definitions/1.0.0"
RESOLUTION_CHECK_SNAPSHOT_SCHEMA = "se-resolution-check-snapshot/1.0.0"
RESOLUTION_CHECK_RECEIPT_SCHEMA = "se-resolution-check-rule-receipt/1.0.0"
RESOLUTION_CHECK_REQUEST_SCHEMA = "se-resolution-check-evaluation/1.0.0"
RESOLUTION_CHECK_PROPOSAL_SCHEMA = "se-resolution-check-proposal/1.0.0"
RESOLUTION_CHECK_RESULT_SCHEMA = "se-resolution-check-result/1.0.0"

_DEFINITION_FIELDS = frozenset({
    "definition_ref", "check_kind", "rule_ref", "difficulty", "actor_inputs", "modifier_policy",
    "assist_policy", "retry_policy", "opposed_policy", "seed_policy", "result_bands",
    "no_roll_policy", "fallback_policy",
})
_DIFFICULTY_SOURCES = frozenset({"fixed", "platform_snapshot", "host_confirm"})
_CHECK_KINDS = frozenset({"ability", "skill", "tool", "combined", "opposed"})
_DEFINITION_IR_FIELDS = frozenset({"schema", "definition_ref", "check_kind", "rule_ref", "difficulty", "actor_inputs", "modifier_policy", "assist_policy", "retry_policy", "opposed_policy", "seed_policy", "result_bands", "no_roll_policy", "fallback_policy", "definition_sha256"})
_BINDING_IR_FIELDS = frozenset({"schema", "definition_ref", "definition_sha256"})


@dataclass(frozen=True, slots=True)
class ResolutionCheckContractError(ValueError):
    code: str
    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.code}:{self.path}"


def _fail(code: str, path: str, reason: str) -> None:
    raise ResolutionCheckContractError(code, path, reason)


def _text(value: object, path: str, maximum: int = 600) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _fail("resolution.text_invalid", path, "字段必须是有界非空文本。")
    return value.strip()


def _ref(value: object, path: str) -> str:
    result = _text(value, path, 128)
    if not result[0].isalnum() or any(not (char.isalnum() or char in "_.:@-") for char in result):
        _fail("resolution.reference_invalid", path, "字段必须是稳定引用。")
    return result


def _hash(value: object, path: str) -> str:
    result = _text(value, path, 71)
    if len(result) != 71 or not result.startswith("sha256:") or any(char not in "0123456789abcdef" for char in result[7:]):
        _fail("resolution.hash_invalid", path, "字段必须是小写 SHA-256 identity。")
    return result


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("resolution.object_invalid", path, "字段必须是对象。")
    return value


def _sequence(value: object, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("resolution.sequence_invalid", path, "字段必须是列表。")
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping): return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)): return [_plain(item) for item in value]
    return value


def compile_resolution_check_definitions(document: Mapping[str, Any]) -> dict[str, Any]:
    if set(document) != {"schema", "definitions"} or document.get("schema") != RESOLUTION_CHECK_AUTHOR_SCHEMA:
        _fail("resolution.document_incompatible", "$", "检定定义文档版本或字段不兼容。")
    definitions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(_sequence(document["definitions"], "definitions")):
        path = f"definitions[{index}]"; value = _mapping(raw, path)
        if set(value) != _DEFINITION_FIELDS: _fail("resolution.definition_fields_invalid", path, "检定定义字段不完整或未知。")
        definition_ref = _ref(value["definition_ref"], f"{path}.definition_ref")
        if definition_ref in seen: _fail("resolution.definition_duplicate", f"{path}.definition_ref", "definition_ref 重复。")
        seen.add(definition_ref)
        kind = str(value["check_kind"])
        if kind not in _CHECK_KINDS: _fail("resolution.check_kind_invalid", f"{path}.check_kind", "检定 kind 未注册。")
        difficulty = _mapping(value["difficulty"], f"{path}.difficulty")
        if set(difficulty) != {"source", "fixed_rating", "public_label"} or difficulty["source"] not in _DIFFICULTY_SOURCES:
            _fail("resolution.difficulty_invalid", f"{path}.difficulty", "difficulty 必须冻结 source/fixed_rating/public_label。")
        rating = difficulty["fixed_rating"]
        if difficulty["source"] == "fixed":
            if isinstance(rating, bool) or not isinstance(rating, int) or not 0 <= rating <= 100: _fail("resolution.difficulty_invalid", f"{path}.difficulty.fixed_rating", "固定难度必须为0..100。")
        elif rating is not None: _fail("resolution.difficulty_invalid", f"{path}.difficulty.fixed_rating", "非固定难度不得预填 rating。")
        actor_inputs = _mapping(value["actor_inputs"], f"{path}.actor_inputs")
        if set(actor_inputs) != {"ability_refs", "skill_refs", "tool_refs", "require_actor"} or actor_inputs["require_actor"] is not True:
            _fail("resolution.actor_inputs_invalid", f"{path}.actor_inputs", "actor 输入必须冻结 ability/skill/tool refs 且要求 actor。")
        normalized_inputs = {}
        for field in ("ability_refs", "skill_refs", "tool_refs"):
            refs = tuple(_ref(item, f"{path}.actor_inputs.{field}") for item in _sequence(actor_inputs[field], f"{path}.actor_inputs.{field}"))
            if len(refs) != len(set(refs)): _fail("resolution.actor_input_duplicate", f"{path}.actor_inputs.{field}", "actor 输入引用不能重复。")
            normalized_inputs[field] = list(refs)
        if not any(normalized_inputs.values()): _fail("resolution.actor_inputs_empty", f"{path}.actor_inputs", "检定至少允许 ability/skill/tool 之一。")
        populated = {field for field, refs in normalized_inputs.items() if refs}
        expected_by_kind = {"ability": {"ability_refs"}, "skill": {"skill_refs"}, "tool": {"tool_refs"}}
        if kind in expected_by_kind and populated != expected_by_kind[kind]:
            _fail("resolution.check_kind_inputs_invalid", f"{path}.actor_inputs", "单一 check kind 必须且只能声明同类 actor 输入。")
        if kind == "combined" and len(populated) < 2:
            _fail("resolution.check_kind_inputs_invalid", f"{path}.actor_inputs", "combined 检定必须声明至少两类 actor 输入。")
        modifier = _mapping(value["modifier_policy"], f"{path}.modifier_policy")
        if set(modifier) != {"allow_advantage", "allow_disadvantage", "stacking", "maximum_receipts"} or modifier["stacking"] != "cancel_each_other":
            _fail("resolution.modifier_policy_invalid", f"{path}.modifier_policy", "修正政策必须冻结 advantage/disadvantage 与 cancel_each_other。")
        if not isinstance(modifier["allow_advantage"], bool) or not isinstance(modifier["allow_disadvantage"], bool) or isinstance(modifier["maximum_receipts"], bool) or not isinstance(modifier["maximum_receipts"], int) or not 0 <= modifier["maximum_receipts"] <= 32:
            _fail("resolution.modifier_policy_invalid", f"{path}.modifier_policy", "修正政策值无效。")
        assist = _mapping(value["assist_policy"], f"{path}.assist_policy")
        if set(assist) != {"allowed", "maximum_assists"} or not isinstance(assist["allowed"], bool) or isinstance(assist["maximum_assists"], bool) or not isinstance(assist["maximum_assists"], int) or not 0 <= assist["maximum_assists"] <= 16 or (not assist["allowed"] and assist["maximum_assists"] != 0):
            _fail("resolution.assist_policy_invalid", f"{path}.assist_policy", "协助政策字段或上限无效。")
        retry = _mapping(value["retry_policy"], f"{path}.retry_policy")
        if set(retry) != {"allowed", "maximum_retries", "cost_required"} or not isinstance(retry["allowed"], bool) or not isinstance(retry["cost_required"], bool) or isinstance(retry["maximum_retries"], bool) or not isinstance(retry["maximum_retries"], int) or not 0 <= retry["maximum_retries"] <= 16 or (not retry["allowed"] and retry["maximum_retries"] != 0):
            _fail("resolution.retry_policy_invalid", f"{path}.retry_policy", "重试政策字段或上限无效。")
        opposed = _mapping(value["opposed_policy"], f"{path}.opposed_policy")
        if set(opposed) != {"allowed", "target_snapshot_required"} or not isinstance(opposed["allowed"], bool) or not isinstance(opposed["target_snapshot_required"], bool) or opposed["allowed"] != (kind == "opposed") or opposed["target_snapshot_required"] != (kind == "opposed"):
            _fail("resolution.opposed_policy_invalid", f"{path}.opposed_policy", "对抗政策必须与 opposed check kind 一致。")
        if value["seed_policy"] != "platform_provided": _fail("resolution.seed_policy_invalid", f"{path}.seed_policy", "随机 seed 只能由平台提供。")
        bands = []
        for band_index, band_raw in enumerate(_sequence(value["result_bands"], f"{path}.result_bands")):
            band = _mapping(band_raw, f"{path}.result_bands[{band_index}]")
            if set(band) != {"outcome", "degree", "public_label"} or band["outcome"] not in {"success", "failure"}:
                _fail("resolution.result_band_invalid", f"{path}.result_bands[{band_index}]", "结果带必须冻结 success/failure、degree 和公开标签。")
            bands.append({"outcome": band["outcome"], "degree": _ref(band["degree"], "degree"), "public_label": _text(band["public_label"], "public_label", 160)})
        if {item["outcome"] for item in bands} != {"success", "failure"} or len({item["degree"] for item in bands}) != len(bands):
            _fail("resolution.result_bands_incomplete", f"{path}.result_bands", "结果带必须同时包含 success/failure 且 degree 唯一。")
        if value["no_roll_policy"] not in {"allow_preview_only", "block"} or value["fallback_policy"] not in {"no_roll", "host_confirm", "block"}:
            _fail("resolution.fallback_policy_invalid", path, "no-roll/fallback 政策无效。")
        material = {
            "schema": "se-resolution-check-definition-ir/1.0.0", "definition_ref": definition_ref,
            "check_kind": kind, "rule_ref": _ref(value["rule_ref"], f"{path}.rule_ref"),
            "difficulty": {"source": difficulty["source"], "fixed_rating": rating, "public_label": _text(difficulty["public_label"], f"{path}.difficulty.public_label", 160)},
            "actor_inputs": {**normalized_inputs, "require_actor": True}, "modifier_policy": _plain(modifier),
            "assist_policy": _plain(assist), "retry_policy": _plain(retry),
            "opposed_policy": _plain(opposed), "seed_policy": "platform_provided",
            "result_bands": bands, "no_roll_policy": value["no_roll_policy"], "fallback_policy": value["fallback_policy"],
        }
        material["definition_sha256"] = canonical_fingerprint(material); definitions.append(material)
    catalog = {"schema": "se-resolution-check-catalog-ir/1.0.0", "definitions": sorted(definitions, key=lambda item: item["definition_ref"])}
    catalog["catalog_sha256"] = canonical_fingerprint(catalog); return catalog


def bind_resolution_check(extension: Mapping[str, Any], catalog: Mapping[str, Any], *, choice_refs=()) -> dict[str, Any]:
    if set(extension) not in ({"definition_ref"}, {"definition_ref", "choice_definitions"}): _fail("resolution.extension_invalid", "extensions.resolution.check/1.0.0", "扩展需要默认定义及可选的逐行动定义绑定。")
    ref = _ref(extension["definition_ref"], "extensions.resolution.check/1.0.0.definition_ref")
    definition = next((item for item in catalog["definitions"] if item["definition_ref"] == ref), None)
    if definition is None: _fail("resolution.definition_unknown", "extensions.resolution.check/1.0.0.definition_ref", "事件引用未知检定定义。")
    binding = {"schema": "se-resolution-check-binding-ir/1.0.0", "definition_ref": ref, "definition_sha256": definition["definition_sha256"]}
    if 'choice_definitions' in extension:
        choices = extension['choice_definitions']
        if not isinstance(choices, Mapping) or not choices or not set(choices) <= set(choice_refs):
            _fail('resolution.extension_invalid', 'choice_definitions', '逐行动绑定必须引用本事件存在的选项。')
        resolved = {}
        for choice, choice_ref in choices.items():
            selected = next((item for item in catalog['definitions'] if item['definition_ref'] == choice_ref), None)
            if selected is None:
                _fail('resolution.definition_unknown', 'choice_definitions', '行动引用未知检定定义。')
            resolved[choice] = {'definition_ref': choice_ref, 'definition_sha256': selected['definition_sha256']}
        binding['choice_definitions'] = resolved
    return binding


@dataclass(frozen=True, slots=True)
class ResolutionCheckSnapshot:
    schema: str; check_revision: int; definition_ref: str; definition_sha256: str; actor_ref: str; target_ref: str | None
    target_snapshot_sha256: str | None
    ability_ref: str | None; skill_ref: str | None; tool_ref: str | None; difficulty_rating: int | None
    difficulty_receipt_ref: str | None; difficulty_receipt_sha256: str | None
    host_confirmation_receipt_ref: str | None; host_confirmation_receipt_sha256: str | None; advantage_state: str
    modifier_receipt_refs: tuple[str, ...]; assist_actor_refs: tuple[str, ...]; assist_receipt_refs: tuple[str, ...]
    retry_count: int; retry_cost_receipt_ref: str | None; retry_cost_receipt_sha256: str | None
    seed_ref: str | None; rule_revision: int
    expected_session_revision: int; rule_capability_available: bool; fingerprint: str

    def __post_init__(self) -> None:
        if self.schema != RESOLUTION_CHECK_SNAPSHOT_SCHEMA or self.advantage_state not in {"none", "advantage", "disadvantage"}: raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "resolution_snapshot", "检定快照版本或优势状态无效。")
        _hash(self.definition_sha256, "definition_sha256"); _hash(self.fingerprint, "fingerprint")
        for name in ("definition_ref", "actor_ref"): _ref(getattr(self, name), name)
        for name in ("target_ref", "ability_ref", "skill_ref", "tool_ref", "difficulty_receipt_ref", "host_confirmation_receipt_ref", "seed_ref"):
            if getattr(self, name) is not None: _ref(getattr(self, name), name)
        for name in ("target_snapshot_sha256", "difficulty_receipt_sha256", "host_confirmation_receipt_sha256", "retry_cost_receipt_sha256"):
            if getattr(self, name) is not None: _hash(getattr(self, name), name)
        if (self.target_ref is None) != (self.target_snapshot_sha256 is None) or (self.difficulty_receipt_ref is None) != (self.difficulty_receipt_sha256 is None) or (self.host_confirmation_receipt_ref is None) != (self.host_confirmation_receipt_sha256 is None) or (self.retry_cost_receipt_ref is None) != (self.retry_cost_receipt_sha256 is None):
            raise PortContractError(ProblemCode.INPUT_INVALID, "difficulty_receipt", "difficulty/host receipt ref 与 SHA-256 必须成对出现。")
        if self.retry_cost_receipt_ref is not None: _ref(self.retry_cost_receipt_ref, "retry_cost_receipt_ref")
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in (self.check_revision, self.rule_revision, self.expected_session_revision, self.retry_count)): raise PortContractError(ProblemCode.INPUT_INVALID, "revision", "检定 revision/retry_count 无效。")
        if self.difficulty_rating is not None and (isinstance(self.difficulty_rating, bool) or not isinstance(self.difficulty_rating, int) or not 0 <= self.difficulty_rating <= 100): raise PortContractError(ProblemCode.INPUT_INVALID, "difficulty_rating", "难度必须是 0..100 的整数。")
        if not any((self.ability_ref, self.skill_ref, self.tool_ref)): raise PortContractError(ProblemCode.INPUT_INVALID, "actor_inputs", "检定缺少 actor ability/skill/tool 输入。")
        if not isinstance(self.rule_capability_available, bool) or not all(isinstance(items, tuple) for items in (self.modifier_receipt_refs, self.assist_actor_refs, self.assist_receipt_refs)) or len(self.modifier_receipt_refs) != len(set(self.modifier_receipt_refs)) or len(self.assist_actor_refs) != len(set(self.assist_actor_refs)) or len(self.assist_receipt_refs) != len(set(self.assist_receipt_refs)) or len(self.assist_actor_refs) != len(self.assist_receipt_refs):
            raise PortContractError(ProblemCode.INPUT_INVALID, "resolution_snapshot", "规则能力状态必须为布尔值且 modifier receipts 不得重复。")
        for collection, path in ((self.modifier_receipt_refs, "modifier_receipt_refs"), (self.assist_actor_refs, "assist_actor_refs"), (self.assist_receipt_refs, "assist_receipt_refs")):
            for item in collection: _ref(item, path)

    def to_mapping(self) -> dict[str, Any]: return {name: (list(getattr(self, name)) if name in {"modifier_receipt_refs", "assist_actor_refs", "assist_receipt_refs"} else getattr(self, name)) for name in self.__dataclass_fields__}
    def fingerprint_material(self): return {key: value for key, value in self.to_mapping().items() if key != "fingerprint"}


def resolution_snapshot_fingerprint(snapshot: ResolutionCheckSnapshot) -> str: return canonical_fingerprint(snapshot.fingerprint_material())


@dataclass(frozen=True, slots=True)
class RuleResolutionReceipt:
    schema: str; receipt_ref: str; definition_ref: str; definition_sha256: str; seed_ref: str
    rule_revision: int; outcome: str; degree: str; total: int; fingerprint: str

    def __post_init__(self) -> None:
        if self.schema != RESOLUTION_CHECK_RECEIPT_SCHEMA or self.outcome not in {"success", "failure"}: raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "rule_receipt", "规则回执版本或 outcome 无效。")
        for name in ("receipt_ref", "definition_ref", "seed_ref", "degree"): _ref(getattr(self, name), name)
        _hash(self.definition_sha256, "definition_sha256"); _hash(self.fingerprint, "fingerprint")
        if isinstance(self.rule_revision, bool) or not isinstance(self.rule_revision, int) or self.rule_revision < 0 or isinstance(self.total, bool) or not isinstance(self.total, int): raise PortContractError(ProblemCode.INPUT_INVALID, "rule_receipt", "规则回执数值无效。")

    def fingerprint_material(self): return {name: getattr(self, name) for name in self.__dataclass_fields__ if name != "fingerprint"}


def rule_receipt_fingerprint(receipt: RuleResolutionReceipt) -> str: return canonical_fingerprint(receipt.fingerprint_material())


class ResolutionAction(StrEnum): PREVIEW = "preview"; PREPARE_ROLL = "prepare_roll"; INTERPRET_RECEIPT = "interpret_receipt"


@dataclass(frozen=True, slots=True)
class ResolutionCheckRequest:
    schema: str; envelope: OperationEnvelope; action: ResolutionAction; snapshot: ResolutionCheckSnapshot; rule_receipt: RuleResolutionReceipt | None = None
    def __post_init__(self):
        if self.schema != RESOLUTION_CHECK_REQUEST_SCHEMA or self.envelope.operation_type != "evaluate_resolution_check" or not isinstance(self.action, ResolutionAction): raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "resolution_request", "检定请求版本、动作或操作无效。")
        if self.envelope.expected_revision != self.snapshot.expected_session_revision: raise PortContractError(ProblemCode.RESULT_STALE, "expected_revision", "session revision 已过期。")
        if self.action is ResolutionAction.INTERPRET_RECEIPT and self.rule_receipt is None: raise PortContractError(ProblemCode.INPUT_INVALID, "rule_receipt", "解释结果必须提供平台规则回执。")
        if self.action is not ResolutionAction.INTERPRET_RECEIPT and self.rule_receipt is not None: raise PortContractError(ProblemCode.INPUT_INVALID, "rule_receipt", "只有解释动作可以携带平台规则回执。")


def resolution_request_fingerprint(request: ResolutionCheckRequest) -> str:
    envelope = {name: getattr(request.envelope, name) for name in request.envelope.__dataclass_fields__ if name != "request_fingerprint"}
    return canonical_fingerprint({"schema": request.schema, "envelope": envelope, "action": request.action.value, "snapshot_fingerprint": request.snapshot.fingerprint, "receipt_fingerprint": None if request.rule_receipt is None else request.rule_receipt.fingerprint})


_SNAPSHOT_FIELDS = frozenset(ResolutionCheckSnapshot.__dataclass_fields__)
_RECEIPT_FIELDS = frozenset(RuleResolutionReceipt.__dataclass_fields__)


def decode_resolution_check_snapshot(value: Mapping[str, Any]) -> ResolutionCheckSnapshot:
    frozen = freeze_json(value, "resolution_check_snapshot")
    if set(frozen) != _SNAPSHOT_FIELDS:
        raise ValueError("resolution check snapshot fields do not match the frozen contract")
    for name in ("modifier_receipt_refs", "assist_actor_refs", "assist_receipt_refs"):
        if not isinstance(frozen[name], tuple): raise ValueError(f"{name} must be an array")
    data = dict(frozen)
    for name in ("modifier_receipt_refs", "assist_actor_refs", "assist_receipt_refs"): data[name] = tuple(data[name])
    return ResolutionCheckSnapshot(**data)


def decode_rule_resolution_receipt(value: Mapping[str, Any]) -> RuleResolutionReceipt:
    frozen = freeze_json(value, "rule_resolution_receipt")
    if set(frozen) != _RECEIPT_FIELDS:
        raise ValueError("rule resolution receipt fields do not match the frozen contract")
    return RuleResolutionReceipt(**dict(frozen))


def decode_resolution_check_request(value: Mapping[str, Any]) -> ResolutionCheckRequest:
    frozen = freeze_json(value, "resolution_check_request")
    if set(frozen) != {"schema", "envelope", "action", "snapshot", "rule_receipt"} or not isinstance(frozen["envelope"], Mapping) or not isinstance(frozen["snapshot"], Mapping):
        raise ValueError("resolution check request fields do not match the frozen contract")
    receipt = frozen["rule_receipt"]
    if receipt is not None and not isinstance(receipt, Mapping):
        raise ValueError("rule_receipt must be an object or null")
    return ResolutionCheckRequest(
        str(frozen["schema"]), OperationEnvelope(**dict(frozen["envelope"])), ResolutionAction(str(frozen["action"])),
        decode_resolution_check_snapshot(frozen["snapshot"]), None if receipt is None else decode_rule_resolution_receipt(receipt),
    )


class ResolutionProposalKind(StrEnum): PREVIEW = "preview"; ROLL_REQUEST = "roll_request"; INTERPRETATION = "interpretation"; NO_ROLL = "no_roll"; HOST_CONFIRMATION = "host_confirmation"


@dataclass(frozen=True, slots=True)
class ResolutionCheckProposal:
    schema: str; proposal_ref: str; operation_ref: str; kind: ResolutionProposalKind; source_check_revision: int
    public_preview: Mapping[str, Any]; private_reconciliation: Mapping[str, Any]; deterministic_roll_input: Mapping[str, Any] | None
    result_candidates: tuple[Mapping[str, Any], ...]; interpreted_result: Mapping[str, Any] | None
    used_receipt_refs: tuple[str, ...] = (); warnings: tuple[str, ...] = ()
    def __post_init__(self):
        if self.schema != RESOLUTION_CHECK_PROPOSAL_SCHEMA: raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "resolution_proposal", "检定提案版本无效。")
        _ref(self.proposal_ref, "proposal_ref"); _ref(self.operation_ref, "operation_ref")
        if isinstance(self.source_check_revision, bool) or not isinstance(self.source_check_revision, int) or self.source_check_revision < 0 or not isinstance(self.public_preview, Mapping) or not isinstance(self.private_reconciliation, Mapping) or not all(isinstance(items, tuple) for items in (self.result_candidates, self.used_receipt_refs, self.warnings)):
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "resolution_proposal", "提案字段类型无效。")
        object.__setattr__(self, "public_preview", freeze_json(self.public_preview, "public_preview"))
        object.__setattr__(self, "private_reconciliation", freeze_json(self.private_reconciliation, "private_reconciliation"))
        if self.deterministic_roll_input is not None: object.__setattr__(self, "deterministic_roll_input", freeze_json(self.deterministic_roll_input, "deterministic_roll_input"))
        if self.interpreted_result is not None: object.__setattr__(self, "interpreted_result", freeze_json(self.interpreted_result, "interpreted_result"))
        object.__setattr__(self, "result_candidates", tuple(freeze_json(item, "result_candidates") for item in self.result_candidates))
        if not self.result_candidates or not all(isinstance(item, Mapping) for item in self.result_candidates): raise PortContractError(ProblemCode.OUTPUT_INVALID, "result_candidates", "结果候选必须是非空对象列表。")
        if len(self.used_receipt_refs) != len(set(self.used_receipt_refs)) or any(not isinstance(item, str) for item in self.warnings): raise PortContractError(ProblemCode.OUTPUT_INVALID, "resolution_proposal", "used receipts 必须唯一且 warnings 必须是文本。")
        for item in self.used_receipt_refs: _ref(item, "used_receipt_refs")
        if self.kind is ResolutionProposalKind.ROLL_REQUEST:
            if self.deterministic_roll_input is None or self.interpreted_result is not None: raise PortContractError(ProblemCode.OUTPUT_INVALID, "resolution_proposal", "roll_request 字段组合无效。")
        elif self.kind is ResolutionProposalKind.INTERPRETATION:
            if self.interpreted_result is None or self.deterministic_roll_input is not None: raise PortContractError(ProblemCode.OUTPUT_INVALID, "resolution_proposal", "interpretation 字段组合无效。")
        elif self.deterministic_roll_input is not None or self.interpreted_result is not None:
            raise PortContractError(ProblemCode.OUTPUT_INVALID, "resolution_proposal", "非 roll/interpret proposal 不得携带对应私有结果。")
    def to_mapping(self): return {"schema": self.schema, "proposal_ref": self.proposal_ref, "operation_ref": self.operation_ref, "kind": self.kind.value, "source_check_revision": self.source_check_revision, "public_preview": _plain(self.public_preview), "private_reconciliation": _plain(self.private_reconciliation), "deterministic_roll_input": _plain(self.deterministic_roll_input), "result_candidates": _plain(self.result_candidates), "interpreted_result": _plain(self.interpreted_result), "used_receipt_refs": list(self.used_receipt_refs), "warnings": list(self.warnings)}


class ResolutionResultStatus(StrEnum): PROPOSED = "proposed"; NO_ROLL = "no_roll"; NEEDS_HOST_CONFIRMATION = "needs_host_confirmation"; BLOCKED = "blocked"; CANCELLED = "cancelled"; TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class ResolutionCheckResult:
    schema: str; operation_ref: str; request_fingerprint: str; expected_revision: int; source_check_revision: int; status: ResolutionResultStatus
    proposal: ResolutionCheckProposal | None = None; problems: tuple[Problem, ...] = (); result_fingerprint: str = "sha256:" + "0" * 64

    def __post_init__(self) -> None:
        if self.schema != RESOLUTION_CHECK_RESULT_SCHEMA or not isinstance(self.problems, tuple): raise PortContractError(ProblemCode.CONTRACT_INCOMPATIBLE, "resolution_result", "检定结果合同无效。")
        _ref(self.operation_ref, "operation_ref"); _hash(self.request_fingerprint, "request_fingerprint"); _hash(self.result_fingerprint, "result_fingerprint")
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in (self.expected_revision, self.source_check_revision)): raise PortContractError(ProblemCode.OUTPUT_INVALID, "expected_revision", "结果 revision 无效。")
        if self.proposal is not None and (self.proposal.operation_ref != self.operation_ref or self.proposal.source_check_revision != self.source_check_revision): raise PortContractError(ProblemCode.OUTPUT_INVALID, "resolution_result.proposal", "Proposal 与 Result 的 operation/check revision 不一致。")
        proposal_kind = None if self.proposal is None else self.proposal.kind
        expected = {ResolutionResultStatus.PROPOSED: {ResolutionProposalKind.PREVIEW, ResolutionProposalKind.ROLL_REQUEST, ResolutionProposalKind.INTERPRETATION}, ResolutionResultStatus.NO_ROLL: {ResolutionProposalKind.NO_ROLL}, ResolutionResultStatus.NEEDS_HOST_CONFIRMATION: {ResolutionProposalKind.HOST_CONFIRMATION}}
        if self.status in expected:
            if proposal_kind not in expected[self.status] or self.problems: raise PortContractError(ProblemCode.OUTPUT_INVALID, "resolution_result", "结果 status/proposal/problems 组合无效。")
        elif self.status in {ResolutionResultStatus.BLOCKED, ResolutionResultStatus.CANCELLED, ResolutionResultStatus.TIMED_OUT}:
            if self.proposal is not None or not self.problems: raise PortContractError(ProblemCode.OUTPUT_INVALID, "resolution_result", "终止结果必须无 proposal 且包含 problem。")
        else: raise PortContractError(ProblemCode.OUTPUT_INVALID, "resolution_result.status", "未知结果状态。")


def resolution_result_fingerprint(result: ResolutionCheckResult) -> str: return canonical_fingerprint({"schema": result.schema, "operation_ref": result.operation_ref, "request_fingerprint": result.request_fingerprint, "expected_revision": result.expected_revision, "source_check_revision": result.source_check_revision, "status": result.status.value, "proposal": None if result.proposal is None else result.proposal.to_mapping(), "problems": [{"code": item.code.value, "failed_operation": item.failed_operation, "reason": item.reason, "automatic_handling": item.automatic_handling, "next_action": item.next_action, "retryable": item.retryable} for item in result.problems]})


def decode_resolution_check_result(value: Mapping[str, Any]) -> ResolutionCheckResult:
    frozen = freeze_json(value, "resolution_check_result")
    if set(frozen) != set(ResolutionCheckResult.__dataclass_fields__): raise ValueError("resolution result fields do not match the frozen contract")
    raw_proposal = frozen["proposal"]
    proposal = None
    if raw_proposal is not None:
        if not isinstance(raw_proposal, Mapping) or set(raw_proposal) != set(ResolutionCheckProposal.__dataclass_fields__): raise ValueError("resolution proposal fields do not match the frozen contract")
        if not all(isinstance(raw_proposal[name], tuple) for name in ("result_candidates", "used_receipt_refs", "warnings")): raise ValueError("resolution proposal arrays are invalid")
        proposal = ResolutionCheckProposal(
            str(raw_proposal["schema"]), str(raw_proposal["proposal_ref"]), str(raw_proposal["operation_ref"]), ResolutionProposalKind(str(raw_proposal["kind"])),
            raw_proposal["source_check_revision"], raw_proposal["public_preview"], raw_proposal["private_reconciliation"], raw_proposal["deterministic_roll_input"],
            tuple(raw_proposal["result_candidates"]), raw_proposal["interpreted_result"], tuple(raw_proposal["used_receipt_refs"]), tuple(raw_proposal["warnings"]),
        )
    raw_problems = frozen["problems"]
    if not isinstance(raw_problems, tuple): raise ValueError("resolution problems must be an array")
    problems = []
    problem_fields = set(Problem.__dataclass_fields__)
    for raw in raw_problems:
        if not isinstance(raw, Mapping) or set(raw) != problem_fields: raise ValueError("resolution problem fields do not match the frozen contract")
        if not isinstance(raw["retryable"], bool): raise ValueError("problem.retryable must be boolean")
        problems.append(Problem(ProblemCode(str(raw["code"])), str(raw["failed_operation"]), str(raw["reason"]), str(raw["automatic_handling"]), str(raw["next_action"]), raw["retryable"]))
    result = ResolutionCheckResult(str(frozen["schema"]), str(frozen["operation_ref"]), str(frozen["request_fingerprint"]), frozen["expected_revision"], frozen["source_check_revision"], ResolutionResultStatus(str(frozen["status"])), proposal, tuple(problems), str(frozen["result_fingerprint"]))
    if result.result_fingerprint != resolution_result_fingerprint(result): raise PortContractError(ProblemCode.RESULT_STALE, "result_fingerprint", "检定结果 fingerprint 不匹配。")
    return result


class ResolutionCheckEvaluator:
    def __init__(self, artifact: Mapping[str, Any]):
        catalog = artifact.get("resolution_check_definitions")
        if not isinstance(catalog, Mapping) or set(catalog) != {"schema", "definitions", "catalog_sha256"} or catalog.get("schema") != "se-resolution-check-catalog-ir/1.0.0" or catalog.get("catalog_sha256") != canonical_fingerprint({key: item for key, item in catalog.items() if key != "catalog_sha256"}): raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "resolution_check_definitions", "Artifact检定目录缺失或指纹错误。")
        definitions = {}
        for item in catalog["definitions"]:
            if not isinstance(item, Mapping) or set(item) != _DEFINITION_IR_FIELDS or item.get("schema") != "se-resolution-check-definition-ir/1.0.0" or item["definition_sha256"] != canonical_fingerprint({key: value for key, value in item.items() if key != "definition_sha256"}) or item["definition_ref"] in definitions: raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "resolution_check_definition", "检定定义字段、唯一性或指纹错误。")
            definitions[item["definition_ref"]] = freeze_json(item, "resolution_definition")
        for event in artifact.get("event_compositions", ()):
            binding = event.get("resolution_check")
            if binding is None: continue
            definition = definitions.get(binding.get("definition_ref")) if isinstance(binding, Mapping) else None
            if not isinstance(binding, Mapping) or set(binding) not in (_BINDING_IR_FIELDS, _BINDING_IR_FIELDS | {'choice_definitions'}) or binding.get("schema") != "se-resolution-check-binding-ir/1.0.0" or definition is None or binding.get("definition_sha256") != definition["definition_sha256"]:
                raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, "event.resolution_check", "事件检定绑定与 Artifact 定义不一致。")
            if 'choice_definitions' in binding:
                choices = binding['choice_definitions']
                available = {item['choice_ref'] for group in event.get('choice_sets', ()) for item in group['choices']}
                if not isinstance(choices, Mapping) or not choices or not set(choices) <= available:
                    raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, 'event.resolution_check', '逐行动绑定引用未知选项。')
                for selected in choices.values():
                    expected = definitions.get(selected.get('definition_ref')) if isinstance(selected, Mapping) else None
                    if not isinstance(selected, Mapping) or set(selected) != {'definition_ref','definition_sha256'} or expected is None or selected['definition_sha256'] != expected['definition_sha256']:
                        raise PortContractError(ProblemCode.STORY_PACK_INCOMPATIBLE, 'event.resolution_check', '逐行动定义与摘要不一致。')
        self._definitions = MappingProxyType(definitions)

    def evaluate(self, request: ResolutionCheckRequest) -> ResolutionCheckResult:
        snapshot = request.snapshot
        if request.envelope.request_fingerprint != resolution_request_fingerprint(request) or snapshot.fingerprint != resolution_snapshot_fingerprint(snapshot): return self._blocked(request, ProblemCode.RESULT_STALE, "检定请求或快照 fingerprint 不匹配。")
        definition = self._definitions.get(snapshot.definition_ref)
        if definition is None or definition["definition_sha256"] != snapshot.definition_sha256: return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "检定快照未绑定 Artifact 精确定义。")
        if snapshot.ability_ref not in definition["actor_inputs"]["ability_refs"] and snapshot.ability_ref is not None: return self._blocked(request, ProblemCode.INPUT_INVALID, "ability_ref 未注册。")
        if snapshot.skill_ref not in definition["actor_inputs"]["skill_refs"] and snapshot.skill_ref is not None: return self._blocked(request, ProblemCode.INPUT_INVALID, "skill_ref 未注册。")
        if snapshot.tool_ref not in definition["actor_inputs"]["tool_refs"] and snapshot.tool_ref is not None: return self._blocked(request, ProblemCode.INPUT_INVALID, "tool_ref 未注册。")
        present = {name for name in ("ability", "skill", "tool") if getattr(snapshot, f"{name}_ref") is not None}
        if (definition["check_kind"] in {"ability", "skill", "tool"} and present != {definition["check_kind"]}) or (definition["check_kind"] == "combined" and len(present) < 2): return self._blocked(request, ProblemCode.INPUT_INVALID, "check_kind 与 actor ability/skill/tool 组合不一致。")
        if snapshot.advantage_state == "advantage" and not definition["modifier_policy"]["allow_advantage"]: return self._blocked(request, ProblemCode.INPUT_INVALID, "advantage 未获定义允许。")
        if snapshot.advantage_state == "disadvantage" and not definition["modifier_policy"]["allow_disadvantage"]: return self._blocked(request, ProblemCode.INPUT_INVALID, "disadvantage 未获定义允许。")
        if len(snapshot.modifier_receipt_refs) > definition["modifier_policy"]["maximum_receipts"]: return self._blocked(request, ProblemCode.INPUT_INVALID, "modifier receipt 超过上限。")
        assist_policy = definition["assist_policy"]
        if (not assist_policy["allowed"] and snapshot.assist_actor_refs) or len(snapshot.assist_actor_refs) > assist_policy["maximum_assists"]: return self._blocked(request, ProblemCode.INPUT_INVALID, "assist 输入不符合冻结政策。")
        retry_policy = definition["retry_policy"]
        if snapshot.retry_count > retry_policy["maximum_retries"] or (snapshot.retry_count and not retry_policy["allowed"]): return self._blocked(request, ProblemCode.INPUT_INVALID, "retry_count 不符合冻结政策。")
        if snapshot.retry_count == 0 and snapshot.retry_cost_receipt_ref is not None: return self._blocked(request, ProblemCode.INPUT_INVALID, "首次检定不得携带 retry cost receipt。")
        if snapshot.retry_count > 0 and retry_policy["cost_required"] and snapshot.retry_cost_receipt_ref is None: return self._blocked(request, ProblemCode.INPUT_INVALID, "重试缺少平台 cost receipt identity。")
        if definition["check_kind"] == "opposed" and snapshot.target_ref is None: return self._blocked(request, ProblemCode.INPUT_INVALID, "opposed 检定缺少平台 target snapshot 引用。")
        difficulty = definition["difficulty"]
        if difficulty["source"] == "fixed" and (snapshot.difficulty_rating != difficulty["fixed_rating"] or snapshot.difficulty_receipt_ref is not None or snapshot.host_confirmation_receipt_ref is not None): return self._blocked(request, ProblemCode.RESULT_STALE, "固定难度禁止 difficulty/host receipts，且必须与 Artifact 一致。")
        if difficulty["source"] == "platform_snapshot" and (snapshot.difficulty_rating is None or snapshot.difficulty_receipt_ref is None or snapshot.host_confirmation_receipt_ref is not None): return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "平台难度必须只携带平台 difficulty receipt identity。")
        if difficulty["source"] == "host_confirm":
            if snapshot.difficulty_receipt_ref is not None: return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "host-confirm 难度禁止平台 difficulty receipt。")
            if snapshot.host_confirmation_receipt_ref is None:
                if snapshot.difficulty_rating is not None: return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "host receipt 缺失时不得预填难度。")
                return self._proposal(request, definition, ResolutionProposalKind.HOST_CONFIRMATION, ResolutionResultStatus.NEEDS_HOST_CONFIRMATION)
            if snapshot.difficulty_rating is None: return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "真人确认回执存在但确认后的难度缺失。")
        if request.action is ResolutionAction.INTERPRET_RECEIPT:
            receipt = request.rule_receipt; assert receipt is not None
            if receipt.fingerprint != rule_receipt_fingerprint(receipt) or receipt.definition_ref != snapshot.definition_ref or receipt.definition_sha256 != snapshot.definition_sha256 or receipt.rule_revision != snapshot.rule_revision or receipt.seed_ref != snapshot.seed_ref: return self._blocked(request, ProblemCode.RESULT_STALE, "规则回执与冻结检定不一致。")
            band = next((item for item in definition["result_bands"] if item["outcome"] == receipt.outcome and item["degree"] == receipt.degree), None)
            if band is None: return self._blocked(request, ProblemCode.SEMANTIC_VALIDATION_FAILED, "规则回执 result band 未注册。")
            return self._proposal(request, definition, ResolutionProposalKind.INTERPRETATION, ResolutionResultStatus.PROPOSED, receipt)
        if not snapshot.rule_capability_available:
            if definition["fallback_policy"] == "no_roll": return self._proposal(request, definition, ResolutionProposalKind.NO_ROLL, ResolutionResultStatus.NO_ROLL)
            if definition["fallback_policy"] == "host_confirm": return self._proposal(request, definition, ResolutionProposalKind.HOST_CONFIRMATION, ResolutionResultStatus.NEEDS_HOST_CONFIRMATION)
            return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "规则能力不可用且 fallback=block。")
        if request.action is ResolutionAction.PREVIEW: return self._proposal(request, definition, ResolutionProposalKind.PREVIEW, ResolutionResultStatus.PROPOSED)
        if request.action is ResolutionAction.PREPARE_ROLL:
            if snapshot.seed_ref is None:
                if definition["no_roll_policy"] == "allow_preview_only": return self._proposal(request, definition, ResolutionProposalKind.NO_ROLL, ResolutionResultStatus.NO_ROLL)
                return self._blocked(request, ProblemCode.CONTRACT_INCOMPATIBLE, "平台未提供 seed，禁止 Engine 自行掷骰。")
            return self._proposal(request, definition, ResolutionProposalKind.ROLL_REQUEST, ResolutionResultStatus.PROPOSED)
        raise AssertionError("unreachable resolution action")

    def _proposal(self, request, definition, kind, status, receipt=None):
        snapshot = request.snapshot; stable = canonical_fingerprint({"operation": request.envelope.operation_ref, "kind": kind.value})[7:39]
        preview = {"check_kind": definition["check_kind"], "difficulty": definition["difficulty"]["public_label"], "input_kinds": [name for name in ("ability", "skill", "tool") if getattr(snapshot, f"{name}_ref") is not None], "has_target": snapshot.target_ref is not None, "advantage_state": snapshot.advantage_state, "modifier_count": len(snapshot.modifier_receipt_refs)}
        private = {"actor_ref": snapshot.actor_ref, "target_ref": snapshot.target_ref, "target_snapshot_sha256": snapshot.target_snapshot_sha256, "ability_ref": snapshot.ability_ref, "skill_ref": snapshot.skill_ref, "tool_ref": snapshot.tool_ref, "difficulty_receipt_ref": snapshot.difficulty_receipt_ref, "difficulty_receipt_sha256": snapshot.difficulty_receipt_sha256, "host_confirmation_receipt_ref": snapshot.host_confirmation_receipt_ref, "host_confirmation_receipt_sha256": snapshot.host_confirmation_receipt_sha256, "modifier_receipt_refs": list(snapshot.modifier_receipt_refs), "assist_actor_refs": list(snapshot.assist_actor_refs), "assist_receipt_refs": list(snapshot.assist_receipt_refs), "retry_count": snapshot.retry_count, "retry_cost_receipt_ref": snapshot.retry_cost_receipt_ref, "retry_cost_receipt_sha256": snapshot.retry_cost_receipt_sha256}
        roll_input = None if kind is not ResolutionProposalKind.ROLL_REQUEST else {"rule_ref": definition["rule_ref"], "seed_ref": snapshot.seed_ref, "rule_revision": snapshot.rule_revision, "difficulty_rating": snapshot.difficulty_rating, **private, "advantage_state": snapshot.advantage_state}
        interpreted = None if receipt is None else {"outcome": receipt.outcome, "degree": receipt.degree, "total": receipt.total, "authoritative": False, "source_receipt_ref": receipt.receipt_ref}
        proposal = ResolutionCheckProposal(RESOLUTION_CHECK_PROPOSAL_SCHEMA, f"resolution.{stable}", request.envelope.operation_ref, kind, snapshot.check_revision, preview, private, roll_input, tuple(definition["result_bands"]), interpreted, () if receipt is None else (receipt.receipt_ref,))
        result = ResolutionCheckResult(RESOLUTION_CHECK_RESULT_SCHEMA, request.envelope.operation_ref, request.envelope.request_fingerprint, request.envelope.expected_revision, snapshot.check_revision, status, proposal)
        return replace(result, result_fingerprint=resolution_result_fingerprint(result))

    def _blocked(self, request, code, reason):
        problem = Problem(code, "评估系统无关检定", reason, "没有掷骰、提交状态或生成权威回执。", "刷新定义、快照、seed、receipt或revision后重试。")
        result = ResolutionCheckResult(RESOLUTION_CHECK_RESULT_SCHEMA, request.envelope.operation_ref, request.envelope.request_fingerprint, request.envelope.expected_revision, request.snapshot.check_revision, ResolutionResultStatus.BLOCKED, problems=(problem,))
        return replace(result, result_fingerprint=resolution_result_fingerprint(result))


class ResolutionCheckService:
    def __init__(self, evaluator, *, clock=None): self.evaluator=evaluator; self._clock=clock or (lambda: datetime.now(UTC))
    async def evaluate_resolution_check(self, request, bridge: PlatformBridge):
        check=CancellationCheck(request.envelope.operation_ref, request.envelope.request_fingerprint); deadline=datetime.fromisoformat(request.envelope.deadline_at.replace("Z","+00:00"))
        if (await bridge.is_cancelled(check)).cancelled: return self._terminal(request, ResolutionResultStatus.CANCELLED, ProblemCode.CANCELLED, "检定操作已取消。")
        if self._clock()>=deadline: return self._terminal(request, ResolutionResultStatus.TIMED_OUT, ProblemCode.DEADLINE_EXCEEDED, "检定操作已超时。")
        result=self.evaluator.evaluate(request)
        if (await bridge.is_cancelled(check)).cancelled: return self._terminal(request, ResolutionResultStatus.CANCELLED, ProblemCode.CANCELLED, "检定结果返回前已取消。")
        if self._clock()>=deadline: return self._terminal(request, ResolutionResultStatus.TIMED_OUT, ProblemCode.DEADLINE_EXCEEDED, "检定结果返回前已超时。")
        return result
    def _terminal(self, request,status,code,reason):
        problem=Problem(code,"评估系统无关检定",reason,"没有生成检定提案。","刷新权威快照后重试。")
        result=ResolutionCheckResult(RESOLUTION_CHECK_RESULT_SCHEMA,request.envelope.operation_ref,request.envelope.request_fingerprint,request.envelope.expected_revision,request.snapshot.check_revision,status,problems=(problem,)); return replace(result,result_fingerprint=resolution_result_fingerprint(result))


class ResolutionCheckStoryEnginePort(Protocol):
    async def evaluate_resolution_check(self, request: ResolutionCheckRequest, bridge: PlatformBridge) -> ResolutionCheckResult: ...


__all__=[name for name in globals() if name.startswith("RESOLUTION_CHECK") or name in {"ResolutionAction","ResolutionCheckContractError","ResolutionCheckEvaluator","ResolutionCheckProposal","ResolutionCheckRequest","ResolutionCheckResult","ResolutionCheckService","ResolutionCheckSnapshot","ResolutionCheckStoryEnginePort","ResolutionProposalKind","ResolutionResultStatus","RuleResolutionReceipt","bind_resolution_check","compile_resolution_check_definitions","decode_resolution_check_request","decode_resolution_check_result","decode_resolution_check_snapshot","decode_rule_resolution_receipt","resolution_request_fingerprint","resolution_result_fingerprint","resolution_snapshot_fingerprint","rule_receipt_fingerprint"}]
