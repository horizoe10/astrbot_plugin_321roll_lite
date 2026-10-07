"""Compile platform-validated world definitions into hosted D20 rules."""
from copy import deepcopy
from .default_rules import default_rules, fingerprint

FEATURE = 'rules.world_template/1.0.0'

def compile_world(world):
    if not isinstance(world,dict) or world.get('format')!='321roll.world-template/1':
        raise ValueError('world_rules.format_invalid')
    rules=default_rules();r=world['rules']
    rules.update(rule_ref='world.'+world['id'],version=str(world['revision']),
        attributes={a['id']:a['name'] for a in world['attributes']},
        templates={a['id']:{'label':a['name'],'attributes':deepcopy(a['attributes']),'skills':list(a['skills'])} for a in world['archetypes']},
        resources={a['id']:{'label':a['name'],'initial':a['initial'],'minimum':a['min'],'maximum':a['max']} for a in world['resources']},
        difficulties=dict(zip(('easy','standard','hard','exceptional'),r['difficulties'])),
        modifier={'source':'committed_actor_attribute','baseline':world['modifier']['baseline'],'divisor':world['modifier']['divisor'],
                  'formula':f"floor((attribute-{world['modifier']['baseline']})/{world['modifier']['divisor']})"},
        failure_costs={'setback':{},'harm':{r['failureResource']:-r['failureCost']} if r['failureCost'] else {}},
        recovery={'rest':{'cost':{r['restCostResource']:-r['restCost']} if r['restCost'] else {},
                         'effect':{r['restGainResource']:r['restGain']} if r['restGain'] else {},'requires_safe_scene':True}},
        resource_gains={'supplies_found':{'supplies':1} if any(a['id']=='supplies' for a in world['resources']) else {}},
        character_options={'attributes':{a['id']:{'min':a['min'],'max':a['max']} for a in world['attributes']},
            'budget':world['budget'],'skills':{a['id']:deepcopy(a) for a in world['skills']},'skill_slots':r['skillSlots'],
            'regions':[{'id':e['id'],'name':e['name']} for e in world['entries'] if e['kind']=='region' and e['public']]},
        items={a['id']:deepcopy(a) for a in world['items']},
        world_source={'id':world['id'],'revision':world['revision'],'title':world['title'],'sha256':fingerprint(world)},
        seat_limits={k:r[k] for k in ('seats','minPlayers','recommendedMin','recommendedMax')},
        action_mode=r['mode'])
    if 'inventory' in world:rules['inventory']=deepcopy(world['inventory'])
    if 'vitality' not in rules['resources']:rules['incapacitation']={**rules['incapacitation'],'resource':None}
    rules.pop('sha256',None);rules['sha256']=fingerprint(rules)
    return rules

def validate_rules(value):
    if value==default_rules():return value
    if (not isinstance(value,dict) or value.get('schema')!='se-default-rules/1.0.0'
            or value.get('sha256')!=fingerprint({k:v for k,v in value.items() if k!='sha256'})
            or not value.get('world_source') or value.get('check_policy')!='attribute-d20/1.0.0'
            or value.get('dice')!={'count':1,'sides':20,'owner':'platform'}):
        raise ValueError('world_rules.rules_invalid')
    return value

def character(rules, template_ref, display_name, description='', attributes=None, skills=None):
    rules=validate_rules(rules)
    if template_ref not in rules['templates'] and not (template_ref=='' and rules.get('character_options')):raise ValueError('quick_character.template_invalid')
    if not isinstance(display_name,str) or not 1<=len(display_name.strip())<=80 or not isinstance(description,str) or len(description)>1200:
        raise ValueError('quick_character.name_invalid')
    template=rules['templates'].get(template_ref,{'attributes':attributes,'skills':[]});options=rules.get('character_options')
    scores=template['attributes'] if attributes is None else attributes
    chosen=template.get('skills',[]) if skills is None else skills
    if options:
        if (not isinstance(scores,dict) or set(scores)!=set(rules['attributes'])
                or any(type(scores[k]) is not int or not b['min']<=scores[k]<=b['max'] for k,b in options['attributes'].items())
                or sum(scores.values())!=options['budget']):raise ValueError('quick_character.attributes_invalid')
        if (not isinstance(chosen,list) or any(not isinstance(s,str) or s not in options['skills'] for s in chosen)
                or len(chosen)!=len(set(chosen)) or len(chosen)>options['skill_slots']):raise ValueError('quick_character.skills_invalid')
    elif scores!=template['attributes'] or chosen:raise ValueError('quick_character.attributes_invalid')
    return {'schema':'se-quick-character-proposal/1.0.0','committed':False,
        'rule_ref':rules['rule_ref'],'rule_version':rules['version'],'rule_sha256':rules['sha256'],
        'template_ref':template_ref,'display_name':display_name.strip(),'description':description.strip(),
        'attributes':deepcopy(scores),'resources':{k:v['initial'] for k,v in rules['resources'].items()},
        **({'skills':list(chosen)} if options else {})}
