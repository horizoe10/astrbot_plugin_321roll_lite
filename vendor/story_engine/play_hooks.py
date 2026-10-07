"""Optional narrative invitations; never an action, roll or state proposal.

Like optional narrative annotations, a malformed hook is discarded without
rejecting otherwise valid prose. The platform supplies the enabled/actionable
form allowlist and the already audience-filtered entity catalog.
"""
from collections.abc import Mapping
import re

FEATURE = 'hosting.play_hooks/1.0.0'
MODEL_CONTRACT = 'se-hosted-narrative-model-output/1.8.0'
OPTIONS_SCHEMA = '321roll-play-hook-options/1.0.0'
PLAYS = frozenset(('playInvestigation', 'playTestimony', 'playNegotiation', 'playRelations',
    'playCalendar', 'playProjects', 'playOutfitting', 'playConflict', 'playChase', 'playDebate',
    'playPlans', 'playFlashback', 'playOracle', 'playTransformation', 'playPrivatePhases',
    'playRegroup', 'playFortune', 'playBranchEndings'))
ACTION = re.compile(r'[a-z][a-z_]{0,63}')
INSTRUCTION = (
    '可以额外输出play_hooks，最多4项，每项{play,action,target_ref,reason,fill}。'
    '只从play_hook_options.plays选择本房已开启、当前允许发起的玩法和动作；没有合适时机则省略或给[]。'
    'target_ref为entity_catalog中本人可见对象的entity_ref，无对象时为null；不得编造或引用隐藏对象、新建人物临时编号。'
    'reason为一句不超过200字的理由，fill为发起表单预填，只用该动作fields中的字段名，最多8项，每项字符串不超过400字。'
    '对象字段可填写该target_ref，平台会解析为当前读者可见的名称。不要输出label或自动执行任何玩法；'
    '提议不占回合，不建立事实，不改变数值、权限或已提交结果。'
)


def validate_options(value):
    if not isinstance(value, Mapping) or set(value) != {'schema', 'plays'} or value['schema'] != OPTIONS_SCHEMA or not isinstance(value['plays'], Mapping):
        raise ValueError('hosted_turn.play_hook_options_invalid')
    for play, actions in value['plays'].items():
        if play not in PLAYS or not isinstance(actions, Mapping):
            raise ValueError('hosted_turn.play_hook_options_invalid')
        for action, entry in actions.items():
            if not isinstance(action, str) or not ACTION.fullmatch(action) or not isinstance(entry, Mapping) or set(entry) != {'fields'}:
                raise ValueError('hosted_turn.play_hook_options_invalid')
            if not isinstance(entry['fields'], (list, tuple)) or len(entry['fields']) > 24 or any(not isinstance(f, str) or not ACTION.fullmatch(f) for f in entry['fields']):
                raise ValueError('hosted_turn.play_hook_options_invalid')
    return value


def _text(value, maximum):
    return isinstance(value, str) and len(value) <= maximum and not any(0xD800 <= ord(ch) <= 0xDFFF for ch in value) and len(value.encode('utf-16-le')) // 2 <= maximum


def normalize(value, context):
    options = context.get('play_hook_options')
    if not options or not isinstance(value, (list, tuple)) or len(value) > 4:
        return []
    from .custom_plays import PLAYS as registered
    plays = options['plays']
    visible = {entry['entity_ref'] for entry in context.get('entity_catalog', {}).get('entities', [])}
    result = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {'play', 'action', 'target_ref', 'reason', 'fill'}:
            continue
        play, action, target, fill = (item[key] for key in ('play', 'action', 'target_ref', 'fill'))
        if not isinstance(play, str) or play not in PLAYS or not isinstance(action, str) or action not in plays.get(play, {}) or action not in registered.get(play, {}):
            continue
        if target is not None and (not isinstance(target, str) or target not in visible):
            continue
        if not _text(item['reason'], 200) or not isinstance(fill, Mapping) or len(fill) > 8:
            continue
        if any(key not in plays[play][action]['fields'] or not _text(text, 400) for key, text in fill.items()):
            continue
        # No unbound entity may be smuggled into prose or a form field.
        refs = re.findall(r'entity\.[A-Za-z0-9_.-]+', item['reason'] + ' ' + ' '.join(fill.values()))
        if any(ref not in visible for ref in refs):
            continue
        result.append({**item, 'fill': dict(fill)})
    return result
