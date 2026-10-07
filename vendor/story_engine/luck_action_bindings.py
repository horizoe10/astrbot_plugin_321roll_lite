"""Compile the authored luck-action bindings the platform gambles on.

The Pack author file keeps the richer declaration: one entry per bound action
offer carrying the authored check facts, the swap recipes, the leave-door
remedy entries and the all-in benefit pairs.  This module normalises that
declaration into the narrow catalog the artifact carries:

* check is the engine-exact pre-roll policy map the platform hands back
  unchanged, so the frozen rules never restate the author prose;
* declaration preserves the authored check facts for the platform freeze,
  projection and recheck;
* recipes binds each swap recipe to its compiled slot values;
* nonterminal_clock_refs names the clocks those slots must keep open;
* event_ref/choice_ref/method_refs, remedy_entries and all_in_benefits are
  preserved so the leave-door and all-in modes stand on registered sources
  instead of invented ones.

Every field is cross-checked against the compiled offer, definition, rule,
recipe catalog and event modifier.  Nothing here reads an author path at run
time: preparation resolves one compiled entry through binding_for_offer.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .luck_intervention import GAMBLABLE_STAKES
from .luck_preparation import REMEDY_EXPIRY, bind_rule_bands
# One definition of the consequence contract: the offer compiler owns it.
from .resolution_action_offer import ResolutionActionOfferContractError, _consequences

SCHEMA = "se-luck-action-bindings-ir/1.0.0"
IR_SCHEMA = SCHEMA
CONDITION_IR_SCHEMA = 'se-luck-action-bindings-ir/1.1.0'
# The authored declaration reuses the reviewed identity of the catalog it
# feeds; the compiled form is told apart by its shape and its own digest.
AUTHOR_SCHEMA = SCHEMA
LEGACY_AUTHOR_SCHEMA = "thirteenth-seat.baimian-luck-action-bindings/1"
AUTHOR_SCHEMAS = frozenset({SCHEMA, LEGACY_AUTHOR_SCHEMA})
AUTHOR_AUTHORITY = "author_declaration_platform_rechecks_instantiated_state"
ACTION_TAG_REF = "custom:action.damage_tag"
DICE = "standard_d20"
MAXIMUM_RECIPES = 4
MAXIMUM_BENEFITS = 2

_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_AUTHOR_DOCUMENT_FIELDS = frozenset({"schema", "entries"})
_AUTHOR_OPTIONAL_DOCUMENT_FIELDS = frozenset({"authority", "requirement_refs", "event_catalog_ref"})
_AUTHOR_ENTRY_FIELDS = frozenset({"offer_ref", "event_ref", "choice_ref", "method_refs", "check",
                                 "recipe_bindings", "remedy_entries", "all_in_benefits"})
_AUTHOR_OPTIONAL_ENTRY_FIELDS = frozenset({"attempt_clock", "condition_sources"})
_DECLARATION_FIELDS = frozenset({"purpose", "risk", "opposed", "group_result", "attribute_ref", "difficulty",
                                 "visible_inputs", "tool_refs", "tool_bonus", "ordinary_k3", "ordinary_k3_guard",
                                 "remedy_chain"})
_RECIPE_BINDING_FIELDS = frozenset({"recipe_ref", "slots", "conditions", "hp_after_replacement", "clocks"})
# The six events advance one attempt-driven clock per final commit, outside the
# band consequences: the tide rises, the whiteout deepens, stability falls. The
# authored block repeats the event clock so the platform can advance it without
# reading the event document at run time.
_ATTEMPT_CLOCK_FIELDS = frozenset({"ref", "current", "maximum", "visibility", "thresholds", "advance_policy"})
# The authored block pastes the event clock verbatim, prose included; the two
# descriptive fields are checked as text and stay out of the compiled IR.
_ATTEMPT_CLOCK_OPTIONAL_FIELDS = frozenset({"title", "consequence"})
_ATTEMPT_THRESHOLD_FIELDS = frozenset({"event", "value"})
_ATTEMPT_POLICY_FIELDS = frozenset({"driven_by"})
_ATTEMPT_POLICY_OPTIONAL_FIELDS = frozenset({"delta"})
_THRESHOLD_EVENTS = frozenset({"section_exit", "contact_ends", "far_search_stops", "side_room_closes"})
_REMEDY_FIELDS = frozenset({"entry_ref", "method_ref", "chain_ref", "target_ref", "scene_ref", "preconditions",
                            "attribute_ref", "difficulty", "tools", "expires", "consequences"})
_BENEFIT_FIELDS = frozenset({"benefit_ref", "source_ref", "permission_ref", "object_ref"})
_CHECK_FIELDS = frozenset({"dice", "purpose", "risk", "opposed", "group_result", "visible_inputs", "remedy_chain",
                           "ordinary_k3"})
_COMPILED_ENTRY_FIELDS = frozenset({
    "offer_ref", "offer_sha256", "event_ref", "choice_ref", "method_refs",
    "resolution_definition_ref", "resolution_definition_sha256",
    "resolution_rule_ref", "resolution_rule_definition_sha256",
    "check", "declaration", "attempt_clock", "recipes", "nonterminal_clock_refs", "remedy_entries",
    "all_in_benefits",
})
_COMPILED_RECIPE_FIELDS = frozenset({"recipe_ref", "recipe_sha256", "slots"})
_COMPILED_ATTEMPT_CLOCK_FIELDS = frozenset({"clock_ref", "visibility", "initial_value", "maximum",
                                           "delta", "advance", "threshold_event", "threshold_value"})


class LuckActionBindingContractError(ValueError):
    def __init__(self, code: str, path: str, reason: str) -> None:
        super().__init__(f"{code}:{path}")
        self.code, self.path, self.reason = code, path, reason


def _fail(code: str, path: str, reason: str) -> None:
    raise LuckActionBindingContractError(code, path, reason)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("luck_action_bindings.object_invalid", path, "field must be a JSON object")
    return value


def _sequence(value: Any, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("luck_action_bindings.array_invalid", path, "field must be a JSON array")
    return value


def _fields(value: Mapping[str, Any], required: frozenset[str], optional: frozenset[str], path: str) -> None:
    if not required <= set(value) <= required | optional:
        _fail("luck_action_bindings.fields_invalid", path, f"fields must be exactly {sorted(required | optional)}")


def _ref(value: Any, path: str) -> str:
    if not isinstance(value, str) or _REF.fullmatch(value) is None:
        _fail("luck_action_bindings.ref_invalid", path, "a stable reference is required")
    return value


def _text(value: Any, path: str, maximum: int = 600) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        _fail("luck_action_bindings.text_invalid", path, "bounded non-empty text is required")
    return value.strip()


def _preserved_ref(value: Any, path: str, maximum: int = 160) -> str:
    """A preserved identifier the platform only echoes back, never resolves."""
    if (not isinstance(value, str) or not value or len(value) > maximum or value != value.strip()
            or any(ord(character) < 32 for character in value)):
        _fail("luck_action_bindings.ref_invalid", path, "a bounded stable identifier is required")
    return value


def _boolean(value: Any, path: str, expected: bool | None = None) -> bool:
    if type(value) is not bool or (expected is not None and value is not expected):
        _fail("luck_action_bindings.boolean_invalid", path, "a boolean is required")
    return value


def _integer(value: Any, path: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("luck_action_bindings.integer_invalid", path, f"an integer in {minimum}..{maximum} is required")
    return value


def _unique_refs(value: Any, path: str, minimum: int, maximum: int) -> list[str]:
    refs = [_ref(item, f"{path}[{index}]") for index, item in enumerate(_sequence(value, path))]
    if not minimum <= len(refs) <= maximum or len(refs) != len(set(refs)):
        _fail("luck_action_bindings.refs_invalid", path, f"references must be unique and {minimum}..{maximum} items")
    return refs


def _index(items: Sequence[Any], key: str, path: str) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(items):
        item = _mapping(raw, f"{path}[{index}]")
        ref = item.get(key)
        if not isinstance(ref, str) or ref in indexed:
            _fail("luck_action_bindings.reference_ambiguous", f"{path}[{index}].{key}", "reference must be unique")
        indexed[ref] = item
    return indexed


def _action_purpose(offer: Mapping[str, Any], path: str) -> str:
    """Read the declared stakes tag; it is the only authored purpose source."""
    context = _mapping(offer.get("modifier_context"), f"{path}.modifier_context")
    values = [item for item in _sequence(context.get("action_values"), f"{path}.modifier_context.action_values")
              if isinstance(item, Mapping) and item.get("ref") == ACTION_TAG_REF]
    if len(values) != 1 or not isinstance(values[0].get("value"), str):
        _fail("luck_action_bindings.action_tag_unresolved", f"{path}.modifier_context.action_values",
              f"the offer must declare {ACTION_TAG_REF} as its single check purpose")
    return values[0]["value"]


def _declaration(raw: Any, method_ref: str, path: str) -> dict[str, Any]:
    """Validate and copy the authored check facts; prose stays prose."""
    value = _mapping(raw, path)
    _fields(value, _DECLARATION_FIELDS, frozenset(), path)
    purpose = _text(value["purpose"], f"{path}.purpose")
    risk = _text(value["risk"], f"{path}.risk", 240)
    _boolean(value["opposed"], f"{path}.opposed", False)
    _boolean(value["group_result"], f"{path}.group_result", False)
    attribute = _ref(value["attribute_ref"], f"{path}.attribute_ref")
    difficulty = _integer(value["difficulty"], f"{path}.difficulty", 1, 40)
    visible = _unique_refs(value["visible_inputs"], f"{path}.visible_inputs", 1, 8)
    tools = _unique_refs(value["tool_refs"], f"{path}.tool_refs", 0, 1)
    bonus = _integer(value["tool_bonus"], f"{path}.tool_bonus", 0, 1)
    if not tools and bonus:
        _fail("luck_action_bindings.tool_bonus_invalid", f"{path}.tool_bonus",
              "a tool bonus needs a declared tool source")
    ordinary_k3 = _boolean(value["ordinary_k3"], f"{path}.ordinary_k3")
    guard = _ref(value["ordinary_k3_guard"], f"{path}.ordinary_k3_guard")
    chain = value["remedy_chain"]
    if chain is not None:
        chain = _ref(chain, f"{path}.remedy_chain")
    return {"purpose": purpose, "risk": risk, "opposed": False, "group_result": False,
            "attribute_ref": attribute, "difficulty": difficulty, "visible_inputs": visible,
            "tool_refs": tools, "tool_bonus": bonus, "ordinary_k3": ordinary_k3,
            "ordinary_k3_guard": guard, "remedy_chain": chain, "method_ref": method_ref}


def _check(declaration: Mapping[str, Any], offer: Mapping[str, Any], rule: Mapping[str, Any],
           path: str) -> dict[str, Any]:
    """Freeze the engine-exact pre-roll policy the platform passes back."""
    if rule.get("roll_expression") != "1d20":
        _fail("luck_action_bindings.dice_unsupported", f"{path}.dice",
              "only the compiled ordinary single D20 is supported")
    purpose = _action_purpose(offer, path)
    if purpose not in GAMBLABLE_STAKES:
        _fail("luck_action_bindings.stakes_excluded", f"{path}.purpose",
              "this check purpose is outside the registered odds window")
    selector = _mapping(offer.get("actor_input_selector"), f"{path}.offer.actor_input_selector")
    allowed = _sequence(selector.get("allowed_input_refs"), f"{path}.offer.actor_input_selector.allowed_input_refs")
    if declaration["attribute_ref"] not in allowed:
        _fail("luck_action_bindings.attribute_unresolved", f"{path}.declaration.attribute_ref",
              "the declared attribute must be a selector input of the compiled offer")
    formula = selector.get("modifier_formula")
    if isinstance(formula, Mapping):
        selected = _mapping(selector.get("selected_input_refs"),
                            f"{path}.offer.actor_input_selector.selected_input_refs")
        if formula.get("kind") == "attribute_event_step":
            if selected.get("ability_ref") != declaration["attribute_ref"]:
                _fail("luck_action_bindings.attribute_drift", f"{path}.declaration.attribute_ref",
                      "the declared attribute must equal the compiled event conversion attribute")
            sources = formula.get("tool_refs") or []
            if not set(declaration["tool_refs"]) <= set(sources):
                _fail("luck_action_bindings.tool_source_invalid", f"{path}.declaration.tool_refs",
                      "declared tool sources must be registered by the compiled event conversion")
            if len(declaration["tool_refs"]) > formula.get("maximum_tools", 0) \
                    or declaration["tool_bonus"] > formula.get("usable_tool_bonus", 0):
                _fail("luck_action_bindings.tool_bonus_invalid", f"{path}.declaration.tool_bonus",
                      "the tool bonus cannot exceed the compiled event conversion cap")
        elif formula.get("kind") == "attribute_minus_baseline":
            if declaration["tool_refs"] or declaration["tool_bonus"]:
                _fail("luck_action_bindings.tool_bonus_invalid", f"{path}.declaration.tool_bonus",
                      "a literal baseline conversion has no tool clause")
    return {"dice": DICE, "purpose": purpose, "risk": True, "opposed": False, "group_result": False,
            "visible_inputs": True, "remedy_chain": False, "ordinary_k3": declaration["ordinary_k3"]}


def _compiled_recipes(raw: Any, catalog: Mapping[str, Any], path: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Bind authored recipe choices to the compiled catalog and its guards."""
    indexed = _index(_sequence(catalog.get("recipes"), f"{path}.catalog"), "recipe_ref", f"{path}.catalog")
    declared = _sequence(raw, path)
    if len(declared) > MAXIMUM_RECIPES:
        _fail("luck_action_bindings.recipes_invalid", path, f"at most {MAXIMUM_RECIPES} swap recipes per binding")
    compiled: list[dict[str, Any]] = []
    clocks: set[str] = set()
    seen: set[str] = set()
    for index, raw_entry in enumerate(declared):
        entry_path = f"{path}[{index}]"
        entry = _mapping(raw_entry, entry_path)
        _fields(entry, _RECIPE_BINDING_FIELDS, frozenset(), entry_path)
        ref = _ref(entry["recipe_ref"], f"{entry_path}.recipe_ref")
        if ref in seen:
            _fail("luck_action_bindings.recipe_duplicate", f"{entry_path}.recipe_ref",
                  "one recipe cannot bind twice to the same action")
        seen.add(ref)
        recipe = indexed.get(ref)
        if recipe is None:
            _fail("luck_action_bindings.recipe_unresolved", f"{entry_path}.recipe_ref",
                  "the recipe must exist in the compiled catalog")
        if "swap" not in recipe.get("modes", ()):
            _fail("luck_action_bindings.recipe_mode_invalid", f"{entry_path}.recipe_ref",
                  "only a compiled swap recipe may be bound here")
        slots = _mapping(entry["slots"], f"{entry_path}.slots")
        declared_slots = _mapping(recipe.get("slots"), f"{entry_path}.recipe.slots")
        if set(slots) != set(declared_slots):
            _fail("luck_action_bindings.slots_incomplete", f"{entry_path}.slots",
                  "slots must cover exactly the compiled recipe slots")
        slot_values = {name: _ref(slots[name], f"{entry_path}.slots.{name}") for name in sorted(slots)}
        clock_slots: set[str] = set()
        for name, definition in sorted(declared_slots.items()):
            kind = _mapping(definition, f"{entry_path}.recipe.slots.{name}").get("kind")
            value = slot_values[name]
            if kind == "owned_item":
                if value not in definition.get("item_refs", ()):
                    _fail("luck_action_bindings.slot_source_invalid", f"{entry_path}.slots.{name}",
                          "an item slot may only use a registered item source")
            elif kind == "public_nonterminal_clock":
                clock_slots.add(name)
                clocks.add(value)
            else:
                _fail("luck_action_bindings.slot_kind_invalid", f"{entry_path}.recipe.slots.{name}",
                      "unregistered slot kind")
        declared_conditions = _unique_refs(entry["conditions"], f"{entry_path}.conditions", 0, 8)
        guard_refs = sorted({guard["condition_ref"] for guard in recipe.get("guards", ())
                             if isinstance(guard, Mapping) and guard.get("kind") == "confirmed_condition"})
        if sorted(declared_conditions) != guard_refs:
            _fail("luck_action_bindings.conditions_incomplete", f"{entry_path}.conditions",
                  "declared conditions must cover exactly the compiled recipe guards")
        _integer(entry["hp_after_replacement"], f"{entry_path}.hp_after_replacement", 1, 99)
        declared_clocks = _mapping(entry["clocks"], f"{entry_path}.clocks")
        if not set(declared_clocks) <= clock_slots:
            _fail("luck_action_bindings.clock_source_invalid", f"{entry_path}.clocks",
                  "clock declarations may only cover the recipe clock slots")
        for name, value in sorted(declared_clocks.items()):
            if _ref(value, f"{entry_path}.clocks.{name}") != slot_values[name]:
                _fail("luck_action_bindings.clock_source_invalid", f"{entry_path}.clocks.{name}",
                      "the clock declaration must equal the clock bound to that slot")
        compiled.append({"recipe_ref": ref, "recipe_sha256": recipe.get("recipe_sha256"), "slots": slot_values})
    compiled.sort(key=lambda item: item["recipe_ref"])
    return compiled, sorted(clocks)


