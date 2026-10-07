"""Attribute-only D20 declarations for the next offered actions."""
from collections.abc import Mapping

POLICY='attribute-d20/1.0.0'
FEATURE='hosting.choice_checks/1.0.0'
INSTRUCTION=('额外输出 suggestion_checks，与 suggestions 逐项对应，每项为 '
 '{kind,attribute_ref,difficulty,failure_cost}。kind 为 check、narrative 或 recover。'
 '只有需要检定才用 check，attribute_ref 取 rules.attributes 中的键，difficulty 取 rules.difficulties，'
 'failure_cost 为 setback 或 harm；其他两类的 attribute_ref、difficulty、failure_cost 均为空字符串。'
 '候选文本只描述准备采取的行动，不预告成功、失败、损失或其他可能后果。'
 '检定仅掷一颗D20并加当前属性修正，职业、技能、装备及场景不另加修正，也不授予优势或重掷。'
 '如果 decision_node 非空，其候选 rule 必须与对应 suggestion_checks 的 kind、difficulty、failure_cost 一致。')

def enabled(rules):return rules.get('check_policy')==POLICY

def validate(values,suggestions,rules):
    if not isinstance(values,(list,tuple)) or len(values)!=len(suggestions):raise ValueError('hosted_turn.choice_checks_invalid')
    result=[]
    for value in values:
        if not isinstance(value,Mapping) or set(value)!={'kind','attribute_ref','difficulty','failure_cost'}:raise ValueError('hosted_turn.choice_checks_invalid')
        if value['kind']=='check':
            if value['attribute_ref'] not in rules['attributes'] or value['difficulty'] not in rules['difficulties'] or value['failure_cost'] not in rules['failure_costs']:raise ValueError('hosted_turn.choice_checks_invalid')
        elif value['kind'] not in {'narrative','recover'} or any(value[k] for k in ('attribute_ref','difficulty','failure_cost')):raise ValueError('hosted_turn.choice_checks_invalid')
        result.append(dict(value))
    return result
