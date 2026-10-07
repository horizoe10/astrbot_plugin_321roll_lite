"""Deterministic pre-roll preparation for one luck intervention window.

The intervention rules and the cost-replacement recipes always come from the
actual fixed artifact read through the authorized bridge; the snapshot only
selects them by reference and carries platform-confirmed frozen inputs. This
entry point never acquires randomness, invokes a Provider, writes state, picks a
candidate for the player, or recompiles the Story Pack.

Two registration states share one contract. Without prepared_choices the
proposal is a preview: every legal candidate of every face is returned and the
platform may not open a window from it. With prepared_choices the player's own
pre-roll registration bounds each face to the free original plus the chosen
options, so the platform can seal one draw and open a single window. A
registered option that has no legal candidate anywhere fails closed instead of
being dropped silently.
"""
from collections.abc import Mapping
from copy import deepcopy
import json

from .contracts.port import ArtifactSliceRequest, canonical_fingerprint
from .luck_intervention import (LuckInterventionError, mode_for_result, original_result,
                                prepare_mode_policy, window_contains)
from .luck_recipes import LuckRecipeError, prepare_replacement
from .resolution_action_offer import ResolutionActionOfferContractError, _consequences

SNAPSHOT_SCHEMA = '321roll-luck-preparation-snapshot/1.0.0'
CONDITION_SNAPSHOT_SCHEMA = '321roll-luck-preparation-snapshot/1.1.0'
PROPOSAL_SCHEMA = 'se-luck-preparation-proposal/1.0.0'
CANDIDATE_SCHEMA = 'se-luck-candidate-proposal/1.0.0'
# The pre-roll bet is one self-contained object: the platform freezes it whole,
# pays the fee, adds the doom and grants exactly one of the two registered
# benefits. Its own digest lets the committed decision be proven against it.
ALL_IN_SCHEMA = 'se-luck-all-in-bet/1.0.0'
FEATURE = 'luck.preparation/1.0.0'
INTERVENTION_RULES_IR = 'se-luck-intervention-rules-ir/1.0.0'
RECIPE_CATALOG_IR = 'se-luck-recipe-catalog-ir/1.0.0'

# The installed platform transport reads one fixed artifact through this bound.
ARTIFACT_SLICE_LIMIT = 16_000_001
LOSS_KINDS = frozenset({'actor.hp.damage', 'inventory.consume', 'inventory.damage', 'inventory.break'})
REMEDY_EXPIRY = frozenset({'next_action_end', 'scene_exit'})
# Only these four modes enter the post-roll window; all-in is a separate,
# mutually exclusive pre-roll bet and is never one of the window candidates.
POST_ROLL_MODES = ('swap', 'protect', 'leave_door', 'change')
MAXIMUM_PREPARED_CHOICES = 4
WINDOW_CANDIDATE_LIMIT = 5

_SNAPSHOT_FIELDS = frozenset({
    'schema', 'operation_ref', 'artifact_ref', 'artifact_sha256', 'offer_ref', 'offer_sha256', 'state',
    'rule_definition', 'result_bands', 'modifier', 'difficulty', 'recipe_bindings', 'remedy_entries',
    'all_in_benefits', 'prepared_choices', 'snapshot_sha256'})
_OPTIONAL_FIELDS = frozenset({'remedy_entries', 'all_in_benefits', 'prepared_choices'})
_BAND_FIELDS = frozenset({'band_ref', 'outcome', 'degree', 'consequences', 'public_label'})
_BINDING_FIELDS = frozenset({'recipe_ref', 'slots', 'conditions', 'hp_after_replacement', 'clocks'})
_ENTRY_FIELDS = frozenset({'entry_ref', 'method_ref', 'chain_ref', 'target_ref', 'scene_ref', 'preconditions',
                           'attribute_ref', 'difficulty', 'tools', 'expires', 'consequences'})
_BENEFIT_FIELDS = frozenset({'benefit_ref', 'source_ref', 'permission_ref', 'object_ref'})
_CHOICE_FIELDS = frozenset({'mode', 'recipe_ref', 'entry_ref'})


class LuckPreparationError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise LuckPreparationError(message)


def _same(left, right):
    return canonical_fingerprint(left) == canonical_fingerprint(right)


def _fields(value, path, required, optional=frozenset()):
    _require(isinstance(value, Mapping) and set(required) <= set(value) <= set(required) | set(optional),
             f'luck_preparation.{path}_fields_invalid')


def _reference(value, path, limit=160):
    _require(isinstance(value, str) and 0 < len(value) <= limit and value[0].isalnum()
             and all(character.isalnum() or character in '_.:@-' for character in value),
             f'luck_preparation.{path}_invalid')
    return value


