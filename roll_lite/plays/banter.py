"""Group-chat plays of the Lite edition: lines in character, heckles from the gallery, a hand from a
teammate, secret notes and the X card.

None of them takes a turn or calls the model on its own.  What they leave waits in the room's
'banter' data and reaches the model with the next narration (story_notes); committing that
narration clears what it used (consume).  Aid is the exception: it rides on the open turn and
joins that turn's check.
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from .. import messages, shared
from ..commands import Caller, Reply, UserError
from ..storage import dumps, loads, now

if TYPE_CHECKING:
    from ..app import LiteApp

LINE_LIMIT = 120
LINES_PER_ACTOR = 2          # pending lines one character may leave before the next narration
HECKLE_LIMIT = 60
HECKLES_PER_ACT = 2          # heckles the story takes up in one act, so the gallery spices it without steering
AID_BONUS = 2
LETTER_LIMIT = 120
LETTERS_IN_CONTEXT = 6


# ---------------------------------------------------------------- data
def data(room: sqlite3.Row) -> dict[str, Any]:
    return loads(room["data_json"], {}).get("banter", {})


def _load(c: sqlite3.Connection, room_id: str) -> tuple[sqlite3.Row, dict[str, Any]]:
    room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    return room, data(room)


def _save(c: sqlite3.Connection, room_id: str, value: dict[str, Any]) -> None:
    row = c.execute("SELECT data_json FROM rooms WHERE id=?", (room_id,)).fetchone()
    whole = loads(row["data_json"], {})
    whole["banter"] = value
    c.execute("UPDATE rooms SET data_json=? WHERE id=?", (dumps(whole), room_id))


def _next(value: dict[str, Any]) -> int:
    value["seq"] = int(value.get("seq") or 0) + 1
    return value["seq"]


def _running(app: "LiteApp", caller: Caller, what: str) -> sqlite3.Row:
    """The open room when its story is running; a paused one says when the play comes back."""
    room = shared.require_room(app, caller, "running", "paused")
    if room["state"] == "paused":
        raise UserError(shared.paused_step(room, what))
    if shared.ending_step(room, what):           # nothing more gets written into the story after the finale
        raise UserError(shared.ending_step(room, what))
    return room


def _heckles_left(room: sqlite3.Row) -> int:
    return max(0, HECKLES_PER_ACT - int((data(room).get("heckles_used") or {}).get(str(room["act"]), 0)))


def _backing_target(heckles: list[dict[str, Any]], rest: str, user_id: str) -> dict[str, Any]:
    """'+1' backs the latest idea of someone else, '+1 3' or '+3' backs idea 3."""
    words = rest.split()
    if words and words[0] == "1" and len(words) > 1:
        words = words[1:]
    elif words == ["1"]:
        words = []
    if words:
        if not words[0].isdigit():
            raise UserError("附和写序号，例如 /团 起哄 +1 2；发送 /团 起哄 查看起哄板。")
        target = next((h for h in heckles if h["index"] == int(words[0])), None)
        if target is None:
            raise UserError(f"起哄板上没有第 {words[0]} 条。发送 /团 起哄 查看起哄板。")
    else:
        others = [h for h in heckles if h["user_id"] != user_id]
        target = others[-1] if others else (heckles[-1] if heckles else None)
        if target is None:
            raise UserError("起哄板上还没有起哄，发送 /团 起哄 点子 提第一个。")
    if target["user_id"] == user_id:
        raise UserError("不能附和自己提的起哄，等别人来附和吧。")
    return target


def top_heckle(room: sqlite3.Row) -> dict[str, Any] | None:
    """The heckle with most backers (earliest on a tie), unless this act already took its share."""
    value = data(room)
    if int((value.get("heckles_used") or {}).get(str(room["act"]), 0)) >= HECKLES_PER_ACT:
        return None
    heckles = value.get("heckles") or []
    return min(heckles, key=lambda h: (-len(h["fans"]), h["n"])) if heckles else None


def story_notes(room: sqlite3.Row) -> tuple[list[str], dict[str, Any]]:
    """Lines for the narration's table notes, and the mark consume() needs once that narration is committed."""
    value = data(room)
    lines: list[str] = []
    mark: dict[str, Any] = {"seq": int(value.get("seq") or 0)}
    said = value.get("lines") or []
    if said:
        lines.append("场上台词（玩家角色刚才当众说的话，原话不改；让在场人物在正文里自然回应）："
                     + "；".join(f"{l['actor']}：“{l['text']}”" + (f"（回应：{l['reply_to']}）" if l.get("reply_to") else "")
                                for l in said))
    heckle = top_heckle(room)
    if heckle is not None:
        lines.append(f"围观群众起哄：“{heckle['text']}”。把它写成正文里一个不喧宾夺主的小插曲，不点名是谁提的，"
                     "不替玩家角色行动，也不改变已经结算的结果。")
        mark["heckle"] = heckle["n"]
    card = value.get("xcard") or {}
    if card.get("pending"):
        lines.append("【安全】有玩家举了 X 卡" + (f"（{card['note']}）" if card.get("note") else "")
                     + "：立刻把剧情从刚才令人不适的内容上转开，之后不再描写或提起，也不追问是谁。")
        mark["xcard"] = True
    letters = (value.get("letters") or [])[-LETTERS_IN_CONTEXT:]
    if letters:
        lines.append("玩家之间的密信（只给主持看：正文不得公开或复述内容，可以借它埋伏笔）："
                     + "；".join(f"{l['from']}→{l['to']}：{l['text']}" for l in letters))
    from . import ties
    lines += ties.story_lines(room, mark)
    return lines, mark


