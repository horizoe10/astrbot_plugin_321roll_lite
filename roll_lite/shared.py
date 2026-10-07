"""Small read helpers every feature module uses.  No business rules live here."""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from .commands import Caller, UserError
from .storage import loads

if TYPE_CHECKING:
    from .app import LiteApp

OPEN_STATES = ("lobby", "running", "paused", "ended")


def open_room(c: sqlite3.Connection, umo: str) -> sqlite3.Row | None:
    """The group's room that is not closed (at most one exists)."""
    return c.execute("SELECT * FROM rooms WHERE umo=? AND state<>'closed'", (umo,)).fetchone()


def require_room(app: "LiteApp", caller: Caller, *states: str) -> sqlite3.Row:
    with app.store.read() as c:
        room = open_room(c, caller.umo)
    if room is None:
        raise UserError("本群还没有开团。管理员可以发送 /团 开启 [世界] 开一桌。")
    if states and room["state"] not in states:
        labels = {"lobby": "筹备中", "running": "进行中", "paused": "已暂停", "ended": "已完结"}
        raise UserError(f"当前团桌{labels.get(room['state'], room['state'])}，不能执行这个操作。")
    return room


def actor_for(c: sqlite3.Connection, room_id: str, user_id: str) -> sqlite3.Row | None:
    return c.execute("SELECT * FROM actors WHERE room_id=? AND user_id=? AND presence<>'left'",
                     (room_id, user_id)).fetchone()


def private_scope(caller: Caller) -> str:
    return f"user:{caller.platform_id}:{caller.user_id}"


def seated_rooms(c: sqlite3.Connection, caller: Caller) -> list[sqlite3.Row]:
    """Open rooms on this platform where the private-chat user holds a seat or hosts, most recent first."""
    return c.execute("SELECT r.* FROM rooms r WHERE r.platform=? AND r.state IN ('lobby','running','paused','ended') AND "
                     "(r.host_user_id=? OR EXISTS(SELECT 1 FROM actors a WHERE a.room_id=r.id AND a.user_id=? AND a.presence<>'left')) "
                     "ORDER BY r.updated_at DESC", (caller.platform_id, caller.user_id, caller.user_id)).fetchall()


def private_room(app: "LiteApp", caller: Caller) -> sqlite3.Row:
    """The room a private chat acts on: the one picked with /团 切换, else the only or latest seated room."""
    with app.store.read() as c:
        rooms = seated_rooms(c, caller)
        picked = app.store.get_setting(c, private_scope(caller), "private.room", None)
    if not rooms:
        raise UserError("你还没有在任何一桌入座或主持。先在群里发送 /团 加入，再回到私聊建卡。")
    return next((r for r in rooms if r["id"] == picked), rooms[0])


def private_umo(c: sqlite3.Connection, platform_id: str, user_id: str) -> str | None:
    """The user's private chat with the bot, remembered from their last private command."""
    from .storage import Store
    return Store.get_setting(c, f"user:{platform_id}:{user_id}", "private.umo", None)


def table_data(room: sqlite3.Row) -> dict[str, Any]:
    """Seat governance kept by the host: handover offer, removed players, seating lock."""
    return loads(room["data_json"], {}).get("table", {})


def set_table_data(c: sqlite3.Connection, room_id: str, **values: Any) -> None:
    from .storage import dumps
    row = c.execute("SELECT data_json FROM rooms WHERE id=?", (room_id,)).fetchone()
    data = loads(row["data_json"], {})
    data.setdefault("table", {}).update(values)
    c.execute("UPDATE rooms SET data_json=? WHERE id=?", (dumps(data), room_id))


def split_target(args: str, caller: Caller) -> tuple[str, str]:
    """(who, rest) from '角色名 其余文字'; with an @mention the person comes from the mention."""
    text = args.strip()
    if caller.mentions:
        if text.startswith(("@", "＠")):
            text = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
        return "", text.strip()
    words = text.split(maxsplit=1)
    return (words[0] if words else ""), (words[1].strip() if len(words) > 1 else "")


def find_actor(c: sqlite3.Connection, room_id: str, token: str, mentions: tuple[str, ...] = ()) -> sqlite3.Row:
    """A seated actor by @mention, character name, nickname, user id or seat number in /团 阵容 order."""
    rows = c.execute("SELECT * FROM actors WHERE room_id=? AND presence<>'left' ORDER BY order_index,created_at",
                     (room_id,)).fetchall()
    for user_id in mentions:
        hit = next((r for r in rows if r["user_id"] == user_id), None)
        if hit is not None:
            return hit
    token = token.strip().lstrip("@＠").strip()
    if token:
        hit = next((r for r in rows if token in (r["name"], r["user_name"], r["user_id"])), None)
        if hit is not None:
            return hit
        if token.isdigit() and 1 <= int(token) <= len(rows):
            return rows[int(token) - 1]
    raise UserError((f"这一桌没有“{token}”。" if token else "要写明是哪一位：角色名、昵称、座位序号，或 @ 对方。")
                    + "发送 /团 阵容 查看入座的人。")


def require_actor(app: "LiteApp", caller: Caller, room: sqlite3.Row) -> sqlite3.Row:
    with app.store.read() as c:
        actor = actor_for(c, room["id"], caller.user_id)
    if actor is None:
        raise UserError("你还没有加入这一桌。发送 /团 加入 入座。")
    return actor


def present_actors(c: sqlite3.Connection, room_id: str) -> list[sqlite3.Row]:
    return c.execute("SELECT * FROM actors WHERE room_id=? AND presence='present' ORDER BY order_index,created_at",
                     (room_id,)).fetchall()


def is_host(app: "LiteApp", caller: Caller, room: sqlite3.Row) -> bool:
    return caller.is_admin or caller.user_id == room["host_user_id"]


def require_host(app: "LiteApp", caller: Caller, room: sqlite3.Row) -> None:
    if not is_host(app, caller, room):
        raise UserError("只有主持人或管理员可以这样做。")


def require_play(app: "LiteApp", caller: Caller, key: str) -> None:
    if not app.features.enabled(caller.umo, key):
        from .features import BY_KEY
        raise UserError(f"本群未开放“{BY_KEY[key].label}”玩法。")


def world(room: sqlite3.Row) -> dict[str, Any]:
    """Frozen {'pack': ..., 'presentation': ...} snapshot taken when the room opened."""
    return loads(room["world_json"], {})


def rules(room: sqlite3.Row) -> dict[str, Any]:
    """Engine rules compiled from the pack (validated by story_engine.world_rules)."""
    return loads(room["rules_json"], {})


def actor_label(actor: sqlite3.Row) -> str:
    return actor["name"] or actor["user_name"]
