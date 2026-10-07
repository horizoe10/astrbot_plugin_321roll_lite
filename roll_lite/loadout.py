"""World skills and items: action preparations, direct use, equipment and refills.

Rules follow 321Roll 0.3.1 (party321.application.world_loadout and
action_preparations):

* Direct use applies the entry's resource cost and gain, spends one use and,
  for items, the consumed quantity plus any durability or charge cost.  It never
  adds a dice modifier.
* A preparation is chosen together with a hosted action.  When the action is a
  check, every prepared entry with an attribute must match the check's
  attribute; their modifiers add to the roll.  All costs are checked against
  the starting resources before anything is spent, and gains from the same
  batch cannot pay for its own costs.
* Uses refill by the entry's reset: 'scene' when the host confirms a new scene
  (and on an act change), 'rest' when the actor rests, 'never' otherwise.

Actor documents: skills_json {skill_id: {uses_left}}, items_json {item_id:
{quantity, uses_left, equipped?, durability?, charges?}}, resources_json
{resource_id: {current, min, max}}.
"""
from __future__ import annotations

import re
import sqlite3
from copy import deepcopy
from typing import Any

from . import shared
from .commands import UserError
from .storage import dumps, loads, now

RESET_LABELS = {"scene": "每幕恢复", "rest": "休整后恢复", "never": "不恢复"}
REASONS = {"spent": "次数已用尽", "out_of_stock": "数量不足", "unaffordable": "资源不足", "equipment_depleted": "耐久或充能不足"}
_MARKER = re.compile(r"[\[［【]\s*用\s+([^\]］】]+?)\s*[\]］】]\s*")


def definitions(room: sqlite3.Row) -> tuple[dict[str, Any], dict[str, Any], dict[str, str], dict[str, str]]:
    pack = shared.world(room)["pack"]
    return ({s["id"]: s for s in pack["skills"]}, {i["id"]: i for i in pack["items"]},
            {r["id"]: r["name"] for r in pack["resources"]}, {a["id"]: a["name"] for a in pack["attributes"]})


def state(actor: sqlite3.Row) -> dict[str, Any]:
    return {"skills": loads(actor["skills_json"], {}), "items": loads(actor["items_json"], {}),
            "resources": loads(actor["resources_json"], {})}


def _definition(room: sqlite3.Row, kind: str, ref: str) -> dict[str, Any]:
    skills, items, _, _ = definitions(room)
    return (skills if kind == "skill" else items)[ref]


def _blocked(defn: dict[str, Any], held: dict[str, Any], kind: str, resources: dict[str, Any]) -> str | None:
    if defn["uses"] and held.get("uses_left", defn["uses"]) <= 0:
        return "spent"
    if kind == "item" and held.get("quantity", 0) < max(1, defn["consume"]):
        return "out_of_stock"
    if defn["cost"]:
        slot = resources.get(defn["costResource"], {})
        if slot.get("current", 0) - defn["cost"] < slot.get("min", 0):
            return "unaffordable"
    equipment = defn.get("equipment") or {} if kind == "item" else {}
    for cost, field in (("durability_cost", "durability"), ("charge_cost", "charges")):
        if equipment.get(cost) and (held.get(field) is None or held[field] < equipment[cost]):
            return "equipment_depleted"
    return None


def entries(room: sqlite3.Row, actor: sqlite3.Row) -> list[dict[str, Any]]:
    """Every skill and item the actor holds, with what it does and whether it can be used now."""
    skills, items, resource_names, attr_names = definitions(room)
    held = state(actor)
    result = []
    for kind, defs, owned in (("skill", skills, held["skills"]), ("item", items, held["items"])):
        for ref, mine in owned.items():
            defn = defs.get(ref)
            if defn is None or (kind == "item" and not mine.get("quantity") and not mine.get("equipped")):
                continue
            reason = _blocked(defn, mine, kind, held["resources"])
            entry = {"kind": kind, "ref": ref, "name": defn["name"], "text": defn.get("text", ""),
                     "attribute": defn["attribute"], "attribute_label": attr_names.get(defn["attribute"], ""),
                     "modifier": defn["modifier"], "uses": defn["uses"],
                     "remaining": mine.get("uses_left", defn["uses"]) if defn["uses"] else None,
                     "reset": defn["reset"], "reset_label": RESET_LABELS.get(defn["reset"], defn["reset"]),
                     "cost": {resource_names.get(defn["costResource"], defn["costResource"]): defn["cost"]} if defn["cost"] else {},
                     "gain": {resource_names.get(defn["gainResource"], defn["gainResource"]): defn["gain"]} if defn["gain"] else {},
                     "usable": reason is None, "reason": REASONS.get(reason or "", "")}
            if kind == "item":
                entry.update(quantity=mine.get("quantity", 0), consume=defn["consume"])
                if defn.get("equipment"):
                    entry["equipment"] = {**defn["equipment"], "equipped": bool(mine.get("equipped")),
                                          "durability": mine.get("durability"), "charges": mine.get("charges")}
            result.append(entry)
    return result