def consume(c: sqlite3.Connection, room_id: str, mark: dict[str, Any] | None) -> list[Any]:
    """After a narration is committed: drop the lines and heckles it saw; returns what the group should be told."""
    if not mark:
        return []
    from . import ties
    ties.consume(c, room_id, mark)
    room, value = _load(c, room_id)
    seq = int(mark.get("seq") or 0)
    notices: list[Any] = []
    if mark.get("heckle"):
        used = next((h for h in value.get("heckles") or [] if h["n"] == mark["heckle"]), None)
        if used is not None:
            counts = value.setdefault("heckles_used", {})
            counts[str(room["act"])] = int(counts.get(str(room["act"]), 0)) + 1
            notices.append(messages.heckle_adopted(used["text"], len(used["fans"]) + 1))
    value["lines"] = [l for l in value.get("lines") or [] if l["n"] > seq]
    value["heckles"] = [h for h in value.get("heckles") or [] if h["n"] > seq]     # the window closes here
    if mark.get("xcard"):
        value["xcard"] = {**(value.get("xcard") or {}), "pending": False, "note": ""}
    _save(c, room_id, value)
    return notices


def reveal(room: sqlite3.Row) -> Any | None:
    """Every secret note of the story, shown when it ends."""
    letters = data(room).get("letters") or []
    return messages.letters_revealed([(l["from"], l["to"], l["text"]) for l in letters]) if letters else None


def xcard_count(room: sqlite3.Row) -> int:
    return int((data(room).get("xcard") or {}).get("count") or 0)


