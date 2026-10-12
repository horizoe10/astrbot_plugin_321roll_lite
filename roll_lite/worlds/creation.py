"""Pure validation of authored character-creation options; usable by offline pack tools."""
from typing import Any

MODES = ("quick", "custom", "forge")
KEYS = ("modes", "move", "swap", "origins", "questions", "kits", "details", "traits", "relation")
MAX_ORIGINS, MAX_KITS, MAX_DETAILS, MAX_DETAIL_OPTIONS, MAX_TRAITS = 12, 8, 4, 8, 8
# When a trait's upside or downside applies; the label reads before "<属性>检定".
TRAIT_WHEN = {"any": "", "hard": "困难及以上的", "easy": "普通及以下的", "hurt": "带伤时的",
              "alone": "没人援手时的", "helped": "有人援手时的", "allIn": "孤注一掷时的"}


def validate_creation(value: Any, pack: dict[str, Any]) -> None:
    """Raise ValueError when a world's optional 'creation' block is malformed."""
    if not isinstance(value, dict) or not set(value) <= set(KEYS):
        raise ValueError("creation 只能包含 " + "、".join(KEYS))
    if "modes" in value and (not isinstance(value["modes"], list) or not set(value["modes"]) <= set(MODES)):
        raise ValueError("creation.modes 只能是 quick、custom、forge")
    if "move" in value and not (type(value["move"]) is int and 0 <= value["move"] <= 12):
        raise ValueError("creation.move 是 0–12 的整数")
    if "swap" in value and not (type(value["swap"]) is int and 0 <= value["swap"] <= pack["rules"]["skillSlots"]):
        raise ValueError("creation.swap 是 0 到技能槽数之间的整数")
    if "relation" in value and type(value["relation"]) is not bool:
        raise ValueError("creation.relation 是 true 或 false（精雕是否有开局关系这一步）")
    items = {i["id"] for i in pack["items"]}
    origins = value.get("origins") or []
    if not isinstance(origins, list) or len(origins) > MAX_ORIGINS:
        raise ValueError(f"creation.origins 最多 {MAX_ORIGINS} 个出身")
    for o in origins:
        if not (isinstance(o, dict) and isinstance(o.get("name"), str) and 1 <= len(o["name"]) <= 30
                and len(str(o.get("text") or "")) <= 200 and (not o.get("item") or o["item"] in items)):
            raise ValueError("creation.origins 每项需要 name（30 字内），可选 text 与 item（物品 id）")
    questions = value.get("questions")
    if questions is not None and not (isinstance(questions, list) and 1 <= len(questions) <= 3
                                      and all(isinstance(q, str) and 2 <= len(q) <= 40 for q in questions)):
        raise ValueError("creation.questions 是 1–3 个问题，每个 40 字内")
    kits = value.get("kits") or []
    if not isinstance(kits, list) or len(kits) > MAX_KITS:
        raise ValueError(f"creation.kits 最多 {MAX_KITS} 个装备包")
    for k in kits:
        if not (isinstance(k, dict) and isinstance(k.get("name"), str) and 1 <= len(k["name"]) <= 20
                and len(str(k.get("text") or "")) <= 80
                and isinstance(k.get("items"), dict) and k["items"]
                and all(i in items and type(n) is int and 1 <= n <= 10 for i, n in k["items"].items())):
            raise ValueError("creation.kits 每项需要 name 和 items（物品 id → 数量 1–10），可选 text（80 字内）")
    _validate_details(value.get("details"))
    _validate_traits(value.get("traits"), {a["id"] for a in pack.get("attributes") or []})


def _validate_details(details: Any) -> None:
    """Story-only build steps such as 信仰 or 外貌: options to pick and/or a line the player writes."""
    if details is None:
        return
    if not isinstance(details, list) or not 1 <= len(details) <= MAX_DETAILS:
        raise ValueError(f"creation.details 是 1–{MAX_DETAILS} 项人物细节")
    names = set()
    for d in details:
        if not (isinstance(d, dict) and set(d) <= {"name", "text", "options", "free", "modes"}
                and isinstance(d.get("name"), str) and 1 <= len(d["name"]) <= 8 and len(str(d.get("text") or "")) <= 60):
            raise ValueError("creation.details 每项需要 name（8 字内），可选 text（60 字内）、options、free、modes")
        if d["name"] in names:
            raise ValueError(f"creation.details 里“{d['name']}”重复了")
        names.add(d["name"])
        options = d.get("options") or []
        if not (isinstance(options, list) and len(options) <= MAX_DETAIL_OPTIONS and all(
                isinstance(o, dict) and isinstance(o.get("name"), str) and 1 <= len(o["name"]) <= 20
                and len(str(o.get("text") or "")) <= 60 for o in options)):
            raise ValueError(f"creation.details.options 最多 {MAX_DETAIL_OPTIONS} 个，每个 name 20 字内、text 60 字内")
        if "free" in d and type(d["free"]) is not bool:
            raise ValueError("creation.details.free 是 true 或 false")
        if not options and d.get("free") is False:
            raise ValueError(f"人物细节“{d['name']}”没有选项时必须允许玩家自己写（free 不能为 false）")
        if "modes" in d and not (isinstance(d["modes"], list) and d["modes"] and set(d["modes"]) <= {"custom", "forge"}):
            raise ValueError("creation.details.modes 只能是 custom、forge")


def _validate_traits(traits: Any, attributes: set[str]) -> None:
    """Traits carry an upside and a downside on checks; the plugin applies them when the dice are rolled."""
    if traits is None:
        return
    if not isinstance(traits, list) or not 1 <= len(traits) <= MAX_TRAITS:
        raise ValueError(f"creation.traits 是 1–{MAX_TRAITS} 个特质")
    names = set()
    for t in traits:
        if not (isinstance(t, dict) and set(t) <= {"name", "text", "up", "down", "modes"}
                and isinstance(t.get("name"), str) and 1 <= len(t["name"]) <= 12 and len(str(t.get("text") or "")) <= 80):
            raise ValueError("creation.traits 每项需要 name（12 字内）、up、down，可选 text（80 字内）、modes")
        if t["name"] in names:
            raise ValueError(f"creation.traits 里“{t['name']}”重复了")
        names.add(t["name"])
        if "modes" in t and not (isinstance(t["modes"], list) and t["modes"] and set(t["modes"]) <= {"custom", "forge"}):
            raise ValueError("creation.traits.modes 只能是 custom、forge")
        for side in ("up", "down"):
            e = t.get(side)
            if not (isinstance(e, dict) and set(e) <= {"when", "attribute", "value"}
                    and e.get("when", "any") in TRAIT_WHEN and (e.get("attribute") is None or e["attribute"] in attributes)
                    and type(e.get("value")) is int and 1 <= e["value"] <= 2):
                raise ValueError(f"特质“{t['name']}”的 {side} 需要 value（1–2），可选 when（"
                                 + "、".join(TRAIT_WHEN) + "）和 attribute（属性 id）")


def effect_text(effect: dict[str, Any], attribute_names: dict[str, str], sign: int) -> str:
    """'困难及以上的胆量检定 +1' / '带伤时的检定 −1' / '所有检定 +1'."""
    when, attr = effect.get("when", "any"), attribute_names.get(effect.get("attribute") or "", "")
    target = TRAIT_WHEN[when] + attr + "检定" if (when != "any" or attr) else "所有检定"
    return f"{target} {'+' if sign > 0 else '−'}{effect['value']}"
