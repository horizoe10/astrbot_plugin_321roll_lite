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
CATALOG_OPTIONS_SCHEMA = '321roll-ledger-options/1.1.0'
MAX_ENTRIES = 4
INSTRUCTION = (
    '本次启用钱物记账：输出ledger，最多4项，每项{actor_ref,kind,item_ref,delta,reason}。'
    '只记本轮正文里实际发生、由故事造成的得失：酬劳、赏钱、拾得、赔付、罚没、被偷、交给NPC或从NPC处得到的东西。'
    'actor_ref只取economy_options.actors里的actor_ref；kind为money时item_ref写空字符串，delta是货币数量的增减；'
    'kind为item时item_ref只取economy_options.items里的item_ref，delta是件数的增减。'
    '钱的单笔增减不超过economy_options.money_limit，物品单笔不超过item_limit，不能让角色花掉自己没有的钱。'
    'reason写一句不超过60字的缘由。玩家之间的转交、商店买卖由平台记账，不写进ledger；'
    '正文没有明确写到得失时给[]。钱和物品的得失只写进ledger，不写成facts。'
    '若economy_options含shops，商品名称、标价、回收价及库存范围以该目录为准，不自拟价格或未列出的货物。'
    '玩家用自然语言表达想买卖，只写询价、挑选或等待结算；没有平台购买回执不能写已经扣款、交货或交易成功。'
    '引导到现有整备买卖命令，不把交易伪装成赠礼、罚款或酬劳；正常赠礼与酬劳仍可记账。'
)


def _text(value, maximum, minimum=0):
    return (isinstance(value, str) and minimum <= len(value.strip()) and len(value) <= maximum
            and not any(0xD800 <= ord(ch) <= 0xDFFF for ch in value))


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def validate_options(value):
    keys = {'schema', 'currency', 'money_limit', 'item_limit', 'actors', 'items'}
    if isinstance(value, Mapping) and value.get('schema') == CATALOG_OPTIONS_SCHEMA:
        keys.add('shops')
    if not isinstance(value, Mapping) or set(value) != keys or value['schema'] not in {OPTIONS_SCHEMA, CATALOG_OPTIONS_SCHEMA}:
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
    if 'shops' in value:
        shops = value['shops']
        if not isinstance(shops, (list, tuple)) or len(shops) > 32:
            raise ValueError('hosted_turn.shop_catalog_invalid')
        known = {i['item_ref'] for i in items}
        ids = set()
        for shop in shops:
            if (not isinstance(shop, Mapping) or set(shop) != {'shop_ref','name','place','here','wares'}
                    or not _text(shop['shop_ref'],120,1) or shop['shop_ref'] in ids
                    or not _text(shop['name'],80,1) or not _text(shop['place'],120)
                    or type(shop['here']) is not bool or not isinstance(shop['wares'], (list,tuple))
                    or len(shop['wares']) > 128):
                raise ValueError('hosted_turn.shop_catalog_invalid')
            ids.add(shop['shop_ref'])
            refs=set()
            for ware in shop['wares']:
                if (not isinstance(ware,Mapping) or set(ware) != {'item_ref','price','sell'}
                        or ware['item_ref'] not in known or ware['item_ref'] in refs
                        or not _integer(ware['price'],0,10**9) or not _integer(ware['sell'],0,10**9)):
                    raise ValueError('hosted_turn.shop_catalog_invalid')
                refs.add(ware['item_ref'])
    return value


def reject_shop_exchange(entries, options):
    """A wallet/item exchange belongs to checkout, never to the story ledger.

    Check gross directions instead of the net balance, so an added reward
    cannot hide a purchase. Gifts and fees on their own remain permitted.
    """
    if 'shops' not in options:
        return
    stock={w['item_ref'] for shop in options['shops'] for w in shop['wares']}
    for actor in {e['actor_ref'] for e in entries}:
        rows=[e for e in entries if e['actor_ref']==actor]
        pays=any(e['kind']=='money' and e['delta']<0 for e in rows)
        earns=any(e['kind']=='money' and e['delta']>0 for e in rows)
        receives=any(e['kind']=='item' and e['item_ref'] in stock and e['delta']>0 for e in rows)
        gives=any(e['kind']=='item' and e['item_ref'] in stock and e['delta']<0 for e in rows)
        if (pays and receives) or (earns and gives):
            raise ValueError('hosted_turn.shop_exchange_requires_checkout: 商店钱物交换必须使用正式买卖，不能写入ledger；正文停在等待结算')


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
    reject_shop_exchange(result, options)
    return result
