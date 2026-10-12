"""Flashbacks and bonds: two plays that tie the characters to their past and to each other.

闪回  /团 闪回 [资源名] 回忆     once per act a player pays 1 point of a resource to write a past moment
                                 into the story; the next narration makes it true and the character's next
                                 check gets FLASHBACK_BONUS.
羁绊  /团 羁绊 角色名 关系       a bond between two characters, live once the other player agrees; the
                                 narration keeps it in mind, aid between bonded characters gets BOND_AID_BONUS,
                                 and the ending shows the map of every bond.

Like the banter plays neither takes a turn or calls the model on its own: what they leave waits in the
room's 'ties' data and reaches the model with the next narration (banter.story_notes calls story_lines).
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from .. import loadout, messages, shared
from ..commands import Caller, Reply, UserError
from ..storage import dumps, loads, now

if TYPE_CHECKING:
    from ..app import LiteApp

FLASHBACK_BONUS = 2
FLASHBACK_COST = 1
FLASHBACK_LIMIT = 120
BOND_LIMIT = 40
BONDS_PER_ACTOR = 3
BOND_AID_BONUS = 3
ACCEPT = ("同意", "接受", "确认")
REFUSE = ("拒绝", "婉拒")
BREAK = ("解除", "断绝")


# ---------------------------------------------------------------- data
def data(room: sqlite3.Row) -> dict[str, Any]:
    return loads(room["data_json"], {}).get("ties", {})


def _load(c: sqlite3.Connection, room_id: str) -> tuple[sqlite3.Row, dict[str, Any]]:
    room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    return room, data(room)


def _save(c: sqlite3.Connection, room_id: str, value: dict[str, Any]) -> None:
    row = c.execute("SELECT data_json FROM rooms WHERE id=?", (room_id,)).fetchone()
    whole = loads(row["data_json"], {})
    whole["ties"] = value
    c.execute("UPDATE rooms SET data_json=? WHERE id=?", (dumps(whole), room_id))


def _next(value: dict[str, Any]) -> int:
    value["seq"] = int(value.get("seq") or 0) + 1
    return value["seq"]


def _actor_data(c: sqlite3.Connection, actor_id: str) -> dict[str, Any]:
    return loads(c.execute("SELECT data_json FROM actors WHERE id=?", (actor_id,)).fetchone()["data_json"], {})


def _set_actor_data(c: sqlite3.Connection, actor_id: str, value: dict[str, Any]) -> None:
    c.execute("UPDATE actors SET data_json=? WHERE id=?", (dumps(value), actor_id))


def active_bonds(room: sqlite3.Row) -> list[dict[str, Any]]:
    return [b for b in data(room).get("bonds") or [] if b["state"] == "active"]


def bond_between(room: sqlite3.Row, one: str, other: str) -> dict[str, Any] | None:
    return next((b for b in active_bonds(room) if {b["a_id"], b["b_id"]} == {one, other}), None)


def aid_bonus(room: sqlite3.Row, helper_id: str, target_id: str) -> tuple[int, str]:
    """The aid bonus between two characters and the bond that raises it ('' when there is none)."""
    from .banter import AID_BONUS
    found = bond_between(room, helper_id, target_id)
    return (BOND_AID_BONUS, found["text"]) if found else (AID_BONUS, "")


# ---------------------------------------------------------------- narration
def story_lines(room: sqlite3.Row, mark: dict[str, Any]) -> list[str]:
    """Flashbacks waiting to be told and the bonds between characters at the table; mark records what was seen."""
    value = data(room)
    lines: list[str] = []
    flashbacks = value.get("flashbacks") or []
    if flashbacks:
        lines.append("闪回（玩家花了资源补写的过去，平台已经认可）：在正文里用一两句回忆把它写成真，"
                     "不推翻已经发生的事；和已知事实冲突时写成部分成真或另有隐情："
                     + "；".join(f"{f['actor']}——“{f['text']}”" for f in flashbacks))
        mark["flashbacks"] = [f["n"] for f in flashbacks]
    bonds = active_bonds(room)
    if bonds:
        fresh = [b for b in bonds if b.get("fresh")]
        lines.append("玩家角色之间的羁绊（两人同场时自然带出这层关系的默契或张力，不替他们说话、行动或做决定）："
                     + "；".join(f"{b['a']} 与 {b['b']}：{b['text']}" for b in bonds)
                     + ("。其中 " + "、".join(f"{b['a']} 与 {b['b']}" for b in fresh) + " 的羁绊是刚刚说开的，可以给一个小小的呼应。"
                        if fresh else ""))
        mark["fresh_bonds"] = [b["n"] for b in fresh]
    return lines


def consume(c: sqlite3.Connection, room_id: str, mark: dict[str, Any]) -> None:
    """After a narration is committed: the flashbacks it told are done and fresh bonds are no longer fresh."""
    told, fresh = set(mark.get("flashbacks") or []), set(mark.get("fresh_bonds") or [])
    if not told and not fresh:
        return
    _, value = _load(c, room_id)
    value["flashbacks"] = [f for f in value.get("flashbacks") or [] if f["n"] not in told]
    for item in value.get("bonds") or []:
        if item["n"] in fresh:
            item["fresh"] = False
    _save(c, room_id, value)


def flashback_bonus(actor: sqlite3.Row) -> dict[str, Any] | None:
    """The flashback still waiting for this actor's next check."""
    return loads(actor["data_json"], {}).get("flashback_bonus")


