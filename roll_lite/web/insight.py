"""Figures the WebUI draws as charts: a table's statistics, its timeline grouped by act and round, model latency.

Everything here only reads.  Events carry no act or round of their own, so the timeline walks them in order:
an act changes at each chapter event, and a round closes with the narration written for its turn.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from ..fun import report
from ..rooms import lifecycle
from ..storage import loads

CHECK_FIELDS = ("face", "modifier", "total", "dc", "outcome", "attribute", "difficulty")
_CHAPTER = re.compile(r"^第(.+?)幕")


def _act_number(text: str, fallback: int) -> int:
    found = _CHAPTER.match(text)
    if found:
        word = found.group(1).strip()
        if word in lifecycle.NUMERALS:
            return lifecycle.NUMERALS.index(word) + 1
        if word.isdigit():
            return int(word)
    return fallback


def timeline(c: sqlite3.Connection, room: sqlite3.Row, current_round: int | None) -> tuple[list[dict[str, Any]], dict[int, dict[str, int]]]:
    """(every event oldest first with its act and round, {act: {rounds, checks}}).

    Events before the opening belong to no act (the lobby); the opening narration is round 0; later events join
    the round whose narration closes them, and events after the last narration join the round in play."""
    rows = c.execute("SELECT id,kind,actor_id,text,data_json,created_at FROM events WHERE room_id=? ORDER BY id",
                     (room["id"],)).fetchall()
    rounds = {r["id"]: r["round"] for r in c.execute("SELECT id,round FROM turns WHERE room_id=?", (room["id"],))}
    items: list[dict[str, Any]] = []
    seen: dict[int, set[int]] = {}
    checks: dict[int, int] = {}
    pending: list[dict[str, Any]] = []
    act, opened, last = 0, False, 0
    for r in rows:
        data = loads(r["data_json"], {})
        kind = r["kind"]
        opening = kind == "narration" and bool(data.get("opening"))
        if opening:
            opened, act = True, act or 1
        if kind == "chapter":
            act = _act_number(r["text"], act + 1)
        item = {"id": r["id"], "kind": kind, "text": r["text"], "created_at": r["created_at"],
                "act": act if opened else None, "round": None}
        if kind == "check" and data.get("face") is not None:
            item["check"] = {k: data.get(k) for k in CHECK_FIELDS}
        items.append(item)
        if not opened:
            continue
        if kind == "check" or (kind == "play" and "【检定】" in r["text"]):
            checks[act] = checks.get(act, 0) + 1
        if opening:
            item["round"] = 0
            pending = []
            continue
        pending.append(item)
        if kind == "narration":
            last = rounds.get(data.get("turn"), last + 1)
            seen.setdefault(act, set()).add(last)
            for p in pending:
                p["round"] = last
            pending = []
    for p in pending:
        p["round"] = current_round if current_round is not None else last + 1
    per_act = {a: {"rounds": len(seen.get(a, ())), "checks": checks.get(a, 0)} for a in set(seen) | set(checks)}
    return items, per_act


def room_stats(c: sqlite3.Connection, room: sqlite3.Row, per_act: dict[int, dict[str, int]]) -> dict[str, Any]:
    """Rounds, check outcomes and what each character did: the figures of the battle report card."""
    data = report.report_data(c, room)
    acts = [{**a, **per_act.get(a["number"], {"rounds": 0, "checks": 0})} for a in data["acts"]]
    return {"rounds": data["rounds"], "checks": data["checks"], "outcomes": data["outcomes"], "cast": data["cast"],
            "acts": acts, "best": data["best"]}


def _seconds(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        return max(0.0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
    except ValueError:
        return None


def _quantile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(share * (len(ordered) - 1))))]


def latency(rows: list[sqlite3.Row]) -> dict[str, Any] | None:
    """Median, 95th percentile and slowest call in seconds, from rows with started_at and completed_at."""
    values = [s for r in rows if (s := _seconds(r["started_at"], r["completed_at"])) is not None]
    if not values:
        return None
    return {"count": len(values), "p50": round(_quantile(values, .5), 1), "p95": round(_quantile(values, .95), 1),
            "max": round(max(values), 1)}


def hourly(c: sqlite3.Connection, moment: datetime) -> list[dict[str, Any]]:
    """Calls and failures in each of the last 24 hours, oldest first; hour is the UTC ISO hour (YYYY-MM-DDTHH)."""
    start = moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
    found = {r["hour"]: dict(r) for r in c.execute(
        "SELECT substr(started_at,1,13) AS hour,COUNT(*) AS calls,SUM(status<>'ok') AS failures FROM model_calls "
        "WHERE started_at>=? GROUP BY hour", (start.isoformat(timespec="seconds"),))}
    series = []
    for offset in range(24):
        hour = (start + timedelta(hours=offset)).isoformat(timespec="seconds")[:13]
        row = found.get(hour) or {}
        series.append({"hour": hour, "calls": row.get("calls") or 0, "failures": row.get("failures") or 0})
    return series
