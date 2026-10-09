"""Scheduling a session (约团), like 321Roll's table schedule: the host offers times, the group marks them.

/团 约团 时间1｜时间2…   the host offers up to six times (replaces an earlier offer); without times shows the board
/团 约 1 3              anyone in the group marks the times that suit them (/团 约 都不行 clears)
/团 定档 序号            the host fixes one; everyone who marked it is @-ed now and again 30 minutes before
/团 约团 取消            the host withdraws the offer

Times are read in Beijing time (UTC+8): 周六 20:00, 明晚 8 点, 10月12日 19:30, 下周日 下午3点, 21:00.
The schedule lives in the room's data (rooms.data_json "schedule") and ends with the room.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from .. import messages, shared
from ..commands import Caller, Reply, UserError
from ..storage import dumps, loads

if TYPE_CHECKING:
    from ..app import LiteApp

BEIJING = timezone(timedelta(hours=8))
MAX_OPTIONS = 6
REMIND_BEFORE = timedelta(minutes=30)
LATE_GRACE = timedelta(minutes=10)
MAX_AHEAD = timedelta(days=60)
WEEKDAYS = "一二三四五六日"
_SPLIT = re.compile(r"[｜|;；,，、\n]+")
_FULL = re.compile(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})[日号]?")
_MONTH_DAY = re.compile(r"(\d{1,2})(?:月|/|-|\.)(\d{1,2})[日号]?")
_RELATIVE = re.compile(r"(大后天|后天|明天|明晚|明早|今天|今晚|今早)")
_WEEKDAY = re.compile(r"(下下|下)?(?:周|星期|礼拜)([一二三四五六日天])")
_TIME = re.compile(r"(凌晨|早上|上午|中午|下午|傍晚|晚上|夜里)?(\d{1,2})(?:[:：](\d{2})|[点时](半|(\d{1,2})分?)?)")
_EVENING = ("下午", "傍晚", "晚上", "夜里")

# Replaced in tests.
def _clock() -> datetime:
    return datetime.now(UTC)


def parse_when(text: str, now: datetime | None = None) -> datetime:
    """A future moment (UTC) from a Chinese date and time read in Beijing time; raises UserError."""
    local_now = (now or _clock()).astimezone(BEIJING)
    raw = re.sub(r"\s+", "", text)
    day, rest, relative = None, raw, None
    if (m := _FULL.search(raw)) is not None:
        day, rest = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)), text), raw.replace(m.group(0), "", 1)
    elif (m := _WEEKDAY.search(raw)) is not None:
        target = WEEKDAYS.index("日" if m.group(2) == "天" else m.group(2))
        if m.group(1):
            monday = local_now.date() - timedelta(days=local_now.weekday()) + timedelta(days=7 * len(m.group(1)))
            day = monday + timedelta(days=target)
        else:
            day = local_now.date() + timedelta(days=(target - local_now.weekday()) % 7)
            relative = "weekday"
        rest = raw.replace(m.group(0), "", 1)
    elif (m := _RELATIVE.search(raw)) is not None:
        word = m.group(1)
        offset = {"今": 0, "明": 1, "后": 2, "大": 3}[word[0]]
        day, rest = local_now.date() + timedelta(days=offset), raw.replace(word, "晚上" if word.endswith("晚") else "", 1)
    elif (m := _MONTH_DAY.search(raw)) is not None and _TIME.search(raw[m.end():]):
        day = _date(local_now.year, int(m.group(1)), int(m.group(2)), text)
        if day < local_now.date():
            day = _date(local_now.year + 1, int(m.group(1)), int(m.group(2)), text)
        rest = raw.replace(m.group(0), "", 1)
    t = _TIME.search(rest)
    if t is None:
        raise UserError(f"“{text.strip()}”里没有看到时间，请写成 周六 20:00、明晚 8 点、10月12日 19:30 这样。")
    hour = int(t.group(2))
    minute = int(t.group(3) or t.group(5) or (30 if t.group(4) == "半" else 0))
    if t.group(1) in _EVENING and hour < 12:
        hour += 12
    elif t.group(1) == "中午" and hour < 11:
        hour += 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise UserError(f"“{text.strip()}”的时间不对。")
    if day is None:
        day = local_now.date()
        relative = "time"
    moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=BEIJING)
    if moment <= local_now and relative in ("time", "weekday"):
        moment += timedelta(days=1 if relative == "time" else 7)
    if moment <= local_now:
        raise UserError(f"“{text.strip()}”已经过去了。")
    if moment - local_now > MAX_AHEAD:
        raise UserError("只能约 60 天以内的时间。")
    return moment.astimezone(UTC)


def _date(year: int, month: int, day: int, text: str):
    try:
        return datetime(year, month, day).date()
    except ValueError:
        raise UserError(f"“{text.strip()}”不是一个有效的日期。") from None


def label(moment: datetime) -> str:
    local = moment.astimezone(BEIJING)
    return f"{local.month} 月 {local.day} 日 周{WEEKDAYS[local.weekday()]} {local:%H:%M}"


def _schedule(room: sqlite3.Row) -> dict[str, Any] | None:
    return loads(room["data_json"], {}).get("schedule")


def _save(c: sqlite3.Connection, room_id: str, schedule: dict[str, Any] | None) -> None:
    data = loads(c.execute("SELECT data_json FROM rooms WHERE id=?", (room_id,)).fetchone()["data_json"], {})
    if schedule is None:
        data.pop("schedule", None)
    else:
        data["schedule"] = schedule
    c.execute("UPDATE rooms SET data_json=? WHERE id=?", (dumps(data), room_id))


def board(room: sqlite3.Row, schedule: dict[str, Any]) -> Any:
    marks = schedule.get("marks") or {}
    options = [{"label": o["label"], "names": [m["name"] for m in marks.values() if i in m["picks"]],
                "decided": schedule.get("decided") == i} for i, o in enumerate(schedule["options"])]
    declined = [m["name"] for m in marks.values() if not m["picks"]]
    return messages.schedule_board(room["title"], options, declined, decided=schedule.get("decided") is not None)


async def offer(app: "LiteApp", caller: Caller, args: str) -> Reply:
    shared.require_play(app, caller, "funSchedule")
    room = shared.require_room(app, caller, "lobby", "running", "paused")
    text = args.strip()
    if not text:
        schedule = _schedule(room)
        if schedule is None:
            raise UserError("这一桌还没有约时间。主持人发送 /团 约团 周六 20:00｜周日 14:00 给出几个时间。")
        return Reply().say(board(room, schedule))
    shared.require_host(app, caller, room)
    if text == "取消":
        with app.store.tx() as c:
            _save(c, room["id"], None)
        return Reply().say("已撤回约团。")
    parts = [p.strip() for p in _SPLIT.split(text) if p.strip()]
    if len(parts) > MAX_OPTIONS:
        raise UserError(f"最多给出 {MAX_OPTIONS} 个时间。")
    moments = sorted(dict.fromkeys(parse_when(p) for p in parts))
    schedule = {"options": [{"at": m.isoformat(timespec="minutes"), "label": label(m)} for m in moments], "marks": {},
                "decided": None, "reminded": False, "by": caller.user_id}
    with app.store.tx() as c:
        _save(c, room["id"], schedule)
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
    return Reply().say(board(room, schedule))


async def mark(app: "LiteApp", caller: Caller, args: str) -> Reply:
    shared.require_play(app, caller, "funSchedule")
    room = shared.require_room(app, caller, "lobby", "running", "paused")
    schedule = _schedule(room)
    if schedule is None:
        raise UserError("这一桌还没有约时间。")
    if schedule.get("decided") is not None:
        raise UserError(f"已经定档：{schedule['options'][schedule['decided']]['label']}。")
    text = args.strip()
    if text in ("都不行", "不行", "0", "无"):
        picks: list[int] = []
    else:
        numbers = [int(n) for n in re.findall(r"\d+", text)]
        if not numbers or any(not 1 <= n <= len(schedule["options"]) for n in numbers):
            raise UserError(f"写上合适的时间序号，例如 /团 约 1 3；序号是 1–{len(schedule['options'])}。都不合适就发 /团 约 都不行。")
        picks = sorted(set(n - 1 for n in numbers))
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
        schedule = _schedule(room) or schedule
        schedule.setdefault("marks", {})[caller.user_id] = {"name": caller.user_name, "picks": picks}
        _save(c, room["id"], schedule)
    return Reply().say(board(room, schedule))


async def decide(app: "LiteApp", caller: Caller, args: str) -> Reply:
    shared.require_play(app, caller, "funSchedule")
    room = shared.require_room(app, caller, "lobby", "running", "paused")
    shared.require_host(app, caller, room)
    schedule = _schedule(room)
    if schedule is None:
        raise UserError("这一桌还没有约时间。")
    if not args.strip().isdigit() or not 1 <= int(args) <= len(schedule["options"]):
        raise UserError(f"写上要定的时间序号，例如 /团 定档 1；序号是 1–{len(schedule['options'])}。")
    index = int(args) - 1
    if datetime.fromisoformat(schedule["options"][index]["at"]) <= _clock():
        raise UserError("这个时间已经过去了，请重新约团。")
    schedule.update(decided=index, reminded=False)
    with app.store.tx() as c:
        _save(c, room["id"], schedule)
    return Reply().say(_notice(room, schedule, "定档"))


def _notice(room: sqlite3.Row, schedule: dict[str, Any], kind: str) -> Any:
    index = schedule["decided"]
    who = [(uid, m["name"]) for uid, m in (schedule.get("marks") or {}).items() if index in m["picks"]]
    if schedule.get("by") and all(uid != schedule["by"] for uid, _ in who):
        who.insert(0, (schedule["by"], "主持人"))
    return messages.schedule_notice(room["title"], schedule["options"][index]["label"], who, kind)


async def on_tick(*, app: "LiteApp") -> Reply:
    stamp = _clock()
    with app.store.read() as c:
        rows = c.execute("SELECT * FROM rooms WHERE state IN ('lobby','running','paused') AND data_json LIKE '%\"schedule\"%'").fetchall()
    for room in rows:
        schedule = _schedule(room)
        if not schedule or schedule.get("decided") is None or schedule.get("reminded"):
            continue
        at = datetime.fromisoformat(schedule["options"][schedule["decided"]]["at"])
        if stamp < at - REMIND_BEFORE:
            continue
        with app.store.tx() as c:
            current = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
            fresh = _schedule(current)
            if not fresh or fresh.get("reminded") or fresh.get("decided") != schedule["decided"]:
                continue
            fresh["reminded"] = True
            _save(c, room["id"], fresh)
        if stamp <= at + LATE_GRACE:
            await app.notifier.send(room["umo"], _notice(room, schedule, "提醒"))
    return Reply()


def install(app: "LiteApp") -> None:
    r = app.router
    r.register("约团", offer, summary="主持人给出几个开团时间；不带时间时查看约团", usage="/团 约团 [周六 20:00｜周日 14:00]", topic="日常")
    r.register("约", mark, summary="勾选合适的开团时间", usage="/团 约 1 3", topic="日常")
    r.register("定档", decide, summary="主持人定下开团时间，开始前 30 分钟提醒", usage="/团 定档 序号", topic="日常")

    async def tick(**payload: Any) -> Reply:
        return await on_tick(app=app, **payload)

    app.hooks.on("tick", tick)