def spend(c: sqlite3.Connection, actor_id: str, receipt: dict[str, Any]) -> None:
    """A check that used the flashback bonus clears it."""
    if receipt.get("flashback"):
        value = _actor_data(c, actor_id)
        value.pop("flashback_bonus", None)
        _set_actor_data(c, actor_id, value)


def reveal(c: sqlite3.Connection, room: sqlite3.Row) -> Any | None:
    """The map of every bond, shown when the story ends."""
    bonds = active_bonds(room)
    return messages.bond_map(_cast(c, room), _rows(bonds), [], finale=True) if bonds else None


# ---------------------------------------------------------------- flashback
def _resource(room: sqlite3.Row, doc: dict[str, Any], text: str) -> tuple[str, str, str]:
    """(resource ref, its name, the memory): a leading resource name picks what to pay with, otherwise the fullest one."""
    pack = shared.world(room)["pack"]
    names = {r["id"]: r["name"] for r in pack["resources"]}
    head, _, rest = text.replace("：", " ").replace(":", " ").partition(" ")
    plain = lambda name: name.strip("〈〉<>《》[]【】")
    chosen = next((ref for ref, name in names.items() if head and plain(head) == plain(name)), None)
    if chosen is not None:
        slot = doc["resources"].get(chosen)
        if not slot or slot["current"] - FLASHBACK_COST <= slot.get("min", 0):
            raise UserError(f"{names[chosen]}只剩最后一点，不能拿来闪回。换一项资源，或不写资源名让我挑最充裕的一项。")
        return chosen, names[chosen], rest.strip()
    usable = [(ref, slot) for ref, slot in doc["resources"].items()
              if ref in names and slot["current"] - FLASHBACK_COST > slot.get("min", 0)]
    if not usable:
        raise UserError("你的资源都只剩最后一点，没有余力闪回。休整一下再来。")
    order = list(names)
    ref, _ = max(usable, key=lambda item: (item[1]["current"] / max(1, item[1].get("max") or 1), -order.index(item[0])))
    return ref, names[ref], text


def _flashback_left(room: sqlite3.Row, actor: sqlite3.Row) -> str:
    own = loads(actor["data_json"], {})
    waiting = own.get("flashback_bonus")
    used = own.get("flashback_act") == room["act"]
    line = "这一幕你已经闪回过了，下一幕再来。" if used else "这一幕你还能闪回一次。"
    if waiting:
        line += f"上次闪回的“{waiting['text'][:20]}”还在等你下一次检定兑现 +{waiting['bonus']}。"
    return line


