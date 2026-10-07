"""Typed, deterministic authoring contract for SE 1 event composition."""

from __future__ import annotations

import re
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from story_engine.catastrophic import CATASTROPHIC_PROFILE_VERSION, CatastrophicContractError, validate_catastrophic_author
from story_engine.versions import AUTHOR_ENVELOPE_CHOICE_SCHEMA, AUTHOR_ENVELOPE_GUARD_SCHEMA, AUTHOR_ENVELOPE_SCHEMA, STORY_ENGINE_RANGE

_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_EVENT_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_PROFILE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_VERSION_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_FORBIDDEN_DATA_KEYS = {
    "adapter",
    "callable",
    "database",
    "delivery_target",
    "handler",
    "http_request",
    "javascript",
    "origin_surface",
    "provider",
    "python",
    "renderer",
    "script",
    "send_message",
    "sql",
    "url_handler",
}
_TOP_LEVEL_FIELDS = {
    "schema",
    "profile",
    "profile_version",
    "requires_engine",
    "requires_capabilities",
    "optional_capabilities",
    "identity",
    "scope",
    "visibility",
    "trigger",
    "guards",
    "omens",
    "checkpoints",
    "routes",
    "effects",
    "budgets",
    "extensions",
    "profile_data",
    "tags",
    "once",
    "cooldown",
    "density_group",
    "minimum_round",
    "cancellation_policy",
}
_EFFECT_FIELDS = {"id", "route_id", "capability_id", "effect_type", "target_ref", "revision_source", "payload", "reversible", "gate_id"}


class DiagnosticSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class AuthoringDiagnostic:
    code: str
    severity: DiagnosticSeverity
    field_path: str
    problem: str
    impact: str
    automatic_handling: str
    next_action: str


class AuthoringContractError(ValueError):
    """Fail-closed contract error with a stable author-facing diagnostic."""

    def __init__(self, diagnostic: AuthoringDiagnostic) -> None:
        super().__init__(diagnostic.problem)
        self.diagnostic = diagnostic
        self.code = diagnostic.code


def _fail(code: str, path: str, problem: str, next_action: str) -> None:
    raise AuthoringContractError(
        AuthoringDiagnostic(
            code=code,
            severity=DiagnosticSeverity.ERROR,
            field_path=path,
            problem=problem,
            impact="当前事件定义未被接受，也不会生成运行提案。",
            automatic_handling="未自动补值或删除内容。",
            next_action=next_action,
        )
    )


def parse_semver(value: str, *, path: str) -> tuple[int, int, int, int, tuple[tuple[int, int | str], ...]]:
    match = _VERSION_RE.fullmatch(str(value or "").strip())
    if not match:
        _fail("author.version_invalid", path, "版本不是有效 SemVer。", "填写例如 1.0.0 的明确版本。")
    prerelease = match.group(4)
    parts: tuple[tuple[int, int | str], ...] = ()
    if prerelease is not None:
        parsed: list[tuple[int, int | str]] = []
        for item in prerelease.split("."):
            if item.isdigit():
                if len(item) > 1 and item.startswith("0"):
                    _fail("author.version_invalid", path, "SemVer 数字预发布标识不能有前导零。", "修正预发布版本。")
                parsed.append((0, int(item)))
            else:
                parsed.append((1, item))
        parts = tuple(parsed)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), 1 if prerelease is None else 0, parts)


def version_satisfies(version: str, requirement: str, *, path: str = "requires_engine") -> bool:
    current = parse_semver(version, path=path)
    tokens = str(requirement or "").split()
    if not tokens:
        _fail("author.version_range_invalid", path, "版本范围不能为空。", "填写显式 SemVer 范围。")
    for token in tokens:
        operator = next((op for op in (">=", "<=", ">", "<", "==") if token.startswith(op)), "==")
        raw = token[len(operator) :] if token.startswith(operator) else token
        target = parse_semver(raw, path=path)
        checks = {
            ">=": current >= target,
            "<=": current <= target,
            ">": current > target,
            "<": current < target,
            "==": current == target,
        }
        if not checks[operator]:
            return False
    return True


