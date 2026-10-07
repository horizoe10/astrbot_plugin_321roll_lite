"""Strict producer-first compilation for Story Pack resolution-rule candidates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


RESOLUTION_RULE_CANDIDATE_SCHEMA = "sp-resolution-rule-contract-candidate/0.2"
RESOLUTION_RULE_DEFINITION_IR_SCHEMA = "se-resolution-rule-definition-ir/1.0.0"
MODIFIER_SOURCE_CATALOG_IR_SCHEMA = "se-modifier-source-catalog-ir/1.0.0"
RESOLUTION_RULE_CATALOG_IR_SCHEMA = "se-resolution-rule-catalog-ir/1.0.0"

_DOCUMENT_FIELDS = frozenset({
    "schema", "contract_kind", "maturity", "requirement_refs",
    "resolution_rule_definitions", "modifier_source_catalog",
    "post_resolution_narrative_binding",
})
_RULE_FIELDS = frozenset({
    "resolution_rule_ref", "roll_expression", "margin", "rng_policy",
    "natural_roll_overrides", "modifier_source_refs", "result_bands",
})
_SOURCE_FIELDS = frozenset({
    "modifier_source_ref", "source_authority", "modifier_bounds", "stacking",
    "narrative_constraint",
})
_BINDING_FIELDS = frozenset({
    "binding_ref", "input_policy", "required_receipt_fields",
    "narrative_may_not_reinterpret_outcome", "band_bindings",
})
_REQUIRED_RECEIPT_FIELDS = {
    "resolution_receipt_ref", "outcome_band_ref", "margin", "modifier_receipt_refs",
}


@dataclass(frozen=True, slots=True)
class ResolutionRuleContractError(ValueError):
    code: str
    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.code}:{self.path}"


def _fail(code: str, path: str, reason: str) -> None:
    raise ResolutionRuleContractError(code, path, reason)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail("resolution_rule.non_canonical_value", "$", f"值无法形成 canonical JSON: {exc}")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("resolution_rule.object_invalid", path, "字段必须是 JSON 对象。")
    return value


def _sequence(value: object, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("resolution_rule.sequence_invalid", path, "字段必须是 JSON 数组。")
    return value


def _fields(value: Mapping[str, Any], expected: frozenset[str] | set[str], path: str) -> None:
    if set(value) != set(expected):
        _fail("resolution_rule.fields_invalid", path, "字段不完整或包含未知字段。")


def _text(value: object, path: str, maximum: int = 600) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        _fail("resolution_rule.text_invalid", path, "字段必须是有界非空文本。")
    return value.strip()


def _ref(value: object, path: str) -> str:
    result = _text(value, path, 160)
    if not result[0].isalnum() or any(not (character.isalnum() or character in "_.:@-") for character in result):
        _fail("resolution_rule.reference_invalid", path, "字段必须是稳定引用。")
    return result


def _integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("resolution_rule.integer_invalid", path, "字段必须是整数。")
    return value


def _world_rules(value: object, *, path: str = "world") -> list[Mapping[str, Any]]:
    found: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        if "rule_id" in value:
            found.append(value)
        for child in value.values():
            found.extend(_world_rules(child, path=path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            found.extend(_world_rules(child, path=path))
    return found


def _compile_bands(raw_bands: object, path: str) -> list[dict[str, Any]]:
    bands: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(_sequence(raw_bands, path)):
        band_path = f"{path}[{index}]"
        band = _mapping(raw, band_path)
        _fields(band, {"band_ref", "margin_condition", "outcome", "degree"}, band_path)
        band_ref = _ref(band["band_ref"], f"{band_path}.band_ref")
        if band_ref in seen:
            _fail("resolution_rule.band_duplicate", f"{band_path}.band_ref", "结果带引用重复。")
        seen.add(band_ref)
        condition = _mapping(band["margin_condition"], f"{band_path}.margin_condition")
        _fields(condition, {"minimum_inclusive", "maximum_inclusive"}, f"{band_path}.margin_condition")
        minimum = condition["minimum_inclusive"]
        maximum = condition["maximum_inclusive"]
        if minimum is not None:
            minimum = _integer(minimum, f"{band_path}.margin_condition.minimum_inclusive")
        if maximum is not None:
            maximum = _integer(maximum, f"{band_path}.margin_condition.maximum_inclusive")
        if minimum is not None and maximum is not None and minimum > maximum:
            _fail("resolution_rule.band_range_invalid", f"{band_path}.margin_condition", "结果带下界不得大于上界。")
        outcome = band["outcome"]
        if outcome not in {"success", "failure"}:
            _fail("resolution_rule.outcome_invalid", f"{band_path}.outcome", "结果必须是 success 或 failure。")
        bands.append({
            "band_ref": band_ref,
            "margin_min": minimum,
            "margin_max": maximum,
            "outcome": outcome,
            "degree": _ref(band["degree"], f"{band_path}.degree"),
        })
    if not bands:
        _fail("resolution_rule.bands_empty", path, "至少需要一个结果带。")
    ordered = sorted(bands, key=lambda item: float("-inf") if item["margin_min"] is None else item["margin_min"])
    if ordered[0]["margin_min"] is not None or ordered[-1]["margin_max"] is not None:
        _fail("resolution_rule.bands_incomplete", path, "结果带必须覆盖全部整数 margin。")
    for left, right in zip(ordered, ordered[1:], strict=False):
        maximum = left["margin_max"]
        minimum = right["margin_min"]
        if maximum is None or minimum is None or maximum + 1 != minimum:
            _fail("resolution_rule.bands_not_partition", path, "结果带必须完整、连续且互斥。")
    return ordered


def _compile_binding(raw: object, band_refs: set[str]) -> dict[str, Any]:
    binding = _mapping(raw, "post_resolution_narrative_binding")
    _fields(binding, _BINDING_FIELDS, "post_resolution_narrative_binding")
    if binding["input_policy"] != "committed_receipt_only" or binding["narrative_may_not_reinterpret_outcome"] is not True:
        _fail("resolution_rule.post_binding_authority_invalid", "post_resolution_narrative_binding", "叙事只能读取已提交回执且不得重释结果。")
    receipt_fields = [_ref(item, "post_resolution_narrative_binding.required_receipt_fields") for item in _sequence(binding["required_receipt_fields"], "post_resolution_narrative_binding.required_receipt_fields")]
    if len(receipt_fields) != len(set(receipt_fields)) or set(receipt_fields) != _REQUIRED_RECEIPT_FIELDS:
        _fail("resolution_rule.receipt_fields_invalid", "post_resolution_narrative_binding.required_receipt_fields", "回执字段必须精确覆盖规则结果、margin 与 modifier 回执。")
    compiled_bindings: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw_band in enumerate(_sequence(binding["band_bindings"], "post_resolution_narrative_binding.band_bindings")):
        band = _mapping(raw_band, f"post_resolution_narrative_binding.band_bindings[{index}]")
        _fields(band, {"band_ref", "narrative_aspect"}, f"post_resolution_narrative_binding.band_bindings[{index}]")
        band_ref = _ref(band["band_ref"], f"post_resolution_narrative_binding.band_bindings[{index}].band_ref")
        if band_ref in seen:
            _fail("resolution_rule.post_binding_duplicate", f"post_resolution_narrative_binding.band_bindings[{index}].band_ref", "结果带叙事绑定重复。")
        seen.add(band_ref)
        compiled_bindings.append({"band_ref": band_ref, "narrative_aspect": _ref(band["narrative_aspect"], f"post_resolution_narrative_binding.band_bindings[{index}].narrative_aspect")})
    if seen != band_refs:
        _fail("resolution_rule.post_binding_incomplete", "post_resolution_narrative_binding.band_bindings", "每个且仅每个结果带都必须有叙事绑定。")
    material = {
        "schema": "se-post-resolution-narrative-binding-ir/1.0.0",
        "binding_ref": _ref(binding["binding_ref"], "post_resolution_narrative_binding.binding_ref"),
        "input_policy": "committed_receipt_only",
        "required_receipt_fields": sorted(receipt_fields),
        "narrative_may_not_reinterpret_outcome": True,
        "band_bindings": sorted(compiled_bindings, key=lambda item: item["band_ref"]),
    }
    material["binding_sha256"] = _digest(material)
    return material


def compile_resolution_rule_contract(document: Mapping[str, Any], world: Mapping[str, Any]) -> dict[str, Any]:
    """Compile one SP candidate into three deterministic Engine-owned IR products."""
    doc = _mapping(document, "$")
    _fields(doc, _DOCUMENT_FIELDS, "$")
    if doc["schema"] != RESOLUTION_RULE_CANDIDATE_SCHEMA or doc["contract_kind"] != "ResolutionRuleDefinition" or doc["maturity"] != "candidate":
        _fail("resolution_rule.document_incompatible", "$", "只接受明确的 SP 0.2 candidate resolution-rule 合同。")
    requirements = [_ref(item, "requirement_refs") for item in _sequence(doc["requirement_refs"], "requirement_refs")]
    if not requirements or len(requirements) != len(set(requirements)):
        _fail("resolution_rule.requirement_refs_invalid", "requirement_refs", "需求引用必须非空且唯一。")
    world_value = _mapping(world, "world")
    world_digest = _digest(world_value)
    available_rules: dict[str, list[Mapping[str, Any]]] = {}
    for world_rule in _world_rules(world_value):
        rule_id = world_rule.get("rule_id")
        if isinstance(rule_id, str):
            available_rules.setdefault(rule_id, []).append(world_rule)

    source_document = _mapping(doc["modifier_source_catalog"], "modifier_source_catalog")
    _fields(source_document, {"catalog_kind", "sources"}, "modifier_source_catalog")
    if source_document["catalog_kind"] != "ModifierSourceCatalog":
        _fail("resolution_rule.modifier_catalog_kind_invalid", "modifier_source_catalog.catalog_kind", "modifier catalog kind 不兼容。")
    compiled_sources: list[dict[str, Any]] = []
    source_refs: set[str] = set()
    for index, raw_source in enumerate(_sequence(source_document["sources"], "modifier_source_catalog.sources")):
        path = f"modifier_source_catalog.sources[{index}]"
        source = _mapping(raw_source, path)
        _fields(source, _SOURCE_FIELDS, path)
        source_ref = _ref(source["modifier_source_ref"], f"{path}.modifier_source_ref")
        if source_ref in source_refs:
            _fail("resolution_rule.modifier_source_duplicate", f"{path}.modifier_source_ref", "modifier source 引用重复。")
        source_refs.add(source_ref)
        authority = _mapping(source["source_authority"], f"{path}.source_authority")
        _fields(authority, {"source_path", "rule_id", "target_ref"}, f"{path}.source_authority")
        if authority["source_path"] != "world/core.json":
            _fail("resolution_rule.world_source_path_invalid", f"{path}.source_authority.source_path", "modifier authority 必须来自 world/core.json。")
        rule_id = _ref(authority["rule_id"], f"{path}.source_authority.rule_id")
        matches = available_rules.get(rule_id, [])
        if len(matches) != 1:
            _fail("resolution_rule.world_rule_unresolved", f"{path}.source_authority.rule_id", "world authority rule 必须存在且唯一。")
        world_rule = matches[0]
        if set(world_rule) != {"effects", "enabled", "mode", "priority", "rule_id", "stacking", "triggers", "when"} or world_rule.get("enabled") is not True or world_rule.get("mode") != "hybrid":
            _fail("resolution_rule.world_rule_shape_invalid", f"world.rule[{rule_id}]", "world rule 必须是启用的有限 hybrid 声明，且不得夹带未知执行字段。")
        if world_rule.get("triggers") != [{"event": "action.requested", "phase": "before_resolution"}]:
            _fail("resolution_rule.world_trigger_invalid", f"world.rule[{rule_id}].triggers", "modifier 必须只在 resolution 前的 action.requested 触发。")
        target_ref = _ref(authority["target_ref"], f"{path}.source_authority.target_ref")
        bounds = _mapping(source["modifier_bounds"], f"{path}.modifier_bounds")
        _fields(bounds, {"minimum", "maximum"}, f"{path}.modifier_bounds")
        minimum = _integer(bounds["minimum"], f"{path}.modifier_bounds.minimum")
        maximum = _integer(bounds["maximum"], f"{path}.modifier_bounds.maximum")
        if minimum > maximum:
            _fail("resolution_rule.modifier_bounds_invalid", f"{path}.modifier_bounds", "modifier 下界不得大于上界。")
        stacking = _mapping(source["stacking"], f"{path}.stacking")
        _fields(stacking, {"group", "limit", "strategy"}, f"{path}.stacking")
        compiled_stacking = {"group": _ref(stacking["group"], f"{path}.stacking.group"), "limit": _integer(stacking["limit"], f"{path}.stacking.limit"), "strategy": stacking["strategy"]}
        if compiled_stacking["limit"] < 1 or compiled_stacking["strategy"] not in {"highest", "lowest", "sum"}:
            _fail("resolution_rule.stacking_invalid", f"{path}.stacking", "stacking policy 不受支持。")
        effects = world_rule.get("effects")
        if not isinstance(effects, Sequence) or isinstance(effects, (str, bytes, bytearray)):
            _fail("resolution_rule.world_effects_invalid", f"world.rule[{rule_id}].effects", "world rule effects 无效。")
        numeric_effects = [item for item in effects if isinstance(item, Mapping) and item.get("op") == "modify_value" and item.get("target_ref") == target_ref and isinstance(item.get("value"), int) and not isinstance(item.get("value"), bool)]
        narrative = _text(source["narrative_constraint"], f"{path}.narrative_constraint")
        narrative_effects = [item for item in effects if isinstance(item, Mapping) and item.get("op") == "add_narrative_constraint" and item.get("value") == narrative]
        if len(effects) != 2 or any(not isinstance(item, Mapping) or set(item) != ({"op", "target_ref", "value"} if item.get("op") == "modify_value" else {"op", "value"}) for item in effects):
            _fail("resolution_rule.world_effects_invalid", f"world.rule[{rule_id}].effects", "world rule 必须只声明一项固定 modifier 和一项叙事约束。")
        if len(numeric_effects) != 1 or minimum != numeric_effects[0]["value"] or maximum != numeric_effects[0]["value"] or len(narrative_effects) != 1 or world_rule.get("stacking") != dict(compiled_stacking):
            _fail("resolution_rule.world_authority_mismatch", path, "candidate modifier 数值、stacking 或叙事约束无法由 world rule 证明。")
        raw_when = _mapping(world_rule.get("when"), f"world.rule[{rule_id}].when")
        _fields(raw_when, {"all"}, f"world.rule[{rule_id}].when")
        conditions: list[dict[str, Any]] = []
        for condition_index, raw_condition in enumerate(_sequence(raw_when["all"], f"world.rule[{rule_id}].when.all")):
            condition_path = f"world.rule[{rule_id}].when.all[{condition_index}]"
            condition = _mapping(raw_condition, condition_path)
            _fields(condition, {"scope", "ref", "operator", "value"}, condition_path)
            if condition["scope"] not in {"action", "scene", "target", "actor"} or condition["operator"] != "==":
                _fail("resolution_rule.world_condition_invalid", condition_path, "world 条件必须可编译为平台注册的 equals 条件。")
            scalar = condition["value"]
            if scalar is not None and not isinstance(scalar, (str, int, float, bool)):
                _fail("resolution_rule.world_condition_invalid", f"{condition_path}.value", "condition value 必须是 JSON scalar。")
            # Canonicalization also rejects NaN and infinities.
            _canonical(scalar)
            conditions.append({
                "scope": condition["scope"],
                "ref": _ref(condition["ref"], f"{condition_path}.ref"),
                "operator": "equals",
                "value": scalar,
            })
        if not conditions:
            _fail("resolution_rule.world_conditions_empty", f"world.rule[{rule_id}].when", "modifier source 必须带有限、可注册的适用条件。")
        material = {
            "modifier_source_ref": source_ref,
            "world_authority_binding": {"source_path": "world/core.json", "rule_id": rule_id, "world_rule_sha256": _digest(world_rule)},
            "conditions": conditions,
            "effect": {"target_ref": target_ref, "amount": numeric_effects[0]["value"]},
            "stacking": compiled_stacking,
            "narrative_constraint": narrative,
        }
        material["source_sha256"] = _digest(material)
        compiled_sources.append(material)
    modifier_catalog = {
        "schema": MODIFIER_SOURCE_CATALOG_IR_SCHEMA,
        "source_authority": {"path": "world/core.json", "digest_algorithm": "canonical-json-utf8-v1", "digest": world_digest},
        "sources": sorted(compiled_sources, key=lambda item: item["modifier_source_ref"]),
    }
    modifier_catalog["catalog_sha256"] = _digest(modifier_catalog)

    raw_rules = _sequence(doc["resolution_rule_definitions"], "resolution_rule_definitions")
    if not raw_rules:
        _fail("resolution_rule.definitions_empty", "resolution_rule_definitions", "至少需要一条 resolution rule。")
    preliminaries: list[tuple[Mapping[str, Any], list[dict[str, Any]], set[str]]] = []
    all_band_refs: set[str] = set()
    rule_refs: set[str] = set()
    for index, raw_rule in enumerate(raw_rules):
        path = f"resolution_rule_definitions[{index}]"
        rule = _mapping(raw_rule, path)
        _fields(rule, _RULE_FIELDS, path)
        rule_ref = _ref(rule["resolution_rule_ref"], f"{path}.resolution_rule_ref")
        if rule_ref in rule_refs:
            _fail("resolution_rule.definition_duplicate", f"{path}.resolution_rule_ref", "resolution rule 引用重复。")
        rule_refs.add(rule_ref)
        if rule["roll_expression"] != "1d20":
            _fail("resolution_rule.roll_expression_invalid", f"{path}.roll_expression", "只接受固定 1d20；不得执行脚本或公式。")
        margin = _mapping(rule["margin"], f"{path}.margin")
        _fields(margin, {"calculation", "value_type"}, f"{path}.margin")
        if margin != {"calculation": "final_total - difficulty", "value_type": "integer"}:
            _fail("resolution_rule.margin_formula_invalid", f"{path}.margin", "margin 必须使用注册的 final_total - difficulty 公式。")
        rng = _mapping(rule["rng_policy"], f"{path}.rng_policy")
        _fields(rng, {"authority", "author_seed_allowed", "replay_source"}, f"{path}.rng_policy")
        if rng != {"authority": "platform_provided", "author_seed_allowed": False, "replay_source": "committed_resolution_receipt"}:
            _fail("resolution_rule.rng_authority_invalid", f"{path}.rng_policy", "RNG 与 replay authority 必须属于平台提交回执。")
        bands = _compile_bands(rule["result_bands"], f"{path}.result_bands")
        band_refs = {item["band_ref"] for item in bands}
        overrides = _mapping(rule["natural_roll_overrides"], f"{path}.natural_roll_overrides")
        _fields(overrides, {"natural_1", "natural_20"}, f"{path}.natural_roll_overrides")
        compiled_overrides = {"natural_1": _ref(overrides["natural_1"], f"{path}.natural_roll_overrides.natural_1"), "natural_20": _ref(overrides["natural_20"], f"{path}.natural_roll_overrides.natural_20")}
        if set(compiled_overrides.values()) - band_refs or compiled_overrides["natural_1"] == compiled_overrides["natural_20"]:
            _fail("resolution_rule.natural_override_invalid", f"{path}.natural_roll_overrides", "natural 1/20 必须映射到两个已定义且不同的结果带。")
        bands_by_ref = {item["band_ref"]: item for item in bands}
        natural_one = bands_by_ref[compiled_overrides["natural_1"]]
        natural_twenty = bands_by_ref[compiled_overrides["natural_20"]]
        if (natural_one["outcome"], natural_one["degree"]) != ("failure", "critical") or (natural_twenty["outcome"], natural_twenty["degree"]) != ("success", "critical"):
            _fail("resolution_rule.natural_override_invalid", f"{path}.natural_roll_overrides", "natural 1/20 必须分别绑定 critical failure 与 critical success。")
        modifiers = [_ref(item, f"{path}.modifier_source_refs") for item in _sequence(rule["modifier_source_refs"], f"{path}.modifier_source_refs")]
        if len(modifiers) != len(set(modifiers)) or set(modifiers) - source_refs:
            _fail("resolution_rule.modifier_reference_invalid", f"{path}.modifier_source_refs", "modifier source 引用必须唯一并解析到已验证 catalog。")
        all_band_refs.update(band_refs)
        preliminaries.append((rule, bands, set(modifiers)))
    binding = _compile_binding(doc["post_resolution_narrative_binding"], all_band_refs)
    definitions: list[dict[str, Any]] = []
    for rule, bands, modifiers in preliminaries:
        material = {
            "schema": RESOLUTION_RULE_DEFINITION_IR_SCHEMA,
            "resolution_rule_ref": rule["resolution_rule_ref"],
            "roll_expression": "1d20",
            "margin": {"calculation": "final_total - difficulty", "value_type": "integer"},
            "rng_policy": {"authority": "platform_provided", "author_seed_allowed": False, "replay_source": "committed_resolution_receipt"},
            "natural_roll_overrides": {"1": rule["natural_roll_overrides"]["natural_1"], "20": rule["natural_roll_overrides"]["natural_20"]},
            "modifier_source_refs": sorted(modifiers),
            "result_bands": bands,
            "post_resolution_narrative_binding": binding,
        }
        material["definition_sha256"] = _digest(material)
        definitions.append(material)
    definitions.sort(key=lambda item: item["resolution_rule_ref"])
    catalog = {
        "schema": RESOLUTION_RULE_CATALOG_IR_SCHEMA,
        "requirement_refs": sorted(requirements),
        "definitions": definitions,
        "modifier_source_catalog_sha256": modifier_catalog["catalog_sha256"],
        "post_resolution_binding_sha256": binding["binding_sha256"],
    }
    catalog["catalog_sha256"] = _digest(catalog)
    products = {
        "resolution_rule_definitions": definitions,
        "modifier_source_catalog": modifier_catalog,
        "resolution_rule_catalog": catalog,
    }
    validate_resolution_rule_products(products)
    return products


def validate_resolution_rule_products(products: Mapping[str, Any]) -> None:
    """Fail closed when compiled IR fields, digests, or cross-references are altered."""
    value = _mapping(products, "products")
    _fields(value, {"resolution_rule_definitions", "modifier_source_catalog", "resolution_rule_catalog"}, "products")
    definitions = list(_sequence(value["resolution_rule_definitions"], "products.resolution_rule_definitions"))
    modifier_catalog = _mapping(value["modifier_source_catalog"], "products.modifier_source_catalog")
    rule_catalog = _mapping(value["resolution_rule_catalog"], "products.resolution_rule_catalog")
    _fields(modifier_catalog, {"schema", "source_authority", "sources", "catalog_sha256"}, "products.modifier_source_catalog")
    _fields(rule_catalog, {"schema", "requirement_refs", "definitions", "modifier_source_catalog_sha256", "post_resolution_binding_sha256", "catalog_sha256"}, "products.resolution_rule_catalog")
    if modifier_catalog.get("schema") != MODIFIER_SOURCE_CATALOG_IR_SCHEMA or rule_catalog.get("schema") != RESOLUTION_RULE_CATALOG_IR_SCHEMA:
        _fail("resolution_rule.product_schema_invalid", "products", "compiled IR schema identity 不兼容。")
    sources = list(_sequence(modifier_catalog.get("sources"), "products.modifier_source_catalog.sources"))
    for index, raw_source in enumerate(sources):
        source = _mapping(raw_source, f"products.modifier_source_catalog.sources[{index}]")
        _fields(source, {"modifier_source_ref", "world_authority_binding", "conditions", "effect", "stacking", "narrative_constraint", "source_sha256"}, f"products.modifier_source_catalog.sources[{index}]")
        if source.get("source_sha256") != _digest({key: item for key, item in source.items() if key != "source_sha256"}):
            _fail("resolution_rule.digest_mismatch", f"products.modifier_source_catalog.sources[{index}].source_sha256", "modifier source 摘要与内容不一致。")
    if modifier_catalog.get("catalog_sha256") != _digest({key: item for key, item in modifier_catalog.items() if key != "catalog_sha256"}):
        _fail("resolution_rule.digest_mismatch", "products.modifier_source_catalog.catalog_sha256", "modifier catalog 摘要与内容不一致。")
    source_refs = {source.get("modifier_source_ref") for source in sources}
    binding_digests: set[str] = set()
    for index, raw_definition in enumerate(definitions):
        definition = _mapping(raw_definition, f"products.resolution_rule_definitions[{index}]")
        _fields(definition, {"schema", "resolution_rule_ref", "roll_expression", "margin", "rng_policy", "natural_roll_overrides", "modifier_source_refs", "result_bands", "post_resolution_narrative_binding", "definition_sha256"}, f"products.resolution_rule_definitions[{index}]")
        if definition.get("schema") != RESOLUTION_RULE_DEFINITION_IR_SCHEMA:
            _fail("resolution_rule.product_schema_invalid", f"products.resolution_rule_definitions[{index}].schema", "resolution definition schema identity 不兼容。")
        if definition.get("definition_sha256") != _digest({key: item for key, item in definition.items() if key != "definition_sha256"}):
            _fail("resolution_rule.digest_mismatch", f"products.resolution_rule_definitions[{index}].definition_sha256", "resolution definition 摘要与内容不一致。")
        if set(_sequence(definition.get("modifier_source_refs"), f"products.resolution_rule_definitions[{index}].modifier_source_refs")) - source_refs:
            _fail("resolution_rule.catalog_reference_mismatch", f"products.resolution_rule_definitions[{index}].modifier_source_refs", "definition 引用了 catalog 中不存在的 modifier source。")
        bands = {_mapping(item, "band").get("band_ref") for item in _sequence(definition.get("result_bands"), "result_bands")}
        for band_index, raw_band in enumerate(definition["result_bands"]):
            _fields(_mapping(raw_band, f"result_bands[{band_index}]"), {"band_ref", "margin_min", "margin_max", "outcome", "degree"}, f"result_bands[{band_index}]")
        overrides = _mapping(definition.get("natural_roll_overrides"), "natural_roll_overrides")
        if set(overrides.values()) - bands:
            _fail("resolution_rule.catalog_reference_mismatch", f"products.resolution_rule_definitions[{index}].natural_roll_overrides", "natural override 引用了不存在的结果带。")
        binding = _mapping(definition.get("post_resolution_narrative_binding"), "post_resolution_narrative_binding")
        _fields(binding, {"schema", "binding_ref", "input_policy", "required_receipt_fields", "narrative_may_not_reinterpret_outcome", "band_bindings", "binding_sha256"}, "post_resolution_narrative_binding")
        expected_binding_digest = _digest({key: item for key, item in binding.items() if key != "binding_sha256"})
        if binding.get("binding_sha256") != expected_binding_digest:
            _fail("resolution_rule.digest_mismatch", "post_resolution_narrative_binding.binding_sha256", "post-resolution binding 摘要与内容不一致。")
        if {item.get("band_ref") for item in binding.get("band_bindings", []) if isinstance(item, Mapping)} != bands:
            _fail("resolution_rule.catalog_reference_mismatch", "post_resolution_narrative_binding.band_bindings", "post-resolution binding 与 definition bands 不一致。")
        binding_digests.add(expected_binding_digest)
    if rule_catalog.get("definitions") != definitions:
        _fail("resolution_rule.catalog_reference_mismatch", "products.resolution_rule_catalog.definitions", "rule catalog definitions 与独立 IR 产物不一致。")
    if rule_catalog.get("modifier_source_catalog_sha256") != modifier_catalog.get("catalog_sha256") or len(binding_digests) != 1 or rule_catalog.get("post_resolution_binding_sha256") not in binding_digests:
        _fail("resolution_rule.catalog_reference_mismatch", "products.resolution_rule_catalog", "rule catalog 摘要引用无法解析到同批产物。")
    if rule_catalog.get("catalog_sha256") != _digest({key: item for key, item in rule_catalog.items() if key != "catalog_sha256"}):
        _fail("resolution_rule.digest_mismatch", "products.resolution_rule_catalog.catalog_sha256", "resolution rule catalog 摘要与内容不一致。")


__all__ = [
    "MODIFIER_SOURCE_CATALOG_IR_SCHEMA", "RESOLUTION_RULE_CANDIDATE_SCHEMA",
    "RESOLUTION_RULE_CATALOG_IR_SCHEMA", "RESOLUTION_RULE_DEFINITION_IR_SCHEMA",
    "ResolutionRuleContractError", "compile_resolution_rule_contract", "validate_resolution_rule_products",
]
