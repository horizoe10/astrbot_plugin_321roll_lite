"""Optional money and item changes written by the narrating model (hosting.ledger/1.0.0).

When the platform sends economy_options the narration contract becomes /1.9.0
and the model may list up to four changes that the story itself caused: a fee
paid, a purse found, goods confiscated, a reward handed over.  The engine only
shapes them: every actor and item reference must come from the options, a
magnitude above the platform's limit is cut to the limit and a loss never takes
more money than the actor holds.  A malformed entry is dropped without
rejecting otherwise valid prose.  The platform still owns the wallet, the
inventory and the final commit.
"""
from collections.abc import Mapping

FEATURE = 'hosting.ledger/1.0.0'
MODEL_CONTRACT = 'se-hosted-narrative-model-output/1.9.0'
OPTIONS_SCHEMA = '321roll-ledger-options/1.0.0'
MAX_ENTRIES = 4
INSTRUCTION = (
    '本次启用钱物记账：输出ledger，最多4项，每项{actor_ref,kind,item_ref,delta,reason}。'
    '只记本轮正文里实际发生、由故事造成的得失：酬劳、赏钱、拾得、赔付、罚没、被偷、交给NPC或从NPC处得到的东西。'
    'actor_ref只取economy_options.actors里的actor_ref；kind为money时item_ref写空字符串，delta是货币数量的增减；'
    'kind为item时item_ref只取economy_options.items里的item_ref，delta是件数的增减。'
    '钱的单笔增减不超过economy_options.money_limit，物品单笔不超过item_limit，不能让角色花掉自己没有的钱。'
    'reason写一句不超过60字的缘由。玩家之间的转交、商店买卖由平台记账，不写进ledger；'
    '正文没有明确写到得失时给[]。钱和物品的得失只写进ledger，不写成facts。'
)


def _text(value, maximum, minimum=0):
    return (isinstance(value, str) and minimum <= len(value.strip()) and len(value) <= maximum
            and not any(0xD800 <= ord(ch) <= 0xDFFF for ch in value))


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def validate_options(value):
    keys = {'schema', 'currency', 'money_limit', 'item_limit', 'actors', 'items'}
    if not isinstance(value, Mapping) or set(value) != keys or value['schema'] != OPTIONS_SCHEMA:
        raise ValueError('hosted_turn.ledger_options_invalid')
    if not _text(value['currency'], 20, 1) or not _integer(value['money_limit'], 1, 100000) or not _integer(value['item_limit'], 1, 99):
        raise ValueError('hosted_turn.ledger_options_invalid')
    actors, items = value['actors'], value['items']
    if not isinstance(actors, (list, tuple)) or not 1 <= len(actors) <= 16 or not isinstance(items, (list, tuple)) or len(items) > 128:
        raise ValueError('hosted_turn.ledger_options_invalid')
    for actor in actors:
        if (not isinstance(actor, Mapping) or set(actor) != {'actor_ref', 'name', 'money'} or not _text(actor['actor_ref'], 120, 1)
                or not _text(actor['name'], 80, 1) or not _integer(actor['money'], 0, 10 ** 9)):
            raise ValueError('hosted_turn.ledger_options_invalid')
    for item in items:
        if not isinstance(item, Mapping) or set(item) != {'item_ref', 'name'} or not _text(item['item_ref'], 120, 1) or not _text(item['name'], 80, 1):
            raise ValueError('hosted_turn.ledger_options_invalid')
    if len({a['actor_ref'] for a in actors}) != len(actors) or len({i['item_ref'] for i in items}) != len(items):
        raise ValueError('hosted_turn.ledger_options_invalid')
    return value


def normalize(value, context):
    """The usable entries of a model ledger, in order; anything malformed is left out."""
    options = context.get('economy_options')
    if not options or not isinstance(value, (list, tuple)):
        return []
    money = {a['actor_ref']: a['money'] for a in options['actors']}
    items = {i['item_ref'] for i in options['items']}
    result = []
    for entry in list(value)[:MAX_ENTRIES]:
        if not isinstance(entry, Mapping) or set(entry) != {'actor_ref', 'kind', 'item_ref', 'delta', 'reason'}:
            continue
        actor, kind, item, delta = entry['actor_ref'], entry['kind'], entry['item_ref'], entry['delta']
        if actor not in money or type(delta) is not int or delta == 0 or not _text(entry['reason'], 120, 1):
            continue
        if kind == 'money' and item == '':
            delta = max(-options['money_limit'], min(options['money_limit'], delta))
            delta = max(delta, -money[actor])
            if delta == 0:
                continue
            money[actor] += delta
        elif kind == 'item' and item in items:
            delta = max(-options['item_limit'], min(options['item_limit'], delta))
        else:
            continue
        result.append({'actor_ref': actor, 'kind': kind, 'item_ref': item, 'delta': delta, 'reason': entry['reason'].strip()})
    return result