def validate_version_range(requirement: str, *, path: str) -> str:
    result = _text(requirement, path=path, maximum=96)
    tokens = result.split()
    if not tokens:
        _fail("author.version_range_invalid", path, "版本范围不能为空。", "填写显式 SemVer 范围。")
    for token in tokens:
        operator = next((op for op in (">=", "<=", ">", "<", "==") if token.startswith(op)), "")
        raw = token[len(operator) :] if operator else token
        parse_semver(raw, path=path)
    return result


def _text(value: Any, *, path: str, minimum: int = 1, maximum: int = 512) -> str:
    if not isinstance(value, str):
        _fail("author.type_invalid", path, "字段必须是文本。", "改为符合长度限制的文本。")
    result = value.strip()
    if not minimum <= len(result) <= maximum:
        _fail("author.text_length_invalid", path, f"文本长度必须在 {minimum} 到 {maximum} 个字符之间。", "缩短或补全该文本。")
    return result


def _identifier(value: Any, *, path: str, pattern: re.Pattern[str] = _ID_RE) -> str:
    result = _text(value, path=path, maximum=128)
    if pattern.fullmatch(result) is None:
        _fail("author.id_invalid", path, "标识必须以小写字母开头，且只含小写字母、数字、点、下划线或短横线。", "改用稳定的小写标识。")
    return result


def _json_data(value: Any, *, path: str, depth: int = 0) -> Any:
    if depth > 32:
        _fail("author.data_too_deep", path, "声明式数据嵌套超过 32 层。", "拆分或简化嵌套数据。")
    if isinstance(value, float) and not math.isfinite(value):
        _fail("author.number_invalid", path, "数字必须是有限值。", "删除 NaN 或无限值。")
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        if len(value) > 10_000:
            _fail("author.data_too_large", path, "对象成员超过 10000 项。", "缩小当前定义。")
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                _fail("author.key_invalid", path, "对象键必须是文本。", "把对象键改为稳定文本。")
            normalized = key.strip()
            if normalized.casefold() in _FORBIDDEN_DATA_KEYS:
                _fail("author.executable_or_platform_data_forbidden", f"{path}.{normalized}", "作者源不得包含代码、平台、数据库、provider 或投递配置。", "删除该字段并改用受信能力引用。")
            result[normalized] = _json_data(item, path=f"{path}.{normalized}", depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > 10_000:
            _fail("author.data_too_large", path, "列表成员超过 10000 项。", "缩小当前定义。")
        return [_json_data(item, path=f"{path}[{index}]", depth=depth + 1) for index, item in enumerate(value)]
    _fail("author.non_declarative_value", path, "作者源只允许 JSON 兼容的纯声明式值。", "删除对象、函数、字节或其他运行时值。")


def _thaw(value: Any) -> Any:
    """Return plain JSON containers from frozen contract values."""
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_thaw(item) for item in value]
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    id: str
    version_range: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, path: str) -> "CapabilityRequirement":
        unknown = set(value) - {"id", "version"}
        if unknown:
            _fail("author.field_unknown", path, "能力要求包含未知字段：" + "、".join(sorted(unknown)), "仅保留 id 和 version。")
        capability_id = _identifier(value.get("id"), path=f"{path}.id")
        version_range = validate_version_range(value.get("version"), path=f"{path}.version")
        return cls(capability_id, version_range)

    def to_mapping(self) -> dict[str, str]:
        return {"id": self.id, "version": self.version_range}


@dataclass(frozen=True, slots=True)
class EventIdentity:
    id: str
    label: str
    summary: str


