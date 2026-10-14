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
    return c.execute("SELECT * FROM rooms WHERE umo=? AND state NOT IN ('closed','shelved')", (umo,)).fetchone()


def require_room(app: "LiteApp", caller: Caller, *states: str) -> sqlite3.Row:
    with app.store.read() as c:
        room = open_room(c, caller.umo)
    if room is None:
        raise UserError("本群当前没有启用的团桌。管理员可 /团 开启 新世界；想接着旧故事玩，发送 /团 暂存列表，再由原主持人或管理员 /团 取回 序号。")
    if states and room["state"] not in states:
        labels = {"lobby": "筹备中", "running": "进行中", "paused": "已暂停", "ended": "已完结"}
        allowed = "、".join(labels[s] for s in states if s in labels)
        if room["state"] == "paused":
            raise UserError(paused_step(room))
        raise UserError(STATE_STEPS.get(room["state"]) or f"故事正在进行，这个操作只能在团桌{allowed}时使用。")
    return room


# What a player can do next when a command does not fit the table's state.
STATE_STEPS = {"ended": "这一桌已经完结：发送 /团 战报 看这一局的回顾；主持人发送 /团 关闭 收桌后可以开新的一桌。",
               "lobby": "故事还没开演：还没入座的先 /团 加入 并建好卡，人齐后等主持人发送 /团 开演。"}


def paused_step(room: sqlite3.Row, what: str = "") -> str:
    """A paused table either waits for /团 恢复 or already has its lobby open; the next step differs."""
    head = f"故事暂停中，{what}要等开演后再来。" if what else "故事暂停中。"
    if loads(room["data_json"], {}).get("regroup"):
        return head + "准备大厅已经开着：建好卡的人发送 /团 准备，还没入座的可以先 /团 加入 再建卡；主持人 /团 开演 后继续。"
    return head + "等主持人发送 /团 恢复 打开准备大厅，大家准备好后再开演。"


def ending_step(room: sqlite3.Row, what: str = "") -> str | None:
    """Between the finale and the ending card the story takes no more moves; what to do instead, or None."""
    st = loads(room["data_json"], {}).get("hosted", {}).get("pacing") or {}
    if st.get("epilogue"):
        return (f"终章已经写完，{what}用不上了：" if what else "终章已经写完：") + \
            "发送 /团 尾声 一句话 写下你的角色最后的去向；主持人可以 /团 完结 直接落幕。"
    if st.get("finale"):
        return (f"故事正在写终章，{what}先停一下" if what else "故事正在写终章") + \
            "：写完后每人留一句尾声。终章没写出来时，主持人可以 /团 主持 重试，或 /团 主持 跳过 直接写尾声。"
    return None


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
        if room["state"] == "ended":
            raise UserError(STATE_STEPS["ended"])
        spectate = "；没入座也可以 /团 起哄 给故事出点子、/团 押 成 竞猜别人这一掷" if room["state"] == "running" else ""
        where = "" if caller.in_group else "在群里"
        raise UserError(f"你还没有加入这一桌。{where}发送 /团 加入 入座{spectate}。")
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
