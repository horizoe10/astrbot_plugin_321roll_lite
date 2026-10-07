"""Strict producer contract for a source-bound resolution action offer.

The module deliberately compiles only declarative author material.  It does
not evaluate a check, create a receipt, select an actor, or advance an event.
Those decisions remain platform-owned.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


RESOLUTION_ACTION_OFFER_AUTHOR_SCHEMA = "se-resolution-action-offers/1.0.0"
RESOLUTION_ACTION_OFFER_CATALOG_SCHEMA = "se-resolution-action-offer-catalog-ir/1.0.0"
RESOLUTION_ACTION_OFFER_BINDING_SCHEMA = "se-resolution-action-offer-binding-ir/1.0.0"
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_DOCUMENT_FIELDS = {"schema", "offers"}
_OFFER_FIELDS = {
    "offer_ref", "event_source_path", "event_ref", "checkpoint_ref", "choice_ref", "route_ref",
    "resolution_definition_ref", "resolution_rule_ref", "actor_input_selector", "modifier_context", "receipt_policy",
    "legal_followup_intents", "result_bands", "narrative_policy", "story_pack_slice",
}
_SELECTOR_FIELDS = {"selector_kind", "actor_binding", "allowed_input_refs", "selected_input_refs", "require_actor"}
_OPTIONAL_SELECTOR_FIELDS = {'modifier_formula'}
_BASELINE_FORMULA_FIELDS = frozenset({"kind", "baseline"})
# The event conversion is the compiled luck-intervention event modifier. A
# selector may only repeat it field for field; the arithmetic itself stays in
# the authority, so nothing here restates floor((attribute - offset) / divisor).
_EVENT_MODIFIER_FIELDS = ("attribute_offset", "divisor", "minimum", "maximum",
                          "usable_tool_bonus", "maximum_tools")
_EVENT_STEP_FIELDS = frozenset({"kind", "tool_refs", *_EVENT_MODIFIER_FIELDS})
# Revalidating a compiled product without the luck authority still bounds every
# constant, so a fabricated conversion cannot claim an unregistered step.
_EVENT_STEP_BOUNDS = {"attribute_offset": (0, 20), "divisor": (1, 10), "minimum": (-20, 0),
                      "maximum": (0, 20), "usable_tool_bonus": (0, 1), "maximum_tools": (0, 1)}
_SELECTED_INPUT_FIELDS = {"ability_ref", "skill_ref", "tool_ref"}
_RECEIPT_FIELDS = {"authority", "required_receipt_fields", "recovery_policy"}
_NARRATIVE_FIELDS = {"input_policy", "narrative_may_not_reinterpret_outcome", "generation_policy"}
_GENERATION_POLICY_FIELDS = {"policy_ref", "instruction", "world_voice"}
_COMPILED_GENERATION_POLICY_FIELDS = _GENERATION_POLICY_FIELDS | {"policy_sha256"}
_SLICE_FIELDS = {"slice_ref", "event_source_path", "checkpoint_ref", "choice_ref", "route_ref", "scene_ref", "narrative_constraints"}
_INTENT_FIELDS = {"choice_ref", "route_ref", "label"}
_RESULT_BAND_FIELDS = {"band_ref", "outcome", "degree", "public_label"}
_MODIFIER_SCOPES = ("action", "scene", "target", "actor")
_MODIFIER_CONTEXT_FIELDS = {"scene_ref", "target_ref", *(f"{scope}_values" for scope in _MODIFIER_SCOPES)}
_LEGACY_MODIFIER_CONTEXT_FIELDS = {
    "scene_ref", "target_ref", "action_values", "scene_values", "target_values",
    "fact_values", "status_values", "item_values",
}
_MODIFIER_VALUE_FIELDS = {"scope", "ref", "value"}
_COMPILED_OFFER_FIELDS = {
    "schema", "offer_ref", "source_event", "resolution", "actor_input_selector",
    "modifier_context", "modifier_source_evaluations", "receipt_policy",
    "legal_followup_intents", "result_bands", "narrative_policy",
    "story_pack_slice", "offer_sha256",
}
_SOURCE_EVENT_FIELDS = {"event_source_path", "event_ref", "checkpoint_ref", "choice_ref", "route_ref", "choice_label"}
_RESOLUTION_FIELDS = {"resolution_definition_ref", "resolution_definition_sha256", "resolution_rule_ref", "resolution_rule_definition_sha256"}
_MODIFIER_EVALUATION_FIELDS = {"modifier_source_ref", "evaluation"}
_COMPILED_SLICE_FIELDS = {"slice_ref", "slice_sha256", "content"}
_SLICE_CONTENT_FIELDS = {"scene_ref", "narrative_constraints"}
_RESOLUTION_DEFINITION_FIELDS = {
    "schema", "definition_ref", "check_kind", "rule_ref", "difficulty",
    "actor_inputs", "modifier_policy", "assist_policy", "retry_policy",
    "opposed_policy", "seed_policy", "result_bands", "no_roll_policy",
    "fallback_policy", "definition_sha256",
}


class ResolutionActionOfferContractError(ValueError):
    def __init__(self, code: str, path: str, reason: str) -> None:
        super().__init__(f"{code}: {path}: {reason}")
        self.code, self.path, self.reason = code, path, reason


def _fail(code: str, path: str, reason: str) -> None:
    raise ResolutionActionOfferContractError(code, path, reason)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("action_offer.object_invalid", path, "object required")
    return value


def _sequence(value: Any, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("action_offer.array_invalid", path, "array required")
    return value


def _exact(value: Mapping[str, Any], fields: set[str], path: str, code: str = "action_offer.fields_invalid") -> None:
    if set(value) != fields:
        _fail(code, path, f"expected exactly {sorted(fields)}")


def _ref(value: Any, path: str) -> str:
    if not isinstance(value, str) or _REF.fullmatch(value) is None:
        _fail("action_offer.ref_invalid", path, "stable opaque ref required")
    return value


def _text(value: Any, path: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        _fail("action_offer.text_invalid", path, "bounded non-empty text required")
    return value.strip()


def _source_path(value: Any, path: str) -> str:
    result = _text(value, path)
    if "\\" in result or result.startswith("/") or ".." in result.split("/") or ":" in result:
        _fail("action_offer.source_path_invalid", path, "normalized package-relative POSIX path required")
    return result


def _unique_index(items: Sequence[Mapping[str, Any]], key: str, path: str) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(items):
        value = _mapping(item, f"{path}[{index}]")
        ref = _ref(value.get(key), f"{path}[{index}].{key}")
        if ref in indexed:
            _fail("action_offer.duplicate_reference", f"{path}[{index}].{key}", "reference must resolve exactly once")
        indexed[ref] = value
    return indexed


def _event_index(events: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    by_path: dict[str, Mapping[str, Any]] = {}
    by_ref: dict[str, Mapping[str, Any]] = {}
    for index, raw_event in enumerate(events):
        event = _mapping(raw_event, f"event_compositions[{index}]")
        source = _mapping(event.get("source"), f"event_compositions[{index}].source")
        identity = _mapping(event.get("identity"), f"event_compositions[{index}].identity")
        path = _source_path(source.get("source_path"), f"event_compositions[{index}].source.source_path")
        ref = _ref(identity.get("id"), f"event_compositions[{index}].identity.id")
        if path in by_path or ref in by_ref:
            _fail("action_offer.event_ambiguous", f"event_compositions[{index}]", "event path and identity must each be unique")
        by_path[path], by_ref[ref] = event, event
    return by_path, by_ref


def _choice_index(event: Mapping[str, Any], checkpoint_ref: str, path: str) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    graph = _mapping(event.get("checkpoint_graph"), f"{path}.checkpoint_graph")
    nodes = _sequence(graph.get("nodes"), f"{path}.checkpoint_graph.nodes")
    checkpoints = _unique_index([_mapping(item, f"{path}.checkpoint_graph.nodes") for item in nodes], "id", f"{path}.checkpoint_graph.nodes")
    checkpoint = checkpoints.get(checkpoint_ref)
    if checkpoint is None or checkpoint.get("kind") != "choice":
        _fail("action_offer.checkpoint_unresolved", f"{path}.checkpoint_ref", "must name one compiled choice checkpoint")
    sets = [item for item in _sequence(event.get("choice_sets"), f"{path}.choice_sets") if isinstance(item, Mapping) and item.get("checkpoint_ref") == checkpoint_ref]
    if len(sets) != 1:
        _fail("action_offer.choice_set_ambiguous", f"{path}.checkpoint_ref", "checkpoint must resolve to exactly one compiled choice set")
    choices = _unique_index([_mapping(item, f"{path}.choice_sets") for item in _sequence(sets[0].get("choices"), f"{path}.choice_sets.choices")], "choice_ref", f"{path}.choice_sets.choices")
    routes = _unique_index([_mapping(item, f"{path}.checkpoint_graph.edges") for item in _sequence(graph.get("edges"), f"{path}.checkpoint_graph.edges")], "id", f"{path}.checkpoint_graph.edges")
    return checkpoint, choices, routes


def _selector(raw: Any, definition: Mapping[str, Any], path: str, *,
              intervention_rules: Any = None, inventory: Any = None) -> dict[str, Any]:
    value = _mapping(raw, path); _exact(value, _SELECTOR_FIELDS | (set(value) & _OPTIONAL_SELECTOR_FIELDS), path)
    kind = _text(value["selector_kind"], f"{path}.selector_kind", 32)
    if kind not in {"ability", "skill", "tool", "combined"} or kind != definition.get("check_kind"):
        _fail("action_offer.actor_selector_mismatch", f"{path}.selector_kind", "selector kind must exactly match the compiled resolution definition")
    if value["actor_binding"] != "binding.actor.current" or not isinstance(value["require_actor"], bool) or value["require_actor"] is not definition.get("actor_inputs", {}).get("require_actor"):
        _fail("action_offer.actor_selector_mismatch", path, "actor selector must retain the current actor binding and definition requirement")
    source_inputs = _mapping(definition.get("actor_inputs"), f"{path}.definition.actor_inputs")
    expected = []
    for name in ("ability_refs", "skill_refs", "tool_refs"):
        expected.extend(_ref(item, f"{path}.definition.actor_inputs.{name}") for item in _sequence(source_inputs.get(name), f"{path}.definition.actor_inputs.{name}"))
    selected = [_ref(item, f"{path}.allowed_input_refs") for item in _sequence(value["allowed_input_refs"], f"{path}.allowed_input_refs")]
    if selected != sorted(expected) or len(selected) != len(set(selected)):
        _fail("action_offer.actor_selector_mismatch", f"{path}.allowed_input_refs", "selector inputs must be the sorted, complete, unique definition inputs")
    selected_tuple = _mapping(value["selected_input_refs"], f"{path}.selected_input_refs"); _exact(selected_tuple, _SELECTED_INPUT_FIELDS, f"{path}.selected_input_refs")
    selected_by_kind: dict[str, str | None] = {}
    for kind_name, source_key in (("ability", "ability_refs"), ("skill", "skill_refs"), ("tool", "tool_refs")):
        candidate = selected_tuple[f"{kind_name}_ref"]
        if candidate is not None:
            candidate = _ref(candidate, f"{path}.selected_input_refs.{kind_name}_ref")
            if candidate not in source_inputs[source_key]:
                _fail("action_offer.actor_selection_invalid", f"{path}.selected_input_refs.{kind_name}_ref", "selected input must belong to the compiled definition allowlist")
        selected_by_kind[kind_name] = candidate
    present = {name for name, item in selected_by_kind.items() if item is not None}
    expected_present = {kind} if kind in {"ability", "skill", "tool"} else {name for name in ("ability", "skill", "tool") if selected_by_kind[name] is not None}
    if present != expected_present or (kind == "combined" and len(present) < 2):
        _fail("action_offer.actor_selection_invalid", f"{path}.selected_input_refs", "selected inputs must explicitly and exactly satisfy the definition check kind")
    result = {"selector_kind": kind, "actor_binding": "binding.actor.current", "allowed_input_refs": selected, "selected_input_refs": {f"{name}_ref": selected_by_kind[name] for name in ("ability", "skill", "tool")}, "require_actor": value["require_actor"]}
    if 'modifier_formula' in value:
        result['modifier_formula'] = _ability_modifier_formula(
            value['modifier_formula'], kind, path+'.modifier_formula',
            intervention_rules=intervention_rules, inventory=inventory)
    return result


def _ability_modifier_formula(raw: Any, kind: str, path: str, *,
                              intervention_rules: Any = None, inventory: Any = None) -> dict[str, Any]:
    """Freeze one ability conversion: a literal baseline or the event step."""
    value = _mapping(raw, path)
    if kind != 'ability':
        _fail('action_offer.modifier_formula_invalid', path, 'ability conversion needs an ability selector')
    formula = value.get('kind')
    if formula == 'attribute_minus_baseline':
        _exact(value, _BASELINE_FORMULA_FIELDS, path)
        if type(value['baseline']) is not int or not 0 <= value['baseline'] <= 100:
            _fail('action_offer.modifier_formula_invalid', path, 'ability conversion must explicitly declare an integer baseline')
        return dict(value)
    if formula != 'attribute_event_step':
        _fail('action_offer.modifier_formula_invalid', path, 'ability conversion kind is not registered')
    _exact(value, _EVENT_STEP_FIELDS, path)
    authority = intervention_rules.get('event_modifier') if isinstance(intervention_rules, Mapping) else None
    if isinstance(authority, Mapping):
        for name in _EVENT_MODIFIER_FIELDS[:4]:
            if type(value[name]) is not int or value[name] != authority.get(name):
                _fail('action_offer.event_step_drift', f'{path}.{name}',
                      'event conversion constants must equal the compiled definition')
    else:
        # A compiled product is digest sealed; without the authority the constants
        # are still bounded, and the compiler proves them field for field.
        for name, bounds in _EVENT_STEP_BOUNDS.items():
            if type(value[name]) is not int or not bounds[0] <= value[name] <= bounds[1]:
                _fail('action_offer.event_step_drift', f'{path}.{name}',
                      'event conversion constants must stay inside the registered bounds')
        if value['minimum'] > value['maximum']:
            _fail('action_offer.event_step_drift', f'{path}.maximum',
                  'event conversion range must stay ordered')
    tool_refs = [_ref(item, f'{path}.tool_refs') for item in _sequence(value['tool_refs'], f'{path}.tool_refs')]
    if len(tool_refs) > 8 or len(tool_refs) != len(set(tool_refs)):
        _fail('action_offer.event_step_tools_invalid', f'{path}.tool_refs', 'declared tool sources must stay unique and bounded')
    if not tool_refs:
        # No authored tool source means provably no tool clause at all.
        expected_bonus = expected_tools = 0
    else:
        if authority is None and (type(value['usable_tool_bonus']) is not int
                                  or value['usable_tool_bonus'] not in (0, 1)
                                  or type(value['maximum_tools']) is not int or value['maximum_tools'] != 1):
            # Revalidation without the authority cannot resolve the constants, so
            # the clause must at least stay the compiled at-most-one-tool clause.
            _fail('action_offer.event_step_tools_invalid', path,
                  'a declared tool clause needs the compiled at-most-one tool bonus')
        definitions = inventory.get('definitions') if isinstance(inventory, Mapping) else None
        if isinstance(definitions, Sequence) and not isinstance(definitions, (str, bytes, bytearray)):
            known = {item.get('item_ref') for item in definitions if isinstance(item, Mapping)}
            for ref in tool_refs:
                if ref not in known:
                    _fail('action_offer.event_step_tool_unresolved', f'{path}.tool_refs',
                          'declared tool sources must resolve to a compiled item definition')
        elif authority is not None:
            _fail('action_offer.event_step_inventory_missing', f'{path}.tool_refs',
                  'declared tool sources must resolve inside the compiled item catalog')
        expected_bonus = authority.get('usable_tool_bonus') if isinstance(authority, Mapping) \
            else value['usable_tool_bonus']
        expected_tools = authority.get('maximum_tools') if isinstance(authority, Mapping) \
            else value['maximum_tools']
    if type(value['usable_tool_bonus']) is not int or value['usable_tool_bonus'] != expected_bonus \
            or type(value['maximum_tools']) is not int or value['maximum_tools'] != expected_tools:
        _fail('action_offer.event_step_tools_invalid', path,
              'tool bonus must match the declared tool sources and the compiled cap')
    return {'kind': formula, **{name: value[name] for name in _EVENT_MODIFIER_FIELDS},
            'tool_refs': sorted(tool_refs)}


def _receipt_and_narrative(raw_receipt: Any, raw_narrative: Any, rule: Mapping[str, Any], path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = _mapping(raw_receipt, f"{path}.receipt_policy"); _exact(receipt, _RECEIPT_FIELDS, f"{path}.receipt_policy")
    binding = _mapping(rule.get("post_resolution_narrative_binding"), f"{path}.rule_binding")
    expected_fields = list(_sequence(binding.get("required_receipt_fields"), f"{path}.rule_binding.required_receipt_fields"))
    fields = [_ref(item, f"{path}.receipt_policy.required_receipt_fields") for item in _sequence(receipt["required_receipt_fields"], f"{path}.receipt_policy.required_receipt_fields")]
    if receipt["authority"] != "platform_committed_resolution_receipt" or receipt["recovery_policy"] != "same_committed_receipt_no_reroll" or fields != expected_fields or len(fields) != len(set(fields)):
        _fail("action_offer.receipt_policy_mismatch", f"{path}.receipt_policy", "receipt policy must exactly preserve the compiled committed-receipt narrative binding")
    narrative = _mapping(raw_narrative, f"{path}.narrative_policy"); _exact(narrative, _NARRATIVE_FIELDS, f"{path}.narrative_policy")
    generation = _mapping(narrative["generation_policy"], f"{path}.narrative_policy.generation_policy"); _exact(generation, _GENERATION_POLICY_FIELDS, f"{path}.narrative_policy.generation_policy")
    if generation["policy_ref"] != binding.get("binding_ref") or narrative["input_policy"] != binding.get("input_policy") or narrative["narrative_may_not_reinterpret_outcome"] is not binding.get("narrative_may_not_reinterpret_outcome"):
        _fail("action_offer.narrative_policy_mismatch", f"{path}.narrative_policy", "narrative policy must exactly preserve the compiled rule binding")
    policy = {"policy_ref": _ref(generation["policy_ref"], f"{path}.narrative_policy.generation_policy.policy_ref"), "instruction": _text(generation["instruction"], f"{path}.narrative_policy.generation_policy.instruction", 1000), "world_voice": _text(generation["world_voice"], f"{path}.narrative_policy.generation_policy.world_voice", 240)}
    policy["policy_sha256"] = _digest(policy)
    policy = {"input_policy": narrative["input_policy"], "narrative_may_not_reinterpret_outcome": narrative["narrative_may_not_reinterpret_outcome"], "generation_policy": policy}
    return ({"authority": receipt["authority"], "required_receipt_fields": fields, "recovery_policy": receipt["recovery_policy"]}, policy)


def _result_bands(raw: Any, rule: Mapping[str, Any], path: str) -> list[dict[str, Any]]:
    """Require author-provided public labels for every Rule IR band.

    Legacy resolution-check labels can have a different degree vocabulary, so
    this contract never guesses a band-to-label projection.
    """
    expected = [_mapping(item, f"{path}.rule.result_bands") for item in _sequence(rule.get("result_bands"), f"{path}.rule.result_bands")]
    labels = _sequence(raw, f"{path}.result_bands")
    if len(labels) != len(expected):
        _fail("action_offer.result_band_count_invalid", f"{path}.result_bands", "one explicit public label is required for every compiled Rule IR band")
    expected_by_ref = {_ref(item.get("band_ref"), f"{path}.rule.result_bands.band_ref"): item for item in expected}
    compiled: list[dict[str, str]] = []; seen: set[str] = set()
    for index, raw_band in enumerate(labels):
        band_path = f"{path}.result_bands[{index}]"; band = _mapping(raw_band, band_path); _exact(band, _RESULT_BAND_FIELDS | ({'consequences'} if 'consequences' in band else set()), band_path)
        ref = _ref(band["band_ref"], f"{band_path}.band_ref"); target = expected_by_ref.get(ref)
        if ref in seen or target is None or band["outcome"] != target.get("outcome") or band["degree"] != target.get("degree"):
            _fail("action_offer.result_band_drift", band_path, "band ref, outcome, and degree must exactly match one unique compiled Rule IR band")
        compiled.append({"band_ref": ref, "outcome": _text(band["outcome"], f"{band_path}.outcome", 32), "degree": _text(band["degree"], f"{band_path}.degree", 32), "public_label": _text(band["public_label"], f"{band_path}.public_label", 240)})
        if 'consequences' in band:
            compiled[-1]['consequences'] = _consequences(band['consequences'],band_path+'.consequences')
        seen.add(ref)
    if seen != set(expected_by_ref):
        _fail("action_offer.result_band_drift", f"{path}.result_bands", "all and only compiled Rule IR bands must be explicitly labeled")
    return sorted(compiled, key=lambda item: item["band_ref"])


def _consequences(raw: Any, path: str) -> list[dict[str, Any]]:
    values=_sequence(raw,path)
    if not 1<=len(values)<=16:
        _fail('action_offer.consequences_invalid',path,'consequences must contain 1..16 effects')
    result=[];seen=set()
    for index,raw_value in enumerate(values):
        field=path+f'[{index}]';value=_mapping(raw_value,field)
        if value.get('kind')=='actor.rope.entangle':
            _exact(value,{'schema','kind','public_label'},field)
            if value['schema']!='se-resolution-action-obligation/1.0.0':
                _fail('action_offer.consequences_invalid',field,'unsupported action obligation version')
            key='obligation.rope_entanglement'
        elif value.get('kind') in {'actor.hp.damage','inventory.consume','inventory.damage','inventory.break'}:
            kind=value['kind'];fields={'schema','kind','public_label'}
            if kind!='actor.hp.damage':fields.add('item_ref')
            if kind!='inventory.break':fields.add('amount')
            _exact(value,fields,field)
            if value['schema']!='se-resolution-personal-cost/1.0.0':
                _fail('action_offer.consequences_invalid',field,'unsupported personal cost version')
            if kind!='inventory.break' and (type(value['amount']) is not int or not 1<=value['amount']<=(99 if kind=='inventory.consume' else 10)):
                _fail('action_offer.consequences_invalid',field,'personal cost amount invalid')
            key='vitality.hp' if kind=='actor.hp.damage' else _ref(value['item_ref'],field+'.item_ref')
        elif value.get('kind') in {'fact.set','actor.scene.fact.set'}:
            scoped=value['kind']=='actor.scene.fact.set'
            _exact(value,{'kind','fact_ref','value','public_label'}|({'schema'} if scoped else set()),field)
            if scoped and value['schema']!='se-resolution-actor-scene-effect/1.0.0':
                _fail('action_offer.consequences_invalid',field,'unsupported actor scene effect version')
            key=_ref(value['fact_ref'],field+'.fact_ref')
            scalar=value['value']
            if type(scalar) not in {bool,int,str} or isinstance(scalar,str) and (not scalar or len(scalar)>240):
                _fail('action_offer.consequences_invalid',field,'fact value must be a bounded scalar')
        elif value.get('kind') in {'clock.advance','actor.scene.clock.advance'}:
            scoped=value['kind']=='actor.scene.clock.advance'
            _exact(value,{'kind','clock_ref','initial_value','amount','public_label'}|({'schema'} if scoped else set()),field)
            if scoped and value['schema']!='se-resolution-actor-scene-effect/1.0.0':
                _fail('action_offer.consequences_invalid',field,'unsupported actor scene effect version')
            key=_ref(value['clock_ref'],field+'.clock_ref')
            if type(value['amount']) is not int or not 1<=value['amount']<=10 or type(value['initial_value']) is not int or value['initial_value']<0:
                _fail('action_offer.consequences_invalid',field,'clock advance and initial value must be bounded integers')
        else:
            _fail('action_offer.consequences_invalid',field,'unregistered consequence kind')
        if key in seen:
            _fail('action_offer.consequences_invalid',field,'duplicate consequence target')
        seen.add(key)
        _text(value['public_label'],field+'.public_label',240)
        result.append(dict(value))
    return result


def validate_personal_cost_sources(catalog, inventory, resources):
    """Reject author costs without a real physical/resource consumer source."""
    items={item['item_ref']:item for item in (inventory or {}).get('definitions',[])}
    pools={item['resource_id']:item for item in (resources or {}).get('definitions',[])}
    for offer in catalog['offers']:
        for band in offer['result_bands']:
            effects=band.get('consequences',[])
            if any(e['kind']=='actor.rope.entangle' for e in effects) and not any(e['kind']=='inventory.consume' and e['item_ref']=='item:rope' and e['amount']==1 for e in effects):
                _fail('action_offer.personal_cost_source_invalid',offer['offer_ref'],'rope entanglement must accompany consumption of one owned spare rope')
            for effect in effects:
                kind=effect['kind']
                if kind=='actor.hp.damage':
                    pool=pools.get('vitality.hp')
                    if pool is None or pool.get('numeric_type')!='integer':
                        _fail('action_offer.personal_cost_source_invalid',offer['offer_ref'],'HP cost requires the actual vitality resource')
                elif kind in {'inventory.consume','inventory.damage','inventory.break'}:
                    item=items.get(effect['item_ref'])
                    if item is None or item['visibility']!='public':
                        _fail('action_offer.personal_cost_source_invalid',offer['offer_ref'],'personal item cost requires a public registered physical item')
                    if kind in {'inventory.damage','inventory.break'}:
                        maximum=item['instance_template']['durability_max']
                        if type(maximum) is not int or maximum<1 or kind=='inventory.damage' and effect['amount']>maximum:
                            _fail('action_offer.personal_cost_source_invalid',offer['offer_ref'],'item damage requires sufficient tracked durability')


def _modifier_context(raw: Any, rule: Mapping[str, Any], products: Mapping[str, Any], path: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    value = _mapping(raw, f"{path}.modifier_context")
    context_fields = set(value)
    if context_fields not in (_MODIFIER_CONTEXT_FIELDS, _LEGACY_MODIFIER_CONTEXT_FIELDS):
        _fail("action_offer.fields_invalid", f"{path}.modifier_context", f"expected exactly {sorted(_MODIFIER_CONTEXT_FIELDS)}")
    if context_fields == _LEGACY_MODIFIER_CONTEXT_FIELDS:
        for legacy_key in ("fact_values", "status_values", "item_values"):
            if _sequence(value[legacy_key], f"{path}.modifier_context.{legacy_key}"):
                _fail("action_offer.modifier_scope_invalid", f"{path}.modifier_context.{legacy_key}", "compiled Rule IR permits only action, scene, target, and actor scopes")
    scene_ref = _ref(value["scene_ref"], f"{path}.modifier_context.scene_ref"); target_ref = _ref(value["target_ref"], f"{path}.modifier_context.target_ref")
    source_catalog = _mapping(products.get("modifier_source_catalog"), f"{path}.modifier_source_catalog")
    sources = _unique_index([_mapping(item, f"{path}.modifier_source_catalog.sources") for item in _sequence(source_catalog.get("sources"), f"{path}.modifier_source_catalog.sources")], "modifier_source_ref", f"{path}.modifier_source_catalog.sources")
    selected_sources = [_ref(item, f"{path}.rule.modifier_source_refs") for item in _sequence(rule.get("modifier_source_refs"), f"{path}.rule.modifier_source_refs")]
    expected_pairs: set[tuple[str, str]] = set()
    conditions_by_source: dict[str, list[Mapping[str, Any]]] = {}
    for source_ref in selected_sources:
        source = sources.get(source_ref)
        if source is None: _fail("action_offer.modifier_source_unresolved", f"{path}.resolution_rule_ref", "selected rule references an unresolved modifier source")
        conditions = [_mapping(item, f"{path}.modifier_source.conditions") for item in _sequence(source.get("conditions"), f"{path}.modifier_source.conditions")]
        conditions_by_source[source_ref] = conditions
        expected_pairs.update((_text(item.get("scope"), f"{path}.modifier_source.conditions.scope", 32), _ref(item.get("ref"), f"{path}.modifier_source.conditions.ref")) for item in conditions)
    actual: dict[tuple[str, str], Any] = {}
    compiled: dict[str, list[dict[str, Any]]] = {}
    expected_categories = {f"{scope}_values": scope for scope in _MODIFIER_SCOPES}
    for key, scope in expected_categories.items():
        items = _sequence(value.get(key, ()), f"{path}.modifier_context.{key}"); output: list[dict[str, Any]] = []
        for index, raw_item in enumerate(items):
            item_path = f"{path}.modifier_context.{key}[{index}]"; item = _mapping(raw_item, item_path); _exact(item, _MODIFIER_VALUE_FIELDS, item_path)
            if item["scope"] != scope or isinstance(item["value"], (Mapping, Sequence)) and not isinstance(item["value"], (str, bytes, bytearray)):
                _fail("action_offer.modifier_context_invalid", item_path, "context entry needs its fixed category scope and a JSON scalar value")
            ref = _ref(item["ref"], f"{item_path}.ref"); pair = (scope, ref)
            if pair in actual: _fail("action_offer.modifier_context_duplicate", item_path, "scope/ref context value must be unique")
            try: json.dumps(item["value"], allow_nan=False)
            except (TypeError, ValueError): _fail("action_offer.modifier_context_invalid", f"{item_path}.value", "context value must be a finite JSON scalar")
            actual[pair] = item["value"]; output.append({"scope": scope, "ref": ref, "value": item["value"]})
        compiled[key] = sorted(output, key=lambda item: item["ref"])
    if set(actual) != expected_pairs:
        _fail("action_offer.modifier_context_drift", f"{path}.modifier_context", "context must contain all and only the selected rule modifier condition scope/ref allowlist")
    states: list[dict[str, str]] = []
    for source_ref in sorted(selected_sources):
        matched = all(actual[(_text(condition["scope"], f"{path}.condition.scope", 32), _ref(condition["ref"], f"{path}.condition.ref"))] == condition["value"] for condition in conditions_by_source[source_ref])
        states.append({"modifier_source_ref": source_ref, "evaluation": "applicable" if matched else "suppressed"})
    return ({"scene_ref": scene_ref, "target_ref": target_ref, **compiled}, states)


def compile_resolution_action_offers(document: Mapping[str, Any], events: Sequence[Mapping[str, Any]], resolution_catalog: Mapping[str, Any], resolution_rule_products: Mapping[str, Any], *,
                                     intervention_rules: Any = None, inventory: Any = None) -> dict[str, Any]:
    """Compile a catalog, refusing unknown, duplicate, drifting, or implicit bindings."""
    doc = _mapping(document, "$" ); _exact(doc, _DOCUMENT_FIELDS, "$")
    if doc.get("schema") != RESOLUTION_ACTION_OFFER_AUTHOR_SCHEMA:
        _fail("action_offer.schema_invalid", "schema", "unsupported action-offer author schema")
    definitions = _unique_index([_mapping(item, "resolution_check.definitions") for item in _sequence(resolution_catalog.get("definitions"), "resolution_check.definitions")], "definition_ref", "resolution_check.definitions")
    rules = _unique_index([_mapping(item, "resolution_rule.definitions") for item in _sequence(resolution_rule_products.get("resolution_rule_definitions"), "resolution_rule.definitions")], "resolution_rule_ref", "resolution_rule.definitions")
    by_path, by_ref = _event_index(events)
    compiled: list[dict[str, Any]] = []
    offer_refs: set[str] = set(); slice_refs: set[str] = set(); used_event_choices: set[tuple[str, str]] = set()
    offers = _sequence(doc.get("offers"), "offers")
    if not offers:
        _fail("action_offer.offers_empty", "offers", "at least one explicit action offer is required")
    for index, raw in enumerate(offers):
        path = f"offers[{index}]"; value = _mapping(raw, path); _exact(value, _OFFER_FIELDS, path)
        offer_ref = _ref(value["offer_ref"], f"{path}.offer_ref")
        if offer_ref in offer_refs: _fail("action_offer.offer_duplicate", f"{path}.offer_ref", "offer_ref must be unique")
        source_path = _source_path(value["event_source_path"], f"{path}.event_source_path"); event_ref = _ref(value["event_ref"], f"{path}.event_ref")
        event = by_path.get(source_path)
        if event is None or by_ref.get(event_ref) is not event:
            _fail("action_offer.event_unresolved", path, "event source path and event identity must resolve to the same unique EventComposition")
        checkpoint_ref = _ref(value["checkpoint_ref"], f"{path}.checkpoint_ref"); choice_ref = _ref(value["choice_ref"], f"{path}.choice_ref"); route_ref = _ref(value["route_ref"], f"{path}.route_ref")
        _, choices, routes = _choice_index(event, checkpoint_ref, path)
        choice = choices.get(choice_ref); route = routes.get(route_ref)
        if choice is None or route is None or choice.get("route_ref") != route_ref or route.get("from") != checkpoint_ref:
            _fail("action_offer.choice_route_mismatch", path, "action must name one exact choice and outgoing route from the source checkpoint")
        key = (event_ref, choice_ref)
        if key in used_event_choices: _fail("action_offer.choice_duplicate", f"{path}.choice_ref", "one source EventComposition choice may bind only one action offer")
        definition_ref = _ref(value["resolution_definition_ref"], f"{path}.resolution_definition_ref"); rule_ref = _ref(value["resolution_rule_ref"], f"{path}.resolution_rule_ref")
        definition, rule = definitions.get(definition_ref), rules.get(rule_ref)
        if definition is None: _fail("action_offer.resolution_definition_unresolved", f"{path}.resolution_definition_ref", "definition must exist exactly once in the compiled resolution catalog")
        if rule is None: _fail("action_offer.resolution_rule_unresolved", f"{path}.resolution_rule_ref", "rule must exist exactly once in the compiled resolution-rule catalog")
        event_binding = event.get("resolution_check")
        if isinstance(event_binding, Mapping):
            event_binding = event_binding.get('choice_definitions', {}).get(choice_ref, event_binding)
        if not isinstance(event_binding, Mapping) or event_binding.get("definition_ref") != definition_ref or event_binding.get("definition_sha256") != definition.get("definition_sha256"):
            _fail("action_offer.event_resolution_drift", path, "source EventComposition must explicitly bind the same compiled resolution definition")
        selector = _selector(value["actor_input_selector"], definition, path,
                             intervention_rules=intervention_rules, inventory=inventory)
        modifier_context, modifier_source_evaluations = _modifier_context(value["modifier_context"], rule, resolution_rule_products, path)
        receipt, narrative = _receipt_and_narrative(value["receipt_policy"], value["narrative_policy"], rule, path)
        result_bands = _result_bands(value["result_bands"], rule, path)
        followups = _sequence(value["legal_followup_intents"], f"{path}.legal_followup_intents")
        if len(followups) != 2: _fail("action_offer.followup_count_invalid", f"{path}.legal_followup_intents", "exactly two legal follow-up intents required")
        # The original route may continue after its committed result; it is not a retry.
        intents: list[dict[str, str]] = []; seen_choices: set[str] = set()
        for intent_index, raw_intent in enumerate(followups):
            intent_path = f"{path}.legal_followup_intents[{intent_index}]"; intent = _mapping(raw_intent, intent_path); _exact(intent, _INTENT_FIELDS, intent_path)
            intent_choice = _ref(intent["choice_ref"], f"{intent_path}.choice_ref"); intent_route = _ref(intent["route_ref"], f"{intent_path}.route_ref"); source_choice = choices.get(intent_choice); source_route = routes.get(intent_route)
            if intent_choice in seen_choices or source_choice is None or source_route is None or source_choice.get("route_ref") != intent_route or source_route.get("from") != checkpoint_ref or intent["label"] != source_choice.get("label"):
                _fail("action_offer.followup_invalid", intent_path, "follow-up must be a distinct exact legal choice/route/label from the same source checkpoint")
            seen_choices.add(intent_choice); intents.append({"choice_ref": intent_choice, "route_ref": intent_route, "label": _text(intent["label"], f"{intent_path}.label", 80)})
        slice_value = _mapping(value["story_pack_slice"], f"{path}.story_pack_slice"); _exact(slice_value, _SLICE_FIELDS, f"{path}.story_pack_slice")
        slice_ref = _ref(slice_value["slice_ref"], f"{path}.story_pack_slice.slice_ref")
        if slice_ref in slice_refs or any(slice_value[name] != expected for name, expected in (("event_source_path", source_path), ("checkpoint_ref", checkpoint_ref), ("choice_ref", choice_ref), ("route_ref", route_ref))):
            _fail("action_offer.story_slice_drift", f"{path}.story_pack_slice", "slice must be unique and exactly repeat the source event/checkpoint/choice/route binding")
        constraints = [_text(item, f"{path}.story_pack_slice.narrative_constraints", 240) for item in _sequence(slice_value["narrative_constraints"], f"{path}.story_pack_slice.narrative_constraints")]
        if not constraints or len(constraints) != len(set(constraints)) or len(constraints) > 16:
            _fail("action_offer.story_slice_constraints_invalid", f"{path}.story_pack_slice.narrative_constraints", "slice requires 1-16 unique explicit narrative constraints")
        slice_output = {"slice_ref": slice_ref, "content": {"scene_ref": _ref(slice_value["scene_ref"], f"{path}.story_pack_slice.scene_ref"), "narrative_constraints": constraints}}
        slice_output["slice_sha256"] = _digest(slice_output)
        item = {
            "schema": "se-resolution-action-offer-ir/1.0.0", "offer_ref": offer_ref,
            "source_event": {"event_source_path": source_path, "event_ref": event_ref, "checkpoint_ref": checkpoint_ref, "choice_ref": choice_ref, "route_ref": route_ref, "choice_label": choice["label"]},
            "resolution": {"resolution_definition_ref": definition_ref, "resolution_definition_sha256": definition["definition_sha256"], "resolution_rule_ref": rule_ref, "resolution_rule_definition_sha256": rule["definition_sha256"]},
            "actor_input_selector": selector, "modifier_context": modifier_context, "modifier_source_evaluations": modifier_source_evaluations, "receipt_policy": receipt, "legal_followup_intents": intents, "result_bands": result_bands, "narrative_policy": narrative,
            "story_pack_slice": slice_output,
        }
        item["offer_sha256"] = _digest(item); compiled.append(item)
        offer_refs.add(offer_ref); slice_refs.add(slice_ref); used_event_choices.add(key)
    compiled.sort(key=lambda item: item["offer_ref"])
    catalog = {"schema": RESOLUTION_ACTION_OFFER_CATALOG_SCHEMA, "resolution_definition_catalog_sha256": resolution_catalog.get("catalog_sha256"), "resolution_rule_catalog_sha256": resolution_rule_products.get("resolution_rule_catalog", {}).get("catalog_sha256"), "offers": compiled}
    if _DIGEST.fullmatch(str(catalog["resolution_definition_catalog_sha256"])) is None or _DIGEST.fullmatch(str(catalog["resolution_rule_catalog_sha256"])) is None:
        _fail("action_offer.catalog_identity_invalid", "catalog", "compiled catalog identities must be SHA-256 digests")
    catalog["catalog_sha256"] = _digest(catalog)
    validate_resolution_action_offer_catalog(catalog, resolution_catalog, resolution_rule_products,
                                             intervention_rules=intervention_rules, inventory=inventory)
    return catalog


def _compiled_modifier_context(raw: Any, path: str) -> None:
    context = _mapping(raw, path); _exact(context, _MODIFIER_CONTEXT_FIELDS, path)
    _ref(context["scene_ref"], f"{path}.scene_ref"); _ref(context["target_ref"], f"{path}.target_ref")
    seen: set[tuple[str, str]] = set()
    for scope in _MODIFIER_SCOPES:
        key = f"{scope}_values"; entries = _sequence(context[key], f"{path}.{key}"); refs: list[str] = []
        for index, raw_entry in enumerate(entries):
            entry_path = f"{path}.{key}[{index}]"; entry = _mapping(raw_entry, entry_path); _exact(entry, _MODIFIER_VALUE_FIELDS, entry_path)
            if entry["scope"] != scope or isinstance(entry["value"], (Mapping, Sequence)) and not isinstance(entry["value"], (str, bytes, bytearray)):
                _fail("action_offer.modifier_context_invalid", entry_path, "compiled context value must use its fixed Rule IR scope and contain a JSON scalar")
            ref = _ref(entry["ref"], f"{entry_path}.ref")
            try: json.dumps(entry["value"], allow_nan=False)
            except (TypeError, ValueError): _fail("action_offer.modifier_context_invalid", f"{entry_path}.value", "context value must be a finite JSON scalar")
            if (scope, ref) in seen: _fail("action_offer.modifier_context_duplicate", entry_path, "scope/ref context value must be unique")
            seen.add((scope, ref)); refs.append(ref)
        if refs != sorted(refs): _fail("action_offer.product_order_invalid", f"{path}.{key}", "compiled context refs must be sorted")


def _validate_compiled_offer(offer: Mapping[str, Any], path: str, *,
                             intervention_rules: Any = None, inventory: Any = None) -> None:
    _exact(offer, _COMPILED_OFFER_FIELDS, path)
    if offer.get("schema") != "se-resolution-action-offer-ir/1.0.0": _fail("action_offer.product_schema_invalid", f"{path}.schema", "compiled offer schema identity is invalid")
    if offer.get("offer_sha256") != _digest({key: entry for key, entry in offer.items() if key != "offer_sha256"}): _fail("action_offer.offer_digest_invalid", path, "offer self digest is invalid")
    _ref(offer["offer_ref"], f"{path}.offer_ref")
    source = _mapping(offer["source_event"], f"{path}.source_event"); _exact(source, _SOURCE_EVENT_FIELDS, f"{path}.source_event")
    _source_path(source["event_source_path"], f"{path}.source_event.event_source_path")
    for key in ("event_ref", "checkpoint_ref", "choice_ref", "route_ref"): _ref(source[key], f"{path}.source_event.{key}")
    _text(source["choice_label"], f"{path}.source_event.choice_label", 80)
    resolution = _mapping(offer["resolution"], f"{path}.resolution"); _exact(resolution, _RESOLUTION_FIELDS, f"{path}.resolution")
    for key in ("resolution_definition_ref", "resolution_rule_ref"): _ref(resolution[key], f"{path}.resolution.{key}")
    for key in ("resolution_definition_sha256", "resolution_rule_definition_sha256"):
        if _DIGEST.fullmatch(str(resolution[key])) is None: _fail("action_offer.catalog_identity_invalid", f"{path}.resolution.{key}", "compiled definition digest is invalid")
    selector = _mapping(offer["actor_input_selector"], f"{path}.actor_input_selector"); _exact(selector, _SELECTOR_FIELDS | (set(selector) & _OPTIONAL_SELECTOR_FIELDS), f"{path}.actor_input_selector")
    kind = selector["selector_kind"]
    if kind not in {"ability", "skill", "tool", "combined"} or selector["actor_binding"] != "binding.actor.current" or not isinstance(selector["require_actor"], bool): _fail("action_offer.actor_selector_mismatch", f"{path}.actor_input_selector", "compiled actor selector identity is invalid")
    allowed = [_ref(item, f"{path}.actor_input_selector.allowed_input_refs") for item in _sequence(selector["allowed_input_refs"], f"{path}.actor_input_selector.allowed_input_refs")]
    if allowed != sorted(allowed) or len(allowed) != len(set(allowed)): _fail("action_offer.actor_selector_mismatch", f"{path}.actor_input_selector.allowed_input_refs", "compiled actor input allowlist must be sorted and unique")
    selected = _mapping(selector["selected_input_refs"], f"{path}.actor_input_selector.selected_input_refs"); _exact(selected, _SELECTED_INPUT_FIELDS, f"{path}.actor_input_selector.selected_input_refs")
    present: set[str] = set()
    for selected_kind in ("ability", "skill", "tool"):
        selected_ref = selected[f"{selected_kind}_ref"]
        if selected_ref is not None:
            selected_ref = _ref(selected_ref, f"{path}.actor_input_selector.selected_input_refs.{selected_kind}_ref")
            if selected_ref not in allowed: _fail("action_offer.actor_selection_invalid", f"{path}.actor_input_selector.selected_input_refs.{selected_kind}_ref", "selected input must belong to the compiled allowlist")
            present.add(selected_kind)
    if present != ({kind} if kind != "combined" else present) or kind == "combined" and len(present) < 2: _fail("action_offer.actor_selection_invalid", f"{path}.actor_input_selector.selected_input_refs", "selected inputs do not satisfy the compiled check kind")
    if 'modifier_formula' in selector:
        _ability_modifier_formula(selector['modifier_formula'], kind, f'{path}.actor_input_selector.modifier_formula',
                                  intervention_rules=intervention_rules, inventory=inventory)
    _compiled_modifier_context(offer["modifier_context"], f"{path}.modifier_context")
    evaluations = _sequence(offer["modifier_source_evaluations"], f"{path}.modifier_source_evaluations")
    if not evaluations: _fail("action_offer.modifier_evaluations_invalid", f"{path}.modifier_source_evaluations", "at least one modifier-source evaluation is required")
    evaluation_refs: list[str] = []
    for index, raw_evaluation in enumerate(evaluations):
        evaluation_path = f"{path}.modifier_source_evaluations[{index}]"; evaluation = _mapping(raw_evaluation, evaluation_path); _exact(evaluation, _MODIFIER_EVALUATION_FIELDS, evaluation_path)
        evaluation_refs.append(_ref(evaluation["modifier_source_ref"], f"{evaluation_path}.modifier_source_ref"))
        if evaluation["evaluation"] not in {"applicable", "suppressed"}: _fail("action_offer.modifier_evaluations_invalid", f"{evaluation_path}.evaluation", "unknown modifier evaluation")
    if evaluation_refs != sorted(set(evaluation_refs)): _fail("action_offer.product_order_invalid", f"{path}.modifier_source_evaluations", "compiled modifier evaluations must be sorted and unique")
    receipt = _mapping(offer["receipt_policy"], f"{path}.receipt_policy"); _exact(receipt, _RECEIPT_FIELDS, f"{path}.receipt_policy")
    receipt_fields = [_ref(item, f"{path}.receipt_policy.required_receipt_fields") for item in _sequence(receipt["required_receipt_fields"], f"{path}.receipt_policy.required_receipt_fields")]
    if receipt["authority"] != "platform_committed_resolution_receipt" or receipt["recovery_policy"] != "same_committed_receipt_no_reroll" or not receipt_fields or len(receipt_fields) != len(set(receipt_fields)): _fail("action_offer.receipt_policy_mismatch", f"{path}.receipt_policy", "compiled receipt policy is invalid")
    intents = _sequence(offer["legal_followup_intents"], f"{path}.legal_followup_intents")
    if len(intents) != 2: _fail("action_offer.followup_count_invalid", f"{path}.legal_followup_intents", "exactly two compiled follow-up intents are required")
    intent_choices: set[str] = set()
    for index, raw_intent in enumerate(intents):
        intent_path = f"{path}.legal_followup_intents[{index}]"; intent = _mapping(raw_intent, intent_path); _exact(intent, _INTENT_FIELDS, intent_path)
        choice_ref = _ref(intent["choice_ref"], f"{intent_path}.choice_ref"); _ref(intent["route_ref"], f"{intent_path}.route_ref"); _text(intent["label"], f"{intent_path}.label", 80)
        if choice_ref in intent_choices: _fail("action_offer.followup_invalid", intent_path, "compiled follow-up choices must be unique")
        intent_choices.add(choice_ref)
    bands = _sequence(offer["result_bands"], f"{path}.result_bands"); band_refs: list[str] = []
    if not bands: _fail("action_offer.result_band_count_invalid", f"{path}.result_bands", "compiled result bands cannot be empty")
    for index, raw_band in enumerate(bands):
        band_path = f"{path}.result_bands[{index}]"; band = _mapping(raw_band, band_path); _exact(band, _RESULT_BAND_FIELDS | ({'consequences'} if 'consequences' in band else set()), band_path)
        if 'consequences' in band:
            _consequences(band['consequences'],band_path+'.consequences')
        band_refs.append(_ref(band["band_ref"], f"{band_path}.band_ref"))
        if band["outcome"] not in {"success", "failure"}: _fail("action_offer.result_band_drift", f"{band_path}.outcome", "compiled result outcome is invalid")
        _ref(band["degree"], f"{band_path}.degree"); _text(band["public_label"], f"{band_path}.public_label", 240)
    if band_refs != sorted(set(band_refs)): _fail("action_offer.product_order_invalid", f"{path}.result_bands", "compiled result bands must be sorted and unique")
    narrative = _mapping(offer["narrative_policy"], f"{path}.narrative_policy"); _exact(narrative, _NARRATIVE_FIELDS, f"{path}.narrative_policy")
    if narrative["input_policy"] != "committed_receipt_only" or narrative["narrative_may_not_reinterpret_outcome"] is not True: _fail("action_offer.narrative_policy_mismatch", f"{path}.narrative_policy", "compiled narrative authority policy is invalid")
    generation = _mapping(narrative["generation_policy"], f"{path}.narrative_policy.generation_policy"); _exact(generation, _COMPILED_GENERATION_POLICY_FIELDS, f"{path}.narrative_policy.generation_policy")
    generation_material = {key: generation[key] for key in _GENERATION_POLICY_FIELDS}
    _ref(generation["policy_ref"], f"{path}.narrative_policy.generation_policy.policy_ref"); _text(generation["instruction"], f"{path}.narrative_policy.generation_policy.instruction", 1000); _text(generation["world_voice"], f"{path}.narrative_policy.generation_policy.world_voice", 240)
    if generation["policy_sha256"] != _digest(generation_material): _fail("action_offer.narrative_digest_invalid", f"{path}.narrative_policy.generation_policy.policy_sha256", "generation policy digest is invalid")
    story_slice = _mapping(offer["story_pack_slice"], f"{path}.story_pack_slice"); _exact(story_slice, _COMPILED_SLICE_FIELDS, f"{path}.story_pack_slice")
    content = _mapping(story_slice["content"], f"{path}.story_pack_slice.content"); _exact(content, _SLICE_CONTENT_FIELDS, f"{path}.story_pack_slice.content")
    _ref(story_slice["slice_ref"], f"{path}.story_pack_slice.slice_ref"); _ref(content["scene_ref"], f"{path}.story_pack_slice.content.scene_ref")
    constraints = [_text(item, f"{path}.story_pack_slice.content.narrative_constraints", 240) for item in _sequence(content["narrative_constraints"], f"{path}.story_pack_slice.content.narrative_constraints")]
    if not constraints or len(constraints) > 16 or len(constraints) != len(set(constraints)): _fail("action_offer.story_slice_constraints_invalid", f"{path}.story_pack_slice.content.narrative_constraints", "compiled story slice requires 1-16 unique constraints")
    if story_slice["slice_sha256"] != _digest({"slice_ref": story_slice["slice_ref"], "content": content}): _fail("action_offer.story_slice_digest_invalid", f"{path}.story_pack_slice.slice_sha256", "story slice digest is invalid")


def _resolution_definition_index(catalog: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    value = _mapping(catalog, "resolution_catalog"); _exact(value, {"schema", "definitions", "catalog_sha256"}, "resolution_catalog")
    if value["schema"] != "se-resolution-check-catalog-ir/1.0.0" or value["catalog_sha256"] != _digest({key: item for key, item in value.items() if key != "catalog_sha256"}): _fail("action_offer.catalog_identity_invalid", "resolution_catalog", "resolution definition catalog identity or digest is invalid")
    definitions = [_mapping(item, "resolution_catalog.definitions") for item in _sequence(value["definitions"], "resolution_catalog.definitions")]
    indexed = _unique_index(definitions, "definition_ref", "resolution_catalog.definitions")
    for index, definition in enumerate(definitions):
        path = f"resolution_catalog.definitions[{index}]"; _exact(definition, _RESOLUTION_DEFINITION_FIELDS, path)
        if definition.get("schema") != "se-resolution-check-definition-ir/1.0.0" or definition.get("definition_sha256") != _digest({key: item for key, item in definition.items() if key != "definition_sha256"}): _fail("action_offer.catalog_identity_invalid", path, "resolution definition schema or digest is invalid")
    return indexed


def validate_resolution_action_offer_catalog(catalog: Mapping[str, Any], resolution_catalog: Mapping[str, Any] | None = None,
                                             resolution_rule_products: Mapping[str, Any] | None = None, *,
                                             intervention_rules: Any = None, inventory: Any = None) -> None:
    """Revalidate a complete product; supplied dependency catalogs are checked transitively."""
    value = _mapping(catalog, "catalog"); _exact(value, {"schema", "resolution_definition_catalog_sha256", "resolution_rule_catalog_sha256", "offers", "catalog_sha256"}, "catalog")
    if value.get("schema") != RESOLUTION_ACTION_OFFER_CATALOG_SCHEMA or value.get("catalog_sha256") != _digest({key: item for key, item in value.items() if key != "catalog_sha256"}): _fail("action_offer.catalog_digest_invalid", "catalog", "catalog schema or self digest is invalid")
    for key in ("resolution_definition_catalog_sha256", "resolution_rule_catalog_sha256"):
        if _DIGEST.fullmatch(str(value[key])) is None: _fail("action_offer.catalog_identity_invalid", f"catalog.{key}", "cross-catalog identity must be a SHA-256 digest")
    offers = _sequence(value["offers"], "catalog.offers")
    if not offers: _fail("action_offer.offers_empty", "catalog.offers", "compiled catalog cannot be empty")
    seen: set[str] = set(); ordered_refs: list[str] = []
    for index, item in enumerate(offers):
        offer = _mapping(item, f"catalog.offers[{index}]"); _validate_compiled_offer(
            offer, f"catalog.offers[{index}]", intervention_rules=intervention_rules, inventory=inventory)
        ref = _ref(offer["offer_ref"], f"catalog.offers[{index}].offer_ref")
        if ref in seen: _fail("action_offer.offer_duplicate", f"catalog.offers[{index}].offer_ref", "compiled offer refs must be unique")
        seen.add(ref); ordered_refs.append(ref)
    if ordered_refs != sorted(ordered_refs): _fail("action_offer.product_order_invalid", "catalog.offers", "compiled offers must be sorted by offer_ref")
    if (resolution_catalog is None) != (resolution_rule_products is None): _fail("action_offer.catalog_identity_invalid", "catalog", "both dependency catalogs are required for cross-catalog validation")
    if resolution_catalog is None or resolution_rule_products is None: return
    definitions = _resolution_definition_index(resolution_catalog)
    try:
        from .resolution_rule import validate_resolution_rule_products
        validate_resolution_rule_products(resolution_rule_products)
    except Exception as exc:
        _fail("action_offer.catalog_identity_invalid", "resolution_rule_products", f"resolution-rule products are invalid: {exc}")
    rule_catalog = _mapping(resolution_rule_products.get("resolution_rule_catalog"), "resolution_rule_products.resolution_rule_catalog")
    if value["resolution_definition_catalog_sha256"] != resolution_catalog.get("catalog_sha256") or value["resolution_rule_catalog_sha256"] != rule_catalog.get("catalog_sha256"): _fail("action_offer.catalog_identity_invalid", "catalog", "cross-catalog digests do not identify the supplied compiled products")
    rules = _unique_index([_mapping(item, "resolution_rule_products.resolution_rule_definitions") for item in _sequence(resolution_rule_products.get("resolution_rule_definitions"), "resolution_rule_products.resolution_rule_definitions")], "resolution_rule_ref", "resolution_rule_products.resolution_rule_definitions")
    for index, raw_offer in enumerate(offers):
        offer = _mapping(raw_offer, f"catalog.offers[{index}]"); path = f"catalog.offers[{index}]"; resolution = _mapping(offer["resolution"], f"{path}.resolution")
        definition = definitions.get(resolution["resolution_definition_ref"]); rule = rules.get(resolution["resolution_rule_ref"])
        if definition is None or resolution["resolution_definition_sha256"] != definition.get("definition_sha256"): _fail("action_offer.resolution_definition_unresolved", f"{path}.resolution", "compiled offer definition does not resolve to the supplied catalog")
        if rule is None or resolution["resolution_rule_definition_sha256"] != rule.get("definition_sha256"): _fail("action_offer.resolution_rule_unresolved", f"{path}.resolution", "compiled offer rule does not resolve to the supplied catalog")
        if _selector(offer["actor_input_selector"], definition, path, intervention_rules=intervention_rules, inventory=inventory) != offer["actor_input_selector"]: _fail("action_offer.actor_selector_mismatch", f"{path}.actor_input_selector", "compiled selector is not canonical")
        context, evaluations = _modifier_context(offer["modifier_context"], rule, resolution_rule_products, path)
        if context != offer["modifier_context"] or evaluations != offer["modifier_source_evaluations"]: _fail("action_offer.modifier_context_drift", f"{path}.modifier_context", "compiled modifier context does not match the supplied Rule IR")
        generation = _mapping(_mapping(offer["narrative_policy"], f"{path}.narrative_policy")["generation_policy"], f"{path}.narrative_policy.generation_policy")
        raw_narrative = {"input_policy": offer["narrative_policy"]["input_policy"], "narrative_may_not_reinterpret_outcome": offer["narrative_policy"]["narrative_may_not_reinterpret_outcome"], "generation_policy": {key: generation[key] for key in _GENERATION_POLICY_FIELDS}}
        receipt, narrative = _receipt_and_narrative(offer["receipt_policy"], raw_narrative, rule, path)
        if receipt != offer["receipt_policy"] or narrative != offer["narrative_policy"]: _fail("action_offer.narrative_policy_mismatch", f"{path}.narrative_policy", "compiled receipt/narrative binding does not match the supplied Rule IR")
        if _result_bands(offer["result_bands"], rule, path) != offer["result_bands"]: _fail("action_offer.result_band_drift", f"{path}.result_bands", "compiled bands do not match the supplied Rule IR")


def action_offer_event_bindings(catalog: Mapping[str, Any], *, intervention_rules: Any = None,
                                inventory: Any = None) -> dict[str, dict[str, Any]]:
    """Return event-id bindings; this is a pure projection of a validated catalog."""
    validate_resolution_action_offer_catalog(catalog, intervention_rules=intervention_rules,
                                             inventory=inventory)
    grouped: dict[str, list[str]] = {}
    for offer in catalog["offers"]:
        grouped.setdefault(offer["source_event"]["event_ref"], []).append(offer["offer_ref"])
    return {event_ref: {"schema": RESOLUTION_ACTION_OFFER_BINDING_SCHEMA, "offer_refs": sorted(refs), "catalog_sha256": catalog["catalog_sha256"]} for event_ref, refs in grouped.items()}


__all__ = [
    "RESOLUTION_ACTION_OFFER_AUTHOR_SCHEMA", "RESOLUTION_ACTION_OFFER_CATALOG_SCHEMA", "RESOLUTION_ACTION_OFFER_BINDING_SCHEMA",
    "ResolutionActionOfferContractError", "action_offer_event_bindings", "compile_resolution_action_offers", "validate_resolution_action_offer_catalog",
]
