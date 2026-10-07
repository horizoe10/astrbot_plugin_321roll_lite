"""Host adjustments from the WebUI, applied when the next round's narration is committed.

The host queues changes (resources, item quantities, skills, remaining uses,
NPC attitudes).  They wait in rooms.data_json["adjustments"] and take effect in
the same transaction that stores the model's next narration, before the next
turn opens, so the story the players just read is never contradicted.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from . import loadout, shared
from .storage import dumps, loads, new_id, now

STANDING = ("敌对", "戒备", "冷淡", "中立", "友善", "信任", "盟友")
KINDS = ("resource", "item", "skill", "uses", "attitude")


class AdjustInvalid(ValueError):
    pass


def _data(room: sqlite3.Row) -> dict[str, Any]:
    return loads(room["data_json"], {})


def pending(room: sqlite3.Row) -> list[dict[str, Any]]:
    return [a for a in _data(room).get("adjustments", []) if a["state"] == "pending"]


def history(room: sqlite3.Row) -> list[dict[str, Any]]:
    return _data(room).get("adjustments", [])[-30:]


def _check(c: sqlite3.Connection, room: sqlite3.Row, change: dict[str, Any]) -> dict[str, Any]:
    pack = shared.world(room)["pack"]
    kind = change.get("kind")
    if kind not in KINDS:
        raise AdjustInvalid("未知的调整类型")
    if kind == "attitude":
        subject = str(change.get("subject") or "").strip()[:80]
        standing = change.get("standing")
        if not subject or type(standing) is not int or not -3 <= standing <= 3:
            raise AdjustInvalid("态度需要对象名和 -3 到 3 之间的档位")
        return {"kind": kind, "subject": subject, "subject_kind": "faction" if change.get("subject_kind") == "faction" else "npc",
                "standing": standing}
    actor = c.execute("SELECT * FROM actors WHERE id=? AND room_id=? AND presence<>'left'", (change.get("actor"), room["id"])).fetchone()
    if actor is None or not actor["archetype_id"]:
        raise AdjustInvalid("角色不存在或还没有建卡")
    ref = str(change.get("ref") or "")
    ids = {"resource": {r["id"] for r in pack["resources"]}, "item": {i["id"] for i in pack["items"]},
           "skill": {s["id"] for s in pack["skills"]}}
    if kind == "uses":
        entry = change.get("entry")
        if entry not in ("skill", "item") or ref not in ids[entry] or type(change.get("value")) is not int or change["value"] < 0:
            raise AdjustInvalid("剩余次数调整无效")
        return {"kind": kind, "actor": actor["id"], "entry": entry, "ref": ref, "value": change["value"]}
    if ref not in ids[kind]:
        raise AdjustInvalid("这个世界里没有该条目")
    if kind == "skill":
        return {"kind": kind, "actor": actor["id"], "ref": ref, "grant": bool(change.get("grant", True))}
    delta = change.get("delta")
    if type(delta) is not int or delta == 0 or abs(delta) > 1000:
        raise AdjustInvalid("变化量需为非零整数")
    return {"kind": kind, "actor": actor["id"], "ref": ref, "delta": delta}


def queue(c: sqlite3.Connection, room: sqlite3.Row, changes: list[dict[str, Any]], by: str, note: str = "") -> dict[str, Any]:
    if not changes or len(changes) > 40:
        raise AdjustInvalid("一次提交 1–40 项调整")
    clean = [_check(c, room, change) for change in changes]
    data = _data(room)
    item = {"id": new_id("adjust"), "state": "pending", "by": by, "note": note[:200], "changes": clean, "created_at": now()}
    data["adjustments"] = (data.get("adjustments", []) + [item])[-60:]
    c.execute("UPDATE rooms SET data_json=? WHERE id=?", (dumps(data), room["id"]))
    return item


def cancel(c: sqlite3.Connection, room: sqlite3.Row, adjustment_id: str) -> None:
    data = _data(room)
    target = next((a for a in data.get("adjustments", []) if a["id"] == adjustment_id), None)
    if target is None or target["state"] != "pending":
        raise AdjustInvalid("只能撤销还没生效的调整")
    target["state"] = "cancelled"
    c.execute("UPDATE rooms SET data_json=? WHERE id=?", (dumps(data), room["id"]))


def describe(room: sqlite3.Row, change: dict[str, Any], names: dict[str, str]) -> str:
    skills, items, resources, _ = loadout.definitions(room)
    who = names.get(change.get("actor", ""), "")
    kind = change["kind"]
    if kind == "attitude":
        return f"{change['subject']} 对队伍的态度 → {STANDING[change['standing'] + 3]}"
    if kind == "resource":
        return f"{who} {resources.get(change['ref'], change['ref'])} {change['delta']:+d}"
    if kind == "item":
        return f"{who} {'获得' if change['delta'] > 0 else '失去'}「{items[change['ref']]['name']}」×{abs(change['delta'])}"
    if kind == "skill":
        return f"{who} {'习得' if change['grant'] else '失去'}技能「{skills[change['ref']]['name']}」"
    defn = (skills if change["entry"] == "skill" else items)[change["ref"]]
    return f"{who}「{defn['name']}」剩余次数设为 {change['value']}"


def _attitude(c: sqlite3.Connection, room: sqlite3.Row, change: dict[str, Any]) -> None:
    rows = c.execute("SELECT * FROM records WHERE room_id=? AND kind='relation'", (room["id"],)).fetchall()
    row = next((r for r in rows if loads(r["document_json"])["subject"] == change["subject"]
                and loads(r["document_json"])["subject_kind"] == change["subject_kind"]), None)
    document = loads(row["document_json"]) if row else {"subject": change["subject"], "subject_kind": change["subject_kind"],
                                                         "standing": 0, "memories": []}
    delta = change["standing"] - document["standing"]
    document["standing"] = change["standing"]
    document["tier"] = STANDING[change["standing"] + 3]
    document["memories"].append({"actor_ref": "host", "text": "主持人调整", "change": delta})
    if row:
        c.execute("UPDATE records SET document_json=?,revision=revision+1,updated_at=? WHERE id=?", (dumps(document), now(), row["id"]))
    else:
        seq = c.execute("SELECT COALESCE(MAX(seq),0)+1 FROM records WHERE room_id=?", (room["id"],)).fetchone()[0]
        c.execute("INSERT INTO records(id,room_id,seq,play,kind,state,document_json,created_by,created_at,updated_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?)", (new_id("rec"), room["id"], seq, "playRelations", "relation", "active",
                                                  dumps(document), "host", now(), now()))


def apply_pending(c: sqlite3.Connection, room_id: str) -> list[str]:
    """Apply every queued adjustment of this room; returns one line per change for the group."""
    room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    data = _data(room)
    waiting = [a for a in data.get("adjustments", []) if a["state"] == "pending"]
    if not waiting:
        return []
    actors = {a["id"]: a for a in c.execute("SELECT * FROM actors WHERE room_id=?", (room_id,)).fetchall()}
    names = {k: shared.actor_label(v) for k, v in actors.items()}
    skills, items, _, _ = loadout.definitions(room)
    lines = []
    for adjustment in waiting:
        for change in adjustment["changes"]:
            if change["kind"] == "attitude":
                _attitude(c, room, change)
            else:
                actor = c.execute("SELECT * FROM actors WHERE id=?", (change["actor"],)).fetchone()
                if actor is None or actor["presence"] == "left":
                    continue
                doc = loadout.state(actor)
                if change["kind"] == "resource":
                    slot = doc["resources"][change["ref"]]
                    slot["current"] = max(slot.get("min", 0), min(slot["max"], slot["current"] + change["delta"]))
                elif change["kind"] == "item":
                    held = doc["items"].setdefault(change["ref"], {"quantity": 0, "uses_left": items[change["ref"]]["uses"]})
                    held["quantity"] = max(0, held.get("quantity", 0) + change["delta"])
                    if not held["quantity"]:
                        held.pop("equipped", None)
                elif change["kind"] == "skill":
                    if change["grant"]:
                        doc["skills"].setdefault(change["ref"], {"uses_left": skills[change["ref"]]["uses"]})
                    else:
                        doc["skills"].pop(change["ref"], None)
                else:
                    owned = doc["skills" if change["entry"] == "skill" else "items"].get(change["ref"])
                    if owned is None:
                        continue
                    owned["uses_left"] = change["value"]
                loadout.save(c, actor["id"], doc)
            lines.append(describe(room, change, names))
        adjustment["state"] = "applied"
        adjustment["applied_at"] = now()
    c.execute("UPDATE rooms SET data_json=? WHERE id=?", (dumps(data), room_id))
    return lines

