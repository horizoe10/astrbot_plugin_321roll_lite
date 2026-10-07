"""Compile the finite luck rules and interpret frozen numeric inputs.

This module never obtains randomness, holds resources, or commits an outcome.
Those operations belong to the platform. Author rule identities are bound to
the actual build and rating catalogs, rather than inferred from display names.
"""
from collections.abc import Mapping
from copy import deepcopy

from .contracts.port import canonical_fingerprint

AUTHOR_SCHEMA = 'se-luck-intervention-definitions/1.0.0'
IR_SCHEMA = 'se-luck-intervention-rules-ir/1.0.0'

# These are the supported semantics of this version, not arbitrary expressions
# evaluated from a Pack. Changing them requires an explicit contract revision.
RESULTS = {
    'natural_failure': 1, 'natural_success': 20,
    'bands': [
        {'result': 'critical_failure', 'minimum': None, 'maximum': -10},
        {'result': 'normal_failure', 'minimum': -9, 'maximum': -5},
        {'result': 'success_with_cost', 'minimum': -4, 'maximum': -1},
        {'result': 'full_success', 'minimum': 0, 'maximum': 9},
        {'result': 'critical_success', 'minimum': 10, 'maximum': None},
    ],
}
WINDOWS = {'1': [-5], '2': [-5, -4], '3': [-6, -5, -4], '4': [-6, -5, -4, -3]}
LIMITS = {'per_check': 1, 'per_scene': 1, 'chapter_by_initial_rating': {'1': 1, '2': 1, '3': 2, '4': 2},
          'fallback_completed_actions': 12, 'change_per_chapter': 1, 'empty_per_chapter': 1,
          'all_in_per_chapter': 1, 'window_seconds': 90, 'maximum_candidates_including_original': 5}
DOOM = {'maximum': 3, 'paid_surcharge_from': 1, 'restricted_from': 2,
        'restricted_modes': ['protect', 'change', 'all_in'], 'disabled_from': 3}
ECHO = {'initial': 4, 'maximum': 6, 'long_rest_floor': 2, 'shouchou_amount': 1, 'shouchou_per_chapter': 1}
EMPTY = {'talent': 'T07', 'echo_exact': 0, 'maximum_doom': 1, 'modes': ['swap', 'leave_door'], 'doom_added': 1}
ALL_IN = {'fee': 1, 'benefit_count': 2, 'benefit_results': ['full_success', 'critical_success'],
          'doom_results': ['normal_failure', 'critical_failure'], 'doom_added': 1}
EVENT_MODIFIER = {'attribute_offset': 5, 'divisor': 3, 'minimum': -2, 'maximum': 5,
                  'usable_tool_bonus': 1, 'maximum_tools': 1}
# Registered check purposes and the subset that may open an odds window. The
# authored binding catalog and the offer compiler both read these, so the
# vocabulary has exactly one definition.
PURPOSES = frozenset({
    'investigation', 'craft', 'movement', 'escape', 'negotiation', 'environment', 'attack',
    'disaster_trigger', 'world_finale', 'death', 'resurrection', 'permanent_fate',
    'vote', 'consent', 'permission', 'hidden_truth', 'loot', 'paid_lottery', 'unlimited_cash'})
GAMBLABLE_STAKES = frozenset({'investigation', 'craft', 'movement', 'escape', 'negotiation', 'environment', 'attack'})
MODE_RULES = {
    'swap': {'skill': 'K1', 'talents': ['T01'], 'fee': 1, 'reaction': True, 'results': ['normal_failure', 'success_with_cost'], 'target_result': None, 'margin_exact': None},
    'protect': {'skill': 'K1', 'talents': ['T01', 'T03'], 'fee': 2, 'reaction': True, 'results': ['normal_failure', 'success_with_cost'], 'target_result': None, 'margin_exact': None},
    'leave_door': {'skill': 'K4', 'talents': ['T01'], 'fee': 2, 'reaction': False, 'results': ['normal_failure'], 'target_result': None, 'margin_exact': None},
    'change': {'skill': 'K3', 'talents': ['T01', 'T04'], 'fee': 3, 'reaction': False, 'results': ['normal_failure'], 'target_result': 'success_with_cost', 'margin_exact': -5},
}
FIXED_SECTIONS = {'results': RESULTS, 'windows': WINDOWS, 'limits': LIMITS, 'doom': DOOM,
                  'echo': ECHO, 'empty': EMPTY, 'all_in': ALL_IN, 'event_modifier': EVENT_MODIFIER, 'modes': MODE_RULES}


