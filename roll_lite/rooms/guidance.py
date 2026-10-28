"""Preparation progress and existing player experience, read from the current table."""
from __future__ import annotations

import sqlite3

from .. import shared
from ..storage import loads


def has_turn_experience(c: sqlite3.Connection, platform: str, user_id: str) -> bool:
    """Reuse the first-turn marker across this user's tables on the same bot platform."""
    rows = c.execute("SELECT a.data_json FROM actors a JOIN rooms r ON r.id=a.room_id "
                     "WHERE r.platform=? AND a.user_id=?", (platform, user_id))
    return any(loads(row["data_json"], {}).get("tips_seen") for row in rows)


def preparation(c: sqlite3.Connection, room: sqlite3.Row) -> str:
    """The same readiness conditions as /团 开演; only public names enter the hint."""
    if room["state"] != "lobby":
        return ""
    actors = shared.present_actors(c, room["id"])
    ready = sum(bool(a["archetype_id"]) for a in actors)
    minimum = shared.world(room)["pack"]["rules"]["minPlayers"]
    pending = [a["user_name"] for a in actors if not a["archetype_id"]]
    lines = [f"筹备进度：在场 {len(actors)} 人，已建卡 {ready} 人（至少 {minimum} 人可开演）。"]
    if pending:
        names = "、".join(pending[:3]) + (f"等 {len(pending)} 人" if len(pending) > 3 else "")
        lines.append(f"待建卡：{names}。私聊我发送 /团 建卡 继续；第一次建卡可用 /团 建卡 快选。")
    if ready < minimum:
        lines.append(f"还需 {minimum - ready} 人建好卡；想参加的群友先 /团 加入。")
        lines.append("主持人：人齐且在场玩家都建好卡后，再发送 /团 开演。")
    elif pending:
        lines.append("主持人：等在场玩家建好卡后再 /团 开演；/团 阵容 可查看进度。")
    else:
        lines.append("在场角色已齐，主持人发送 /团 开演，生成开场后开始轮流行动。")
    return "\n".join(lines)
