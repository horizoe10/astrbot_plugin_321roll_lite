"""Deterministic, source-bound luck rating; no random draw or narrative calls."""
from collections.abc import Mapping
from .contracts.port import canonical_fingerprint

AUTHOR_SCHEMA = 'se-luck-rating-definitions/1.0.0'
IR_SCHEMA = 'se-luck-rating-rules-ir/1.0.0'


class LuckRatingError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise LuckRatingError(message)


def compile_luck_rating(document, build, inventory, resources):
    require(isinstance(document, Mapping) and set(document) == {'schema', 'eligibility', 'formula', 'device_bonuses'}, 'luck rating fields invalid')
    require(document['schema'] == AUTHOR_SCHEMA, 'unsupported luck rating version')
    require(build is not None and inventory is not None and resources is not None, 'luck rating requires build, inventory and resources')
    eligibility = document['eligibility']
    require(isinstance(eligibility, Mapping) and set(eligibility) == {'profession_ref', 'specialization_ref', 'talent_ref', 'resource_ref', 'anchor_parameter_ref'}, 'luck eligibility fields invalid')
    require(all(isinstance(v, str) and v for v in eligibility.values()), 'luck eligibility identity missing')
    formula = document['formula']
    require(isinstance(formula, Mapping) and set(formula) == {'charisma_ref', 'anchor_refs', 'divisor', 'minimum', 'maximum'}, 'luck formula fields invalid')
    require(all(type(formula[key]) is int for key in ('divisor', 'minimum', 'maximum')) and (formula['divisor'], formula['minimum'], formula['maximum']) == (8, 1, 4), 'luck rating formula must be clamp(floor((C+A)/8)+E,1,4)')
    require(isinstance(formula['anchor_refs'], (list, tuple)) and len(formula['anchor_refs']) == 2 and all(isinstance(x,str) for x in formula['anchor_refs']) and len(set(formula['anchor_refs'])) == 2, 'luck requires two distinct attribute anchors')
    candidates = {}
    for recipe in build['recipes']:
        for step in recipe['steps']:
            for candidate in step.get('candidates', ()):
                candidates.setdefault(candidate['source_ref'], []).append(candidate)
    for ref in [formula['charisma_ref'], *formula['anchor_refs']]:
        require(isinstance(ref,str) and ref in candidates and all(c['resolver_metadata'].get('metric_kind')=='attribute' for c in candidates[ref]), 'luck formula attribute reference unknown')
    profession, specialization, talent = (eligibility[key] for key in ('profession_ref','specialization_ref','talent_ref'))
    require(profession in candidates and all(c['resolver_metadata'].get('profession_ref')==profession for c in candidates[profession]), 'luck profession unknown')
    require(specialization in candidates and all(c['resolver_metadata'].get('parent_profession_ref')==profession for c in candidates[specialization]), 'luck specialization does not belong to profession')
    require(talent in candidates and all(c['resolver_metadata'].get('ability_kind')=='talent' and c['resolver_metadata'].get('parent_specialization_ref')==specialization for c in candidates[talent]), 'luck talent does not belong to specialization')
    matching=[recipe['selection_rules']['variants'].get(talent) for recipe in build['recipes'] if talent in recipe.get('selection_rules',{}).get('variants',{})]
    require(matching and all(v['parameter_ref']==eligibility['anchor_parameter_ref'] and set(v['values'])==set(formula['anchor_refs']) for v in matching), 'luck anchor declaration does not match talent variants')
    require(eligibility['resource_ref'] in {d['resource_id'] for d in resources['definitions']}, 'luck resource is not defined')
    bonuses=document['device_bonuses']
    require(isinstance(bonuses,Mapping) and bonuses, 'luck device sources required')
    definitions={d['item_ref']:d for d in inventory['definitions']}
    for ref,bonus in bonuses.items():
        require(ref in definitions and type(bonus) is int and bonus in {0,1}, 'luck device identity or modifier invalid')
        item=definitions[ref]
        require(item['stack_policy']=='unique' and type(item['instance_template']['durability_max']) is int and item['instance_template']['durability_max']>0, 'luck device must be a unique tracked physical item')
        require(ref in inventory.get('instance_attributes',{}), 'luck device carrying unit mapping missing')
    devices={ref:{'bonus':bonus,'definition_sha256':definitions[ref]['definition_sha256'],'durability_max':definitions[ref]['instance_template']['durability_max']} for ref,bonus in bonuses.items()}
    result={'schema':IR_SCHEMA,'eligibility':dict(eligibility),'formula':{**formula,'anchor_refs':list(formula['anchor_refs'])},'devices':devices}
    result['rules_sha256']=canonical_fingerprint(result)
    return result


def rating_from_values(charisma, anchor, equipment_bonus):
    require(type(charisma) is int and 0<=charisma<=20 and type(anchor) is int and 0<=anchor<=20, 'effective attributes must be known integers from 0 to 20')
    require(type(equipment_bonus) is int and equipment_bonus in {0,1}, 'one valid bound device contributes zero or one')
    return min(4,max(1,(charisma+anchor)//8+equipment_bonus))
