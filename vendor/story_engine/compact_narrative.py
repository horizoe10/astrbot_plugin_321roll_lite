"""One model-authored choice list, expanded into the unchanged public proposal.

The platform snapshot and validation inputs stay intact. Only redundant model
output and provenance metadata unused by the model are removed from its input.
"""
from .brief_start import _object
from .play_hooks import MODEL_CONTRACT as HOOKS_CONTRACT

CONTRACT='se-hosted-narrative-model-output/1.7.0'
FEATURE='hosting.compact_narrative/1.0.0'
FIELDS=('paragraphs','facts','npcs','progress','annotations','choices','decision_reason')
CHECK_FIELDS=('kind','attribute_ref','difficulty','failure_cost')
INSTRUCTION=(
 '本次按紧凑正文合同输出paragraphs、facts、npcs、progress、choices、decision_reason。'
 'annotations仅在需要标注实体引用、NPC对白或动作时输出，不生成整组空标注。'
 '先写paragraphs正文，再填写其他结构化字段。后续行动只写一次choices，不重复写suggestions或decision_node。'
 'choices给四个不同的简明方向，每项{text,kind,attribute_ref,difficulty,failure_cost,source_fact_refs,exit}。'
 'kind仅为check、narrative、recover；check的属性取rules.attributes，难度取rules.difficulties，代价取rules.failure_costs；'
 '其他两种的attribute_ref、difficulty、failure_cost均为空字符串。候选只表达准备采取的行动，不预告结果。'
 '属性检定只用一颗D20加当前属性修正，不附加职业、技能、装备修正，不授予优势或重掷。'
 '普通推进decision_reason=null，source_fact_refs可为空。真正需要玩家权衡的关键分歧才填写decision_reason，'
 '此时给2至4项互不相同的choices，至少一项exit=true表示实际可选的暂缓或退让，不替玩家决定退出。'
 '关键候选source_fact_refs必须引用输入facts的编号或scene、goal，1至8项；不得自造来源或把猜测当事实。'
 '共同危险活跃时不得提出安全休息。候选不自创资源数量、财物转移、控制权或真人同意。'
)


def model_context(context):
    """Project verified inputs; retain identity, audience, truth kind and content."""
    result=dict(context)
    result['facts']=[{k:v for k,v in fact.items() if k!='source_receipt_ref'} for fact in context['facts']]
    if 'entity_catalog' in context:
        catalog=context['entity_catalog']
        result['entity_catalog']={k:v for k,v in catalog.items() if k not in {'schema','entities'}}
        result['entity_catalog']['entities']=[
            {k:v for k,v in entity.items() if k not in {'entity_version','source_receipt_refs'}}
            for entity in catalog['entities']]
    return result


def selected_intent(context):
    """Reuse a fresh platform-authorized choice; never interpret added input."""
    if context.get('narrative_model_contract') not in {CONTRACT,HOOKS_CONTRACT}:return None
    selected=context.get('selected_candidate')
    scene=context['scene']
    if not selected or context.get('action_references') or any(scene.get(key) for key in ('action_detail','preparations','risk_response','resource_action')) or (scene.get('risk') or {}).get('status')=='active':return None
    candidate=selected['candidate'];rule=candidate['rule']
    if candidate['text']!=context['action'] or set(rule)!=set(CHECK_FIELDS) or rule['kind'] not in {'check','narrative'}:return None
    value={**rule,'reason':'沿用本人所选正式候选的原规则。','clarification':'','risk_response':''}
    basis=context.get('attribute_context')
    if basis:
        value.update(attribute_reason='',attribute_source_refs=[])
        if rule['kind']=='check':
            attribute=next((row for row in basis['attributes'] if row['ref']==rule['attribute_ref']),None)
            if attribute is None:return None
            value.update(attribute_reason='按原候选登记的'+attribute['label']+'方法处理，采用当前角色的实际属性。',attribute_source_refs=[basis['action_source_ref']])
    return value


def expand(value, *, allow_play_hooks=False):
    """Derive duplicate public fields without inventing or correcting a choice."""
    _object(value,tuple(k for k in FIELDS if k!='annotations' or k in value)+(('play_hooks',) if allow_play_hooks and 'play_hooks' in value else ()))
    choices=value['choices']
    if not isinstance(choices,(list,tuple)) or not 1<=len(choices)<=4:
        raise ValueError('hosted_turn.choice_checks_invalid')
    for choice in choices:
        _object(choice,('text',*CHECK_FIELDS,'source_fact_refs','exit'))
        if not isinstance(choice['source_fact_refs'],(list,tuple)) or len(choice['source_fact_refs'])>8 or type(choice['exit']) is not bool:
            raise ValueError('hosted_turn.decision_source_invalid')
    reason=value['decision_reason']
    if reason is not None and (not isinstance(reason,str) or not reason.strip() or len(reason)>300):
        raise ValueError('hosted_turn.decision_schema_invalid')
    result={k:value[k] for k in FIELDS if k not in {'choices','decision_reason'} and k in value}
    if allow_play_hooks and 'play_hooks' in value:result['play_hooks']=value['play_hooks']
    result['suggestions']=[choice['text'] for choice in choices]
    result['suggestion_checks']=[{k:choice[k] for k in CHECK_FIELDS} for choice in choices]
    result['decision_node']=None if reason is None else {
        'schema':'se-hosted-decision-node/1.0.0','reason':reason,'candidates':[
            {'text':choice['text'],'rule':{k:choice[k] for k in CHECK_FIELDS if k!='attribute_ref'},
             'source_fact_refs':choice['source_fact_refs'],'exit':choice['exit']} for choice in choices]}
    return result
