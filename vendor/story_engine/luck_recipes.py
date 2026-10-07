"""Finite authored cost replacements. No RNG, Model, state write or authority."""
from collections.abc import Mapping
from copy import deepcopy
from itertools import product
from .contracts.port import canonical_fingerprint
from .resolution_action_offer import _consequences, validate_personal_cost_sources, ResolutionActionOfferContractError

AUTHOR_SCHEMA='se-luck-recipe-definitions/1.0.0'
IR_SCHEMA='se-luck-recipe-catalog-ir/1.0.0'


class LuckRecipeError(ValueError):
    pass


def require(condition,message):
    if not condition:raise LuckRecipeError(message)


def instantiate(recipe,slots):
    require(isinstance(slots,Mapping) and set(slots)==set(recipe['slots']), 'recipe slot bindings incomplete')
    for key,definition in recipe['slots'].items():
        value=slots[key]
        require(isinstance(value,str) and value, 'recipe slot identity missing')
        if definition['kind']=='owned_item':require(value in definition['item_refs'], 'recipe item outside authored sources')
    def effect(value):
        result=deepcopy(value)
        for key,item in result.items():
            if isinstance(item,Mapping):
                require(set(item)=={'slot'} and isinstance(item['slot'],str) and item['slot'] in slots, 'unknown effect slot')
                expected='owned_item' if key=='item_ref' else 'public_nonterminal_clock' if key=='clock_ref' else None
                require(expected is not None and recipe['slots'][item['slot']]['kind']==expected, 'effect slot source kind mismatch')
                result[key]=slots[item['slot']]
        return result
    original=effect(recipe['original_cost']);replacement=[effect(x) for x in recipe['replacement']]
    _consequences([original],recipe['recipe_ref']+'.original')
    _consequences(replacement,recipe['recipe_ref']+'.replacement')
    return original,replacement


def compile_luck_recipes(document,inventory,resources):
    require(isinstance(document,Mapping) and set(document)=={'schema','recipes'} and document['schema']==AUTHOR_SCHEMA, 'unsupported luck recipe document')
    require(isinstance(document['recipes'],(list,tuple)) and 1<=len(document['recipes'])<=24, 'recipe count must be bounded')
    items={x['item_ref']:x for x in (inventory or {}).get('definitions',[])}
    definitions=[];seen=set()
    for value in document['recipes']:
        require(isinstance(value,Mapping) and set(value)=={'recipe_ref','label','modes','slots','original_cost','replacement','guards'}, 'recipe fields invalid')
        ref=value['recipe_ref']
        require(isinstance(ref,str) and 1<=len(ref)<=100 and ref not in seen, 'recipe identity missing or duplicate');seen.add(ref)
        require(isinstance(value['label'],str) and 1<=len(value['label'])<=240, 'recipe label invalid')
        require(isinstance(value['modes'],(list,tuple)) and value['modes'] and all(isinstance(mode,str) for mode in value['modes']) and len(set(value['modes']))==len(value['modes']) and set(value['modes'])<={'swap','protect'}, 'recipe only replaces one cost through swap/protect')
        slots=value['slots'];require(isinstance(slots,Mapping) and len(slots)<=4, 'recipe slots invalid')
        choices=[]
        for key,slot in slots.items():
            require(isinstance(key,str) and 1<=len(key)<=64 and isinstance(slot,Mapping), 'recipe slot invalid')
            if slot.get('kind')=='owned_item':
                require(set(slot)=={'kind','item_refs'} and isinstance(slot['item_refs'],(list,tuple)) and 1<=len(slot['item_refs'])<=8, 'item slot fields invalid')
                require(all(isinstance(ref,str) and ref in items for ref in slot['item_refs']) and len(set(slot['item_refs']))==len(slot['item_refs']), 'recipe references unknown or duplicate items')
                choices.append(list(slot['item_refs']))
            else:
                require(slot=={'kind':'public_nonterminal_clock'}, 'unsupported recipe slot or clock purpose')
                choices.append(['clock.binding.'+key])
        guards=value['guards'];require(isinstance(guards,(list,tuple)) and 1<=len(guards)<=8, 'explicit recipe guards required')
        for guard in guards:
            require(isinstance(guard,Mapping), 'recipe guard invalid')
            if guard.get('kind')=='confirmed_condition':
                require(set(guard)=={'kind','condition_ref'} and isinstance(guard['condition_ref'],str) and 1<=len(guard['condition_ref'])<=160, 'condition guard invalid')
            elif guard.get('kind')=='hp_survives':
                require(set(guard)=={'kind','amount'} and type(guard['amount']) is int and 1<=guard['amount']<=10, 'HP guard invalid')
            else:
                require(set(guard)=={'kind','slot','minimum_headroom'} and guard.get('kind')=='clock_headroom'
                        and isinstance(guard['slot'],str) and guard['slot'] in slots and slots[guard['slot']]['kind']=='public_nonterminal_clock'
                        and type(guard['minimum_headroom']) is int and guard['minimum_headroom']>=2, 'clock guard must preserve irreversible headroom')
        for values in product(*choices):
            bindings=dict(zip(slots,values,strict=True));original,replacement=instantiate(value,bindings)
            require(original['kind'] in {'actor.hp.damage','inventory.damage','inventory.break','inventory.consume','actor.scene.fact.set'}, 'recipe original cost has no supported consumer')
            semantic=lambda effect:{key:item for key,item in effect.items() if key!='public_label'}
            require(any(canonical_fingerprint(semantic(effect))!=canonical_fingerprint(semantic(original)) for effect in replacement), 'replacement cannot be a decorative copy')
            if 'protect' in value['modes']:
                require(original['kind'] in {'inventory.consume','inventory.break'}, 'protection must preserve an owned physical target')
                require(not any(x.get('item_ref')==original['item_ref'] for x in replacement), 'protection cannot destroy its protected target')
            for effects in ([original],replacement):
                validate_personal_cost_sources({'offers':[{'offer_ref':ref,'result_bands':[{'consequences':effects}]}]},inventory,resources)
        result=deepcopy(dict(value));result['recipe_sha256']=canonical_fingerprint(result);definitions.append(result)
    result={'schema':IR_SCHEMA,'recipes':definitions}
    result['catalog_sha256']=canonical_fingerprint(result)
    return result


