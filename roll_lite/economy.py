"""Money for worlds that want it: a wallet, shops tied to places, the story's own gains and losses, and 整备.

A world turns money on with an optional top-level "economy" block (validate() lists its fields).  Each
character keeps a wallet in actors.data_json["money"], apart from the resource bars, so a wound never
touches it.  The story moves money and items through the engine's ledger (hosting.ledger/1.0.0): the
narrating model lists what the story itself caused, the plugin caps it and applies it together with the
narration.  Buying and selling happen only in 整备, a short private phase between rounds: the host opens
it, the turn clock stops, players shop in private chat at the shops of the current place, and when
everyone is done (or the time is up, or the host closes it) a public summary goes to the group and into
the next narration.  Gifts between players work at any time.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from . import loadout, messages, shared
from .commands import Caller, Reply, UserError
from .storage import dumps, loads, now
from .worlds.economy import validate  # noqa: F401  (the world block's rules)

if TYPE_CHECKING:
    from .app import LiteApp

OUTFIT_MINUTES, MAX_OUTFIT_MINUTES = 3, 15
STORY_ITEM_LIMIT = 2
DONE_WORDS = ("好了", "好", "完成", "准备好了", "结束", "ok", "OK")


# ---------------------------------------------------------------- world block
def settings(pack: dict[str, Any]) -> dict[str, Any] | None:
    raw = pack.get("economy")
    if not raw:
        return None
    return {"currency": raw["currency"].strip(), "initial": raw.get("initial", 0), "prices": dict(raw.get("prices") or {}),
            "sell": raw.get("sell", 50), "wage": raw.get("wage", 0), "story_limit": raw.get("storyLimit", 20),
            "auto_outfit": bool(raw.get("autoOutfit")), "kit_money": raw.get("kitMoney", 0),
            "shops": [{"id": s["id"], "name": s["name"].strip(), "kind": s.get("kind", ""), "place": s.get("place") or "",
                       "items": list(s["items"]), "text": s.get("text", "")} for s in raw.get("shops") or []]}


def of_room(room: sqlite3.Row) -> dict[str, Any] | None:
    return settings(shared.world(room)["pack"])


def require_economy(room: sqlite3.Row) -> dict[str, Any]:
    s = of_room(room)
    if s is None:
        raise UserError("这个世界没有钱和商店。")
    return s


def money_text(s: dict[str, Any], amount: int) -> str:
    return f"{amount} {s['currency']}"


# ---------------------------------------------------------------- wallet
def balance(actor: sqlite3.Row, s: dict[str, Any]) -> int:
    return int(loads(actor["data_json"], {}).get("money", s["initial"]))


def set_balance(c: sqlite3.Connection, actor_id: str, amount: int) -> None:
    data = loads(c.execute("SELECT data_json FROM actors WHERE id=?", (actor_id,)).fetchone()["data_json"], {})
    data["money"] = max(0, int(amount))
    c.execute("UPDATE actors SET data_json=?,updated_at=? WHERE id=?", (dumps(data), now(), actor_id))


def start_money(s: dict[str, Any], origin: dict[str, Any] | None, kit_money: bool) -> int:
    """Starting wallet: the world's amount, the origin's adjustment and, in 精雕, a kit taken as money."""
    return max(0, s["initial"] + int((origin or {}).get("money") or 0) + (s["kit_money"] if kit_money else 0))


def wallet_view(room: sqlite3.Row, actor: sqlite3.Row) -> tuple[str, int] | None:
    """(currency, balance) for cards, or None in a world without money."""
    s = of_room(room)
    return None if s is None or not actor["archetype_id"] else (s["currency"], balance(actor, s))


def _add_item(pack: dict[str, Any], doc: dict[str, Any], ref: str, count: int) -> None:
    defn = next(i for i in pack["items"] if i["id"] == ref)
    held = doc["items"].setdefault(ref, {"quantity": 0, "uses_left": defn["uses"]})
    held["quantity"] = held.get("quantity", 0) + count
    for field, limit in (("durability", "durability_max"), ("charges", "charge_max")):
        if (defn.get("equipment") or {}).get(limit) is not None and held.get(field) is None:
            held[field] = defn["equipment"][limit]


def _take_item(doc: dict[str, Any], ref: str, count: int) -> int:
    """Remove up to count; returns how many were removed."""
    held = doc["items"].get(ref)
    taken = min(count, (held or {}).get("quantity", 0))
    if taken:
        held["quantity"] -= taken
        if not held["quantity"]:
            held.pop("equipped", None)
    return taken


def _fits(pack: dict[str, Any], doc: dict[str, Any], ref: str, count: int) -> bool:
    """Whether count more of ref stay within the world's carrying capacity (worlds without one always fit)."""
    capacity = (pack.get("inventory") or {}).get("capacity")
    if capacity is None:
        return True
    units = {i["id"]: (i.get("equipment") or {}).get("carrying_units", 0) for i in pack["items"]}
    load = sum(h.get("quantity", 0) * units.get(r, 0) for r, h in doc["items"].items())
    return load + count * units.get(ref, 0) <= capacity


