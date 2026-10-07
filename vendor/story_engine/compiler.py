"""Deterministic, code-free SE 1 compiler, canonical IR and Artifact contracts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from .catastrophic import CATASTROPHIC_PROFILE_VERSION, CatastrophicContractError, compile_catastrophic_contract
from .turn_interaction import (
    TURN_INTERACTION_CAPABILITY, TurnInteractionContractError, bind_turn_interaction_policy,
    compile_turn_interaction_policies,
)
from .resolution_check import (
    RESOLUTION_CHECK_CAPABILITY, ResolutionCheckContractError, bind_resolution_check,
    compile_resolution_check_definitions,
)
from .resolution_rule import ResolutionRuleContractError, compile_resolution_rule_contract
from .resolution_action_offer import (
    ResolutionActionOfferContractError, action_offer_event_bindings,
    compile_resolution_action_offers,
)
from .luck_action_bindings import (AUTHOR_SCHEMA as LUCK_ACTION_BINDINGS_AUTHOR_SCHEMA,
                                   LuckActionBindingContractError, compile_luck_action_bindings)
from .character_build import CHARACTER_BUILD_CAPABILITY, CharacterBuildContractError, bind_character_build, compile_character_build_definitions
from .character_progression import CHARACTER_PROGRESSION_CAPABILITY, CharacterProgressionContractError, bind_character_progression, compile_character_progression_definitions
from .reward_settlement import REWARD_SETTLEMENT_CAPABILITY, RewardSettlementContractError, bind_reward_settlement, compile_reward_settlement_definitions
from .inventory_equipment import INVENTORY_EQUIPMENT_CAPABILITY, InventoryEquipmentContractError, bind_inventory_equipment, compile_inventory_equipment_definitions
from .ability_execution import ABILITY_EXECUTION_CAPABILITY, AbilityExecutionContractError, bind_ability_execution, compile_ability_execution_definitions
from .conflict_procedure import CONFLICT_PROCEDURE_CAPABILITY, ConflictProcedureContractError, bind_conflict_procedure, compile_conflict_procedure_definitions
from .recovery_cycle import RECOVERY_CYCLE_CAPABILITY, RecoveryCycleContractError, bind_recovery_cycle, compile_recovery_cycle_definitions
from .recovery_cycle_v2 import RECOVERY_CYCLE_CAPABILITY as RECOVERY_CYCLE_V2_CAPABILITY, RecoveryCycleContractError as RecoveryCycleV2ContractError, bind_recovery_cycle as bind_recovery_cycle_v2, compile_recovery_cycle_definitions as compile_recovery_cycle_v2_definitions
from .offline_public import OFFLINE_PUBLIC_CAPABILITY, OfflinePublicContractError, compile_offline_public
from .contracts.authoring import AuthoringContractError, EventAuthorEnvelope, version_satisfies
from .profiles import CONFLICT_RECOVERY_UNION_PROFILE_REGISTRY, CONFLICT_RECOVERY_UNION_V2_PROFILE_REGISTRY, P0_PROFILE_REGISTRY, ProfileRegistry
from .provider_registry import load_provider_manifest, provider_manifest_file_sha256, resolve_provider
from .resources import ResourceCatalog, ResourceContractError, VitalityContract, effect_contract_identities
from .conditions import CONDITION_TREE_SCHEMA, GUARD_CAPABILITY, ConditionContractError, FactCatalog, normalize_condition_tree
from .choices import CHOICE_CAPABILITY, CHOICE_CONTRACT, ChoiceContractError, compile_choice_semantics
from .v02_extension_candidate import (
    V02ExtensionCandidateError,
    normalize_v02_extension_candidate,
)
from .versions import (
    ARTIFACT_CHOICE_SCHEMA, ARTIFACT_GUARD_SCHEMA, ARTIFACT_RECOVERY_SCHEMA, ARTIFACT_SCHEMA, ARTIFACT_UNION_SCHEMA, ARTIFACT_UNION_V2_SCHEMA,
    AUTHOR_ENVELOPE_CHOICE_SCHEMA, AUTHOR_ENVELOPE_GUARD_SCHEMA,
    BUDGET_ALGORITHM_VERSION,
    CANONICAL_IR_SCHEMA,
    CANONICAL_IR_CHOICE_SCHEMA, CANONICAL_IR_GUARD_SCHEMA, CANONICAL_IR_RECOVERY_SCHEMA, CANONICAL_IR_UNION_SCHEMA, CANONICAL_IR_UNION_V2_SCHEMA, CANONICAL_IR_RESOLUTION_RULE_SCHEMA, CANONICAL_IR_ACTION_OFFER_SCHEMA,
    COMPILER_TARGET_ABI, COMPILER_TARGET_CHOICE_ABI, COMPILER_TARGET_GUARD_ABI, COMPILER_TARGET_RECOVERY_ABI, COMPILER_TARGET_UNION_ABI, COMPILER_TARGET_UNION_V2_ABI, COMPILER_TARGET_RESOLUTION_RULE_ABI, COMPILER_TARGET_ACTION_OFFER_ABI,
    ARTIFACT_RESOLUTION_RULE_SCHEMA, ARTIFACT_ACTION_OFFER_SCHEMA,
    EVENT_COMPOSITION_IR_CHOICE_SCHEMA, EVENT_COMPOSITION_IR_GUARD_SCHEMA, EVENT_COMPOSITION_IR_SCHEMA,
    GRAPH_ALGORITHM_VERSION,
    REFERENCE_ALGORITHM_VERSION,
    STORY_ENGINE_SPEC_VERSION,
)

_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_AUDIENCES = ("public", "party", "actor", "dm", "admin", "author")
_AUDIENCE_RANK = {value: index for index, value in enumerate(_AUDIENCES)}
_EXIT_KINDS = {"complete", "retreat", "continue_with_cost", "human_dm"}
_GATES = {"preview", "consent", "host"}
_CHECKPOINT_FIELDS = {
    "id", "kind", "public_summary", "exit_kind", "irreversible",
    "required_gate", "recoverable", "max_visits", "timeout_exit",
}
_ROUTE_FIELDS = {"id", "from", "to", "outcome", "public_meaning", "required_capability"}
_FORBIDDEN_KEYS = {
    "adapter", "callable", "database", "delivery_target", "handler", "http_request",
    "javascript", "origin_surface", "provider", "python", "renderer", "script",
    "send_message", "sql", "url_handler", "outbox", "platform_command",
}
_V02_CANONICAL_IR_SCHEMA = "se-canonical-story-pack-ir/1.10.0"
_V02_ARTIFACT_SCHEMA = "se-story-artifact/1.10.0"
_V02_COMPILER_TARGET_ABI = "se-compiler/1.10.0"
STATIC_VISUAL_STYLE_SCHEMA = "se-static-visual-style/1.0.0"
STATIC_VISUAL_STYLE_FIELDS = frozenset({"schema", "style_ref", "instruction", "palette"})
STATIC_VISUAL_STYLE_MAX_INSTRUCTION = 1200
STATIC_VISUAL_STYLE_MAX_PALETTE = 8
_STATIC_VISUAL_STYLE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_STATIC_VISUAL_STYLE_PALETTE_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_STATIC_VISUAL_STYLE_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _plain(value: Any, *, path: str = "$") -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        _raise("compiler.number_invalid", path, "数字必须是有限值。", "删除 NaN 或无限值。")
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                _raise("compiler.key_invalid", path, "对象键必须是非空文本。", "改用稳定文本键。")
            normalized = key.strip()
            if normalized.casefold() in _FORBIDDEN_KEYS:
                _raise("compiler.platform_or_code_forbidden", f"{path}.{normalized}", "编译输入不得包含代码、平台提交、provider、adapter 或投递配置。", "删除该字段并改用公开能力合同。")
            result[normalized] = _plain(item, path=f"{path}.{normalized}")
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    _raise("compiler.non_declarative_value", path, "编译输入只允许 JSON 兼容的声明式数据。", "删除运行对象、函数或字节值。")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_thaw(item) for item in value]
    return value


def _text(value: Any, *, path: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        _raise("compiler.text_invalid", path, "字段必须是长度受限的非空文本。", "填写明确且精简的文本。")
    return value.strip()


def _identifier(value: Any, *, path: str) -> str:
    result = _text(value, path=path, maximum=128)
    if _ID_RE.fullmatch(result) is None:
        _raise("compiler.id_invalid", path, "标识不是稳定小写 ID。", "使用小写字母开头，只含字母、数字、点、下划线或短横线的 ID。")
    return result


def _satisfies(version: str, requirement: str, *, path: str) -> bool:
    try:
        return version_satisfies(version, requirement, path=path)
    except CompilerContractError:
        raise
    except Exception:
        _raise("compiler.version_invalid", path, "版本或版本范围不是有效 SemVer。", "填写明确的 SemVer 和版本范围。")


def _source_path(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts or ":" in normalized or len(normalized) > 512:
        _raise("compiler.source_path_invalid", "source_path", "来源路径必须是包内相对路径。", "使用不含盘符、上级跳转或绝对根的 POSIX 相对路径。")
    return path.as_posix()


def _compile_static_visual_style(document: Any) -> dict[str, Any]:
    """Compile one optional Story Pack art-style declaration into its frozen triple."""
    if not isinstance(document, Mapping):
        _raise("static_visual_style.object_invalid", "static_visual_style_document", "画风声明必须是一个对象。", "提供 se-static-visual-style/1.0.0 声明对象。")
    unknown = sorted(set(document) - STATIC_VISUAL_STYLE_FIELDS)
    if unknown:
        _raise("static_visual_style.field_unknown", "static_visual_style_document", "画风声明包含未知字段：" + "、".join(unknown), "只声明 schema、style_ref、instruction 与 palette。")
    missing = sorted(STATIC_VISUAL_STYLE_FIELDS - set(document))
    if missing:
        _raise("static_visual_style.field_missing", "static_visual_style_document", "画风声明缺少字段：" + "、".join(missing), "补齐 schema、style_ref、instruction 与 palette。")
    if document["schema"] != STATIC_VISUAL_STYLE_SCHEMA:
        _raise("static_visual_style.schema_unsupported", "static_visual_style_document.schema", "画风声明必须使用 " + STATIC_VISUAL_STYLE_SCHEMA + "。", "改写为当前 Engine 声明的 schema。")
    style_ref = document["style_ref"]
    if not isinstance(style_ref, str) or _STATIC_VISUAL_STYLE_REF_RE.fullmatch(style_ref) is None:
        _raise("static_visual_style.reference_invalid", "static_visual_style_document.style_ref", "style_ref 必须是不超过 128 个字符的稳定 ASCII 引用。", "使用以字母或数字开头、只含字母数字点号、下划线、冒号与连字符的稳定引用。")
    instruction = document["instruction"]
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction.strip()) > STATIC_VISUAL_STYLE_MAX_INSTRUCTION or _STATIC_VISUAL_STYLE_CONTROL_RE.search(instruction):
        _raise("static_visual_style.text_invalid", "static_visual_style_document.instruction", f"instruction 必须是 1 到 {STATIC_VISUAL_STYLE_MAX_INSTRUCTION} 个字符、不含换行或控制字符的非空文本。", "压缩画风说明并去掉换行与控制字符。")
    palette = document["palette"]
    if not isinstance(palette, Sequence) or isinstance(palette, (str, bytes, bytearray)) or not 1 <= len(palette) <= STATIC_VISUAL_STYLE_MAX_PALETTE:
        _raise("static_visual_style.palette_invalid", "static_visual_style_document.palette", f"palette 必须是 1 到 {STATIC_VISUAL_STYLE_MAX_PALETTE} 个 #RRGGBB 颜色。", "只声明正式画风使用的颜色。")
    colors: list[str] = []
    for index, item in enumerate(palette):
        if not isinstance(item, str) or _STATIC_VISUAL_STYLE_PALETTE_RE.fullmatch(item) is None:
            _raise("static_visual_style.palette_invalid", f"static_visual_style_document.palette[{index}]", "颜色必须是 #RRGGBB。", "改写为六位十六进制颜色。")
        colors.append(item)
    return {"style_ref": style_ref, "instruction": instruction.strip(), "palette": colors}


class CompilerSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class CompilerDiagnostic:
    code: str
    severity: CompilerSeverity
    source_path: str
    field_path: str
    problem: str
    impact: str
    automatic_handling: str
    next_action: str
    technical_reference: str = ""

    def to_mapping(self) -> dict[str, str]:
        return {name: str(getattr(self, name)) for name in self.__dataclass_fields__}


class CompilerContractError(ValueError):
    def __init__(self, diagnostic: CompilerDiagnostic) -> None:
        super().__init__(diagnostic.problem)
        self.diagnostic = diagnostic
        self.code = diagnostic.code


def _raise(code: str, field_path: str, problem: str, next_action: str, *, source_path: str = "", technical_reference: str = "") -> None:
    raise CompilerContractError(CompilerDiagnostic(
        code, CompilerSeverity.ERROR, source_path, field_path, problem,
        "当前故事包不会生成 Canonical IR 或运行 Artifact。",
        "未自动删字段、改引用、补业务事实或降级 required 内容。",
        next_action, technical_reference,
    ))


@dataclass(frozen=True, slots=True)
class CapabilityProvider:
    id: str
    version: str
    provider_contract_hash: str

    def __post_init__(self) -> None:
        _identifier(self.id, path="capability.id")
        _satisfies(self.version, f"=={self.version}", path="capability.version")
        if _HASH_RE.fullmatch(self.provider_contract_hash) is None:
            _raise("compiler.provider_hash_invalid", "capability.provider_contract_hash", "provider 合同 hash 必须是带 sha256: 前缀的小写 SHA-256。", "重新生成并填写 provider 合同 hash。")

    def to_mapping(self) -> dict[str, str]:
        return {"id": self.id, "version": self.version, "provider_contract_hash": self.provider_contract_hash}


class CapabilityCatalog:
    def __init__(self, providers: Sequence[CapabilityProvider], *, revision: str) -> None:
        self.revision = _identifier(revision, path="capability_catalog.revision")
        ordered = tuple(sorted(providers, key=lambda item: item.id))
        if len({item.id for item in ordered}) != len(ordered):
            _raise("compiler.capability_provider_conflict", "capability_catalog", "同一能力只能有一个冻结 provider。", "消除 provider 冲突后重编。")
        self.providers = ordered
        self._by_id = {item.id: item for item in ordered}
        self.fingerprint = _digest({"revision": self.revision, "providers": [item.to_mapping() for item in ordered]})

    def get(self, capability_id: str) -> CapabilityProvider | None:
        return self._by_id.get(capability_id)

    def to_mapping(self) -> dict[str, Any]:
        return {"revision": self.revision, "fingerprint": self.fingerprint, "providers": [item.to_mapping() for item in self.providers]}


def engine_owned_provider(capability_id: str, capability_version: str) -> CapabilityProvider:
    """Resolve one production provider tuple by exact Engine-owned identity."""
    provider = resolve_provider(capability_id, capability_version)
    return CapabilityProvider(provider["capability_id"], provider["capability_version"], provider["provider_contract_sha256"])


@dataclass(frozen=True, slots=True)
class ReferenceDescriptor:
    source_ref: str
    canonical_ref: str
    entity_type: str
    audience: str = "public"

    def __post_init__(self) -> None:
        _identifier(self.source_ref, path="reference.source_ref")
        _identifier(self.canonical_ref, path="reference.canonical_ref")
        _identifier(self.entity_type, path="reference.entity_type")
        if self.audience not in _AUDIENCE_RANK:
            _raise("compiler.reference_audience_invalid", "reference.audience", "引用 audience 不受支持。", "使用公开 audience 集合。")

    def to_mapping(self) -> dict[str, str]:
        return {"source_ref": self.source_ref, "canonical_ref": self.canonical_ref, "entity_type": self.entity_type, "audience": self.audience}


class ReferenceCatalog:
    def __init__(self, references: Sequence[ReferenceDescriptor], *, revision: str) -> None:
        self.revision = _identifier(revision, path="reference_catalog.revision")
        ordered = tuple(sorted(references, key=lambda item: item.source_ref))
        if len({item.source_ref for item in ordered}) != len(ordered):
            _raise("compiler.reference_duplicate", "reference_catalog", "来源引用不能映射到多个实体。", "保留唯一精确映射。")
        if len({item.canonical_ref for item in ordered}) != len(ordered):
            _raise("compiler.canonical_reference_duplicate", "reference_catalog", "Canonical 引用不能重复。", "修正实体索引。")
        self.references = ordered
        self._by_source = {item.source_ref: item for item in ordered}
        self.fingerprint = _digest({"revision": self.revision, "references": [item.to_mapping() for item in ordered]})

    def resolve(self, source_ref: str, *, path: str, audience: str, source_path: str) -> ReferenceDescriptor:
        item = self._by_source.get(source_ref)
        if item is None:
            _raise("compiler.reference_unresolved", path, "引用没有精确的 Canonical 映射。", "在当前故事包实体索引中声明该引用；不得按相似名称匹配。", source_path=source_path, technical_reference=source_ref)
        if _AUDIENCE_RANK[audience] < _AUDIENCE_RANK[item.audience]:
            _raise("compiler.reference_audience_leak", path, "当前字段的 audience 会暴露更受限的引用。", "收紧该字段 audience 或改用可公开引用。", source_path=source_path, technical_reference=item.canonical_ref)
        return item

    def to_mapping(self) -> dict[str, Any]:
        return {"revision": self.revision, "fingerprint": self.fingerprint}


@dataclass(frozen=True, slots=True)
class AuthorSource:
    source_path: str
    value: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_path", _source_path(self.source_path))
        if not isinstance(self.value, Mapping):
            _raise("compiler.author_source_invalid", "$", "作者源必须是对象。", "提交一个公共 event envelope。", source_path=self.source_path)


@dataclass(frozen=True, slots=True)
class EventCompositionIR:
    value: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _freeze(_plain(self.value)))

    def to_mapping(self) -> dict[str, Any]:
        return _thaw(self.value)


@dataclass(frozen=True, slots=True)
class CanonicalStoryPackIR:
    value: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _freeze(_plain(self.value)))

    @property
    def canonical_sha256(self) -> str:
        return str(self.value["canonical_sha256"])

    def to_mapping(self) -> dict[str, Any]:
        return _thaw(self.value)


@dataclass(frozen=True, slots=True)
class Artifact:
    value: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _freeze(_plain(self.value)))

    @property
    def artifact_sha256(self) -> str:
        return str(self.value["artifact_sha256"])

    def to_mapping(self) -> dict[str, Any]:
        return _thaw(self.value)


@dataclass(frozen=True, slots=True)
class CompilationResult:
    canonical_ir: CanonicalStoryPackIR
    artifact: Artifact
    diagnostics: tuple[CompilerDiagnostic, ...]
    compiler_contract_fingerprint: str


def _schema_fingerprints(
    *, guard_mode: bool = False, choice_mode: bool = False,
    conflict_mode: bool = False, recovery_mode: bool = False, union_mode: bool = False, union_v2_mode: bool = False,
    resolution_rule_mode: bool = False, action_offer_mode: bool = False,
    v02_extension_mode: bool = False,
    build_selection_mode: bool = False,
) -> dict[str, str]:
    root = Path(__file__).with_name("schemas")
    names = (
        "se-event-composition-1.0.0.schema.json",
        "se-profile-registry-1.1.0.schema.json",
        "se-canonical-story-pack-ir-1.1.0.schema.json",
        "se-story-artifact-1.1.0.schema.json",
        "actor.resource_pool-1.0.0.schema.json",
        "actor.vitality-1.0.0.schema.json",
        "typed-effect-proposal-1.0.0.schema.json",
    )
    if guard_mode:
        names = names + (
            "se-event-composition-1.1.0.schema.json", "se-condition-tree-1.0.0.schema.json",
            "se-event-composition-ir-1.1.0.schema.json",
            "se-event-guard-fact-snapshot-1.0.0.schema.json", "se-canonical-story-pack-ir-1.2.0.schema.json",
            "se-story-artifact-1.2.0.schema.json",
        )
    if choice_mode:
        names = names + (
            "se-event-composition-1.2.0.schema.json", "se-event-choice-semantics-1.0.0.schema.json",
            "se-event-composition-ir-1.2.0.schema.json", "se-canonical-story-pack-ir-1.3.0.schema.json",
            "se-story-artifact-1.3.0.schema.json",
        )
    if conflict_mode:
        # Direct file-byte identities keep author/runtime schema changes
        # independent from (and additional to) the provider contract digest.
        names = names + (
            "se-conflict-procedure-definitions-1.0.0.schema.json",
            "se-conflict-procedure-runtime-1.0.0.schema.json",
        )
    if recovery_mode:
        names = names + (
            "se-canonical-story-pack-ir-1.4.0.schema.json",
            "se-story-artifact-1.4.0.schema.json",
            "se-recovery-cycle-definitions-1.1.0.schema.json",
            "se-recovery-cycle-runtime-1.1.0.schema.json",
        )
    if union_mode:
        names = names + (
            "se-conflict-procedure-definitions-1.0.0.schema.json",
            "se-conflict-procedure-runtime-1.0.0.schema.json",
            "se-recovery-cycle-definitions-1.1.0.schema.json",
            "se-recovery-cycle-runtime-1.1.0.schema.json",
            "se-canonical-story-pack-ir-1.5.0.schema.json",
            "se-story-artifact-1.5.0.schema.json",
        )
    if union_v2_mode:
        names = names + (
            "se-conflict-procedure-definitions-1.0.0.schema.json",
            "se-conflict-procedure-runtime-1.0.0.schema.json",
            "se-recovery-cycle-definitions-1.1.0.schema.json",
            "se-recovery-cycle-runtime-1.1.0.schema.json",
            "se-recovery-cycle-definitions-2.0.0.schema.json",
            "se-recovery-cycle-runtime-2.0.0.schema.json",
            "se-provider-contracts-1.0.0.schema.json",
            "se-canonical-story-pack-ir-1.6.0.schema.json",
            "se-story-artifact-1.6.0.schema.json",
        )
    if resolution_rule_mode:
        names = names + (
            "se-resolution-rule-definition-ir-1.0.0.schema.json",
            "se-modifier-source-catalog-ir-1.0.0.schema.json",
            "se-resolution-rule-catalog-ir-1.0.0.schema.json",
            "se-canonical-story-pack-ir-1.7.0.schema.json",
            "se-story-artifact-1.7.0.schema.json",
        )
    if action_offer_mode:
        names = names + (
            "se-resolution-action-offer-catalog-ir-1.0.0.schema.json",
            "se-canonical-story-pack-ir-1.8.0.schema.json",
            "se-story-artifact-1.8.0.schema.json",
        )
    if v02_extension_mode:
        names = names + (
            "se-canonical-story-pack-ir-1.10.0.schema.json",
            "se-story-artifact-1.10.0.schema.json",
        )
    if build_selection_mode:
        names = names + ('se-character-build-definitions-1.2.0.schema.json',)
    names = tuple(dict.fromkeys(names))
    return {name: "sha256:" + hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}


def _ability_provider_schema_file_sha256(path: Path | None = None) -> str:
    schema_path = path or Path(__file__).with_name("schemas") / "se-provider-contracts-1.1.0.schema.json"
    return "sha256:" + hashlib.sha256(schema_path.read_bytes()).hexdigest()


def _compiler_fingerprint(
    capabilities: CapabilityCatalog, references: ReferenceCatalog, registry: ProfileRegistry,
    *, guard_mode: bool = False, choice_mode: bool = False,
    conflict_mode: bool = False, recovery_mode: bool = False, union_mode: bool = False, union_v2_mode: bool = False,
    ability_provider_mode: bool = False,
    resolution_rule_mode: bool = False, action_offer_mode: bool = False,
    v02_extension_mode: bool = False,
    build_selection_mode: bool = False,
) -> str:
    material = {
        "target_abi": _V02_COMPILER_TARGET_ABI if v02_extension_mode else COMPILER_TARGET_ACTION_OFFER_ABI if action_offer_mode else COMPILER_TARGET_RESOLUTION_RULE_ABI if resolution_rule_mode else COMPILER_TARGET_UNION_V2_ABI if union_v2_mode else COMPILER_TARGET_UNION_ABI if union_mode else COMPILER_TARGET_RECOVERY_ABI if recovery_mode else COMPILER_TARGET_CHOICE_ABI if choice_mode else COMPILER_TARGET_GUARD_ABI if guard_mode else COMPILER_TARGET_ABI,
        "schemas": _schema_fingerprints(
            guard_mode=guard_mode, choice_mode=choice_mode, conflict_mode=conflict_mode,
            recovery_mode=recovery_mode, union_mode=union_mode, union_v2_mode=union_v2_mode,
            resolution_rule_mode=resolution_rule_mode, action_offer_mode=action_offer_mode,
            v02_extension_mode=v02_extension_mode,
            build_selection_mode=build_selection_mode,
        ),
        "profile_registry": {"revision": registry.revision, "fingerprint": registry.fingerprint},
        "capability_catalog": capabilities.to_mapping(),
        "reference_catalog": references.to_mapping(),
        "algorithms": {"graph": GRAPH_ALGORITHM_VERSION, "reference": REFERENCE_ALGORITHM_VERSION, "budget": BUDGET_ALGORITHM_VERSION},
        "semantic_event_registry": "se-semantic-events/1.0.0",
        "condition_registry": "se-condition-tree/1.0.0",
        "effect_registry": "se-effects/1.0.0",
    }
    if union_v2_mode:
        provider_path = Path(__file__).with_name("provider_contracts.json")
        provider_contracts = json.loads(provider_path.read_text(encoding="utf-8"))
        expected = _digest({k: v for k, v in provider_contracts.items() if k != "manifest_fingerprint"})
        if provider_contracts.get("manifest_fingerprint") != expected:
            raise RuntimeError("provider_contracts.fingerprint_mismatch")
        material["provider_contracts_file_sha256"] = "sha256:" + hashlib.sha256(provider_path.read_bytes()).hexdigest()
        material["provider_contracts_fingerprint"] = expected
    if ability_provider_mode:
        provider_contracts = load_provider_manifest()
        material["ability_provider_contracts_file_sha256"] = provider_manifest_file_sha256()
        material["ability_provider_schema_file_sha256"] = _ability_provider_schema_file_sha256()
        material["ability_provider_contracts_fingerprint"] = provider_contracts["manifest_fingerprint"]
        material["ability_provider_contract_sha256"] = resolve_provider("ability.execution", "1.0.0")["provider_contract_sha256"]
    return _digest(material)


def _field_audience(envelope: EventAuthorEnvelope, path: str) -> str:
    exact = envelope.visibility.audiences.get(path)
    if exact is not None:
        return exact
    candidates = [(key, value) for key, value in envelope.visibility.audiences.items() if path == key or path.startswith(key + ".") or path.startswith(key + "[")]
    return max(candidates, key=lambda item: len(item[0]))[1] if candidates else envelope.visibility.default


def _reference_occurrences(value: Any, *, path: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            normalized = str(key).casefold()
            if normalized in {
                "fact_ref", "initial_checkpoint_ref", "checkpoint_ref", "phase_ref", "guard_ref", "route_ref", "choice_ref", "policy_ref", "definition_ref", "rule_ref", "recipe_ref", "progression_ref",
                "human_dm_checkpoint_ref", "aftermath_checkpoint_ref", "fate_checkpoint_ref", "terminal_checkpoint_ref",
            }:
                continue
            if normalized.endswith("_ref") and isinstance(item, str):
                found.append((child, item))
            elif normalized.endswith("_refs") and isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
                found.extend((f"{child}[{index}]", ref) for index, ref in enumerate(item) if isinstance(ref, str))
            found.extend(_reference_occurrences(item, path=child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            found.extend(_reference_occurrences(item, path=f"{path}[{index}]"))
    return found


def _checkpoint_graph(envelope: EventAuthorEnvelope, present_caps: set[str], *, source_path: str, diagnostics: list[CompilerDiagnostic]) -> dict[str, Any]:
    declared_caps = {item.id for item in envelope.requires_capabilities} | {item.id for item in envelope.optional_capabilities}
    nodes: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(envelope.checkpoints):
        path = f"checkpoints[{index}]"
        unknown = set(raw) - _CHECKPOINT_FIELDS
        if unknown:
            _raise("compiler.checkpoint_field_unknown", path, "检查点包含未知字段：" + "、".join(sorted(unknown)), "只使用冻结的检查点字段。", source_path=source_path)
        node_id = _identifier(raw.get("id"), path=f"{path}.id")
        if node_id in nodes:
            _raise("compiler.checkpoint_duplicate", f"{path}.id", "检查点 ID 重复。", "为每个检查点使用唯一 ID。", source_path=source_path)
        kind = _identifier(raw.get("kind"), path=f"{path}.kind")
        summary = _text(raw.get("public_summary"), path=f"{path}.public_summary", maximum=240)
        exit_kind = str(raw.get("exit_kind") or "")
        if exit_kind and exit_kind not in _EXIT_KINDS:
            _raise("compiler.exit_kind_invalid", f"{path}.exit_kind", "退出类型不受支持。", "选择完成、撤退、带代价继续或 human DM 接管。", source_path=source_path)
        irreversible = raw.get("irreversible", False)
        recoverable = raw.get("recoverable", True)
        max_visits = raw.get("max_visits", 1)
        if not isinstance(irreversible, bool) or not isinstance(recoverable, bool) or isinstance(max_visits, bool) or not isinstance(max_visits, int) or max_visits < 1:
            _raise("compiler.checkpoint_value_invalid", path, "检查点布尔值或 max_visits 无效。", "使用布尔值和大于零的 max_visits。", source_path=source_path)
        gate = str(raw.get("required_gate") or "")
        if gate and gate not in _GATES:
            _raise("compiler.gate_invalid", f"{path}.required_gate", "不可逆 gate 类型不受支持。", "选择 preview、consent 或 host。", source_path=source_path)
        if irreversible and not gate:
            _raise("compiler.irreversible_gate_missing", path, "不可逆检查点前缺少 preview、consent 或 host gate。", "声明 required_gate 后重编。", source_path=source_path)
        timeout_exit = str(raw.get("timeout_exit") or "")
        nodes[node_id] = {"id": node_id, "kind": kind, "public_summary": summary, "exit_kind": exit_kind, "irreversible": irreversible, "required_gate": gate, "recoverable": recoverable, "max_visits": max_visits, "timeout_exit": timeout_exit}

    edges: list[dict[str, Any]] = []
    edge_ids: set[str] = set()
    for index, raw in enumerate(envelope.routes):
        path = f"routes[{index}]"
        unknown = set(raw) - _ROUTE_FIELDS
        if unknown:
            _raise("compiler.route_field_unknown", path, "路线包含未知字段：" + "、".join(sorted(unknown)), "只使用冻结的路线字段。", source_path=source_path)
        route_id = _identifier(raw.get("id"), path=f"{path}.id")
        if route_id in edge_ids:
            _raise("compiler.route_duplicate", f"{path}.id", "路线 ID 重复。", "为每条路线使用唯一 ID。", source_path=source_path)
        edge_ids.add(route_id)
        source = _identifier(raw.get("from"), path=f"{path}.from")
        target = _identifier(raw.get("to"), path=f"{path}.to")
        if source not in nodes or target not in nodes:
            _raise("compiler.route_endpoint_unknown", path, "路线端点不是已声明检查点。", "修正 from/to 为现有检查点 ID。", source_path=source_path)
        capability = str(raw.get("required_capability") or "")
        if capability:
            capability = _identifier(capability, path=f"{path}.required_capability")
            if capability not in declared_caps:
                _raise("compiler.route_capability_undeclared", f"{path}.required_capability", "路线能力没有列入 required 或 optional capability。", "在作者 envelope 中声明版本化能力要求。", source_path=source_path)
            if capability not in present_caps:
                diagnostics.append(CompilerDiagnostic(
                    "compiler.optional_route_pruned", CompilerSeverity.WARNING, source_path, path,
                    "路线依赖的 optional 能力当前缺席。", "该路线不会进入本次 Artifact，并已重新执行可达性检查。",
                    "仅裁剪这条显式 optional 路线；没有修改作者源。", "安装匹配能力或补充不依赖该能力的出口。", capability,
                ))
                continue
        edges.append({"id": route_id, "from": source, "to": target, "outcome": _identifier(raw.get("outcome"), path=f"{path}.outcome"), "public_meaning": _text(raw.get("public_meaning"), path=f"{path}.public_meaning", maximum=240), "required_capability": capability})

    edges.sort(key=lambda item: item["id"])
    adjacency = {node: [] for node in nodes}
    for edge in edges:
        adjacency[edge["from"]].append(edge["to"])
    exits = sorted(node for node, value in nodes.items() if value["exit_kind"])
    if nodes and not exits:
        _raise("compiler.graph_exit_missing", "checkpoints", "检查点图没有完成、撤退、带代价继续或 human DM 出口。", "至少声明一个 exit_kind。", source_path=source_path)
    for start in sorted(nodes):
        queue = deque([start]); seen = {start}; reachable = False
        while queue:
            current = queue.popleft()
            if current in exits:
                reachable = True; break
            for target in adjacency[current]:
                if target not in seen:
                    seen.add(target); queue.append(target)
        if not reachable:
            _raise("compiler.graph_node_without_exit", f"checkpoints.{start}", "检查点没有可达出口。", "增加通向完成、撤退、带代价继续或 human DM 的路线。", source_path=source_path)

    # Tarjan SCC; every cyclic component must be explicitly bounded and recoverable.
    index = 0; stack: list[str] = []; on_stack: set[str] = set(); indices: dict[str, int] = {}; low: dict[str, int] = {}; components: list[list[str]] = []
    def visit(node: str) -> None:
        nonlocal index
        indices[node] = low[node] = index; index += 1; stack.append(node); on_stack.add(node)
        for target in adjacency[node]:
            if target not in indices:
                visit(target); low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], indices[target])
        if low[node] == indices[node]:
            component: list[str] = []
            while True:
                current = stack.pop(); on_stack.remove(current); component.append(current)
                if current == node: break
            components.append(sorted(component))
    for node in sorted(nodes):
        if node not in indices: visit(node)
    loops: list[dict[str, Any]] = []
    for component in components:
        cyclic = len(component) > 1 or any(target == component[0] for target in adjacency[component[0]])
        if not cyclic: continue
        for node in component:
            value = nodes[node]
            if value["max_visits"] <= 1 or not value["recoverable"] or not value["timeout_exit"] or value["timeout_exit"] not in exits:
                _raise("compiler.graph_loop_unbounded", f"checkpoints.{node}", "循环检查点缺少最大次数、可恢复标志或有效超时出口。", "设置 max_visits>1、recoverable=true 和指向出口的 timeout_exit。", source_path=source_path)
            if value["max_visits"] > envelope.budgets.max_loop_iterations:
                _raise("compiler.graph_loop_budget_exceeded", f"checkpoints.{node}.max_visits", "循环次数超过事件预算。", "降低 max_visits 或在 profile 上限内调整 max_loop_iterations。", source_path=source_path)
        loops.append({"nodes": component, "max_visits": max(nodes[node]["max_visits"] for node in component), "timeout_exits": sorted({nodes[node]["timeout_exit"] for node in component})})
    if len(nodes) > envelope.budgets.max_checkpoints:
        _raise("compiler.checkpoint_budget_exceeded", "checkpoints", "实际检查点数量超过事件预算。", "减少检查点或在 profile 上限内调整 max_checkpoints。", source_path=source_path)
    if len(envelope.effects) > envelope.budgets.max_cross_module_effects:
        _raise("compiler.effect_budget_exceeded", "effects", "效果数量超过跨模块效果预算。", "减少效果或在 profile 上限内调整预算。", source_path=source_path)
    return {"nodes": [nodes[key] for key in sorted(nodes)], "edges": edges, "bounded_loops": loops, "reachable_exits": exits}


def _compile_event(source: AuthorSource, capabilities: CapabilityCatalog, references: ReferenceCatalog, registry: ProfileRegistry, fingerprint: str, diagnostics: list[CompilerDiagnostic], interaction_catalog: Mapping[str, Any] | None = None, resolution_catalog: Mapping[str, Any] | None = None, build_catalog: Mapping[str, Any] | None = None, progression_catalog: Mapping[str, Any] | None = None, reward_catalog: Mapping[str, Any] | None = None, inventory_catalog: Mapping[str, Any] | None = None, ability_catalog: Mapping[str, Any] | None = None, conflict_catalog: Mapping[str, Any] | None = None, recovery_catalog: Mapping[str, Any] | None = None) -> dict[str, Any]:
    try:
        envelope = registry.parse(source.value)
    except AuthoringContractError as exc:
        diagnostic = getattr(exc, "diagnostic", None)
        if diagnostic is not None:
            _raise(str(diagnostic.code), str(diagnostic.field_path), str(diagnostic.problem), str(diagnostic.next_action), source_path=source.source_path)
        raise
    required: list[dict[str, str]] = []
    optional_present: list[dict[str, str]] = []
    present_ids: set[str] = set()
    for requirement in envelope.requires_capabilities:
        provider = capabilities.get(requirement.id)
        if provider is None:
            _raise("compiler.capability_required_missing", "requires_capabilities", f"必需能力 {requirement.id} 缺席。", "安装并冻结满足版本范围的能力 provider。", source_path=source.source_path, technical_reference=requirement.id)
        if not _satisfies(provider.version, requirement.version_range, path="requires_capabilities"):
            _raise("compiler.capability_version_mismatch", "requires_capabilities", f"能力 {requirement.id} 的 provider 版本不满足作者范围。", "升级 provider 或调整作者源版本范围。", source_path=source.source_path, technical_reference=provider.version)
        required.append(provider.to_mapping()); present_ids.add(provider.id)
    for requirement in envelope.optional_capabilities:
        provider = capabilities.get(requirement.id)
        if provider is not None and _satisfies(provider.version, requirement.version_range, path="optional_capabilities"):
            optional_present.append(provider.to_mapping()); present_ids.add(provider.id)
    required_by_id = {item.id: item for item in envelope.requires_capabilities}
    optional_by_id = {item.id: item for item in envelope.optional_capabilities}
    compiled_extensions: dict[str, Any] = {}
    for extension_key, extension_value in sorted(envelope.extensions.items()):
        if extension_key == TURN_INTERACTION_CAPABILITY:
            if interaction_catalog is None:
                _raise("interaction.policy_catalog_missing", f"extensions.{extension_key}", "事件引用交互政策但编译输入没有政策目录。", "提供 se-turn-interaction-policies/1.0.0 作者文档。", source_path=source.source_path)
            compiled_extensions[extension_key] = _plain(extension_value, path=f"extensions.{extension_key}")
            continue
        if extension_key == RESOLUTION_CHECK_CAPABILITY:
            if resolution_catalog is None:
                _raise("resolution.definition_catalog_missing", f"extensions.{extension_key}", "事件引用检定定义但编译输入没有定义目录。", "提供 se-resolution-check-definitions/1.0.0 作者文档。", source_path=source.source_path)
            provider = capabilities.get("resolution.check")
            if provider is None or provider.version != "1.0.0":
                _raise("compiler.extension_provider_mismatch", f"extensions.{extension_key}", "resolution extension 没有精确 1.0.0 provider。", "安装并冻结 resolution.check/1.0.0。", source_path=source.source_path)
            compiled_extensions[extension_key] = _plain(extension_value, path=f"extensions.{extension_key}")
            continue
        if extension_key == CHARACTER_BUILD_CAPABILITY:
            if build_catalog is None:_raise("character_build.catalog_missing",f"extensions.{extension_key}","事件引用建角 recipe 但编译输入缺少目录。","提供 se-character-build-definitions/1.0.0。",source_path=source.source_path)
            provider=capabilities.get("character.build")
            if provider is None or provider.version!="1.0.0":_raise("compiler.extension_provider_mismatch",f"extensions.{extension_key}","character.build provider 缺失或版本不精确。","注册 character.build/1.0.0。",source_path=source.source_path)
            compiled_extensions[extension_key]=_plain(extension_value,path=f"extensions.{extension_key}");continue
        if extension_key == CHARACTER_PROGRESSION_CAPABILITY:
            if progression_catalog is None:_raise("progression.catalog_missing",f"extensions.{extension_key}","事件引用 progression definition 但缺少目录。","提供 se-character-progression-definitions/1.0.0。",source_path=source.source_path)
            provider=capabilities.get("character.progression")
            if provider is None or provider.version!="1.0.0":_raise("compiler.extension_provider_mismatch",f"extensions.{extension_key}","character.progression provider 缺失或版本不精确。","注册 character.progression/1.0.0。",source_path=source.source_path)
            compiled_extensions[extension_key]=_plain(extension_value,path=f"extensions.{extension_key}");continue
        if extension_key == REWARD_SETTLEMENT_CAPABILITY:
            if reward_catalog is None:_raise("reward.catalog_missing",f"extensions.{extension_key}","事件引用 reward definition 但缺少目录。","提供 se-reward-settlement-definitions/1.0.0。",source_path=source.source_path)
            provider=capabilities.get("reward.settlement")
            if provider is None or provider.version!="1.0.0":_raise("compiler.extension_provider_mismatch",f"extensions.{extension_key}","reward.settlement provider 缺失或版本不精确。","注册 reward.settlement/1.0.0。",source_path=source.source_path)
            compiled_extensions[extension_key]=_plain(extension_value,path=f"extensions.{extension_key}");continue
        if extension_key == INVENTORY_EQUIPMENT_CAPABILITY:
            if inventory_catalog is None:_raise("inventory.catalog_missing",f"extensions.{extension_key}","inventory catalog missing","provide inventory definitions",source_path=source.source_path)
            provider=capabilities.get("inventory.equipment")
            if provider is None or provider.version!="1.0.0":_raise("compiler.extension_provider_mismatch",f"extensions.{extension_key}","inventory provider missing","register inventory.equipment/1.0.0",source_path=source.source_path)
            compiled_extensions[extension_key]=_plain(extension_value,path=f"extensions.{extension_key}");continue
        if extension_key == ABILITY_EXECUTION_CAPABILITY:
            if ability_catalog is None:_raise("ability.catalog_missing",f"extensions.{extension_key}","ability catalog missing","provide ability definitions",source_path=source.source_path)
            provider=capabilities.get("ability.execution")
            if provider is None or provider.version!="1.0.0":_raise("compiler.extension_provider_mismatch",f"extensions.{extension_key}","ability provider missing","register ability.execution/1.0.0",source_path=source.source_path)
            compiled_extensions[extension_key]=_plain(extension_value,path=f"extensions.{extension_key}");continue
        if extension_key == CONFLICT_PROCEDURE_CAPABILITY:
            if (envelope.profile, envelope.profile_version) != ("conflict_event", "1.0.0"):
                _raise("conflict.profile_required", f"extensions.{extension_key}", "conflict procedure extension requires conflict_event@1.0.0.", "Select conflict_event@1.0.0 from the explicit conflict-v3 successor Registry.", source_path=source.source_path)
            if conflict_catalog is None:_raise("conflict.catalog_missing",f"extensions.{extension_key}","conflict catalog missing","provide conflict definitions",source_path=source.source_path)
            if required_by_id.get("conflict.procedure") is None and optional_by_id.get("conflict.procedure") is None:_raise("compiler.extension_capability_undeclared",f"extensions.{extension_key}","conflict extension capability undeclared","declare conflict.procedure in required/optional capabilities",source_path=source.source_path)
            provider=capabilities.get("conflict.procedure")
            if provider is None or provider.version!="1.0.0":_raise("compiler.extension_provider_mismatch",f"extensions.{extension_key}","conflict provider missing","register conflict.procedure/1.0.0",source_path=source.source_path)
            compiled_extensions[extension_key]=_plain(extension_value,path=f"extensions.{extension_key}");continue
        if extension_key in {RECOVERY_CYCLE_CAPABILITY, RECOVERY_CYCLE_V2_CAPABILITY}:
            expected_version = "2.0.0" if extension_key == RECOVERY_CYCLE_V2_CAPABILITY else "1.1.0"
            expected_profile = "2.0.0" if extension_key == RECOVERY_CYCLE_V2_CAPABILITY else "1.0.0"
            if (envelope.profile, envelope.profile_version) != ("recovery_event", expected_profile):
                _raise("recovery.profile_required", f"extensions.{extension_key}", f"recovery cycle {expected_version} requires recovery_event@{expected_profile}", "Select the exact Recovery or union successor Registry", source_path=source.source_path)
            if recovery_catalog is None:
                _raise("recovery.catalog_missing", f"extensions.{extension_key}", "recovery catalog missing", f"provide se-recovery-cycle-definitions/{expected_version}", source_path=source.source_path)
            if required_by_id.get("recovery.cycle") is None and optional_by_id.get("recovery.cycle") is None:
                _raise("compiler.extension_capability_undeclared", f"extensions.{extension_key}", "recovery extension capability undeclared", "declare recovery.cycle in required/optional capabilities", source_path=source.source_path)
            provider = capabilities.get("recovery.cycle")
            if provider is None or provider.version != expected_version:
                _raise("compiler.extension_provider_mismatch", f"extensions.{extension_key}", f"recovery provider missing or not exact {expected_version}", f"register recovery.cycle/{expected_version}", source_path=source.source_path)
            compiled_extensions[extension_key] = _plain(extension_value, path=f"extensions.{extension_key}")
            continue
        if "/" not in extension_key:
            _raise("compiler.extension_key_invalid", f"extensions.{extension_key}", "extension key 缺少稳定命名空间或版本。", "使用 capability.id/SemVer 格式。", source_path=source.source_path)
        capability_id, extension_version = extension_key.rsplit("/", 1)
        capability_id = _identifier(capability_id, path=f"extensions.{extension_key}")
        requirement = required_by_id.get(capability_id) or optional_by_id.get(capability_id)
        if requirement is None:
            _raise("compiler.extension_capability_undeclared", f"extensions.{extension_key}", "extension 没有对应的 required 或 optional capability。", "同时声明同命名空间的版本化 capability。", source_path=source.source_path)
        if not _satisfies(extension_version, requirement.version_range, path=f"extensions.{extension_key}"):
            _raise("compiler.extension_version_mismatch", f"extensions.{extension_key}", "extension 版本不满足能力要求范围。", "统一 extension key、能力范围和 provider 版本。", source_path=source.source_path)
        provider = capabilities.get(capability_id)
        if provider is None and capability_id in optional_by_id:
            diagnostics.append(CompilerDiagnostic(
                "compiler.optional_extension_ignored", CompilerSeverity.WARNING, source.source_path, f"extensions.{extension_key}",
                "optional extension 的 provider 当前缺席。", "该扩展不会进入本次 Artifact；核心路线保持可达。",
                "按 optional 注册政策忽略扩展纯数据，没有执行内容。", "安装匹配 provider 后重新编译。", extension_key,
            ))
            continue
        if provider is None or provider.version != extension_version:
            _raise("compiler.extension_provider_mismatch", f"extensions.{extension_key}", "extension 没有精确版本的冻结 provider 合同。", "安装与 extension key 版本一致的 provider。", source_path=source.source_path)
        compiled_extensions[extension_key] = _plain(extension_value, path=f"extensions.{extension_key}")
    if (envelope.profile, envelope.profile_version) == ("conflict_event", "1.0.0") and CONFLICT_PROCEDURE_CAPABILITY not in compiled_extensions:
        _raise("conflict.extension_required", "extensions", "conflict_event@1.0.0 requires an explicit conflict procedure binding.", "Declare conflict.procedure/1.0.0 and bind one procedure_ref extension.", source_path=source.source_path)
    if (envelope.profile, envelope.profile_version) == ("recovery_event", "1.0.0") and RECOVERY_CYCLE_CAPABILITY not in compiled_extensions:
        _raise("recovery.extension_required", "extensions", "recovery_event@1.0.0 requires an explicit recovery cycle binding", "Declare recovery.cycle/1.1.0 and bind one recovery_ref extension", source_path=source.source_path)
    if (envelope.profile, envelope.profile_version) == ("recovery_event", "2.0.0") and RECOVERY_CYCLE_V2_CAPABILITY not in compiled_extensions:
        _raise("recovery.extension_required", "extensions", "recovery_event@2.0.0 requires an explicit recovery 2.0 binding", "Declare recovery.cycle/2.0.0 and bind one recovery_ref extension", source_path=source.source_path)
    choice_mode = envelope.schema == AUTHOR_ENVELOPE_CHOICE_SCHEMA
    guard_mode = envelope.schema in {AUTHOR_ENVELOPE_GUARD_SCHEMA, AUTHOR_ENVELOPE_CHOICE_SCHEMA}
    fact_catalog = None
    guard_tree = None
    if guard_mode:
        if GUARD_CAPABILITY.rsplit("/", 1)[0] not in required_by_id:
            _raise("compiler.guard_capability_missing", "requires_capabilities", "guard evaluator capability must be required.", "Declare event.guard.evaluate >=1.0.0 <2.0.0.", source_path=source.source_path)
        if not envelope.guards:
            _raise("compiler.guard_condition_invalid", "guards", "guard authoring requires at least one condition tree.", "Declare one strict condition tree.", source_path=source.source_path)
        try:
            assert envelope.fact_catalog is not None
            fact_catalog = FactCatalog.from_mapping(envelope.fact_catalog)
            root = envelope.guards[0] if len(envelope.guards) == 1 else {"op": "all", "args": list(envelope.guards)}
            guard_tree = normalize_condition_tree(root, fact_catalog)
        except ConditionContractError as exc:
            _raise(exc.code, exc.path, exc.reason, "Fix the registered fact catalog or strict condition tree.", source_path=source.source_path)
    graph = _checkpoint_graph(envelope, present_ids, source_path=source.source_path, diagnostics=diagnostics)
    if (envelope.profile,envelope.profile_version)==('crisis_event','1.2.0'):
        from .event_composition import validate_crisis_r2_graph
        try:validate_crisis_r2_graph(envelope.profile_data,graph,envelope.initial_checkpoint_ref,envelope.choice_sets,envelope.effects,envelope.extensions)
        except ValueError as exc:_raise('compiler.crisis_graph_invalid','profile_data',str(exc),'Declare every scene handoff and keep preparation free of mechanical effects.',source_path=source.source_path)
    interaction_binding = None
    if TURN_INTERACTION_CAPABILITY in compiled_extensions:
        assert interaction_catalog is not None
        try:
            interaction_binding = bind_turn_interaction_policy(
                compiled_extensions[TURN_INTERACTION_CAPABILITY], interaction_catalog, graph,
                envelope.profile, envelope.profile_version,
            )
        except TurnInteractionContractError as exc:
            _raise(exc.code, exc.path, exc.reason, "修正交互政策、阶段图或 policy_ref 后重新编译。", source_path=source.source_path)
    resolution_binding = None
    if RESOLUTION_CHECK_CAPABILITY in compiled_extensions:
        assert resolution_catalog is not None
        try:
            resolution_binding = bind_resolution_check(compiled_extensions[RESOLUTION_CHECK_CAPABILITY], resolution_catalog, choice_refs=[item['choice_ref'] for group in envelope.choice_sets for item in group['choices']])
        except ResolutionCheckContractError as exc:
            _raise(exc.code, exc.path, exc.reason, "修正检定定义或 definition_ref 后重新编译。", source_path=source.source_path)
    build_binding=None
    if CHARACTER_BUILD_CAPABILITY in compiled_extensions:
        assert build_catalog is not None
        try:build_binding=bind_character_build(compiled_extensions[CHARACTER_BUILD_CAPABILITY],build_catalog)
        except CharacterBuildContractError as exc:_raise(exc.code,exc.path,exc.reason,"修正 build recipe 或 recipe_ref。",source_path=source.source_path)
    progression_binding=None
    if CHARACTER_PROGRESSION_CAPABILITY in compiled_extensions:
        assert progression_catalog is not None
        try:progression_binding=bind_character_progression(compiled_extensions[CHARACTER_PROGRESSION_CAPABILITY],progression_catalog)
        except CharacterProgressionContractError as exc:_raise(exc.code,exc.path,exc.reason,"修正 progression definition/ref。",source_path=source.source_path)
    reward_binding=None
    if REWARD_SETTLEMENT_CAPABILITY in compiled_extensions:
        assert reward_catalog is not None
        try:reward_binding=bind_reward_settlement(compiled_extensions[REWARD_SETTLEMENT_CAPABILITY],reward_catalog)
        except RewardSettlementContractError as exc:_raise(exc.code,exc.path,exc.reason,"修正 reward definition/ref。",source_path=source.source_path)
    inventory_binding=None
    if INVENTORY_EQUIPMENT_CAPABILITY in compiled_extensions:
        assert inventory_catalog is not None
        try:inventory_binding=bind_inventory_equipment(compiled_extensions[INVENTORY_EQUIPMENT_CAPABILITY],inventory_catalog)
        except InventoryEquipmentContractError as exc:_raise(exc.code,exc.path,exc.reason,"fix inventory refs",source_path=source.source_path)
    ability_binding=None
    if ABILITY_EXECUTION_CAPABILITY in compiled_extensions:
        assert ability_catalog is not None
        try:ability_binding=bind_ability_execution(compiled_extensions[ABILITY_EXECUTION_CAPABILITY],ability_catalog)
        except AbilityExecutionContractError as exc:_raise(exc.code,exc.path,exc.reason,"fix ability refs",source_path=source.source_path)
    conflict_binding=None
    if CONFLICT_PROCEDURE_CAPABILITY in compiled_extensions:
        assert conflict_catalog is not None
        try:conflict_binding=bind_conflict_procedure(compiled_extensions[CONFLICT_PROCEDURE_CAPABILITY],conflict_catalog)
        except ConflictProcedureContractError as exc:_raise(exc.code,exc.path,exc.reason,"fix conflict procedure ref",source_path=source.source_path)
    recovery_binding = None
    recovery_extension_key = RECOVERY_CYCLE_V2_CAPABILITY if RECOVERY_CYCLE_V2_CAPABILITY in compiled_extensions else RECOVERY_CYCLE_CAPABILITY if RECOVERY_CYCLE_CAPABILITY in compiled_extensions else None
    if recovery_extension_key is not None:
        assert recovery_catalog is not None
        try:
            recovery_binding = bind_recovery_cycle_v2(compiled_extensions[recovery_extension_key], recovery_catalog) if recovery_extension_key == RECOVERY_CYCLE_V2_CAPABILITY else bind_recovery_cycle(compiled_extensions[recovery_extension_key], recovery_catalog)
        except (RecoveryCycleContractError, RecoveryCycleV2ContractError) as exc:
            _raise(exc.code, exc.path, exc.reason, "fix recovery definition refs", source_path=source.source_path)
        if envelope.profile_data.get("recovery_ref") != recovery_binding["recovery_ref"]:
            _raise(
                "recovery.profile_binding_mismatch", "profile_data.recovery_ref",
                "recovery Profile data and extension binding select different definitions",
                f"use the same catalog-backed recovery_ref in profile_data and {recovery_extension_key}",
                source_path=source.source_path,
            )
    catastrophic_contract = None
    if envelope.profile == "catastrophic_event" and envelope.profile_version == CATASTROPHIC_PROFILE_VERSION:
        try:
            catastrophic_contract = compile_catastrophic_contract(
                envelope.to_mapping(),
                graph,
                tuple(f"{item['id']}/{item['version']}" for item in required),
            )
        except CatastrophicContractError as exc:
            _raise(exc.code, exc.path, exc.reason, "修正灾难最大链或能力子集链后重新编译。", source_path=source.source_path)
    choice_semantics = None
    if choice_mode:
        try:
            assert guard_tree is not None and envelope.initial_checkpoint_ref is not None
            choice_semantics = compile_choice_semantics(
                initial_checkpoint_ref=envelope.initial_checkpoint_ref, choice_sets=envelope.choice_sets,
                graph=graph, guard_tree_sha256=guard_tree.tree_sha256,
                owner_policy="pre_actor_build" if envelope.profile == "character_build_event" and envelope.profile_version == "1.0.0" else "actor",
            )
        except ChoiceContractError as exc:
            _raise(exc.code, exc.path, exc.reason, "Fix the explicit activation root or choice semantics.", source_path=source.source_path)
    frozen_refs: dict[str, dict[str, str]] = {}
    resolved_refs: dict[str, str] = {}
    for path, source_ref in [(f"scope.refs[{index}]", item) for index, item in enumerate(envelope.scope.refs)] + _reference_occurrences(envelope.to_mapping()):
        if path.startswith(f"extensions.{INVENTORY_EQUIPMENT_CAPABILITY}.item_refs") or path.startswith(f"extensions.{ABILITY_EXECUTION_CAPABILITY}.ability_refs") or path in {f"extensions.{RECOVERY_CYCLE_CAPABILITY}.recovery_ref", f"extensions.{RECOVERY_CYCLE_V2_CAPABILITY}.recovery_ref", "profile_data.recovery_ref"}:
            continue  # Exact colon-bearing refs are validated and hash-bound by their dedicated catalog binders.
        audience = _field_audience(envelope, path)
        if (envelope.profile,envelope.profile_version)==('crisis_event','1.2.0') and (
            path.startswith('profile_data.scene_checkpoint_refs[') or path.startswith('profile_data.preparation_route_refs[')
            or path in {'profile_data.decision_checkpoint_ref','profile_data.host_handoff_checkpoint_ref'}
        ):
            continue  # Exact local graph identities were checked above.
        descriptor = references.resolve(source_ref, path=path, audience=audience, source_path=source.source_path)
        frozen_refs[descriptor.canonical_ref] = descriptor.to_mapping()
        resolved_refs[source_ref] = descriptor.canonical_ref
    active_routes = {item["id"] for item in graph["edges"]}
    compiled_effects: list[dict[str, Any]] = []
    for index, raw in enumerate(envelope.effects):
        route_id, capability_id = str(raw["route_id"]), str(raw["capability_id"])
        if route_id not in active_routes or capability_id not in present_ids:
            diagnostics.append(CompilerDiagnostic(
                "compiler.optional_effect_pruned", CompilerSeverity.WARNING, source.source_path, f"effects[{index}]",
                "effect 依赖的 optional 路线或能力当前缺席。", "该 effect 不会进入本次 Artifact。",
                "仅裁剪这条显式 optional effect；没有修改作者源。", "安装匹配能力后重新编译。", str(raw["id"]),
            ))
            continue
        provider = capabilities.get(capability_id)
        assert provider is not None
        compiled_effects.append({
            "id": str(raw["id"]), "route_id": route_id, "capability_ref": f"{capability_id}/{provider.version}",
            "effect_type": str(raw["effect_type"]), "target_ref": resolved_refs[str(raw["target_ref"])],
            "revision_source": str(raw["revision_source"]), "payload": _plain(raw["payload"], path=f"effects[{index}].payload"),
            "reversible": bool(raw["reversible"]), "gate_checkpoint_ref": str(raw["gate_id"]) if raw.get("gate_id") is not None else None,
        })
    compiled_effects.sort(key=lambda item: item["id"])
    material = envelope.to_mapping()
    definition_hash = _digest(material)
    event = {
        "schema": EVENT_COMPOSITION_IR_CHOICE_SCHEMA if choice_mode else EVENT_COMPOSITION_IR_GUARD_SCHEMA if guard_mode else EVENT_COMPOSITION_IR_SCHEMA,
        "profile": envelope.profile,
        "profile_version": envelope.profile_version,
        "source": {"source_path": source.source_path, "definition_hash": definition_hash, "compiler_contract_fingerprint": fingerprint},
        "identity": material["identity"], "scope": material["scope"], "visibility": material["visibility"],
        "capability_closure": {"required": sorted(required, key=lambda item: item["id"]), "optional_present": sorted(optional_present, key=lambda item: item["id"]), "provider_contract_hashes": {item["id"]: item["provider_contract_hash"] for item in sorted(required + optional_present, key=lambda item: item["id"])}},
        "trigger_plan": material["trigger"],
        "density_policy": {"group": envelope.density_group, "minimum_round": envelope.minimum_round, "cooldown": envelope.cooldown, "once": envelope.once},
        "checkpoint_graph": graph,
        "frozen_refs": [frozen_refs[key] for key in sorted(frozen_refs)],
        "consequence_and_consent_gates": [{"checkpoint_id": item["id"], "gate": item["required_gate"]} for item in graph["nodes"] if item["required_gate"]],
        "idempotency_templates": {"start": "{operation_id}:event:start", "advance": "{operation_id}:event:{checkpoint_id}:{route_id}"},
        "proposal_plans": {"receipt": True, "causal": True, "audit": True, "projection_audiences": sorted(set([envelope.visibility.default, *envelope.visibility.audiences.values()]))},
        "resource_budgets": envelope.budgets.to_mapping(),
        "cancellation_policy": envelope.cancellation_policy,
        "profile_data": material["profile_data"], "omens": material["omens"], "effects": compiled_effects, "extensions": compiled_extensions,
        "compile_diagnostics_summary": {"warnings": 0, "errors": 0},
    }
    if guard_mode:
        assert fact_catalog is not None and guard_tree is not None
        event.update({
            "guard_contract": CONDITION_TREE_SCHEMA,
            "guard_capability": GUARD_CAPABILITY,
            "fact_catalog": fact_catalog.to_mapping(),
            "fact_catalog_sha256": fact_catalog.fingerprint,
            "guard_tree": guard_tree.to_mapping()["root"],
            "guard_tree_sha256": guard_tree.tree_sha256,
            "guard_limits": {"max_depth": guard_tree.max_depth, "node_count": guard_tree.node_count, "max_args": 16},
        })
    else:
        event["guards"] = material["guards"]
    if choice_mode:
        assert choice_semantics is not None
        event.update({
            "choice_contract": CHOICE_CONTRACT,
            "choice_capability": CHOICE_CAPABILITY,
            "required_platform_features": [CHOICE_CAPABILITY],
            "initial_checkpoint_ref": choice_semantics["initial_checkpoint_ref"],
            "choice_sets": choice_semantics["choice_sets"],
            "choice_semantics_sha256": choice_semantics["choice_semantics_sha256"],
        })
    if catastrophic_contract is not None:
        event["catastrophic_contract"] = catastrophic_contract
    if interaction_binding is not None:
        event["turn_interaction"] = interaction_binding
    if resolution_binding is not None:
        event["resolution_check"] = resolution_binding
    if build_binding is not None:event["character_build"]=build_binding
    if progression_binding is not None:event["character_progression"]=progression_binding
    if reward_binding is not None:event["reward_settlement"]=reward_binding
    if inventory_binding is not None:event["inventory_equipment"]=inventory_binding
    if ability_binding is not None:event["ability_execution"]=ability_binding
    if conflict_binding is not None:event["conflict_procedure"]=conflict_binding
    if recovery_binding is not None:event["recovery_cycle"]=recovery_binding
    event["event_ir_sha256"] = _digest(event)
    return event


def compile_story_pack(
    *,
    package_id: str,
    content_version: str,
    manifest: Mapping[str, Any],
    world: Mapping[str, Any],
    modules: Sequence[Mapping[str, Any]],
    event_sources: Sequence[AuthorSource],
    capability_catalog: CapabilityCatalog,
    reference_catalog: ReferenceCatalog,
    profile_registry: ProfileRegistry = P0_PROFILE_REGISTRY,
    resource_document: Mapping[str, Any] | None = None,
    vitality_document: Mapping[str, Any] | None = None,
    turn_interaction_document: Mapping[str, Any] | None = None,
    resolution_check_document: Mapping[str, Any] | None = None,
    resolution_rule_document: Mapping[str, Any] | None = None,
    resolution_action_offer_document: Mapping[str, Any] | None = None,
    character_build_document: Mapping[str, Any] | None = None,
    character_build_catalog_document: Mapping[str, Any] | None = None,
    character_progression_document: Mapping[str, Any] | None = None,
    reward_settlement_document: Mapping[str, Any] | None = None,
    inventory_equipment_document: Mapping[str, Any] | None = None,
    luck_rating_document: Mapping[str, Any] | None = None,
    luck_intervention_document: Mapping[str, Any] | None = None,
    luck_recipes_document: Mapping[str, Any] | None = None,
    luck_action_binding_document: Mapping[str, Any] | None = None,
    ability_execution_document: Mapping[str, Any] | None = None,
    conflict_procedure_document: Mapping[str, Any] | None = None,
    recovery_cycle_document: Mapping[str, Any] | None = None,
    offline_public_document: Mapping[str, Any] | None = None,
    openings_document: Mapping[str, Any] | None = None,
    static_visual_style_document: Mapping[str, Any] | None = None,
    v02_extension_candidate: Mapping[str, Any] | None = None,
) -> CompilationResult:
    """Compile one current-contract story pack without I/O, code execution or platform state."""
    package_id = _identifier(package_id, path="package_id")
    content_version = _text(content_version, path="content_version", maximum=64)
    _satisfies(content_version, f"=={content_version}", path="content_version")
    if not isinstance(manifest, Mapping) or not isinstance(world, Mapping):
        _raise("compiler.story_pack_section_invalid", "manifest/world", "manifest 和 world 必须是对象。", "提交纯 JSON 对象。")
    if not isinstance(modules, Sequence) or isinstance(modules, (str, bytes, bytearray)) or any(not isinstance(item, Mapping) for item in modules):
        _raise("compiler.modules_invalid", "modules", "modules 必须是对象列表。", "提交带稳定 module_id 或 id 的声明列表。")
    if not isinstance(event_sources, Sequence) or isinstance(event_sources, (str, bytes, bytearray)) or any(not isinstance(item, AuthorSource) for item in event_sources):
        _raise("compiler.event_sources_invalid", "event_sources", "event_sources 必须是 AuthorSource 列表。", "先冻结每个包内相对路径和作者对象。")
    normalized_manifest = _plain(manifest, path="manifest")
    normalized_world = _plain(world, path="world")
    normalized_v02_extension = None
    if v02_extension_candidate is not None:
        try:
            normalized_v02_extension = normalize_v02_extension_candidate(v02_extension_candidate)
        except V02ExtensionCandidateError as exc:
            _raise(exc.code, exc.path, exc.reason, "修正 v0.2 四族 aggregate 的身份、摘要或来源闭包后重新编译。")
        if normalized_v02_extension["story_pack_ref"] != package_id:
            _raise(
                "v02_extension.story_pack_identity_mismatch", "v02_extension_candidate.story_pack_ref",
                "四族 aggregate 的 Story Pack 身份与当前编译包不一致。",
                "使用由当前 package_id 的真实 Story Pack 源生成的 aggregate。",
            )
    normalized_modules = sorted((_plain(item, path=f"modules[{index}]") for index, item in enumerate(modules)), key=lambda item: str(item.get("module_id") or item.get("id") or ""))
    module_ids = [_identifier(item.get("module_id") or item.get("id"), path=f"modules[{index}].module_id") for index, item in enumerate(normalized_modules)]
    if len(set(module_ids)) != len(module_ids):
        _raise("compiler.module_id_duplicate", "modules", "模块 ID 重复。", "每个模块只保留一个当前声明。")
    if not event_sources:
        _raise("compiler.event_sources_empty", "event_sources", "当前编译没有事件作者源。", "至少提供一个公共 event envelope。")
    if len({item.source_path for item in event_sources}) != len(event_sources):
        _raise("compiler.source_path_duplicate", "event_sources", "多个事件使用同一来源路径。", "每个作者定义使用唯一包内相对路径。")
    author_schemas = {str(item.value.get("schema")) for item in event_sources}
    if not author_schemas <= {"se-event-composition/1.0.0", AUTHOR_ENVELOPE_GUARD_SCHEMA, AUTHOR_ENVELOPE_CHOICE_SCHEMA}:
        _raise("compiler.author_schema_unsupported", "event_sources", "Event sources contain an unsupported authoring schema.", "Use only the explicitly supported inherited and current event schemas.")
    choice_mode = AUTHOR_ENVELOPE_CHOICE_SCHEMA in author_schemas
    guard_mode = bool(author_schemas & {AUTHOR_ENVELOPE_GUARD_SCHEMA, AUTHOR_ENVELOPE_CHOICE_SCHEMA})
    union_mode = (
        profile_registry.revision == CONFLICT_RECOVERY_UNION_PROFILE_REGISTRY.revision
        and profile_registry.fingerprint == CONFLICT_RECOVERY_UNION_PROFILE_REGISTRY.fingerprint
    )
    if profile_registry.revision == CONFLICT_RECOVERY_UNION_PROFILE_REGISTRY.revision and not union_mode:
        _raise("engine.profile_fingerprint_mismatch", "profile_registry", "union Registry identity does not match its frozen contents", "use the exact combined successor Registry")
    union_v2_registry_mode = (
        profile_registry.revision == CONFLICT_RECOVERY_UNION_V2_PROFILE_REGISTRY.revision
        and profile_registry.fingerprint == CONFLICT_RECOVERY_UNION_V2_PROFILE_REGISTRY.fingerprint
    )
    if profile_registry.revision == CONFLICT_RECOVERY_UNION_V2_PROFILE_REGISTRY.revision and not union_v2_registry_mode:
        _raise("engine.profile_fingerprint_mismatch", "profile_registry", "union/2 Registry identity does not match its frozen contents", "use the exact union/2 successor Registry")
    if vitality_document is not None and resource_document is None:
        _raise("engine.vitality_dependency_missing", "vitality_document", "vitality 作者合同缺少 resource_pool 定义。", "同时提供 actor.resource_pool/1.0.0 作者文档。")
    try:
        resource_catalog = ResourceCatalog.from_author_document(resource_document) if resource_document is not None else None
        vitality_contract = VitalityContract.from_author_document(vitality_document, resource_catalog) if vitality_document is not None and resource_catalog is not None else None
    except ResourceContractError as exc:
        # Preserve stable resource error categories while keeping the compiler's diagnostic envelope.
        _raise(exc.code, exc.path, exc.reason, "修正资源/生命力作者合同后重新编译。")
    interaction_catalog = None
    if turn_interaction_document is not None:
        try:
            interaction_catalog = compile_turn_interaction_policies(turn_interaction_document)
            for policy in interaction_catalog["policies"]:
                for binding in policy["applicable_profiles"]:
                    profile_id, version = binding.rsplit("@", 1)
                    profile_registry.resolve(profile_id, version)
        except (TurnInteractionContractError, AuthoringContractError) as exc:
            if isinstance(exc, TurnInteractionContractError):
                _raise(exc.code, exc.path, exc.reason, "修正 turn interaction 作者文档后重新编译。")
            raise
    resolution_catalog = None
    if resolution_check_document is not None:
        try:
            resolution_catalog = compile_resolution_check_definitions(resolution_check_document)
        except ResolutionCheckContractError as exc:
            _raise(exc.code, exc.path, exc.reason, "修正 resolution check 作者文档后重新编译。")
    resolution_rule_products = None
    if resolution_rule_document is not None:
        try:
            resolution_rule_products = compile_resolution_rule_contract(resolution_rule_document, normalized_world)
        except ResolutionRuleContractError as exc:
            _raise(exc.code, exc.path, exc.reason, "修正 resolution rule candidate 或 world authority 后重新编译。")
    if resolution_action_offer_document is not None and (resolution_catalog is None or resolution_rule_products is None):
        _raise("action_offer.dependencies_missing", "resolution_action_offer_document", "action offer 必须同时绑定已编译的 resolution definition 与 resolution rule catalog。", "同时提供 resolution_check_document 和 resolution_rule_document。")
    build_catalog=None
    if character_build_document is not None:
        try:build_catalog=compile_character_build_definitions(character_build_document,character_build_catalog_document)
        except CharacterBuildContractError as exc:_raise(exc.code,exc.path,exc.reason,"修正 character build 作者文档。")
    progression_catalog=None
    if character_progression_document is not None:
        try:progression_catalog=compile_character_progression_definitions(character_progression_document)
        except CharacterProgressionContractError as exc:_raise(exc.code,exc.path,exc.reason,"修正 character progression 作者文档。")
    reward_catalog=None
    if reward_settlement_document is not None:
        try:reward_catalog=compile_reward_settlement_definitions(reward_settlement_document)
        except RewardSettlementContractError as exc:_raise(exc.code,exc.path,exc.reason,"修正 reward settlement 作者文档。")
    inventory_catalog=None
    if inventory_equipment_document is not None:
        try:inventory_catalog=compile_inventory_equipment_definitions(inventory_equipment_document)
        except InventoryEquipmentContractError as exc:_raise(exc.code,exc.path,exc.reason,"fix inventory author document")
    from .character_build_equipment import validate_equipment_inventory, BuildEquipmentError
    try: validate_equipment_inventory(build_catalog, inventory_catalog)
    except BuildEquipmentError as exc: _raise('character_build.equipment_invalid', 'character_build.selection_rules', str(exc), '补齐真实物品定义和技能媒介后重新编译。')
    luck_rating_rules=None
    if luck_rating_document is not None:
        from .luck_rating import compile_luck_rating, LuckRatingError
        try: luck_rating_rules=compile_luck_rating(luck_rating_document,build_catalog,inventory_catalog,resource_document)
        except LuckRatingError as exc: _raise('luck_rating.definition_invalid','luck_rating_document',str(exc),'修正机运资格、公式与真实资源和物品来源。')
    luck_intervention_rules=None
    if luck_intervention_document is not None:
        from .luck_intervention import compile_luck_intervention, LuckInterventionError
        try: luck_intervention_rules=compile_luck_intervention(luck_intervention_document,luck_rating_rules,build_catalog)
        except LuckInterventionError as exc: _raise('luck_intervention.definition_invalid','luck_intervention_document',str(exc),'修正机运结果、费用、次数与已编译的职业技能来源。')
    luck_recipe_catalog=None
    if luck_recipes_document is not None:
        from .luck_recipes import compile_luck_recipes, LuckRecipeError
        try: luck_recipe_catalog=compile_luck_recipes(luck_recipes_document,inventory_catalog,resource_document)
        except (LuckRecipeError,ResolutionActionOfferContractError) as exc: _raise('luck_recipes.definition_invalid','luck_recipes_document',str(exc),'修正明确的代价配方、物品来源、条件和效果消费者。')
    ability_catalog=None
    if ability_execution_document is not None:
        try:ability_catalog=compile_ability_execution_definitions(ability_execution_document)
        except AbilityExecutionContractError as exc:_raise(exc.code,exc.path,exc.reason,"fix ability author document")
        ability_provider = capability_catalog.get("ability.execution")
        expected_ability_provider = resolve_provider("ability.execution", "1.0.0")
        if ability_provider is None or ability_provider.version != expected_ability_provider["capability_version"] or ability_provider.provider_contract_hash != expected_ability_provider["provider_contract_sha256"]:
            _raise("compiler.extension_provider_mismatch", "capability_catalog.ability.execution", "ability provider missing or not the exact Engine-owned production tuple", "resolve ability.execution/1.0.0 from provider.contracts.2")
    conflict_catalog=None
    if conflict_procedure_document is not None:
        try:conflict_catalog=compile_conflict_procedure_definitions(conflict_procedure_document)
        except ConflictProcedureContractError as exc:_raise(exc.code,exc.path,exc.reason,"fix conflict procedure author document")
    recovery_catalog = None
    recovery_v2_mode = False
    if recovery_cycle_document is not None:
        recovery_v2_mode = recovery_cycle_document.get("schema") == "se-recovery-cycle-definitions/2.0.0"
        try:
            recovery_catalog = compile_recovery_cycle_v2_definitions(recovery_cycle_document) if recovery_v2_mode else compile_recovery_cycle_definitions(recovery_cycle_document)
        except (RecoveryCycleContractError, RecoveryCycleV2ContractError) as exc:_raise(exc.code,exc.path,exc.reason,"fix recovery author document")
    offline_public_catalog = None
    if offline_public_document is not None:
        if openings_document is None:
            _raise("offline_public.openings_source_missing", "openings_document", "offline public 公开轨道缺少真实开场来源闭包。", "同时提供活动 Story Pack 的 openings 文档。")
        try:offline_public_catalog=compile_offline_public(offline_public_document,openings_document)
        except OfflinePublicContractError as exc:_raise(exc.code,exc.path,exc.reason,"修正 offline public 作者声明或真实公开来源后重新编译。")
    static_visual_style = None
    if static_visual_style_document is not None:
        if normalized_v02_extension is None:
            _raise("static_visual_style.artifact_contract_unsupported", "static_visual_style_document", "只有 se-story-artifact/1.10.0 的 v0.2 编译路径携带 static_visual_style；当前 artifact 合同没有这个可选字段。", "在 v0.2 扩展候选编译路径上声明画风，或省略该声明。")
        static_visual_style = _compile_static_visual_style(static_visual_style_document)
    union_v2_mode = recovery_v2_mode and union_v2_registry_mode
    if recovery_v2_mode and not union_v2_registry_mode and profile_registry.revision != "se1-p0-recovery-v2/2":
        _raise("recovery.profile_registry_invalid", "profile_registry", "recovery 2.0 requires its exact recovery/2 or union/2 Registry", "select an explicit recovery 2.0 Registry")
    fingerprint = _compiler_fingerprint(
        capability_catalog, reference_catalog, profile_registry,
        guard_mode=guard_mode, choice_mode=choice_mode,
        conflict_mode=conflict_catalog is not None and not union_mode and not union_v2_mode,
        recovery_mode=recovery_catalog is not None and not union_mode and not recovery_v2_mode,
        union_mode=union_mode,
        union_v2_mode=recovery_v2_mode,
        ability_provider_mode=ability_catalog is not None,
        resolution_rule_mode=resolution_rule_products is not None,
        action_offer_mode=resolution_action_offer_document is not None,
        v02_extension_mode=normalized_v02_extension is not None,
        build_selection_mode=build_catalog is not None and build_catalog['schema']=='se-character-build-catalog-ir/1.2.0',
    )
    if normalized_v02_extension is not None:
        fingerprint = _digest({
            "base_compiler_fingerprint": fingerprint,
            "v02_extension_aggregate_sha256": normalized_v02_extension["aggregate_sha256"],
            "v02_extension_source_bindings_sha256": normalized_v02_extension["source_bindings_sha256"],
            "v02_extension_dependency_digests_sha256": normalized_v02_extension["dependency_digests_sha256"],
            "v02_extension_semantic_digests_sha256": normalized_v02_extension["semantic_digests_sha256"],
        })
        narrative_style_schema=normalized_v02_extension['products']['narrative_style']['schema']
        if narrative_style_schema in {'se-narrative-style-candidate-runtime/1.2.0','se-narrative-style-candidate-runtime/1.3.0'}:
            schema_root=Path(__file__).with_name('schemas')
            version=narrative_style_schema.rsplit('/',1)[1]
            fingerprint=_digest({'base_compiler_fingerprint':fingerprint,'event_narrative_contract_schemas':{name:'sha256:'+hashlib.sha256((schema_root/name).read_bytes()).hexdigest() for name in ('se-narrative-style-candidate-runtime-'+version+'.schema.json','se-authored-event-narrative-1.0.0.schema.json','se-authored-event-narrative-1.1.0.schema.json','sp-event-narrative-annotations-1.0.0.schema.json',*(['sp-event-narrative-annotations-1.1.0.schema.json'] if version=='1.3.0' else []))}})
    if resolution_rule_products is not None:
        fingerprint = _digest({
            "base_compiler_fingerprint": fingerprint,
            "resolution_rule_catalog_sha256": resolution_rule_products["resolution_rule_catalog"]["catalog_sha256"],
            "modifier_source_catalog_sha256": resolution_rule_products["modifier_source_catalog"]["catalog_sha256"],
            "resolution_rule_definition_sha256": [item["definition_sha256"] for item in resolution_rule_products["resolution_rule_definitions"]],
        })
    if interaction_catalog is not None:
        fingerprint = _digest({"base_compiler_fingerprint": fingerprint, "turn_interaction_contract": TURN_INTERACTION_CAPABILITY})
    if resolution_catalog is not None:
        fingerprint = _digest({"base_compiler_fingerprint": fingerprint, "resolution_check_contract": RESOLUTION_CHECK_CAPABILITY})
    if resolution_action_offer_document is not None:
        fingerprint = _digest({"base_compiler_fingerprint": fingerprint, "resolution_action_offer_contract": "se-resolution-action-offers/1.0.0"})
    if luck_action_binding_document is not None:
        # Compiled after the events, so only the contract identity is folded in
        # here; its content is covered by canonical_ir_sha256/content_sha256.
        fingerprint = _digest({"base_compiler_fingerprint": fingerprint,
                               "luck_action_bindings_contract": LUCK_ACTION_BINDINGS_AUTHOR_SCHEMA})
        if any('condition_sources' in entry for entry in luck_action_binding_document.get('entries',[])):
            root=Path(__file__).with_name('schemas')
            fingerprint=_digest({'base_compiler_fingerprint':fingerprint,'luck_condition_contracts':{name:'sha256:'+hashlib.sha256((root/name).read_bytes()).hexdigest() for name in (
                'se-luck-action-bindings-ir-1.1.0.schema.json','321roll-luck-preparation-snapshot-1.1.0.schema.json',
                'se-canonical-story-pack-ir-1.11.0.schema.json','se-story-artifact-1.11.0.schema.json')}})
    if build_catalog is not None:fingerprint=_digest({"base_compiler_fingerprint":fingerprint,"character_build_contract":CHARACTER_BUILD_CAPABILITY})
    if progression_catalog is not None:fingerprint=_digest({"base_compiler_fingerprint":fingerprint,"character_progression_contract":CHARACTER_PROGRESSION_CAPABILITY})
    if reward_catalog is not None:fingerprint=_digest({"base_compiler_fingerprint":fingerprint,"reward_settlement_contract":REWARD_SETTLEMENT_CAPABILITY})
    if inventory_catalog is not None:fingerprint=_digest({"base_compiler_fingerprint":fingerprint,"inventory_equipment_contract":INVENTORY_EQUIPMENT_CAPABILITY})
    if inventory_catalog is not None and inventory_catalog['schema']=='se-inventory-equipment-catalog-ir/1.1.0':
        fingerprint=_digest({'base_compiler_fingerprint':fingerprint,'inventory_instance_attributes_contract':'se-inventory-equipment-definitions/1.1.0'})
    if luck_rating_rules is not None:
        fingerprint=_digest({'base_compiler_fingerprint':fingerprint,'luck_rating_contract':'se-luck-rating-definitions/1.0.0','luck_rating_rules_sha256':luck_rating_rules['rules_sha256']})
    if luck_intervention_rules is not None:
        fingerprint=_digest({'base_compiler_fingerprint':fingerprint,'luck_intervention_contract':'se-luck-intervention-definitions/1.0.0','luck_intervention_rules_sha256':luck_intervention_rules['rules_sha256']})
    if ability_catalog is not None:fingerprint=_digest({"base_compiler_fingerprint":fingerprint,"ability_execution_contract":ABILITY_EXECUTION_CAPABILITY})
    if conflict_catalog is not None:
        conflict_schemas = _schema_fingerprints(union_mode=True) if union_mode else _schema_fingerprints(conflict_mode=True)
        fingerprint=_digest({
            "base_compiler_fingerprint":fingerprint,
            "conflict_procedure_contract":CONFLICT_PROCEDURE_CAPABILITY,
            "conflict_author_schema_file_sha256":conflict_schemas["se-conflict-procedure-definitions-1.0.0.schema.json"],
            "conflict_runtime_schema_file_sha256":conflict_schemas["se-conflict-procedure-runtime-1.0.0.schema.json"],
        })
    if recovery_catalog is not None:
        recovery_schemas = _schema_fingerprints(union_v2_mode=True) if recovery_v2_mode else _schema_fingerprints(union_mode=True) if union_mode else _schema_fingerprints(recovery_mode=True)
        fingerprint = _digest({
            "base_compiler_fingerprint": fingerprint,
            "recovery_cycle_contract": RECOVERY_CYCLE_V2_CAPABILITY if recovery_v2_mode else RECOVERY_CYCLE_CAPABILITY,
            "recovery_author_schema_sha256": recovery_schemas["se-recovery-cycle-definitions-2.0.0.schema.json" if recovery_v2_mode else "se-recovery-cycle-definitions-1.1.0.schema.json"],
            "recovery_runtime_schema_sha256": recovery_schemas["se-recovery-cycle-runtime-2.0.0.schema.json" if recovery_v2_mode else "se-recovery-cycle-runtime-1.1.0.schema.json"],
        })
    if luck_recipe_catalog is not None:
        fingerprint=_digest({'base_compiler_fingerprint':fingerprint,'luck_recipes_contract':'se-luck-recipe-definitions/1.0.0','luck_recipe_catalog_sha256':luck_recipe_catalog['catalog_sha256']})
    if offline_public_catalog is not None:
        fingerprint=_digest({"base_compiler_fingerprint":fingerprint,"offline_public_contract":OFFLINE_PUBLIC_CAPABILITY,"offline_public_catalog_sha256":offline_public_catalog["catalog_sha256"]})
    if static_visual_style is not None:
        fingerprint=_digest({"base_compiler_fingerprint":fingerprint,"static_visual_style_contract":STATIC_VISUAL_STYLE_SCHEMA,"static_visual_style_sha256":_digest(static_visual_style)})
    diagnostics: list[CompilerDiagnostic] = []
    events = [_compile_event(item, capability_catalog, reference_catalog, profile_registry, fingerprint, diagnostics, interaction_catalog, resolution_catalog, build_catalog, progression_catalog, reward_catalog, inventory_catalog, ability_catalog, conflict_catalog, recovery_catalog) for item in event_sources]
    events.sort(key=lambda item: item["identity"]["id"])
    if normalized_v02_extension is not None:
        from .event_narrative_annotations import event_annotation_index
        try:event_annotation_index(normalized_v02_extension['products']['narrative_style'],events)
        except (KeyError,TypeError,ValueError) as exc:_raise('compiler.event_narrative_invalid','v02_extension.products.narrative_style',str(exc),'修正事件正文、路线与显式引用的作者绑定后重编。')
    action_offer_catalog = None
    if resolution_action_offer_document is not None:
        assert resolution_catalog is not None and resolution_rule_products is not None
        try:
            action_offer_catalog = compile_resolution_action_offers(
                resolution_action_offer_document, events, resolution_catalog, resolution_rule_products,
                intervention_rules=luck_intervention_rules, inventory=inventory_catalog)
            from .resolution_action_offer import validate_personal_cost_sources
            validate_personal_cost_sources(action_offer_catalog, inventory_catalog, resource_document)
            bindings = action_offer_event_bindings(action_offer_catalog,
                                                  intervention_rules=luck_intervention_rules,
                                                  inventory=inventory_catalog)
            for event in events:
                binding = bindings.get(event["identity"]["id"])
                if binding is not None:
                    event["resolution_action_offers"] = binding
        except ResolutionActionOfferContractError as exc:
            _raise(exc.code, exc.path, exc.reason, "修正 action-offer 的源事件、检定定义、规则、收据或路线绑定后重新编译。")
    luck_action_bindings = None
    if luck_action_binding_document is not None:
        if action_offer_catalog is None or luck_recipe_catalog is None or luck_intervention_rules is None \
                or resolution_catalog is None or resolution_rule_products is None:
            _raise("luck_action_bindings.dependency_missing", "luck_action_binding_document",
                   "机运行动绑定需要已编译的动作目录、检定定义、D20 规则、机运规则与代价配方。",
                   "同时提供 resolution_action_offer_document、resolution_check_document、resolution_rule_document、"
                   "luck_intervention_document 与 luck_recipes_document。")
        try:
            luck_action_bindings = compile_luck_action_bindings(
                luck_action_binding_document, action_offer_catalog, luck_recipe_catalog,
                resolution_catalog, resolution_rule_products, luck_intervention_rules)
        except LuckActionBindingContractError as exc:
            _raise(exc.code, exc.path, exc.reason, "修正作者绑定的行动、配方、时钟来源与掷前检查策略后重新编译。")
    if recovery_catalog is not None and not any("recovery_cycle" in event for event in events):
        _raise("recovery.catalog_unused", "recovery_cycle_document", "recovery definitions were supplied but no event opted in", "bind at least one recovery_event or omit the recovery document")
    if len({item["identity"]["id"] for item in events}) != len(events):
        _raise("compiler.event_id_duplicate", "event_sources", "事件 ID 重复。", "为每个事件使用唯一稳定 ID。")
    for event in events:
        count = sum(1 for item in diagnostics if item.source_path == event["source"]["source_path"] and item.severity == CompilerSeverity.WARNING)
        event["compile_diagnostics_summary"]["warnings"] = count
        event["event_ir_sha256"] = _digest({key: value for key, value in event.items() if key != "event_ir_sha256"})
    selected_profile_keys = sorted({(str(item["profile"]), str(item["profile_version"])) for item in events})
    selected_profiles = [
        {"profile_id": profile_id, "profile_version": version, "contract_sha256": profile_registry.resolve(profile_id, version).contract_sha256}
        for profile_id, version in selected_profile_keys
    ]
    registry_identity = {
        "schema": profile_registry.schema,
        "registry_version": profile_registry.registry_version,
        "revision": profile_registry.revision,
        "fingerprint": profile_registry.fingerprint,
        "selection_policy": profile_registry.selection_policy,
    }
    resource_definitions = resource_catalog.to_ir() if resource_catalog is not None else []
    resource_catalog_sha256 = resource_catalog.fingerprint if resource_catalog is not None else _digest([])
    provider_contracts = None
    if recovery_v2_mode:
        provider_path = Path(__file__).with_name("provider_contracts.json")
        provider_contracts = json.loads(provider_path.read_text(encoding="utf-8"))
        if provider_contracts.get("manifest_fingerprint") != _digest({k: v for k, v in provider_contracts.items() if k != "manifest_fingerprint"}):
            raise RuntimeError("provider_contracts.fingerprint_mismatch")
        selected_provider = [item for item in provider_contracts.get("providers", []) if item.get("capability_id") == "recovery.cycle" and item.get("capability_version") == "2.0.0"]
        if len(selected_provider) != 1 or selected_provider[0].get("profile_version") != "2.0.0":
            raise RuntimeError("provider_contracts.recovery_v2_missing")
    effect_contracts: list[dict[str, Any]] = []
    if resource_catalog is not None and resource_document is not None:
        identities = {item["capability_ref"]: item for item in effect_contract_identities()}
        resource_identity = dict(identities["actor.resource_pool/1.0.0"])
        resource_identity.update({"contract_sha256": _digest(_plain(resource_document)), "contract": _plain(resource_document)})
        effect_contracts.append(resource_identity)
        if vitality_contract is not None and vitality_document is not None:
            vitality_identity = dict(identities["actor.vitality/1.0.0"])
            vitality_identity.update({"contract_sha256": _digest(_plain(vitality_document)), "contract": _plain(vitality_document)})
            effect_contracts.append(vitality_identity)
        effect_contracts.append(dict(identities["character.state.effects/1"]))
    conditional_luck=luck_action_bindings is not None and luck_action_bindings['schema']=='se-luck-action-bindings-ir/1.1.0'
    ir_material = {
        "schema": "se-canonical-story-pack-ir/1.11.0" if conditional_luck else _V02_CANONICAL_IR_SCHEMA if normalized_v02_extension is not None else CANONICAL_IR_ACTION_OFFER_SCHEMA if action_offer_catalog is not None else CANONICAL_IR_RESOLUTION_RULE_SCHEMA if resolution_rule_products is not None else CANONICAL_IR_UNION_V2_SCHEMA if recovery_v2_mode else CANONICAL_IR_UNION_SCHEMA if union_mode else CANONICAL_IR_RECOVERY_SCHEMA if recovery_catalog is not None else CANONICAL_IR_CHOICE_SCHEMA if choice_mode else CANONICAL_IR_GUARD_SCHEMA if guard_mode else CANONICAL_IR_SCHEMA, "engine_spec": STORY_ENGINE_SPEC_VERSION,
        "package": {"package_id": package_id, "content_version": content_version},
        "manifest": normalized_manifest, "world": normalized_world, "modules": normalized_modules,
        "event_compositions": events,
        "profile_registry": registry_identity,
        "profile_contracts": selected_profiles,
        "resource_definitions": resource_definitions,
        "resource_catalog_sha256": resource_catalog_sha256,
        "effect_contracts": effect_contracts,
        "compiler_contract_fingerprint": fingerprint,
    }
    if interaction_catalog is not None:
        ir_material["turn_interaction_policies"] = interaction_catalog
    if resolution_catalog is not None:
        ir_material["resolution_check_definitions"] = resolution_catalog
    if resolution_rule_products is not None:
        ir_material.update(resolution_rule_products)
    if action_offer_catalog is not None:
        ir_material["resolution_action_offers"] = action_offer_catalog
    if build_catalog is not None:ir_material["character_build_definitions"]=build_catalog
    if luck_rating_rules is not None:ir_material['luck_rating_rules']=luck_rating_rules
    if luck_intervention_rules is not None:ir_material['luck_intervention_rules']=luck_intervention_rules
    if luck_recipe_catalog is not None:ir_material['luck_recipe_catalog']=luck_recipe_catalog
    if luck_action_bindings is not None:ir_material['luck_action_bindings']=luck_action_bindings
    if progression_catalog is not None:ir_material["character_progression_definitions"]=progression_catalog
    if reward_catalog is not None:ir_material["reward_settlement_definitions"]=reward_catalog
    if inventory_catalog is not None:ir_material["inventory_equipment_definitions"]=inventory_catalog
    if ability_catalog is not None:ir_material["ability_execution_definitions"]=ability_catalog
    if conflict_catalog is not None:ir_material["conflict_procedure_definitions"]=conflict_catalog
    if recovery_catalog is not None:ir_material["recovery_cycle_definitions"]=recovery_catalog
    if provider_contracts is not None:ir_material["provider_contracts"]=provider_contracts
    if normalized_v02_extension is not None:ir_material["v02_extension"]=normalized_v02_extension
    ir_material["canonical_sha256"] = _digest(ir_material)
    canonical_ir = CanonicalStoryPackIR(ir_material)
    source_map = []
    sources_by_path = {item.source_path: item.value for item in event_sources}
    for event_index, event in enumerate(events):
        source_path = event["source"]["source_path"]
        author_value = sources_by_path[source_path]
        checkpoint_index = {str(item.get("id")): index for index, item in enumerate(author_value.get("checkpoints", []))}
        route_index = {str(item.get("id")): index for index, item in enumerate(author_value.get("routes", []))}
        effect_index = {str(item.get("id")): index for index, item in enumerate(author_value.get("effects", []))}
        choice_index = {str(item.get("checkpoint_ref")): index for index, item in enumerate(author_value.get("choice_sets", []))}
        source_map.append({"output_path": f"event_compositions[{event_index}]", "source_path": source_path, "field_path": "$"})
        for node_index, node in enumerate(event["checkpoint_graph"]["nodes"]):
            source_map.append({"output_path": f"event_compositions[{event_index}].checkpoint_graph.nodes[{node_index}]", "source_path": source_path, "field_path": f"checkpoints[{checkpoint_index[node['id']]}]"})
        for edge_index, edge in enumerate(event["checkpoint_graph"]["edges"]):
            source_map.append({"output_path": f"event_compositions[{event_index}].checkpoint_graph.edges[{edge_index}]", "source_path": source_path, "field_path": f"routes[{route_index[edge['id']]}]"})
        for compiled_index, effect in enumerate(event["effects"]):
            source_map.append({"output_path": f"event_compositions[{event_index}].effects[{compiled_index}]", "source_path": source_path, "field_path": f"effects[{effect_index[effect['id']]}]"})
        for compiled_index, choice_set in enumerate(event.get("choice_sets", [])):
            source_map.append({"output_path": f"event_compositions[{event_index}].choice_sets[{compiled_index}]", "source_path": source_path, "field_path": f"choice_sets[{choice_index[choice_set['checkpoint_ref']]}]"})
    content_material = {"manifest": normalized_manifest, "world": normalized_world, "modules": normalized_modules, "event_sources": [item.value for item in sorted(event_sources, key=lambda item: item.source_path)], "resource_document": _plain(resource_document) if resource_document is not None else None, "vitality_document": _plain(vitality_document) if vitality_document is not None else None}
    if turn_interaction_document is not None:
        content_material["turn_interaction_document"] = _plain(turn_interaction_document)
    if resolution_check_document is not None:
        content_material["resolution_check_document"] = _plain(resolution_check_document)
    if resolution_rule_document is not None:
        content_material["resolution_rule_document"] = _plain(resolution_rule_document)
    if resolution_action_offer_document is not None:
        content_material["resolution_action_offer_document"] = _plain(resolution_action_offer_document)
    if character_build_document is not None:content_material["character_build_document"]=_plain(character_build_document)
    if character_build_catalog_document is not None:content_material["character_build_catalog_document"]=_plain(character_build_catalog_document)
    if luck_rating_document is not None:content_material['luck_rating_document']=_plain(luck_rating_document)
    if luck_intervention_document is not None:content_material['luck_intervention_document']=_plain(luck_intervention_document)
    if luck_recipes_document is not None:content_material['luck_recipes_document']=_plain(luck_recipes_document)
    if luck_action_binding_document is not None:content_material['luck_action_binding_document']=_plain(luck_action_binding_document)
    if character_progression_document is not None:content_material["character_progression_document"]=_plain(character_progression_document)
    if reward_settlement_document is not None:content_material["reward_settlement_document"]=_plain(reward_settlement_document)
    if inventory_equipment_document is not None:content_material["inventory_equipment_document"]=_plain(inventory_equipment_document)
    if ability_execution_document is not None:content_material["ability_execution_document"]=_plain(ability_execution_document)
    if conflict_procedure_document is not None:content_material["conflict_procedure_document"]=_plain(conflict_procedure_document)
    if recovery_cycle_document is not None:content_material["recovery_cycle_document"]=_plain(recovery_cycle_document)
    if offline_public_document is not None:content_material["offline_public_document"]=_plain(offline_public_document)
    if static_visual_style_document is not None:content_material["static_visual_style_document"]=_plain(static_visual_style_document)
    if provider_contracts is not None:content_material["provider_contracts"]=_plain(provider_contracts)
    if normalized_v02_extension is not None:content_material["v02_extension_candidate"]=normalized_v02_extension
    artifact_material = {
        "schema": "se-story-artifact/1.11.0" if conditional_luck else _V02_ARTIFACT_SCHEMA if normalized_v02_extension is not None else ARTIFACT_ACTION_OFFER_SCHEMA if action_offer_catalog is not None else ARTIFACT_RESOLUTION_RULE_SCHEMA if resolution_rule_products is not None else ARTIFACT_UNION_V2_SCHEMA if recovery_v2_mode else ARTIFACT_UNION_SCHEMA if union_mode else ARTIFACT_RECOVERY_SCHEMA if recovery_catalog is not None else ARTIFACT_CHOICE_SCHEMA if choice_mode else ARTIFACT_GUARD_SCHEMA if guard_mode else ARTIFACT_SCHEMA, "engine_spec": STORY_ENGINE_SPEC_VERSION, "target_abi": _V02_COMPILER_TARGET_ABI if normalized_v02_extension is not None else COMPILER_TARGET_ACTION_OFFER_ABI if action_offer_catalog is not None else COMPILER_TARGET_RESOLUTION_RULE_ABI if resolution_rule_products is not None else COMPILER_TARGET_UNION_V2_ABI if recovery_v2_mode else COMPILER_TARGET_UNION_ABI if union_mode else COMPILER_TARGET_RECOVERY_ABI if recovery_catalog is not None else COMPILER_TARGET_CHOICE_ABI if choice_mode else COMPILER_TARGET_GUARD_ABI if guard_mode else COMPILER_TARGET_ABI,
        "package": {"package_id": package_id, "content_version": content_version},
        "canonical_ir_sha256": canonical_ir.canonical_sha256, "compiler_contract_fingerprint": fingerprint,
        "content_sha256": _digest(content_material),
        "profile_registry": registry_identity,
        "profile_contracts": selected_profiles,
        "resource_definitions": resource_definitions,
        "resource_catalog_sha256": resource_catalog_sha256,
        "effect_contracts": effect_contracts,
        "event_compositions": events,
        "capability_closure": capability_catalog.to_mapping(),
        "source_map": sorted(source_map, key=lambda item: (item["output_path"], item["source_path"], item["field_path"])),
        "projection_plan": {"kind": "bounded_proposal_only", "execution_owner": "321_platform", "projection_owner": "321_platform"},
        "diagnostics_summary": {"warnings": sum(item.severity == CompilerSeverity.WARNING for item in diagnostics), "errors": 0},
    }
    if interaction_catalog is not None:
        artifact_material["turn_interaction_policies"] = interaction_catalog
    if resolution_catalog is not None:
        artifact_material["resolution_check_definitions"] = resolution_catalog
    if resolution_rule_products is not None:
        artifact_material.update(resolution_rule_products)
    if action_offer_catalog is not None:
        artifact_material["resolution_action_offers"] = action_offer_catalog
    if build_catalog is not None:artifact_material["character_build_definitions"]=build_catalog
    if luck_rating_rules is not None:artifact_material['luck_rating_rules']=luck_rating_rules
    if luck_intervention_rules is not None:artifact_material['luck_intervention_rules']=luck_intervention_rules
    if luck_recipe_catalog is not None:artifact_material['luck_recipe_catalog']=luck_recipe_catalog
    if luck_action_bindings is not None:artifact_material['luck_action_bindings']=luck_action_bindings
    if progression_catalog is not None:artifact_material["character_progression_definitions"]=progression_catalog
    if reward_catalog is not None:artifact_material["reward_settlement_definitions"]=reward_catalog
    if inventory_catalog is not None:artifact_material["inventory_equipment_definitions"]=inventory_catalog
    if ability_catalog is not None:artifact_material["ability_execution_definitions"]=ability_catalog
    if conflict_catalog is not None:artifact_material["conflict_procedure_definitions"]=conflict_catalog
    if recovery_catalog is not None:artifact_material["recovery_cycle_definitions"]=recovery_catalog
    if offline_public_catalog is not None:artifact_material["offline_public_catalog"]=offline_public_catalog
    if static_visual_style is not None:artifact_material["static_visual_style"]=static_visual_style
    if provider_contracts is not None:artifact_material["provider_contracts"]=provider_contracts
    if normalized_v02_extension is not None:artifact_material["v02_extension"]=normalized_v02_extension
    artifact_material["artifact_sha256"] = _digest(artifact_material)
    return CompilationResult(canonical_ir, Artifact(artifact_material), tuple(sorted(diagnostics, key=lambda item: (item.source_path, item.field_path, item.code))), fingerprint)


__all__ = [
    "Artifact", "AuthorSource", "CanonicalStoryPackIR", "CapabilityCatalog", "CapabilityProvider",
    "CompilationResult", "CompilerContractError", "CompilerDiagnostic", "CompilerSeverity",
    "EventCompositionIR", "ReferenceCatalog", "ReferenceDescriptor", "STATIC_VISUAL_STYLE_SCHEMA", "compile_story_pack", "engine_owned_provider",
]