def prepare_replacement(recipe, *, slots, original_effects, conditions, hp_after_replacement, clocks):
    """Prepare an exact result-band replacement using platform-frozen facts.

    An absent fact is unavailable, not a fact the model may improvise. Actual
    item ownership, materials and quotas remain platform preparation checks.
    """
    require(isinstance(original_effects,list) and 1<=len(original_effects)<=16 and all(isinstance(effect,Mapping) for effect in original_effects), 'original result effects invalid')
    require(isinstance(conditions,Mapping) and isinstance(clocks,Mapping), 'frozen guard inputs invalid')
    _consequences(original_effects,recipe['recipe_ref']+'.original-band')
    original,replacement=instantiate(recipe,slots)
    semantic=lambda effect:{k:v for k,v in effect.items() if k!='public_label'}
    matches=[i for i,effect in enumerate(original_effects) if canonical_fingerprint(semantic(effect))==canonical_fingerprint(semantic(original))]
    if len(matches)!=1:return None
    effects=deepcopy(original_effects);effects[matches[0]:matches[0]+1]=replacement
    for guard in recipe['guards']:
        if guard['kind']=='confirmed_condition':
            if conditions.get(guard['condition_ref']) is not True:return None
        elif guard['kind']=='hp_survives':
            if type(hp_after_replacement) is not int or hp_after_replacement<=0:return None
        else:
            ref=slots[guard['slot']];clock=clocks.get(ref)
            if (not isinstance(clock,Mapping) or clock.get('public') is not True or clock.get('terminal') is not False
                    or type(clock.get('current')) is not int or type(clock.get('maximum')) is not int or not 0<=clock['current']<clock['maximum']):return None
            headroom=clock['maximum']-clock['current']
            delta=sum(x['amount'] for x in effects if x['kind']=='clock.advance' and x['clock_ref']==ref)
            if headroom<guard['minimum_headroom'] or delta>=headroom:return None
    # Validate the merged band too: a replacement must not double-charge a
    # retained consequence or create two writes to the same declared target.
    try:
        _consequences(effects,recipe['recipe_ref']+'.prepared')
    except ResolutionActionOfferContractError as exc:
        # Both inputs are already valid. An unsupported combined target/count
        # leaves the original action available without inventing a candidate.
        if exc.code=='action_offer.consequences_invalid':return None
        raise
    result={'schema':'se-luck-replacement-proposal/1.0.0','committed':False,'recipe_ref':recipe['recipe_ref'],
            'recipe_sha256':recipe['recipe_sha256'],'original_effect_index':matches[0],
            'original_effects_sha256':canonical_fingerprint(original_effects),'slots':dict(slots),'effects':effects}
    result['proposal_sha256']=canonical_fingerprint(result)
    return result
