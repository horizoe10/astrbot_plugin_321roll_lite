"""Compile explicit author references; never infer identity from prose names.

Two author contracts are supported side by side and one never rewrites the
other:

* ``sp-authored-narrative-annotations/1.0.0`` annotates whole source
  paragraphs; :func:`compile_authored_annotations` keeps its exact legacy
  output for those documents.
* ``sp-authored-narrative-annotations/1.1.0`` annotates ordered half-open
  Unicode spans inside the original paragraphs; :func:`compile_authored_blocks`
  splits paragraphs into ordered source-bound blocks and keeps every
  unannotated character as plain ``paragraph`` text.
"""
import hashlib
from collections.abc import Mapping
from .world_entities import known_world_entities

LEGACY_ANNOTATION_SCHEMA = 'sp-authored-narrative-annotations/1.0.0'
SPAN_ANNOTATION_SCHEMA = 'sp-authored-narrative-annotations/1.1.0'
ANNOTATION_SCHEMAS = frozenset({LEGACY_ANNOTATION_SCHEMA, SPAN_ANNOTATION_SCHEMA})
COMPILED_BLOCK_KINDS = frozenset({'paragraph', 'npc_dialogue', 'npc_action'})
ENTITY_REFERENCE_SCHEMA = 'se-authored-entity-reference/1.0.0'
SPEAKER_SCHEMA = 'se-authored-speaker/1.0.0'


def compile_authored_annotations(opening,paragraphs):
    world=opening['initial_state'].get('world_initialization',{})
    world_entities=known_world_entities(world)
    declaration=opening['prologue_story'].get('entity_annotations')
    if declaration is None:return None
    def fail():raise ValueError('authored_narrative.references_invalid')
    if not isinstance(declaration,Mapping) or set(declaration)!={'schema','body_sha256','blocks'} or declaration['schema'] not in ANNOTATION_SCHEMAS:fail()
    if declaration['schema']==SPAN_ANNOTATION_SCHEMA:
        return compile_authored_blocks(opening,paragraphs)
    if declaration['body_sha256']!='sha256:'+hashlib.sha256(opening['prologue_story']['body'].encode()).hexdigest():fail()
    known={}
    def add(ref,kind,label,aliases=()):
        if ref in known:fail()
        known[ref]={'kind':kind,'label':label,'aliases':aliases}
    for npc in world.get('npcs',[]):add(npc['ref'],'person',npc['label'])
    for field,kind in [('scene','place'),('quest','quest')]:
        if field in world:add(world[field]['ref'],kind,world[field]['label'])
    for clock in world.get('clocks',[]):
        if clock['visibility']=='public':add(clock['ref'],'status',clock['title'])
    for item in world_entities:
        if item['visibility']=='public':add(item['ref'],item['kind'],item['label'],item['aliases'])
    values=declaration['blocks']
    if not isinstance(values,(list,tuple)) or len(values)>len(paragraphs):fail()
    output=[{'kind':'paragraph','references':[],'speaker':None,'reference_status':'none'} for _ in paragraphs]
    seen=set()
    for annotation in values:
        if not isinstance(annotation,Mapping) or set(annotation)!={'sequence','kind','speaker','mentions'}:fail()
        sequence=annotation['sequence']
        if type(sequence) is not int or not 1<=sequence<=len(paragraphs) or sequence in seen:fail()
        seen.add(sequence);text=paragraphs[sequence-1]
        if annotation['kind'] not in {'paragraph','npc_dialogue'} or not isinstance(annotation['mentions'],(list,tuple)) or len(annotation['mentions'])>32:fail()
        previous=0;refs=[]
        for ref in annotation['mentions']:
            if not isinstance(ref,Mapping) or set(ref)!={'source_ref','label','start','end'}:fail()
            entity=known.get(ref['source_ref'])
            if entity is None or ref['label'] not in (entity['label'],*entity['aliases']) or type(ref['start']) is not int or type(ref['end']) is not int or not previous<=ref['start']<ref['end']<=len(text) or text[ref['start']:ref['end']]!=ref['label']:fail()
            refs.append({'schema':'se-authored-entity-reference/1.0.0',**ref,'kind':entity['kind']});previous=ref['end']
        speaker=annotation['speaker']
        if speaker is not None:
            if not isinstance(speaker,Mapping) or set(speaker)!={'source_ref','label'}:fail()
            entity=known.get(speaker['source_ref'])
            if entity is None or entity['kind']!='person' or speaker['label']!=entity['label'] or speaker['source_ref'] not in {npc['ref'] for npc in world.get('npcs',[])}:fail()
            speaker={'schema':'se-authored-speaker/1.0.0',**speaker,'kind':'person'}
        if (annotation['kind']=='npc_dialogue')!=(speaker is not None):fail()
        output[sequence-1]={'kind':annotation['kind'],'references':refs,'speaker':speaker,'reference_status':'resolved' if refs or speaker else 'none'}
    return output


