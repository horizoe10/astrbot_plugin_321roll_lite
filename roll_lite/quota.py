"""A per-group daily cap on AI-narrated rounds, so a self-hosted bot's model bill stays in hand.

A round counts when a player's action (chosen, written or picked on timeout) is resolved and
narrated; the opening, collective events and the host's retries and rewrites do not count.  The
day is the Beijing calendar date, like today's roll.  0, the default, means no cap.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from .commands import UserError

if TYPE_CHECKING:
    from .app import LiteApp

KEY = "story.daily_round_limit"
MAX_LIMIT = 1000
BEIJING = timezone(timedelta(hours=8))


def daily_limit(app: "LiteApp") -> int:
    with app.store.read() as c:
        return _limit(app, c)


def _limit(app: "LiteApp", c: sqlite3.Connection) -> int:
    value = app.store.get_setting(c, "global", KEY, 0)
    return value if type(value) is int and 0 <= value <= MAX_LIMIT else 0


def set_daily_limit(app: "LiteApp", value: int) -> int:
    if type(value) is not int or not 0 <= value <= MAX_LIMIT:
        raise ValueError(f"每群每天 0–{MAX_LIMIT} 轮，0 为不限")
    with app.store.tx() as c:
        app.store.set_setting(c, "global", KEY, value)
    return value


def _day_start() -> str:
    local = datetime.now(UTC).astimezone(BEIJING).replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(UTC).isoformat(timespec="seconds")


def rounds_today(c: sqlite3.Connection, umo: str) -> int:
    return c.execute("SELECT COUNT(*) FROM events e JOIN rooms r ON r.id=e.room_id "
                     "WHERE r.umo=? AND e.kind='action' AND e.created_at>=?", (umo, _day_start())).fetchone()[0]


def rounds_by_group(c: sqlite3.Connection) -> list[dict[str, object]]:
    """Today's narrated rounds of every group that played today, most first, with the group's latest table title."""
    rows = c.execute("SELECT r.umo, MAX(r.group_id) AS group_id, COUNT(*) AS rounds, "
                     "(SELECT title FROM rooms x WHERE x.umo=r.umo ORDER BY x.created_at DESC LIMIT 1) AS title "
                     "FROM events e JOIN rooms r ON r.id=e.room_id WHERE e.kind='action' AND e.created_at>=? "
                     "GROUP BY r.umo ORDER BY rounds DESC", (_day_start(),)).fetchall()
    return [{"umo": r["umo"], "group_id": r["group_id"], "rounds": r["rounds"], "title": r["title"]} for r in rows]


def require_round(app: "LiteApp", c: sqlite3.Connection, umo: str) -> None:
    """Raises UserError when this group has used today's narrated rounds."""
    limit = _limit(app, c)
    if limit and rounds_today(c, umo) >= limit:
        raise UserError(exhausted(limit))


def exhausted(limit: int) -> str:
    return (f"本群今天的 AI 叙事已经用完（每天 {limit} 轮），故事停在这里，北京时间零点后可以接着行动。"
            "管理员可以在后台“设置”里调整这个上限。")
