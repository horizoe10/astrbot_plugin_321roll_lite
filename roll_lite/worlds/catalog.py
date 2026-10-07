"""World packs: the built-in 321roll.world-template/1 packs in worlds/, custom worlds and market installs.

Validation is ported from 321Roll application/world_template.py; the engine's
own world_rules.compile_world turns a valid world into hosted D20 rules.
presentation.json is read for text only (act titles and leads, place names,
endings); weather, ambience and image fields are ignored.

Market installs (worlds/market.py) are rows with origin_json set.  One whose id
matches a built-in pack replaces it while its revision is at least the built-in
one; uninstalling brings the built-in text back.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..storage import dumps, loads, now
from ..version import WORLD_FORMAT

if TYPE_CHECKING:
    from ..app import LiteApp

BUILTIN_DIR = Path(__file__).resolve().parents[2] / "worlds"
ENTRY_KINDS = ("region", "place", "faction", "npc", "goal", "clue")
KIND_LABELS = {"region": "地区", "place": "地点", "faction": "势力", "npc": "人物", "goal": "目标", "clue": "线索"}
# Admin-chosen cover for custom worlds (colour field + one large character), kept in presentation.cover.
COVER_TONES = ("ink", "ember", "neon", "jade", "wine", "slate")


class WorldInvalid(ValueError):
    pass


def validate_world(value: Any) -> dict[str, Any]:
    """Port of 321Roll world_template.validate with readable failure messages."""
    def require(ok: bool, message: str) -> None:
        if not ok:
            raise WorldInvalid(message)

    def integer(v: Any, low: int, high: int) -> bool:
        return type(v) is int and low <= v <= high

    def text(v: Any, limit: int, required: bool = False) -> bool:
        return (isinstance(v, str) and len(v) <= limit and (not required or bool(v.strip()))
                and not any(0xD800 <= ord(c) <= 0xDFFF for c in v))

    def key(v: Any) -> bool:
        return isinstance(v, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,100}", v) is not None

    require(isinstance(value, dict) and value.get("format") == WORLD_FORMAT, f"format 必须是 {WORLD_FORMAT}")
    require(key(value.get("id")) and integer(value.get("revision"), 1, 1000000), "id 或 revision 无效")
    for name, limit in (("title", 100), ("worldview", 6000), ("seed", 3000), ("style", 300), ("boundaries", 1000), ("guidance", 2000)):
        require(text(value.get(name), limit, name in ("title", "worldview", "seed")), f"{name} 缺失或超长（上限 {limit}）")
    ids: dict[str, set[str]] = {}
    for name in ("attributes", "resources", "skills", "items", "archetypes", "entries"):
        rows = value.get(name)
        require(isinstance(rows, list) and len(rows) <= 200, f"{name} 必须是列表")
        require(all(isinstance(r, dict) and key(r.get("id")) and text(r.get("name"), 100, True) for r in rows), f"{name} 的 id 或 name 无效")
        ids[name] = {r["id"] for r in rows}
        require(len(ids[name]) == len(rows), f"{name} 有重复 id")
    attrs, resources = value["attributes"], value["resources"]
    rules, modifier = value.get("rules"), value.get("modifier")
    require(3 <= len(attrs) <= 12 and 1 <= len(resources) <= 8 and 1 <= len(value["archetypes"]) <= 200,
            "需要 3–12 项属性、1–8 种资源、至少 1 个职业")
    require(all(integer(a.get("min"), -100, 100) and integer(a.get("max"), a["min"], 100) for a in attrs), "属性 min/max 无效")
    require(integer(value.get("budget"), sum(a["min"] for a in attrs), sum(a["max"] for a in attrs)), "budget 超出属性范围")
    require(isinstance(modifier, dict) and integer(modifier.get("baseline"), -100, 100) and integer(modifier.get("divisor"), 1, 100), "modifier 无效")
    require(all(integer(r.get("min"), 0, 1000000) and integer(r.get("max"), max(1, r["min"]), 1000000)
                and integer(r.get("initial"), r["min"], r["max"]) for r in resources), "资源 min/max/initial 无效")
    require(isinstance(rules, dict) and integer(rules.get("dcMin"), 1, 100) and integer(rules.get("dcMax"), rules["dcMin"], 100), "rules.dcMin/dcMax 无效")
    require(integer(rules.get("dc"), rules["dcMin"], rules["dcMax"]), "rules.dc 无效")
    ds = rules.get("difficulties")
    require(isinstance(ds, list) and len(ds) == 4 and all(integer(n, rules["dcMin"], rules["dcMax"]) for n in ds)
            and all(ds[i] < ds[i + 1] for i in range(3)), "rules.difficulties 必须是 4 个递增难度")
    require(integer(rules.get("seats"), 1, 16) and integer(rules.get("minPlayers"), 1, rules["seats"])
            and integer(rules.get("recommendedMin"), 1, rules["seats"])
            and integer(rules.get("recommendedMax"), rules["recommendedMin"], rules["seats"]), "席位规则无效")
    require(rules.get("mode") in ("hybrid", "choice_only", "dialogue_only") and type(rules.get("expectedResults")) is bool
            and integer(rules.get("skillSlots"), 0, 20), "rules.mode/expectedResults/skillSlots 无效")
    for cost, ref in (("failureCost", "failureResource"), ("restCost", "restCostResource"), ("restGain", "restGainResource")):
        require(integer(rules.get(cost), 0, 1000000) and isinstance(rules.get(ref), str)
                and (rules[cost] == 0 or rules[ref] in ids["resources"]), f"rules.{cost}/{ref} 无效")
    for name in ("skills", "items"):
        for row in value[name]:
            require(text(row.get("text"), 2000) and isinstance(row.get("attribute"), str)
                    and (not row["attribute"] or row["attribute"] in ids["attributes"]), f"{name}.{row['id']} 的 text/attribute 无效")
            require(integer(row.get("modifier"), -20, 20) and integer(row.get("uses"), 0, 1000)
                    and row.get("reset") in ("rest", "scene", "never"), f"{name}.{row['id']} 的 modifier/uses/reset 无效")
            for amount, ref in (("cost", "costResource"), ("gain", "gainResource")):
                require(integer(row.get(amount), 0, 1000000) and isinstance(row.get(ref), str)
                        and (row[amount] == 0 or row[ref] in ids["resources"]), f"{name}.{row['id']} 的 {amount} 无效")
            if name == "items":
                require(integer(row.get("initial"), 0, 10000) and integer(row.get("consume"), 0, 10000), f"items.{row['id']} 的 initial/consume 无效")
    inventory = value.get("inventory")
    if "inventory" in value:
        require(isinstance(inventory, dict) and set(inventory) == {"slots", "capacity"}, "inventory 无效")
        slots, capacity = inventory["slots"], inventory["capacity"]
        require(isinstance(slots, list) and len(slots) <= 20 and all(key(v) for v in slots) and len(set(slots)) == len(slots), "inventory.slots 无效")
        require(capacity is None or integer(capacity, 0, 1000000), "inventory.capacity 无效")
    total = 0
    for row in value["items"]:
        if "equipment" not in row:
            continue
        e = row["equipment"]
        require(isinstance(e, dict) and {"slot", "durability_max", "charge_max", "carrying_units"} <= set(e)
                <= {"slot", "durability_max", "charge_max", "carrying_units", "durability_cost", "charge_cost"}, f"items.{row['id']}.equipment 无效")
        require(e["slot"] is None or (inventory is not None and isinstance(e["slot"], str) and e["slot"] in inventory["slots"]), f"items.{row['id']} 的装备栏位无效")
        require(all(e[k] is None or integer(e[k], 0, 1000000) for k in ("durability_max", "charge_max")), f"items.{row['id']} 的耐久/充能无效")
        require(all(integer(e.get(k + "_cost", 0), 0, e[k + "_max"] or 0) for k in ("durability", "charge")), f"items.{row['id']} 的消耗无效")
        require(integer(e["carrying_units"], 0, 1000000), f"items.{row['id']} 的负重无效")
        total += row["initial"] * e["carrying_units"]
    if inventory is not None and inventory["capacity"] is not None:
        require(total <= inventory["capacity"], "初始物品超出负重")
    for row in value["archetypes"]:
        scores, skills = row.get("attributes"), row.get("skills")
        require(isinstance(scores, dict) and set(scores) == ids["attributes"]
                and all(integer(scores[a["id"]], a["min"], a["max"]) for a in attrs) and sum(scores.values()) == value["budget"],
                f"职业 {row['id']} 的属性必须覆盖全部属性且合计等于 budget")
        require(isinstance(skills, list) and all(isinstance(s, str) and s in ids["skills"] for s in skills)
                and len(set(skills)) == len(skills) and len(skills) <= rules["skillSlots"], f"职业 {row['id']} 的技能无效")
    for row in value["entries"]:
        require(row.get("kind") in ENTRY_KINDS and text(row.get("summary"), 4000) and text(row.get("secret"), 4000)
                and type(row.get("public")) is bool, f"条目 {row['id']} 的 kind/summary/secret/public 无效")
        links = row.get("links")
        require(isinstance(links, list) and all(isinstance(r, str) and r in ids["entries"] and r != row["id"] for r in links), f"条目 {row['id']} 的 links 无效")
    initial = value.get("initial")
    require(isinstance(initial, dict) and text(initial.get("place"), 100, True) and text(initial.get("time"), 100)
            and text(initial.get("state"), 2000), "initial 无效")
    public = {e["id"] for e in value["entries"] if e["public"]}
    require(isinstance(initial.get("links"), list) and all(isinstance(r, str) and r in public for r in initial["links"]), "initial.links 只能引用公开条目")
    return deepcopy(value)


def validate_presentation(value: Any, world: dict[str, Any]) -> dict[str, Any]:
    """Keep the text parts of a 321roll.world-pack-presentation/1 document, plus Lite's optional cover."""
    if not value:
        return {"acts": [], "places": [], "endings": []}
    if not isinstance(value, dict):
        raise WorldInvalid("presentation 必须是对象")
    acts = []
    for act in value.get("acts") or []:
        if not isinstance(act, dict) or type(act.get("number")) is not int or not str(act.get("title") or "").strip():
            raise WorldInvalid("presentation.acts 需要 number 与 title")
        acts.append({"number": act["number"], "title": str(act["title"]).strip(), "lead": str(act.get("lead") or "").strip()})
    acts.sort(key=lambda a: a["number"])
    places = [{"entry": str(p.get("entry") or ""), "name": str(p.get("name") or "").strip(),
               "aliases": [str(a) for a in p.get("aliases") or [] if str(a).strip()]}
              for p in value.get("places") or [] if isinstance(p, dict) and str(p.get("name") or "").strip()]
    endings = [{"id": str(e.get("id") or ""), "name": str(e.get("name") or "").strip(), "rule": str(e.get("rule") or "").strip()}
               for e in value.get("endings") or [] if isinstance(e, dict) and str(e.get("name") or "").strip()]
    clean: dict[str, Any] = {"acts": acts, "places": places, "endings": endings}
    cover = value.get("cover")
    if cover is not None:
        mark = str(cover.get("mark") or "").strip() if isinstance(cover, dict) else ""
        if not (1 <= len(mark) <= 2) or cover.get("tone") not in COVER_TONES:
            raise WorldInvalid("封面需要 1–2 个字和一种配色")
        clean["cover"] = {"mark": mark, "tone": cover["tone"]}
    return clean


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def brief(snapshot: dict[str, Any]) -> dict[str, str]:
    """The engine brief (validate_brief fields) built from a frozen world snapshot.

    Hidden entry text (secret) goes to the model through the worldview so the story
    stays consistent; it is never posted to the group by Lite itself.
    """
    pack = snapshot["pack"]
    entries = []
    for e in pack["entries"]:
        line = f"- {KIND_LABELS.get(e['kind'], e['kind'])}「{e['name']}」：{e['summary']}"
        if e.get("secret"):
            line += f"（隐藏设定，不可直接透露：{e['secret']}）"
        entries.append(line)
    worldview = pack["worldview"]
    if pack.get("guidance"):
        worldview += "\n\n主持要点：" + pack["guidance"]
    if entries:
        worldview += "\n\n世界条目：\n" + "\n".join(entries)
    endings = snapshot.get("presentation", {}).get("endings") or []
    if endings:
        worldview += "\n\n可能的结局：\n" + "\n".join(f"- {e['name']}：{e['rule']}" for e in endings)
    initial = pack["initial"]
    opening = pack["seed"] + f"\n\n起点：{initial['place']}" + (f"，{initial['time']}" if initial.get("time") else "")
    if initial.get("state"):
        opening += f"\n{initial['state']}"
    return {"worldview": worldview[:6000], "opening": opening[:3000], "tone": (pack.get("style") or "")[:300],
            "boundaries": (pack.get("boundaries") or "")[:1000]}