def _attempt_clock(raw: Any, declaration: Mapping[str, Any], path: str) -> dict[str, Any] | None:
    """Normalise the event's attempt-driven clock into its one-commit advance.

    Only an attempt-driven clock becomes an advance the platform applies once per
    final commit, outside the band consequences. A band-driven or absent clock
    stays out of this field: nothing here invents an advance the author did not
    declare, and the delta keeps its sign so a count-down clock stays a count-down."""
    if raw is None:
        return None
    value = _mapping(raw, path)
    _fields(value, _ATTEMPT_CLOCK_FIELDS, _ATTEMPT_CLOCK_OPTIONAL_FIELDS, path)
    for name in sorted(_ATTEMPT_CLOCK_OPTIONAL_FIELDS & set(value)):
        _text(value[name], f"{path}.{name}", 600)
    clock_ref = _ref(value["ref"], f"{path}.ref")
    current = _integer(value["current"], f"{path}.current", 0, 99)
    maximum = _integer(value["maximum"], f"{path}.maximum", 1, 99)
    if current > maximum:
        _fail("luck_action_bindings.attempt_clock_invalid", f"{path}.current",
              "the clock cannot start beyond its maximum")
    if value["visibility"] != "public":
        _fail("luck_action_bindings.attempt_clock_invalid", f"{path}.visibility",
              "an odds window needs a publicly visible clock")
    thresholds = _sequence(value["thresholds"], f"{path}.thresholds")
    if len(thresholds) != 1:
        _fail("luck_action_bindings.attempt_clock_invalid", f"{path}.thresholds",
              "the attempt clock declares exactly one closure threshold")
    threshold = _mapping(thresholds[0], f"{path}.thresholds[0]")
    _fields(threshold, _ATTEMPT_THRESHOLD_FIELDS, frozenset(), f"{path}.thresholds[0]")
    threshold_event = _text(threshold["event"], f"{path}.thresholds[0].event", 40)
    if threshold_event not in _THRESHOLD_EVENTS:
        _fail("luck_action_bindings.attempt_clock_invalid", f"{path}.thresholds[0].event",
              "unregistered closure threshold event")
    threshold_value = _integer(threshold["value"], f"{path}.thresholds[0].value", 0, maximum)
    if threshold_value == current:
        _fail("luck_action_bindings.attempt_clock_invalid", f"{path}.thresholds[0].value",
              "the clock must not start already closed")
    policy = _mapping(value["advance_policy"], f"{path}.advance_policy")
    _fields(policy, _ATTEMPT_POLICY_FIELDS, _ATTEMPT_POLICY_OPTIONAL_FIELDS, f"{path}.advance_policy")
    if policy["driven_by"] != "attempt":
        # A band-driven clock advances inside the compiled band consequences.
        return None
    if "delta" not in policy:
        _fail("luck_action_bindings.attempt_clock_invalid", f"{path}.advance_policy.delta",
              "an attempt-driven clock declares its delta")
    delta = _integer(policy["delta"], f"{path}.advance_policy.delta", -5, 5)
    if delta == 0:
        _fail("luck_action_bindings.attempt_clock_invalid", f"{path}.advance_policy.delta",
              "an attempt advance needs a non-zero delta")
    if delta > 0 and threshold_value < current or delta < 0 and threshold_value > current:
        _fail("luck_action_bindings.attempt_clock_invalid", f"{path}.thresholds[0].value",
              "the closure threshold must lie in the direction the delta moves the clock")
    if clock_ref not in declaration["visible_inputs"]:
        _fail("luck_action_bindings.attempt_clock_invalid", f"{path}.ref",
              "a declared attempt clock must be one of the action's visible inputs")
    return {"clock_ref": clock_ref, "visibility": "public", "initial_value": current,
            "maximum": maximum, "delta": delta, "advance": "once_per_commit",
            "threshold_event": threshold_event, "threshold_value": threshold_value}


