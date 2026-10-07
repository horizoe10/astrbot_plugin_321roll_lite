"""Versioned length policy independent of authored voice and narrative facts."""
from collections.abc import Mapping
from .hosted_narrative_policy import RANGES

SCHEMA='321roll-narrative-length-policy/2.0.0'
FEATURE='post_resolution.narrative_length/2.0.0'

def validate(policy):
    if (not isinstance(policy,Mapping) or set(policy)!={'schema','revision','mode'}
            or policy['schema']!=SCHEMA or type(policy['revision']) is not int or policy['revision']<0
            or not isinstance(policy['mode'],str) or policy['mode'] not in RANGES):
        raise ValueError('post_resolution.narrative_length_policy_invalid')
    return policy

def instruction(policy):
    low,high=RANGES[policy['mode']]
    return f'本次冻结的正文篇幅为{low}—{high}个可见字符（含上下界），以{(low+high)//2}字为目标，每个自然段不超过360字。只计算blocks正文，标点计入，空白、结构字段、选项和独立机械结果不计。保持故事包的既定文风，不重复段落凑字、不增加行动或改写后果；输出前在同一次生成内核对篇幅。'

def validate_length(texts,policy):
    low,high=RANGES[policy['mode']]
    if not low<=sum(not c.isspace() for text in texts for c in text)<=high:
        raise ValueError('post_resolution.narrative_length_invalid')
