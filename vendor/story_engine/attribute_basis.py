"""Source-bound attribute selection; never grants modifiers or acquires RNG."""
from collections.abc import Mapping
from .default_rules import fingerprint

SCHEMA='321roll-action-attribute-context/1.0.0'

def validate_context(value):
    if not isinstance(value,Mapping) or set(value)!={'schema','attributes','sources','action_source_ref','context_sha256'} or value['schema']!=SCHEMA:
        raise ValueError('attribute_basis.invalid_context')
    attributes=value['attributes'];sources=value['sources']
    if not isinstance(attributes,(list,tuple)) or not 1<=len(attributes)<=32 or not isinstance(sources,(list,tuple)) or not 1<=len(sources)<=32:
        raise ValueError('attribute_basis.invalid_sources')
    refs=[]
    for attribute in attributes:
        if not isinstance(attribute,Mapping) or set(attribute)!={'ref','label','value'} or any(not isinstance(attribute[k],str) or not attribute[k].strip() or len(attribute[k])>200 for k in ('ref','label')) or type(attribute['value']) is not int or not 0<=attribute['value']<=100:
            raise ValueError('attribute_basis.invalid_attribute')
        refs.append(attribute['ref'])
    if len(refs)!=len(set(refs)):raise ValueError('attribute_basis.duplicate_attribute')
    refs=[]
    for source in sources:
        if not isinstance(source,Mapping) or set(source)!={'source_ref','kind','label','text','source_sha256'} or source['kind'] not in {'action','profession','specialization','skill','attribute'}:
            raise ValueError('attribute_basis.invalid_source')
        if any(not isinstance(source[k],str) or not source[k].strip() or len(source[k])>(4000 if k=='text' else 240) for k in ('source_ref','label','text')) or source['source_sha256']!=fingerprint({k:v for k,v in source.items() if k!='source_sha256'}):
            raise ValueError('attribute_basis.source_mismatch')
        refs.append(source['source_ref'])
    if len(refs)!=len(set(refs)) or not any(s['source_ref']==value['action_source_ref'] and s['kind']=='action' for s in sources):
        raise ValueError('attribute_basis.action_source_required')
    if value['context_sha256']!=fingerprint({k:v for k,v in value.items() if k!='context_sha256'}):raise ValueError('attribute_basis.context_mismatch')
    return value

def validate_selection(value,context):
    if not isinstance(value['attribute_ref'],str) or value['attribute_ref'] not in {a['ref'] for a in context['attributes']}:
        raise ValueError('attribute_basis.foreign_attribute')
    reason=value['attribute_reason'];refs=value['attribute_source_refs']
    if not isinstance(reason,str) or not reason.strip() or len(reason)>300:raise ValueError('attribute_basis.reason_required')
    if not isinstance(refs,(list,tuple)) or not 1<=len(refs)<=16 or any(not isinstance(r,str) for r in refs) or len(refs)!=len(set(refs)) or not set(refs)<={s['source_ref'] for s in context['sources']} or context['action_source_ref'] not in refs:
        raise ValueError('attribute_basis.foreign_source')
    return value

INSTRUCTION=('根据行动目标、实际方法及其属性关联，结合输入中实际职业、专精和已学技能，在 attribute_context.attributes 允许范围内选择属性。'
             '不得只取最高数值，职业或技能文字不授予额外数值、不视为发动技能或支付技能费用，不得按预期骰面选属性。'
             '额外输出 attribute_ref、attribute_reason（一句简短理由）、attribute_source_refs；引用只可来自 attribute_context.sources，必须包含 action_source_ref。'
             'attribute_reason 会给行动本人阅读，不得包含难度档、DC、骰面或未公开资料。只引用实际与本次方法有关的职业或技能，不把全部技能列为生效加值。')

def evaluate_fixed(payload):
    """Apply authored training associations without a Provider or numeric bonus."""
    from .pack_check_plan import _object,_text,_plain
    from .turn_interaction import normalize_attribute_selection_rules
    _object(payload,('operation_ref','context'));_text(payload['operation_ref'])
    context=_plain(payload['context'])
    _object(context,('schema','room_ref','actor_ref','event_ref','room_revision','actor_revision','event_revision','artifact_sha256','offer_ref','offer_sha256','definition_sha256','default_attribute_ref','selection_rules','attribute_context','context_sha256'))
    if context['schema']!='321roll-fixed-attribute-context/1.0.0':raise ValueError('attribute_basis.fixed_context_invalid')
    for key in ('room_ref','actor_ref','event_ref','offer_ref','default_attribute_ref'):_text(context[key])
    for key in ('room_revision','actor_revision','event_revision'):
        if type(context[key]) is not int or context[key]<1:raise ValueError('attribute_basis.invalid_revision')
    for key in ('artifact_sha256','offer_sha256','definition_sha256','context_sha256'):
        value=context[key]
        if not isinstance(value,str) or len(value)!=71 or not value.startswith('sha256:') or any(ch not in '0123456789abcdef' for ch in value[7:]):raise ValueError('attribute_basis.invalid_digest')
    if context['context_sha256']!=fingerprint({k:v for k,v in context.items() if k!='context_sha256'}):raise ValueError('attribute_basis.fixed_context_mismatch')
    basis=validate_context(context['attribute_context']);allowed={a['ref']:a for a in basis['attributes']};selected=context['default_attribute_ref']
    if selected not in allowed:raise ValueError('attribute_basis.foreign_default')
    rule=context['selection_rules']
    if rule is not None:
        normalized=normalize_attribute_selection_rules([rule])[0]
        if normalized!=rule or rule['offer_ref']!=context['offer_ref'] or any(a['attribute_ref'] not in allowed for a in rule['associations']):raise ValueError('attribute_basis.foreign_association')
    actual={s['source_ref'] for s in basis['sources'] if s['kind'] in {'profession','specialization','skill'}}
    matched=next((a for a in (rule or {}).get('associations',[]) if set(a['required_source_refs'])<=actual),None)
    if matched:selected=matched['attribute_ref']
    reason=matched['reason'] if matched else rule['fallback_reason'] if rule else '按原候选登记的'+allowed[selected]['label']+'方法处理，采用当前角色的实际属性。'
    result={'schema':'se-fixed-attribute-proposal/1.0.0','committed':False,'operation_ref':payload['operation_ref'],'context_sha256':context['context_sha256'],'attribute_ref':selected,'attribute_reason':reason,'attribute_source_refs':[basis['action_source_ref'],*(matched['required_source_refs'] if matched else [selected])]}
    validate_selection(result,basis);result['proposal_sha256']=fingerprint(result)
    return result
