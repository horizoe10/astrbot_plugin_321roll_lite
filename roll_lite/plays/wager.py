"""竞猜: while a player's turn is open, anyone else in the group (seated or not) bets on how the roll goes.

/团 押 成|败   bet (again to change the bet) until the dice are rolled
/团 押         this turn's bets and the table's prophets so far

Bets ride on the open turn ('bets' in turns.data_json) and are settled with that turn's check (settle, called
from hosted.resolve).  A turn without a check voids them.  Right and total guesses per person stay in the room's
'wager' data; the battle report names the best prophet.
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from .. import messages, shared
from ..commands import Caller, Reply, UserError
from ..storage import dumps, loads

if TYPE_CHECKING:
    from ..app import LiteApp

SUCCESS = ("成", "成功", "过", "胜", "赢", "能")
FAILURE = ("败", "失败", "不过", "挂", "输", "不能")
PICKS = {"success": "成", "failure": "败"}


def seers(room: sqlite3.Row) -> list[dict[str, Any]]:
    """Everyone who has guessed in this story, best first: most right, then fewest guesses."""
    table = loads(room["data_json"], {}).get("wager", {}).get("seers") or {}
    rows = [{"user_id": uid, **v} for uid, v in table.items()]
    return sorted(rows, key=lambda r: (-r["right"], r["total"], r["name"]))


def prophet(room: sqlite3.Row) -> dict[str, Any] | None:
    best = next(iter(seers(room)), None)
    return best if best and best["right"] > 0 else None


def settle(c: sqlite3.Connection, room_id: str, bets: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any] | None:
    """Score this turn's bets against its receipt; returns what the status message shows."""
    if not bets:
        return None
    if receipt.get("kind") != "check":
        return {"void": [b["name"] for b in bets.values()]}
    outcome = "success" if receipt.get("success") else "failure"
    row = c.execute("SELECT data_json FROM rooms WHERE id=?", (room_id,)).fetchone()
    whole = loads(row["data_json"], {})
    table = whole.setdefault("wager", {}).setdefault("seers", {})
    right, wrong = [], []
    for uid, bet in bets.items():
        hit = bet["pick"] == outcome
        (right if hit else wrong).append(bet["name"])
        mine = table.setdefault(uid, {"name": bet["name"], "right": 0, "total": 0})
        mine.update(name=bet["name"], right=mine["right"] + hit, total=mine["total"] + 1)
    c.execute("UPDATE rooms SET data_json=? WHERE id=?", (dumps(whole), room_id))
    return {"outcome": outcome, "right": right, "wrong": wrong}


def _board(room: sqlite3.Row, turn: sqlite3.Row | None, actor_name: str, user_id: str, note: str = "") -> Any:
    bets = loads(turn["data_json"], {}).get("bets") or {} if turn is not None else {}
    rows = [{"name": b["name"], "pick": b["pick"]} for b in bets.values()]
    top = [{"name": s["name"], "right": s["right"], "total": s["total"]} for s in seers(room)[:5]]
    mine = (bets.get(user_id) or {}).get("pick", "")
    return messages.wager_board(actor_name, turn["round"] if turn is not None else 0, rows, top,
                                mine=mine, open=turn is not None, note=note)


async def bet(app: "LiteApp", caller: Caller, args: str) -> Reply:
    from .hosted import current_turn
    from . import rush
    room = shared.require_room(app, caller, "running", "paused")
    word = args.strip()
    with app.store.read() as c:
        turn = current_turn(c, room["id"])
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone() if turn is not None else None
    open_turn = turn if (turn is not None and turn["state"] == "awaiting" and not rush.is_round(turn)
                         and room["state"] == "running") else None
    name = shared.actor_label(actor) if open_turn is not None else ""
    if not word:
        return Reply().say(_board(room, open_turn, name, caller.user_id))
    pick = "success" if word in SUCCESS else "failure" if word in FAILURE else ""
    if not pick:
        raise UserError("押 成 或 败，例如 /团 押 成；发送 /团 押 看这一轮谁押了什么。")
    if room["state"] == "paused":
        raise UserError(shared.paused_step(room, "竞猜"))
    if shared.ending_step(room, "竞猜"):
        raise UserError(shared.ending_step(room, "竞猜"))
    if turn is not None and rush.is_round(turn):
        raise UserError("快团里大家同时出手，竞猜留到普通回合再玩。")
    if open_turn is None:
        raise UserError("骰子已经在掷了，下一轮再押。" if turn is not None and turn["state"] == "resolving"
                        else "现在没有等待掷骰的回合，轮到下一位行动时再押。")
    if actor["user_id"] == caller.user_id:
        raise UserError("现在轮到的就是你，不能押自己这一掷：直接 /团 A 选一项，或 /团 行动 你的做法。")
    with app.store.tx() as c:
        turn = c.execute("SELECT * FROM turns WHERE id=?", (open_turn["id"],)).fetchone()
        if turn["state"] != "awaiting":
            raise UserError("骰子已经掷下去了，下一轮再押。")
        data = loads(turn["data_json"], {})
        bets = data.setdefault("bets", {})
        changed = caller.user_id in bets and bets[caller.user_id]["pick"] != pick
        bets[caller.user_id] = {"name": caller.user_name, "pick": pick}
        c.execute("UPDATE turns SET data_json=? WHERE id=?", (dumps(data), turn["id"]))
        turn = c.execute("SELECT * FROM turns WHERE id=?", (turn["id"],)).fetchone()
    note = f"{caller.user_name} {'改押' if changed else '押'} {name} {'检定成功' if pick == 'success' else '检定失败'}"
    return Reply().say(_board(room, turn, name, caller.user_id, note))


def install(app: "LiteApp") -> None:
    app.router.register(("押", "竞猜", "押注"), bet, summary="押正在行动的人这一掷是成是败，掷骰时揭晓；没入座也能玩",
                        usage="/团 押 成｜/团 押 败｜/团 押", topic="互动")
