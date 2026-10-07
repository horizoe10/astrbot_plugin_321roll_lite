"""Frozen audience-safe targets selected by the player, with code-point spans."""
from collections.abc import Mapping
import re

FEATURE = 'action.entity_refs/1.0.0'


def validate(action, references):
    if not isinstance(references,(list,tuple)) or len(references)>32:
        raise ValueError('hosted_turn.action_references_invalid')
    previous=0;result=[];description_budget=8000
    for ref in references:
        if (not isinstance(ref,Mapping) or set(ref)!={'entity_ref','kind','label','description','source_receipt_refs','start','end'}
            or not isinstance(ref['entity_ref'],str) or not re.fullmatch(r'entity\.[a-f0-9]{64}',ref['entity_ref'])
            or not isinstance(ref['kind'],str) or ref['kind'] not in {'person','place','item','quest','ability','status'}
            or type(ref['start']) is not int or type(ref['end']) is not int
            or not previous<=ref['start']<ref['end']<=len(action)
            or not isinstance(ref['label'],str) or action[ref['start']:ref['end']]!=ref['label']
            or not isinstance(ref['description'],str) or len(ref['description'])>4000
            or not isinstance(ref['source_receipt_refs'],(list,tuple)) or len(ref['source_receipt_refs'])>32
            or any(not isinstance(source,str) or not 1<=len(source)<=200 for source in ref['source_receipt_refs'])):
            raise ValueError('hosted_turn.action_references_invalid')
        previous=ref['end']
        description=ref['description'] if len(ref['description'])<=description_budget else ''
        description_budget-=len(description)
        result.append({**ref,'description':description})
    return result
