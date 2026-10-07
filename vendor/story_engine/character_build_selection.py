"""Versioned, deterministic constraints over resolved build identities."""
from collections.abc import Mapping, Sequence
import re


SCHEMA = 'se-character-build-selection-rules/1.0.0'


class SelectionRuleError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise SelectionRuleError(message)


def _plain(value):
    if isinstance(value, Mapping):return {key:_plain(item) for key,item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value,(str,bytes)):return [_plain(item) for item in value]
    return value


def validate_selection_rules(rules, catalogs):
    fields = {'schema', 'variants', 'prerequisites', 'required_skills'}
    equipment = isinstance(rules, Mapping) and rules.get('schema') == 'se-character-build-selection-rules/1.1.0'
    if equipment: fields |= {'equipment_kits', 'equipment_profiles'}
    _require(isinstance(rules, Mapping) and set(rules) == fields and rules['schema'] in {SCHEMA, 'se-character-build-selection-rules/1.1.0'}, 'selection rules schema or fields invalid')
    _require(all(isinstance(rules[key], Mapping) for key in ('variants', 'prerequisites', 'required_skills')), 'selection rule maps required')
    by_source = {}
    for catalog in catalogs:
        _require(isinstance(catalog,Mapping) and isinstance(catalog.get('candidates'),(list,tuple)), 'resolved candidate map required')
        for candidate in catalog['candidates']:
            _require(isinstance(candidate,Mapping) and isinstance(candidate.get('source_ref'),str) and isinstance(candidate.get('resolver_metadata'),Mapping), 'resolved candidate identity and metadata required')
            by_source.setdefault(candidate['source_ref'], []).append(candidate)
    def kind(ref, expected):
        _require(isinstance(ref, str) and ref in by_source and all(item['resolver_metadata'].get('ability_kind') == expected for item in by_source[ref]), 'selection rule source kind or identity invalid')
    for ref, variant in rules['variants'].items():
        kind(ref, 'talent')
        _require(isinstance(variant, Mapping) and set(variant) == {'parameter_ref', 'values'}, 'variant fields invalid')
        _require(isinstance(variant['parameter_ref'], str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:@-]{0,79}',variant['parameter_ref']), 'variant parameter invalid')
        values = variant['values']
        _require(isinstance(values, (list, tuple)) and 2 <= len(values) <= 8 and all(isinstance(value, str) and value in by_source and all(item['resolver_metadata'].get('metric_kind') == 'attribute' for item in by_source[value]) for value in values), 'variant values must reference real attributes')
        _require(len(set(values)) == len(values), 'duplicate variant value')
    for ref, dependencies in rules['prerequisites'].items():
        kind(ref, 'talent')
        _require(isinstance(dependencies, (list, tuple)) and 1 <= len(dependencies) <= 8 and all(isinstance(dep, str) for dep in dependencies), 'prerequisites invalid')
        _require(len(set(dependencies)) == len(dependencies) and ref not in dependencies, 'duplicate or self prerequisite')
        for dep in dependencies:
            kind(dep, 'talent')
            _require({item['resolver_metadata'].get('parent_specialization_ref') for item in by_source[dep]} == {item['resolver_metadata'].get('parent_specialization_ref') for item in by_source[ref]}, 'prerequisites cross specialization')
    visited=set()
    def visit(ref, path):
        _require(ref not in path, 'prerequisite cycle')
        if ref in visited:return
        for dep in rules['prerequisites'].get(ref, ()):
            visit(dep, path | {ref})
        visited.add(ref)
    for ref in rules['prerequisites']:
        visit(ref, set())
    for talent, skill in rules['required_skills'].items():
        kind(talent, 'talent');kind(skill, 'skill')
        _require(all(item['resolver_metadata'].get('signature') is False for item in by_source[skill]), 'required skill must use a derived slot')
        _require({item['resolver_metadata'].get('parent_specialization_ref') for item in by_source[skill]} == {item['resolver_metadata'].get('parent_specialization_ref') for item in by_source[talent]}, 'required skill crosses specialization')
    for catalog in catalogs:
        grouped = {}
        for item in catalog['candidates']:
            grouped.setdefault(item['source_ref'], []).append(item)
        for ref, candidates in grouped.items():
            variant = rules['variants'].get(ref)
            if variant is None:
                _require(len(candidates) == 1 and all('selection_parameters' not in item['resolver_metadata'] for item in candidates), 'undeclared duplicate source or parameter')
            else:
                parameters = [item['resolver_metadata'].get('selection_parameters') for item in candidates]
                _require(all(isinstance(item, Mapping) and set(item) == {variant['parameter_ref']} for item in parameters), 'variant parameter missing or unknown')
                values = [item[variant['parameter_ref']] for item in parameters]
                _require(len(values) == len(set(values)) and set(values) == set(variant['values']), 'variant family incomplete or duplicated')
    if equipment:
        from .character_build_equipment import validate_equipment_rules, BuildEquipmentError
        try: validate_equipment_rules(rules, by_source)
        except BuildEquipmentError as exc: raise SelectionRuleError(str(exc)) from None
    return _plain(rules)


def candidate_allowed(rules, source_ref, selected, *, skill_slots_remaining=None):
    if not rules:
        return True
    if not set(rules['prerequisites'].get(source_ref, ())) <= selected:
        return False
    if skill_slots_remaining is not None:
        required = {skill for talent, skill in rules['required_skills'].items() if talent in selected}
        if len(required - (selected | {source_ref})) > skill_slots_remaining:
            return False
    return True


def selected_parameters(recipe, answers):
    """Derive parameters from the frozen selection; never accept player fields."""
    parameters = {}
    for step in recipe['steps']:
        answer = answers.get(step['step_ref'], {})
        if answer.get('kind') != 'choice':
            continue
        match = next((item for item in step['candidates'] if item['selection_ref'] == answer['selection_ref']), None)
        _require(match is not None and match['source_ref'] == answer['source_ref'], 'selected source and token mismatch')
        value = match['resolver_metadata'].get('selection_parameters')
        if value:
            _require(match['source_ref'] not in parameters, 'same parameterized talent chosen twice')
            parameters[match['source_ref']] = _plain(value)
    return parameters