def _digest(value, path):
    _require(isinstance(value, str) and len(value) == 71 and value.startswith('sha256:')
             and all(character in '0123456789abcdef' for character in value[7:]),
             f'luck_preparation.{path}_invalid')
    return value


def _integer(value, path):
    _require(type(value) is int, f'luck_preparation.{path}_invalid')
    return value


def _references(value, path, minimum, maximum):
    _require(isinstance(value, (list, tuple)) and minimum <= len(value) <= maximum, f'luck_preparation.{path}_invalid')
    refs = [_reference(item, path) for item in value]
    _require(len(set(refs)) == len(refs), f'luck_preparation.{path}_invalid')
    return refs


def _consequences_or_fail(effects, path):
    """Validate one consequence list; an empty list is a real, legal resolution.

    The compiled action offer omits the key when a band declares no effect at
    all, and the platform projects the same band as an explicit empty array.
    Both spellings mean one thing here: this band carries no effect."""
    _require(isinstance(effects, (list, tuple)), f'luck_preparation.{path}_invalid')
    if not effects:
        return []
    try:
        _consequences(effects, f'luck_preparation.{path}')
    except ResolutionActionOfferContractError as exc:
        raise LuckPreparationError(f'luck_preparation.{path}_invalid: {exc}') from exc
    return [dict(effect) for effect in effects]


def _band_view(band):
    """The snapshot view of one fixed band: consequences always explicit.

    Only the comparison uses this projection. The artifact keeps its own bytes
    and digests, so an offer that never declared a consequence list and a
    snapshot that spells it as an empty array still describe the same band."""
    value = {name: item for name, item in band.items() if name != 'consequences'}
    value['consequences'] = [dict(effect) for effect in band.get('consequences', ())]
    return value


def _digest_matches(value, key):
    return value.get(key) == canonical_fingerprint({name: item for name, item in value.items() if name != key})


def _choice(value, path='prepared_choices'):
    """One registered option: the free original is never part of the selection."""
    _fields(value, 'prepared_choice', _CHOICE_FIELDS)
    mode = value['mode']
    _require(mode in POST_ROLL_MODES, f'luck_preparation.{path}_invalid')
    recipe_ref, entry_ref = value['recipe_ref'], value['entry_ref']
    for ref, name in ((recipe_ref, 'recipe_ref'), (entry_ref, 'entry_ref')):
        if ref is not None:
            _reference(ref, f'prepared_choice.{name}', 100 if name == 'recipe_ref' else 160)
    if mode in {'swap', 'protect'}:
        _require(recipe_ref is not None and entry_ref is None, f'luck_preparation.{path}_invalid')
    elif mode == 'leave_door':
        _require(entry_ref is not None and recipe_ref is None, f'luck_preparation.{path}_invalid')
    else:
        _require(recipe_ref is None and entry_ref is None, f'luck_preparation.{path}_invalid')
    return {'mode': mode, 'recipe_ref': recipe_ref, 'entry_ref': entry_ref}


def _prepared_choices(value):
    """Normalize the bounded pre-roll registration; None means preview only.

    An empty list is the player's explicit pre-roll choice to keep the ordinary
    rules: it confirms the action with no intervention option. Omitting the
    field is a preview and never authorises a seal.
    """
    raw = value.get('prepared_choices')
    if raw is None:
        return None
    _require(isinstance(raw, (list, tuple)) and len(raw) <= MAXIMUM_PREPARED_CHOICES,
             'luck_preparation.prepared_choices_invalid')
    chosen, seen = [], set()
    for item in raw:
        normalized = _choice(item)
        key = (normalized['mode'], normalized['recipe_ref'], normalized['entry_ref'])
        _require(key not in seen, 'luck_preparation.prepared_choice_duplicate')
        seen.add(key)
        chosen.append(normalized)
    return chosen


