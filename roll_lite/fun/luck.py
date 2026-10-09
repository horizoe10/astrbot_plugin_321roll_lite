"""骰运: how kind the d20 has been to each member of a group.

/团 骰运 [@某人] [全部]   one member's month (or all time) in this group: average natural face, 20s and 1s,
                         and the spread of faces 1-20
/团 骰运 榜              this month's luckiest and unluckiest (at least MIN_ROLLS rolls), and who rolled most 20s and 1s

Every natural d20 face is logged where it is rolled (record()): checks in the story and in plays, today's roll
(once in each group it is shown in), free dice (every d20 face, dropped ones too) and duels.  The tiers reuse
today's roll's names, read from the average instead of one face.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Iterable

from .. import messages, shared
from ..commands import Caller, Reply, UserError
from ..storage import now
from .schedule import BEIJING

if TYPE_CHECKING:
    from ..app import LiteApp

MIN_ROLLS = 10       # on the board
FEW_ROLLS = 5        # below this a member's tier reads "样本太少"
SOURCES = {"check": "检定", "daily": "一掷", "dice": "掷骰", "duel": "对决"}
# (lowest average, label, tier key); a fair d20 averages 10.5
TIERS = ((12.5, "天光", "dawn"), (11.25, "顺风", "fair"), (9.75, "平潮", "calm"), (8.5, "阴云", "cloud"), (0, "逆风", "gale"))
BOARD_WORDS = ("榜", "排行", "排行榜")
ALL_WORDS = ("全部", "总计", "历史")


def record(c: sqlite3.Connection, umo: str, user_id: str, user_name: str, source: str, faces: Iterable[int]) -> None:
    stamp = now()
    c.executemany("INSERT INTO d20_log(umo,user_id,user_name,source,face,created_at) VALUES(?,?,?,?,?,?)",
                  [(umo, user_id, user_name, source, int(f), stamp) for f in faces if 1 <= int(f) <= 20])


def month_start() -> tuple[str, str]:
    """(UTC timestamp of this Beijing month's start, its label)."""
    local = datetime.now(UTC).astimezone(BEIJING).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(UTC).isoformat(timespec="seconds"), f"{local.year} 年 {local.month} 月"


def tier(average: float, count: int) -> tuple[str, str]:
    if count < FEW_ROLLS:
        return "样本太少", "calm"
    return next((label, key) for low, label, key in TIERS if average >= low)


def member_stats(c: sqlite3.Connection, umo: str, user_id: str, since: str | None) -> dict[str, Any]:
    where, args = ("AND created_at>=?", (umo, user_id, since)) if since else ("", (umo, user_id))
    faces = [0] * 20
    sources: dict[str, int] = {}
    for row in c.execute(f"SELECT face,source,COUNT(*) AS n FROM d20_log WHERE umo=? AND user_id=? {where} GROUP BY face,source", args):
        faces[row["face"] - 1] += row["n"]
        sources[row["source"]] = sources.get(row["source"], 0) + row["n"]
    count = sum(faces)
    average = sum((i + 1) * n for i, n in enumerate(faces)) / count if count else 0.0
    label, key = tier(average, count)
    return {"count": count, "average": round(average, 2), "faces": faces, "crits": faces[19], "fumbles": faces[0],
            "high": round(sum(faces[10:]) / count * 100) if count else 0, "tier": label, "tier_key": key,
            "sources": [[SOURCES.get(s, s), n] for s, n in sorted(sources.items(), key=lambda kv: -kv[1])]}


def board_rows(c: sqlite3.Connection, umo: str, since: str) -> list[dict[str, Any]]:
    """Members with at least MIN_ROLLS rolls since then: luckiest first."""
    rows = c.execute(
        "SELECT user_id, COUNT(*) AS n, AVG(face) AS avg, SUM(face=20) AS crits, SUM(face=1) AS fumbles, "
        "(SELECT user_name FROM d20_log l WHERE l.umo=d.umo AND l.user_id=d.user_id ORDER BY id DESC LIMIT 1) AS name "
        "FROM d20_log d WHERE umo=? AND created_at>=? GROUP BY user_id", (umo, since)).fetchall()
    out = []
    for r in rows:
        label, key = tier(r["avg"], r["n"])
        out.append({"user_id": r["user_id"], "name": r["name"], "count": r["n"], "average": round(r["avg"], 2),
                    "crits": r["crits"], "fumbles": r["fumbles"], "tier": label, "tier_key": key})
    return out


async def luck_command(app: "LiteApp", caller: Caller, args: str) -> Reply:
    shared.require_play(app, caller, "funLuck")
    words = args.split()
    since, month = month_start()
    if words and words[0] in BOARD_WORDS:
        with app.store.read() as c:
            rows = board_rows(c, caller.umo, since)
        ranked = sorted((r for r in rows if r["count"] >= MIN_ROLLS), key=lambda r: (-r["average"], -r["count"]))
        return Reply().say(messages.luck_board(month, ranked, rows, MIN_ROLLS))
    everything = any(w in ALL_WORDS for w in words)
    user_id, name = (caller.mentions[0], "") if caller.mentions else (caller.user_id, caller.user_name)
    with app.store.read() as c:
        stats = member_stats(c, caller.umo, user_id, None if everything else since)
        total = stats["count"] if everything else c.execute("SELECT COUNT(*) FROM d20_log WHERE umo=? AND user_id=?",
                                                            (caller.umo, user_id)).fetchone()[0]
        if not name:
            row = c.execute("SELECT user_name FROM d20_log WHERE umo=? AND user_id=? ORDER BY id DESC LIMIT 1",
                            (caller.umo, user_id)).fetchone()
            name = row["user_name"] if row else "这位群友"
    if not total:
        raise UserError(f"{name} 在本群还没有掷过 d20。跑团检定、今日一掷、自由掷骰和对决都会算进骰运。")
    return Reply().say(messages.luck_card(name, "全部记录" if everything else month, stats, total))


def install(app: "LiteApp") -> None:
    app.router.register("骰运", luck_command, summary="看看自己在本群的骰运，或本月骰运榜",
                        usage="/团 骰运 [@某人|榜|全部]", topic="日常")