def entity_reference_kinds(opening):
    """Public entity ids of one opening, keyed by their stable source ref."""
    world = opening['initial_state'].get('world_initialization', {})
    kinds = {}
    for entity in known_world_entities(world):
        if entity['visibility'] == 'public':
            kinds[entity['ref']] = entity['kind']
    return kinds


def known_entities(opening):
    """Author-known entity labels and kinds for one opening.

    The set is exactly the one the 1.0 compiler used: NPC declarations,
    public clocks, the opening scene and quest, and public world entities.
    Identity still comes only from the explicit ``source_ref``.
    """
    world = opening['initial_state'].get('world_initialization', {})
    known = {}

    def add(ref, kind, label, aliases=()):
        if ref in known:
            raise ValueError('authored_narrative.references_invalid')
        known[ref] = {'kind': kind, 'label': label, 'aliases': aliases}

    for npc in world.get('npcs', []):
        add(npc['ref'], 'person', npc['label'])
    for field, kind in [('scene', 'place'), ('quest', 'quest')]:
        if field in world:
            add(world[field]['ref'], kind, world[field]['label'])
    for clock in world.get('clocks', []):
        if clock['visibility'] == 'public':
            add(clock['ref'], 'status', clock['title'])
    for item in known_world_entities(world):
        if item['visibility'] == 'public':
            add(item['ref'], item['kind'], item['label'], item['aliases'])
    return known


def npc_source_refs(opening):
    """Stable NPC declarations of one opening; only these may speak or act."""
    world = opening['initial_state'].get('world_initialization', {})
    return {npc['ref'] for npc in world.get('npcs', [])}


def validate_author_mentions(known, text, mentions):
    """Validate ordered explicit mentions and project them onto ``text``.

    ``text`` is the exact text an annotation covers (a paragraph for 1.0, one
    span for 1.1.0) and mention offsets are half-open block-local Unicode
    intervals.  Every mention must reproduce its declared label with the
    original characters and punctuation; unit mismatches fail closed.
    """
    references = []
    previous = 0
    for ref in mentions:
        if not isinstance(ref, Mapping) or set(ref) != {'source_ref', 'label', 'start', 'end'}:
            raise ValueError('authored_narrative.references_invalid')
        entity = known.get(ref['source_ref'])
        if entity is None or ref['label'] not in (entity['label'], *entity['aliases']):
            raise ValueError('authored_narrative.references_invalid')
        if type(ref['start']) is not int or type(ref['end']) is not int:
            raise ValueError('authored_narrative.references_invalid')
        if not previous <= ref['start'] < ref['end'] <= len(text) or text[ref['start']:ref['end']] != ref['label']:
            raise ValueError('authored_narrative.references_invalid')
        references.append({'schema': ENTITY_REFERENCE_SCHEMA, **ref, 'kind': entity['kind']})
        previous = ref['end']
    return references


def validate_author_speaker(known, npcs, speaker):
    """Validate one explicit NPC speaker declaration and project it."""
    if not isinstance(speaker, Mapping) or set(speaker) != {'source_ref', 'label'}:
        raise ValueError('authored_narrative.speaker_invalid')
    entity = known.get(speaker['source_ref'])
    if entity is None or entity['kind'] != 'person' or speaker['label'] != entity['label'] or speaker['source_ref'] not in npcs:
        raise ValueError('authored_narrative.speaker_invalid')
    return {'schema': SPEAKER_SCHEMA, **speaker, 'kind': 'person'}