@dataclass(frozen=True, slots=True)
class EventScope:
    kind: str
    refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EventVisibility:
    default: str = "public"
    audiences: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EventTrigger:
    event: str
    when: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResourceBudgets:
    max_rounds: int
    max_checkpoints: int
    max_loop_iterations: int
    max_concurrent_fronts: int
    max_cascade_events: int
    max_cross_module_effects: int
    max_local_ms: int
    max_context_tokens: int
    max_pressure_rounds: int
    recovery_window_rounds: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, defaults: Mapping[str, int]) -> "ResourceBudgets":
        expected = set(defaults)
        unknown = set(value) - expected
        if unknown:
            _fail("author.field_unknown", "budgets", "预算包含未知字段：" + "、".join(sorted(unknown)), "使用 Profile Registry 声明的预算字段。")
        material = dict(defaults)
        material.update(value)
        for key, item in material.items():
            if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                _fail("author.budget_invalid", f"budgets.{key}", "预算必须是正整数。", "填写大于零且不超过 profile 上限的整数。")
            if item > defaults[key]:
                _fail("author.budget_exceeds_profile", f"budgets.{key}", "预算超过当前 profile 的安全上限。", f"将值调整为不超过 {defaults[key]}。")
        return cls(**material)

    def to_mapping(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class EventAuthorEnvelope:
    schema: str
    profile: str
    profile_version: str
    requires_engine: str
    requires_capabilities: tuple[CapabilityRequirement, ...]
    optional_capabilities: tuple[CapabilityRequirement, ...]
    identity: EventIdentity
    scope: EventScope
    visibility: EventVisibility
    trigger: EventTrigger
    guards: tuple[Mapping[str, Any], ...]
    fact_catalog: Mapping[str, Any] | None
    required_platform_features: tuple[str, ...]
    initial_checkpoint_ref: str | None
    choice_sets: tuple[Mapping[str, Any], ...]
    omens: tuple[Mapping[str, Any], ...]
    checkpoints: tuple[Mapping[str, Any], ...]
    routes: tuple[Mapping[str, Any], ...]
    effects: tuple[Mapping[str, Any], ...]
    budgets: ResourceBudgets
    extensions: Mapping[str, Any]
    profile_data: Mapping[str, Any]
    tags: tuple[str, ...]
    once: bool
    cooldown: int
    density_group: str
    minimum_round: int
    cancellation_policy: str

    def to_mapping(self) -> dict[str, Any]:
        result = {
            "schema": self.schema,
            "profile": self.profile,
            "profile_version": self.profile_version,
            "requires_engine": self.requires_engine,
            "requires_capabilities": [item.to_mapping() for item in self.requires_capabilities],
            "optional_capabilities": [item.to_mapping() for item in self.optional_capabilities],
            "identity": {"id": self.identity.id, "label": self.identity.label, "summary": self.identity.summary},
            "scope": {"kind": self.scope.kind, "refs": list(self.scope.refs)},
            "visibility": {"default": self.visibility.default, "audiences": dict(self.visibility.audiences)},
            "trigger": {"event": self.trigger.event, "when": _thaw(self.trigger.when)},
            "guards": _thaw(self.guards),
            "omens": _thaw(self.omens),
            "checkpoints": _thaw(self.checkpoints),
            "routes": _thaw(self.routes),
            "effects": _thaw(self.effects),
            "budgets": self.budgets.to_mapping(),
            "extensions": _thaw(self.extensions),
            "profile_data": _thaw(self.profile_data),
            "tags": list(self.tags),
            "once": self.once,
            "cooldown": self.cooldown,
            "density_group": self.density_group,
            "minimum_round": self.minimum_round,
            "cancellation_policy": self.cancellation_policy,
        }
        if self.schema in {AUTHOR_ENVELOPE_GUARD_SCHEMA, AUTHOR_ENVELOPE_CHOICE_SCHEMA}:
            result["fact_catalog"] = _thaw(self.fact_catalog)
        if self.schema == AUTHOR_ENVELOPE_CHOICE_SCHEMA:
            result["required_platform_features"] = list(self.required_platform_features)
            result["initial_checkpoint_ref"] = self.initial_checkpoint_ref
            result["choice_sets"] = _thaw(self.choice_sets)
        return result


def _mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("author.type_invalid", path, "字段必须是对象。", "填写对象结构。")
    return value


def _sequence_of_mappings(value: Any, *, path: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("author.type_invalid", path, "字段必须是对象列表。", "填写对象列表；无内容时使用空列表。")
    result = _json_data(value, path=path)
    for index, item in enumerate(result):
        if not isinstance(item, Mapping):
            _fail("author.type_invalid", f"{path}[{index}]", "列表成员必须是对象。", "将该成员改为对象。")
    return tuple(_freeze(item) for item in result)


def parse_author_envelope(value: Mapping[str, Any], *, profile_contract: Any) -> EventAuthorEnvelope:
    """Parse one envelope against a resolved ProfileContract.

    Profile resolution is intentionally external, keeping the common DTO free of a
    registry singleton and making registry revision/fingerprint explicit to callers.
    """

    if not isinstance(value, Mapping):
        _fail("author.envelope_invalid", "$", "事件定义必须是对象。", "提交符合公共 envelope 的对象。")
    schema = _text(value.get("schema"), path="schema", maximum=64)
    if schema not in {AUTHOR_ENVELOPE_SCHEMA, AUTHOR_ENVELOPE_GUARD_SCHEMA, AUTHOR_ENVELOPE_CHOICE_SCHEMA}:
        _fail("author.schema_unsupported", "schema", "作者 envelope 版本不受支持。", f"使用 {AUTHOR_ENVELOPE_SCHEMA}、{AUTHOR_ENVELOPE_GUARD_SCHEMA} 或 {AUTHOR_ENVELOPE_CHOICE_SCHEMA}。")
    allowed_fields = _TOP_LEVEL_FIELDS | ({"fact_catalog"} if schema in {AUTHOR_ENVELOPE_GUARD_SCHEMA, AUTHOR_ENVELOPE_CHOICE_SCHEMA} else set()) | ({"required_platform_features", "initial_checkpoint_ref", "choice_sets"} if schema == AUTHOR_ENVELOPE_CHOICE_SCHEMA else set())
    unknown = set(value) - allowed_fields
    if unknown:
        _fail("author.field_unknown", "$", "事件定义包含未知字段：" + "、".join(sorted(unknown)), "删除未知字段或先升级公开合同。")
    if schema in {AUTHOR_ENVELOPE_GUARD_SCHEMA, AUTHOR_ENVELOPE_CHOICE_SCHEMA} and "fact_catalog" not in value:
        _fail("author.field_missing", "fact_catalog", "guard authoring requires a fact catalog.", "Declare every dynamic guard fact.")
    if schema == AUTHOR_ENVELOPE_CHOICE_SCHEMA:
        for field_name in ("required_platform_features", "initial_checkpoint_ref", "choice_sets"):
            if field_name not in value:
                _fail("author.field_missing", field_name, "choice authoring field is required.", "Declare the explicit activation root and platform choice semantics.")
        if value["required_platform_features"] != ["event.choice_set/1.0.0"]:
            _fail("author.platform_feature_invalid", "required_platform_features", "choice authoring requires the exact platform feature event.choice_set/1.0.0.", "Declare the exact versioned platform feature once.")
    profile = _identifier(value.get("profile"), path="profile", pattern=_PROFILE_RE)
    if profile != profile_contract.profile_id:
        _fail("profile.contract_mismatch", "profile", "解析到的 profile 合同与事件声明不一致。", "从同一 Profile Registry 重新解析合同。")
    profile_version = _text(value.get("profile_version"), path="profile_version", maximum=64)
    if profile_version != profile_contract.version:
        _fail("profile.version_unsupported", "profile_version", "profile 版本不受支持。", f"使用 {profile_contract.version}。")
    requires_engine = _text(value.get("requires_engine"), path="requires_engine", maximum=96)
    version_satisfies("1.0.0", requires_engine)

    def capabilities(field_name: str) -> tuple[CapabilityRequirement, ...]:
        raw = value.get(field_name, [])
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            _fail("author.type_invalid", field_name, "能力要求必须是列表。", "填写由 id 和 version 构成的列表。")
        parsed = tuple(CapabilityRequirement.from_mapping(_mapping(item, path=f"{field_name}[{index}]"), path=f"{field_name}[{index}]") for index, item in enumerate(raw))
        ids = [item.id for item in parsed]
        if len(ids) != len(set(ids)):
            _fail("author.capability_duplicate", field_name, "能力要求不能重复。", "合并重复能力并保留一个明确版本范围。")
        return tuple(sorted(parsed, key=lambda item: item.id))

    required = capabilities("requires_capabilities")
    optional = capabilities("optional_capabilities")
    overlap = {item.id for item in required} & {item.id for item in optional}
    if overlap:
        _fail("author.capability_conflict", "optional_capabilities", "同一能力不能同时声明为 required 和 optional。", "明确选择 required 或 optional。")

    identity_raw = _mapping(value.get("identity"), path="identity")
    if set(identity_raw) != {"id", "label", "summary"}:
        _fail("author.identity_fields_invalid", "identity", "identity 必须且只能包含 id、label、summary。", "补齐或删除对应字段。")
    identity = EventIdentity(
        _identifier(identity_raw["id"], path="identity.id"),
        _text(identity_raw["label"], path="identity.label", maximum=80),
        _text(identity_raw["summary"], path="identity.summary", maximum=600),
    )
    scope_raw = _mapping(value.get("scope"), path="scope")
    if set(scope_raw) != {"kind", "refs"}:
        _fail("author.scope_fields_invalid", "scope", "scope 必须且只能包含 kind 和 refs。", "补齐或删除对应字段。")
    scope_kind = _text(scope_raw["kind"], path="scope.kind", maximum=32)
    if scope_kind not in {"scene", "site", "region", "faction", "quest", "actor_group", "campaign"}:
        _fail("author.scope_kind_invalid", "scope.kind", "scope.kind 不在公共合同允许范围内。", "选择已注册的范围类型。")
    if scope_kind not in profile_contract.allowed_scope_kinds:
        _fail("profile.scope_not_allowed", "scope.kind", "当前 profile 不允许该范围类型。", "改用 profile 允许的范围或选择其他 profile。")
    refs_raw = scope_raw["refs"]
    if not isinstance(refs_raw, Sequence) or isinstance(refs_raw, (str, bytes, bytearray)) or not refs_raw:
        _fail("author.scope_refs_invalid", "scope.refs", "scope.refs 必须是非空稳定引用列表。", "填写至少一个可解析引用。")
    refs = tuple(_identifier(item, path=f"scope.refs[{index}]") for index, item in enumerate(refs_raw))
    if len(refs) != len(set(refs)):
        _fail("author.reference_duplicate", "scope.refs", "范围引用不能重复。", "删除重复引用。")

    visibility_raw = _mapping(value.get("visibility", {"default": "public"}), path="visibility")
    if set(visibility_raw) - {"default", "audiences"}:
        _fail("author.field_unknown", "visibility", "visibility 包含未知字段。", "仅保留 default 和 audiences。")
    default_visibility = _text(visibility_raw.get("default", "public"), path="visibility.default", maximum=16)
    if default_visibility not in {"public", "party", "actor", "dm", "admin", "author"}:
        _fail("author.visibility_invalid", "visibility.default", "可见性 audience 不受支持。", "选择 public、party、actor、dm、admin 或 author。")
    audiences = _json_data(_mapping(visibility_raw.get("audiences", {}), path="visibility.audiences"), path="visibility.audiences")
    for audience_path, audience in audiences.items():
        if audience not in {"public", "party", "actor", "dm", "admin", "author"}:
            _fail("author.visibility_invalid", f"visibility.audiences.{audience_path}", "字段 audience 不受支持。", "选择公共合同注册的 audience。")

    trigger_raw = _mapping(value.get("trigger"), path="trigger")
    if set(trigger_raw) - {"event", "when"} or "event" not in trigger_raw:
        _fail("author.trigger_fields_invalid", "trigger", "trigger 必须包含 event，且只可附带 when。", "填写注册语义事件和安全条件树。")
    trigger_event = _identifier(trigger_raw["event"], path="trigger.event", pattern=_EVENT_RE)
    trigger_when = _json_data(_mapping(trigger_raw.get("when", {}), path="trigger.when"), path="trigger.when")

    profile_data = _json_data(_mapping(value.get("profile_data", {}), path="profile_data"), path="profile_data")
    profile_contract.validate_profile_data(profile_data)
    checkpoints = _sequence_of_mappings(value.get("checkpoints", []), path="checkpoints")
    if not profile_contract.min_checkpoints <= len(checkpoints) <= profile_contract.max_checkpoints:
        _fail("profile.checkpoint_count_invalid", "checkpoints", f"当前 profile 的检查点数量必须在 {profile_contract.min_checkpoints} 到 {profile_contract.max_checkpoints} 之间。", "调整检查点数量或选择其他 profile。")
    required_ids = {item.id for item in required}
    missing_profile_caps = set(profile_contract.required_capabilities) - required_ids
    if missing_profile_caps:
        _fail("profile.capability_missing", "requires_capabilities", "当前 profile 缺少必需能力：" + "、".join(sorted(missing_profile_caps)), "按 Profile Registry 补齐 required 能力和版本范围。")
    for item in required:
        if item.id not in profile_contract.required_capabilities:
            continue
        exact_range = getattr(profile_contract, "required_capability_ranges", {}).get(item.id)
        if exact_range is not None and item.version_range != exact_range:
            _fail("profile.capability_version_mismatch", "requires_capabilities", f"能力 {item.id} 必须声明 Profile Registry 固定的版本范围 {exact_range}。", "使用 Registry 声明的精确 required capability range；禁止放宽、降级或漂移。")
        if exact_range is None and not version_satisfies("1.0.0", item.version_range, path="requires_capabilities"):
            _fail("profile.capability_version_mismatch", "requires_capabilities", f"能力 {item.id} 的版本范围不包含 profile 所需的 1.0.0。", "调整能力版本范围或升级 profile 合同。")
    allowed_profile_capabilities = set(profile_contract.allowed_capabilities)
    if schema in {AUTHOR_ENVELOPE_GUARD_SCHEMA, AUTHOR_ENVELOPE_CHOICE_SCHEMA}:
        allowed_profile_capabilities.add("event.guard.evaluate")
    disallowed = (required_ids | {item.id for item in optional}) - allowed_profile_capabilities
    if disallowed:
        _fail("profile.capability_not_allowed", "requires_capabilities", "当前 profile 未允许能力：" + "、".join(sorted(disallowed)), "删除越界能力或升级为适当 profile；不得猜测未注册 capability ID。")

    routes = _sequence_of_mappings(value.get("routes", []), path="routes")
    route_ids = {str(item.get("id") or "") for item in routes}
    gated_checkpoint_ids = {
        _identifier(item.get("id"), path=f"checkpoints[{index}].id")
        for index, item in enumerate(checkpoints) if item.get("required_gate")
    }
    effects = _sequence_of_mappings(value.get("effects", []), path="effects")
    effect_ids: set[str] = set()
    declared_capabilities = required_ids | {item.id for item in optional}
    for index, effect in enumerate(effects):
        path = f"effects[{index}]"
        missing = (_EFFECT_FIELDS - {"gate_id"}) - set(effect)
        unknown = set(effect) - _EFFECT_FIELDS
        if missing or unknown:
            _fail("author.effect_fields_invalid", path, "effect 字段不完整或包含未知字段。", "使用冻结的 id/route_id/capability_id/effect_type/target_ref/revision_source/payload/reversible/gate_id 字段。")
        effect_id = _identifier(effect["id"], path=f"{path}.id")
        if effect_id in effect_ids:
            _fail("author.effect_duplicate", f"{path}.id", "effect ID 重复。", "为每个 effect 使用唯一 ID。")
        effect_ids.add(effect_id)
        route_id = _identifier(effect["route_id"], path=f"{path}.route_id")
        if route_id not in route_ids:
            _fail("author.effect_route_unknown", f"{path}.route_id", "effect 引用了未声明路线。", "改为当前事件已声明的 route_id。")
        capability_id = _identifier(effect["capability_id"], path=f"{path}.capability_id")
        if capability_id not in declared_capabilities:
            _fail("author.effect_capability_undeclared", f"{path}.capability_id", "effect 能力没有列入 required 或 optional capability。", "先声明版本化 capability。")
        _identifier(effect["effect_type"], path=f"{path}.effect_type")
        _identifier(effect["target_ref"], path=f"{path}.target_ref")
        if effect["revision_source"] not in {"event", "world", "actor"}:
            _fail("author.effect_revision_source_invalid", f"{path}.revision_source", "effect revision 来源无效。", "选择 event、world 或 actor。")
        _mapping(effect["payload"], path=f"{path}.payload")
        if not isinstance(effect["reversible"], bool):
            _fail("author.effect_reversible_invalid", f"{path}.reversible", "effect reversible 必须是布尔值。", "填写 true 或 false。")
        if effect.get("gate_id") is not None:
            gate_id = _identifier(effect["gate_id"], path=f"{path}.gate_id")
            if gate_id not in gated_checkpoint_ids:
                _fail("author.effect_gate_unknown", f"{path}.gate_id", "effect gate 没有指向声明 required_gate 的检查点。", "改为带 required_gate 的 checkpoint ID，或删除 gate_id。")

    tags_raw = value.get("tags", [])
    if not isinstance(tags_raw, Sequence) or isinstance(tags_raw, (str, bytes, bytearray)):
        _fail("author.type_invalid", "tags", "tags 必须是列表。", "填写稳定标签列表。")
    tags = tuple(sorted({_identifier(item, path=f"tags[{index}]") for index, item in enumerate(tags_raw)}))
    cooldown = value.get("cooldown", 1)
    minimum_round = value.get("minimum_round", 1)
    for path, number in (("cooldown", cooldown), ("minimum_round", minimum_round)):
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            _fail("author.integer_invalid", path, "字段必须是非负整数。", "填写非负整数。")
    density_group = _identifier(value.get("density_group", "default"), path="density_group")
    cancellation_policy = _text(value.get("cancellation_policy", "until_irreversible"), path="cancellation_policy", maximum=32)
    if cancellation_policy not in {"until_triggered", "until_irreversible", "host_only_after_trigger"}:
        _fail("author.cancellation_policy_invalid", "cancellation_policy", "取消政策不受支持。", "选择公共合同注册的取消政策。")

    budgets = ResourceBudgets.from_mapping(_mapping(value.get("budgets", {}), path="budgets"), defaults=profile_contract.budget_limits)
    once = value.get("once", False)
    if not isinstance(once, bool):
        _fail("author.type_invalid", "once", "once 必须是布尔值。", "填写 true 或 false。")
    if profile == "catastrophic_event" and profile_version == CATASTROPHIC_PROFILE_VERSION:
        try:
            validate_catastrophic_author(value)
        except CatastrophicContractError as exc:
            _fail(exc.code, exc.path, exc.reason, "补齐版本化灾难合同并重新编译；不得用模型文本或默认值代替。")
    return EventAuthorEnvelope(
        schema=schema,
        profile=profile,
        profile_version=profile_version,
        requires_engine=requires_engine,
        requires_capabilities=required,
        optional_capabilities=optional,
        identity=identity,
        scope=EventScope(scope_kind, refs),
        visibility=EventVisibility(default_visibility, _freeze(audiences)),
        trigger=EventTrigger(trigger_event, _freeze(trigger_when)),
        guards=_sequence_of_mappings(value.get("guards", []), path="guards"),
        fact_catalog=None if schema == AUTHOR_ENVELOPE_SCHEMA else _freeze(_json_data(_mapping(value.get("fact_catalog"), path="fact_catalog"), path="fact_catalog")),
        required_platform_features=tuple(value.get("required_platform_features", ())),
        initial_checkpoint_ref=None if schema != AUTHOR_ENVELOPE_CHOICE_SCHEMA else _identifier(value.get("initial_checkpoint_ref"), path="initial_checkpoint_ref"),
        choice_sets=() if schema != AUTHOR_ENVELOPE_CHOICE_SCHEMA else _sequence_of_mappings(value.get("choice_sets"), path="choice_sets"),
        omens=_sequence_of_mappings(value.get("omens", []), path="omens"),
        checkpoints=checkpoints,
        routes=routes,
        effects=effects,
        budgets=budgets,
        extensions=_freeze(_json_data(_mapping(value.get("extensions", {}), path="extensions"), path="extensions")),
        profile_data=_freeze(profile_data),
        tags=tags,
        once=once,
        cooldown=cooldown,
        density_group=density_group,
        minimum_round=minimum_round,
        cancellation_policy=cancellation_policy,
    )


__all__ = [
    "AuthoringContractError",
    "AuthoringDiagnostic",
    "CapabilityRequirement",
    "DiagnosticSeverity",
    "EventAuthorEnvelope",
    "EventIdentity",
    "EventScope",
    "EventTrigger",
    "EventVisibility",
    "ResourceBudgets",
    "parse_author_envelope",
    "parse_semver",
    "version_satisfies",
    "validate_version_range",
]