class LuckInterventionError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise LuckInterventionError(message)


def _same(left, right):
    # Python considers True == 1; the wire contract deliberately does not.
    return canonical_fingerprint(left) == canonical_fingerprint(right)


def compile_luck_intervention(document, rating, build):
    _require(isinstance(document, Mapping) and set(document) == {'schema', 'sources', *FIXED_SECTIONS}, 'luck intervention fields invalid')
    _require(document['schema'] == AUTHOR_SCHEMA, 'unsupported luck intervention version')
    _require(isinstance(rating, Mapping) and rating.get('schema') == 'se-luck-rating-rules-ir/1.0.0', 'compiled luck rating required')
    _require(isinstance(build, Mapping), 'compiled character build required')
    for key, expected in FIXED_SECTIONS.items():
        _require(_same(document[key], expected), f'unsupported luck {key} semantics')
    sources = document['sources']
    _require(isinstance(sources, Mapping) and set(sources) == {'talents', 'skills'}, 'luck source groups invalid')
    _require(isinstance(sources['talents'], Mapping) and set(sources['talents']) == {f'T{i:02}' for i in range(1, 11)}, 'ten distinct talent sources required')
    _require(isinstance(sources['skills'], Mapping) and set(sources['skills']) == {f'K{i}' for i in range(1, 6)}, 'five existing specialization skill sources required')
    candidates = {}
    for recipe in build['recipes']:
        for step in recipe['steps']:
            for candidate in step.get('candidates', ()):
                candidates.setdefault(candidate['source_ref'], []).append(candidate)
    for group, kind in (('talents', 'talent'), ('skills', 'skill')):
        refs = list(sources[group].values())
        _require(all(isinstance(ref, str) and ref for ref in refs) and len(set(refs)) == len(refs), 'luck sources must be distinct identities')
        for ref in refs:
            _require(ref in candidates and all(c['resolver_metadata'].get('ability_kind') == kind and c['resolver_metadata'].get('parent_specialization_ref') == rating['eligibility']['specialization_ref'] for c in candidates[ref]), f'unknown or foreign luck {kind} source: {ref}')
    talents, skills = sources['talents'], sources['skills']
    _require(talents['T01'] == rating['eligibility']['talent_ref'], 'luck T01 differs from rating eligibility')
    for recipe in build['recipes']:
        offered = {c['source_ref'] for s in recipe['steps'] for c in s.get('candidates', ())}
        if talents['T01'] not in offered:
            continue
        rules = recipe.get('selection_rules', {})
        prerequisites = rules.get('prerequisites', {})
        for logical in ('T03', 'T04', 'T07'):
            _require(prerequisites.get(talents[logical]) == [talents['T01']], 'luck dependency differs from build selection')
        _require(rules.get('required_skills', {}).get(talents['T04']) == skills['K3'], 'change requires the actual learned K3 in build selection')
        # Build compilation validates cycles globally; retain an explicit check
        # for callers supplying compiled-shaped data at this entry point.
        def visit(ref, stack):
            _require(ref not in stack, 'cyclic luck talent prerequisite')
            for parent in prerequisites.get(ref, ()):
                visit(parent, stack | {ref})
        for ref in talents.values():
            visit(ref, set())
    result = deepcopy(dict(document))
    result.update(schema=IR_SCHEMA, rating_rules_sha256=rating['rules_sha256'])
    result['rules_sha256'] = canonical_fingerprint(result)
    return result


def original_result(rules, face, modifier, difficulty):
    """Interpret an already sealed D20; natural results always take priority."""
    _require(type(face) is int and 1 <= face <= 20, 'sealed face must be an integer D20 result')
    _require(type(modifier) is int and type(difficulty) is int, 'frozen modifier and DC must be known integers')
    total, margin = face + modifier, face + modifier - difficulty
    if face == rules['results']['natural_failure']:
        result = 'critical_failure'
    elif face == rules['results']['natural_success']:
        result = 'critical_success'
    else:
        result = next(band['result'] for band in rules['results']['bands']
                      if (band['minimum'] is None or margin >= band['minimum']) and (band['maximum'] is None or margin <= band['maximum']))
    return {'face': face, 'modifier': modifier, 'difficulty': difficulty, 'total': total, 'margin': margin, 'result': result}