def effect_text(entry: dict[str, Any]) -> str:
    """'观察+1 · 剩 2 次' style summary for prompts and cards."""
    parts = []
    if entry["modifier"]:
        parts.append(f"{entry['attribute_label'] or '检定'}{entry['modifier']:+d}")
    parts += [f"{k}-{v}" for k, v in entry["cost"].items()] + [f"{k}+{v}" for k, v in entry["gain"].items()]
    if entry["remaining"] is not None:
        parts.append(f"剩 {entry['remaining']} 次")
    if entry.get("quantity") is not None:
        parts.append(f"×{entry['quantity']}")
    return " · ".join(parts)


def find(room: sqlite3.Row, actor: sqlite3.Row, name: str) -> dict[str, Any]:
    name = name.strip()
    held = entries(room, actor)
    match = next((e for e in held if e["name"] == name), None) or next((e for e in held if e["name"].startswith(name)), None)
    if match is None:
        names = "、".join(e["name"] for e in held) or "无"
        raise UserError(f"你没有“{name}”。你持有的技能和物品：{names}。")
    return match


def split_marker(text: str) -> tuple[str, list[str]]:
    """Take '[用 手电筒、全校广播]' out of an action; returns (action, names)."""
    names: list[str] = []
    def take(m: re.Match) -> str:
        names.extend(n for n in re.split(r"[、,，\s]+", m.group(1)) if n)
        return " "
    return _MARKER.sub(take, text).strip(), names


def freeze(room: sqlite3.Row, actor: sqlite3.Row, names: list[str], attribute: str | None = None) -> list[dict[str, Any]]:
    """Validate a preparation at submission and record exactly what was chosen."""
    chosen, seen = [], set()
    for name in names:
        entry = find(room, actor, name)
        key = (entry["kind"], entry["ref"])
        if key in seen:
            raise UserError(f"“{entry['name']}”重复了。")
        seen.add(key)
        if not entry["usable"]:
            raise UserError(f"“{entry['name']}”{entry['reason']}，本次不能准备。")
        if attribute and entry["attribute"] and entry["attribute"] != attribute:
            raise UserError(f"“{entry['name']}”只适用于{entry['attribute_label']}检定，本次不能准备。")
        chosen.append({"kind": entry["kind"], "ref": entry["ref"], "name": entry["name"],
                       "attribute": entry["attribute"], "modifier": entry["modifier"]})
    plan(room, state(actor), chosen, attribute=attribute)        # costs must already be affordable
    return chosen


def _apply(room: sqlite3.Row, doc: dict[str, Any], kind: str, ref: str, *, resources: bool = True) -> dict[str, int]:
    """One use of an entry on doc (skills/items/resources); returns the resource changes it made."""
    defn = _definition(room, kind, ref)
    held = doc["skills" if kind == "skill" else "items"].get(ref)
    if held is None:
        raise UserError(f"你的角色没有“{defn['name']}”。")
    reason = _blocked(defn, held, kind, doc["resources"])
    if reason and not (reason == "unaffordable" and not resources):
        raise UserError(f"“{defn['name']}”{REASONS[reason]}，本次没有消耗任何东西。")
    changes: dict[str, int] = {}
    if resources:
        if defn["cost"]:
            changes[defn["costResource"]] = -defn["cost"]
        if defn["gain"]:
            changes[defn["gainResource"]] = changes.get(defn["gainResource"], 0) + defn["gain"]
        for key, delta in changes.items():
            slot = doc["resources"][key]
            slot["current"] = min(slot["max"], max(slot.get("min", 0), slot["current"] + delta))
    if defn["uses"]:
        held["uses_left"] = held.get("uses_left", defn["uses"]) - 1
    if kind == "item":
        held["quantity"] = held.get("quantity", 0) - defn["consume"]
        equipment = defn.get("equipment") or {}
        for cost, field in (("durability_cost", "durability"), ("charge_cost", "charges")):
            if equipment.get(cost):
                held[field] -= equipment[cost]
        if not held["quantity"]:
            held.pop("equipped", None)
    return changes


