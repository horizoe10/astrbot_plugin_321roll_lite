"""Authored scene variants: validate at import, select against a frozen room world."""
from __future__ import annotations

import re
from typing import Any

SEASONS = {"spring", "summer", "autumn", "winter"}
TIMES = {"morning", "day", "dusk", "night"}
TIME_WORDS = {"morning": ("清晨", "早晨", "早上", "黎明", "上午"),
              "day": ("白天", "中午", "午后", "下午", "正午"),
              "dusk": ("傍晚", "黄昏", "日落"), "night": ("夜晚", "晚上", "夜间", "深夜", "夜里")}


def variants(extensions: dict | None) -> dict:
    return ((extensions or {}).get("321roll-lite") or {}).get("scene_variants") or {}


def validate(extensions: Any, presentation: dict, images: set[str]) -> None:
    """Unknown extension namespaces/keys remain forward compatible; this known field is strict."""
    if extensions is None:
        return
    if not isinstance(extensions, dict):
        raise ValueError("extensions 必须是对象")
    own = extensions.get("321roll-lite")
    if own is None:
        return
    if not isinstance(own, dict):
        raise ValueError("321roll-lite 扩展必须是对象")
    if "scene_variants" not in own:
        return
    data = own["scene_variants"]
    def require(ok, message):
        if not ok:
            raise ValueError("scene_variants：" + message)
    require(isinstance(data, dict) and set(data) == {"act_seasons", "places"}, "需要 act_seasons 与 places")
    acts = {a["number"] for a in presentation.get("acts") or []}
    seasons = data["act_seasons"]
    require(isinstance(seasons, list) and len(seasons) == len(acts)
            and acts == set(range(1, len(acts)+1))
            and all(isinstance(s, str) and s in SEASONS for s in seasons), "幕季节表无效")
    places = data["places"]
    known = {p["entry"] for p in presentation.get("places") or []}
    require(isinstance(places, dict) and set(places) <= known, "地点未在 presentation 登记")
    for place, group in places.items():
        require(isinstance(group, dict) and {"variants"} <= set(group) <= {"base", "variants"}, f"{place} 的登记无效")
        require(isinstance(group["variants"], list) and len(group["variants"]) <= 200, f"{place} 的差分列表无效")
        for is_base, condition in [(True, group.get("base", {})), *[(False, v) for v in group["variants"]]]:
            fields = {"season", "time"} if is_base else {"image", "season", "time", "weather", "acts"}
            require(isinstance(condition, dict) and set(condition) <= fields, f"{place} 的条件字段无效")
            if not is_base:
                require(isinstance(condition.get("image"), str) and condition["image"] in images
                        and len(condition) >= 2, f"{place} 的差分缺少图片或条件")
            if "season" in condition:
                require(isinstance(condition["season"], str) and condition["season"] in SEASONS, "季节无效")
            if "time" in condition:
                require(isinstance(condition["time"], str) and condition["time"] in TIMES, "时段无效")
            if "weather" in condition:
                require(condition["weather"] == "snow" and condition.get("season") == "winter", "雪景须指定冬季")
            if "acts" in condition:
                selected = condition["acts"]
                require(isinstance(selected, list) and bool(selected)
                        and all(type(n) is int and n in acts for n in selected), "幕号无效")
                require("season" not in condition or all(seasons[n-1] == condition["season"] for n in selected), "幕号与季节冲突")


def image_keys(extensions: dict | None) -> list[str]:
    return [v["image"] for p in variants(extensions).get("places", {}).values() for v in p["variants"]]


def time_of(title: str, clock: dict | None = None) -> str | None:
    found = [(title.index(word), -len(word), key) for key, words in TIME_WORDS.items() for word in words if word in title]
    if found:
        return min(found)[2]
    slot = (clock or {}).get("slot")
    if type(slot) is int and 0 <= slot < 4:
        return ("morning", "day", "dusk", "night")[slot]
    return {"morning": "morning", "noon": "day", "afternoon": "day", "day": "day",
            "evening": "dusk", "dusk": "dusk", "night": "night"}.get(slot)