def _snapshot(value):
    _fields(value, 'snapshot', _SNAPSHOT_FIELDS - _OPTIONAL_FIELDS, _OPTIONAL_FIELDS)
    _require(value['schema'] in {SNAPSHOT_SCHEMA,CONDITION_SNAPSHOT_SCHEMA}, 'luck_preparation.snapshot_schema_invalid')
    _digest(value['snapshot_sha256'], 'snapshot_sha256')
    _require(_digest_matches(value, 'snapshot_sha256'), 'luck_preparation.snapshot_digest_mismatch')
    for key in ('operation_ref', 'artifact_ref', 'offer_ref'):
        _reference(value[key], key)
    for key in ('artifact_sha256', 'offer_sha256'):
        _digest(value[key], key)
    _integer(value['modifier'], 'modifier')
    _integer(value['difficulty'], 'difficulty')
    rule = value['rule_definition']
    _require(isinstance(rule, Mapping), 'luck_preparation.rule_definition_invalid')
    _reference(rule.get('resolution_rule_ref'), 'rule_definition.resolution_rule_ref')
    _digest(rule.get('definition_sha256'), 'rule_definition.definition_sha256')
    _require(_digest_matches(rule, 'definition_sha256'), 'luck_preparation.rule_definition_mismatch')
    bands = value['result_bands']
    _require(isinstance(bands, (list, tuple)) and 2 <= len(bands) <= 8, 'luck_preparation.result_bands_invalid')
    seen = set()
    normalized_bands = []
    for band in bands:
        _fields(band, 'result_band', _BAND_FIELDS - {'consequences'}, {'consequences'})
        ref = _reference(band['band_ref'], 'result_bands.band_ref')
        _require(ref not in seen, 'luck_preparation.result_bands_invalid')
        seen.add(ref)
        _require(band['outcome'] in {'success', 'failure'}, 'luck_preparation.result_bands_invalid')
        _reference(band['degree'], 'result_bands.degree')
        _require(isinstance(band['public_label'], str) and 0 < len(band['public_label']) <= 240,
                 'luck_preparation.result_bands_invalid')
        normalized_bands.append({**band,
                                 'consequences': _consequences_or_fail(band.get('consequences', ()),
                                                                      'result_bands')})
    bindings = value['recipe_bindings']
    _require(isinstance(bindings, (list, tuple)) and len(bindings) <= 24, 'luck_preparation.recipe_bindings_invalid')
    for binding in bindings:
        _fields(binding, 'recipe_binding', _BINDING_FIELDS)
        _reference(binding['recipe_ref'], 'recipe_binding.recipe_ref', 100)
        _require(isinstance(binding['slots'], Mapping) and len(binding['slots']) <= 4,
                 'luck_preparation.recipe_binding_invalid')
        _require(isinstance(binding['conditions'], Mapping) and isinstance(binding['clocks'], Mapping),
                 'luck_preparation.recipe_binding_invalid')
        _require(type(binding['hp_after_replacement']) is int, 'luck_preparation.recipe_binding_invalid')
    entries = value.get('remedy_entries', ())
    _require(isinstance(entries, (list, tuple)) and len(entries) <= 8, 'luck_preparation.remedy_entries_invalid')
    for entry in entries:
        _fields(entry, 'remedy_entry', _ENTRY_FIELDS, {'result_requirements'} if value['schema']==CONDITION_SNAPSHOT_SCHEMA else set())
        requirements=entry.get('result_requirements',[])
        _require(isinstance(requirements,list) and len(requirements)<=8,'luck_preparation.result_condition_invalid')
        for requirement in requirements:
            _fields(requirement,'result_condition',{'band_ref','fact_ref','value'})
            _reference(requirement['band_ref'],'result_condition.band_ref')
            _reference(requirement['fact_ref'],'result_condition.fact_ref')
            _require(requirement['value'] is True,'luck_preparation.result_condition_invalid')
        for key in ('entry_ref', 'method_ref', 'chain_ref', 'target_ref', 'scene_ref', 'attribute_ref'):
            _reference(entry[key], f'remedy_entry.{key}')
        _references(entry['preconditions'], 'remedy_entry.preconditions', 1, 8)
        _references(entry['tools'], 'remedy_entry.tools', 0, 8)
        _integer(entry['difficulty'], 'remedy_entry.difficulty')
        _require(entry['expires'] in REMEDY_EXPIRY, 'luck_preparation.remedy_entry_expiry_invalid')
        _consequences_or_fail(entry['consequences'], 'remedy_entry')
    benefits = value.get('all_in_benefits', ())
    _require(isinstance(benefits, (list, tuple)) and len(benefits) in {0, 2}, 'luck_preparation.all_in_benefits_invalid')
    seen = set()
    for benefit in benefits:
        _fields(benefit, 'all_in_benefit', _BENEFIT_FIELDS)
        for key in sorted(_BENEFIT_FIELDS):
            _reference(benefit[key], f'all_in_benefit.{key}')
        _require(benefit['benefit_ref'] not in seen, 'luck_preparation.all_in_benefits_invalid')
        seen.add(benefit['benefit_ref'])
    # Two registered benefits are two distinct objects: the player chooses one of
    # them, so a pair pointing at one object is not a choice at all.
    _require(len({benefit['object_ref'] for benefit in benefits}) == len(benefits),
             'luck_preparation.all_in_benefits_invalid')
    _prepared_choices(value)
    return {**dict(value), 'result_bands': normalized_bands}