async def flashback(app: "LiteApp", caller: Caller, args: str) -> Reply:
    from .banter import _running
    room = _running(app, caller, "闪回")
    actor = shared.require_actor(app, caller, room)
    text = args.strip()
    if not text:
        return Reply().say(messages.flashback_guide(_flashback_left(room, actor)))
    if actor["presence"] != "present" or not actor["archetype_id"]:
        raise UserError("建好卡、在场的角色才能闪回。")
    if loads(actor["data_json"], {}).get("flashback_act") == room["act"]:
        raise UserError("这一幕你已经闪回过了，下一幕再来。")
    ref, name, text = _resource(room, loadout.state(actor), text)
    text = text.strip("“”\"'「」").strip()
    if not 4 <= len(text) <= FLASHBACK_LIMIT:
        raise UserError(f"写一段 4–{FLASHBACK_LIMIT} 字的回忆，例如 {messages.cmd('/团 闪回 我早就把备用钥匙藏在戏箱里')}。")
    label = shared.actor_label(actor)
    with app.store.tx() as c:
        actor = c.execute("SELECT * FROM actors WHERE id=?", (actor["id"],)).fetchone()
        doc = loadout.state(actor)
        slot = doc["resources"][ref]
        slot["current"] -= FLASHBACK_COST
        loadout.save(c, actor["id"], doc)
        own = _actor_data(c, actor["id"])
        own.update(flashback_act=room["act"], flashback_bonus={"text": text, "bonus": FLASHBACK_BONUS})
        _set_actor_data(c, actor["id"], own)
        room, value = _load(c, room["id"])
        value.setdefault("flashbacks", []).append({"n": _next(value), "actor_id": actor["id"], "actor": label, "text": text,
                                                   "act": room["act"], "at": now()})
        _save(c, room["id"], value)
        app.store.add_event(c, room["id"], "system", f"{label} 闪回：{text}", actor_id=actor["id"])
    return Reply().say(messages.flashback_told(label, text, name, -FLASHBACK_COST, slot["current"],
                                               slot.get("max", slot["current"]), FLASHBACK_BONUS))


# ---------------------------------------------------------------- bonds
def _cast(c: sqlite3.Connection, room: sqlite3.Row) -> list[dict[str, str]]:
    roles = {a["id"]: a["name"] for a in shared.world(room)["pack"]["archetypes"]}
    return [{"id": a["id"], "name": shared.actor_label(a), "role": roles.get(a["archetype_id"], "")}
            for a in c.execute("SELECT * FROM actors WHERE room_id=? AND presence<>'left' ORDER BY order_index,created_at",
                               (room["id"],))]


def _rows(bonds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"a": b["a"], "b": b["b"], "a_id": b["a_id"], "b_id": b["b_id"], "text": b["text"]} for b in bonds]


def board(c: sqlite3.Connection, room: sqlite3.Row, note: str = "") -> Any:
    pending = [b for b in data(room).get("bonds") or [] if b["state"] == "pending"]
    return messages.bond_map(_cast(c, room), _rows(active_bonds(room)), _rows(pending), note=note)


async def bond(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "lobby", "running", "paused")
    words = args.split(maxsplit=1)
    if not words and not caller.mentions:
        with app.store.read() as c:
            return Reply().say(board(c, room))
    me = shared.require_actor(app, caller, room)
    head, rest = (words[0], words[1] if len(words) > 1 else "") if words else ("", "")
    if head in ACCEPT or head in REFUSE:
        return _answer(app, caller, room, me, rest, head in ACCEPT)
    if head in BREAK:
        return _break(app, caller, room, me, rest)
    who, text = shared.split_target(args, caller)
    text = text.strip().strip("“”\"'「」").strip()
    with app.store.read() as c:
        other = shared.find_actor(c, room["id"], who, caller.mentions)
    if other["id"] == me["id"]:
        raise UserError("羁绊要和同桌的另一位结。")
    if not 2 <= len(text) <= BOND_LIMIT:
        raise UserError(f"写上你们是什么关系（2–{BOND_LIMIT} 字），例如 /团 羁绊 {shared.actor_label(other)} 发小，欠他一条命。")
    with app.store.tx() as c:
        return Reply().say(offer(c, room["id"], me, other, text))


