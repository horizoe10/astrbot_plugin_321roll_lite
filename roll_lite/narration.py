"""Narration settings: how freely the model improvises, the balance of dialogue and description, and length.

A world has defaults for the three.  A package carries them in world.json's extensions
("321roll".randomness for improvisation, "321roll-lite".dialogue and .length); the admin may adjust
them on this machine (setting "world.<id>.narration", the only source for custom worlds); anything
left unset uses FALLBACK.  A table copies the world's values when it opens (hosted.narration_defaults)
and may override each one (hosted.narrative); the next narration uses whatever is current, so a
change made while the model is writing applies from the following one.

Tables opened before this existed have no copied values and keep their old behaviour; a world style
that was written as the host's directive is read back as the table's improvisation.
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from story_engine import hosted_narrative_policy as policy_rules

from .storage import loads
from .worlds.package import NARRATIVE_STYLES, narrative_style

if TYPE_CHECKING:
    from .app import LiteApp
    from .worlds.catalog import WorldEntry

FIELDS = ("improv", "dialogue", "length")
FIELD_LABELS = {"improv": "即兴程度", "dialogue": "对白与描写", "length": "正文篇幅"}
IMPROV = tuple(name for _, name, _ in NARRATIVE_STYLES)                     # 严谨 … 奔放
IMPROV_TEXT = {name: text.split("。", 1)[1] for _, name, text in NARRATIVE_STYLES}
IMPROV_RANDOMNESS = dict(zip(IMPROV, (10, 25, 50, 75, 100)))                  # what an export writes, one per band
LEGACY_DIRECTIVES = {text: name for _, name, text in NARRATIVE_STYLES}        # how tables opened before 0.1.3 kept it
DIALOGUE = ("description_high", "description_soft", "balanced", "dialogue_soft", "dialogue_high")   # 多描写 → 多对白
LENGTH = ("free", "minimal", "balanced", "epic")
LENGTH_LABELS = {"free": "不限", "minimal": "简洁", "balanced": "均衡", "epic": "长篇"}
FALLBACK = {"improv": "均衡", "dialogue": "dialogue_soft", "length": "free"}
SOURCE_LABELS = {"world": "世界设置", "local": "本机调整", "pack": "世界包", "fallback": "插件默认"}
STYLE_LIMIT = 300
_ROOM_KEYS = {"improv": "improv", "dialogue": "preset", "length": "mode"}     # names inside hosted.narrative


def label(field: str, value: str | None) -> str:
    if value is None:
        return "未设置"
    if field == "dialogue":
        return policy_rules.PRESETS[value]
    if field == "length":
        return LENGTH_LABELS[value]
    return value


def length_detail(value: str | None) -> str:
    if value in policy_rules.RANGES:
        low, high = policy_rules.RANGES[value]
        return f"每段正文 {low}–{high} 字（不计选项），字数不合时模型会自动重写"
    return "不限字数，模型通常写 2–4 个短段落"


def choices(field: str) -> tuple[str, ...]:
    return {"improv": IMPROV, "dialogue": DIALOGUE, "length": LENGTH}[field]


def parse(field: str, word: str) -> str | None:
    """The value for a word people type (偏对白, 简洁, 奔放) or a stored key; None when it is neither."""
    word = word.strip()
    return next((v for v in choices(field) if word in (v, label(field, v))), None)


def clean(raw: Any) -> dict[str, str]:
    """Only known fields with known values (stored settings are never trusted blindly)."""
    if not isinstance(raw, dict):
        return {}
    return {f: raw[f] for f in FIELDS if raw.get(f) in choices(f)}


def check(field: str, value: Any) -> str | None:
    """A WebUI or stored value: a known step, or None to follow the default; anything else is refused."""
    if field not in FIELDS:
        raise ValueError(f"未知的叙事设置：{field}")
    if value is None or value in choices(field):
        return value
    raise ValueError(f"{FIELD_LABELS[field]}没有“{value}”这一档")


# ---------------------------------------------------------------- packages
def from_extensions(extensions: Any) -> dict[str, str]:
    """World defaults declared in a world.json's extensions; anything malformed is ignored."""
    if not isinstance(extensions, dict):
        return {}
    result: dict[str, str] = {}
    full = extensions.get("321roll")
    style = narrative_style(full.get("randomness")) if isinstance(full, dict) else None
    if style is not None:
        result["improv"] = style[0]
    lite = extensions.get("321roll-lite")
    if isinstance(lite, dict):
        result.update(clean({"dialogue": lite.get("dialogue"), "length": lite.get("length")}))
    return result