async def _fixed_artifact(bridge, snapshot):
    """Read the room-fixed artifact through the authorized bridge only."""
    _require(callable(getattr(bridge, 'read_authorized_artifact', None)), 'luck_preparation.artifact_unavailable')
    request = ArtifactSliceRequest(snapshot['operation_ref'], snapshot['artifact_ref'],
                                   snapshot['artifact_sha256'], 0, ARTIFACT_SLICE_LIMIT)
    value = await bridge.read_authorized_artifact(request)
    _require(getattr(value, 'artifact_ref', None) == snapshot['artifact_ref']
             and getattr(value, 'artifact_sha256', None) == snapshot['artifact_sha256']
             and getattr(value, 'offset', None) == 0, 'luck_preparation.artifact_slice_invalid')
    content = getattr(value, 'content', None)
    _require(isinstance(content, (bytes, bytearray)) and len(content) > 0, 'luck_preparation.artifact_slice_invalid')
    try:
        artifact = json.loads(bytes(content).decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise LuckPreparationError(f'luck_preparation.artifact_invalid: {exc}') from exc
    _require(isinstance(artifact, Mapping) and isinstance(artifact.get('schema'), str)
             and _digest_matches(artifact, 'artifact_sha256'), 'luck_preparation.artifact_invalid')
    _require(artifact['artifact_sha256'] == snapshot['artifact_sha256'], 'luck_preparation.artifact_mismatch')
    return artifact


def _component(artifact, key, digest_key, schema, path):
    value = artifact.get(key)
    _require(isinstance(value, Mapping) and value.get('schema') == schema, f'luck_preparation.{path}_missing')
    _require(_digest_matches(value, digest_key), f'luck_preparation.{path}_mismatch')
    return value


def _rule_definition(artifact, snapshot):
    definitions = artifact.get('resolution_rule_definitions')
    _require(isinstance(definitions, (list, tuple)) and definitions, 'luck_preparation.rule_definitions_missing')
    rule = snapshot['rule_definition']
    matches = [item for item in definitions if isinstance(item, Mapping)
               and item.get('resolution_rule_ref') == rule['resolution_rule_ref'] and _same(item, rule)]
    _require(len(matches) == 1, 'luck_preparation.rule_definition_unknown')
    return rule


def _offer(artifact, snapshot, rule):
    catalog = artifact.get('resolution_action_offers')
    _require(isinstance(catalog, Mapping) and isinstance(catalog.get('offers'), (list, tuple)),
             'luck_preparation.action_offers_missing')
    _require(_digest_matches(catalog, 'catalog_sha256'), 'luck_preparation.action_offer_catalog_mismatch')
    matches = [item for item in catalog['offers'] if isinstance(item, Mapping) and item.get('offer_ref') == snapshot['offer_ref']]
    _require(len(matches) == 1, 'luck_preparation.offer_unknown')
    offer = matches[0]
    _require(_digest_matches(offer, 'offer_sha256') and offer['offer_sha256'] == snapshot['offer_sha256'],
             'luck_preparation.offer_mismatch')
    bands = offer.get('result_bands')
    _require(isinstance(bands, (list, tuple)) and all(isinstance(band, Mapping) for band in bands),
             'luck_preparation.action_offers_missing')
    # Compare the normalized views only; the fixed artifact itself is untouched.
    _require(_same([_band_view(band) for band in bands],
                   [_band_view(band) for band in snapshot['result_bands']]),
             'luck_preparation.result_bands_mismatch')
    resolution = offer.get('resolution')
    _require(isinstance(resolution, Mapping)
             and resolution.get('resolution_rule_ref') == rule['resolution_rule_ref']
             and resolution.get('resolution_rule_definition_sha256') == rule['definition_sha256'],
             'luck_preparation.offer_rule_mismatch')
    return offer


_SEALING = (('risk', False), ('opposed', True), ('group_result', True), ('visible_inputs', False),
            ('remedy_chain', True), ('ordinary_k3', True))


def _seals(check):
    """Fields on which a frozen check policy has already closed the odds window."""
    sealed = {name for name, value in _SEALING if check[name] is value}
    if check['dice'] != 'standard_d20':
        sealed.add('dice')
    return sealed


def _binding_check_ok(declared, runtime):
    """The platform evaluates the declared K3 guard from committed event facts.

    Other authored exclusions remain mandatory; ordinary_k3 in the binding
    declares a conditional route, not evidence that its term was fulfilled.
    """
    return _same(declared['purpose'], runtime['purpose']) and _seals(declared) - {'ordinary_k3'} <= _seals(runtime)


def _binding(artifact, snapshot, offer):
    """Resolve the authored binding this action claims; never reads a path.

    The catalog is compiled into the fixed artifact, so an action the author did
    not bind can never reach a window, and the frozen check policy must be the
    one the binding declares.
    """
    # Imported here: the binding compiler reuses bind_rule_bands from this module.
    from .luck_action_bindings import LuckActionBindingContractError, binding_for_offer
    catalog = artifact.get('luck_action_bindings')
    if not isinstance(catalog, Mapping):
        raise LuckPreparationError('luck_preparation.luck_action_bindings_missing')
    try:
        entry = binding_for_offer(catalog, snapshot['offer_ref'], snapshot['offer_sha256'])
    except LuckActionBindingContractError as exc:
        raise LuckPreparationError(f'luck_preparation.binding_invalid: {exc.code}:{exc.path}') from exc
    if not _binding_check_ok(entry['check'], snapshot['state']['check']):
        raise LuckPreparationError('luck_preparation.check_binding_mismatch')
    _require(_same(entry['resolution_rule_ref'], offer['resolution']['resolution_rule_ref'])
             and _same(entry['resolution_rule_definition_sha256'],
                       offer['resolution']['resolution_rule_definition_sha256']),
             'luck_preparation.binding_invalid: rule')
    return entry


def _margin_band(rule, margin):
    matches = [band for band in rule['result_bands']
               if (band['margin_min'] is None or margin >= band['margin_min'])
               and (band['margin_max'] is None or margin <= band['margin_max'])]
    _require(len(matches) == 1, 'luck_preparation.rule_band_unresolved')
    return matches[0]


def _natural_band(rule, raw):
    key = '1' if raw['face'] == 1 else '20'
    ref = rule['natural_roll_overrides'][key]
    return next(band for band in rule['result_bands'] if band['band_ref'] == ref)


def _result_band(rule, rules, name):
    """Bind one fixed luck result name to the compiled rule band for it.

    Both declared ends of the fixed luck band must land on the same compiled
    band, so a rule that silently reshapes the margins is refused.
    """
    band = next(item for item in rules['results']['bands'] if item['result'] == name)
    points = [value for value in (band['minimum'], band['maximum']) if value is not None]
    resolved = {_margin_band(rule, point)['band_ref'] for point in points}
    _require(len(resolved) == 1, 'luck_preparation.result_bands_unresolved')
    return _margin_band(rule, points[0])


def bind_rule_bands(rule, rules, result_bands):
    """Prove the compiled D20 rule and the author bands agree on every result."""
    compiled = {band['band_ref']: band for band in rule['result_bands']}
    offered = {band['band_ref']: band for band in result_bands}
    _require(set(compiled) == set(offered), 'luck_preparation.result_bands_mismatch')
    for name in (band['result'] for band in rules['results']['bands']):
        # Every fixed luck result name must resolve to the compiled band of the
        # same success/failure family; a drifted pack fails closed here.
        expected = 'failure' if name in {'critical_failure', 'normal_failure'} else 'success'
        _require(_result_band(rule, rules, name)['outcome'] == expected, 'luck_preparation.result_bands_conflict')
    for ref, band in offered.items():
        _require((band['outcome'], band['degree']) == (compiled[ref]['outcome'], compiled[ref]['degree']),
                 'luck_preparation.result_bands_conflict')
    return compiled, offered


def _bindings(catalog, snapshot):
    recipes = {recipe['recipe_ref']: recipe for recipe in catalog['recipes']}
    provided = {}
    for binding in snapshot['recipe_bindings']:
        ref = binding['recipe_ref']
        _require(ref in recipes, 'luck_preparation.recipe_binding_invalid')
        _require(ref not in provided, 'luck_preparation.recipe_binding_duplicate')
        provided[ref] = binding
    return [(recipe, provided[recipe['recipe_ref']]) for recipe in catalog['recipes'] if recipe['recipe_ref'] in provided]


def _policy(rules, state):
    try:
        return prepare_mode_policy(rules, state)
    except LuckInterventionError as exc:
        raise LuckPreparationError(f'luck_preparation.state_invalid: {exc}') from exc


def _offerable(policy, entries, benefits):
    """Modes this action may register at all, before per-face legality.

    Leave-door needs a platform-confirmed reachable entry and all-in needs two
    pre-registered benefits; this entry point invents neither.
    """
    modes = []
    for item in policy['modes']:
        if item['mode'] == 'all_in':
            if len(benefits) == 2:
                modes.append(dict(item))
        elif item['mode'] != 'leave_door' or entries:
            modes.append(dict(item))
    return modes


def _all_in(rules, item, benefits):
    value = {'schema': ALL_IN_SCHEMA, 'mode': 'all_in', 'extra_echo': item['fee'], 'empty': False,
             'coin_waiver': False, 'reaction': False, 'benefits': [dict(benefit) for benefit in benefits],
             'benefit_choice_required': True, 'benefit_results': list(rules['all_in']['benefit_results']),
             'doom_results': list(rules['all_in']['doom_results']), 'doom_added': rules['all_in']['doom_added'],
             'exclusive_with_post_roll': True}
    value['all_in_sha256'] = canonical_fingerprint(value)
    return value


def _candidate(mode, item, raw, original, final, effects, *, recipe=None, remedy=None):
    return {'schema': CANDIDATE_SCHEMA, 'mode': mode, 'extra_echo': item['fee'], 'empty': item['empty'],
            'coin_waiver': item['coin_waiver'], 'reaction': item['reaction'], 'raw': dict(raw),
            'original_band': {'band_ref': original['band_ref'], 'outcome': original['outcome'],
                              'degree': original['degree'],
                              'effects_sha256': canonical_fingerprint(original['consequences'])},
            'final_band': {'band_ref': final['band_ref'], 'outcome': final['outcome'], 'degree': final['degree']},
            'effects': deepcopy(effects),
            'loss_effect_count': sum(1 for effect in effects if effect['kind'] in LOSS_KINDS),
            'recipe': recipe, 'remedy': remedy}


def _wire(candidate_ref, proposal):
    return {'candidate_ref': candidate_ref, 'mode': proposal['mode'], 'extra_echo': proposal['extra_echo'],
            'proposal': proposal, 'proposal_sha256': canonical_fingerprint(proposal)}


def _recipe_candidates(mode, item, bindings, raw, original, offered):
    candidates = []
    if not original['consequences']:
        # A band that declares no effect has nothing to replace, so swap and
        # protect stay unavailable instead of inventing an original cost.
        return candidates
    for recipe, binding in bindings:
        if mode not in recipe['modes']:
            continue
        try:
            replacement = prepare_replacement(recipe, slots=binding['slots'], original_effects=original['consequences'],
                                              conditions=binding['conditions'],
                                              hp_after_replacement=binding['hp_after_replacement'],
                                              clocks=binding['clocks'])
        except (LuckRecipeError, ResolutionActionOfferContractError) as exc:
            raise LuckPreparationError(f'luck_preparation.recipe_binding_invalid: {exc}') from exc
        if replacement is None:
            continue
        source = {'recipe_ref': recipe['recipe_ref'], 'recipe_sha256': recipe['recipe_sha256'],
                  'modes': list(recipe['modes']), 'slots': dict(binding['slots']),
                  'original_effect_index': replacement['original_effect_index'],
                  'original_effects_sha256': replacement['original_effects_sha256'],
                  'replacement_sha256': replacement['proposal_sha256']}
        proposal = _candidate(mode, item, raw, original, offered[original['band_ref']], replacement['effects'],
                              recipe=source)
        key = (mode, recipe['recipe_ref'], None)
        candidates.append((key, _wire(f'luck.face{raw["face"]:02}.{mode}.{recipe["recipe_ref"]}', proposal)))
    return candidates


def _leave_door_candidates(item, raw, original, entries):
    candidates = []
    for index, entry in enumerate(entries, 1):
        if any(requirement['band_ref']!=original['band_ref'] or not any(effect['kind']=='fact.set' and effect.get('fact_ref')==requirement['fact_ref'] and effect.get('value') is True for effect in original['consequences']) for requirement in entry.get('result_requirements',[])):
            continue
        # The original failure consequences still settle; the entry only keeps
        # the pre-existing remedy path open. An unsupported combination keeps
        # the original action available instead of inventing a consequence.
        effects = [*deepcopy(original['consequences']), *deepcopy(entry['consequences'])]
        if effects:
            try:
                _consequences(effects, 'luck_preparation.leave_door')
            except ResolutionActionOfferContractError:
                continue
        remedy = {'entry_ref': entry['entry_ref'], 'method_ref': entry['method_ref'], 'chain_ref': entry['chain_ref'],
                  'target_ref': entry['target_ref'], 'scene_ref': entry['scene_ref'],
                  'preconditions': list(entry['preconditions']), 'attribute_ref': entry['attribute_ref'],
                  'difficulty': entry['difficulty'], 'tools': list(entry['tools']), 'expires': entry['expires'],
                  'consumes_next_action': True, 'chain_disables_luck': True}
        proposal = _candidate('leave_door', item, raw, original, original, effects, remedy=remedy)
        key = ('leave_door', None, entry['entry_ref'])
        candidates.append((key, _wire(f'luck.face{raw["face"]:02}.leave_door.{index}', proposal)))
    return candidates


def _change_candidate(item, rules, rule, raw, original, offered):
    target = _result_band(rule, rules, 'success_with_cost')
    if target['band_ref'] == original['band_ref']:
        return None
    effects = deepcopy(offered[target['band_ref']]['consequences'])
    if not any(effect['kind'] in LOSS_KINDS for effect in effects):
        # The adopted band keeps no actual loss, so this action has no legal
        # change candidate at all.
        return None
    proposal = _candidate('change', item, raw, original, offered[target['band_ref']], effects)
    return (('change', None, None), _wire(f'luck.face{raw["face"]:02}.change', proposal))


def _legal_faces(*, rules, rating, rule, offered, policy, modes, bindings, entries, modifier, difficulty):
    """Every legal candidate of all twenty faces, keyed and never truncated."""
    faces = []
    for face in range(1, 21):
        raw = original_result(rules, face, modifier, difficulty)
        original = _margin_band(rule, raw['margin']) if face not in {1, 20} else _natural_band(rule, raw)
        _require(original['band_ref'] in offered, 'luck_preparation.result_bands_mismatch')
        band = offered[original['band_ref']]
        proposed = _candidate('original', {'fee': 0, 'empty': False, 'coin_waiver': False, 'reaction': False},
                              raw, band, band, band['consequences'])
        candidates = [(('original', None, None), _wire(f'luck.face{face:02}.original', proposed))]
        if policy['status'] == 'eligible' and window_contains(rules, rating, raw):
            for item in modes:
                mode = item['mode']
                # All-in is a pre-roll bet: it never becomes a window candidate.
                if mode == 'all_in' or not mode_for_result(rules, mode, rating, raw):
                    continue
                if mode in {'swap', 'protect'}:
                    candidates.extend(_recipe_candidates(mode, item, bindings, raw, band, offered))
                elif mode == 'leave_door':
                    candidates.extend(_leave_door_candidates(item, raw, band, entries))
                else:
                    candidate = _change_candidate(item, rules, rule, raw, band, offered)
                    if candidate is not None:
                        candidates.append(candidate)
        faces.append({'face': face, 'raw': raw,
                      'band': {'band_ref': band['band_ref'], 'outcome': band['outcome'], 'degree': band['degree'],
                               'public_label': band['public_label']},
                      'candidates': candidates})
    return faces


def _faces(legal_faces, chosen):
    """Project each face, keeping the free original first and the player's order."""
    order = None if chosen is None else {key: index for index, key in enumerate(chosen)}
    faces = []
    for value in legal_faces:
        candidates = value['candidates']
        if order is None:
            selected = candidates
        else:
            # The free original stays available on every face; the registered
            # options follow in the player's own order.
            original = [item for item in candidates if item[0][0] == 'original']
            registered = sorted([item for item in candidates if item[0] in order],
                                key=lambda item: order[item[0]])
            selected = original + registered
        faces.append({'face': value['face'], 'raw': value['raw'], 'band': value['band'],
                      'candidates': [entry for _, entry in selected],
                      'unprepared_candidate_count': len(candidates) - len(selected)})
    return faces


def _option_ref(key):
    return key[1] if key[0] in {'swap', 'protect'} else key[2] if key[0] == 'leave_door' else None


def _prepared_modes(modes, legal_keys, chosen):
    """Mode menu of the preview, or the player's registered plan when confirmed."""
    keys = set(legal_keys)
    lookup = {item['mode']: item for item in modes}
    if chosen is None:
        prepared = []
        for item in modes:
            if item['mode'] == 'all_in' or not any(key[0] == item['mode'] for key in keys):
                continue
            refs = sorted({_option_ref(key) for key in keys if key[0] == item['mode'] and _option_ref(key)})
            prepared.append({**item, 'option_refs': refs})
        return prepared
    prepared, seen = [], set()
    for key in chosen:
        mode = key[0]
        if mode in seen:
            continue
        seen.add(mode)
        prepared.append({**lookup[mode],
                         'option_refs': [item for item in (_option_ref(item) for item in chosen
                                                           if item[0] == mode) if item]})
    return prepared


def _selection(chosen):
    return {'state': 'preview' if chosen is None else 'confirmed',
            'acquisition_allowed': chosen is not None,
            'maximum_prepared_choices': MAXIMUM_PREPARED_CHOICES,
            'window_candidate_limit': WINDOW_CANDIDATE_LIMIT,
            'prepared_choices': [] if chosen is None else [dict(item) for item in chosen]}


async def prepare_luck_action(snapshot, bridge=None):
    """Return the twenty-face candidate plan for one frozen luck action.

    Without prepared_choices this is a preview of every legal option and the
    platform must not open a window from it. With prepared_choices the player has
    registered the options to window, each face keeps the free original plus
    those options, and a registered option without any legal candidate fails
    closed. The result is always an uncommitted proposal: the platform owns the
    seal, the reservation, the player's choice and the final transaction.

    An empty prepared_choices is a confirmation too: the player explicitly keeps
    the ordinary rules, so every face returns the free original only and the
    platform settles the original result without opening a window.
    """
    value = _snapshot(snapshot)
    chosen = _prepared_choices(value)
    # Empty is a real choice: confirmed, zero intervention options, no window.
    artifact = await _fixed_artifact(bridge, value)
    rules = _component(artifact, 'luck_intervention_rules', 'rules_sha256', INTERVENTION_RULES_IR, 'intervention_rules')
    catalog = _component(artifact, 'luck_recipe_catalog', 'catalog_sha256', RECIPE_CATALOG_IR, 'recipe_catalog')
    rule = _rule_definition(artifact, value)
    offer = _offer(artifact, value, rule)
    # Policy first: it freezes and validates the state, including the check map
    # the binding guard then compares against the authored declaration.
    policy = _policy(rules, value['state'])
    _binding(artifact, value, offer)
    bind_rule_bands(rule, rules, value['result_bands'])
    entries = list(value.get('remedy_entries', ()))
    benefits = list(value.get('all_in_benefits', ()))
    modes = _offerable(policy, entries, benefits) if policy['status'] == 'eligible' else []
    legal_faces = _legal_faces(rules=rules, rating=value['state']['rating'], rule=rule,
                               offered={band['band_ref']: band for band in value['result_bands']}, policy=policy,
                               modes=modes, bindings=_bindings(catalog, value), entries=entries,
                               modifier=value['modifier'], difficulty=value['difficulty'])
    legal_keys = {key for face in legal_faces for key, _ in face['candidates']}
    if chosen is not None:
        # A registered option this action cannot produce anywhere is a rejected
        # registration, never a silently dropped legal option.
        for item in chosen:
            _require((item['mode'], item['recipe_ref'], item['entry_ref']) in legal_keys,
                     'luck_preparation.prepared_choice_unavailable')
    keys = None if chosen is None else [(item['mode'], item['recipe_ref'], item['entry_ref']) for item in chosen]
    faces = _faces(legal_faces, keys)
    prepared = _prepared_modes(modes, legal_keys, keys)
    all_in = next((item for item in modes if item['mode'] == 'all_in'), None)
    result = {'schema': PROPOSAL_SCHEMA, 'committed': False, 'operation_ref': value['operation_ref'],
              'snapshot_sha256': value['snapshot_sha256'],
              'artifact': {'artifact_ref': value['artifact_ref'], 'artifact_sha256': value['artifact_sha256'],
                           'intervention_rules_sha256': rules['rules_sha256'],
                           'recipe_catalog_sha256': catalog['catalog_sha256'],
                           'resolution_rule_ref': rule['resolution_rule_ref'],
                           'resolution_rule_definition_sha256': rule['definition_sha256'],
                           'offer_ref': offer['offer_ref'], 'offer_sha256': offer['offer_sha256']},
              'selection': _selection(chosen), 'policy': deepcopy(policy), 'prepared_modes': prepared,
              'all_in': _all_in(rules, all_in, benefits) if all_in is not None else None,
              'maximum_extra_echo': max([item['fee'] for item in prepared]
                                        + ([all_in['fee']] if all_in is not None else []), default=0),
              'faces': faces}
    result['proposal_sha256'] = canonical_fingerprint(result)
    return result


__all__ = ['ALL_IN_SCHEMA', 'CANDIDATE_SCHEMA', 'FEATURE', 'INTERVENTION_RULES_IR', 'LuckPreparationError',
           'MAXIMUM_PREPARED_CHOICES', 'POST_ROLL_MODES', 'PROPOSAL_SCHEMA', 'RECIPE_CATALOG_IR',
           'SNAPSHOT_SCHEMA', 'WINDOW_CANDIDATE_LIMIT', 'bind_rule_bands', 'prepare_luck_action']
