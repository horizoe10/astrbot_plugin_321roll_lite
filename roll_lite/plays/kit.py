"""Skills and items outside a check: view, use, equip, unequip, drop; scene refills; private-room switch.

Rules live in roll_lite/loadout.py.  Direct use is not turn-bound but waits
for a hosted action that is still settling, like 321Roll's world loadout.
These commands also work in a private chat with the bot; uses and equipment
changes are announced to the group in one line.
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from .. import loadout, messages, people, shared
from ..commands import Caller, Reply, UserError
from ..storage import now
from . import hosted

if TYPE_CHECKING:
    from ..app import LiteApp


def _mine(app: "LiteApp", caller: Caller) -> tuple[sqlite3.Row, sqlite3.Row]:
    room = shared.require_room(app, caller, "lobby", "running", "paused")
    actor = shared.require_actor(app, caller, room)
    if not actor["archetype_id"]:
        raise UserError("你还没有建卡。发送 /团 职业 查看职业，再用 /团 选职业 序号 角色名 建卡。")
    return room, actor


def _idle(app: "LiteApp", room: sqlite3.Row) -> None:
    with app.store.read() as c:
        turn = hosted.current_turn(c, room["id"])
    if turn is not None and turn["state"] == "resolving":
        raise UserError("有一个行动正在结算，等它结束后再使用。")


async def _announce(app: "LiteApp", caller: Caller, text: str) -> None:
    if caller.in_private:
        await app.notifier.send(caller.umo, text)


async def show(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller)
    with app.store.read() as c:
        if args.strip():
            name = args.strip().lstrip("@")
            actor = c.execute("SELECT * FROM actors WHERE room_id=? AND presence<>'left' AND (name=? OR user_name=?)",
                              (room["id"], name, name)).fetchone()
        else:
            actor = shared.actor_for(c, room["id"], caller.user_id)
    if actor is None:
        raise UserError("没有找到这个角色。" if args.strip() else "你还没有加入这一桌。发送 /团 加入 入座。")
    resources = [(r["name"], v["current"], v["max"]) for r in shared.world(room)["pack"]["resources"]
                 for k, v in loadout.state(actor)["resources"].items() if k == r["id"]]
    return Reply().say(messages.loadout_card(shared.actor_label(actor), loadout.entries(room, actor), resources,
                                             own=actor["user_id"] == caller.user_id))


async def use(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room, actor = _mine(app, caller)
    if not args.strip():
        raise UserError("写法：/团 使用 物品或技能名，例如 /团 使用 薄荷糖。检定时要加成，请在行动后写 [用 名称]。")
    _idle(app, room)
    entry = loadout.find(room, actor, args)
    async with app.lock(room["id"]):
        with app.store.tx() as c:
            fresh = c.execute("SELECT * FROM actors WHERE id=?", (actor["id"],)).fetchone()
            doc, changes = loadout.use(room, fresh, entry)
            loadout.save(c, actor["id"], doc)
            names = loadout.definitions(room)[2]
            shown = {names.get(k, k): v for k, v in changes.items()}
            line = f"{shared.actor_label(actor)} 使用「{entry['name']}」" + ("　" + "　".join(f"{k} {v:+d}" for k, v in shown.items()) if shown else "")
            app.store.add_event(c, room["id"], "play", line, actor_id=actor["id"], data={"loadout": "use", "ref": entry["ref"]})
            app.store.bump_room(c, room["id"])
            after = c.execute("SELECT * FROM actors WHERE id=?", (actor["id"],)).fetchone()
    left = next((e for e in loadout.entries(room, after) if e["ref"] == entry["ref"] and e["kind"] == entry["kind"]), None)
    await _announce(app, caller, line)
    return Reply().say(messages.loadout_receipt(shared.actor_label(actor), "使用", entry["name"], shown,
                                                loadout.effect_text(left) if left else "已用完"))


async def _equip(app: "LiteApp", caller: Caller, args: str, on: bool) -> Reply:
    room, actor = _mine(app, caller)
    _idle(app, room)
    entry = loadout.find(room, actor, args)
    verb = "装备" if on else "卸下"
    with app.store.tx() as c:
        doc = loadout.equip(room, actor, entry, on)
        loadout.save(c, actor["id"], doc)
        line = f"{shared.actor_label(actor)} {verb}了「{entry['name']}」"
        app.store.add_event(c, room["id"], "play", line, actor_id=actor["id"], data={"loadout": "equip" if on else "unequip"})
    await _announce(app, caller, line)
    return Reply().say(messages.loadout_receipt(shared.actor_label(actor), verb, entry["name"], {}, ""))


async def equip(app: "LiteApp", caller: Caller, args: str) -> Reply:
    return await _equip(app, caller, args, True)


async def unequip(app: "LiteApp", caller: Caller, args: str) -> Reply:
    return await _equip(app, caller, args, False)


async def drop(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room, actor = _mine(app, caller)
    _idle(app, room)
    words = args.split()
    quantity = int(words[-1]) if len(words) > 1 and words[-1].isdigit() else 1
    name = " ".join(words[:-1]) if len(words) > 1 and words[-1].isdigit() else args
    entry = loadout.find(room, actor, name)
    with app.store.tx() as c:
        doc = loadout.drop(room, actor, entry, quantity)
        loadout.save(c, actor["id"], doc)
        line = f"{shared.actor_label(actor)} 丢弃了「{entry['name']}」×{quantity}"
        app.store.add_event(c, room["id"], "play", line, actor_id=actor["id"], data={"loadout": "drop"})
    await _announce(app, caller, line)
    left = doc["items"].get(entry["ref"], {}).get("quantity", 0)
    return Reply().say(messages.loadout_receipt(shared.actor_label(actor), f"丢弃 {quantity} 个", entry["name"], {},
                                                f"×{left}" if left else "已经没有了"))


async def new_scene(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "running", "paused")
    shared.require_host(app, caller, room)
    _idle(app, room)
    with app.store.tx() as c:
        count = loadout.refill(c, room, "scene")
        app.store.add_event(c, room["id"], "system", "主持人确认进入新场景，按场景恢复的技能与物品次数已恢复。")
        app.store.bump_room(c, room["id"])
    return Reply().say(f"进入新场景：按“每幕恢复”的技能与物品次数已恢复（{count} 名角色）。")


async def switch(app: "LiteApp", caller: Caller, args: str) -> Reply:
    """Private chat only: pick which seated table private commands act on."""
    if caller.in_group:
        raise UserError("这个指令在私聊里使用，用来选择私聊操作的是哪一桌。")
    with app.store.read() as c:
        rooms = shared.seated_rooms(c, caller)
        picked = app.store.get_setting(c, shared.private_scope(caller), "private.room", None)
    if not rooms:
        raise UserError("你还没有在任何一桌入座。先在群里发送 /团 加入。")
    if args.strip().isdigit() and 1 <= int(args) <= len(rooms):
        chosen = rooms[int(args) - 1]
        with app.store.tx() as c:
            app.store.set_setting(c, shared.private_scope(caller), "private.room", chosen["id"])
        return Reply().say(f"私聊指令现在作用于群 {chosen['group_id']} 的《{chosen['title'].split(' · ')[0]}》。")
    current = next((r for r in rooms if r["id"] == picked), rooms[0])
    return Reply().say(messages.private_rooms([(r["group_id"], r["title"], r["id"] == current["id"]) for r in rooms]))


async def show_people(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller)
    with app.store.read() as c:
        met = people.people(c, room["id"])
    name = args.strip()
    if name:
        person = next((p for p in met if p["name"] == name), None) or next((p for p in met if name in p["name"]), None)
        if person is None:
            raise UserError(f"还没有遇到“{name}”。发送 /团 人物 查看登场人物。")
        return Reply().say(messages.person_card(person))
    return Reply().say(messages.people_list(met))


def install(app: "LiteApp") -> None:
    r = app.router
    t = "道具"
    r.register(("背包", "技能"), show, summary="查看技能与物品", usage="/团 背包 [角色名]", topic=t, private="self")
    r.register("使用", use, summary="直接使用技能或物品（不掷骰）", usage="/团 使用 名称", topic=t, private="self")
    r.register("装备", equip, summary="装备物品", usage="/团 装备 名称", topic=t, private="self")
    r.register("卸下", unequip, summary="卸下装备", usage="/团 卸下 名称", topic=t, private="self")
    r.register("丢弃", drop, summary="丢弃物品", usage="/团 丢弃 名称 [数量]", topic=t, private="self")
    r.register("主持 新场景", new_scene, summary="确认进入新场景，恢复按场景计的次数", topic="主持")
    r.register("切换", switch, summary="私聊里选择操作哪一桌", usage="/团 切换 [序号]", topic="基础", group_only=False)
    r.register("人物", show_people, summary="查看登场人物与他们对队伍的态度", usage="/团 人物 [名字]", topic="交涉", private="self")

