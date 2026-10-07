"""Room lifecycle: open, seats and archetypes, start, pause, end, close, saves and status."""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from .. import shared
from .. import messages
from ..commands import Caller, Reply, UserError
from ..engine import VENDOR  # noqa: F401
from ..engine.gateway import EngineCallFailed
from ..storage import dumps, loads, new_id, now
from ..worlds.catalog import WorldCatalog

from story_engine import world_rules

if TYPE_CHECKING:
    from ..app import LiteApp

STATE_LABELS = {"lobby": "筹备中", "running": "进行中", "paused": "已暂停", "ended": "已完结", "closed": "已关闭"}
SLOT_LABELS = ("清晨", "白天", "傍晚", "夜晚")
SAVE_TABLES = ("actors", "records", "turns", "facts", "npcs", "votes")
ROOM_SAVE_COLUMNS = ("state", "title", "scene_json", "goal", "act", "chapter", "clock_json", "seat_cap",
                     "host_user_id", "data_json", "world_json", "rules_json")
AUTO_SAVE = "auto"          # saves.created_by of the snapshots /团 主持 回退 uses; hidden from the save list
AUTO_KEEP = 5
NUMERALS = "一二三四五六七八九十"


def catalog(app: "LiteApp") -> WorldCatalog:
    if not hasattr(app, "worlds"):
        app.worlds = WorldCatalog(app)  # type: ignore[attr-defined]
    return app.worlds  # type: ignore[attr-defined]


