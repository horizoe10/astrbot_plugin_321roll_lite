"""一分钟冒险: a three-step solo adventure in a random installed world, once a day per person.

/团 冒险          start today's adventure (or show the one in progress)
/团 冒险 A|B|C    pick this step's option: a d20 against its difficulty decides how it goes
/团 冒险 放弃     end it early (today's adventure is still spent)

One model call writes the whole adventure up front: a hook, three steps of three options with what success and
failure look like, and three endings.  The player is a random archetype of that world, so the world's own
attribute scores give the modifiers.  Nothing here touches a table or a story.
"""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .. import messages, shared
from ..commands import Caller, Reply, UserError
from ..dice import roll_check, success_chance
from ..engine.bridge import AstrBotModelBridge, ModelOutputInvalid, ModelUnavailable
from ..features import group_scope
from ..storage import dumps, now
from . import luck
from .schedule import BEIJING

if TYPE_CHECKING:
    from ..app import LiteApp

KEY = "fun.adventure."
STALE = timedelta(hours=3)
DAILY = 1
STEPS = 3
LABELS = "ABC"
DIFFICULTIES = ("easy", "standard", "hard")
DEFAULT_DCS = (8, 12, 15)
QUIT = ("放弃", "结束", "退出")
TIERS = {3: ("传奇", "triumph"), 2: ("凯旋", "mixed"), 1: ("狼狈脱身", "mixed"), 0: ("铩羽而归", "fall")}
SYSTEM = ("你在群聊里主持一场“一分钟冒险”：一位玩家扮演下面这个世界里的一名{role}，用三步选择走完一段很短的小冒险。请原创：\n"
          "- title：不超过 12 字，不剧透；\n"
          "- hook：40–120 字的开场，交代他为什么在这里、要做成什么事；\n"
          "- steps：正好 3 步，一步步推到一个小高潮。每步 scene 30–100 字，写眼前的局面，要能接在上一步成功或失败之后；"
          "每步 options 正好 3 个：text 是不超过 16 字的做法，attribute 从这些属性里选一个：{attributes}，"
          "difficulty 写 easy、standard 或 hard（越冒险越难），success 和 failure 各 20–70 字，写这一步成功和失败的结果；\n"
          "- endings：triumph（三步都成功）、mixed（成功一两步）、fall（一步都没成功），各 40–120 字，写这段冒险的收尾；\n"
          "- 只用这个世界公开的设定，用第二人称“你”；不写真实人物、政治、色情和血腥细节；\n"
          '- 只输出一个 JSON 对象：{{"title": "", "hook": "", "steps": [{{"scene": "", "options": [{{"text": "", "attribute": "", '
          '"difficulty": "standard", "success": "", "failure": ""}}]}}], "endings": {{"triumph": "", "mixed": "", "fall": ""}}}}。')


def _key(caller: Caller) -> str:
    return KEY + caller.user_id


def _today_start() -> str:
    start = datetime.now(UTC).astimezone(BEIJING).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC).isoformat(timespec="seconds")


def played_today(app: "LiteApp", user_id: str) -> int:
    with app.store.read() as c:
        return c.execute("SELECT COUNT(*) FROM fun_log WHERE kind='adventure' AND user_id=? AND created_at>=?",
                         (user_id, _today_start())).fetchone()[0]


def current(app: "LiteApp", caller: Caller) -> dict[str, Any] | None:
    with app.store.read() as c:
        state = app.store.get_setting(c, group_scope(caller.umo), _key(caller))
    if state and datetime.fromisoformat(state["started_at"]) < datetime.now(UTC) - STALE:
        return None
    return state


def _store(app: "LiteApp", caller: Caller, state: dict[str, Any] | None) -> None:
    with app.store.tx() as c:
        if state is None:
            c.execute("DELETE FROM settings WHERE scope=? AND key=?", (group_scope(caller.umo), _key(caller)))
        else:
            app.store.set_setting(c, group_scope(caller.umo), _key(caller), state)


def _log(app: "LiteApp", caller: Caller, kind: str, data: dict[str, Any]) -> None:
    with app.store.tx() as c:
        c.execute("INSERT INTO fun_log(umo,kind,user_id,data_json,created_at) VALUES(?,?,?,?,?)",
                  (caller.umo, kind, caller.user_id, dumps(data), now()))


