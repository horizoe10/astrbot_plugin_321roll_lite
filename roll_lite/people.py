"""People the party has met: model NPCs merged with relation records.

Attitude is toward the whole party (321Roll's relations play keeps one
standing per subject, -3..3).  Each memory remembers which character moved it,
so every player's contribution can be shown without splitting the attitude.
NPCs that never had a relation entry count as neutral.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from .adjust import STANDING
from .storage import loads


def people(c: sqlite3.Connection, room_id: str) -> list[dict[str, Any]]:
    actors = {a["id"]: (a["name"] or a["user_name"]) for a in c.execute("SELECT * FROM actors WHERE room_id=?", (room_id,))}
    actors["host"] = "主持人"
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for npc in c.execute("SELECT * FROM npcs WHERE room_id=? ORDER BY updated_at", (room_id,)):
        result[("npc", npc["name"])] = {"name": npc["name"], "kind": "npc", "description": npc["description"],
                                        "motivation": npc["motivation"], "standing": 0, "tier": STANDING[3],
                                        "contributions": {}, "memories": [], "seq": None, "met": True}
    for row in c.execute("SELECT * FROM records WHERE room_id=? AND kind='relation' ORDER BY seq", (room_id,)):
        doc = loads(row["document_json"])
        key = (doc["subject_kind"], doc["subject"])
        entry = result.setdefault(key, {"name": doc["subject"], "kind": doc["subject_kind"], "description": "", "motivation": "",
                                        "contributions": {}, "met": False})
        entry.update(standing=doc["standing"], tier=doc.get("tier") or STANDING[doc["standing"] + 3], seq=row["seq"])
        entry["memories"] = [{"who": actors.get(m.get("actor_ref"), "队伍"), "text": m.get("text", ""), "change": m.get("change", 0)}
                             for m in doc.get("memories", [])]
        for m in entry["memories"]:
            if m["change"]:
                entry["contributions"][m["who"]] = entry["contributions"].get(m["who"], 0) + m["change"]
    return sorted(result.values(), key=lambda p: (-abs(p["standing"]), p["kind"], p["name"]))