# ---------------------------------------------------------------- places and shops
def place_names(room: sqlite3.Row, entry_id: str) -> list[str]:
    snapshot = shared.world(room)
    names = [e["name"] for e in snapshot["pack"]["entries"] if e["id"] == entry_id]
    for place in snapshot.get("presentation", {}).get("places") or []:
        if place.get("entry") == entry_id:
            names += [place["name"], *(place.get("aliases") or [])]
    return [n for n in dict.fromkeys(names) if n]


def place_label(room: sqlite3.Row, shop: dict[str, Any]) -> str:
    return (place_names(room, shop["place"]) or [""])[0] if shop["place"] else ""


def shops_here(room: sqlite3.Row, s: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Shops open at the current scene: the ones of this place (matched in the scene title) and the ones without a place."""
    s = s or of_room(room)
    if s is None:
        return []
    title = loads(room["scene_json"], {}).get("title", "")
    return [shop for shop in s["shops"] if not shop["place"] or any(n in title for n in place_names(room, shop["place"]))]


def new_place_shops(room: sqlite3.Row, old_title: str) -> list[dict[str, Any]]:
    """Shops tied to a place the story just walked into (none when the scene title did not change)."""
    s = of_room(room)
    title = loads(room["scene_json"], {}).get("title", "")
    if s is None or title == old_title:
        return []
    return [shop for shop in shops_here(room, s) if shop["place"]
            and not any(n in old_title for n in place_names(room, shop["place"]))]


def _wares(room: sqlite3.Row, s: dict[str, Any], shop: dict[str, Any], actor: sqlite3.Row | None) -> list[dict[str, Any]]:
    items = {i["id"]: i for i in shared.world(room)["pack"]["items"]}
    held = loadout.state(actor)["items"] if actor is not None else {}
    return [{"name": items[r]["name"], "price": s["prices"][r], "sell": s["prices"][r] * s["sell"] // 100,
             "text": str(items[r].get("text") or "")[:40], "owned": held.get(r, {}).get("quantity", 0)} for r in shop["items"]]


def shop_views(room: sqlite3.Row, s: dict[str, Any], shops: list[dict[str, Any]], actor: sqlite3.Row | None) -> list[dict[str, Any]]:
    here = {shop["id"] for shop in shops_here(room, s)}
    return [{"name": shop["name"], "kind": shop["kind"], "text": shop["text"], "place": place_label(room, shop),
             "open": shop["id"] in here, "wares": _wares(room, s, shop, actor)} for shop in shops]


# ---------------------------------------------------------------- the story's ledger
def ledger_options(c: sqlite3.Connection, room: sqlite3.Row) -> dict[str, Any] | None:
    """economy_options for narrate_committed, or None when this table has no money or no checked narration."""
    s = of_room(room)
    if s is None:
        return None
    from .engine import VENDOR  # noqa: F401
    from story_engine import attribute_checks, hosted_ledger
    if not attribute_checks.enabled(shared.rules(room)):
        return None
    actors = [a for a in shared.present_actors(c, room["id"]) if a["archetype_id"]][:16]
    if not actors:
        return None
    return {"schema": hosted_ledger.OPTIONS_SCHEMA, "currency": s["currency"], "money_limit": s["story_limit"],
            "item_limit": STORY_ITEM_LIMIT,
            "actors": [{"actor_ref": a["id"], "name": shared.actor_label(a)[:80], "money": balance(a, s)} for a in actors],
            "items": [{"item_ref": i["id"], "name": i["name"][:80]} for i in shared.world(room)["pack"]["items"][:128]]}


def describe_entry(room: sqlite3.Row, entry: dict[str, Any], names: dict[str, str]) -> str:
    s = of_room(room) or {"currency": ""}
    who = names.get(entry["actor_ref"], "")
    if entry["kind"] == "money":
        return f"{who} {'得到' if entry['delta'] > 0 else '失去'} {abs(entry['delta'])} {s['currency']}"
    item = next((i["name"] for i in shared.world(room)["pack"]["items"] if i["id"] == entry["item_ref"]), entry["item_ref"])
    return f"{who} {'得到' if entry['delta'] > 0 else '失去'}「{item}」×{abs(entry['delta'])}"


def apply_ledger(c: sqlite3.Connection, room: sqlite3.Row, ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the story's changes in the narration's transaction; returns what actually changed, for the card."""
    s = of_room(room)
    if s is None or not ledger:
        return []
    pack = shared.world(room)["pack"]
    names = {i["id"]: i["name"] for i in pack["items"]}
    applied = []
    for entry in ledger:
        actor = c.execute("SELECT * FROM actors WHERE id=? AND room_id=?", (entry["actor_ref"], room["id"])).fetchone()
        if actor is None or actor["presence"] == "left" or not actor["archetype_id"]:
            continue
        if entry["kind"] == "money":
            before = balance(actor, s)
            after = max(0, before + entry["delta"])
            if after == before:
                continue
            set_balance(c, actor["id"], after)
            applied.append({"who": shared.actor_label(actor), "kind": "money", "name": s["currency"], "delta": after - before,
                            "reason": entry["reason"], "after": after})
            continue
        if entry["item_ref"] not in names:
            continue
        doc = loadout.state(actor)
        if entry["delta"] > 0:
            _add_item(pack, doc, entry["item_ref"], entry["delta"])
            delta = entry["delta"]
        else:
            delta = -_take_item(doc, entry["item_ref"], -entry["delta"])
            if not delta:
                continue
        loadout.save(c, actor["id"], doc)
        applied.append({"who": shared.actor_label(actor), "kind": "item", "name": names[entry["item_ref"]], "delta": delta,
                        "reason": entry["reason"], "after": doc["items"][entry["item_ref"]]["quantity"]})
    return applied


def pay_wage(c: sqlite3.Connection, room: sqlite3.Row) -> int:
    """The world's per-act wage to everyone seated with a card: (amount each, [{name, after}]); (0, []) when none."""
    s = of_room(room)
    if s is None or not s["wage"]:
        return 0, []
    paid = []
    for actor in shared.present_actors(c, room["id"]):
        if actor["archetype_id"]:
            after = balance(actor, s) + s["wage"]
            set_balance(c, actor["id"], after)
            paid.append({"name": shared.actor_label(actor), "after": after})
    return s["wage"], paid


def story_notes(room: sqlite3.Row) -> list[str]:
    """What the last 整备 bought and sold, for the next narration."""
    return list(loads(room["data_json"], {}).get("outfit_notes") or [])


def clear_notes(c: sqlite3.Connection, room_id: str) -> None:
    _set(c, room_id, outfit_notes=None)


# ---------------------------------------------------------------- 整备
def _set(c: sqlite3.Connection, room_id: str, **values: Any) -> None:
    data = loads(c.execute("SELECT data_json FROM rooms WHERE id=?", (room_id,)).fetchone()["data_json"], {})
    for key, value in values.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    c.execute("UPDATE rooms SET data_json=? WHERE id=?", (dumps(data), room_id))


def outfit(room: sqlite3.Row) -> dict[str, Any] | None:
    return loads(room["data_json"], {}).get("outfit")


def guard(room: sqlite3.Row) -> None:
    """Turn actions wait while the table is in 整备."""
    if outfit(room) is not None:
        raise UserError("现在是整备时间，回合暂停：私聊我发送 /团 商店 看看能买什么，买好后发送 /团 整备 好了。"
                        "全员好了、时间到或主持人收起后，回合接着继续。")


def host_guard(room: sqlite3.Row, what: str) -> None:
    """Host moves that write the story wait until 整备 is put away."""
    if outfit(room) is not None:
        raise UserError(f"整备还开着，故事暂停中：先发送 /团 主持 整备 收起，再{what}。")


def _players(c: sqlite3.Connection, room_id: str) -> list[sqlite3.Row]:
    return [a for a in shared.present_actors(c, room_id) if a["archetype_id"]]


def _minutes_left(info: dict[str, Any]) -> int:
    seconds = (datetime.fromisoformat(info["deadline"]) - datetime.now(UTC)).total_seconds()
    return max(1, -(-int(seconds) // 60))


def _outfit_card(c: sqlite3.Connection, room: sqlite3.Row, info: dict[str, Any], title: str) -> Any:
    s = of_room(room)
    shops = [shop for shop in s["shops"] if shop["id"] in info["shops"]]
    members = [{"name": shared.actor_label(a), "done": a["id"] in info["done"]} for a in _players(c, room["id"])]
    return messages.outfit_card(title, info.get("place", ""), [shop["name"] for shop in shops], members, _minutes_left(info),
                                s["currency"])


def open_outfit(app: "LiteApp", room_id: str, minutes: int, by: str) -> Reply:
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        s = require_economy(room)
        if room["state"] != "running":
            raise UserError("故事进行中才能整备。")
        if shared.ending_step(room):
            raise UserError("故事已经走向终章，不再开整备。同伴之间想交接钱物，随时可以 /团 给 名字 物品，或 /团 给 名字 钱 数额。")
        if outfit(room) is not None:
            raise UserError("已经在整备了：玩家私聊我发送 /团 商店 看看能买什么。")
        from .plays import hosted
        turn = hosted.current_turn(c, room_id)
        if turn is not None and turn["state"] != "awaiting":
            raise UserError("这一段还在结算或等主持人审阅；等正文发出来、下一位行动之前再整备。")
        if not _players(c, room_id):
            raise UserError("还没有建好卡的在场玩家。")
        info = {"opened_at": now(), "minutes": minutes, "by": by,
                "deadline": (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat(timespec="seconds"),
                "place": loads(room["scene_json"], {}).get("title", ""),
                "shops": [shop["id"] for shop in shops_here(room, s)], "done": [], "log": []}
        _set(c, room_id, outfit=info)
        app.store.add_event(c, room_id, "system", f"{by} 开启了整备（{minutes} 分钟）")
        app.store.bump_room(c, room_id)
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        card = _outfit_card(c, room, info, "整备开始")
    return Reply().say(card)


def _summary(c: sqlite3.Connection, room: sqlite3.Row, info: dict[str, Any], s: dict[str, Any], why: str) -> tuple[Any, list[str]]:
    rows, notes = [], []
    for actor in _players(c, room["id"]):
        mine = [x for x in info["log"] if x["actor"] == actor["id"]]
        bought = [x for x in mine if x["kind"] == "buy"]
        sold = [x for x in mine if x["kind"] == "sell"]
        spent = sum(x["money"] for x in bought)
        earned = sum(x["money"] for x in sold)
        name = shared.actor_label(actor)
        rows.append({"name": name, "bought": [f"{x['item']}×{x['count']}" for x in bought],
                     "sold": [f"{x['item']}×{x['count']}" for x in sold], "shops": list(dict.fromkeys(x["shop"] for x in mine)),
                     "spent": spent, "earned": earned, "after": balance(actor, s), "done": actor["id"] in info["done"]})
        if mine:
            parts = []
            for shop in dict.fromkeys(x["shop"] for x in mine):
                here_b = "、".join(f"{x['item']}×{x['count']}" for x in bought if x["shop"] == shop)
                here_s = "、".join(f"{x['item']}×{x['count']}" for x in sold if x["shop"] == shop)
                parts.append(f"在{shop}" + (f"买了{here_b}" if here_b else "") + ("，" if here_b and here_s else "")
                             + (f"卖掉{here_s}" if here_s else ""))
            notes.append(f"整备：{name}" + "；".join(parts) + f"（现有 {balance(actor, s)} {s['currency']}）")
    gifts = [x for x in info["log"] if x["kind"] == "give"]
    for g in gifts:
        notes.append(f"整备：{g['from']} 把{g['item']}交给了 {g['to']}")
    if not notes:
        notes.append("整备：大家清点了行囊，没有买卖。")
    return messages.outfit_summary(rows, s["currency"], info.get("place", ""), why,
                                   [f"{g['from']} → {g['to']}：{g['item']}" for g in gifts]), notes


async def close_outfit(app: "LiteApp", room_id: str, why: str) -> Reply:
    """End 整备: public summary, notes for the next narration, the turn clock moves on and the turn is shown again."""
    from .plays import hosted
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        info = outfit(room)
        if info is None:
            return Reply()
        s = of_room(room)
        card, notes = _summary(c, room, info, s, why)
        _set(c, room_id, outfit=None, outfit_notes=(story_notes(room) + notes)[-12:])
        turn = hosted.current_turn(c, room_id)
        holder = None
        if turn is not None and turn["state"] == "awaiting":
            if turn["deadline_at"]:
                paused_for = datetime.now(UTC) - datetime.fromisoformat(info["opened_at"])
                deadline = max(datetime.fromisoformat(turn["deadline_at"]) + paused_for, datetime.now(UTC) + timedelta(minutes=1))
                c.execute("UPDATE turns SET deadline_at=? WHERE id=?", (deadline.isoformat(timespec="seconds"), turn["id"]))
                turn = c.execute("SELECT * FROM turns WHERE id=?", (turn["id"],)).fetchone()
            if turn["actor_id"]:
                holder = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
        app.store.add_event(c, room_id, "system", "整备结束：" + why)
        from .plays import collaboration
        vote = collaboration.open_vote(c, room_id)
        if vote is not None and {a["id"] for a in hosted.eligible_actors(c, room_id)} <= set(loads(vote["ballots_json"], {})):
            # everyone voted during 整备: the next tick settles it right away
            c.execute("UPDATE votes SET deadline_at=? WHERE id=?", (datetime.now(UTC).isoformat(timespec="seconds"), vote["id"]))
        app.store.bump_room(c, room_id)
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    reply = Reply().say(card)
    if turn is not None and turn["state"] == "awaiting" and room["state"] == "running":
        from .plays import rush
        if rush.is_round(turn) or holder is not None:
            reply.say(hosted.turn_prompt(app, room, turn, holder))
    return reply


async def outfit_tick(app: "LiteApp") -> Reply:
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    with app.store.read() as c:
        due = [(r["id"], r["umo"]) for r in c.execute(
            "SELECT id,umo FROM rooms WHERE json_extract(data_json,'$.outfit.deadline')<=?", (stamp,))]
    for room_id, umo in due:
        if app.lock(room_id).locked():
            continue
        async with app.lock(room_id):
            reply = await close_outfit(app, room_id, "时间到")
        if reply.messages:
            await app.notifier.send(umo, reply.messages)
    return Reply()


def _require_outfit(app: "LiteApp", caller: Caller) -> tuple[sqlite3.Row, dict[str, Any], dict[str, Any], sqlite3.Row]:
    room = shared.require_room(app, caller, "running", "paused")
    s = require_economy(room)
    info = outfit(room)
    if info is None:
        raise UserError("买卖只在整备时间里进行：主持人发送 /团 主持 整备 开启后，私聊我 /团 商店 看货。"
                        "同伴之间转交随时可以：/团 给 名字 物品，或 /团 给 名字 钱 数额。")
    actor = shared.require_actor(app, caller, room)
    if not actor["archetype_id"]:
        raise UserError("先建好角色再采买：发送 /团 建卡。")
    return room, s, info, actor


def _count(text: str) -> tuple[str, int]:
    """'绷带 2' / '绷带×2' / '2 绷带' → ('绷带', 2)."""
    text = text.strip()
    m = re.fullmatch(r"(.+?)\s*[x×*＊]?\s*(\d{1,3})", text) or re.fullmatch(r"(\d{1,3})\s*(?:个|件|份)?\s*(.+)", text)
    if not m:
        return text, 1
    a, b = m.groups()
    return (a.strip(), int(b)) if not a.isdigit() else (b.strip(), int(a))


def _money_words(text: str, s: dict[str, Any] | None) -> int | None:
    """'钱 10' / '10 铜轮' / '铜轮 10' → 10; None when the text names an item instead."""
    if s is None:
        return None
    unit = "钱|金钱|" + re.escape(s["currency"])
    m = re.fullmatch(rf"(?:{unit})\s*(\d{{1,6}})\s*(?:{unit})?|(\d{{1,6}})\s*(?:{unit})", text.strip())
    return int(m.group(1) or m.group(2)) if m else None


def _find_ware(room: sqlite3.Row, s: dict[str, Any], shops: list[dict[str, Any]], name: str) -> tuple[dict[str, Any], str]:
    items = {i["id"]: i for i in shared.world(room)["pack"]["items"]}
    offered = [(shop, r) for shop in shops for r in shop["items"]]
    # "店名 物品" picks that shop.
    for shop in shops:
        if name.startswith(shop["name"]) and name[len(shop["name"]):].strip():
            name, offered = name[len(shop["name"]):].strip(), [(shop, r) for r in shop["items"]]
            break
    for test in (lambda n: n == name, lambda n: n.startswith(name), lambda n: name in n):
        found = [(shop, r) for shop, r in offered if test(items[r]["name"])]
        if found:
            return found[0][0], found[0][1]
    wares = "、".join(dict.fromkeys(items[r]["name"] for _, r in offered)) or "无"
    raise UserError(f"这里的店没有“{name}”。现在能买：{wares}。")


def _sellable(room: sqlite3.Row, s: dict[str, Any], actor: sqlite3.Row, name: str) -> dict[str, Any]:
    """The held item the player means; the refusal lists only what the shops would take back."""
    name = name.strip()
    items = [e for e in loadout.entries(room, actor) if e["kind"] == "item" and (e.get("quantity") or 0) > 0]
    match = next((e for e in items if e["name"] == name), None) or next((e for e in items if name and e["name"].startswith(name)), None)
    if match is not None:
        return match
    if any(e["name"].startswith(name) for e in loadout.entries(room, actor) if e["kind"] == "skill") and name:
        raise UserError("技能卖不掉，只有背包里的物品能卖。")
    offer = [f"{e['name']}（回收 {s['prices'].get(e['ref'], 0) * s['sell'] // 100}）" for e in items
             if s["prices"].get(e["ref"], 0) * s["sell"] // 100]
    raise UserError(f"你没有“{name}”可卖。" + (f"能卖给店里的：{'、'.join(offer)}。" if offer else "你身上没有店里收的东西。"))


async def show_shops(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "lobby", "running", "paused")
    s = require_economy(room)
    with app.store.read() as c:
        actor = shared.actor_for(c, room["id"], caller.user_id)
    info = outfit(room)
    wanted = args.strip()
    shops = [shop for shop in s["shops"] if not wanted or shop["name"].startswith(wanted) or wanted in shop["name"]]
    if wanted and not shops:
        raise UserError("没有这家店。这个世界的店：" + "、".join(shop["name"] for shop in s["shops"]) + "。")
    if not wanted:
        here = shops_here(room, s)
        shops = here + [shop for shop in s["shops"] if shop not in here]
    wallet = balance(actor, s) if actor is not None and actor["archetype_id"] else None
    return Reply().say(messages.shop_card(shop_views(room, s, shops, actor), s["currency"], wallet,
                                          place=loads(room["scene_json"], {}).get("title", ""), outfit=info is not None,
                                          sell=s["sell"], single=bool(wanted)))


async def buy(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room, s, info, actor = _require_outfit(app, caller)
    name, count = _count(args)
    if not name:
        raise UserError("写上要买的东西，例如 /团 买 绷带 2。")
    if not 1 <= count <= 99:
        raise UserError("一次买 1–99 件。")
    shops = [shop for shop in s["shops"] if shop["id"] in info["shops"]]
    if not shops:
        raise UserError("这里没有店。整备时间里还可以互相转交（/团 给 名字 物品），或发送 /团 整备 好了。")
    if actor["id"] in info["done"]:
        raise UserError("你已经发送过 /团 整备 好了。还想买的话先发送 /团 整备 取消。")
    shop, ref = _find_ware(room, s, shops, name)
    pack = shared.world(room)["pack"]
    item = next(i for i in pack["items"] if i["id"] == ref)
    cost = s["prices"][ref] * count
    with app.store.tx() as c:
        actor = c.execute("SELECT * FROM actors WHERE id=?", (actor["id"],)).fetchone()
        have = balance(actor, s)
        if cost > have:
            raise UserError(f"{item['name']}×{count} 要 {cost} {s['currency']}，你只有 {have}。")
        doc = loadout.state(actor)
        if not _fits(pack, doc, ref, count):
            raise UserError(f"背包装不下 {item['name']}×{count} 了：先 /团 卖 或 /团 丢弃 一些东西。")
        _add_item(pack, doc, ref, count)
        loadout.save(c, actor["id"], doc)
        set_balance(c, actor["id"], have - cost)
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
        info = outfit(room)
        info["log"].append({"actor": actor["id"], "kind": "buy", "shop": shop["name"], "item": item["name"], "count": count,
                            "money": cost})
        _set(c, room["id"], outfit=info)
        app.store.add_event(c, room["id"], "system", f"{shared.actor_label(actor)} 在{shop['name']}买了{item['name']}×{count}",
                            actor_id=actor["id"])
    return Reply().say(messages.trade_card("buy", shared.actor_label(actor), shop["name"], item["name"], count, -cost,
                                           have - cost, s["currency"], held=doc["items"][ref]["quantity"]))


async def sell(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room, s, info, actor = _require_outfit(app, caller)
    name, count = _count(args)
    if not s["sell"]:
        raise UserError("这个世界的店不收东西。")
    shops = [shop for shop in s["shops"] if shop["id"] in info["shops"]]
    if not shops:
        raise UserError("这里没有店可以卖东西。")
    if actor["id"] in info["done"]:
        raise UserError("你已经发送过 /团 整备 好了。还想卖的话先发送 /团 整备 取消。")
    entry = _sellable(room, s, actor, name)
    price = s["prices"].get(entry["ref"], 0) * s["sell"] // 100
    if price <= 0:
        raise UserError(f"店里不收“{entry['name']}”。")
    with app.store.tx() as c:
        actor = c.execute("SELECT * FROM actors WHERE id=?", (actor["id"],)).fetchone()
        doc = loadout.state(actor)
        held = doc["items"].get(entry["ref"]) or {}
        free = held.get("quantity", 0) - (1 if held.get("equipped") else 0)
        if not 1 <= count <= free:
            raise UserError(f"你能卖的“{entry['name']}”只有 {max(0, free)} 件" + ("（装备着的那件要先卸下）" if held.get("equipped") else "") + "。")
        _take_item(doc, entry["ref"], count)
        loadout.save(c, actor["id"], doc)
        after = balance(actor, s) + price * count
        set_balance(c, actor["id"], after)
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
        info = outfit(room)
        shop = next((sh for sh in shops if entry["ref"] in sh["items"]), shops[0])
        info["log"].append({"actor": actor["id"], "kind": "sell", "shop": shop["name"], "item": entry["name"], "count": count,
                            "money": price * count})
        _set(c, room["id"], outfit=info)
        app.store.add_event(c, room["id"], "system", f"{shared.actor_label(actor)} 在{shop['name']}卖掉{entry['name']}×{count}",
                            actor_id=actor["id"])
    return Reply().say(messages.trade_card("sell", shared.actor_label(actor), shop["name"], entry["name"], count, price * count,
                                           after, s["currency"], held=doc["items"].get(entry["ref"], {}).get("quantity", 0)))


async def give(app: "LiteApp", caller: Caller, args: str) -> Reply:
    """/团 给 名字 钱 10 | /团 给 名字 绷带 [数量]: works any time the dice are not rolling."""
    room = shared.require_room(app, caller, "lobby", "running", "paused")
    s = of_room(room)
    actor = shared.require_actor(app, caller, room)
    if not actor["archetype_id"]:
        raise UserError("先建好角色。")
    token, rest = shared.split_target(args, caller)
    if not token or not rest.strip():
        raise UserError("写上给谁、给什么，例如 /团 给 林晓 绷带 1" + ("，或 /团 给 林晓 钱 10" if s else "") + "。")
    from .plays import hosted
    pack = shared.world(room)["pack"]
    with app.store.tx() as c:
        turn = hosted.current_turn(c, room["id"])
        if turn is not None and turn["state"] == "resolving":
            raise UserError("有一个行动正在结算，等它结束后再转交。")
        target = shared.find_actor(c, room["id"], token, caller.mentions)
        if target["id"] == actor["id"] or not target["archetype_id"] or target["presence"] == "left":
            raise UserError("只能交给同桌另一位建好卡的角色。")
        actor = c.execute("SELECT * FROM actors WHERE id=?", (actor["id"],)).fetchone()
        amount = _money_words(rest, s)
        if amount is not None:
            have = balance(actor, s)
            if not 1 <= amount <= have:
                raise UserError(f"你现在有 {have} {s['currency']}，转交的数额要在 1–{have} 之间。")
            set_balance(c, actor["id"], have - amount)
            set_balance(c, target["id"], balance(target, s) + amount)
            what, after = f"{amount} {s['currency']}", have - amount
            label = what
        else:
            name, count = _count(rest)
            entry = loadout.find(room, actor, name)
            if entry["kind"] != "item":
                raise UserError("技能没法交给别人。")
            mine, theirs = loadout.state(actor), loadout.state(target)
            held = mine["items"].get(entry["ref"]) or {}
            free = held.get("quantity", 0) - (1 if held.get("equipped") else 0)
            if not 1 <= count <= free:
                raise UserError(f"你能交出的“{entry['name']}”只有 {max(0, free)} 件。")
            if not _fits(pack, theirs, entry["ref"], count):
                raise UserError(f"{shared.actor_label(target)} 的背包装不下了。")
            _take_item(mine, entry["ref"], count)
            _add_item(pack, theirs, entry["ref"], count)
            loadout.save(c, actor["id"], mine)
            loadout.save(c, target["id"], theirs)
            what, after, label = f"{entry['name']}×{count}", None, f"{entry['name']}×{count}"
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
        info = outfit(room)
        if info is not None:
            info["log"].append({"actor": actor["id"], "kind": "give", "from": shared.actor_label(actor),
                                "to": shared.actor_label(target), "item": label, "count": 1, "money": 0, "shop": ""})
            _set(c, room["id"], outfit=info)
        app.store.add_event(c, room["id"], "system", f"{shared.actor_label(actor)} 把{what}交给了 {shared.actor_label(target)}",
                            actor_id=actor["id"])
    return Reply().say(messages.gift_card(shared.actor_label(actor), shared.actor_label(target), what,
                                          after, s["currency"] if s else ""))


async def player_outfit(app: "LiteApp", caller: Caller, args: str) -> Reply:
    word = args.strip()
    room, s, info, actor = _require_outfit(app, caller)
    if not word:
        with app.store.read() as c:
            card = _outfit_card(c, room, info, "整备中")
        reply = Reply().say(card)
        reply.private_only = True
        return reply
    cancel = word in ("取消", "撤回", "还没好")
    if not cancel and word not in DONE_WORDS:
        raise UserError("买好了发送 /团 整备 好了；想再买发送 /团 整备 取消。")
    async with app.lock(room["id"]):
        with app.store.tx() as c:
            room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
            info = outfit(room)
            if info is None:
                raise UserError("整备刚刚结束了。")
            info["done"] = [i for i in info["done"] if i != actor["id"]] + ([] if cancel else [actor["id"]])
            _set(c, room["id"], outfit=info)
            players = _players(c, room["id"])
            everyone = all(a["id"] in info["done"] for a in players)
            card = _outfit_card(c, room, info, f"{shared.actor_label(actor)} {'还要再看看' if cancel else '整备好了'}")
        if everyone and not cancel:
            return await close_outfit(app, room["id"], "全员整备好了")
    return Reply().say(card)


async def host_outfit(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "running")
    shared.require_host(app, caller, room)
    require_economy(room)
    word = args.strip()
    if word in ("收起", "结束", "关", "关闭", "停"):
        if outfit(room) is None:
            raise UserError("现在没有在整备。")
        async with app.lock(room["id"]):
            return await close_outfit(app, room["id"], "主持人收起了整备")
    if word and not word.isdigit():
        raise UserError("写分钟数开启整备，例如 /团 主持 整备 3；收起写 /团 主持 整备 收起。")
    minutes = int(word) if word else OUTFIT_MINUTES
    if not 1 <= minutes <= MAX_OUTFIT_MINUTES:
        raise UserError(f"整备时间是 1–{MAX_OUTFIT_MINUTES} 分钟。")
    async with app.lock(room["id"]):
        return open_outfit(app, room["id"], minutes, caller.user_name)


async def host_ledger(app: "LiteApp", caller: Caller, args: str) -> Reply:
    """/团 主持 记账 [撤回 序号]: the money and item changes in the draft waiting for review."""
    from .plays import hosted
    room = shared.require_room(app, caller, "running", "paused")
    shared.require_host(app, caller, room)
    s = require_economy(room)
    try:
        turn = hosted._review_turn(app, room)
    except UserError:
        raise UserError("现在没有等待审阅的正文：钱物变化只在审稿时能撤回。先发送 /团 主持 审稿 开，"
                        "下一段正文会先私聊给你，再用 /团 主持 记账 查看。") from None
    proposal = loads(turn["narrative_json"], {})
    ledger = list(proposal.get("ledger") or [])
    word = args.strip()
    m = re.fullmatch(r"(?:撤回|删除|去掉)?\s*(\d{1,2})", word)
    if word and not m:
        raise UserError("撤回一笔写 /团 主持 记账 撤回 序号。")
    removed = ""
    with app.store.read() as c:
        names = {a["id"]: shared.actor_label(a) for a in c.execute("SELECT * FROM actors WHERE room_id=?", (room["id"],))}
    if m:
        index = int(m.group(1)) - 1
        if not 0 <= index < len(ledger):
            raise UserError(f"草稿里有 {len(ledger)} 笔钱物变化。" if ledger else "这份草稿没有钱物变化。")
        removed = describe_entry(room, ledger.pop(index), names)
        with app.store.tx() as c:
            c.execute("UPDATE turns SET narrative_json=?,updated_at=? WHERE id=?", (dumps({**proposal, "ledger": ledger}), now(), turn["id"]))
    reply = Reply().say(messages.ledger_draft([describe_entry(room, e, names) + f"（{e['reason']}）" for e in ledger], removed))
    reply.private_only = True
    return reply


def install(app: "LiteApp") -> None:
    r = app.router
    r.register(("商店", "看货"), show_shops, summary="看这个世界的商店、货价和你的钱包", usage="/团 商店 [店名]", topic="整备", private="self")
    r.register("买", buy, summary="整备时在当前地点的店里买东西", usage="/团 买 物品 [数量]", topic="整备", private="self")
    r.register("卖", sell, summary="整备时把物品卖给店里", usage="/团 卖 物品 [数量]", topic="整备", private="self")
    r.register(("给", "转交"), give, summary="把钱或物品交给同伴，随时可用", usage="/团 给 名字 物品 [数量]｜/团 给 名字 钱 数额",
               topic="整备", private="room")
    r.register("整备", player_outfit, summary="整备时查看进度；买好了说“好了”", usage="/团 整备 [好了|取消]", topic="整备", private="room")
    r.register("主持 整备", host_outfit, summary="开启整备：回合暂停，大家私聊采买；或提前收起", usage="/团 主持 整备 [分钟|收起]",
               topic="主持")
    r.register("主持 记账", host_ledger, summary="审稿时查看或撤回正文里的钱物变化", usage="/团 主持 记账 [撤回 序号]", topic="主持",
               private="self")

    async def tick(**_: Any) -> Reply:
        return await outfit_tick(app)
    app.hooks.on("tick", tick)

    async def paused(room_id: str, **_: Any) -> Reply:
        """Pausing ends 整备 first: the summary goes out now instead of landing in the middle of the pause."""
        return await close_outfit(app, room_id, "主持人暂停了故事")
    app.hooks.on("room_paused", paused)
