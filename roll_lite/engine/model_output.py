"""Structured response shapes shared by Provider adapters and routing."""
from typing import Any
from copy import deepcopy

_NARRATIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "narrative_document": {
            "type": "object",
            "properties": {
                "blocks": {
                    "type": "array", "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {"text": {"type": "string", "minLength": 1}},
                        "required": ["text"], "additionalProperties": False,
                    },
                },
            },
            "required": ["blocks"], "additionalProperties": False,
        },
    },
    "required": ["narrative_document"],
    "additionalProperties": False,
}
_REF_SCHEMA = {"type": "string", "minLength": 1, "maxLength": 160}
_DIGEST_SCHEMA = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
_POST_RESOLUTION_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": [
        "blocks", "proposals", "option_copy", "used_fact_refs",
        "used_receipt_refs", "used_capability_refs", "warnings",
    ],
    "properties": {
        "blocks": {"type": "array", "minItems": 1, "maxItems": 8, "items": {
            "type": "object", "additionalProperties": False, "required": ["kind", "text"],
            "properties": {
                "kind": {"type": "string", "enum": ["paragraph", "dialogue", "heading", "aside"]},
                "text": {"type": "string", "minLength": 1, "maxLength": 360, "pattern": "^[^\\r\\n]+$"},
            },
        }},
        "proposals": {"type": "array", "maxItems": 0, "items": {"type": "string"}},
        "option_copy": {
            "type": "object", "additionalProperties": False, "required": ["status", "items"],
            "properties": {
                "status": {"type": "string", "enum": ["no_options", "frozen_options"]},
                "items": {"type": "array", "maxItems": 16, "items": {
                    "type": "object", "additionalProperties": False, "required": ["local_ref", "text"],
                    "properties": {"local_ref": _REF_SCHEMA, "text": {"type": "string", "minLength": 1, "maxLength": 80}},
                }},
            },
        },
        "used_fact_refs": {"type": "array", "uniqueItems": True, "items": _REF_SCHEMA},
        "used_receipt_refs": {"type": "array", "minItems": 1, "uniqueItems": True, "items": _REF_SCHEMA},
        "used_capability_refs": {"type": "array", "minItems": 2, "maxItems": 2, "uniqueItems": True, "items": {"type": "string", "enum": ["base.narrative", "narrative.structured_output"]}},
        "warnings": {"type": "array", "maxItems": 32, "items": {"type": "string", "minLength": 1, "maxLength": 240}},
    },
}
_STORY_EVOLUTION_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["items", "dependency_edges", "narrative_dependency_refs", "warnings", "unused_reason"],
    "properties": {
        "items": {"type": "array", "maxItems": 8, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["proposal_local_ref", "type", "priority", "audience", "source_refs", "depends_on", "payload"],
            "properties": {
                "proposal_local_ref": {"type": "string", "pattern": "^local\\.[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$"},
                "type": {"enum": ["static_anchor.suggest", "static_module.suggest", "character_reaction.suggest", "narrative_focus.suggest", "story_thread.open", "story_thread.transition", "local_truth.freeze", "evidence.extend", "future_direction.offer", "dynamic_scene.propose", "dynamic_actor.propose", "dynamic_graph_node.propose", "dynamic_graph_edge.propose"]},
                "priority": {"enum": ["P0", "P1"]},
                "audience": {"enum": ["public", "player", "player_specific", "host", "owner", "author_offline"]},
                "source_refs": {"type": "array", "minItems": 1, "uniqueItems": True, "items": _REF_SCHEMA},
                "depends_on": {"type": "array", "uniqueItems": True, "items": {"type": "string", "pattern": "^local\\.[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$"}},
                "payload": {"type": "object", "additionalProperties": False, "required": ["summary", "target_refs"], "properties": {"summary": {"type": "string", "minLength": 1, "maxLength": 4000}, "target_refs": {"type": "array", "uniqueItems": True, "items": _REF_SCHEMA}}},
            },
        }},
        "dependency_edges": {"type": "array", "maxItems": 64, "items": {"type": "object", "additionalProperties": False, "required": ["from_local_ref", "to_local_ref"], "properties": {"from_local_ref": {"type": "string", "pattern": "^local\\."}, "to_local_ref": {"type": "string", "pattern": "^local\\."}}}},
        "narrative_dependency_refs": {"type": "array", "uniqueItems": True, "items": {"type": "string", "pattern": "^local\\."}},
        "warnings": {"type": "array", "maxItems": 32, "items": {"type": "string", "minLength": 1, "maxLength": 240}},
        "unused_reason": {"type": ["string", "null"], "minLength": 1, "maxLength": 240},
    },
}