def select(snapshot: dict, act: int, title: str, clock: dict | None = None, *, key: str = "") -> str:
    origin = snapshot.get("origin") or {}
    if not origin:
        return key or f"act:{act}"
    available = set(origin.get("images") or {}) | set(origin.get("scenes") or {})
    if origin.get("banner"):
        available.add("cover")
    def first(keys):
        return next((k for k in keys if k and k in available), "")
    fallback = [f"act:{act}", f"act-{act}", "act:1", "act-1", "cover"]
    if key:
        return first([key, *fallback])
    places = snapshot.get("presentation", {}).get("places") or []
    matches = [(-len(alias), title.index(alias), index, p) for index, p in enumerate(places)
               for alias in {p["name"], *(p.get("aliases") or [])} if alias and alias in title]
    if not matches:
        return first(fallback)
    place = min(matches, key=lambda m: m[:3])[3]
    base_key = first([place.get("image"), "place:"+place["entry"], "place-"+place["entry"]])
    registry = variants(snapshot.get("extensions"))
    group = registry.get("places", {}).get(place["entry"], {})
    seasons = registry.get("act_seasons") or []
    season = seasons[act-1] if 1 <= act <= len(seasons) else None
    time = time_of(title, clock)
    weather = "snow" if re.search(r"下雪|降雪|飘雪|雪天|雪夜|·\s*雪(?:\s|$)", title) else None
    candidates = [*group.get("variants", []), {"image": base_key, **group.get("base", {})}]
    def matches_condition(c, ignore_time=False):
        return (c["image"] in available and ("acts" not in c or act in c["acts"])
                and ("season" not in c or season == c["season"])
                and (ignore_time or "time" not in c or time == c["time"])
                and ("weather" not in c or weather == c["weather"]))
    def priority(c):
        return tuple(field in c for field in ("acts", "weather", "season", "time"))
    good = [c for c in candidates if matches_condition(c)]
    if good:
        return max(good, key=priority)["image"]
    # Weather and event constraints still apply when relaxing the time condition.
    good = [c for c in candidates if matches_condition(c, True)]
    if good:
        order = {"day": 0, "dusk": 1, "morning": 2, "night": 3}
        return min(good, key=lambda c: (order.get(c.get("time"), 4), tuple(-int(v) for v in priority(c))))["image"]
    return first([base_key, *fallback])


def art(room: Any, key: str = "", tag: str = "") -> dict[str, str]:
    from ..storage import loads
    snapshot = loads(room["world_json"])
    selected = select(snapshot, room["act"], loads(room["scene_json"], {}).get("title", ""),
                      loads(room["clock_json"], {}), key=key)
    return {"world": room["world_id"], "room": room["id"], "key": selected, "tag": tag}


def frozen_entry(app, art: dict):
    from .catalog import WorldEntry
    from ..rooms.lifecycle import catalog
    from ..storage import loads
    if art.get("room"):
        with app.store.read() as c:
            row = c.execute("SELECT world_json FROM rooms WHERE id=?", (art["room"],)).fetchone()
        if row:
            world = loads(row["world_json"])
            if "origin" in world:
                pack = world["pack"]
                return WorldEntry(pack["id"], pack["title"], world["source"], True,
                                  pack, world["presentation"], world["origin"])
    return catalog(app).get(art.get("world") or "")


def bind(message, room, key: str = "", tag: str = ""):
    message.art = art(room, key, tag)
    return message


def ending_keys(snapshot: dict, title: str) -> list[str]:
    # Optional suffix endings are matched individually, never by arbitrary substring.
    titles = {p.strip() for p in title.split(" · ")}
    return [e.get("image") or "ending:"+e["id"] for e in snapshot.get("presentation", {}).get("endings", [])
            if e["name"] in titles or e["id"] == title]