# ---------------------------------------------------------------- formatting
def card_data(room: sqlite3.Row, actor: sqlite3.Row) -> dict[str, Any]:
    pack = shared.world(room)["pack"]
    mod = shared.rules(room)["modifier"]
    attrs = loads(actor["attributes_json"], {})
    resources = loads(actor["resources_json"], {})
    skills = loads(actor["skills_json"], {})
    items = loads(actor["items_json"], {})
    archetype = next((a for a in pack["archetypes"] if a["id"] == actor["archetype_id"]), None)
    return {"name": shared.actor_label(actor), "user_name": actor["user_name"], "away": actor["presence"] == "away",
            "archetype": archetype["name"] if archetype else "", "archetype_text": (archetype or {}).get("text", ""),
            "attributes": [(a["name"], attrs.get(a["id"], 0), (attrs.get(a["id"], 0) - mod["baseline"]) // mod["divisor"])
                           for a in pack["attributes"]],
            "resources": [(r["name"], resources.get(r["id"], {}).get("current", 0), r["max"]) for r in pack["resources"]],
            "skills": [(s["name"], s.get("text", ""), skills[s["id"]].get("uses_left") if s.get("uses") else None)
                       for s in pack["skills"] if s["id"] in skills],
            "items": [f"{i['name']}×{items[i['id']]['quantity']}" for i in pack["items"] if items.get(i["id"], {}).get("quantity")],
            "traits": [t["title"] for t in loads(actor["traits_json"], [])]}


def character_card(room: sqlite3.Row, actor: sqlite3.Row) -> Any:
    return messages.character_card(card_data(room, actor))


def clock_text(room: sqlite3.Row) -> str:
    clock = loads(room["clock_json"], {})
    if not clock:
        return ""
    return f"第 {clock.get('day', 1)} 日 · {SLOT_LABELS[clock.get('slot', 0) % 4]}"


def act_heading(room: sqlite3.Row, number: int | None = None) -> str:
    acts = shared.world(room).get("presentation", {}).get("acts") or []
    number = room["act"] if number is None else number
    act = next((a for a in acts if a["number"] == number), None)
    if act is None:
        return ""
    label = NUMERALS[number - 1] if 1 <= number <= 10 else str(number)
    return f"第{label}幕 · {act['title']}" + (f"\n{act['lead']}" if act["lead"] else "")


# ---------------------------------------------------------------- actor building
def build_character(rules: dict[str, Any], pack: dict[str, Any], archetype_id: str, name: str) -> dict[str, Any]:
    try:
        proposal = world_rules.character(rules, archetype_id, name)
    except ValueError as exc:
        raise UserError("角色名需为 1–80 个字。") from exc
    template = rules["templates"][archetype_id]
    resources = {r["id"]: {"current": proposal["resources"][r["id"]], "min": r["min"], "max": r["max"]} for r in pack["resources"]}
    skills = {s["id"]: {"uses_left": s["uses"]} for s in pack["skills"] if s["id"] in template["skills"]}
    items = {}
    for i in pack["items"]:
        if i["initial"] > 0:
            items[i["id"]] = {"quantity": i["initial"], "uses_left": i["uses"]}
            equipment = i.get("equipment") or {}
            for field, limit in (("durability", "durability_max"), ("charges", "charge_max")):
                if equipment.get(limit) is not None:
                    items[i["id"]][field] = equipment[limit]
    return {"name": proposal["display_name"], "attributes": proposal["attributes"], "resources": resources,
            "skills": skills, "items": items}


# ---------------------------------------------------------------- commands
async def list_worlds(app: "LiteApp", caller: Caller, args: str) -> Reply:
    entries = catalog(app).entries()
    if not entries:
        return Reply().say("当前没有启用的世界包。请在后台启用或导入世界。")
    return Reply().say(messages.world_list([{"title": e.title, "players": f"{e.pack['rules']['recommendedMin']}–"
                                             f"{e.pack['rules']['recommendedMax']}"} for e in entries]))


async def open_room(app: "LiteApp", caller: Caller, args: str) -> Reply:
    entry = catalog(app).resolve(args)
    if entry is None:
        raise UserError("没有找到这个世界。发送 /团 世界 查看列表。")
    snapshot, rules = await catalog(app).snapshot(entry)
    pack = snapshot["pack"]
    room_id = new_id("room")
    cap = min(app.config.default_seat_cap, pack["rules"]["seats"])
    try:
        with app.store.tx() as c:
            if shared.open_room(c, caller.umo) is not None:
                raise UserError("本群已有一桌未关闭的团。主持人可以先发送 /团 关闭。")
            c.execute("INSERT INTO rooms(id,umo,platform,group_id,state,world_id,world_json,rules_json,title,scene_json,goal,"
                      "clock_json,seat_cap,host_user_id,created_at,updated_at) VALUES(?,?,?,?,'lobby',?,?,?,?,?,?,?,?,?,?,?)",
                      (room_id, caller.umo, caller.platform_id, caller.group_id, entry.id, dumps(snapshot), dumps(rules),
                       pack["title"], dumps({"title": pack["initial"]["place"], "description": pack["initial"].get("state", "")}),
                       "", dumps({"day": 1, "slot": 0}), cap, caller.user_id, now(), now()))
            app.store.add_event(c, room_id, "system", f"{caller.user_name} 开启了《{pack['title']}》")
            app.store.audit(c, caller.user_id, "room.open", room_id, {"world": entry.id, "umo": caller.umo})
    except sqlite3.IntegrityError as exc:
        raise UserError("本群已有一桌未关闭的团。") from exc
    return Reply().say(messages.open_card(pack["title"], pack["seed"], cap, pack["rules"]["minPlayers"], caller.user_name))


async def show_worldview(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller)
    pack = shared.world(room)["pack"]
    from ..worlds.catalog import KIND_LABELS
    entries = [(e["name"], KIND_LABELS.get(e["kind"], e["kind"]), e["summary"]) for e in pack["entries"] if e.get("public")]
    return Reply().say(messages.worldview(pack["title"], pack["worldview"], entries))


async def join(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "lobby", "running", "paused")
    with app.store.tx() as c:
        existing = c.execute("SELECT * FROM actors WHERE room_id=? AND user_id=?", (room["id"], caller.user_id)).fetchone()
        if existing is not None and existing["presence"] != "left":
            raise UserError("你已经在座位上了。")
        table = shared.table_data(room)
        if any(entry["user_id"] == caller.user_id for entry in table.get("removed", [])):
            raise UserError("主持人已请你离开这一桌。需要主持人发送 /团 主持 放行 你的昵称 后才能再入座。")
        if table.get("seating_locked") and not shared.is_host(app, caller, room):
            raise UserError("主持人暂时关闭了入座。等主持人发送 /团 主持 入座 开 后再来。")
        seated = c.execute("SELECT COUNT(*) FROM actors WHERE room_id=? AND presence<>'left'", (room["id"],)).fetchone()[0]
        if seated >= room["seat_cap"]:
            raise UserError(f"席位已满（{room['seat_cap']} 人）。")
        order = c.execute("SELECT COALESCE(MAX(order_index),0)+1 FROM actors WHERE room_id=?", (room["id"],)).fetchone()[0]
        if existing is not None:
            c.execute("UPDATE actors SET presence='present',order_index=?,user_name=?,revision=revision+1,updated_at=? WHERE id=?",
                      (order, caller.user_name, now(), existing["id"]))
            actor_id = existing["id"]
        else:
            actor_id = new_id("actor")
            c.execute("INSERT INTO actors(id,room_id,user_id,user_name,order_index,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                      (actor_id, room["id"], caller.user_id, caller.user_name, order, now(), now()))
        app.store.add_event(c, room["id"], "system", f"{caller.user_name} 入座", actor_id=actor_id)
        app.store.bump_room(c, room["id"])
    reply = Reply().say(messages.joined(caller.user_name, seated + 1, room["seat_cap"]))
    if room["state"] != "lobby":
        reply.say("故事已经开始：选好职业后会排进行动顺序末尾。")
    return reply


async def archetypes(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller)
    pack = shared.world(room)["pack"]
    names = {a["id"]: a["name"] for a in pack["attributes"]}
    skills = {s["id"]: s for s in pack["skills"]}
    order = [a["id"] for a in pack["attributes"]]
    data = [{"name": arch["name"], "text": arch.get("text", ""),
             "attributes": [(names[k], arch["attributes"][k]) for k in order],
             "skills": [(skills[s]["name"], skills[s].get("text", "")) for s in arch["skills"]]} for arch in pack["archetypes"]]
    return Reply().say(messages.archetype_list(pack["title"], data))


async def choose_archetype(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "lobby", "running", "paused")
    actor = shared.require_actor(app, caller, room)
    pack = shared.world(room)["pack"]
    words = args.split(maxsplit=1)
    if len(words) < 2:
        raise UserError("写法：/团 选职业 <序号或名称> <角色名>")
    token, name = words[0], words[1].strip()
    if token.isdigit() and 1 <= int(token) <= len(pack["archetypes"]):
        arch = pack["archetypes"][int(token) - 1]
    else:
        arch = next((a for a in pack["archetypes"] if token in (a["id"], a["name"])), None)
    if arch is None:
        raise UserError("没有这个职业。发送 /团 职业 查看列表。")
    if actor["archetype_id"] and room["state"] != "lobby":
        raise UserError("故事开始后不能更换职业。")
    built = build_character(shared.rules(room), pack, arch["id"], name)
    with app.store.tx() as c:
        changed = c.execute(
            "UPDATE actors SET name=?,archetype_id=?,attributes_json=?,resources_json=?,skills_json=?,items_json=?,"
            "revision=revision+1,updated_at=? WHERE id=? AND revision=?",
            (built["name"], arch["id"], dumps(built["attributes"]), dumps(built["resources"]), dumps(built["skills"]),
             dumps(built["items"]), now(), actor["id"], actor["revision"])).rowcount
        if changed != 1:
            raise UserError("角色刚刚发生了变化，请再发一次。")
        app.store.add_event(c, room["id"], "system", f"{caller.user_name} 选择了{arch['name']}「{built['name']}」", actor_id=actor["id"])
        app.store.bump_room(c, room["id"])
        actor = c.execute("SELECT * FROM actors WHERE id=?", (actor["id"],)).fetchone()
    reply = Reply().say(character_card(room, actor))
    public: list[Any] = []
    if caller.in_private:
        public.append(f"{caller.user_name} 建好了角色：{arch['name']}「{built['name']}」。")
    if room["state"] == "running":
        hook = await app.hooks.emit("roster_changed", room_id=room["id"], actor_id=actor["id"], change="joined")
        if caller.in_private:
            public.extend(hook.messages)
        else:
            reply.extend(hook)
    if public:
        await app.notifier.send(room["umo"], public)
    reply.say(messages.next_steps_after_card(room["state"]))
    return reply


async def show_character(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller)
    with app.store.read() as c:
        if args.strip():
            name = args.strip().lstrip("@")
            actor = c.execute("SELECT * FROM actors WHERE room_id=? AND presence<>'left' AND (name=? OR user_name=?)",
                              (room["id"], name, name)).fetchone()
        else:
            actor = shared.actor_for(c, room["id"], caller.user_id)
    if actor is None:
        raise UserError("没有找到这个角色。")
    return Reply().say(character_card(room, actor))


async def roster(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller)
    pack = shared.world(room)["pack"]
    archs = {a["id"]: a["name"] for a in pack["archetypes"]}
    with app.store.read() as c:
        actors = c.execute("SELECT * FROM actors WHERE room_id=? AND presence<>'left' ORDER BY order_index", (room["id"],)).fetchall()
    rows = [(a["user_name"], f"{archs.get(a['archetype_id'], '')}「{a['name']}」" if a["archetype_id"] else "—",
             "暂离" if a["presence"] == "away" else ("就绪" if a["archetype_id"] else "未选职业")) for a in actors]
    return Reply().say(messages.roster(len(actors), room["seat_cap"], rows))


async def leave(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "lobby", "running", "paused")
    actor = shared.require_actor(app, caller, room)
    with app.store.tx() as c:
        c.execute("UPDATE actors SET presence='left',revision=revision+1,updated_at=? WHERE id=?", (now(), actor["id"]))
        app.store.add_event(c, room["id"], "system", f"{shared.actor_label(actor)} 离开了这一桌", actor_id=actor["id"])
        app.store.bump_room(c, room["id"])
    reply = Reply().say(messages.notice(f"{shared.actor_label(actor)} 已离座", "角色和记录保留在这一桌，想回来时再发送 /团 加入。"))
    if room["state"] in ("running", "paused"):
        reply.extend(await app.hooks.emit("roster_changed", room_id=room["id"], actor_id=actor["id"], change="left"))
    return reply


async def set_presence(app: "LiteApp", caller: Caller, presence: str) -> Reply:
    room = shared.require_room(app, caller, "lobby", "running", "paused")
    actor = shared.require_actor(app, caller, room)
    return await change_presence(app, room, actor, presence)


async def change_presence(app: "LiteApp", room: sqlite3.Row, actor: sqlite3.Row, presence: str, *, by: str = "") -> Reply:
    """Away or back for one actor; by names the host when it is not the player's own choice."""
    label = shared.actor_label(actor)
    if actor["presence"] == presence:
        who = f"{label} " if by else "你"
        raise UserError(f"{who}已经是暂离状态。" if presence == "away" else f"{who}已经在场。")
    with app.store.tx() as c:
        c.execute("UPDATE actors SET presence=?,revision=revision+1,updated_at=? WHERE id=?", (presence, now(), actor["id"]))
        verb = "暂离" if presence == "away" else "回到桌边"
        app.store.add_event(c, room["id"], "system", (f"主持人让 {label} {verb}" if by else f"{label} {verb}"), actor_id=actor["id"])
        app.store.bump_room(c, room["id"])
    if by:
        title = f"主持人让 {label} {'暂离' if presence == 'away' else '回到队列'}"
        detail = (f"轮到 {label} 时会自动跳过，表决也不再等。" if presence == "away" else f"下一次轮到 {label} 时会在群里@。")
        hint = f"{actor['user_name']} 回来后可以发送 /团 返回" if presence == "away" else ""
    else:
        title = f"{label} {'暂离' if presence == 'away' else '回到了队列'}"
        detail = "轮到你时会自动跳过，表决也不再等你。" if presence == "away" else "下一次轮到你时会在群里@你。"
        hint = "回来时发送 /团 返回" if presence == "away" else ""
    reply = Reply().say(messages.notice(title, detail, hint))
    if room["state"] in ("running", "paused"):
        reply.extend(await app.hooks.emit("roster_changed", room_id=room["id"], actor_id=actor["id"],
                                          change="away" if presence == "away" else "returned"))
    return reply


async def away(app: "LiteApp", caller: Caller, args: str) -> Reply:
    return await set_presence(app, caller, "away")


async def back(app: "LiteApp", caller: Caller, args: str) -> Reply:
    return await set_presence(app, caller, "present")


async def seat_cap(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "lobby", "running", "paused")
    shared.require_host(app, caller, room)
    limit = min(app.config.max_seat_cap, shared.world(room)["pack"]["rules"]["seats"])
    if not args.strip().isdigit() or not 1 <= int(args) <= limit:
        raise UserError(f"人数上限可设为 1–{limit}。")
    with app.store.tx() as c:
        seated = c.execute("SELECT COUNT(*) FROM actors WHERE room_id=? AND presence<>'left'", (room["id"],)).fetchone()[0]
        if int(args) < seated:
            raise UserError(f"已有 {seated} 人入座，不能低于这个数。")
        c.execute("UPDATE rooms SET seat_cap=? WHERE id=?", (int(args), room["id"]))
        app.store.bump_room(c, room["id"])
    return Reply().say(messages.notice(f"席位上限改为 {int(args)} 人", hint="玩家发送 /团 加入 入座"))


async def start(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "lobby")
    shared.require_host(app, caller, room)
    rules = shared.world(room)["pack"]["rules"]
    with app.store.read() as c:
        actors = shared.present_actors(c, room["id"])
    ready = [a for a in actors if a["archetype_id"]]
    if len(ready) < rules["minPlayers"]:
        raise UserError(f"至少需要 {rules['minPlayers']} 名已选职业的在场玩家。")
    missing = [a["user_name"] for a in actors if not a["archetype_id"]]
    if missing:
        raise UserError("还有玩家没有选职业：" + "、".join(missing) + "。可以等他们选好，或请他们 /团 暂离。")
    with app.store.tx() as c:
        if c.execute("UPDATE rooms SET state='running',revision=revision+1,updated_at=? WHERE id=? AND state='lobby' AND revision=?",
                     (now(), room["id"], room["revision"])).rowcount != 1:
            raise UserError("团桌状态刚刚变化，请再试一次。")
        app.store.add_event(c, room["id"], "system", "故事开演")
    await caller.send("正在生成开场，请稍候……")
    try:
        return await app.hooks.emit("story_started", room_id=room["id"])
    except EngineCallFailed as exc:
        with app.store.tx() as c:
            c.execute("UPDATE rooms SET state='lobby',updated_at=? WHERE id=?", (now(), room["id"]))
            app.store.add_event(c, room["id"], "system", "开场生成失败，团桌回到筹备")
        raise UserError("开场生成失败：" + exc.user_message + " 团桌已回到筹备状态，可以再次 /团 开演。") from exc


async def pause(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "running")
    shared.require_host(app, caller, room)
    with app.store.tx() as c:
        c.execute("UPDATE rooms SET state='paused' WHERE id=?", (room["id"],))
        app.store.bump_room(c, room["id"])
        app.store.add_event(c, room["id"], "system", f"{caller.user_name} 暂停了故事")
    reply = Reply().say(messages.notice("故事已暂停", "回合计时停止，玩家暂时不能行动；私聊里的查看指令照常可用。", "主持人发送 /团 恢复 继续"))
    return reply.extend(await app.hooks.emit("room_paused", room_id=room["id"]))


async def resume(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "paused")
    shared.require_host(app, caller, room)
    with app.store.tx() as c:
        c.execute("UPDATE rooms SET state='running' WHERE id=?", (room["id"],))
        app.store.bump_room(c, room["id"])
        app.store.add_event(c, room["id"], "system", f"{caller.user_name} 恢复了故事")
    reply = Reply().say(messages.notice("故事继续", "回合计时重新开始。"))
    return reply.extend(await app.hooks.emit("room_resumed", room_id=room["id"]))


async def complete_story(app: "LiteApp", room_id: str, ending: dict[str, Any] | None, *, by: str) -> Reply:
    """Move a running or paused room to 'ended' (used by /团 完结 and by the ending play)."""
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        if room is None or room["state"] not in ("running", "paused"):
            return Reply()
        data = loads(room["data_json"], {})
        data["ending"] = ending
        c.execute("UPDATE rooms SET state='ended',ended_at=?,data_json=? WHERE id=?", (now(), dumps(data), room_id))
        app.store.bump_room(c, room_id)
        app.store.add_event(c, room_id, "system", "故事完结" + (f"：{ending['title']}" if ending else ""), data={"by": by})
    reply = Reply()
    reply.extend(await app.hooks.emit("story_completed", room_id=room_id, ending=ending))
    with app.store.read() as c:
        names = {a["id"]: shared.actor_label(a) for a in c.execute("SELECT * FROM actors WHERE room_id=?", (room_id,))}
        record = c.execute("SELECT document_json FROM records WHERE room_id=? AND kind='ending' ORDER BY seq DESC LIMIT 1",
                           (room_id,)).fetchone()
        rounds = c.execute("SELECT COALESCE(MAX(round),0) FROM turns WHERE room_id=?", (room_id,)).fetchone()[0]
        checks = c.execute("SELECT COUNT(*) FROM events WHERE room_id=? AND (kind='check' OR (kind='play' AND text LIKE '%【检定】%'))",
                           (room_id,)).fetchone()[0]
    epilogues = [(names.get(e["actor_ref"], ""), e["text"]) for e in (loads(record["document_json"]) if record else {}).get("epilogues", [])]
    reply.say(messages.ending_card(shared.world(room)["pack"]["title"], (ending or {}).get("title", ""), epilogues,
                                   f"共 {rounds} 轮 · {checks} 次检定"))
    return reply


async def finish(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "running", "paused")
    shared.require_host(app, caller, room)
    return await complete_story(app, room["id"], {"title": args.strip()} if args.strip() else None, by=caller.user_id)


async def close(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller)
    shared.require_host(app, caller, room)
    if room["state"] in ("running", "paused") and args.strip() != "确认":
        raise UserError("故事还没有完结。确定直接收桌请发送 /团 关闭 确认。")
    with app.store.tx() as c:
        c.execute("UPDATE rooms SET state='closed',ended_at=COALESCE(ended_at,?) WHERE id=?", (now(), room["id"]))
        app.store.bump_room(c, room["id"])
        app.store.add_event(c, room["id"], "system", f"{caller.user_name} 收桌")
        app.store.audit(c, caller.user_id, "room.close", room["id"], {})
    reply = Reply().say(messages.notice("已收桌", "这一桌的故事、角色和记录都保留在后台。", "管理员发送 /团 开启 开新的一桌"))
    return reply.extend(await app.hooks.emit("room_closed", room_id=room["id"]))


async def status(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller)
    scene = loads(room["scene_json"], {})
    acts = shared.world(room).get("presentation", {}).get("acts") or []
    act = next((a for a in acts if a["number"] == room["act"]), None)
    started = room["state"] != "lobby"
    with app.store.read() as c:
        actor = shared.actor_for(c, room["id"], caller.user_id)
        round_row = c.execute("SELECT MAX(round) FROM turns WHERE room_id=?", (room["id"],)).fetchone()
    me = None
    if actor is not None and actor["archetype_id"]:
        data = card_data(room, actor)
        me = {"name": data["name"], "archetype": data["archetype"], "resources": data["resources"]}
    extra = await app.hooks.emit("status_lines", room_id=room["id"])
    return Reply().say(messages.status_card(
        room["title"], STATE_LABELS[room["state"]], (room["act"], len(acts), act["title"]) if act and started else None,
        round_row[0] if started else None, clock_text(room) if started else "",
        scene.get("title", "") if started else "", room["goal"] if started else "", me, [str(m) for m in extra.messages]))


# ---------------------------------------------------------------- saves
def snapshot_room(c: sqlite3.Connection, room_id: str) -> dict[str, Any]:
    room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    data: dict[str, Any] = {"room": {k: room[k] for k in ROOM_SAVE_COLUMNS}}
    for table in SAVE_TABLES:
        data[table] = [dict(row) for row in c.execute(f"SELECT * FROM {table} WHERE room_id=?", (room_id,))]
    data["last_event"] = c.execute("SELECT COALESCE(MAX(id),0) FROM events WHERE room_id=?", (room_id,)).fetchone()[0]
    return data


def restore_snapshot(c: sqlite3.Connection, room_id: str, data: dict[str, Any]) -> None:
    for table in reversed(SAVE_TABLES):
        c.execute(f"DELETE FROM {table} WHERE room_id=?", (room_id,))
    for table in SAVE_TABLES:
        for row in data.get(table, []):
            columns = list(row)
            c.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                      [row[k] for k in columns])
    room = dict(data["room"])
    room["state"] = "paused"
    c.execute(f"UPDATE rooms SET {','.join(k + '=?' for k in room)} WHERE id=?", [*room.values(), room_id])
    c.execute("DELETE FROM events WHERE room_id=? AND id>?", (room_id, data["last_event"]))


def auto_snapshot(c: sqlite3.Connection, room_id: str, label: str) -> None:
    """Keep the table as it is right before an action resolves, for /团 主持 回退 (latest AUTO_KEEP only)."""
    c.execute("INSERT INTO saves(id,room_id,name,data_json,created_by,created_at) VALUES(?,?,?,?,?,?)",
              (new_id("save"), room_id, label[:60], dumps(snapshot_room(c, room_id)), AUTO_SAVE, now()))
    c.execute("DELETE FROM saves WHERE room_id=? AND created_by=? AND id NOT IN (SELECT id FROM saves WHERE room_id=? "
              "AND created_by=? ORDER BY created_at DESC, rowid DESC LIMIT ?)", (room_id, AUTO_SAVE, room_id, AUTO_SAVE, AUTO_KEEP))


async def save(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "running", "paused")
    shared.require_host(app, caller, room)
    name = args.strip()[:40] or now().replace("T", " ")[:16]
    async with app.lock(room["id"]):
        with app.store.tx() as c:
            if c.execute("SELECT COUNT(*) FROM saves WHERE room_id=? AND created_by<>?", (room["id"], AUTO_SAVE)).fetchone()[0] >= 20:
                raise UserError("每桌最多 20 个存档，请先在后台删除旧存档。")
            c.execute("INSERT INTO saves(id,room_id,name,data_json,created_by,created_at) VALUES(?,?,?,?,?,?)",
                      (new_id("save"), room["id"], name, dumps(snapshot_room(c, room["id"])), caller.user_id, now()))
            app.store.add_event(c, room["id"], "system", f"存档：{name}")
    return Reply().say(messages.notice(f"已存档「{name}」", hint="发送 /团 存档列表 查看，/团 读档 序号 读取"))


async def list_saves(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller)
    with app.store.read() as c:
        rows = c.execute("SELECT name,created_at FROM saves WHERE room_id=? AND created_by<>? ORDER BY created_at",
                         (room["id"], AUTO_SAVE)).fetchall()
    if not rows:
        return Reply().say("这一桌还没有存档。主持人发送 /团 存档 [名称] 存档。")
    return Reply().say(messages.saves_list([(r["name"], r["created_at"][:16].replace("T", " "))
                                            for r in rows]))


async def load_save(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "running", "paused", "ended")
    shared.require_host(app, caller, room)
    with app.store.read() as c:
        rows = c.execute("SELECT * FROM saves WHERE room_id=? AND created_by<>? ORDER BY created_at", (room["id"], AUTO_SAVE)).fetchall()
    token = args.strip()
    row = (rows[int(token) - 1] if token.isdigit() and 1 <= int(token) <= len(rows)
           else next((r for r in rows if r["name"] == token), None))
    if row is None:
        raise UserError("没有找到这个存档。发送 /团 存档列表 查看。")
    async with app.lock(room["id"]):
        with app.store.tx() as c:
            restore_snapshot(c, room["id"], loads(row["data_json"]))
            app.store.bump_room(c, room["id"])
            app.store.add_event(c, room["id"], "system", f"读档：{row['name']}")
            app.store.audit(c, caller.user_id, "room.load", room["id"], {"save": row["id"]})
    reply = Reply().say(messages.notice(f"已读取存档「{row['name']}」", "故事回到存档时的位置，目前处于暂停状态。", "主持人发送 /团 恢复 继续"))
    return reply.extend(await app.hooks.emit("room_restored", room_id=room["id"]))


def install(app: "LiteApp") -> None:
    catalog(app)
    r = app.router
    r.register(("世界", "世界列表"), list_worlds, summary="查看可开的世界", topic="开团")
    r.register("世界观", show_worldview, summary="阅读本桌世界的完整设定", topic="开团", private="self")
    r.register("开启", open_room, summary="开一桌（管理员）", usage="/团 开启 [世界序号或名称]", topic="开团", admin=True)
    r.register(("加入", "入座"), join, summary="入座", topic="开团")
    r.register("职业", archetypes, summary="查看职业", topic="开团", private="self")
    r.register("选职业", choose_archetype, summary="选择职业并命名角色", usage="/团 选职业 <序号> <角色名>", topic="开团", private="self")
    r.register("角色", show_character, summary="查看角色卡", usage="/团 角色 [角色名]", topic="开团", private="self")
    r.register("阵容", roster, summary="查看入座情况", topic="开团", private="self")
    r.register("退出", leave, summary="离开这一桌", topic="开团", private="room")
    r.register("暂离", away, summary="暂时离开行动队列", topic="开团", private="room")
    r.register(("返回", "返回队列"), back, summary="回到行动队列", topic="开团", private="room")
    r.register("开演", start, summary="开始故事（主持人）", topic="主持")
    r.register("人数", seat_cap, summary="设置席位上限（主持人）", usage="/团 人数 <n>", topic="主持")
    r.register("暂停", pause, summary="暂停故事（主持人）", topic="主持")
    r.register(("恢复", "继续"), resume, summary="继续故事（主持人）", topic="主持")
    r.register("完结", finish, summary="直接完结故事（主持人）", usage="/团 完结 [结局名]", topic="主持")
    r.register("关闭", close, summary="收桌（主持人）", topic="主持")
    r.register("存档", save, summary="存档（主持人）", usage="/团 存档 [名称]", topic="主持")
    r.register("存档列表", list_saves, summary="查看存档", topic="主持", private="self")
    r.register("读档", load_save, summary="读档（主持人）", usage="/团 读档 <序号或名称>", topic="主持")
    r.register("状态", status, summary="查看团桌状态", topic="基础", private="self")