def window_contains(rules, rating, raw):
    _require(type(rating) is int and 1 <= rating <= 4, 'frozen rating invalid')
    return raw['result'] in {'normal_failure', 'success_with_cost'} and raw['face'] not in {1, 20} and raw['margin'] in rules['windows'][str(rating)]


def mode_for_result(rules, mode, rating, raw):
    _require(mode in rules['modes'], 'unknown post-roll mode')
    policy = rules['modes'][mode]
    return window_contains(rules, rating, raw) and raw['result'] in policy['results'] and (policy['margin_exact'] is None or raw['margin'] == policy['margin_exact'])


def intervention_fee(rules, mode, doom, *, empty=False, waive_surcharge=False):
    """Return a numeric fee or None when doom excludes this prepared mode.

    Empty/waiver eligibility and actual device charge ownership are checked by
    the preparation consumer before calling this numeric interpreter.
    """
    _require(mode in {*rules['modes'], 'all_in'}, 'unknown paid luck mode')
    _require(type(doom) is int and 0 <= doom <= rules['doom']['maximum'], 'frozen doom invalid')
    _require(type(empty) is bool and type(waive_surcharge) is bool, 'fee flags must be boolean')
    _require(not waive_surcharge or mode == 'swap' and not empty, 'coin only waives paid swap surcharge')
    if doom >= rules['doom']['disabled_from'] or doom >= rules['doom']['restricted_from'] and mode in rules['doom']['restricted_modes']:
        return None
    if empty:
        return 0 if mode in rules['empty']['modes'] and doom <= rules['empty']['maximum_doom'] else None
    base = rules['all_in']['fee'] if mode == 'all_in' else rules['modes'][mode]['fee']
    return base + int(doom >= rules['doom']['paid_surcharge_from'] and not waive_surcharge)


def event_modifier(rules, effective_attribute, *, usable_tool=False):
    _require(type(effective_attribute) is int and 0 <= effective_attribute <= 20 and type(usable_tool) is bool, 'event attribute or tool state invalid')
    policy = rules['event_modifier']
    return (effective_attribute - policy['attribute_offset']) // policy['divisor'] + (policy['usable_tool_bonus'] if usable_tool else 0)


def echo_after_long_rest(rules, current):
    _require(type(current) is int and 0 <= current <= rules['echo']['maximum'], 'actual echo balance invalid')
    return min(rules['echo']['maximum'], max(current, rules['echo']['long_rest_floor']))