def to_extensions(values: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if values.get("improv") in IMPROV:
        result["321roll"] = {"randomness": IMPROV_RANDOMNESS[values["improv"]]}
    lite = {f: values[f] for f in ("dialogue", "length") if f in values}
    if lite:
        result["321roll-lite"] = lite
    return result


def _packaged(entry: "WorldEntry") -> dict[str, str]:
    origin = entry.origin or {}
    values = clean(origin.get("narration"))
    style = narrative_style(origin.get("randomness"))
    if style is not None:
        values["improv"] = style[0]
    return values


# ---------------------------------------------------------------- worlds
def _key(world_id: str) -> str:
    return f"world.{world_id}.narration"


def stored(c: sqlite3.Connection, app: "LiteApp", world_id: str) -> dict[str, str]:
    return clean(app.store.get_setting(c, "global", _key(world_id), {}))


def world_defaults(app: "LiteApp", entry: "WorldEntry") -> dict[str, dict[str, Any]]:
    """Each field's value for new tables on this world, where it comes from, and the package's own value."""
    with app.store.read() as c:
        own = stored(c, app, entry.id)
    packaged = {} if entry.source == "custom" else _packaged(entry)
    result = {}
    for f in FIELDS:
        if f in own:
            value, source = own[f], "world" if entry.source == "custom" else "local"
        elif f in packaged:
            value, source = packaged[f], "pack"
        else:
            value, source = FALLBACK[f], "fallback"
        result[f] = {"value": value, "label": label(f, value), "source": source, "source_label": SOURCE_LABELS[source],
                     "packaged": packaged.get(f, FALLBACK[f]), "packaged_label": label(f, packaged.get(f, FALLBACK[f]))}
    return result


def default_values(app: "LiteApp", entry: "WorldEntry") -> dict[str, str]:
    return {f: d["value"] for f, d in world_defaults(app, entry).items()}


def set_world(c: sqlite3.Connection, app: "LiteApp", world_id: str, changes: dict[str, Any], *, replace: bool = False) -> dict[str, str]:
    """Store this machine's defaults for a world.  A None value clears the field (back to the package or FALLBACK)."""
    values = {} if replace else stored(c, app, world_id)
    for f, value in changes.items():
        if check(f, value) is None:
            values.pop(f, None)
        else:
            values[f] = value
    if values:
        app.store.set_setting(c, "global", _key(world_id), values)
    else:
        forget_world(c, world_id)
    return values


def forget_world(c: sqlite3.Connection, world_id: str) -> None:
    c.execute("DELETE FROM settings WHERE scope='global' AND key=?", (_key(world_id),))


# ---------------------------------------------------------------- tables
def _hosted(room: sqlite3.Row) -> dict[str, Any]:
    return loads(room["data_json"], {}).get("hosted", {})


def _own(narrative: dict[str, Any]) -> dict[str, str]:
    """The table's overrides, read from hosted.narrative (preset and mode are the names it always had)."""
    own: dict[str, str] = {}
    if narrative.get("improv") in IMPROV:
        own["improv"] = narrative["improv"]
    if narrative.get("preset") in DIALOGUE:
        own["dialogue"] = narrative["preset"]
    if "mode" in narrative:
        own["length"] = narrative["mode"] if narrative["mode"] in policy_rules.RANGES else "free"
    return own


def inherited(room: sqlite3.Row) -> dict[str, str]:
    hosted = _hosted(room)
    if "narration_defaults" in hosted:
        return clean(hosted["narration_defaults"])
    legacy = LEGACY_DIRECTIVES.get(str(hosted.get("directive") or ""))
    return {"improv": legacy} if legacy else {}


def is_legacy_directive(text: str) -> bool:
    return text in LEGACY_DIRECTIVES


def room_view(room: sqlite3.Row) -> dict[str, Any]:
    """Each field's value now, whether the table set it, and what it inherited; plus the table's style words."""
    narrative = _hosted(room).get("narrative") or {}
    own, base = _own(narrative), inherited(room)
    result: dict[str, Any] = {}
    for f in FIELDS:
        value = own.get(f, base.get(f))
        result[f] = {"value": value, "label": label(f, value), "own": f in own, "inherited": base.get(f),
                     "inherited_label": label(f, base.get(f))}
    result["style"] = str(narrative.get("style") or "")
    return result


def describe(view: dict[str, Any], field: str) -> str:
    """e.g. 偏对白（世界默认） or 简洁（本桌设置）."""
    item = view[field]
    if item["value"] is None:
        return "未设置"
    return item["label"] + ("（本桌设置）" if item["own"] else "（世界默认）")


def summary(values: dict[str, str]) -> str:
    return f"即兴 {label('improv', values.get('improv'))} · {label('dialogue', values.get('dialogue'))} · 篇幅{label('length', values.get('length'))}"


def set_room(c: sqlite3.Connection, room_id: str, changes: dict[str, Any]) -> None:
    """Table overrides: a field set to None follows the inherited value again; style "" clears the words."""
    from .plays.hosted import set_hosted_data
    row = c.execute("SELECT data_json FROM rooms WHERE id=?", (room_id,)).fetchone()
    narrative = dict((loads(row["data_json"], {}).get("hosted") or {}).get("narrative") or {})
    for f, value in changes.items():
        if f == "style":
            text = " ".join(str(value or "").split())
            if len(text) > STYLE_LIMIT:
                raise ValueError(f"风格描述最多 {STYLE_LIMIT} 字。")
            if text:
                narrative["style"] = text
            else:
                narrative.pop("style", None)
        elif check(f, value) is None:
            narrative.pop(_ROOM_KEYS[f], None)
        else:
            narrative[_ROOM_KEYS[f]] = None if value == "free" else value
    narrative["revision"] = int(narrative.get("revision", 0)) + 1
    set_hosted_data(c, room_id, narrative=narrative)


# ---------------------------------------------------------------- the model
def prompt_lines(room: sqlite3.Row) -> list[str]:
    """Lines for the model's recent events: improvisation always; dialogue and style only without a length
    (with a length the engine's narrative policy carries them)."""
    view = room_view(room)
    lines = []
    improv = view["improv"]["value"]
    if improv:
        lines.append(f"即兴程度：{improv}。{IMPROV_TEXT[improv]}")
    if view["length"]["value"] not in policy_rules.RANGES:
        dialogue = view["dialogue"]["value"]
        parts = [f"对白与描写比例“{policy_rules.PRESETS[dialogue]}”" if dialogue else "", view["style"]]
        if any(parts):
            lines.append("文风要求：" + "；".join(filter(None, parts)))
    return lines


def policy(room: sqlite3.Row, world_style: str) -> dict[str, Any] | None:
    """The engine's length-and-style policy, once the table has a length."""
    view = room_view(room)
    mode = view["length"]["value"]
    if mode not in policy_rules.RANGES:
        return None
    narrative = _hosted(room).get("narrative") or {}
    style = view["style"] or world_style.strip() or "贴合本世界的基调与氛围"
    return {"schema": policy_rules.SCHEMA, "revision": int(narrative.get("revision", 1)), "mode": mode,
            "preset": view["dialogue"]["value"] or "balanced", "style": style[:600]}