def _remedy_entries(raw: Any, method_ref: str, declaration: Mapping[str, Any],
                    path: str) -> list[dict[str, Any]]:
    """Preserve at most one leave-door entry; the platform must never invent one."""
    declared = _sequence(raw, path)
    if len(declared) > 1:
        _fail("luck_action_bindings.remedy_invalid", path, "at most one leave-door entry per action")
    compiled: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(declared):
        entry_path = f"{path}[{index}]"
        entry = _mapping(raw_entry, entry_path)
        _fields(entry, _REMEDY_FIELDS, frozenset(), entry_path)
        if entry["method_ref"] != method_ref:
            _fail("luck_action_bindings.remedy_invalid", f"{entry_path}.method_ref",
                  "a remedy entry must bind its own method")
        if entry["expires"] not in REMEDY_EXPIRY:
            _fail("luck_action_bindings.remedy_invalid", f"{entry_path}.expires", "unregistered remedy expiry")
        if entry["chain_ref"] != declaration["remedy_chain"]:
            _fail("luck_action_bindings.remedy_invalid", f"{entry_path}.chain_ref",
                  "the remedy chain must match the declared chain")
        for name in ("entry_ref", "chain_ref", "target_ref", "scene_ref", "attribute_ref"):
            _ref(entry[name], f"{entry_path}.{name}")
        _integer(entry["difficulty"], f"{entry_path}.difficulty", 1, 40)
        _unique_refs(entry["preconditions"], f"{entry_path}.preconditions", 1, 8)
        _unique_refs(entry["tools"], f"{entry_path}.tools", 0, 8)
        try:
            _consequences(entry["consequences"], f"{entry_path}.consequences")
        except ResolutionActionOfferContractError as exc:
            _fail("luck_action_bindings.consequences_invalid", f"{entry_path}.consequences", str(exc))
        compiled.append({name: entry[name] for name in sorted(_REMEDY_FIELDS)})
    if declaration["remedy_chain"] is not None and not compiled:
        _fail("luck_action_bindings.remedy_invalid", path, "a declared chain needs its real entry")
    if declaration["remedy_chain"] is None and compiled:
        _fail("luck_action_bindings.remedy_invalid", path, "a remedy entry needs its declared chain")
    return compiled