def compile_authored_blocks(opening, paragraphs):
    """Compile ordered source-bound spans for ``sp-authored-narrative-annotations/1.1.0``.

    Returns ``[{'sequence','start','end','text','kind','references','speaker',
    'reference_status'}, ...]`` in author order for the given normalized
    paragraphs, or ``None`` when the opening carries no 1.1.0 declaration.
    Every character the author did not annotate stays in a ``paragraph``
    block, so joining the texts of one sequence reproduces that paragraph
    verbatim, punctuation included.
    """
    declaration = opening['prologue_story'].get('entity_annotations')
    if declaration is None or not isinstance(declaration, Mapping):
        return None
    if declaration.get('schema') != SPAN_ANNOTATION_SCHEMA:
        return None
    if set(declaration) != {'schema', 'body_sha256', 'blocks'}:
        raise ValueError('authored_narrative.references_invalid')
    body = opening['prologue_story']['body']
    if declaration['body_sha256'] != 'sha256:' + hashlib.sha256(body.encode()).hexdigest():
        raise ValueError('authored_narrative.references_invalid')
    values = declaration['blocks']
    if not isinstance(values, (list, tuple)) or len(values) > 256:
        raise ValueError('authored_narrative.references_invalid')
    known = known_entities(opening)
    npcs = npc_source_refs(opening)
    grouped = {}
    for annotation in values:
        if not isinstance(annotation, Mapping) or set(annotation) != {'sequence', 'kind', 'start', 'end', 'speaker', 'mentions'}:
            raise ValueError('authored_narrative.references_invalid')
        sequence = annotation['sequence']
        if type(sequence) is not int or not 1 <= sequence <= len(paragraphs):
            raise ValueError('authored_narrative.references_invalid')
        text = paragraphs[sequence - 1]
        if annotation['kind'] not in COMPILED_BLOCK_KINDS or not isinstance(annotation['mentions'], (list, tuple)) or len(annotation['mentions']) > 32:
            raise ValueError('authored_narrative.references_invalid')
        if type(annotation['start']) is not int or type(annotation['end']) is not int or not 0 <= annotation['start'] < annotation['end'] <= len(text):
            raise ValueError('authored_narrative.references_invalid')
        speaker = annotation['speaker']
        if speaker is not None:
            speaker = validate_author_speaker(known, npcs, speaker)
        if (annotation['kind'] in {'npc_dialogue', 'npc_action'}) != (speaker is not None):
            raise ValueError('authored_narrative.speaker_invalid')
        grouped.setdefault(sequence, []).append({
            'kind': annotation['kind'], 'start': annotation['start'], 'end': annotation['end'],
            'speaker': speaker,
            'references': validate_author_mentions(known, text[annotation['start']:annotation['end']], annotation['mentions']),
        })
    output = []
    for sequence, text in enumerate(paragraphs, start=1):
        spans = sorted(grouped.get(sequence, []), key=lambda item: item['start'])
        previous = 0
        for span in spans:
            if span['start'] < previous:
                raise ValueError('authored_narrative.references_invalid')
            if span['start'] > previous:
                output.append({'sequence':sequence,**_compiled_span('paragraph', previous, span['start'], text, None, [])})
            output.append({'sequence':sequence,**_compiled_span(span['kind'], span['start'], span['end'], text, span['speaker'], span['references'])})
            previous = span['end']
        if previous < len(text):
            output.append({'sequence':sequence,**_compiled_span('paragraph', previous, len(text), text, None, [])})
    return output


def _compiled_span(kind, start, end, paragraph, speaker, references):
    # ``references`` are already block-local: the author declaration and the
    # compiled block share the same half-open Unicode unit by contract.
    return {
        'kind': kind,
        'references': references,
        'speaker': speaker,
        'reference_status': 'resolved' if references or speaker else 'none',
        'start': start,
        'end': end,
        'text': paragraph[start:end],
    }
