"""Pack-independent opening world of a custom room: what holds when the story starts.

The brief-start model proposes it together with the opening scene: the time of
day, the public facts everyone already knows, a few countdown clocks and the
permissions an opening character has declared in person.  The Engine only
checks shape and bounds.  The platform owns the state: it re-validates, binds
each permission to the opening character it names, publishes the world when the
room starts and alone advances a clock, always from a committed receipt.
"""
from collections.abc import Mapping

FEATURE = 'story.opening_world/1.0.0'
SCHEMA = 'se-opening-world/1.0.0'
VISIBILITY = ('public', 'party')
FIELDS = ('time_description', 'public_facts', 'clocks', 'permissions')


def _fail():
    raise ValueError('brief_start.opening_world_invalid')


def _text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum \
            or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        _fail()
    return value.strip()


def _items(value, low, high, fields):
    if not isinstance(value, (list, tuple)) or not low <= len(value) <= high:
        _fail()
    for item in value:
        if not isinstance(item, Mapping) or set(item) != set(fields):
            _fail()
    return value


def validate(value, npc_names):
    """Normalized opening world, or ``brief_start.opening_world_invalid``."""
    if not isinstance(value, Mapping) or set(value) != set(FIELDS):
        _fail()
    facts = value['public_facts']
    if not isinstance(facts, (list, tuple)) or not 1 <= len(facts) <= 8:
        _fail()
    facts = [_text(item, 300) for item in facts]
    clocks = []
    for clock in _items(value['clocks'], 0, 4, ('title', 'segments', 'consequence', 'visibility')):
        if type(clock['segments']) is not int or not 4 <= clock['segments'] <= 8 or clock['visibility'] not in VISIBILITY:
            _fail()
        clocks.append({'title': _text(clock['title'], 60), 'segments': clock['segments'],
                       'consequence': _text(clock['consequence'], 300), 'visibility': clock['visibility']})
    names = set(npc_names)
    permissions = []
    for item in _items(value['permissions'], 0, 6, ('npc', 'label', 'statement', 'scope')):
        if item['npc'] not in names:
            _fail()
        permissions.append({'npc': item['npc'], 'label': _text(item['label'], 60),
                            'statement': _text(item['statement'], 400), 'scope': _text(item['scope'], 200)})
    if len(set(facts)) != len(facts) or len({c['title'] for c in clocks}) != len(clocks) \
            or len({(p['npc'], p['label']) for p in permissions}) != len(permissions):
        _fail()
    return {'schema': SCHEMA, 'time_description': _text(value['time_description'], 200),
            'public_facts': facts, 'clocks': clocks, 'permissions': permissions}


INSTRUCTION = (
    '另返回 opening_world 对象，只描述故事开始这一刻已经成立的情况：'
    'time_description 为一句开场时间与天气；'
    'public_facts 为1至8条同桌一开始就都知道的公开事实，不写秘密、推测、他人内心或结局；'
    'clocks 为0至4个倒计时，每个为 {title,segments,consequence,visibility}，segments 为4至8的整数，'
    'consequence 写明满格时会发生的事，visibility 为 public（旁观者也看得到）或 party（只有同桌看得到）；'
    'permissions 为0至6条开场人物本人主动声明的许可，每条为 {npc,label,statement,scope}，'
    'npc 必须与 npcs 中某一项的 name 完全一致，statement 是该人物说出的声明，scope 写清许可的范围。'
    '许可随时可由该人物撤回，不代表任何玩家的同意；时钟与许可都不预定玩家的行动或结果。'
)