def offer(c: sqlite3.Connection, room_id: str, me: sqlite3.Row, other: sqlite3.Row, text: str) -> Any:
    """Record a pending bond from me to other and return the message that asks other to answer."""
    names = shared.actor_label(me), shared.actor_label(other)
    room, value = _load(c, room_id)
    bonds = value.setdefault("bonds", [])
    pair = {me["id"], other["id"]}
    waiting = next((b for b in bonds if b["state"] == "pending" and {b["a_id"], b["b_id"]} == pair), None)
    if waiting is not None and waiting["b_id"] == me["id"]:
        raise UserError(f"{names[1]} 已经向你提了羁绊“{waiting['text']}”，发送 /团 羁绊 同意 接受，或 /团 羁绊 拒绝 后再提你的。")
    if waiting is not None:
        raise UserError(f"你提的羁绊“{waiting['text']}”还在等 {names[1]} 回应，对方同意或拒绝后才能再提。")
    renewing = any(b["state"] == "active" and {b["a_id"], b["b_id"]} == pair for b in bonds)
    if not renewing:
        for actor_id, name in ((me["id"], names[0]), (other["id"], names[1])):
            if sum(1 for b in bonds if b["state"] == "active" and actor_id in (b["a_id"], b["b_id"])) >= BONDS_PER_ACTOR:
                raise UserError(f"{name} 已经有 {BONDS_PER_ACTOR} 条羁绊了，先用 /团 羁绊 解除 角色名 解开一条。")
    bonds.append({"n": _next(value), "a_id": me["id"], "a": names[0], "b_id": other["id"], "b": names[1], "text": text,
                  "state": "pending", "at": now()})
    _save(c, room_id, value)
    return messages.bond_proposed(names[0], names[1], text, other["user_id"], other["user_name"], renewing)


def _answer(app: "LiteApp", caller: Caller, room: sqlite3.Row, me: sqlite3.Row, who: str, accept: bool) -> Reply:
    with app.store.tx() as c:
        room, value = _load(c, room["id"])
        bonds = value.get("bonds") or []
        waiting = [b for b in bonds if b["state"] == "pending" and b["b_id"] == me["id"]]
        if who.strip() or caller.mentions:
            proposer = shared.find_actor(c, room["id"], who, caller.mentions)
            waiting = [b for b in waiting if b["a_id"] == proposer["id"]]
        if not waiting:
            raise UserError("现在没有等你回应的羁绊。想和别人结羁绊，发送 /团 羁绊 角色名 关系。")
        chosen = waiting[-1]
        if accept:
            pair = {chosen["a_id"], chosen["b_id"]}
            value["bonds"] = [b for b in bonds if not (b["state"] == "active" and {b["a_id"], b["b_id"]} == pair)]
            chosen.update(state="active", fresh=True, since=now())
            app.store.add_event(c, room["id"], "system", f"{chosen['a']} 与 {chosen['b']} 结下羁绊：{chosen['text']}")
        else:
            value["bonds"] = [b for b in bonds if b is not chosen]
        _save(c, room["id"], value)
    if not accept:
        return Reply().say(f"{chosen['b']} 婉拒了 {chosen['a']} 提的羁绊“{chosen['text']}”。")
    return Reply().say(messages.bond_formed(chosen["a"], chosen["b"], chosen["text"], BOND_AID_BONUS))


def _break(app: "LiteApp", caller: Caller, room: sqlite3.Row, me: sqlite3.Row, who: str) -> Reply:
    with app.store.tx() as c:
        other = shared.find_actor(c, room["id"], who, caller.mentions)
        room, value = _load(c, room["id"])
        bonds = value.get("bonds") or []
        found = next((b for b in bonds if b["state"] == "active" and {b["a_id"], b["b_id"]} == {me["id"], other["id"]}), None)
        if found is None:
            raise UserError(f"你和 {shared.actor_label(other)} 之间没有羁绊。发送 /团 羁绊 查看这一桌的关系图。")
        value["bonds"] = [b for b in bonds if b is not found]
        _save(c, room["id"], value)
        app.store.add_event(c, room["id"], "system", f"{found['a']} 与 {found['b']} 的羁绊解开了")
    return Reply().say(f"{shared.actor_label(me)} 与 {shared.actor_label(other)} 的羁绊“{found['text']}”解开了，之后的正文不再提这层关系。")


def install(app: "LiteApp") -> None:
    r = app.router
    r.register("闪回", flashback, summary="花 1 点资源补写一段过去：下一段正文写成真，下次检定 +2，每幕一次",
               usage="/团 闪回 [资源名] <回忆>｜/团 闪回", topic="互动", private="room")
    r.register("羁绊", bond, summary="和同伴结下关系：对方同意后生效，正文会记得，互相援手 +3，终章画关系图",
               usage="/团 羁绊 <角色名> <关系>｜/团 羁绊 同意｜/团 羁绊 拒绝｜/团 羁绊 解除 <角色名>｜/团 羁绊",
               topic="互动", private="room")
