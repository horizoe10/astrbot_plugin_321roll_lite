"""快团: the whole party acts at once instead of in turn.

The host switches it on (/团 主持 快团 开).  A rush round is one turn row whose data holds the
submissions: every present player may choose A–D or write an action; each submission is rolled at
once and its status goes out, and when everyone has submitted or skipped, or the round's window
closes, one narration tells all of it.  Players who did not submit only watch that round.  The
options are shared by the party and the next round starts with everyone again.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from astrbot.api import logger

from .. import loadout, messages, quota, shared
from ..commands import Caller, Reply, UserError
from ..engine.gateway import EngineCallFailed
from ..fun import luck
from ..rooms import lifecycle
from ..storage import dumps, loads, now
from . import hosted, ties

if TYPE_CHECKING:
    from ..app import LiteApp

WINDOW_SECONDS = 180       # a rush round never waits longer than this, even on a table without a limit


# ---------------------------------------------------------------- state
def enabled(room: sqlite3.Row) -> bool:
    return bool(hosted.hosted_data(room).get("rush"))


def is_round(turn: sqlite3.Row | None) -> bool:
    return turn is not None and "rush" in loads(turn["data_json"], {})


def entries(turn: sqlite3.Row) -> dict[str, Any]:
    return loads(turn["data_json"], {}).get("rush", {}).get("entries", {})


def window(app: "LiteApp", room: sqlite3.Row) -> int:
    seconds = hosted.turn_seconds(app, room)
    return min(seconds, WINDOW_SECONDS) if seconds > 0 else WINDOW_SECONDS


def _deadline(app: "LiteApp", room: sqlite3.Row) -> str:
    return (datetime.now(UTC) + timedelta(seconds=window(app, room))).isoformat(timespec="seconds")


def _write(c: sqlite3.Connection, turn_id: str, rush: dict[str, Any] | None, **columns: Any) -> sqlite3.Row:
    data = loads(c.execute("SELECT data_json FROM turns WHERE id=?", (turn_id,)).fetchone()["data_json"], {})
    if rush is None:
        data.pop("rush", None)
    else:
        data["rush"] = rush
    sets = ",".join(f"{k}=?" for k in columns)
    c.execute(f"UPDATE turns SET data_json=?{',' + sets if sets else ''},updated_at=? WHERE id=?",
              (dumps(data), *columns.values(), now(), turn_id))
    return c.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()


def open_round(app: "LiteApp", c: sqlite3.Connection, room: sqlite3.Row, choices: list[dict[str, Any]],
               round_number: int) -> sqlite3.Row | None:
    actors = hosted.eligible_actors(c, room["id"])
    if not actors:
        return None
    turn = hosted.open_turn(app, c, room, actors[0], choices, round_number, cheat_sheet=False)
    return _write(c, turn["id"], {"entries": {}}, deadline_at=_deadline(app, room))


def members(c: sqlite3.Connection, room_id: str, turn: sqlite3.Row) -> list[tuple[sqlite3.Row, bool]]:
    done = entries(turn)
    return [(a, a["id"] in done) for a in hosted.eligible_actors(c, room_id)]


def prompt(app: "LiteApp", room: sqlite3.Row, turn: sqlite3.Row) -> Any:
    rules = shared.rules(room)
    with app.store.read() as c:
        rows = members(c, room["id"], turn)
        others = hosted.others_guide(c, room, None, turn)
    from . import pacing
    closing = pacing.closing_open(room)
    choices = [{"label": ch["label"], "text": ch["text"], "tag": messages.check_tag(rules, ch["check"]),
                **({"closing": ch["closing"]} if closing and ch.get("closing") else {})}
               for ch in loads(turn["choices_json"], [])]
    minutes = None
    if turn["deadline_at"]:
        minutes = max(1, round((datetime.fromisoformat(turn["deadline_at"]) - datetime.now(UTC)).total_seconds() / 60))
    return messages.rush_prompt(turn["round"], choices, minutes, rules.get("action_mode", "hybrid"),
                                [(shared.actor_label(a), a["user_name"], a["user_id"], done) for a, done in rows], others=others,
                                pace=pacing.band(room, turn["round"]))


def my_round(app: "LiteApp", caller: Caller) -> tuple[sqlite3.Row, sqlite3.Row, sqlite3.Row] | None:
    """(room, actor, turn) when the caller's table is in a rush round, else None."""
    try:
        room = shared.require_room(app, caller, "running")
    except UserError:
        return None
    with app.store.read() as c:
        turn = hosted.current_turn(c, room["id"])
    if not is_round(turn):
        return None
    from .. import economy
    economy.guard(room)
    shared.require_play(app, caller, "playActions")
    actor = shared.require_actor(app, caller, room)
    if turn["state"] != "awaiting":
        raise UserError("这一轮的正文正在写，等它出来再交下一轮的行动。")
    if actor["presence"] != "present" or not actor["archetype_id"]:
        raise UserError("建好卡、在场的玩家才能交行动。")
    if actor["id"] in entries(turn):
        raise UserError("这一轮你已经交过了，等其他人交齐。")
    return room, actor, turn


