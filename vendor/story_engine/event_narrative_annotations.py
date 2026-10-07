"""Explicit source-bound event prose; shared by compiler and event evaluator.

``se-authored-event-narrative/1.0.0`` stays byte-compatible with its frozen
contract and always carries the whole route text in a single block.
``se-authored-event-narrative/1.1.0`` compiles the same author route bodies
through ordered spans, so a route may emit several blocks whose concatenated
text still equals ``public_meaning`` verbatim.
"""
import hashlib,json
from collections.abc import Mapping
from .authored_narrative_annotations import (
    LEGACY_ANNOTATION_SCHEMA,SPAN_ANNOTATION_SCHEMA,compile_authored_annotations,
    compile_authored_blocks,validate_author_mentions,
)

LEGACY_SCHEMA='se-authored-event-narrative/1.0.0'
SCHEMA='se-authored-event-narrative/1.1.0'
DOCUMENT_SCHEMAS=frozenset({LEGACY_SCHEMA,SCHEMA})
STYLE_SCHEMA='se-narrative-style-candidate-runtime/1.3.0'
AUTHOR_DOCUMENT_SCHEMA='sp-event-narrative-annotations/1.1.0'
LEGACY_AUTHOR_DOCUMENT_SCHEMA='sp-event-narrative-annotations/1.0.0'

BLOCK_FIELDS=frozenset({'block_ref','order','locale','audience','source_ref','text','text_digest','kind','references','speaker','reference_status'})
REFERENCE_KINDS=frozenset({'person','place','quest','status'})
KINDS=frozenset({'paragraph','npc_dialogue','npc_action'})

def digest(value):
    return 'sha256:'+hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def text_digest(value):return 'sha256:'+hashlib.sha256(value.encode()).hexdigest()

def _legacy_annotation(opening,item,text):
    return compile_authored_annotations({'initial_state':opening['initial_state'],'prologue_story':{'body':text,'entity_annotations':item['entity_annotations']}},[text])


def compile_event_annotations(opening,locale,opening_index=None):
    """Compile author event routes; 1.0 keeps one block, 1.1.0 keeps the spans."""
    source=opening['initial_state'].get('event_narrative_annotations')
    if source is None:return []
    if not isinstance(source,Mapping) or set(source)!={'schema','routes'} or source['schema'] not in {AUTHOR_DOCUMENT_SCHEMA,LEGACY_AUTHOR_DOCUMENT_SCHEMA} or not isinstance(source['routes'],(list,tuple)) or not source['routes']:raise ValueError('event_narrative.author_invalid')
    anchor='author/se1/openings_and_routes.json#'+opening['id']+'/initial_state/event_narrative_annotations/routes'
    if opening_index is not None:anchor='author/se1/openings_and_routes.json#/openings/'+str(opening_index)+'/initial_state/event_narrative_annotations/routes'
    output=[];seen=set()
    for index,item in enumerate(source['routes']):
        if not isinstance(item,Mapping) or set(item)!={'event_ref','route_ref','body','entity_annotations'}:raise ValueError('event_narrative.author_invalid')
        key=(item['event_ref'],item['route_ref'])
        if any(not isinstance(ref,str) or not ref.strip() for ref in key) or key in seen or not isinstance(item['body'],str) or not item['body'].strip():raise ValueError('event_narrative.author_invalid')
        seen.add(key)
        text=item['body']
        declaration=item['entity_annotations']
        expected=SPAN_ANNOTATION_SCHEMA if source['schema']==AUTHOR_DOCUMENT_SCHEMA else LEGACY_ANNOTATION_SCHEMA
        if not isinstance(declaration,Mapping) or declaration.get('schema')!=expected:raise ValueError('event_narrative.author_version_invalid')
        schema=SCHEMA if isinstance(declaration,Mapping) and declaration.get('schema')==SPAN_ANNOTATION_SCHEMA else LEGACY_SCHEMA
        blocks=[]
        if schema==SCHEMA:
            spans=compile_authored_blocks({'initial_state':opening['initial_state'],'prologue_story':{'body':text,'entity_annotations':declaration}},[text])
            if not spans:raise ValueError('event_narrative.author_invalid')
            for order,span in enumerate(spans,start=1):
                blocks.append({'block_ref':opening['id']+'.event.'+item['route_ref']+'.block.'+str(order),'order':order,'locale':locale,'audience':'public','source_ref':anchor+'/'+str(index)+'['+str(span['start'])+':'+str(span['end'])+']','text':span['text'],'text_digest':text_digest(span['text']),**{k:span[k] for k in ('kind','references','speaker','reference_status')}})
        else:
            annotation=_legacy_annotation(opening,item,text)
            if annotation is None:raise ValueError('event_narrative.author_invalid')
            blocks.append({'block_ref':opening['id']+'.event.'+item['route_ref']+'.paragraph.1','order':1,'locale':locale,'audience':'public','source_ref':anchor+'/'+str(index),'text':text,'text_digest':text_digest(text),**annotation[0]})
        value={'schema':schema,'opening_ref':opening['id'],'event_ref':item['event_ref'],'route_ref':item['route_ref'],'source_body_sha256':text_digest(text),'blocks':blocks}
        value['document_sha256']=digest(value);output.append(value)
    return sorted(output,key=lambda item:(item['event_ref'],item['route_ref']))