def _condition_sources(raw, remedies, clock, path, offer=None):
    values=_sequence(raw,path)
    expected={ref for entry in remedies for ref in entry['preconditions']}
    if not values or len(values)>8:_fail('luck_action_bindings.condition_invalid',path,'bounded condition sources required')
    seen=set();result=[]
    for value in values:
        value=_mapping(value,path);kind=value.get('kind')
        extra={'event_checkpoint':{'checkpoint_ref'},'attempt_clock_after':{'clock_ref','operator','value'},'result_fact':{'band_ref','fact_ref','value'}}.get(kind)
        if extra is None:_fail('luck_action_bindings.condition_invalid',path,'unknown condition source')
        _fields(value,{'condition_ref','kind'}|extra,frozenset(),path)
        ref=_ref(value['condition_ref'],path)
        if ref in seen:_fail('luck_action_bindings.condition_invalid',path,'duplicate condition source')
        seen.add(ref)
        if kind=='event_checkpoint':
            _ref(value['checkpoint_ref'],path)
            if offer and value['checkpoint_ref']!=offer['source_event']['checkpoint_ref']:_fail('luck_action_bindings.condition_invalid',path,'checkpoint must bind the original method')
        elif kind=='attempt_clock_after':
            if (not clock or value['clock_ref']!=clock['clock_ref'] or type(value['value']) is not int
                    or value['value']!=clock['threshold_value'] or value['operator']!=('lt' if clock['delta']>0 else 'gt')):
                _fail('luck_action_bindings.condition_invalid',path,'condition must preserve the actual closure threshold')
        else:
            _ref(value['band_ref'],path);_ref(value['fact_ref'],path);_boolean(value['value'],path,True)
            if offer:
                band=next((b for b in offer['result_bands'] if b['band_ref']==value['band_ref']),None)
                if not band or band['outcome']!='failure' or band['degree']=='critical' or not any(e['kind']=='fact.set' and e.get('fact_ref')==value['fact_ref'] and e.get('value') is True for e in band.get('consequences',[])):
                    _fail('luck_action_bindings.condition_invalid',path,'result fact must be produced by this ordinary failure')
        result.append(dict(value))
    if seen!=expected:_fail('luck_action_bindings.condition_invalid',path,'each remedy condition needs exactly one source')
    return sorted(result,key=lambda value:value['condition_ref'])