# ---------------------------------------------------------------- commands
async def say(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _running(app, caller, "台词")
    actor = shared.require_actor(app, caller, room)
    text = args.strip().strip("“”\"'「」").strip()
    if not 1 <= len(text) <= LINE_LIMIT:
        raise UserError(f"写一句 {LINE_LIMIT} 字以内的台词，例如 /团 说 你们先走，我断后。")
    label = shared.actor_label(actor)
    reply_to = " ".join(caller.quote.split())[:30]
    with app.store.tx() as c:
        room, value = _load(c, room["id"])
        lines = value.setdefault("lines", [])
        if sum(1 for l in lines if l["actor_id"] == actor["id"]) >= LINES_PER_ACTOR:
            raise UserError(f"你已经说了 {LINES_PER_ACTOR} 句，等下一段正文出来再接着说。")
        lines.append({"n": _next(value), "actor_id": actor["id"], "actor": label, "text": text,
                      "reply_to": reply_to, "at": now()})
        _save(c, room["id"], value)
        app.store.add_event(c, room["id"], "system", f"{label}：“{text}”", actor_id=actor["id"])
    return Reply().say(messages.line_said(label, text, reply_to))


async def heckle(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _running(app, caller, "起哄")
    words = args.strip()
    with app.store.tx() as c:
        room, value = _load(c, room["id"])
        heckles = value.setdefault("heckles", [])
        if words and not _heckles_left(room):
            raise UserError(f"这一幕的起哄名额用完了（每幕采纳 {HECKLES_PER_ACT} 条），换幕后再来。")
        if words.startswith(("+", "＋")):
            target = _backing_target(heckles, words.lstrip("+＋"), caller.user_id)
            if any(caller.user_id in h["fans"] for h in heckles):
                raise UserError("这一段你已经附和过了。")
            target["fans"].append(caller.user_id)
        elif words:
            if not 2 <= len(words) <= HECKLE_LIMIT:
                raise UserError(f"起哄写 2–{HECKLE_LIMIT} 字，例如 {messages.cmd('/团 起哄 让钟楼的灯突然灭掉')}。")
            if any(h["user_id"] == caller.user_id for h in heckles):
                raise UserError("这一段你已经起哄过了，可以发送 /团 起哄 +1 附和别人。")
            heckles.append({"n": _next(value), "index": len(heckles) + 1, "user_id": caller.user_id,
                            "user_name": caller.user_name, "text": words, "fans": []})
        _save(c, room["id"], value)
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
    rows = [(h["index"], h["text"], len(h["fans"]) + 1, h.get("user_name") or "") for h in data(room).get("heckles") or []]
    return Reply().say(messages.heckle_board(rows, _heckles_left(room), HECKLES_PER_ACT))


async def aid(app: "LiteApp", caller: Caller, args: str) -> Reply:
    from .hosted import current_turn
    from .ties import aid_bonus
    room = _running(app, caller, "援手")
    helper = shared.require_actor(app, caller, room)
    if helper["presence"] != "present" or not helper["archetype_id"]:
        raise UserError("建好卡、在场的同伴才能出手相助。")
    text = args.strip()[:60]
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
        turn = current_turn(c, room["id"])
        if turn is None or turn["state"] != "awaiting":
            raise UserError("现在没有等待行动的回合。")
        if "rush" in loads(turn["data_json"], {}):
            raise UserError("快团里大家同时行动，援手留到普通回合再用。")
        if turn["actor_id"] == helper["id"]:
            raise UserError("援手是帮同伴的；轮到你时直接行动就好。")
        if loads(helper["data_json"], {}).get("aid_act") == room["act"]:
            raise UserError("这一幕你已经出手相助过了。")
        turn_data = loads(turn["data_json"], {})
        if turn_data.get("aid"):
            raise UserError(f"{turn_data['aid']['name']} 已经在帮忙了。")
        turn_data["aid"] = {"actor_id": helper["id"], "name": shared.actor_label(helper), "text": text}
        c.execute("UPDATE turns SET data_json=? WHERE id=?", (dumps(turn_data), turn["id"]))
        target = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
    bonus, bond = aid_bonus(room, helper["id"], target["id"])
    return Reply().say(messages.aid_offered(shared.actor_label(helper), shared.actor_label(target), text, bonus, bond))


async def letter(app: "LiteApp", caller: Caller, args: str) -> Reply:
    if not caller.in_private:
        raise UserError("密信要私聊 bot 发送，群里发就不是密信了。写法：/团 密信 角色名 内容")
    room = shared.require_room(app, caller, "running", "paused")
    sender = shared.require_actor(app, caller, room)
    if not args.strip():
        mine = [l for l in data(room).get("letters") or [] if sender["id"] in (l["from_id"], l["to_id"])]
        return Reply().say(messages.letter_inbox(shared.actor_label(sender), [
            ("收到", l["from"], l["text"]) if l["to_id"] == sender["id"] else ("递出", l["to"], l["text"]) for l in mine[-10:]]))
    who, text = shared.split_target(args, caller)
    with app.store.read() as c:
        target = shared.find_actor(c, room["id"], who, caller.mentions)
        target_umo = shared.private_umo(c, room["platform"], target["user_id"])
    if target["id"] == sender["id"]:
        raise UserError("纸条要递给同桌的另一位。")
    text = text.strip()
    if not 1 <= len(text) <= LETTER_LIMIT:
        raise UserError(f"纸条写 {LETTER_LIMIT} 字以内。写法：/团 密信 角色名 内容")
    names = shared.actor_label(sender), shared.actor_label(target)
    with app.store.tx() as c:
        room, value = _load(c, room["id"])
        value.setdefault("letters", []).append({"n": _next(value), "from_id": sender["id"], "from": names[0],
                                                "to_id": target["id"], "to": names[1], "text": text,
                                                "act": room["act"], "at": now()})
        _save(c, room["id"], value)
        app.store.add_event(c, room["id"], "system", f"{names[0]} 给 {names[1]} 递了一张纸条", actor_id=sender["id"])
    await app.notifier.send(room["umo"], messages.letter_passed(*names, delivered=bool(target_umo),
                                                                user_id=target["user_id"], user_name=target["user_name"]))
    if target_umo:
        await app.notifier.send(target_umo, messages.letter_received(names[0], names[1], text))
    return Reply().say(messages.letter_sent(names[1], bool(target_umo)))


async def xcard(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "running", "paused")
    with app.store.read() as c:
        seated = shared.actor_for(c, room["id"], caller.user_id) is not None
    if not seated and caller.in_private:
        shared.require_actor(app, caller, room)
    with app.store.tx() as c:
        room, value = _load(c, room["id"])
        card = value.get("xcard") or {}
        value["xcard"] = {"pending": True, "note": args.strip()[:60], "count": int(card.get("count") or 0) + 1}
        _save(c, room["id"], value)
        app.store.add_event(c, room["id"], "system", "有人举了 X 卡")
    pace = loads(room["data_json"], {}).get("hosted", {}).get("pacing") or {}
    stage = "epilogue" if pace.get("epilogue") else "finale" if pace.get("finale") else ""
    await app.notifier.send(room["umo"], messages.xcard_raised(stage))
    return Reply().say(messages.xcard_ack(caller.in_private, seated, stage))


def install(app: "LiteApp") -> None:
    r = app.router
    r.register(("说", "台词"), say, summary="当众说一句台词，不占回合，下一段正文里会有人回应",
               usage="/团 说 <台词>（可以引用回复 bot 的正文）", topic="互动", private="room")
    r.register("起哄", heckle, summary="围观起哄，附和最多的一条会写进下一段正文；没入座也能玩",
               usage="/团 起哄 <点子>｜/团 起哄 +1 [序号]｜/团 起哄", topic="互动")
    r.register("援手", aid, summary="帮当前行动的同伴一把：检定 +2，失败一起承担，每幕一次",
               usage="/团 援手 [怎么帮]", topic="互动", private="room")
    r.register("密信", letter, summary="私聊给同桌递纸条，群里只看到递了纸条，终章公开",
               usage="/团 密信 <角色名> <内容>｜/团 密信", topic="互动", private="self")
    r.register(("X卡", "X", "x", "x卡"), xcard, summary="匿名举 X 卡，故事避开刚才让人不适的内容（建议私聊发）",
               usage="/团 X [可选说明]", topic="互动", private="self")