def prepare_mode_policy(rules, state):
    """Filter learned modes and their affordable fees before any random draw.

    This is a rule-policy result, not a window or a reservation. The platform
    must intersect it with compiled, usable consequence recipes and register
    the chosen plan. In particular, this function cannot invent a remedy,
    replacement cost, all-in benefit, or item instance.
    """
    fields = {'eligible', 'rating', 'talent_refs', 'skill_refs', 'check', 'quota',
              'echo_current', 'echo_available', 'original_echo_cost', 'doom',
              'sealed', 'reaction_available', 'coin_waiver_available'}
    _require(isinstance(state, Mapping) and set(state) == fields, 'luck preparation state fields invalid')
    for key in ('eligible', 'sealed', 'reaction_available', 'coin_waiver_available'):
        _require(type(state[key]) is bool, f'unknown luck state: {key}')
    for key in ('echo_current', 'echo_available', 'original_echo_cost'):
        _require(type(state[key]) is int and 0 <= state[key] <= rules['echo']['maximum'], f'unknown echo input: {key}')
    _require(state['echo_available'] <= state['echo_current'], 'available echo exceeds current balance')
    _require(type(state['doom']) is int and 0 <= state['doom'] <= rules['doom']['maximum'], 'unknown doom state')
    for key in ('talent_refs', 'skill_refs'):
        value = state[key]
        _require(isinstance(value, (list, tuple)) and all(isinstance(ref, str) and ref for ref in value) and len(set(value)) == len(value), 'actual learned source identities invalid')
    quota = state['quota']
    _require(isinstance(quota, Mapping) and set(quota) == {'chapter_remaining', 'scene_remaining', 'change_remaining', 'empty_remaining', 'all_in_remaining'}, 'frozen quota fields invalid')
    for key, value in quota.items():
        _require(type(value) is int and 0 <= value <= (2 if key == 'chapter_remaining' else 1), 'unknown or invalid remaining quota')
    check = state['check']
    _require(isinstance(check, Mapping) and set(check) == {'dice', 'purpose', 'risk', 'opposed', 'group_result', 'visible_inputs', 'remedy_chain', 'ordinary_k3'}, 'luck check fields invalid')
    for key in ('risk', 'opposed', 'group_result', 'visible_inputs', 'remedy_chain', 'ordinary_k3'):
        _require(type(check[key]) is bool, f'unknown check condition: {key}')
    _require(check['dice'] in {'standard_d20', 'advantage', 'disadvantage', 'multiple', 'automatic'}, 'unknown dice contract')
    _require(check['purpose'] in PURPOSES, 'unknown check purpose')
    talents, skills = rules['sources']['talents'], rules['sources']['skills']

    def unavailable(reason):
        return {'status': 'unavailable', 'reason': reason, 'modes': [], 'maximum_extra_echo': 0}

    if not state['eligible']:
        _require(state['rating'] is None, 'ineligible rating must be not applicable')
        return {'status': 'not_applicable', 'reason': 'missing_eligibility', 'modes': [], 'maximum_extra_echo': 0}
    _require(type(state['rating']) is int and 1 <= state['rating'] <= 4 and talents['T01'] in state['talent_refs'], 'eligible rating or T01 source missing')
    if check['dice'] != 'standard_d20' or check['opposed'] or check['group_result']:
        return unavailable('excluded_check')
    if check['purpose'] not in GAMBLABLE_STAKES:
        return unavailable('excluded_stakes')
    if not check['risk'] or check['remedy_chain']:
        return unavailable('no_new_risk_opportunity')
    if not check['visible_inputs']:
        return unavailable('protected_resolution_inputs')
    if check['ordinary_k3']:
        return unavailable('ordinary_skill_variant')
    if state['sealed']:
        return unavailable('fortune_sealed')
    if state['doom'] >= rules['doom']['disabled_from']:
        return unavailable('doom_disabled')
    if state['echo_available'] < state['original_echo_cost']:
        return unavailable('original_cost_unaffordable')
    available = state['echo_available'] - state['original_echo_cost']
    modes = []
    # All-in has its own quota and does not consume the K1 reaction. It remains
    # independent when the scene's post-roll intervention was already used.
    if quota['all_in_remaining'] and skills['K3'] in state['skill_refs']:
        fee = intervention_fee(rules, 'all_in', state['doom'])
        if fee is not None and fee <= available:
            modes.append({'mode': 'all_in', 'fee': fee, 'empty': False, 'coin_waiver': False, 'reaction': False})
    if quota['scene_remaining'] and quota['chapter_remaining']:
        for mode, policy in rules['modes'].items():
            if skills[policy['skill']] not in state['skill_refs'] or not {talents[t] for t in policy['talents']} <= set(state['talent_refs']):
                continue
            # Swap and protect answer inside K1's own odds window and spend this
            # round's one reaction permission. Change (K3) and leave-door (K4)
            # do not consume a reaction, so a used-up reaction must not disable
            # those independent modes.
            if policy['reaction'] and not state['reaction_available']:
                continue
            if mode == 'change' and not quota['change_remaining']:
                continue
            empty = state['echo_current'] == 0 and talents['T07'] in state['talent_refs'] and bool(quota['empty_remaining'])
            waiver = mode == 'swap' and state['coin_waiver_available'] and state['doom'] > 0 and not empty
            fee = intervention_fee(rules, mode, state['doom'], empty=empty, waive_surcharge=waiver)
            if fee is not None and fee <= available:
                modes.append({'mode': mode, 'fee': fee, 'empty': empty, 'coin_waiver': waiver, 'reaction': policy['reaction']})
    return {'status': 'eligible' if modes else 'unavailable', 'reason': None if modes else 'no_affordable_learned_mode',
            'modes': modes, 'maximum_extra_echo': max((mode['fee'] for mode in modes), default=0)}