def _all_in_benefits(raw: Any, method_ref: str, path: str) -> list[dict[str, Any]]:
    """Preserve the reviewed benefit pair; both objects must already exist."""
    declared = _sequence(raw, path)
    if len(declared) not in {0, MAXIMUM_BENEFITS}:
        _fail("luck_action_bindings.benefits_invalid", path, f"all-in benefits are 0 or {MAXIMUM_BENEFITS} items")
    compiled: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_entry in enumerate(declared):
        entry_path = f"{path}[{index}]"
        entry = _mapping(raw_entry, entry_path)
        _fields(entry, _BENEFIT_FIELDS, frozenset(), entry_path)
        for name in sorted(_BENEFIT_FIELDS):
            (_preserved_ref if name == "benefit_ref" else _ref)(entry[name], f"{entry_path}.{name}")
        if entry["source_ref"] != method_ref:
            _fail("luck_action_bindings.benefits_invalid", f"{entry_path}.source_ref",
                  "a benefit must name this action method as its source")
        if entry["benefit_ref"] in seen:
            _fail("luck_action_bindings.benefits_invalid", f"{entry_path}.benefit_ref", "benefit refs must be unique")
        seen.add(entry["benefit_ref"])
        compiled.append({name: entry[name] for name in sorted(_BENEFIT_FIELDS)})
    if len({item["object_ref"] for item in compiled}) != len(compiled):
        _fail("luck_action_bindings.benefits_invalid", path,
              "the two all-in benefits must be two distinct objects")
    return sorted(compiled, key=lambda item: item["benefit_ref"])


