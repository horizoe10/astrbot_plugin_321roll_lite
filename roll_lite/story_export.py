"""The whole story of one table as a Markdown book, for the admin to download after (or during) play.

Chapters follow the acts; each turn reads as the player's action, the dice line and the narration.
Host narration, play notes and vote results are kept, as are the ending and every epilogue.  The
story log keeps what a rewind or a loaded save undid, so such a jump is marked where it happened.
Only what the group saw goes in: no host directives, hidden entries or model notes.
"""
from __future__ import annotations

import re
import sqlite3

from . import shared
from .rooms import lifecycle
from .storage import loads

STATE_LABELS = lifecycle.STATE_LABELS
JUMPS = ("主持人回退到", "读档：")


def _day(stamp: str | None) -> str:
    return (stamp or "")[:10]


def _quote(text: str) -> str:
    return "\n".join("> " + line if line.strip() else ">" for line in text.strip().splitlines())


def _paras(text: str) -> str:
    return "\n\n".join(p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip())


def markdown(c: sqlite3.Connection, room: sqlite3.Row) -> str:
    pack = shared.world(room)["pack"]
    actors = c.execute("SELECT * FROM actors WHERE room_id=? ORDER BY order_index", (room["id"],)).fetchall()
    names = {a["id"]: shared.actor_label(a) for a in actors}
    archetypes = {t["id"]: t["name"] for t in pack.get("archetypes") or []}
    events = c.execute("SELECT * FROM events WHERE room_id=? ORDER BY id", (room["id"],)).fetchall()
    data = loads(room["data_json"], {})
    ending = (data.get("ending") or {}).get("title", "")
    record = c.execute("SELECT document_json FROM records WHERE room_id=? AND kind='ending' ORDER BY seq DESC LIMIT 1",
                       (room["id"],)).fetchone()
    epilogues = (loads(record["document_json"]) if record else {}).get("epilogues", [])
    rounds = c.execute("SELECT COALESCE(MAX(round),0) FROM turns WHERE room_id=?", (room["id"],)).fetchone()[0]

    title = pack["title"] + (f" · {room['title']}" if room["title"] and room["title"] != pack["title"] else "")
    span = _day(room["created_at"]) + (" – " + _day(room["ended_at"] or room["updated_at"])
                                       if _day(room["ended_at"] or room["updated_at"]) != _day(room["created_at"]) else "")
    meta = [span, STATE_LABELS.get(room["state"], room["state"]), f"共 {rounds} 轮"] + ([f"结局：{ending}"] if ending else [])
    out = [f"# {title}", "", "> " + " · ".join(p for p in meta if p), ""]
    cast = [a for a in actors if a["archetype_id"]]
    if cast:
        out += ["## 登场角色", ""]
        out += [f"- **{names[a['id']]}**" + (f"（{archetypes[a['archetype_id']]}）" if a["archetype_id"] in archetypes else "")
                + f" · 玩家 {a['user_name']}" for a in cast]
        out.append("")

    first = next((a for a in lifecycle.act_list(room) if a["number"] == 1), None)
    if first is not None and not any(e["kind"] == "chapter" for e in events[:1]):
        out += [f"## 第一幕" + (f" · {first['title']}" if first["title"] else ""), ""]
        if first["lead"]:
            out += [f"*{first['lead']}*", ""]
    for e in events:
        kind, text = e["kind"], e["text"].strip()
        if not text:
            continue
        if kind == "chapter":
            head, _, lead = text.partition("——")
            out += ["---", "", f"## {head}", ""] + ([f"*{lead}*", ""] if lead else [])
        elif kind == "narration":
            if loads(e["data_json"], {}).get("opening"):
                scene, _, body = text.partition("\n")
                out += [f"### {scene}", "", _paras(body), ""]
            else:
                out += [_paras(text), ""]
        elif kind == "action":
            who, _, what = text.partition("：")
            out += [f"**▸ {who}**：{what}" if what else f"**▸ {text}**", ""]
        elif kind == "check":
            out += [f"🎲 {text}", ""]
        elif kind == "host":
            out += [_quote(text), ""]
        elif kind in ("play", "vote"):
            out += [f"*{text}*", ""]
        elif kind == "system" and text.startswith(JUMPS):
            out += [f"*（{text}，此前一段剧情作废）*", ""]
    if ending or epilogues:
        out += ["---", "", "## 终章" + (f" · {ending}" if ending else ""), ""]
        for item in epilogues:
            out += [f"**{names.get(item.get('actor_ref'), '')}**：{item.get('text', '')}", ""]
    out.append(f"*由 321Roll Lite 导出 · {pack['title']}*")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


def filename(room: sqlite3.Row) -> str:
    title = shared.world(room)["pack"]["title"].split(" · ")[0]
    stem = re.sub(r'[\\/:*?"<>|\s]+', "_", f"{title}-{_day(room['created_at'])}").strip("_") or "story"
    return stem + ".md"


def export(c: sqlite3.Connection, room: sqlite3.Row) -> tuple[str, bytes]:
    return filename(room), markdown(c, room).encode("utf-8")


__all__ = ["export", "markdown"]