def plan(room: sqlite3.Row, doc: dict[str, Any], chosen: list[dict[str, Any]], *, attribute: str | None = None
         ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Spend a preparation on a copy of doc → (new doc, summary{items, modifier, costs, gains})."""
    working = deepcopy(doc)
    costs: dict[str, int] = {}
    gains: dict[str, int] = {}
    modifier = 0
    for item in chosen:
        defn = _definition(room, item["kind"], item["ref"])
        if attribute and defn["attribute"] and defn["attribute"] != attribute:
            raise UserError(f"“{defn['name']}”只适用于{definitions(room)[3].get(defn['attribute'], '')}检定，本次没有消耗任何东西。")
        if defn["cost"]:
            costs[defn["costResource"]] = costs.get(defn["costResource"], 0) + defn["cost"]
        if defn["gain"]:
            gains[defn["gainResource"]] = gains.get(defn["gainResource"], 0) + defn["gain"]
        modifier += defn["modifier"]
    for ref, cost in costs.items():
        slot = doc["resources"][ref]
        if slot["current"] - cost < slot.get("min", 0):
            raise UserError("准备项的资源合计不足，本次没有消耗任何东西。")
    for item in chosen:
        _apply(room, working, item["kind"], item["ref"], resources=False)
    for ref, slot in doc["resources"].items():
        working["resources"][ref]["current"] = min(slot["max"], slot["current"] - costs.get(ref, 0) + gains.get(ref, 0))
    return working, {"items": chosen, "modifier": modifier, "costs": costs, "gains": gains}


def save(c: sqlite3.Connection, actor_id: str, doc: dict[str, Any]) -> None:
    c.execute("UPDATE actors SET skills_json=?,items_json=?,resources_json=?,revision=revision+1,updated_at=? WHERE id=?",
              (dumps(doc["skills"]), dumps(doc["items"]), dumps(doc["resources"]), now(), actor_id))


def use(room: sqlite3.Row, actor: sqlite3.Row, entry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    doc = state(actor)
    changes = _apply(room, doc, entry["kind"], entry["ref"])
    return doc, changes


def equip(room: sqlite3.Row, actor: sqlite3.Row, entry: dict[str, Any], on: bool) -> dict[str, Any]:
    if entry["kind"] != "item" or "equipment" not in entry or not entry["equipment"].get("slot"):
        raise UserError(f"“{entry['name']}”不是可以装备的物品。")
    doc = state(actor)
    held = doc["items"][entry["ref"]]
    slot = entry["equipment"]["slot"]
    if on:
        if held.get("equipped"):
            raise UserError(f"“{entry['name']}”已经装备着。")
        _, items, _, _ = definitions(room)
        taken = next((items[r]["name"] for r, h in doc["items"].items()
                      if h.get("equipped") and (items.get(r, {}).get("equipment") or {}).get("slot") == slot), None)
        if taken:
            raise UserError(f"这个装备位已经有“{taken}”，先卸下它。")
        held["equipped"] = True
    else:
        if not held.get("equipped"):
            raise UserError(f"“{entry['name']}”当前没有装备。")
        held.pop("equipped")
    return doc


def drop(room: sqlite3.Row, actor: sqlite3.Row, entry: dict[str, Any], quantity: int) -> dict[str, Any]:
    if entry["kind"] != "item":
        raise UserError("技能不能丢弃。")
    doc = state(actor)
    held = doc["items"][entry["ref"]]
    if held.get("equipped"):
        raise UserError(f"先卸下“{entry['name']}”再丢弃。")
    if not 1 <= quantity <= held.get("quantity", 0):
        raise UserError(f"数量要在 1–{held.get('quantity', 0)} 之间。")
    held["quantity"] -= quantity
    return doc


def refill(c: sqlite3.Connection, room: sqlite3.Row, reset: str, actor_ids: list[str] | None = None) -> int:
    """Restore uses of every entry with this reset; returns how many actors changed."""
    skills, items, _, _ = definitions(room)
    changed = 0
    rows = c.execute("SELECT * FROM actors WHERE room_id=? AND presence<>'left'", (room["id"],)).fetchall()
    for actor in rows:
        if actor_ids is not None and actor["id"] not in actor_ids:
            continue
        doc = state(actor)
        touched = False
        for defs, owned in ((skills, doc["skills"]), (items, doc["items"])):
            for ref, held in owned.items():
                defn = defs.get(ref)
                if defn and defn["uses"] and defn["reset"] == reset and held.get("uses_left") != defn["uses"]:
                    held["uses_left"] = defn["uses"]
                    touched = True
        if touched:
            save(c, actor["id"], doc)
            changed += 1
    return changed

