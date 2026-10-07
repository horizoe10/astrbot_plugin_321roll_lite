"""Strict, deterministic NarrativeStyleProfile to Style IR compiler.

This is an independent, non-installable contract slice.  It is intentionally
not wired into the dev6 compiler, package exports, entrypoints, or provider
surface.  Compilation is pure data transformation and adds no model calls.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


NARRATIVE_STYLE_PROFILE_SCHEMA = "narrative-style-profile/1.0.0"
NARRATIVE_STYLE_IR_SCHEMA = "se-narrative-style-ir/1.0.0"
NARRATIVE_STYLE_CANDIDATE_RUNTIME_SCHEMA = "se-narrative-style-candidate-runtime/1.0.0"
NARRATIVE_STYLE_REFERENCED_RUNTIME_SCHEMA = 'se-narrative-style-candidate-runtime/1.1.0'
NARRATIVE_STYLE_RUNTIME_SCHEMAS = frozenset({NARRATIVE_STYLE_CANDIDATE_RUNTIME_SCHEMA,NARRATIVE_STYLE_REFERENCED_RUNTIME_SCHEMA})
from .event_narrative_annotations import LEGACY_SCHEMA as NARRATIVE_STYLE_EVENT_LEGACY_SCHEMA,STYLE_SCHEMA as NARRATIVE_STYLE_EVENT_RUNTIME_SCHEMA,compile_event_annotations
LEGACY_OPENING_DOCUMENT_SCHEMA = 'se-narrative-opening-document/1.0.0'
REFERENCED_OPENING_DOCUMENT_SCHEMA = 'se-narrative-opening-document/1.1.0'
SPAN_OPENING_DOCUMENT_SCHEMA = 'se-narrative-opening-document/1.2.0'
STORY_PACK_STYLE_CANDIDATE_SCHEMA = "sp-narrative-style-profiles-candidate/0.2"
STORY_PACK_STYLE_COVERAGE_SCHEMA = "sp-narrative-style-coverage-candidate/0.2"
STORY_PACK_OPENINGS_SCHEMA = "thirteenth-seat.openings-routes/1"

PHASE_KINDS = (
    "cooperative",
    "private_parallel",
    "regroup",
    "public_conflict",
    "finale",
    "epilogue",
)
AUDIENCES = frozenset({"public", "party", "actor", "dm", "admin", "author"})
PRESET_SPECS: dict[str, tuple[int, int, str]] = {
    "dialogue_high": (80, 20, "对白主导推进；仍保留必要行动、环境、规则事实与明确行动出口。"),
    "dialogue_soft": (65, 35, "对白偏多；用简洁动作与环境维持因果、风险和人物差异。"),
    "balanced": (50, 50, "对白、行动、环境与后果按场景自然平衡，不套用固定段落模板。"),
    "description_soft": (35, 65, "描写偏多；保留关系变化、风险说明与玩家选择所需对白。"),
    "description_high": (20, 80, "高密度描写空间、感官、行动与后果；不得省略必要对白或选择。"),
}

_PROFILE_FIELDS = frozenset({
    "schema", "profile_ref", "profile_version", "locale", "label", "public_summary",
    "world_voice_summary", "base_instruction", "hard_constraints", "forbidden_expressions",
    "audience_ceiling", "default_preset", "allowed_presets", "preset_definitions", "phase_variants",
    "customization", "budgets",
})
_PROFILE_PRESET_FIELDS = frozenset({"preset", "dialogue_weight", "description_weight", "directive", "prohibition"})
_VARIANT_FIELDS = frozenset({
    "variant_ref", "phase", "instruction", "audience_ceiling", "narrative_distance",
    "sentence_rhythm", "sensory_focus",
})
_CUSTOMIZATION_FIELDS = frozenset({"enabled", "max_chars", "allowed_topics"})
_BUDGET_FIELDS = frozenset({"base_max_chars", "variant_max_chars", "compiled_max_chars"})
_CANDIDATE_FIELDS = frozenset({
    "schema", "candidate_version", "installable", "locale", "default_profile_ref",
    "default_preset_ref", "expression_only", "requirement_refs", "world_tone",
    "shared_taboos", "must_preserve", "paragraph_contract", "runtime_generation",
    "narrative_presets", "phase_variants", "profiles",
})
_COVERAGE_FIELDS = frozenset({
    "schema", "candidate_version", "installable", "profile_source_path",
    "source_catalog_path", "requirement_refs", "counts", "shared_application", "openings",
})
_OPENINGS_FIELDS = frozenset({"schema", "story_pack_ref", "version", "selection_policy", "openings", "counts", "known_gap"})
_OPENING_FIELDS = frozenset({
    "id", "title", "region", "crisis", "initial_state", "actions", "route", "prologue_story",
    "requirement_source", "action_resolution", "closure", "grey_crown_thread",
})
_PROLOGUE_FIELDS = frozenset({"begin_marker", "body", "end_marker", "sha256", "authority", "coverage"})
_COVERAGE_OPENING_FIELDS = frozenset({
    "source_opening_id", "source_title", "source_region", "source_body_sha256",
    "default_profile_ref", "allowed_profile_refs", "allowed_preset_refs", "sensory_anchors",
})
_SOURCE_PROFILE_FIELDS = frozenset({
    "profile_ref", "player_name", "summary", "is_default", "perspective",
    "narrative_distance", "rhythm", "sensory_focus", "best_for", "allowed_preset_refs",
})
_SOURCE_PRESET_FIELDS = frozenset({
    "preset_ref", "player_name", "dialogue_weight", "description_weight", "directive", "prohibition",
})
_SOURCE_VARIANT_FIELDS = frozenset({"phase_kind", "player_name", "rhythm", "focus", "boundary"})
_CANDIDATE_RUNTIME_FIELDS = frozenset({
    "schema", "source_candidate_schema", "coverage_schema", "openings_schema",
    "candidate_version", "installable", "locale", "default_profile_ref",
    "default_preset_ref", "source_style_sha256", "source_coverage_sha256",
    "source_openings_sha256", "requirement_refs", "paragraph_contract",
    "runtime_generation", "preset_catalog", "profile_irs", "adapter_source_map",
    "opening_bindings", "counts", "model_calls", "runtime_sha256",
})

_STORY_PACK_PROFILE_PATH = "author/se1/v02/narrative_style_profiles.json"
_STORY_PACK_COVERAGE_PATH = "author/se1/v02/narrative_style_coverage.json"
_STORY_PACK_OPENINGS_PATH = "author/se1/openings_and_routes.json"
_ADAPTER_AUDIENCE_CEILING = ("actor", "party", "public")


@dataclass(frozen=True, slots=True)
class NarrativeStyleContractError(ValueError):
    code: str
    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.code}:{self.path}"


def _fail(code: str, path: str, reason: str) -> None:
    raise NarrativeStyleContractError(code, path, reason)


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("style_profile_incompatible", path, "字段必须是 JSON 对象。")
    return value


def _sequence(value: object, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("style_profile_incompatible", path, "字段必须是 JSON 数组。")
    return value


def _fields(value: Mapping[str, Any], expected: frozenset[str] | set[str], path: str) -> None:
    if set(value) != set(expected):
        _fail("style_profile_incompatible", path, "字段不完整或包含未知字段。")


def _text(value: object, path: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        _fail("style_profile_incompatible", path, "字段必须是有界非空文本。")
    return value.strip()


def _ref(value: object, path: str) -> str:
    result = _text(value, path, 160)
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:@-"
    if result[0] not in allowed[:62] or any(char not in allowed for char in result):
        _fail("style_profile_incompatible", path, "字段必须是稳定引用。")
    return result


def _integer(value: object, path: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or (maximum is not None and value > maximum):
        _fail("style_budget_exceeded", path, "字段必须是合同范围内的整数。")
    return value


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        _fail("style_profile_incompatible", path, "字段必须是布尔值。")
    return value


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail("style_profile_incompatible", "$", f"值无法形成 canonical JSON: {exc}")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _unique_texts(value: object, path: str, *, maximum: int, required: bool = False) -> list[str]:
    items = [_text(item, f"{path}[{index}]", maximum) for index, item in enumerate(_sequence(value, path))]
    if required and not items:
        _fail("style_profile_incompatible", path, "列表不得为空。")
    if len(items) != len(set(items)):
        _fail("style_policy_conflict", path, "列表不得包含重复项。")
    return sorted(items)


def _audiences(value: object, path: str) -> list[str]:
    items = _unique_texts(value, path, maximum=20, required=True)
    if set(items) - AUDIENCES:
        _fail("style_policy_conflict", path, "audience 不属于冻结公共枚举。")
    return items


def _instruction(layers: Mapping[str, str]) -> str:
    order = ("platform_safety", "hard_constraints", "base_profile", "phase_variant", "narrative_preset", "custom_expectation")
    return "\n".join(f"{name.upper()}: {layers[name]}" for name in order)


def compile_narrative_style_profile(document: Mapping[str, Any]) -> dict[str, Any]:
    """Compile one declarative profile into deterministic, audience-safe Style IR."""
    if document is None:
        _fail("style_profile_missing", "$", "NarrativeStyleProfile 不得缺失。")
    profile = _mapping(document, "$")
    _fields(profile, _PROFILE_FIELDS, "$")
    if profile["schema"] != NARRATIVE_STYLE_PROFILE_SCHEMA:
        _fail("style_contract_unsupported", "$.schema", "NarrativeStyleProfile 合同版本不受支持。")

    profile_ref = _ref(profile["profile_ref"], "$.profile_ref")
    profile_version = _ref(profile["profile_version"], "$.profile_version")
    locale = _text(profile["locale"], "$.locale", 35)
    if "-" not in locale or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-" for char in locale):
        _fail("style_profile_incompatible", "$.locale", "locale 必须是固定 BCP-47 风格标签。")
    label = _text(profile["label"], "$.label", 120)
    public_summary = _text(profile["public_summary"], "$.public_summary", 600)
    world_voice_summary = _text(profile["world_voice_summary"], "$.world_voice_summary", 600)
    base_instruction = _text(profile["base_instruction"], "$.base_instruction", 1200)
    hard_constraints = _unique_texts(profile["hard_constraints"], "$.hard_constraints", maximum=360, required=True)
    forbidden = _unique_texts(profile["forbidden_expressions"], "$.forbidden_expressions", maximum=240)
    base_audiences = _audiences(profile["audience_ceiling"], "$.audience_ceiling")

    preset_definitions: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(_sequence(profile["preset_definitions"], "$.preset_definitions")):
        path = f"$.preset_definitions[{index}]"
        definition = _mapping(raw, path)
        _fields(definition, _PROFILE_PRESET_FIELDS, path)
        preset = definition["preset"]
        if preset not in PRESET_SPECS or preset in preset_definitions:
            _fail("style_profile_incompatible", f"{path}.preset", "preset definition 缺失、重复或不受支持。")
        dialogue = _integer(definition["dialogue_weight"], f"{path}.dialogue_weight", maximum=100)
        description = _integer(definition["description_weight"], f"{path}.description_weight", maximum=100)
        if dialogue + description != 100:
            _fail("style_policy_conflict", path, "对白与描写权重之和必须为 100。")
        preset_definitions[preset] = {
            "dialogue_weight": dialogue,
            "description_weight": description,
            "directive": _text(definition["directive"], f"{path}.directive", 360),
            "prohibition": _text(definition["prohibition"], f"{path}.prohibition", 360),
        }
    if set(preset_definitions) != set(PRESET_SPECS):
        _fail("style_profile_incompatible", "$.preset_definitions", "Profile 必须精确声明五档 preset definition。")
    preset_order = ("dialogue_high", "dialogue_soft", "balanced", "description_soft", "description_high")
    dialogue_curve = [preset_definitions[key]["dialogue_weight"] for key in preset_order]
    description_curve = [preset_definitions[key]["description_weight"] for key in preset_order]
    if not all(left > right for left, right in zip(dialogue_curve, dialogue_curve[1:])) or not all(left < right for left, right in zip(description_curve, description_curve[1:])):
        _fail("style_policy_conflict", "$.preset_definitions", "五档对白/描写权重必须严格单调且可区分。")

    allowed_presets = _unique_texts(profile["allowed_presets"], "$.allowed_presets", maximum=40, required=True)
    if set(allowed_presets) != set(PRESET_SPECS):
        _fail("style_profile_incompatible", "$.allowed_presets", "首版 Profile 必须明确允许且只允许冻结五档 preset。")
    default_preset = profile["default_preset"]
    if default_preset not in PRESET_SPECS or default_preset not in allowed_presets:
        _fail("style_profile_incompatible", "$.default_preset", "默认 preset 必须属于冻结五档。")

    customization = _mapping(profile["customization"], "$.customization")
    _fields(customization, _CUSTOMIZATION_FIELDS, "$.customization")
    compiled_customization = {
        "enabled": _boolean(customization["enabled"], "$.customization.enabled"),
        "max_chars": _integer(customization["max_chars"], "$.customization.max_chars", maximum=600),
        "allowed_topics": _unique_texts(customization["allowed_topics"], "$.customization.allowed_topics", maximum=80),
    }
    if not compiled_customization["enabled"] and (compiled_customization["max_chars"] != 0 or compiled_customization["allowed_topics"]):
        _fail("style_policy_conflict", "$.customization", "禁用自定义时不得保留字符预算或允许主题。")

    budgets = _mapping(profile["budgets"], "$.budgets")
    _fields(budgets, _BUDGET_FIELDS, "$.budgets")
    compiled_budgets = {
        "base_max_chars": _integer(budgets["base_max_chars"], "$.budgets.base_max_chars", minimum=1, maximum=1200),
        "variant_max_chars": _integer(budgets["variant_max_chars"], "$.budgets.variant_max_chars", minimum=1, maximum=320),
        "compiled_max_chars": _integer(budgets["compiled_max_chars"], "$.budgets.compiled_max_chars", minimum=1, maximum=1800),
    }
    if len(base_instruction) > compiled_budgets["base_max_chars"]:
        _fail("style_budget_exceeded", "$.base_instruction", "base instruction 超过声明预算。")

    variants: list[dict[str, Any]] = []
    source_index_by_ref: dict[str, int] = {}
    phases: set[str] = set()
    refs: set[str] = set()
    for index, raw in enumerate(_sequence(profile["phase_variants"], "$.phase_variants")):
        path = f"$.phase_variants[{index}]"
        variant = _mapping(raw, path)
        _fields(variant, _VARIANT_FIELDS, path)
        phase = variant["phase"]
        if phase not in PHASE_KINDS or phase in phases:
            _fail("style_variant_invalid", f"{path}.phase", "phase 必须属于冻结枚举且不得重复。")
        phases.add(phase)
        variant_ref = _ref(variant["variant_ref"], f"{path}.variant_ref")
        if variant_ref in refs:
            _fail("style_variant_invalid", f"{path}.variant_ref", "variant_ref 不得重复。")
        refs.add(variant_ref)
        source_index_by_ref[variant_ref] = index
        instruction = _text(variant["instruction"], f"{path}.instruction", 320)
        if len(instruction) > compiled_budgets["variant_max_chars"]:
            _fail("style_budget_exceeded", f"{path}.instruction", "phase variant 超过声明预算。")
        variant_audiences = _audiences(variant["audience_ceiling"], f"{path}.audience_ceiling")
        if set(variant_audiences) - set(base_audiences):
            _fail("style_policy_conflict", f"{path}.audience_ceiling", "phase variant 不得扩大 base audience。")
        variants.append({
            "variant_ref": variant_ref,
            "phase": phase,
            "instruction": instruction,
            "audience_ceiling": variant_audiences,
            "narrative_distance": _text(variant["narrative_distance"], f"{path}.narrative_distance", 160),
            "sentence_rhythm": _text(variant["sentence_rhythm"], f"{path}.sentence_rhythm", 160),
            "sensory_focus": _unique_texts(variant["sensory_focus"], f"{path}.sensory_focus", maximum=80),
        })
    if phases != set(PHASE_KINDS):
        _fail("style_variant_invalid", "$.phase_variants", "必须为六种 phase 各声明一个且仅一个 variant。")
    variants.sort(key=lambda item: item["phase"])

    safety_material = {
        "hard_constraints": hard_constraints,
        "forbidden_expressions": forbidden,
        "audience_ceiling": base_audiences,
        "semantic_boundaries": ["facts", "choices", "rules", "consent", "authority", "audience"],
    }
    safety_digest = _digest(safety_material)
    style_slices: list[dict[str, Any]] = []
    for variant in variants:
        for preset in sorted(PRESET_SPECS):
            preset_definition = preset_definitions[preset]
            dialogue_weight = preset_definition["dialogue_weight"]
            description_weight = preset_definition["description_weight"]
            preset_directive = preset_definition["directive"] + "；" + preset_definition["prohibition"]
            layers = {
                "platform_safety": "保留输出 Schema、已提交事实、规则、同意、权限、玩家能动性与当前 audience；Style 只影响表达。",
                "hard_constraints": "；".join(hard_constraints + (["禁用：" + "；".join(forbidden)] if forbidden else [])),
                "base_profile": base_instruction,
                "phase_variant": "；".join((variant["instruction"], variant["narrative_distance"], variant["sentence_rhythm"], "感官重点=" + "、".join(variant["sensory_focus"]))),
                "narrative_preset": preset_directive,
                "custom_expectation": "仅在平台已授权且通过主题/长度校验时填入；不得覆盖前序层。",
            }
            instruction = _instruction(layers)
            if len(instruction) > compiled_budgets["compiled_max_chars"]:
                _fail("style_budget_exceeded", f"$.phase_variants[{variant['phase']}].{preset}", "合成 Style 指令超过硬预算。")
            material = {
                "slice_ref": f"{profile_ref}:{variant['phase']}:{preset}",
                "variant_ref": variant["variant_ref"],
                "phase": variant["phase"],
                "preset": preset,
                "dialogue_weight": dialogue_weight,
                "description_weight": description_weight,
                "audience_ceiling": variant["audience_ceiling"],
                "instruction_layers": layers,
                "compiled_instruction": instruction,
                "protected_semantics_sha256": safety_digest,
                "additional_model_calls": 0,
            }
            material["slice_sha256"] = _digest(material)
            style_slices.append(material)

    runtime_slice = {
        "profile_ref": profile_ref,
        "profile_version": profile_version,
        "locale": locale,
        "audience_ceiling": base_audiences,
        "default_preset": default_preset,
        "allowed_presets": allowed_presets,
        "customization": compiled_customization,
        "budgets": compiled_budgets,
        "style_slices": style_slices,
    }
    material = {
        "schema": NARRATIVE_STYLE_IR_SCHEMA,
        "source_schema": NARRATIVE_STYLE_PROFILE_SCHEMA,
        "profile_ref": profile_ref,
        "profile_version": profile_version,
        "locale": locale,
        "source_sha256": _digest(profile),
        "source_map": [{"ir_ref": profile_ref, "source_path": "$"}] + [
            {"ir_ref": item["variant_ref"], "source_path": f"$.phase_variants[{source_index_by_ref[item['variant_ref']]}]"}
            for item in variants
        ],
        "label": label,
        "public_summary": public_summary,
        "world_voice_summary": world_voice_summary,
        "hard_constraints": hard_constraints,
        "forbidden_expressions": forbidden,
        "phase_variants": variants,
        "safety_contract_sha256": safety_digest,
        "runtime_slice_sha256": _digest(runtime_slice),
        "additional_model_calls": 0,
        **runtime_slice,
    }
    material["ir_sha256"] = _digest(material)
    return material


def validate_narrative_style_ir(value: Mapping[str, Any], source_document: Mapping[str, Any]) -> None:
    """Validate digests and exact reproducibility against the source profile."""
    ir = _mapping(value, "$")
    expected = {
        "schema", "source_schema", "profile_ref", "profile_version", "locale", "source_sha256",
        "source_map", "label", "public_summary", "world_voice_summary", "hard_constraints",
        "forbidden_expressions", "audience_ceiling", "default_preset", "allowed_presets",
        "customization", "budgets", "phase_variants", "style_slices", "safety_contract_sha256",
        "runtime_slice_sha256", "additional_model_calls", "ir_sha256",
    }
    _fields(ir, expected, "$")
    if ir["schema"] != NARRATIVE_STYLE_IR_SCHEMA or ir["source_schema"] != NARRATIVE_STYLE_PROFILE_SCHEMA:
        _fail("style_contract_unsupported", "$.schema", "Style IR 合同版本不受支持。")
    runtime_slice = {key: ir[key] for key in (
        "profile_ref", "profile_version", "locale", "audience_ceiling", "default_preset",
        "allowed_presets", "customization", "budgets", "style_slices",
    )}
    if ir["runtime_slice_sha256"] != _digest(runtime_slice) or ir["ir_sha256"] != _digest({key: item for key, item in ir.items() if key != "ir_sha256"}):
        _fail("style_digest_mismatch", "$", "Style IR 摘要与内容不一致。")
    if ir["additional_model_calls"] != 0 or any(item.get("additional_model_calls") != 0 for item in ir["style_slices"]):
        _fail("style_policy_conflict", "$.additional_model_calls", "文风编译不得新增模型调用。")
    rebuilt = compile_narrative_style_profile(source_document)
    if ir != rebuilt:
        _fail("style_digest_mismatch", "$", "Style IR 必须逐字段匹配源 Profile 的确定性重编译结果。")


def _raw_text_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _required_false(value: object, path: str) -> None:
    if _boolean(value, path):
        _fail("style_profile_incompatible", path, "未分配候选必须保持 non-installable。")


def _paragraphs(body: str, *, path: str, hard_max: int) -> list[str]:
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs: list[str] = []
    pending: list[str] = []
    for line in normalized.split("\n"):
        if line.strip():
            pending.append(line.strip())
        elif pending:
            paragraphs.append("\n".join(pending))
            pending = []
    if pending:
        paragraphs.append("\n".join(pending))
    if len(paragraphs) < 2:
        _fail("style_profile_incompatible", path, "opening 正文必须保留多个权威自然段。")
    for index, paragraph in enumerate(paragraphs):
        visible = len("".join(paragraph.split()))
        if visible == 0 or visible > hard_max:
            _fail("style_budget_exceeded", f"{path}.paragraphs[{index}]", "自然段为空或超过 hard_max。")
    return paragraphs


def _validate_paragraph_contract(value: object) -> dict[str, Any]:
    path = "$.paragraph_contract"
    contract = _mapping(value, path)
    fields = {
        "structure", "allowed_block_kinds", "required_block_fields",
        "ordinary_paragraph_visible_characters", "length_mode_paragraph_targets",
        "new_paragraph_triggers", "special_block_overflow",
        "short_dialogue_or_turn_sentence_may_be_below_target_min",
        "paragraph_boundaries_are_authoritative", "empty_lines_are_not_the_schema",
        "choices_or_resolution_results_may_not_be_embedded",
        "humanizer_may_reorder_merge_or_split_blocks",
    }
    _fields(contract, fields, path)
    if contract["structure"] != "NarrativeDocument.blocks[]":
        _fail("style_profile_incompatible", f"{path}.structure", "段落合同必须使用 NarrativeDocument.blocks[]。")
    expected_kinds = {"paragraph", "dialogue", "heading", "aside", "letter", "declaration", "short_poem", "ritual"}
    kinds = set(_unique_texts(contract["allowed_block_kinds"], f"{path}.allowed_block_kinds", maximum=40, required=True))
    if kinds != expected_kinds:
        _fail("style_profile_incompatible", f"{path}.allowed_block_kinds", "block kind 集合与候选合同不一致。")
    expected_block_fields = {"block_ref", "kind", "order", "locale", "audience", "source_ref", "text_digest"}
    block_fields = set(_unique_texts(contract["required_block_fields"], f"{path}.required_block_fields", maximum=40, required=True))
    if block_fields != expected_block_fields:
        _fail("style_profile_incompatible", f"{path}.required_block_fields", "Narrative block 必需字段不完整。")
    ordinary = _mapping(contract["ordinary_paragraph_visible_characters"], f"{path}.ordinary_paragraph_visible_characters")
    _fields(ordinary, {"target_min", "target_max", "hard_max"}, f"{path}.ordinary_paragraph_visible_characters")
    target_min = _integer(ordinary["target_min"], f"{path}.ordinary_paragraph_visible_characters.target_min", minimum=1)
    target_max = _integer(ordinary["target_max"], f"{path}.ordinary_paragraph_visible_characters.target_max", minimum=target_min)
    hard_max = _integer(ordinary["hard_max"], f"{path}.ordinary_paragraph_visible_characters.hard_max", minimum=target_max)
    if (target_min, target_max, hard_max) != (60, 220, 360):
        _fail("style_profile_incompatible", f"{path}.ordinary_paragraph_visible_characters", "段落字符门必须为 60/220/360。")
    targets = _mapping(contract["length_mode_paragraph_targets"], f"{path}.length_mode_paragraph_targets")
    _fields(targets, {"minimal", "balanced", "epic"}, f"{path}.length_mode_paragraph_targets")
    compiled_targets: dict[str, dict[str, int]] = {}
    for mode, expected_range in {"minimal": (2, 4), "balanced": (4, 8), "epic": (7, 14)}.items():
        item = _mapping(targets[mode], f"{path}.length_mode_paragraph_targets.{mode}")
        _fields(item, {"minimum", "maximum"}, f"{path}.length_mode_paragraph_targets.{mode}")
        minimum = _integer(item["minimum"], f"{path}.length_mode_paragraph_targets.{mode}.minimum", minimum=1)
        maximum = _integer(item["maximum"], f"{path}.length_mode_paragraph_targets.{mode}.maximum", minimum=minimum)
        if (minimum, maximum) != expected_range:
            _fail("style_profile_incompatible", f"{path}.length_mode_paragraph_targets.{mode}", "长度模式段落范围漂移。")
        compiled_targets[mode] = {"minimum": minimum, "maximum": maximum}
    triggers = _unique_texts(contract["new_paragraph_triggers"], f"{path}.new_paragraph_triggers", maximum=60, required=True)
    expected_triggers = {
        "time_change", "location_change", "camera_change", "actor_change", "speaker_change",
        "information_level_change", "situation_turn", "player_action_hook",
    }
    if set(triggers) != expected_triggers:
        _fail("style_profile_incompatible", f"{path}.new_paragraph_triggers", "自然段触发集合不完整。")
    expected_literals = {
        "special_block_overflow": "split_with_shared_group_ref",
        "short_dialogue_or_turn_sentence_may_be_below_target_min": True,
        "paragraph_boundaries_are_authoritative": True,
        "empty_lines_are_not_the_schema": True,
        "choices_or_resolution_results_may_not_be_embedded": True,
        "humanizer_may_reorder_merge_or_split_blocks": False,
    }
    for key, expected in expected_literals.items():
        if contract[key] != expected:
            _fail("style_policy_conflict", f"{path}.{key}", "段落安全语义不允许漂移。")
    return {
        "structure": contract["structure"],
        "allowed_block_kinds": sorted(kinds),
        "required_block_fields": sorted(block_fields),
        "ordinary_paragraph_visible_characters": {"target_min": target_min, "target_max": target_max, "hard_max": hard_max},
        "length_mode_paragraph_targets": compiled_targets,
        "new_paragraph_triggers": triggers,
        **expected_literals,
    }


def _validate_runtime_generation(value: object) -> dict[str, Any]:
    path = "$.runtime_generation"
    runtime = _mapping(value, path)
    fields = {
        "integration", "additional_polish_calls", "additional_humanizer_calls",
        "additional_segmentation_calls", "channel_specific_rewrite_calls",
        "web_qq_and_headless_project_same_committed_narrative",
    }
    _fields(runtime, fields, path)
    if runtime["integration"] != "existing_structured_primary_generation_call":
        _fail("style_policy_conflict", f"{path}.integration", "Style 必须进入既有结构化主调用。")
    call_fields = (
        "additional_polish_calls", "additional_humanizer_calls",
        "additional_segmentation_calls", "channel_specific_rewrite_calls",
    )
    compiled = {"integration": runtime["integration"]}
    for field in call_fields:
        if _integer(runtime[field], f"{path}.{field}") != 0:
            _fail("style_policy_conflict", f"{path}.{field}", "Style/段落/渠道投影不得新增模型调用。")
        compiled[field] = 0
    if runtime["web_qq_and_headless_project_same_committed_narrative"] is not True:
        _fail("style_policy_conflict", f"{path}.web_qq_and_headless_project_same_committed_narrative", "跨表面必须投影同一 committed Narrative。")
    compiled["web_qq_and_headless_project_same_committed_narrative"] = True
    compiled["additional_model_calls"] = 0
    return compiled


def compile_story_pack_narrative_style_candidate(
    style_document: Mapping[str, Any],
    coverage_document: Mapping[str, Any],
    openings_document: Mapping[str, Any],
) -> dict[str, Any]:
    """Adapt the real Thirteenth Seat candidate source into public Style IR/runtime."""
    style = _mapping(style_document, "$")
    coverage = _mapping(coverage_document, "coverage")
    openings = _mapping(openings_document, "openings")
    _fields(style, _CANDIDATE_FIELDS, "$")
    _fields(coverage, _COVERAGE_FIELDS, "coverage")
    _fields(openings, _OPENINGS_FIELDS, "openings")
    if style["schema"] != STORY_PACK_STYLE_CANDIDATE_SCHEMA or coverage["schema"] != STORY_PACK_STYLE_COVERAGE_SCHEMA:
        _fail("style_contract_unsupported", "$", "Story Pack Narrative Style candidate 合同不受支持。")
    if openings["schema"] != STORY_PACK_OPENINGS_SCHEMA:
        _fail("style_contract_unsupported", "openings.schema", "Story Pack openings 合同不受支持。")
    if style["candidate_version"] != "unassigned" or coverage["candidate_version"] != "unassigned":
        _fail("style_profile_incompatible", "$.candidate_version", "适配器只接受未分配候选。")
    _required_false(style["installable"], "$.installable")
    _required_false(coverage["installable"], "coverage.installable")
    if style["expression_only"] is not True:
        _fail("style_policy_conflict", "$.expression_only", "Narrative Style 必须保持 expression-only。")
    locale = _text(style["locale"], "$.locale", 35)
    if coverage["profile_source_path"] != _STORY_PACK_PROFILE_PATH or coverage["source_catalog_path"] != _STORY_PACK_OPENINGS_PATH:
        _fail("style_digest_mismatch", "coverage", "coverage 必须绑定固定候选源路径。")

    paragraph_contract = _validate_paragraph_contract(style["paragraph_contract"])
    runtime_generation = _validate_runtime_generation(style["runtime_generation"])
    world_tone = _mapping(style["world_tone"], "$.world_tone")
    _fields(world_tone, {"core", "darkness_source", "epic_source", "grounding_rule", "uncertainty_rule"}, "$.world_tone")
    normalized_world_tone = {key: _text(world_tone[key], f"$.world_tone.{key}", 600) for key in sorted(world_tone)}
    shared_taboos = _unique_texts(style["shared_taboos"], "$.shared_taboos", maximum=240, required=True)
    must_preserve = _unique_texts(style["must_preserve"], "$.must_preserve", maximum=80, required=True)
    requirement_refs = _unique_texts(style["requirement_refs"], "$.requirement_refs", maximum=80, required=True)
    coverage_requirement_refs = _unique_texts(coverage["requirement_refs"], "coverage.requirement_refs", maximum=80, required=True)
    if not set(coverage_requirement_refs) & set(requirement_refs):
        _fail("style_profile_incompatible", "coverage.requirement_refs", "coverage 与 Style 源没有共同需求锚点。")

    presets: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(_sequence(style["narrative_presets"], "$.narrative_presets")):
        path = f"$.narrative_presets[{index}]"
        item = _mapping(raw, path)
        _fields(item, _SOURCE_PRESET_FIELDS, path)
        preset_ref = _ref(item["preset_ref"], f"{path}.preset_ref")
        if preset_ref in presets or preset_ref not in PRESET_SPECS:
            _fail("style_profile_incompatible", f"{path}.preset_ref", "preset 缺失、重复或不受支持。")
        dialogue = _integer(item["dialogue_weight"], f"{path}.dialogue_weight", maximum=100)
        description = _integer(item["description_weight"], f"{path}.description_weight", maximum=100)
        if dialogue + description != 100:
            _fail("style_policy_conflict", path, "对白与描写权重之和必须为 100。")
        presets[preset_ref] = {
            "preset_ref": preset_ref,
            "player_name": _text(item["player_name"], f"{path}.player_name", 120),
            "dialogue_weight": dialogue,
            "description_weight": description,
            "directive": _text(item["directive"], f"{path}.directive", 360),
            "prohibition": _text(item["prohibition"], f"{path}.prohibition", 360),
        }
    if set(presets) != set(PRESET_SPECS):
        _fail("style_profile_incompatible", "$.narrative_presets", "候选必须精确声明五档 preset。")
    preset_order = ("dialogue_high", "dialogue_soft", "balanced", "description_soft", "description_high")
    dialogue_curve = [presets[key]["dialogue_weight"] for key in preset_order]
    description_curve = [presets[key]["description_weight"] for key in preset_order]
    if not all(left > right for left, right in zip(dialogue_curve, dialogue_curve[1:])) or not all(left < right for left, right in zip(description_curve, description_curve[1:])):
        _fail("style_policy_conflict", "$.narrative_presets", "Story Pack 五档权重必须严格单调且可区分。")
    default_preset = _ref(style["default_preset_ref"], "$.default_preset_ref")
    if default_preset not in presets:
        _fail("style_profile_incompatible", "$.default_preset_ref", "默认 preset 未解析。")

    variants: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(_sequence(style["phase_variants"], "$.phase_variants")):
        path = f"$.phase_variants[{index}]"
        item = _mapping(raw, path)
        _fields(item, _SOURCE_VARIANT_FIELDS, path)
        phase = item["phase_kind"]
        if phase not in PHASE_KINDS or phase in variants:
            _fail("style_variant_invalid", f"{path}.phase_kind", "phase variant 缺失、重复或无效。")
        variants[phase] = {
            "player_name": _text(item["player_name"], f"{path}.player_name", 120),
            "rhythm": _text(item["rhythm"], f"{path}.rhythm", 320),
            "focus": _text(item["focus"], f"{path}.focus", 160),
            "boundary": _text(item["boundary"], f"{path}.boundary", 320),
        }
    if set(variants) != set(PHASE_KINDS):
        _fail("style_variant_invalid", "$.phase_variants", "候选必须精确声明六种 phase variant。")

    source_profiles = _sequence(style["profiles"], "$.profiles")
    normalized_profiles: list[dict[str, Any]] = []
    profile_source_index: dict[str, int] = {}
    default_profiles: list[str] = []
    for index, raw in enumerate(source_profiles):
        path = f"$.profiles[{index}]"
        item = _mapping(raw, path)
        _fields(item, _SOURCE_PROFILE_FIELDS, path)
        profile_ref = _ref(item["profile_ref"], f"{path}.profile_ref")
        if profile_ref in profile_source_index:
            _fail("style_profile_incompatible", f"{path}.profile_ref", "profile_ref 不得重复。")
        profile_source_index[profile_ref] = index
        if _boolean(item["is_default"], f"{path}.is_default"):
            default_profiles.append(profile_ref)
        allowed = _unique_texts(item["allowed_preset_refs"], f"{path}.allowed_preset_refs", maximum=40, required=True)
        if set(allowed) != set(presets):
            _fail("style_profile_incompatible", f"{path}.allowed_preset_refs", "每个候选 Profile 必须覆盖全部五档。")
        base_instruction = "；".join((
            _text(item["summary"], f"{path}.summary", 600),
            f"perspective={_ref(item['perspective'], f'{path}.perspective')}",
            f"narrative_distance={_ref(item['narrative_distance'], f'{path}.narrative_distance')}",
            _text(item["rhythm"], f"{path}.rhythm", 600),
            normalized_world_tone["grounding_rule"],
            normalized_world_tone["uncertainty_rule"],
        ))
        phase_documents = []
        for phase in PHASE_KINDS:
            source_variant = variants[phase]
            phase_documents.append({
                "variant_ref": f"{profile_ref}.variant.{phase}",
                "phase": phase,
                "instruction": source_variant["boundary"],
                "audience_ceiling": ["actor"] if phase == "private_parallel" else list(_ADAPTER_AUDIENCE_CEILING),
                "narrative_distance": "只使用当前 audience 获准的有限视角",
                "sentence_rhythm": source_variant["rhythm"],
                "sensory_focus": [source_variant["focus"]],
            })
        normalized_profiles.append({
            "schema": NARRATIVE_STYLE_PROFILE_SCHEMA,
            "profile_ref": profile_ref,
            "profile_version": "candidate-unassigned",
            "locale": locale,
            "label": _text(item["player_name"], f"{path}.player_name", 120),
            "public_summary": _text(item["summary"], f"{path}.summary", 600),
            "world_voice_summary": normalized_world_tone["core"],
            "base_instruction": base_instruction,
            "hard_constraints": [f"must_preserve:{entry}" for entry in must_preserve] + [normalized_world_tone["grounding_rule"], normalized_world_tone["uncertainty_rule"]],
            "forbidden_expressions": shared_taboos,
            "audience_ceiling": list(_ADAPTER_AUDIENCE_CEILING),
            "default_preset": default_preset,
            "allowed_presets": sorted(presets),
            "preset_definitions": [
                {
                    "preset": preset_ref,
                    "dialogue_weight": presets[preset_ref]["dialogue_weight"],
                    "description_weight": presets[preset_ref]["description_weight"],
                    "directive": presets[preset_ref]["directive"],
                    "prohibition": presets[preset_ref]["prohibition"],
                }
                for preset_ref in sorted(presets)
            ],
            "phase_variants": phase_documents,
            "customization": {"enabled": False, "max_chars": 0, "allowed_topics": []},
            "budgets": {"base_max_chars": 900, "variant_max_chars": 300, "compiled_max_chars": 1800},
        })
    default_profile = _ref(style["default_profile_ref"], "$.default_profile_ref")
    if default_profiles != [default_profile] or default_profile not in profile_source_index:
        _fail("style_profile_incompatible", "$.default_profile_ref", "候选必须有且仅有一个匹配的默认 Profile。")
    if len(normalized_profiles) != 3:
        _fail("style_profile_incompatible", "$.profiles", "当前候选必须精确包含三套 Profile。")

    profile_irs = [compile_narrative_style_profile(item) for item in normalized_profiles]
    profile_irs.sort(key=lambda item: item["profile_ref"])

    coverage_counts = _mapping(coverage["counts"], "coverage.counts")
    _fields(coverage_counts, {"profiles", "presets", "phase_variants", "source_openings", "covered_openings"}, "coverage.counts")
    expected_counts = {"profiles": 3, "presets": 5, "phase_variants": 6, "source_openings": 10, "covered_openings": 10}
    if any(_integer(coverage_counts[key], f"coverage.counts.{key}") != value for key, value in expected_counts.items()):
        _fail("style_profile_incompatible", "coverage.counts", "Style coverage 计数与冻结候选不一致。")
    shared = _mapping(coverage["shared_application"], "coverage.shared_application")
    _fields(shared, {"paragraph_contract_ref", "runtime_generation_ref", "covered_phase_kinds"}, "coverage.shared_application")
    if shared["paragraph_contract_ref"] != _STORY_PACK_PROFILE_PATH + "#/paragraph_contract" or shared["runtime_generation_ref"] != _STORY_PACK_PROFILE_PATH + "#/runtime_generation":
        _fail("style_digest_mismatch", "coverage.shared_application", "共享合同引用未绑定固定 Style 源。")
    if set(_unique_texts(shared["covered_phase_kinds"], "coverage.shared_application.covered_phase_kinds", maximum=40, required=True)) != set(PHASE_KINDS):
        _fail("style_variant_invalid", "coverage.shared_application.covered_phase_kinds", "coverage 未覆盖全部六种 phase。")

    source_openings = _sequence(openings["openings"], "openings.openings")
    coverage_openings = _sequence(coverage["openings"], "coverage.openings")
    if len(source_openings) != 10 or len(coverage_openings) != 10:
        _fail("style_profile_incompatible", "coverage.openings", "实际候选必须精确包含并覆盖 10 个 opening。")
    source_by_id: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for index, raw in enumerate(source_openings):
        path = f"openings.openings[{index}]"
        opening = _mapping(raw, path)
        _fields(opening, _OPENING_FIELDS, path)
        opening_id = _ref(opening["id"], f"{path}.id")
        if opening_id in source_by_id:
            _fail("style_profile_incompatible", f"{path}.id", "opening id 不得重复。")
        prologue = _mapping(opening["prologue_story"], f"{path}.prologue_story")
        _fields(prologue, _PROLOGUE_FIELDS|({'entity_annotations'} if 'entity_annotations' in prologue else set()), f"{path}.prologue_story")
        body = _text(prologue["body"], f"{path}.prologue_story.body", 20_000)
        if prologue["sha256"] != _raw_text_digest(body):
            _fail("style_digest_mismatch", f"{path}.prologue_story.sha256", "opening 正文 digest 不匹配。")
        source_by_id[opening_id] = (index, opening)

    opening_bindings: list[dict[str, Any]] = []
    covered_ids: set[str] = set()
    hard_max = paragraph_contract["ordinary_paragraph_visible_characters"]["hard_max"]
    target_min = paragraph_contract["ordinary_paragraph_visible_characters"]["target_min"]
    target_max = paragraph_contract["ordinary_paragraph_visible_characters"]["target_max"]
    profile_refs = set(profile_source_index)
    for index, raw in enumerate(coverage_openings):
        path = f"coverage.openings[{index}]"
        item = _mapping(raw, path)
        _fields(item, _COVERAGE_OPENING_FIELDS, path)
        opening_id = _ref(item["source_opening_id"], f"{path}.source_opening_id")
        if opening_id in covered_ids or opening_id not in source_by_id:
            _fail("style_profile_incompatible", f"{path}.source_opening_id", "coverage opening 重复或悬空。")
        covered_ids.add(opening_id)
        source_index, source_opening = source_by_id[opening_id]
        if item["source_title"] != source_opening["title"] or item["source_region"] != source_opening["region"]:
            _fail("style_digest_mismatch", path, "coverage 标题或地区与 opening 源不一致。")
        prologue = _mapping(source_opening["prologue_story"], f"openings.openings[{source_index}].prologue_story")
        body = prologue["body"]
        if item["source_body_sha256"] != prologue["sha256"] or item["source_body_sha256"] != _raw_text_digest(body):
            _fail("style_digest_mismatch", f"{path}.source_body_sha256", "coverage 未绑定当前 opening 正文。")
        allowed_profiles = _unique_texts(item["allowed_profile_refs"], f"{path}.allowed_profile_refs", maximum=160, required=True)
        allowed_presets = _unique_texts(item["allowed_preset_refs"], f"{path}.allowed_preset_refs", maximum=40, required=True)
        if set(allowed_profiles) != profile_refs or set(allowed_presets) != set(presets) or item["default_profile_ref"] != default_profile:
            _fail("style_profile_incompatible", path, "opening Style 选择集合与候选目录不一致。")
        sensory_anchors = _unique_texts(item["sensory_anchors"], f"{path}.sensory_anchors", maximum=80, required=True)
        paragraphs = _paragraphs(body, path=f"openings.openings[{source_index}].prologue_story.body", hard_max=hard_max)
        from .authored_narrative_annotations import compile_authored_annotations,compile_authored_blocks
        try:
            span_blocks=compile_authored_blocks(source_opening,paragraphs)
            annotations=None if span_blocks is not None else compile_authored_annotations(source_opening,paragraphs)
        except (KeyError,TypeError,ValueError):_fail('style_reference_invalid',f'openings.openings[{source_index}].prologue_story.entity_annotations','静态正文引用与作者身份、可见范围或正文不一致。')
        blocks = []
        outside_target = 0
        for order, paragraph in enumerate(paragraphs, start=1):
            visible = len("".join(paragraph.split()))
            if not target_min <= visible <= target_max:
                outside_target += 1
        if span_blocks is not None:
            # Author spans: output blocks are counted, ordered and source
            # anchored directly, and every unannotated gap stays a paragraph.
            for order, span in enumerate(span_blocks, start=1):
                blocks.append({
                    "block_ref": f"{opening_id}.{span['kind']}.{order:02d}",
                    "kind": span['kind'],
                    "order": order,
                    "locale": locale,
                    "audience": "party",
                    "source_ref": f"{_STORY_PACK_OPENINGS_PATH}#/openings/{source_index}/prologue_story/body?paragraph={span['sequence']}&start={span['start']}&end={span['end']}",
                    "text": span['text'],
                    "text_digest": _raw_text_digest(span['text']),
                    "references": span['references'],
                    "speaker": span['speaker'],
                    "reference_status": span['reference_status'],
                })
            document_schema = SPAN_OPENING_DOCUMENT_SCHEMA
        else:
            for order, paragraph in enumerate(paragraphs, start=1):
                blocks.append({
                    "block_ref": f"{opening_id}.paragraph.{order:02d}",
                    "kind": "paragraph",
                    "order": order,
                    "locale": locale,
                    "audience": "party",
                    "source_ref": f"{_STORY_PACK_OPENINGS_PATH}#/openings/{source_index}/prologue_story/body",
                    "text": paragraph,
                    "text_digest": _raw_text_digest(paragraph),
                })
                if annotations is not None:blocks[-1].update(annotations[order-1])
            document_schema = REFERENCED_OPENING_DOCUMENT_SCHEMA if annotations is not None else LEGACY_OPENING_DOCUMENT_SCHEMA
        narrative_document = {
            "schema": document_schema,
            "opening_ref": opening_id,
            "blocks": blocks,
            "paragraph_count": len(blocks),
            "outside_target_count": outside_target,
            "hard_limit_violations": 0,
        }
        narrative_document["document_sha256"] = _digest({key: value for key, value in narrative_document.items() if key != "document_sha256"})
        opening_bindings.append({
            "opening_ref": opening_id,
            "title": _text(item["source_title"], f"{path}.source_title", 160),
            "region": _text(item["source_region"], f"{path}.source_region", 160),
            "source_body_sha256": item["source_body_sha256"],
            "default_profile_ref": default_profile,
            "allowed_profile_refs": allowed_profiles,
            "allowed_preset_refs": allowed_presets,
            "sensory_anchors": sensory_anchors,
            "narrative_document": narrative_document,
        })
        try:event_narratives=compile_event_annotations(source_opening,locale,source_index)
        except (KeyError,TypeError,ValueError):_fail('style_event_reference_invalid',f'openings.openings[{source_index}].initial_state.event_narrative_annotations','事件引用与作者身份或正文不一致。')
        if event_narratives:opening_bindings[-1]['event_narratives']=event_narratives
    if covered_ids != set(source_by_id):
        _fail("style_profile_incompatible", "coverage.openings", "coverage 必须逐项覆盖全部 opening。")
    opening_bindings.sort(key=lambda item: item["opening_ref"])

    runtime = {
        "schema": NARRATIVE_STYLE_REFERENCED_RUNTIME_SCHEMA if any(
            b['narrative_document']['schema'] in {REFERENCED_OPENING_DOCUMENT_SCHEMA, SPAN_OPENING_DOCUMENT_SCHEMA} for b in opening_bindings
        ) else NARRATIVE_STYLE_CANDIDATE_RUNTIME_SCHEMA,
        "source_candidate_schema": STORY_PACK_STYLE_CANDIDATE_SCHEMA,
        "coverage_schema": STORY_PACK_STYLE_COVERAGE_SCHEMA,
        "openings_schema": STORY_PACK_OPENINGS_SCHEMA,
        "candidate_version": "unassigned",
        "installable": False,
        "locale": locale,
        "default_profile_ref": default_profile,
        "default_preset_ref": default_preset,
        "source_style_sha256": _digest(style),
        "source_coverage_sha256": _digest(coverage),
        "source_openings_sha256": _digest(openings),
        "requirement_refs": requirement_refs,
        "paragraph_contract": paragraph_contract,
        "runtime_generation": runtime_generation,
        "preset_catalog": [presets[key] for key in sorted(presets)],
        "profile_irs": profile_irs,
        "adapter_source_map": [
            {"ir_ref": ref, "source_path": f"{_STORY_PACK_PROFILE_PATH}#/profiles/{profile_source_index[ref]}"}
            for ref in sorted(profile_source_index)
        ],
        "opening_bindings": opening_bindings,
        "counts": {
            "profiles": len(profile_irs),
            "presets": len(presets),
            "phase_variants": len(variants),
            "style_slices": sum(len(item["style_slices"]) for item in profile_irs),
            "source_openings": len(source_by_id),
            "covered_openings": len(opening_bindings),
            "narrative_blocks": sum(len(item["narrative_document"]["blocks"]) for item in opening_bindings),
        },
        "model_calls": 0,
    }
    runtime["runtime_sha256"] = _digest(runtime)
    if any(b.get('event_narratives') for b in opening_bindings):
        runtime['schema']=NARRATIVE_STYLE_EVENT_RUNTIME_SCHEMA
        runtime['runtime_sha256']=_digest({k:v for k,v in runtime.items() if k!='runtime_sha256'})
    return runtime


def load_story_pack_narrative_style_candidate(worktree_root: str | Path) -> dict[str, Any]:
    """Read the fixed real candidate paths below one Story Pack worktree root."""
    root = Path(worktree_root).resolve()
    if not root.is_dir():
        _fail("style_profile_missing", str(root), "Story Pack worktree 根目录不存在。")

    def load(relative: str) -> Mapping[str, Any]:
        path = (root / Path(relative)).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            _fail("style_profile_incompatible", relative, "候选路径越出 Story Pack worktree。")
        if not path.is_file():
            _fail("style_profile_missing", relative, "候选文件不存在。")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            _fail("style_profile_incompatible", relative, f"候选文件不是有效 UTF-8 JSON: {exc}")
        return _mapping(value, relative)

    return compile_story_pack_narrative_style_candidate(
        load(_STORY_PACK_PROFILE_PATH),
        load(_STORY_PACK_COVERAGE_PATH),
        load(_STORY_PACK_OPENINGS_PATH),
    )


def validate_story_pack_narrative_style_runtime(
    value: Mapping[str, Any],
    style_document: Mapping[str, Any],
    coverage_document: Mapping[str, Any],
    openings_document: Mapping[str, Any],
) -> None:
    """Validate the public candidate runtime by digest and exact recompilation."""
    runtime = _mapping(value, "$")
    _fields(runtime, _CANDIDATE_RUNTIME_FIELDS, "$")
    if runtime['schema'] not in NARRATIVE_STYLE_RUNTIME_SCHEMAS | {NARRATIVE_STYLE_EVENT_RUNTIME_SCHEMA}:
        _fail("style_contract_unsupported", "$.schema", "Narrative Style runtime 合同不受支持。")
    if runtime["installable"] is not False:
        _fail("style_profile_incompatible", "$.installable", "候选 runtime 不得声明为可安装。")
    runtime_generation = _mapping(runtime["runtime_generation"], "$.runtime_generation")
    model_calls = runtime["model_calls"]
    additional_calls = runtime_generation.get("additional_model_calls")
    if isinstance(model_calls, bool) or model_calls != 0 or isinstance(additional_calls, bool) or additional_calls != 0:
        _fail("style_policy_conflict", "$.model_calls", "候选适配和投影不得新增模型调用。")
    if runtime["runtime_sha256"] != _digest({key: item for key, item in runtime.items() if key != "runtime_sha256"}):
        _fail("style_digest_mismatch", "$.runtime_sha256", "候选 runtime digest 与内容不一致。")
    for index, raw_profile_ir in enumerate(_sequence(runtime["profile_irs"], "$.profile_irs")):
        profile_ir = _mapping(raw_profile_ir, f"$.profile_irs[{index}]")
        if profile_ir.get("ir_sha256") != _digest({key: item for key, item in profile_ir.items() if key != "ir_sha256"}):
            _fail("style_digest_mismatch", "$.profile_irs", "嵌套 Style IR digest 与内容不一致。")
    rebuilt = compile_story_pack_narrative_style_candidate(style_document, coverage_document, openings_document)
    if runtime != rebuilt:
        _fail("style_digest_mismatch", "$", "候选 runtime 必须逐字段匹配实际 Story Pack 源的确定性重编译结果。")


__all__ = [
    "AUDIENCES", "NARRATIVE_STYLE_CANDIDATE_RUNTIME_SCHEMA", "NARRATIVE_STYLE_IR_SCHEMA",
    "NARRATIVE_STYLE_PROFILE_SCHEMA", "PHASE_KINDS", "PRESET_SPECS",
    "STORY_PACK_OPENINGS_SCHEMA", "STORY_PACK_STYLE_CANDIDATE_SCHEMA",
    "STORY_PACK_STYLE_COVERAGE_SCHEMA", "NarrativeStyleContractError",
    "compile_narrative_style_profile", "compile_story_pack_narrative_style_candidate",
    "load_story_pack_narrative_style_candidate", "validate_narrative_style_ir",
    "validate_story_pack_narrative_style_runtime",
]