def _text(value: Any, low: int, high: int) -> str:
    text = " ".join(str(value or "").split())
    if not low <= len(text) <= high:
        raise ModelOutputInvalid("adventure_field_length")
    return text


def _hero(pack: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int], dict[str, str]]:
    """A random archetype of the world, its attribute modifiers and the attribute names."""
    archetype = random.choice(pack["archetypes"])
    base = pack.get("modifier") or {"baseline": 10, "divisor": 2}
    names = {a["id"]: a["name"] for a in pack["attributes"]}
    scores = archetype.get("attributes") or {}
    mods = {ref: (int(scores.get(ref, base["baseline"])) - base["baseline"]) // base["divisor"] for ref in names}
    return archetype, mods, names


def _dcs(pack: dict[str, Any]) -> tuple[int, ...]:
    values = (pack.get("rules") or {}).get("difficulties") or []
    return tuple(int(v) for v in values[:3]) if len(values) >= 3 else DEFAULT_DCS


def _build(answer: dict[str, Any], names: dict[str, str], dcs: tuple[int, ...]) -> dict[str, Any]:
    by_name = {name.strip("〈〉"): ref for ref, name in names.items()} | {ref: ref for ref in names}
    steps = answer.get("steps")
    if not isinstance(steps, list) or len(steps) < STEPS:
        raise ModelOutputInvalid("adventure_steps")
    built = []
    for step in steps[:STEPS]:
        options = step.get("options") if isinstance(step, dict) else None
        if not isinstance(options, list) or len(options) < 2:
            raise ModelOutputInvalid("adventure_options")
        rows = []
        for i, option in enumerate(options[:3]):
            if not isinstance(option, dict):
                raise ModelOutputInvalid("adventure_options")
            ref = by_name.get(str(option.get("attribute") or "").strip().strip("〈〉")) or list(names)[i % len(names)]
            difficulty = option.get("difficulty") if option.get("difficulty") in DIFFICULTIES else "standard"
            rows.append({"text": _text(option.get("text"), 2, 30), "attr": ref, "difficulty": difficulty,
                         "dc": dcs[DIFFICULTIES.index(difficulty)],
                         "success": _text(option.get("success"), 6, 160), "failure": _text(option.get("failure"), 6, 160)})
        built.append({"scene": _text(step.get("scene"), 10, 220), "options": rows})
    endings = answer.get("endings") if isinstance(answer.get("endings"), dict) else {}
    return {"title": _text(answer.get("title"), 1, 20), "hook": _text(answer.get("hook"), 20, 260), "steps": built,
            "endings": {k: _text(endings.get(k), 10, 260) for k in ("triumph", "mixed", "fall")}}


def view(state: dict[str, Any]) -> dict[str, Any]:
    """What a card shows of the adventure so far: the current step's options with their odds."""
    step = len(state["results"])
    options = []
    if step < STEPS:
        for label, o in zip(LABELS, state["steps"][step]["options"]):
            mod = state["mods"].get(o["attr"], 0)
            options.append({"label": label, "text": o["text"], "tag": f"{state['names'][o['attr']]}·{messages.DIFFICULTY[o['difficulty']]}",
                            "chance": success_chance(mod, o["dc"])})
    return {"title": state["title"], "world": state["world"], "world_id": state["world_id"], "hero": state["name"],
            "role": state["role"], "hook": state["hook"], "step": step, "total": STEPS,
            "scene": state["steps"][step]["scene"] if step < STEPS else "", "options": options, "results": state["results"]}


async def adventure(app: "LiteApp", caller: Caller, args: str) -> Reply:
    shared.require_play(app, caller, "funAdventure")
    word = args.strip().upper().replace("Ａ", "A").replace("Ｂ", "B").replace("Ｃ", "C")
    state = current(app, caller)
    if word in QUIT:
        if state is None:
            raise UserError("你现在没有进行中的冒险。")
        _store(app, caller, None)
        _log(app, caller, "adventure_end", {"title": state["title"], "quit": True})
        return Reply().say(f"{caller.user_name} 放弃了“{state['title']}”。今天的冒险已经用掉了，明天再来。")
    if word:
        async with app.lock("adventure:" + caller.umo + ":" + caller.user_id):
            state = current(app, caller)       # read again: a second quick pick must see the first one
            if state is None:
                raise UserError("你现在没有进行中的冒险，发送 /团 冒险 开始今天的一场。")
            return _choose(app, caller, state, word)
    if state is not None:
        return Reply().say(messages.adventure_stage(view(state)))
    if played_today(app, caller.user_id) >= DAILY:
        raise UserError("你今天已经冒险过了，每人每天一次，明天再来。")
    from ..rooms import lifecycle
    worlds = [w for w in lifecycle.catalog(app).entries() if w.pack.get("archetypes") and w.pack.get("attributes")]
    if not worlds:
        raise UserError("还没有可用的世界，请管理员先在后台安装或启用一个世界。")
    async with app.lock("adventure:" + caller.umo + ":" + caller.user_id):
        if current(app, caller) is not None:
            return Reply().say(messages.adventure_stage(view(current(app, caller))))
        entry = random.choice(worlds)
        pack = entry.pack
        archetype, mods, names = _hero(pack)
        await caller.send(f"正在为 {caller.user_name} 铺开一场冒险……")
        bridge = AstrBotModelBridge(app, room_id=None, umo=caller.umo)
        system = SYSTEM.format(role=archetype["name"], attributes="、".join(n.strip("〈〉") for n in names.values()))
        prompt = (f"世界：{pack['title']}\n公开设定：{str(pack.get('worldview') or '')[:800]}\n文风：{str(pack.get('style') or '')[:200]}\n"
                  f"玩家：{caller.user_name}，身份：{archetype['name']}（{archetype.get('text', '')}）")
        try:
            built = _build(await bridge.free_json(system, prompt, "fun.adventure"), names, _dcs(pack))
        except (ModelUnavailable, ModelOutputInvalid) as exc:
            reason = str(exc) if isinstance(exc, ModelUnavailable) else "写出来的冒险不合格式。"
            raise UserError(f"这场冒险没铺开：{reason}今天的次数没有扣，稍后再发送 /团 冒险 试试。") from exc
        state = {"started_at": now(), "name": caller.user_name, "world_id": entry.id,
                 "world": messages.short_title(pack["title"]), "role": archetype["name"], "mods": mods,
                 "names": {ref: name.strip("〈〉") for ref, name in names.items()}, "results": [], **built}
        _store(app, caller, state)
        _log(app, caller, "adventure", {"title": state["title"], "world": entry.id})
    return Reply().say(messages.adventure_stage(view(state), fresh=True))


def _choose(app: "LiteApp", caller: Caller, state: dict[str, Any], word: str) -> Reply:
    step = len(state["results"])
    options = state["steps"][step]["options"]
    labels = LABELS[:len(options)]
    index = labels.find(word[:1]) if word[:1] in labels else (int(word) - 1 if word.isdigit() and 1 <= int(word) <= len(options) else -1)
    if index < 0:
        raise UserError(f"这一步可选 {'、'.join(labels)}，例如 /团 冒险 A；不玩了发送 /团 冒险 放弃。")
    option = options[index]
    mod = state["mods"].get(option["attr"], 0)
    roll = roll_check(mod, option["dc"])
    state["results"].append({"step": step + 1, "label": labels[index], "text": option["text"], "attr": state["names"][option["attr"]],
                             "difficulty": messages.DIFFICULTY[option["difficulty"]], "face": roll.face, "modifier": mod,
                             "total": roll.total, "dc": option["dc"], "ok": roll.success, "crit": roll.critical,
                             "fumble": roll.fumble, "outcome": option["success"] if roll.success else option["failure"]})
    with app.store.tx() as c:
        luck.record(c, caller.umo, caller.user_id, caller.user_name, "adventure", [roll.face])
    if len(state["results"]) < STEPS:
        _store(app, caller, state)
        return Reply().say(messages.adventure_stage(view(state)))
    _store(app, caller, None)
    wins = sum(1 for r in state["results"] if r["ok"])
    label, key = TIERS[wins]
    _log(app, caller, "adventure_end", {"title": state["title"], "wins": wins})
    return Reply().say(messages.adventure_end({**view(state), "wins": wins, "tier": label, "ending": state["endings"][key]}))


def install(app: "LiteApp") -> None:
    app.router.register("冒险", adventure, summary="一分钟冒险：随机一个世界，三步选择三次掷骰，每人每天一次",
                        usage="/团 冒险｜/团 冒险 A｜/团 冒险 放弃", topic="日常", group_only=False)