def validate_referenced_block(block,text,known=None):
    """Validate one compiled narrative block against its exact source text.

    Returns the block mapping.  Mentions must cover the block-local half-open
    Unicode intervals of the original characters: no invented label, no
    reordering, no overlap, and no drift away from ``text``.
    """
    if not isinstance(block,Mapping) or set(block)!=BLOCK_FIELDS:raise ValueError('event_narrative.references_invalid')
    if any(not isinstance(block[k],str) or not block[k] for k in ('block_ref','locale','source_ref','text','kind')):raise ValueError('event_narrative.references_invalid')
    if type(block['order']) is not int or block['order']<1 or block['audience']!='public' or block['kind'] not in KINDS:raise ValueError('event_narrative.references_invalid')
    if block['text_digest']!=text_digest(block['text']) or block['text']!=text:raise ValueError('event_narrative.body_mismatch')
    refs=block['references'];speaker=block['speaker']
    if not isinstance(refs,(list,tuple)) or len(refs)>32 or block['reference_status'] not in {'none','resolved'}:raise ValueError('event_narrative.references_invalid')
    previous=0
    for ref in refs:
        if not isinstance(ref,Mapping) or set(ref)!={'schema','source_ref','kind','label','start','end'} or ref['schema']!='se-authored-entity-reference/1.0.0' or ref['kind'] not in REFERENCE_KINDS or not isinstance(ref['source_ref'],str) or not ref['source_ref']:raise ValueError('event_narrative.references_invalid')
        if known is not None and known.get(ref['source_ref'])!=ref['kind']:raise ValueError('event_narrative.references_invalid')
        if type(ref['start']) is not int or type(ref['end']) is not int or not previous<=ref['start']<ref['end']<=len(text) or text[ref['start']:ref['end']]!=ref['label']:raise ValueError('event_narrative.references_invalid')
        previous=ref['end']
    if speaker is not None:
        if not isinstance(speaker,Mapping) or set(speaker)!={'schema','source_ref','kind','label'} or speaker['schema']!='se-authored-speaker/1.0.0' or speaker['kind']!='person' or not all(isinstance(speaker[k],str) and speaker[k] for k in ('source_ref','label')):raise ValueError('event_narrative.speaker_invalid')
    if (block['kind'] in {'npc_dialogue','npc_action'})!=(speaker is not None) or block['reference_status']!=('resolved' if refs or speaker else 'none'):raise ValueError('event_narrative.references_invalid')
    return block


def event_annotation_index(style,events):
    """Validate against canonical route text, never against a display-name lookup."""
    if not style:return {}
    values=[(b['opening_ref'],value) for b in style.get('opening_bindings',[]) for value in b.get('event_narratives',[])]
    if not values:return {}
    if style.get('schema')!=STYLE_SCHEMA:raise ValueError('event_narrative.style_version_invalid')
    event_index={event['identity']['id']:event for event in events};result={}
    fields={'schema','opening_ref','event_ref','route_ref','source_body_sha256','blocks','document_sha256'}
    from .authored_narrative_annotations import entity_reference_kinds
    for opening_ref,doc in values:
        if not isinstance(doc,Mapping) or set(doc)!=fields or doc['schema'] not in DOCUMENT_SCHEMAS or doc['opening_ref']!=opening_ref or doc['document_sha256']!=digest({k:v for k,v in doc.items() if k!='document_sha256'}):raise ValueError('event_narrative.document_invalid')
        legacy=doc['schema']==LEGACY_SCHEMA
        event=event_index.get(doc['event_ref']);key=(doc['event_ref'],doc['route_ref'])
        routes=[r for r in event['checkpoint_graph']['edges'] if r['id']==doc['route_ref']] if event else []
        blocks=doc['blocks']
        if key in result or len(routes)!=1 or not isinstance(blocks,(list,tuple)) or not blocks or (legacy and len(blocks)!=1):raise ValueError('event_narrative.route_invalid')
        text=routes[0]['public_meaning']
        if doc['source_body_sha256']!=text_digest(text):raise ValueError('event_narrative.body_mismatch')
        if legacy:
            block=blocks[0]
            # Frozen 1.0 documents carry no ``kind`` and only whole paragraphs.
            if not isinstance(block,Mapping) or block.get('kind','paragraph') not in {'paragraph','npc_dialogue'}:raise ValueError('event_narrative.references_invalid')
            validate_referenced_block(block,text)
        else:
            if any(not isinstance(block,Mapping) for block in blocks):raise ValueError('event_narrative.references_invalid')
            if [block.get('order') for block in blocks]!=list(range(1,len(blocks)+1)):raise ValueError('event_narrative.route_invalid')
            if ''.join(str(block.get('text','')) for block in blocks)!=text:raise ValueError('event_narrative.body_mismatch')
            if len({block.get('block_ref') for block in blocks})!=len(blocks):raise ValueError('event_narrative.route_invalid')
            for block in blocks:
                validate_referenced_block(block,block.get('text','') if isinstance(block.get('text'),str) else '')
        result[key]=doc
    return result
