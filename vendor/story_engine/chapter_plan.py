"""Non-binding chapter outlines; progression remains platform authority."""
from collections.abc import Mapping

FEATURE = 'story.chapter_plan/1.0.0'


def validate_plan(value):
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 8:
        raise ValueError('brief_start.chapter_plan_invalid')
    result = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {'title', 'summary', 'completion_goal'}:
            raise ValueError('brief_start.chapter_plan_invalid')
        chapter = {}
        for key, limit in (('title', 120), ('summary', 1000), ('completion_goal', 1000)):
            text = item[key]
            if not isinstance(text, str) or not text.strip() or len(text) > limit or any(0xD800 <= ord(c) <= 0xDFFF for c in text):
                raise ValueError('brief_start.chapter_plan_invalid')
            chapter[key] = text.strip()
        result.append(chapter)
    if len({row['title'] for row in result}) != len(result):
        raise ValueError('brief_start.chapter_plan_invalid')
    return result


INSTRUCTION = (
    '另返回 chapter_plan 数组，包含1至8章，每章只有 title、summary、completion_goal。'
    '第一章对应本次开场。大纲是可调整的叙事方向，不是已经发生的事实；不要预定玩家选择、检定结果或奖励。'
    'summary 是该章揭示时给玩家的无剧透简介；completion_goal 是供主持参考的收束目标。'
)