# ---------------------------------------------------------------- submissions
async def submit(app: "LiteApp", room: sqlite3.Row, actor: sqlite3.Row, turn: sqlite3.Row, action: str,
                 intent: dict[str, Any] | None, *, prepared: list[dict[str, Any]] | None = None, all_in: bool = False,
                 early: Callable[[Any], Awaitable[Any]] | None = None) -> Reply:
    room_id = room["id"]
    async with app.lock(room_id):
        with app.store.read() as c:
            room, turn = hosted._require_active_turn(c, room_id, turn["id"], ("awaiting",))
            if not is_round(turn) or actor["id"] in entries(turn):
                raise UserError("这一轮已经收了你的行动，或者正文已经在写了。")
            quota.require_round(app, c, room["umo"])
            room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
            # A free action written after this player's clarifying question answers it, as in a normal turn.
            asked = (loads(turn["data_json"], {}).get("clarify") or {}).get(actor["id"]) if intent is None else None
            if asked:
                action = f"{asked['action']}（补充：{action}）"[:2000]
            context = hosted.build_context(c, room, actor, action, None)
            if asked:
                context["action"] = (action + f"\n（主持刚才追问：{asked['question']}；括号里的补充就是玩家的回答）")[:2000]
        if intent is None:
            try:
                result = await app.engine.call("propose_intent", {"context": context}, room_id=room_id, umo=room["umo"],
                                               rules=shared.rules(room))
            except EngineCallFailed as exc:
                raise UserError("行动理解失败：" + exc.user_message + " 你可以换个说法再试，或选择 A–D。") from exc
            intent = result["proposal"]
            if intent["kind"] == "clarify" and asked:
                intent = await hosted.firm_intent(app, room, actor, turn, context, action)
            if intent["kind"] in ("clarify", "impossible"):
                question = (intent.get("clarification") or intent.get("reason") or "").strip()
                with app.store.tx() as c:
                    _, turn = hosted._require_active_turn(c, room_id, turn["id"], ("awaiting",))
                    data = loads(turn["data_json"], {})
                    if intent["kind"] == "clarify":
                        data.setdefault("clarify", {})[actor["id"]] = {"action": action[:500], "question": question[:300]}
                    else:                           # refused outright: the next action starts fresh
                        data.get("clarify", {}).pop(actor["id"], None)
                    c.execute("UPDATE turns SET data_json=? WHERE id=?", (dumps(data), turn["id"]))
                minutes = max(1, round((datetime.fromisoformat(turn["deadline_at"]) - datetime.now(UTC)).total_seconds() / 60))
                return Reply().say(messages.ask_back(shared.actor_label(actor), actor["user_name"], actor["user_id"],
                                                     question, intent["kind"], again=False, minutes=minutes,
                                                     choices=bool(loads(turn["choices_json"], []))))
        with app.store.read() as c:
            hosted._require_active_turn(c, room_id, turn["id"], ("awaiting",))
        flash_review = await ties.review_for_check(app, room, actor, action, intent)
        label = shared.actor_label(actor)
        with app.store.tx() as c:
            fresh_room, turn = hosted._require_active_turn(c, room_id, turn["id"], ("awaiting",))
            if fresh_room['chapter'] != room['chapter']:
                raise UserError('行动理解期间已经换幕，请按当前剧情重新行动。')
            room = fresh_room
            done = entries(turn)
            if actor['id'] in done:
                raise UserError('这一轮已经收了你的行动。')
            if not done:
                lifecycle.auto_snapshot(c, room_id, f"第 {turn['round']} 轮 · 快团行动前")
            actor = c.execute("SELECT * FROM actors WHERE id=?", (actor["id"],)).fetchone()
            flash_bonus, flash_notice = ties.checked_bonus(app, c, room, actor, flash_review)
            receipt, doc = hosted.mechanics(room, actor, intent, prepared, all_in=all_in, flashback=flash_bonus)
            if flash_notice:
                receipt['flashback_notice'] = flash_notice
            receipt["intent_reason"] = intent.get("reason", "")
            loadout.save(c, actor["id"], doc)
            ties.spend(c, actor["id"], receipt)
            if receipt.get("face"):
                luck.record(c, room["umo"], actor["user_id"], actor["user_name"], "check", [receipt["face"]])
            if intent["kind"] == "recover":
                loadout.refill(c, room, "rest", [actor["id"]])
            if receipt.get("all_in"):
                hosted._mark_act(c, actor["id"], "all_in_act", room["act"])
            app.store.add_event(c, room_id, "action", f"{label}：{action}", actor_id=actor["id"])
            dice = hosted.receipt_text(receipt)
            if dice:
                app.store.add_event(c, room_id, "check", f"{label} {dice}", actor_id=actor["id"], data=receipt)
            done[actor["id"]] = {"label": label, "action": action, "intent": intent, "receipt": receipt}
            turn = _write(c, turn["id"], {"entries": done})
            rows = members(c, room_id, turn)
        status = hosted.status_message(room, actor, turn["round"], action, receipt)
        reply = Reply()
        if early is None:
            reply.say(status)
        else:
            try:
                await early(status)
            except Exception:
                logger.exception("321Roll Lite could not send a rush roll before the round closed")
                reply.say(status)
        return reply.extend(await _after_submission(app, room_id, turn["id"], rows))