@dataclass(frozen=True)
class WorldEntry:
    id: str
    title: str
    source: str            # 'builtin' | 'custom' | 'market'
    enabled: bool
    pack: dict[str, Any]
    presentation: dict[str, Any]
    origin: dict[str, Any] | None = None   # market install record (see worlds/market.py)


class WorldCatalog:
    def __init__(self, app: "LiteApp") -> None:
        self.app = app
        self._builtin: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        self.load_builtin()

    def load_builtin(self) -> None:
        self._builtin.clear()
        if not BUILTIN_DIR.is_dir():
            return
        for folder in sorted(p for p in BUILTIN_DIR.iterdir() if (p / "pack.json").is_file()):
            pack = validate_world(json.loads((folder / "pack.json").read_text(encoding="utf-8")))
            raw = (folder / "presentation.json")
            presentation = validate_presentation(json.loads(raw.read_text(encoding="utf-8")) if raw.is_file() else None, pack)
            self._builtin[pack["id"]] = (pack, presentation)

    def _enabled(self, c: Any, world_id: str) -> bool:
        return bool(self.app.store.get_setting(c, "global", f"world.{world_id}.enabled", True))

    def entries(self, *, include_disabled: bool = False) -> list[WorldEntry]:
        result = []
        with self.app.store.read() as c:
            rows = [self._entry(c, row) for row in c.execute(
                "SELECT id,pack_json,presentation_json,origin_json FROM worlds ORDER BY created_at")]
            replacing = {e.id: e for e in rows if e.id in self._builtin}
            for world_id, (pack, presentation) in self._builtin.items():
                market = replacing.get(world_id)
                if market is not None and market.pack["revision"] >= pack["revision"]:
                    result.append(market)
                else:
                    result.append(WorldEntry(world_id, pack["title"], "builtin", self._enabled(c, world_id), pack, presentation))
            result += [e for e in rows if e.id not in self._builtin]
        return [e for e in result if include_disabled or e.enabled]

    def _entry(self, c: Any, row: Any) -> WorldEntry:
        pack = loads(row["pack_json"])
        origin = loads(row["origin_json"], None)
        return WorldEntry(row["id"], pack["title"], "market" if origin else "custom", self._enabled(c, row["id"]), pack,
                          loads(row["presentation_json"], {"acts": [], "places": [], "endings": []}), origin)

    def stored(self, world_id: str) -> WorldEntry | None:
        """The worlds-table row for an id, including a market install hidden by a newer built-in pack."""
        with self.app.store.read() as c:
            row = c.execute("SELECT id,pack_json,presentation_json,origin_json FROM worlds WHERE id=?", (world_id,)).fetchone()
            return None if row is None else self._entry(c, row)

    def builtin_revision(self, world_id: str) -> int | None:
        found = self._builtin.get(world_id)
        return None if found is None else found[0]["revision"]

    def get(self, world_id: str) -> WorldEntry | None:
        return next((e for e in self.entries(include_disabled=True) if e.id == world_id), None)

    def resolve(self, token: str) -> WorldEntry | None:
        """Pick an enabled world by list number, id or title (prefix)."""
        entries = self.entries()
        token = token.strip()
        if not token:
            return entries[0] if entries else None
        if token.isdigit() and 1 <= int(token) <= len(entries):
            return entries[int(token) - 1]
        return next((e for e in entries if e.id == token), None) or \
            next((e for e in entries if e.title == token or e.title.split(" · ")[0] == token), None) or \
            next((e for e in entries if e.title.startswith(token)), None)

    async def snapshot(self, entry: WorldEntry) -> tuple[dict[str, Any], dict[str, Any]]:
        """Frozen world snapshot and its compiled engine rules for a new room."""
        snapshot = {"source": entry.source, "pack": deepcopy(entry.pack), "presentation": deepcopy(entry.presentation)}
        snapshot["digest"] = digest({"pack": snapshot["pack"], "presentation": snapshot["presentation"]})
        rules = await self.app.engine.compile_world(snapshot["pack"])
        return snapshot, rules

    def set_enabled(self, world_id: str, enabled: bool) -> None:
        if self.get(world_id) is None:
            raise WorldInvalid("世界不存在")
        with self.app.store.tx() as c:
            self.app.store.set_setting(c, "global", f"world.{world_id}.enabled", bool(enabled))

    async def save_custom(self, pack: Any, presentation: Any = None, *, create: bool = False) -> WorldEntry:
        """Insert or replace a custom world; create=True refuses an id already in use.

        Replacing keeps the revision moving forward so saved copies can be told apart.
        """
        pack = validate_world(pack)
        clean = validate_presentation(presentation, pack)
        if pack["id"] in self._builtin:
            raise WorldInvalid("id 与内置世界包重复，请换一个 id")
        with self.app.store.read() as c:
            existing = c.execute("SELECT pack_json,origin_json FROM worlds WHERE id=?", (pack["id"],)).fetchone()
        if existing is not None and existing["origin_json"]:
            raise WorldInvalid("这个 id 属于从市场安装的世界，不能直接覆盖；可以复制一份再改")
        if existing is not None and create:
            raise WorldInvalid(f"已经有 id 为 {pack['id']} 的世界，请换一个 id")
        if existing is not None:
            pack["revision"] = max(pack["revision"], loads(existing["pack_json"]).get("revision", 0) + 1)
        try:
            await self.app.engine.compile_world(pack)
        except ValueError as exc:
            raise WorldInvalid(f"世界引擎无法编译这个世界：{exc}") from exc
        with self.app.store.tx() as c:
            c.execute("INSERT INTO worlds(id,pack_json,presentation_json,created_at,updated_at) VALUES(?,?,?,?,?) "
                      "ON CONFLICT(id) DO UPDATE SET pack_json=excluded.pack_json,presentation_json=excluded.presentation_json,"
                      "updated_at=excluded.updated_at", (pack["id"], dumps(pack), dumps(clean), now(), now()))
        return self.get(pack["id"])  # type: ignore[return-value]

    def delete_custom(self, world_id: str) -> None:
        if world_id in self._builtin:
            raise WorldInvalid("内置世界包不能删除，可以停用")
        found = self.stored(world_id)
        if found is not None and found.origin:
            raise WorldInvalid("市场安装的世界请在市场里卸载")
        with self.app.store.tx() as c:
            c.execute("DELETE FROM worlds WHERE id=?", (world_id,))
            c.execute("DELETE FROM settings WHERE scope='global' AND key=?", (f"world.{world_id}.enabled",))

    # ------------------------------------------------------------ market installs
    def check_install(self, world_id: str, revision: int) -> None:
        """Refuse an install that would overwrite a custom world or go back in revision."""
        found = self.stored(world_id)
        if found is not None and not found.origin:
            raise WorldInvalid("已经有同 id 的自定义世界，请先删除它或把它改成别的 id")
        builtin = self.builtin_revision(world_id)
        if builtin is not None and revision < builtin:
            raise WorldInvalid(f"插件自带的版本（第 {builtin} 版）比这个安装包（第 {revision} 版）新")
        if found is not None and revision < found.pack["revision"]:
            raise WorldInvalid(f"已安装第 {found.pack['revision']} 版，不能降级到第 {revision} 版；需要的话先卸载")

    def save_market(self, pack: dict[str, Any], presentation: dict[str, Any], origin: dict[str, Any]) -> None:
        """Record a checked and compiled market world (worlds/market.py does both)."""
        with self.app.store.tx() as c:
            c.execute("INSERT INTO worlds(id,pack_json,presentation_json,origin_json,created_at,updated_at) VALUES(?,?,?,?,?,?) "
                      "ON CONFLICT(id) DO UPDATE SET pack_json=excluded.pack_json,presentation_json=excluded.presentation_json,"
                      "origin_json=excluded.origin_json,updated_at=excluded.updated_at",
                      (pack["id"], dumps(pack), dumps(presentation), dumps(origin), now(), now()))

    def remove_market(self, world_id: str) -> WorldEntry:
        found = self.stored(world_id)
        if found is None or not found.origin:
            raise WorldInvalid("没有从市场安装这个世界")
        with self.app.store.tx() as c:
            c.execute("DELETE FROM worlds WHERE id=?", (world_id,))
            if world_id not in self._builtin:
                c.execute("DELETE FROM settings WHERE scope='global' AND key=?", (f"world.{world_id}.enabled",))
        return found
