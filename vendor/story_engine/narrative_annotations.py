"""Optional narrative references over a frozen audience-safe entity catalog."""
from collections.abc import Mapping
import re

FEATURE='narrative.entity_refs/1.0.0'
UPDATE_FEATURE='narrative.entity_updates/1.0.0'
MODEL_CONTRACT='se-hosted-narrative-model-output/1.2.0'
UPDATE_MODEL_CONTRACT='se-hosted-narrative-model-output/1.3.0'
CATALOG_SCHEMA='se-narrative-entity-catalog/1.0.0'
UPDATE_CATALOG_SCHEMA='se-narrative-entity-catalog/1.1.0'
ACTION_FEATURE='narrative.npc_actions/1.0.0'
ACTION_CONTRACT='se-narrative-annotations/1.1.0'
ACTION_MODEL_CONTRACT='se-hosted-narrative-model-output/1.5.0'


def validate_catalog(value):
    if not isinstance(value,Mapping) or set(value)!={'schema','entities','scene_ref','goal_ref'} or value['schema'] not in (CATALOG_SCHEMA,UPDATE_CATALOG_SCHEMA) or not isinstance(value['entities'],(list,tuple)) or len(value['entities'])>64:
        raise ValueError('hosted_turn.entity_catalog_invalid')
    updates=value['schema']==UPDATE_CATALOG_SCHEMA
    known={}
    for item in value['entities']:
        if (not isinstance(item,Mapping) or set(item)!=({'entity_ref','kind','label','description','aliases','speaker_kind','source_receipt_refs'}|({'entity_version','context_ref'} if updates else set()))
            or not isinstance(item['entity_ref'],str) or not re.fullmatch(r'entity\.[a-f0-9]{64}',item['entity_ref']) or item['entity_ref'] in known
            or item['kind'] not in ('person','place','item','quest','ability','status')
            or not isinstance(item['label'],str) or not 1<=len(item['label'])<=240
            or not isinstance(item['description'],str) or len(item['description'])>800
            or item['speaker_kind'] not in (None,'npc','player')
            or not isinstance(item['aliases'],(list,tuple)) or len(item['aliases'])>8
            or any(not isinstance(alias,str) or not 1<=len(alias)<=240 for alias in item['aliases'])
            or not isinstance(item['source_receipt_refs'],(list,tuple)) or len(item['source_receipt_refs'])>32
            or any(not isinstance(ref,str) or not 1<=len(ref)<=200 for ref in item['source_receipt_refs'])):
            raise ValueError('hosted_turn.entity_catalog_invalid')
        if updates:
            if not isinstance(item['entity_version'],str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',item['entity_version']):raise ValueError('hosted_turn.entity_catalog_invalid')
            if item['speaker_kind']=='npc':
                if not isinstance(item['context_ref'],str) or not re.fullmatch(r'npc\.context\.[a-f0-9]{40}',item['context_ref']):raise ValueError('hosted_turn.entity_catalog_invalid')
            elif item['context_ref'] is not None:raise ValueError('hosted_turn.entity_catalog_invalid')
        known[item['entity_ref']]=item
    if any(ref is not None and (not isinstance(ref,str) or ref not in known) for ref in (value['scene_ref'],value['goal_ref'])):
        raise ValueError('hosted_turn.entity_catalog_invalid')
    return known


def expanded_entities(catalog,proposed=()):
    known=validate_catalog(catalog)
    for npc in proposed:
        target=npc['entity_ref'] or 'new.'+npc['npc_ref']
        before=known.get(target)
        aliases=list(dict.fromkeys(([before['label'],*before['aliases']] if before else [])+npc['aliases']))
        known[target]={'entity_ref':target,'kind':'person','label':npc['name'],'aliases':aliases,'speaker_kind':'npc'}
    return known


def normalize(paragraphs,annotations,catalog,proposed=(),*,allow_actions=False):
    known=expanded_entities(catalog,proposed)
    invalid_all=not isinstance(annotations,(list,tuple)) or len(annotations)>len(paragraphs)
    entries={};duplicates=set()
    for annotation in annotations if not invalid_all else []:
        if not isinstance(annotation,Mapping) or type(annotation.get('sequence')) is not int or not 1<=annotation['sequence']<=len(paragraphs):
            invalid_all=True;continue
        sequence=annotation['sequence']
        if sequence in entries:duplicates.add(sequence)
        entries[sequence]=annotation
    blocks=[]
    for sequence,text in enumerate(paragraphs,1):
        block={'kind':'paragraph','text':text,'references':[],'speaker':None,'reference_status':'none'}
        annotation=entries.get(sequence)
        if invalid_all or sequence in duplicates:
            block['reference_status']='unresolved';blocks.append(block);continue
        if annotation is None:
            blocks.append(block);continue
        try:
            kinds={'paragraph','npc_dialogue'}|({'npc_action'} if allow_actions else set())
            if set(annotation)!={'sequence','kind','speaker','mentions'} or annotation['kind'] not in kinds or not isinstance(annotation['mentions'],(list,tuple)) or len(annotation['mentions'])>32:
                raise ValueError
            previous=0;references=[]
            for mention in annotation['mentions']:
                if not isinstance(mention,Mapping) or set(mention)!={'entity_ref','label','start','end'}:raise ValueError
                entity=known.get(mention['entity_ref'])
                if (entity is None or type(mention['start']) is not int or type(mention['end']) is not int
                    or not previous<=mention['start']<mention['end']<=len(text)
                    or mention['label'] not in [entity['label'],*entity['aliases']]
                    or text[mention['start']:mention['end']]!=mention['label']):raise ValueError
                references.append({'schema':'321roll-narrative-entity-reference/1.0.0',**mention,'kind':entity['kind']})
                previous=mention['end']
            speaker=annotation['speaker']
            if speaker is not None:
                if not isinstance(speaker,Mapping) or set(speaker)!={'entity_ref','label'}:raise ValueError
                entity=known.get(speaker['entity_ref'])
                if entity is None or entity['speaker_kind']!='npc' or speaker['label'] not in [entity['label'],*entity['aliases']]:raise ValueError
                speaker={'schema':'321roll-narrative-speaker/1.0.0',**speaker,'kind':'person'}
            if (annotation['kind'] in {'npc_dialogue','npc_action'})!=(speaker is not None):raise ValueError
            block.update(kind=annotation['kind'],references=references,speaker=speaker,reference_status='resolved' if references or speaker else 'none')
        except (KeyError,TypeError,ValueError):
            # Reference failures never invent an identity or trigger another
            # model call. The structurally valid paragraph stays readable.
            block['reference_status']='unresolved'
        blocks.append(block)
    return blocks