async def skip(app: "LiteApp", room: sqlite3.Row, actor: sqlite3.Row, turn: sqlite3.Row) -> Reply:
    async with app.lock(room["id"]):
        with app.store.tx() as c:
            room, turn = hosted._require_active_turn(c, room["id"], turn["id"], ("awaiting",))
            done = entries(turn)
            if actor['id'] in done:
                raise UserError('这一轮已经收了你的行动。')
            done[actor["id"]] = {"label": shared.actor_label(actor), "skip": True}
            turn = _write(c, turn["id"], {"entries": done})
            rows = members(c, room["id"], turn)
        reply = Reply().say(f"{shared.actor_label(actor)} 这一轮旁观。")
        return reply.extend(await _after_submission(app, room["id"], turn["id"], rows))


async def _after_submission(app: "LiteApp", room_id: str, turn_id: str, rows: list[tuple[sqlite3.Row, bool]]) -> Reply:
    """Write the round once everyone is in; otherwise say who is still missing.  The room lock is held."""
    if not all(done for _, done in rows):
        return Reply().say(messages.rush_progress([(shared.actor_label(a), done) for a, done in rows]))
    return await close(app, room_id, turn_id)


async def close(app: "LiteApp", room_id: str, turn_id: str) -> Reply:
    """Narrate the round from what was submitted (the room lock is held).  Nobody acting just reopens the options."""
    with app.store.tx() as c:
        turn = c.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
        if turn is None or turn["state"] != "awaiting" or not is_round(turn):
            return Reply()
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        acted = [(ref, e) for ref, e in entries(turn).items() if not e.get("skip")]
        if not acted:
            c.execute("UPDATE turns SET state='skipped',updated_at=? WHERE id=?", (now(), turn_id))
            app.store.add_event(c, room_id, "system", f"第 {turn['round']} 轮快团没人行动")
            new = open_round(app, c, room, loads(turn["choices_json"], []), turn["round"] + 1)
            reply = Reply().say(f"第 {turn['round']} 轮没人交行动，故事原地停了一会儿。")
            return reply.say(prompt(app, room, new)) if new is not None else reply
        refs = {ref for ref, _ in acted}
        watching = [shared.actor_label(a) for a, _ in members(c, room_id, turn) if a["id"] not in refs]
        first_ref, first = acted[0]
        receipt = {**first["receipt"], "rush": [{"actor": e["label"], "action": e["action"],
                                                 "result": hosted.receipt_text(e["receipt"]) or "不需检定"} for _, e in acted],
                   "rush_watching": watching}
        settled = [item for _, e in acted for item in e['receipt'].get('settled_items', [])]
        if settled:
            receipt['settled_items'] = settled
        combined = "\n".join(f"{e['label']}：{e['action']}" for _, e in acted)
        c.execute("UPDATE turns SET state='resolving',actor_id=?,action_text=?,intent_json=?,receipt_json=?,updated_at=? WHERE id=?",
                  (first_ref, combined, dumps(first["intent"]), dumps(receipt), now(), turn_id))
    return await hosted.narrate(app, room_id, turn_id)


