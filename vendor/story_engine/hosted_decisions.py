"""Structured next decisions, produced within the existing narrative budget."""
from .brief_start import _object,_text

FEATURE='hosting.structured_decisions/1.0.0'
SCHEMA='se-hosted-decision-node/1.0.0'
MODEL_CONTRACT='se-hosted-narrative-model-output/1.4.0'

def validate(value,context,suggestions):
    if value is None:return None
    _object(value,('schema','reason','candidates'))
    if value['schema']!=SCHEMA:raise ValueError('hosted_turn.decision_schema_invalid')
    _text(value['reason'],300)
    candidates=value['candidates']
    if not isinstance(candidates,(list,tuple)) or not 2<=len(candidates)<=4:raise ValueError('hosted_turn.decision_candidates_invalid')
    known={f['fact_ref'] for f in context['facts']}|{'scene','goal'}
    texts=[];exits=0
    for item in candidates:
        _object(item,('text','rule','source_fact_refs','exit'))
        texts.append(_text(item['text'],300))
        if type(item['exit']) is not bool:raise ValueError('hosted_turn.decision_exit_invalid')
        exits+=item['exit']
        rule=item['rule'];_object(rule,('kind','difficulty','failure_cost'))
        if rule['kind']=='check':
            if rule['difficulty'] not in context['rules']['difficulties'] or rule['failure_cost'] not in {'setback','harm'}:raise ValueError('hosted_turn.decision_rule_invalid')
        elif rule['kind'] not in {'narrative','recover'} or rule['difficulty'] or rule['failure_cost']:
            raise ValueError('hosted_turn.decision_rule_invalid')
        if rule['kind']=='recover' and (context['scene'].get('risk') or {}).get('status')=='active':raise ValueError('hosted_turn.decision_recovery_invalid')
        refs=item['source_fact_refs']
        if not isinstance(refs,(list,tuple)) or not 1<=len(refs)<=8 or any(not isinstance(ref,str) or ref not in known for ref in refs) or len(set(refs))!=len(refs):raise ValueError('hosted_turn.decision_source_invalid')
    if texts!=list(suggestions) or len(set(texts))!=len(texts) or not exits:raise ValueError('hosted_turn.decision_candidates_invalid')
    return dict(value)

INSTRUCTION=('额外输出 decision_node：普通推进为 null；只有下一步涉及有后果的路线分歧、需要权衡的风险或不能替玩家决定的承诺时，'
 '提出 {schema:"se-hosted-decision-node/1.0.0",reason,candidates:[{text,rule:{kind,difficulty,failure_cost},source_fact_refs,exit}]}。'
 '关键节点给2到4项不同合法候选，text必须逐项等于suggestions，至少一项exit=true，表达退让、暂缓或保留退出权的实际途径，不替玩家退出故事。'
 '先检索当前输入的受众可见facts、scene、goal和rules，source_fact_refs只取这些事实编号或scene、goal，至少一项，不能把传言当定案。'
 'rule.kind仅为narrative、check、recover；check只用给定难度档和setback或harm，其他两项difficulty和failure_cost为空。'
 'narrative不引入随机和资源费用；recover沿现有安全休息规则；不得自创资源数量、物品、控制权或PVP同意。'
 '危险活跃时不得提出安全休息。候选只是下次行动的合法规则提案，不能描述已被玩家选择。')