def compile_luck_action_bindings(document: Mapping[str, Any], offers: Mapping[str, Any],
                                 recipes: Mapping[str, Any], definitions: Mapping[str, Any],
                                 rules: Mapping[str, Any], intervention_rules: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise one authored binding document into the artifact catalog."""
    doc = _mapping(document, "$")
    _fields(doc, _AUTHOR_DOCUMENT_FIELDS, _AUTHOR_OPTIONAL_DOCUMENT_FIELDS, "$")
    if doc.get("schema") not in AUTHOR_SCHEMAS:
        _fail("luck_action_bindings.schema_invalid", "schema", "unsupported luck action binding author schema")
    if doc.get("authority", AUTHOR_AUTHORITY) != AUTHOR_AUTHORITY:
        _fail("luck_action_bindings.authority_invalid", "authority",
              "bindings stay an author declaration the platform rechecks")
    if "requirement_refs" in doc:
        _unique_refs(doc["requirement_refs"], "requirement_refs", 0, 16)
    if "event_catalog_ref" in doc:
        _text(doc["event_catalog_ref"], "event_catalog_ref", 240)
    entries = _sequence(doc["entries"], "entries")
    if not 1 <= len(entries) <= 64:
        _fail("luck_action_bindings.entries_invalid", "entries", "the catalog stays 1..64 entries")
    offer_index = _index(_sequence(_mapping(offers, "offers").get("offers"), "offers.offers"), "offer_ref",
                         "offers.offers")
    rule_index = _index(_sequence(_mapping(rules, "rules").get("resolution_rule_definitions"), "rules.definitions"),
                        "resolution_rule_ref", "rules.definitions")
    definition_index = _index(
        _sequence(_mapping(definitions, "definitions").get("definitions"), "definitions.definitions"),
        "definition_ref", "definitions.definitions")
    compiled: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(entries):
        path = f"entries[{index}]"
        entry = _mapping(raw, path)
        _fields(entry, _AUTHOR_ENTRY_FIELDS, _AUTHOR_OPTIONAL_ENTRY_FIELDS, path)
        offer_ref = _ref(entry["offer_ref"], f"{path}.offer_ref")
        if offer_ref in seen:
            _fail("luck_action_bindings.offer_duplicate", f"{path}.offer_ref", "one binding per offer")
        seen.add(offer_ref)
        offer = offer_index.get(offer_ref)
        if offer is None:
            _fail("luck_action_bindings.offer_unresolved", f"{path}.offer_ref",
                  "the offer must exist in the compiled action catalog")
        source_event = _mapping(offer.get("source_event"), f"{path}.offer.source_event")
        if entry["event_ref"] != source_event.get("event_ref") \
                or entry["choice_ref"] != source_event.get("choice_ref"):
            _fail("luck_action_bindings.source_event_drift", path,
                  "a binding must repeat the exact compiled source event and choice")
        method_refs = _unique_refs(entry["method_refs"], f"{path}.method_refs", 1, 1)
        resolution = _mapping(offer.get("resolution"), f"{path}.offer.resolution")
        rule_ref = _ref(resolution.get("resolution_rule_ref"), f"{path}.offer.resolution.resolution_rule_ref")
        definition_ref = _ref(resolution.get("resolution_definition_ref"),
                              f"{path}.offer.resolution.resolution_definition_ref")
        rule = rule_index.get(rule_ref)
        if rule is None or rule.get("definition_sha256") != resolution.get("resolution_rule_definition_sha256"):
            _fail("luck_action_bindings.rule_unresolved", f"{path}.offer.resolution",
                  "the offer must bind one compiled D20 definition")
        definition = definition_index.get(definition_ref)
        if definition is None or definition.get("definition_sha256") != resolution.get("resolution_definition_sha256"):
            _fail("luck_action_bindings.definition_unresolved", path,
                  "the offer must bind one compiled check definition")
        # The authored binding must sit on a rule whose bands the compiled luck
        # results already resolve onto, exactly as preparation re-checks at run time.
        try:
            bind_rule_bands(rule, intervention_rules, offer.get("result_bands"))
        except ValueError as exc:
            _fail("luck_action_bindings.rule_bands_incompatible", f"{path}.offer.result_bands", str(exc))
        declaration = _declaration(entry["check"], method_refs[0], f"{path}.check")
        bound_recipes, clocks = _compiled_recipes(entry["recipe_bindings"], recipes, f"{path}.recipe_bindings")
        compiled.append({
            "offer_ref": offer_ref,
            "offer_sha256": offer.get("offer_sha256"),
            "event_ref": _ref(entry["event_ref"], f"{path}.event_ref"),
            "choice_ref": _ref(entry["choice_ref"], f"{path}.choice_ref"),
            "method_refs": method_refs,
            "resolution_definition_ref": definition_ref,
            "resolution_definition_sha256": definition.get("definition_sha256"),
            "resolution_rule_ref": rule_ref,
            "resolution_rule_definition_sha256": rule.get("definition_sha256"),
            "check": _check(declaration, offer, rule, f"{path}.check"),
            "declaration": declaration,
            "attempt_clock": _attempt_clock(entry.get("attempt_clock"), declaration,
                                             f"{path}.attempt_clock"),
            "recipes": bound_recipes,
            "nonterminal_clock_refs": clocks,
            "remedy_entries": _remedy_entries(entry["remedy_entries"], method_refs[0], declaration,
                                              f"{path}.remedy_entries"),
            "all_in_benefits": _all_in_benefits(entry["all_in_benefits"], method_refs[0],
                                                f"{path}.all_in_benefits"),
        })
        if 'condition_sources' in entry:
            compiled[-1]['condition_sources']=_condition_sources(entry['condition_sources'],compiled[-1]['remedy_entries'],compiled[-1]['attempt_clock'],f'{path}.condition_sources',offer)
    compiled.sort(key=lambda item: item["offer_ref"])
    result = {"schema": CONDITION_IR_SCHEMA if any('condition_sources' in entry for entry in compiled) else IR_SCHEMA, "entries": compiled}
    result["document_sha256"] = _digest(result)
    validate_luck_action_bindings_ir(result)
    return result


def _validate_attempt_clock(raw: Any, declaration: Mapping[str, Any], path: str) -> None:
    """Re-check a compiled attempt clock; null is a real, legal value."""
    if raw is None:
        return
    value = _mapping(raw, path)
    _fields(value, _COMPILED_ATTEMPT_CLOCK_FIELDS, frozenset(), path)
    clock_ref = _ref(value["clock_ref"], f"{path}.clock_ref")
    if value["visibility"] != "public" or value["advance"] != "once_per_commit":
        _fail("luck_action_bindings.attempt_clock_invalid", path,
              "a compiled attempt clock stays public and advances once per commit")
    initial = _integer(value["initial_value"], f"{path}.initial_value", 0, 99)
    maximum = _integer(value["maximum"], f"{path}.maximum", 1, 99)
    threshold = _integer(value["threshold_value"], f"{path}.threshold_value", 0, maximum)
    delta = _integer(value["delta"], f"{path}.delta", -5, 5)
    if initial > maximum or delta == 0 or threshold == initial \
            or (delta > 0 and threshold < initial) or (delta < 0 and threshold > initial):
        _fail("luck_action_bindings.attempt_clock_invalid", path, "compiled attempt clock is not coherent")
    if _text(value["threshold_event"], f"{path}.threshold_event", 40) not in _THRESHOLD_EVENTS:
        _fail("luck_action_bindings.attempt_clock_invalid", f"{path}.threshold_event",
              "unregistered closure threshold event")
    if clock_ref not in declaration["visible_inputs"]:
        _fail("luck_action_bindings.attempt_clock_invalid", f"{path}.clock_ref",
              "a declared attempt clock must be one of the action's visible inputs")


def _check_digest(value: Any, path: str) -> None:


    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        _fail("luck_action_bindings.ir_invalid", path, "compiled digest is invalid")


def _validate_ir_entry(entry: Mapping[str, Any], path: str, conditions=False) -> str:
    _fields(entry, _COMPILED_ENTRY_FIELDS, frozenset({'condition_sources'}) if conditions else frozenset(), path)
    for name in ("offer_sha256", "resolution_definition_sha256", "resolution_rule_definition_sha256"):
        _check_digest(entry[name], f"{path}.{name}")
    for name in ("resolution_definition_ref", "resolution_rule_ref", "event_ref", "choice_ref"):
        _ref(entry[name], f"{path}.{name}")
    method_refs = _unique_refs(entry["method_refs"], f"{path}.method_refs", 1, 1)
    check = _mapping(entry["check"], f"{path}.check")
    _fields(check, _CHECK_FIELDS, frozenset(), f"{path}.check")
    if check["dice"] != DICE or check["purpose"] not in GAMBLABLE_STAKES:
        _fail("luck_action_bindings.ir_invalid", f"{path}.check", "compiled check policy is invalid")
    for name in ("risk", "opposed", "group_result", "visible_inputs", "remedy_chain", "ordinary_k3"):
        _boolean(check[name], f"{path}.check.{name}")
    if check["opposed"] or check["group_result"] or check["remedy_chain"] or not check["risk"]:
        _fail("luck_action_bindings.ir_invalid", f"{path}.check", "compiled check policy is not gamblable")
    declaration = _mapping(entry["declaration"], f"{path}.declaration")
    _fields(declaration, _DECLARATION_FIELDS | {"method_ref"}, frozenset(), f"{path}.declaration")
    if declaration["method_ref"] != method_refs[0] or declaration["ordinary_k3"] is not check["ordinary_k3"]:
        _fail("luck_action_bindings.ir_invalid", f"{path}.declaration",
              "the compiled declaration disagrees with the check policy")
    _text(declaration["purpose"], f"{path}.declaration.purpose")
    _text(declaration["risk"], f"{path}.declaration.risk", 240)
    _boolean(declaration["opposed"], f"{path}.declaration.opposed", False)
    _boolean(declaration["group_result"], f"{path}.declaration.group_result", False)
    _ref(declaration["attribute_ref"], f"{path}.declaration.attribute_ref")
    _integer(declaration["difficulty"], f"{path}.declaration.difficulty", 1, 40)
    _unique_refs(declaration["visible_inputs"], f"{path}.declaration.visible_inputs", 1, 8)
    _unique_refs(declaration["tool_refs"], f"{path}.declaration.tool_refs", 0, 1)
    _integer(declaration["tool_bonus"], f"{path}.declaration.tool_bonus", 0, 1)
    _ref(declaration["ordinary_k3_guard"], f"{path}.declaration.ordinary_k3_guard")
    if declaration["remedy_chain"] is not None:
        _ref(declaration["remedy_chain"], f"{path}.declaration.remedy_chain")
    _validate_attempt_clock(entry["attempt_clock"], declaration, f"{path}.attempt_clock")
    compiled_recipes = _sequence(entry["recipes"], f"{path}.recipes")
    if len(compiled_recipes) > MAXIMUM_RECIPES:
        _fail("luck_action_bindings.ir_invalid", f"{path}.recipes", "compiled recipes must stay bounded")
    recipe_refs: list[str] = []
    for recipe_index, raw_recipe in enumerate(compiled_recipes):
        recipe_path = f"{path}.recipes[{recipe_index}]"
        recipe = _mapping(raw_recipe, recipe_path)
        _fields(recipe, _COMPILED_RECIPE_FIELDS, frozenset(), recipe_path)
        recipe_refs.append(_ref(recipe["recipe_ref"], f"{recipe_path}.recipe_ref"))
        _check_digest(recipe["recipe_sha256"], f"{recipe_path}.recipe_sha256")
        bound = _mapping(recipe["slots"], f"{recipe_path}.slots")
        if len(bound) > 4:
            _fail("luck_action_bindings.ir_invalid", f"{recipe_path}.slots", "compiled slots must stay bounded")
        for name, value in bound.items():
            _ref(value, f"{recipe_path}.slots.{name}")
    if recipe_refs != sorted(recipe_refs) or len(recipe_refs) != len(set(recipe_refs)):
        _fail("luck_action_bindings.ir_invalid", f"{path}.recipes", "compiled recipes must be sorted and unique")
    clocks = _unique_refs(entry["nonterminal_clock_refs"], f"{path}.nonterminal_clock_refs", 0, 8)
    if clocks != sorted(clocks):
        _fail("luck_action_bindings.ir_invalid", f"{path}.nonterminal_clock_refs", "clock refs must be sorted")
    remedy_entries = _sequence(entry["remedy_entries"], f"{path}.remedy_entries")
    if len(remedy_entries) > 1:
        _fail("luck_action_bindings.ir_invalid", f"{path}.remedy_entries", "leave-door entries stay unique")
    for remedy_index, raw_remedy in enumerate(remedy_entries):
        remedy_path = f"{path}.remedy_entries[{remedy_index}]"
        remedy = _mapping(raw_remedy, remedy_path)
        _fields(remedy, _REMEDY_FIELDS, frozenset(), remedy_path)
        for name in ("entry_ref", "method_ref", "chain_ref", "target_ref", "scene_ref", "attribute_ref"):
            _ref(remedy[name], f"{remedy_path}.{name}")
        if remedy["method_ref"] not in method_refs or remedy["chain_ref"] != declaration["remedy_chain"] \
                or remedy["expires"] not in REMEDY_EXPIRY:
            _fail("luck_action_bindings.ir_invalid", remedy_path, "the leave-door entry drifted from its method")
        _integer(remedy["difficulty"], f"{remedy_path}.difficulty", 1, 40)
        _unique_refs(remedy["preconditions"], f"{remedy_path}.preconditions", 1, 8)
        _unique_refs(remedy["tools"], f"{remedy_path}.tools", 0, 8)
        try:
            _consequences(remedy["consequences"], f"{remedy_path}.consequences")
        except ResolutionActionOfferContractError as exc:
            _fail("luck_action_bindings.ir_invalid", f"{remedy_path}.consequences", str(exc))
    if 'condition_sources' in entry:
        normalized=_condition_sources(entry['condition_sources'],remedy_entries,entry['attempt_clock'],f'{path}.condition_sources')
        if normalized!=entry['condition_sources']:_fail('luck_action_bindings.ir_invalid',path,'condition sources must be sorted')
    benefits = _sequence(entry["all_in_benefits"], f"{path}.all_in_benefits")
    if len(benefits) not in {0, MAXIMUM_BENEFITS}:
        _fail("luck_action_bindings.ir_invalid", f"{path}.all_in_benefits",
              f"all-in benefits are 0 or {MAXIMUM_BENEFITS} items")
    benefit_refs: list[str] = []
    for benefit_index, raw_benefit in enumerate(benefits):
        benefit_path = f"{path}.all_in_benefits[{benefit_index}]"
        benefit = _mapping(raw_benefit, benefit_path)
        _fields(benefit, _BENEFIT_FIELDS, frozenset(), benefit_path)
        for name in sorted(_BENEFIT_FIELDS):
            (_preserved_ref if name == "benefit_ref" else _ref)(benefit[name], f"{benefit_path}.{name}")
        if benefit["source_ref"] not in method_refs:
            _fail("luck_action_bindings.ir_invalid", f"{benefit_path}.source_ref",
                  "a benefit must name this action method")
        benefit_refs.append(benefit["benefit_ref"])
    if len(benefit_refs) != len(set(benefit_refs)):
        _fail("luck_action_bindings.ir_invalid", f"{path}.all_in_benefits", "benefit refs must be unique")
    return entry["offer_ref"]


def validate_luck_action_bindings_ir(value: Any) -> None:
    """Fail closed when a compiled binding catalog is altered or reordered."""
    catalog = _mapping(value, "luck_action_bindings")
    if set(catalog) != {"schema", "entries", "document_sha256"} or catalog.get("schema") not in {IR_SCHEMA,CONDITION_IR_SCHEMA}:
        _fail("luck_action_bindings.ir_invalid", "luck_action_bindings", "compiled binding identity is invalid")
    if catalog.get("document_sha256") != _digest({key: item for key, item in catalog.items()
                                                  if key != "document_sha256"}):
        _fail("luck_action_bindings.digest_mismatch", "luck_action_bindings.document_sha256",
              "binding catalog digest does not match its content")
    entries = _sequence(catalog["entries"], "luck_action_bindings.entries")
    if not 1 <= len(entries) <= 64:
        _fail("luck_action_bindings.ir_invalid", "luck_action_bindings.entries", "binding catalog must stay bounded")
    refs = [_validate_ir_entry(_mapping(raw, f"luck_action_bindings.entries[{index}]"),
                               f"luck_action_bindings.entries[{index}]",catalog['schema']==CONDITION_IR_SCHEMA)
            for index, raw in enumerate(entries)]
    if refs != sorted(refs) or len(refs) != len(set(refs)):
        _fail("luck_action_bindings.ir_invalid", "luck_action_bindings.entries",
              "compiled entries must be sorted and unique")


def binding_for_offer(catalog: Any, offer_ref: str, offer_sha256: str) -> dict[str, Any]:
    """Resolve the one binding a runtime proposal may use; never reads a path."""
    validate_luck_action_bindings_ir(catalog)
    matches = [entry for entry in catalog["entries"] if entry["offer_ref"] == offer_ref]
    if len(matches) != 1:
        _fail("luck_action_bindings.offer_unbound", "luck_action_bindings.entries",
              "no unique compiled binding covers this action")
    if matches[0]["offer_sha256"] != offer_sha256:
        _fail("luck_action_bindings.offer_mismatch", "luck_action_bindings.entries",
              "the compiled binding does not match this action digest")
    return matches[0]


__all__ = ["ACTION_TAG_REF", "AUTHOR_AUTHORITY", "AUTHOR_SCHEMA", "AUTHOR_SCHEMAS", "DICE", "IR_SCHEMA",
           "LEGACY_AUTHOR_SCHEMA", "MAXIMUM_RECIPES", "SCHEMA", "LuckActionBindingContractError",
           "binding_for_offer", "compile_luck_action_bindings", "validate_luck_action_bindings_ir"]