def party_line(receipt: dict[str, Any]) -> str:
    """The table note that replaces 'who acts this turn' for a rush round."""
    parts = "；".join(f"{r['actor']}（{r['action']}；{r['result']}）" for r in receipt["rush"])
    line = ("快团：本轮全队同时行动，下面每位角色的行动和骰果都已由平台结算：" + parts + "。"
            "正文按这个顺序把每个人的行动和结果都写到，合成一段连贯的场面；只写他们交上来的行动，"
            "不替任何人新增行动、台词或决定，各人的人设只用在本人身上。")
    if receipt.get("rush_watching"):
        line += "这一轮没交行动的角色（" + "、".join(receipt["rush_watching"]) + "）只在一旁看着。"
    return line + "suggestions 是全队下一轮共用的选项，用省略行动者的通用措辞。"


# ---------------------------------------------------------------- host switch
async def host_rush(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "running", "paused")
    shared.require_host(app, caller, room)
    word = args.strip()
    if word not in ("开", "关", "开启", "关闭", ""):
        raise UserError("写法：/团 主持 快团 开｜关")
    if not word:
        return Reply().say(messages.notice(f"快团{'已开启' if enabled(room) else '未开启'}",
                                           "开启后每一轮全队同时行动，交齐或时间到就一起写正文。",
                                           "主持人发送 /团 主持 快团 开｜关"))
    on = word.startswith("开")
    with app.store.tx() as c:
        turn = hosted.current_turn(c, room["id"])
        if not on and is_round(turn) and entries(turn):
            raise UserError("这一轮已经有人交了行动，等这一轮正文写完再关。")
        hosted.set_hosted_data(c, room["id"], rush=on)
        app.store.add_event(c, room["id"], "host", "主持人" + ("开启" if on else "关闭") + "了快团")
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
        if turn is not None and turn["state"] == "awaiting" and on != is_round(turn):
            turn = (_write(c, turn["id"], {"entries": {}}, deadline_at=_deadline(app, room)) if on else
                    _write(c, turn["id"], None, deadline_at=hosted._deadline(app, room)))
        holder = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone() if turn is not None else None
    reply = Reply().say(messages.rush_toggled(on, window(app, room) // 60))
    if turn is not None and turn["state"] == "awaiting" and holder is not None and room["state"] == "running":
        reply.say(hosted.turn_prompt(app, room, turn, holder))
    return reply


def install(app: "LiteApp") -> None:
    app.router.register("主持 快团", host_rush, summary="快团：全队同时行动，交齐或时间到就一起写正文",
                        usage="/团 主持 快团 [开|关]", topic="主持")