def _closed_object(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_STATIC_VISUAL_SCHEMA = _closed_object({
    'svg': {'type': 'string', 'minLength': 1, 'maxLength': 65536},
    'alt': {'type': 'string', 'minLength': 1, 'maxLength': 240},
})


_BRIEF_START_SCHEMA = _closed_object({
    "scene": _closed_object({"title": {"type": "string", "minLength": 1, "maxLength": 120},
                             "description": {"type": "string", "minLength": 1, "maxLength": 4000}}),
    "goal": {"type": "string", "minLength": 1, "maxLength": 1000},
    "npcs": {"type": "array", "minItems": 1, "maxItems": 6, "items": _closed_object({
        "name": {"type": "string", "minLength": 1, "maxLength": 80},
        "description": {"type": "string", "minLength": 1, "maxLength": 1000},
        "motivation": {"type": "string", "minLength": 1, "maxLength": 1000}})},
    "characters": {"type": "array", "minItems": 1, "maxItems": 12, "items": _closed_object({
        "member_ref": {"type": "string", "minLength": 1, "maxLength": 128},
        "display_name": {"type": "string", "minLength": 1, "maxLength": 80},
        "description": {"type": "string", "maxLength": 1200},
        "template_ref": {"type": "string", "minLength": 1, "maxLength": 128}})},
    "suggestions": {"type": "array", "minItems": 1, "maxItems": 4,
                    "items": {"type": "string", "minLength": 1, "maxLength": 300}},
})

CHAPTER_PLAN_SCHEMA = {'type':'array','minItems':1,'maxItems':8,'items':_closed_object({
    'title':{'type':'string','minLength':1,'maxLength':120},
    'summary':{'type':'string','minLength':1,'maxLength':1000},
    'completion_goal':{'type':'string','minLength':1,'maxLength':1000}})}
# Optional additive field. A frozen request that negotiates chapters requires it.
_BRIEF_START_SCHEMA['properties']['chapter_plan'] = CHAPTER_PLAN_SCHEMA
# Opening world (story.opening_world/1.0.0): additive; required only when the frozen request asks for it.
OPENING_WORLD_SCHEMA = _closed_object({
    'time_description': {'type': 'string', 'minLength': 1, 'maxLength': 200},
    'public_facts': {'type': 'array', 'minItems': 1, 'maxItems': 8, 'items': {'type': 'string', 'minLength': 1, 'maxLength': 300}},
    'clocks': {'type': 'array', 'minItems': 0, 'maxItems': 4, 'items': _closed_object({
        'title': {'type': 'string', 'minLength': 1, 'maxLength': 60},
        'segments': {'type': 'integer', 'minimum': 4, 'maximum': 8},
        'consequence': {'type': 'string', 'minLength': 1, 'maxLength': 300},
        'visibility': {'type': 'string', 'enum': ['public', 'party']}})},
    'permissions': {'type': 'array', 'minItems': 0, 'maxItems': 6, 'items': _closed_object({
        'npc': {'type': 'string', 'minLength': 1, 'maxLength': 80},
        'label': {'type': 'string', 'minLength': 1, 'maxLength': 60},
        'statement': {'type': 'string', 'minLength': 1, 'maxLength': 400},
        'scope': {'type': 'string', 'minLength': 1, 'maxLength': 200}})}})
_BRIEF_START_SCHEMA['properties']['opening_world'] = OPENING_WORLD_SCHEMA

_HOSTED_INTENT_SCHEMA = _closed_object({
    'kind':{'type':'string','enum':['narrative','check','recover','clarify','impossible']},
    'attribute_ref':{'type':'string','enum':['','strength','agility','endurance','perception','reason','will','presence','knowledge','craft']},
    'difficulty':{'type':'string','enum':['','easy','standard','hard','exceptional']},
    'failure_cost':{'type':'string','enum':['','setback','harm']},
    'reason':{'type':'string','minLength':1,'maxLength':1000},
    'clarification':{'type':'string','maxLength':500},
})
_HOSTED_INTENT_1_1_SCHEMA = _closed_object({**_HOSTED_INTENT_SCHEMA['properties'],
    'risk_response':{'type':'string','enum':['','intervention','evacuation','rescue']}})
_HOSTED_NARRATIVE_SCHEMA = _closed_object({
    'paragraphs':{'type':'array','minItems':1,'maxItems':8,'items':{'type':'string','minLength':1,'maxLength':1200}},
    'facts':{'type':'array','maxItems':8,'items':_closed_object({
        'kind':{'type':'string','enum':['world_fact','npc_statement','player_declaration','hypothesis']},
        'subject_ref':{'type':'string','minLength':1,'maxLength':96},
        'text':{'type':'string','minLength':1,'maxLength':1000}})},
    'npcs':{'type':'array','maxItems':4,'items':_closed_object({
        'npc_ref':{'type':'string','pattern':'^npc\\.[a-zA-Z0-9_.-]{1,80}$'},
        'name':{'type':'string','minLength':1,'maxLength':80},
        'description':{'type':'string','minLength':1,'maxLength':1000},
        'motivation':{'type':'string','minLength':1,'maxLength':1000}})},
    'suggestions':{'type':'array','minItems':1,'maxItems':4,'items':{'type':'string','minLength':1,'maxLength':300}},
})


_HOSTED_NARRATIVE_1_1_SCHEMA = _closed_object({**_HOSTED_NARRATIVE_SCHEMA['properties'],
    'progress':_closed_object({
        'scene':{'anyOf':[{'type':'object','properties':{
            'title':{'type':'string','minLength':1,'maxLength':120},
            'description':{'type':'string','minLength':1,'maxLength':4000}},
            'required':['title','description'],'additionalProperties':False},{'type':'null'}]},
        'goal':{'type':['string','null'],'minLength':1,'maxLength':1000}})})


_NARRATIVE_MENTION=_closed_object({
    'entity_ref':{'type':'string','pattern':r'^entity\.[a-f0-9]{64}$'},
    'label':{'type':'string','minLength':1,'maxLength':240},
    'start':{'type':'integer','minimum':0},'end':{'type':'integer','minimum':1}})
_NARRATIVE_SPEAKER=_closed_object({key:value for key,value in _NARRATIVE_MENTION['properties'].items() if key in {'entity_ref','label'}})
_HOSTED_NARRATIVE_1_2_SCHEMA=_closed_object({**_HOSTED_NARRATIVE_1_1_SCHEMA['properties'],
    'annotations':{'type':'array','maxItems':8,'items':_closed_object({
        'sequence':{'type':'integer','minimum':1,'maximum':8},
        'kind':{'type':'string','enum':['paragraph','npc_dialogue']},
        'speaker':{'anyOf':[_NARRATIVE_SPEAKER,{'type':'null'}]},
        'mentions':{'type':'array','maxItems':32,'items':_NARRATIVE_MENTION}})}})

_HOSTED_NARRATIVE_1_3_SCHEMA=deepcopy(_HOSTED_NARRATIVE_1_2_SCHEMA)
_HOSTED_NARRATIVE_1_3_SCHEMA['properties']['npcs']['items']=_closed_object({
    **_HOSTED_NARRATIVE_1_3_SCHEMA['properties']['npcs']['items']['properties'],
    'entity_ref':{'anyOf':[{'type':'string','pattern':r'^entity\.[a-f0-9]{64}$'},{'type':'null'}]},
    'aliases':{'type':'array','maxItems':8,'uniqueItems':True,'items':{'type':'string','minLength':1,'maxLength':80}}})
_updated_annotation=_HOSTED_NARRATIVE_1_3_SCHEMA['properties']['annotations']['items']['properties']
for _reference in (_updated_annotation['mentions']['items'],_updated_annotation['speaker']['anyOf'][0]):
    _reference['properties']['entity_ref']['pattern']=r'^(entity\.[a-f0-9]{64}|new\.npc\.[a-zA-Z0-9_.-]{1,80})$'


_POST_RESOLUTION_ENTITY_SCHEMA=deepcopy(_POST_RESOLUTION_SCHEMA)
_POST_RESOLUTION_ENTITY_SCHEMA['properties']['annotations']=deepcopy(_HOSTED_NARRATIVE_1_2_SCHEMA['properties']['annotations'])
_POST_RESOLUTION_ENTITY_SCHEMA['required'].append('annotations')


_ATTRIBUTE_SOURCES = {'type': 'array', 'maxItems': 16, 'uniqueItems': True,
                      'items': {'type': 'string', 'minLength': 1, 'maxLength': 240}}
_HOSTED_INTENT_1_2_SCHEMA = _closed_object({**_HOSTED_INTENT_1_1_SCHEMA['properties'],
    'attribute_reason': {'type': 'string', 'maxLength': 300},
    'attribute_source_refs': {**_ATTRIBUTE_SOURCES, 'items': {'type': 'string', 'minLength': 1, 'maxLength': 200}}})
_HOSTED_DECISION_SCHEMA = _closed_object({
    'schema': {'type': 'string', 'enum': ['se-hosted-decision-node/1.0.0']},
    'reason': {'type': 'string', 'minLength': 1, 'maxLength': 300},
    'candidates': {'type': 'array', 'minItems': 2, 'maxItems': 4, 'items': _closed_object({
        'text': {'type': 'string', 'minLength': 1, 'maxLength': 300},
        'rule': _closed_object({
            'kind': {'type': 'string', 'enum': ['narrative', 'check', 'recover']},
            'difficulty': deepcopy(_HOSTED_INTENT_SCHEMA['properties']['difficulty']),
            'failure_cost': {'type': 'string', 'enum': ['', 'setback', 'harm']}}),
        'source_fact_refs': {**_ATTRIBUTE_SOURCES, 'minItems': 1, 'maxItems': 8,
                             'items': {'type': 'string', 'minLength': 1, 'maxLength': 200}},
        'exit': {'type': 'boolean'}})}})
_HOSTED_NARRATIVE_1_4_SCHEMA = _closed_object({**_HOSTED_NARRATIVE_1_3_SCHEMA['properties'],
    'decision_node': {'anyOf': [_HOSTED_DECISION_SCHEMA, {'type': 'null'}]}})
_HOSTED_NARRATIVE_1_5_SCHEMA = deepcopy(_HOSTED_NARRATIVE_1_4_SCHEMA)
_HOSTED_NARRATIVE_1_5_SCHEMA['properties']['paragraphs']['maxItems']=16
_HOSTED_NARRATIVE_1_5_SCHEMA['properties']['paragraphs']['items']['maxLength']=1200
_HOSTED_NARRATIVE_1_5_SCHEMA['properties']['annotations']['maxItems']=16
_HOSTED_NARRATIVE_1_5_SCHEMA['properties']['annotations']['items']['properties']['sequence']['maximum']=16
_HOSTED_NARRATIVE_1_5_SCHEMA['properties']['annotations']['items']['properties']['kind']['enum'].append('npc_action')
_CHOICE_CHECKS_SCHEMA={'type':'array','minItems':1,'maxItems':4,'items':_closed_object({
    **deepcopy(_HOSTED_DECISION_SCHEMA['properties']['candidates']['items']['properties']['rule']['properties']),
    'attribute_ref':deepcopy(_HOSTED_INTENT_SCHEMA['properties']['attribute_ref'])})}
_HOSTED_NARRATIVE_1_6_SCHEMA=_closed_object({**deepcopy(_HOSTED_NARRATIVE_1_5_SCHEMA['properties']),'suggestion_checks':_CHOICE_CHECKS_SCHEMA})
_HOSTED_NARRATIVE_1_7_SCHEMA=_closed_object({
    **{k:deepcopy(v) for k,v in _HOSTED_NARRATIVE_1_6_SCHEMA['properties'].items() if k not in {'suggestions','suggestion_checks','decision_node'}},
    'choices':{'type':'array','minItems':1,'maxItems':4,'items':_closed_object({
        'text':{'type':'string','minLength':1,'maxLength':300},
        **deepcopy(_CHOICE_CHECKS_SCHEMA['items']['properties']),
        'source_fact_refs':{'type':'array','maxItems':8,'uniqueItems':True,'items':{'type':'string','minLength':1,'maxLength':200}},
        'exit':{'type':'boolean'}})},
    'decision_reason':{'anyOf':[{'type':'string','minLength':1,'maxLength':300},{'type':'null'}]}})
# D031-15 adds an optional contract; rc24 /1.7.0 is unchanged.
PLAY_HOOK_MODEL_CONTRACT = 'se-hosted-narrative-model-output/1.8.0'
_PLAY_HOOK_SCHEMA = _closed_object({
    'play': {'enum': ['playInvestigation','playTestimony','playNegotiation','playRelations','playCalendar','playProjects','playOutfitting','playConflict','playChase','playDebate','playPlans','playFlashback','playOracle','playTransformation','playPrivatePhases','playRegroup','playFortune','playBranchEndings']},
    'action': {'type':'string','pattern':r'^[a-z][a-z_]{0,63}$'},
    'target_ref': {'anyOf':[{'type':'string','pattern':r'^entity\.[a-f0-9]{64}$'},{'type':'null'}]},
    'reason': {'type':'string','maxLength':200},
    'fill': {'type':'object','maxProperties':8,'propertyNames':{'pattern':r'^[a-z][a-z_]{0,63}$'},'additionalProperties':{'type':'string','maxLength':400}}})
_HOSTED_NARRATIVE_1_8_SCHEMA = deepcopy(_HOSTED_NARRATIVE_1_7_SCHEMA)
_HOSTED_NARRATIVE_1_8_SCHEMA['properties']['play_hooks'] = {'type':'array','maxItems':4,'items':_PLAY_HOOK_SCHEMA}

_BRIEF_START_1_1_SCHEMA=_closed_object({**deepcopy(_BRIEF_START_SCHEMA['properties']),'suggestion_checks':deepcopy(_CHOICE_CHECKS_SCHEMA)})
_BRIEF_START_1_1_SCHEMA['required'].remove('chapter_plan')
_BRIEF_START_1_1_SCHEMA['required'].remove('opening_world')
_ORDERED_ANNOTATIONS_SCHEMA=deepcopy(_HOSTED_NARRATIVE_1_2_SCHEMA['properties']['annotations'])
_ORDERED_ANNOTATIONS_SCHEMA['maxItems']=16
_ORDERED_ANNOTATIONS_SCHEMA['items']['properties']['sequence']['maximum']=16
_ORDERED_ANNOTATIONS_SCHEMA['items']['properties']['kind']['enum'].append('npc_action')
_POST_RESOLUTION_ACTION_SCHEMA=deepcopy(_POST_RESOLUTION_ENTITY_SCHEMA)
_POST_RESOLUTION_ACTION_SCHEMA['properties']['annotations']=deepcopy(_ORDERED_ANNOTATIONS_SCHEMA)
_POST_RESOLUTION_ACTION_SCHEMA['properties']['blocks']['maxItems']=16
_POST_RESOLUTION_ACTION_SCHEMA['properties']['blocks']['items']['properties']['text']['maxLength']=1200
COLLECTIVE_EVENT_CONTRACT = 'se-hosted-collective-event-model-output/1.0.0'
_COLLECTIVE_EVENT_SCHEMA = _closed_object({
    'title': {'type': 'string', 'minLength': 1, 'maxLength': 80},
    'premise': {'type': 'string', 'minLength': 1, 'maxLength': 600},
    'directions': {'type': 'array', 'minItems': 2, 'maxItems': 3, 'items': _closed_object({
        'direction_ref': {'type': 'string', 'pattern': r'^[a-z0-9][a-z0-9._-]{0,63}$'},
        'label': {'type': 'string', 'minLength': 1, 'maxLength': 200, 'pattern': r'^[^\r\n]+$'},
        'description': {'type': 'string', 'minLength': 1, 'maxLength': 600},
        'risk': {'type': 'string', 'maxLength': 300, 'pattern': r'^[^\r\n]*$'},
        'cost': {'type': 'string', 'maxLength': 300, 'pattern': r'^[^\r\n]*$'}})}})
LEGACY_NARRATIVE_CONTRACT = 'se-turn-narrative-proposal/1.0.0'
BRIEF_START_CONTRACT = 'se-brief-start-model-output/1.0.0'
STATIC_VISUAL_CONTRACT = 'se-static-visual-model-output/1.0.0'

# This explicit catalog is also the routing/budget classification. Adding a
# current Engine output must not silently select an unrelated legacy document.
_MODEL_OUTPUT_SCHEMAS = {
    'se-timeout-ranking-model-output/1.0.0': _closed_object({'ranking': {'type':'array','minItems':1,'maxItems':4,'items':_closed_object({
        'choice_ref':{'type':'string','minLength':1,'maxLength':100},
        'risk':{'type':'integer','minimum':0,'maximum':100},
        'reason':{'type':'string','minLength':1,'maxLength':300}})}}),
    LEGACY_NARRATIVE_CONTRACT: _NARRATIVE_SCHEMA,
    BRIEF_START_CONTRACT: _BRIEF_START_SCHEMA,
    'se-brief-start-model-output/1.1.0': _BRIEF_START_1_1_SCHEMA,
    'se-post-resolution-model-output/1.0.0': _POST_RESOLUTION_SCHEMA,
    'se-post-resolution-model-output/1.1.0': _POST_RESOLUTION_ENTITY_SCHEMA,
    'se-post-resolution-model-output/1.2.0': _POST_RESOLUTION_ACTION_SCHEMA,
    'se-story-evolution-model-output/1.0.0': _STORY_EVOLUTION_SCHEMA,
    'se-hosted-intent-model-output/1.0.0': _HOSTED_INTENT_SCHEMA,
    'se-hosted-intent-model-output/1.1.0': _HOSTED_INTENT_1_1_SCHEMA,
    'se-hosted-intent-model-output/1.2.0': _HOSTED_INTENT_1_2_SCHEMA,
    'se-hosted-narrative-model-output/1.0.0': _HOSTED_NARRATIVE_SCHEMA,
    'se-hosted-narrative-model-output/1.1.0': _HOSTED_NARRATIVE_1_1_SCHEMA,
    'se-hosted-narrative-model-output/1.2.0': _HOSTED_NARRATIVE_1_2_SCHEMA,
    'se-hosted-narrative-model-output/1.3.0': _HOSTED_NARRATIVE_1_3_SCHEMA,
    'se-hosted-narrative-model-output/1.4.0': _HOSTED_NARRATIVE_1_4_SCHEMA,
    'se-hosted-narrative-model-output/1.5.0': _HOSTED_NARRATIVE_1_5_SCHEMA,
    'se-hosted-narrative-model-output/1.6.0': _HOSTED_NARRATIVE_1_6_SCHEMA,
    'se-hosted-narrative-model-output/1.7.0': _HOSTED_NARRATIVE_1_7_SCHEMA,
    PLAY_HOOK_MODEL_CONTRACT: _HOSTED_NARRATIVE_1_8_SCHEMA,
    COLLECTIVE_EVENT_CONTRACT: _COLLECTIVE_EVENT_SCHEMA,
    STATIC_VISUAL_CONTRACT: _STATIC_VISUAL_SCHEMA,
}
HOSTED_INTENT_CONTRACTS = frozenset(k for k in _MODEL_OUTPUT_SCHEMAS if k.startswith('se-hosted-intent-'))
HOSTED_NARRATIVE_CONTRACTS = frozenset(k for k in _MODEL_OUTPUT_SCHEMAS if k.startswith('se-hosted-narrative-'))
HOSTED_CONTRACTS = HOSTED_INTENT_CONTRACTS | HOSTED_NARRATIVE_CONTRACTS
COLLECTIVE_EVENT_CONTRACTS = frozenset({COLLECTIVE_EVENT_CONTRACT})
OPTIONAL_ANNOTATION_CONTRACTS = frozenset(k for k, v in _MODEL_OUTPUT_SCHEMAS.items() if 'annotations' in v['properties'])


def compact_hosted_context(context):
    """Authorized model-only projection; never modify the frozen platform state."""
    result=dict(context)
    result['facts']=[{k:v for k,v in fact.items() if k!='source_receipt_ref'} for fact in context['facts']]
    if 'entity_catalog' in context:
        catalog=context['entity_catalog']
        result['entity_catalog']={k:v for k,v in catalog.items() if k not in {'schema','entities'}}
        result['entity_catalog']['entities']=[{k:v for k,v in entity.items() if k not in {'entity_version','source_receipt_refs'}} for entity in catalog['entities']]
    return result


def model_output_schema(output_contract: str) -> dict[str, Any]:
    try:
        return _MODEL_OUTPUT_SCHEMAS[output_contract]
    except KeyError:
        raise ValueError('provider_output_contract_unsupported') from None

