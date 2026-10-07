"""WebUI backend as plain async functions: (app, payload, username) -> JSON-ready dict.

web/api.py registers them with AstrBot; tools/preview_webui.py serves them
locally.  Room operations run the same '/团' commands as an administrator so
the group sees the same receipts and the same rules apply.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .. import adjust, loadout, messages, people, shared
from ..commands import Caller, strip_command
from ..delivery import load_prefs, save_prefs
from ..engine.gateway import ENGINE_VERSION
from ..features import BY_KEY, group_scope
from ..render import MARKDOWN_PLATFORMS, PLAIN, inline, render
from ..rooms import lifecycle
from ..storage import dumps, loads, now
from ..version import DATABASE_SCHEMA, PLUGIN_VERSION, WORLD_FORMAT
from ..worlds.catalog import COVER_TONES, WorldInvalid, validate_presentation, validate_world
from .preview import message_preview

if TYPE_CHECKING:
    from ..app import LiteApp

ROOM_COMMANDS = ("暂停", "恢复", "完结", "关闭", "主持 跳过", "主持 直述", "主持 指引", "主持 推进", "主持 重试", "主持 换幕",
                 "主持 选项", "主持 集体事件", "主持 结束表决", "主持 限时", "存档", "读档", "人数",
                 "主持 交棒", "主持 移出", "主持 放行", "主持 暂离", "主持 返回", "主持 入座", "主持 退回", "主持 顺序",
                 "主持 轮到", "主持 回退", "主持 篇幅", "主持 文风", "主持 检定", "主持 审稿", "主持 发布", "主持 重写",
                 "主持 表决时限")
BACKUP_TABLES = ("settings", "worlds", "rooms", "actors", "records", "turns", "events", "facts", "npcs", "votes", "saves",
                 "outbox", "audit")


class WebError(Exception):
    pass


# Covers are a colour field plus one large character; preset worlds get a hand-picked pair.
COVERS = {"seventh-mystery": ("七", "ink"), "wildfire-hunt": ("狩", "ember"), "neon-pawnshop": ("当", "neon"),
          "nameless-sword-tomb": ("剑", "jade"), "final-curtain": ("戏", "wine"), "greycrown-prequel": ("冠", "slate")}
# Export file: one JSON holding both documents, so a world can be saved and imported again as is.
BUNDLE_FORMAT = "321roll-lite.world-bundle/1"


def cover(world_id: str, title: str, presentation: dict[str, Any] | None = None) -> dict[str, str]:
    chosen = (presentation or {}).get("cover")
    if chosen:
        return dict(chosen)
    if world_id in COVERS:
        mark, tone = COVERS[world_id]
    else:
        name = title.split(" · ")[0].removeprefix("第")
        mark = next((ch for ch in name if not ch.isspace()), "团")
        tone = COVER_TONES[sum(map(ord, world_id)) % len(COVER_TONES)]
    return {"mark": mark, "tone": tone}


def _room_row(app: "LiteApp", room_id: str) -> Any:
    with app.store.read() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    if room is None:
        raise WebError("房间不存在")
    return room


def _room_summary(c: Any, room: Any) -> dict[str, Any]:
    actors = c.execute("SELECT * FROM actors WHERE room_id=? AND presence<>'left' ORDER BY order_index", (room["id"],)).fetchall()
    turn = c.execute("SELECT * FROM turns WHERE room_id=? ORDER BY created_at DESC LIMIT 1", (room["id"],)).fetchone()
    narration = c.execute("SELECT text FROM events WHERE room_id=? AND kind='narration' ORDER BY id DESC LIMIT 1",
                          (room["id"],)).fetchone()
    turn_actor = next((a for a in actors if turn is not None and a["id"] == turn["actor_id"]), None)
    live_turn = turn is not None and turn["state"] in ("awaiting", "resolving", "failed")
    return {"id": room["id"], "title": room["title"], "world_id": room["world_id"], "group_id": room["group_id"],
            "platform": room["platform"], "state": room["state"], "state_label": lifecycle.STATE_LABELS.get(room["state"], room["state"]),
            "players": len(actors), "away": sum(a["presence"] == "away" for a in actors), "seat_cap": room["seat_cap"],
            "round": turn["round"] if turn else 0,
            "act": room["act"], "acts_total": len(shared.world(room).get("presentation", {}).get("acts") or []),
            "act_heading": lifecycle.act_heading(room).split("\n")[0] if room["state"] != "lobby" else "",
            "cover": cover(room["world_id"], room["title"], shared.world(room).get("presentation")),
            "names": [shared.actor_label(a) for a in actors],
            "turn": {"actor": shared.actor_label(turn_actor) if turn_actor else "", "state": turn["state"],
                     "deadline_at": turn["deadline_at"]} if live_turn else None,
            "excerpt": " ".join((narration["text"] if narration else "").split())[:140],
            "created_at": room["created_at"], "updated_at": room["updated_at"]}


PLAY_NOTES = {
    "playActions": ("轮流行动：选 A–D 选项或自由描述，平台掷骰、模型写正文。", "/团 选 A　/团 行动 …"),
    "playCollaboration": ("全队提议、集体事件与投票，平票时以主持人为准。", "/团 全队 …　/团 投 A"),
    "playInvestigation": ("记线索、提假设、搜查与下结论。", "/团 线索 …　/团 假设 …"),
    "playTestimony": ("记录证词、追问、出示证据、对照两份说法。", "/团 证词 …　/团 对照 #1 #2"),
    "playNegotiation": ("开启交涉、提出并签署条款，筹码够了才能达成。", "/团 交涉 …　/团 条款 #n …"),
    "playRelations": ("争取人物态度，记下同伴目标。", "/团 关系 …　/团 目标 …"),
    "playCalendar": ("推进世界时间，设定期限。", "/团 时间 花费 2 …"),
    "playProjects": ("分段推进的长期项目与安全休整。", "/团 项目 … 3　/团 休整"),
    "playConflict": ("对抗、交锋、让步，以及多人守关的合力险关。", "/团 冲突 …　/团 交锋 #n …"),
    "playChase": ("追与逃，按距离结算的对抗。", "/团 冲突 追逐 …"),
    "playDebate": ("以论点交锋的对抗。", "/团 辩论 …"),
    "playPlans": ("拟定计划、认领步骤、逐步执行。", "/团 计划 …｜…"),
    "playOracle": ("是非神谕与灵感表，只给建议、不成事实。", "/团 神谕 很可能 …"),
    "playTransformation": ("角色的转变与传承，需要本人确认。", "/团 转变 …"),
    "playFortune": ("抽一支签，之后兑现。", "/团 机运 …"),
    "playBranchEndings": ("提出结局分支，全员支持后进入并写尾声。", "/团 结局 提出 …"),
}


# ---------------------------------------------------------------- reads
async def overview(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    from ..delivery import load_prefs
    from ..plays import collaboration, hosted
    moment = datetime.now(UTC)
    since = (moment - timedelta(days=1)).isoformat(timespec="seconds")
    week = (moment - timedelta(days=6)).date().isoformat()
    month = (moment - timedelta(days=30)).isoformat(timespec="seconds")
    with app.store.read() as c:
        states = {row[0]: row[1] for row in c.execute("SELECT state,COUNT(*) FROM rooms GROUP BY state")}
        open_rows = c.execute("SELECT * FROM rooms WHERE state IN ('lobby','running','paused','ended') "
                              "ORDER BY CASE state WHEN 'running' THEN 0 WHEN 'paused' THEN 1 WHEN 'lobby' THEN 2 ELSE 3 END,"
                              " updated_at DESC LIMIT 12").fetchall()
        active = [_room_summary(c, r) for r in open_rows]
        calls = c.execute("SELECT COUNT(*),COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0),"
                          "COALESCE(SUM(status<>'ok'),0) FROM model_calls WHERE started_at>=?", (since,)).fetchone()
        days = {r["day"]: dict(r) for r in c.execute(
            "SELECT substr(started_at,1,10) AS day,COUNT(*) AS calls,SUM(status<>'ok') AS failures,"
            "SUM(input_tokens+output_tokens) AS tokens FROM model_calls WHERE substr(started_at,1,10)>=? GROUP BY day", (week,))}
        outbox = c.execute("SELECT COUNT(*) FROM outbox WHERE state='pending'").fetchone()[0]
        events = [dict(r) for r in c.execute(
            "SELECT e.created_at,e.kind,e.text,r.title,r.id AS room_id FROM events e JOIN rooms r ON r.id=e.room_id "
            "WHERE e.kind IN ('narration','action','play','vote','check','system') ORDER BY e.id DESC LIMIT 14")]
        seated = c.execute("SELECT COUNT(*) FROM actors a JOIN rooms r ON r.id=a.room_id "
                           "WHERE r.state IN ('lobby','running','paused') AND a.presence<>'left'").fetchone()[0]
        rounds_today = c.execute("SELECT COUNT(*) FROM turns WHERE state IN ('done','timed_out') AND updated_at>=?", (since,)).fetchone()[0]
        plays = {r[0]: r[1] for r in c.execute("SELECT play,COUNT(*) FROM records WHERE created_at>=? GROUP BY play", (month,))}
        plays["playActions"] = c.execute("SELECT COUNT(*) FROM turns WHERE state IN ('done','timed_out') AND created_at>=?", (month,)).fetchone()[0]
        plays["playCollaboration"] = c.execute("SELECT COUNT(*) FROM votes WHERE created_at>=?", (month,)).fetchone()[0]
        by_world = {r[0]: r[1] for r in c.execute("SELECT world_id,COUNT(*) FROM rooms GROUP BY world_id")}
        failed_turns = c.execute("SELECT t.room_id,r.title FROM turns t JOIN rooms r ON r.id=t.room_id "
                                 "WHERE t.state='failed' AND r.state IN ('running','paused')").fetchall()
        votes = []
        for row in open_rows:
            vote = collaboration.open_vote(c, row["id"])
            if vote is not None:
                voters = len(hosted.eligible_actors(c, row["id"]))
                votes.append({"room_id": row["id"], "room": row["title"], "title": vote["title"],
                              "ballots": len(loads(vote["ballots_json"], {})), "voters": voters, "deadline_at": vote["deadline_at"]})
        blocked = app.store.get_setting(c, "global", "message.markdown_blocked", []) or []
        every = app.store.get_setting(c, "global", "collective.every", 3)
    worlds = lifecycle.catalog(app).entries(include_disabled=True)
    prefs = load_prefs(app)

    attention: list[dict[str, Any]] = []
    for row in failed_turns:
        attention.append({"tone": "err", "icon": "alert", "title": "正文生成失败，等主持人重试", "detail": row["title"].split(" · ")[0],
                          "action": "去处理", "link": "rooms/" + row["room_id"]})
    for vote in votes:
        attention.append({"tone": "gold", "icon": "vote", "title": "表决进行中：" + vote["title"],
                          "detail": f"{vote['room'].split(' · ')[0]} · 已投 {vote['ballots']}/{vote['voters']}", "deadline_at": vote["deadline_at"],
                          "action": "查看", "link": "rooms/" + vote["room_id"]})
    for item in active:
        name = item["title"].split(" · ")[0]
        if item["state"] == "paused":
            attention.append({"tone": "warn", "icon": "pause", "title": "团桌已暂停", "detail": name,
                              "action": "查看", "link": "rooms/" + item["id"]})
        elif item["state"] == "lobby":
            attention.append({"tone": "", "icon": "users", "title": f"筹备中，{item['players']}/{item['seat_cap']} 人入座",
                              "detail": name, "action": "查看", "link": "rooms/" + item["id"]})
        elif item["state"] == "ended":
            attention.append({"tone": "", "icon": "flag", "title": "故事已完结，等待收桌", "detail": name,
                              "action": "收桌", "link": "rooms/" + item["id"]})
    if outbox:
        attention.append({"tone": "warn", "icon": "send", "title": f"{outbox} 条消息没送达", "detail": "群里有人再发 /团 时会自动补发",
                          "action": "查看", "link": "ops/outbox"})
    if calls[3]:
        attention.append({"tone": "err", "icon": "activity", "title": f"24 小时内模型失败 {calls[3]} 次", "detail": "看看失败原因",
                          "action": "查看", "link": "ops/usage"})
    if blocked:
        attention.append({"tone": "warn", "icon": "message", "title": "有平台拒收 Markdown，已改发纯文本", "detail": "、".join(blocked),
                          "action": "设置", "link": "messages"})
    if not app.config.admin_ids:
        attention.append({"tone": "", "icon": "key", "title": "还没有设置插件管理员", "detail": "目前只有 AstrBot 管理员可以开团",
                          "action": "设置", "link": "settings"})

    feature = None
    lead = next((r for r in open_rows if r["state"] in ("running", "paused")), None)
    if lead is not None:
        feature = await room(app, {"id": lead["id"]}, username)
        feature = {k: feature[k] for k in ("id", "title", "state", "state_label", "cover", "act", "acts", "act_heading", "round", "clock",
                                           "scene", "goal", "turn", "vote", "seat_cap", "turn_timeout_seconds")} | {
            "actors": [a for a in feature["actors"] if a["presence"] != "left"],
            "story": next((e["text"] for e in feature["events"] if e["kind"] == "narration"), ""),
            "recent": [e for e in feature["events"] if e["kind"] in ("action", "play", "check", "vote")][:4]}
    series = []
    for offset in range(6, -1, -1):
        day = (moment - timedelta(days=offset)).date().isoformat()
        row = days.get(day) or {}
        series.append({"day": day, "calls": row.get("calls") or 0, "failures": row.get("failures") or 0, "tokens": row.get("tokens") or 0})
    entries = {w.id: w for w in worlds}
    return {"version": PLUGIN_VERSION, "engine_version": ENGINE_VERSION, "rooms": states, "active_rooms": active,
            "model_24h": {"calls": calls[0], "input_tokens": calls[1], "output_tokens": calls[2], "failures": calls[3]},
            "model_week": series,
            "outbox_pending": outbox, "worlds": {"total": len(worlds), "enabled": sum(w.enabled for w in worlds)},
            "world_usage": sorted(({"id": wid, "title": entries[wid].title if wid in entries else wid, "rooms": n,
                                    "cover": cover(wid, entries[wid].title if wid in entries else wid,
                                                   entries[wid].presentation if wid in entries else None)}
                                   for wid, n in by_world.items()), key=lambda x: -x["rooms"])[:6],
            "custom_worlds": sum(w.source == "custom" for w in worlds),
            "seated": seated, "rounds_24h": rounds_today, "feature": feature, "attention": attention,
            "plays": sorted(({"key": k, "label": BY_KEY[k].label, "count": n} for k, n in plays.items() if k in BY_KEY and n),
                            key=lambda x: -x["count"]),
            "plays_enabled": sum(1 for p in app.features.table() if p["status"] == "active" and p["effective"]),
            "plays_total": sum(1 for p in app.features.table() if p["status"] == "active"),
            "message": {**prefs.public(), "blocked": list(blocked)},
            "ready": {"admins": len(app.config.admin_ids), "whitelist": app.config.group_whitelist_enabled,
                      "provider": app.config.chat_provider_id or "跟随会话", "turn_timeout": app.config.turn_timeout_seconds,
                      "collective_every": every, "allowed_groups": len(app.config.allowed_groups)},
            "recent": [{**e, "text": " ".join(e["text"].split())[:160]} for e in events]}


async def rooms(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    state = str(payload.get("state") or "")
    query = str(payload.get("q") or "").strip()
    with app.store.read() as c:
        sql, args = "SELECT * FROM rooms", []
        clauses = []
        if state == "open":
            clauses.append("state IN ('lobby','running','paused','ended')")
        elif state:
            clauses.append("state=?")
            args.append(state)
        if query:
            clauses.append("(title LIKE ? OR group_id LIKE ?)")
            args += [f"%{query}%", f"%{query}%"]
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = c.execute(sql + " ORDER BY updated_at DESC LIMIT 200", args).fetchall()
        counts = {r[0]: r[1] for r in c.execute("SELECT state,COUNT(*) FROM rooms GROUP BY state")}
        return {"rooms": [_room_summary(c, r) for r in rows], "counts": counts}


def _actor_dict(room: Any, actor: Any) -> dict[str, Any]:
    pack = shared.world(room)["pack"]
    archetype = next((a for a in pack["archetypes"] if a["id"] == actor["archetype_id"]), None)
    resources = loads(actor["resources_json"], {})
    attributes = loads(actor["attributes_json"], {})
    modifier = shared.rules(room).get("modifier") or {"baseline": 10, "divisor": 2}
    return {"id": actor["id"], "user_id": actor["user_id"], "user_name": actor["user_name"], "name": actor["name"],
            "archetype": archetype["name"] if archetype else "", "presence": actor["presence"], "order": actor["order_index"],
            "attributes": [{"name": a["name"], "value": attributes.get(a["id"]),
                            "modifier": (attributes[a["id"]] - modifier["baseline"]) // modifier["divisor"] if a["id"] in attributes else None}
                           for a in pack["attributes"]],
            "resources": [{"id": r["id"], "name": r["name"], "current": resources.get(r["id"], {}).get("current"), "max": r["max"]}
                          for r in pack["resources"]],
            "loadout": loadout.entries(room, actor) if actor["archetype_id"] else [],
            "traits": [t["title"] for t in loads(actor["traits_json"], [])]}


PLAY_GROUPS = [("playInvestigation", "调查", ("clue", "hypothesis")), ("playTestimony", "证词", ("testimony",)),
               ("playNegotiation", "交涉", ("negotiation",)), ("playRelations", "同伴目标", ("companion_goal",)),
               ("playConflict", "对抗", ("contest",)), ("playPlans", "计划", ("plan",)),
               ("playProjects", "项目与期限", ("project", "deadline")), ("playOracle", "神谕与机运", ("oracle", "fortune")),
               ("playTransformation", "转变", ("transformation",)), ("playBranchEndings", "结局", ("branch", "ending"))]


async def room(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    from ..plays import collaboration, custom, hosted
    row = _room_row(app, str(payload.get("id") or ""))
    with app.store.read() as c:
        summary = _room_summary(c, row)
        actors = [_actor_dict(row, a) for a in c.execute("SELECT * FROM actors WHERE room_id=? ORDER BY order_index", (row["id"],))]
        turn = hosted.current_turn(c, row["id"])
        vote = collaboration.open_vote(c, row["id"])
        records = [{"seq": r["seq"], "kind": r["kind"], "kind_label": custom.KIND_LABELS.get(r["kind"], r["kind"]), "state": r["state"],
                    "state_label": custom.STATE_LABELS.get(r["state"], r["state"]), "line": inline(custom.record_line(r), PLAIN),
                    "document": loads(r["document_json"]), "updated_at": r["updated_at"],
                    "steps": [inline(s, PLAIN) for s in custom.record_steps(r)]}
                   for r in c.execute("SELECT * FROM records WHERE room_id=? AND kind<>'calendar' ORDER BY seq DESC", (row["id"],))]
        met = people.people(c, row["id"])
        events = [{"id": e["id"], "kind": e["kind"], "text": e["text"], "created_at": e["created_at"]}
                  for e in c.execute("SELECT * FROM events WHERE room_id=? ORDER BY id DESC LIMIT 80", (row["id"],))]
        facts = [dict(f) for f in c.execute("SELECT fact_ref,kind,subject_ref,text FROM facts WHERE room_id=? ORDER BY created_at DESC LIMIT 60", (row["id"],))]
        npcs = [dict(n) for n in c.execute("SELECT npc_ref,name,description,motivation FROM npcs WHERE room_id=? ORDER BY updated_at DESC", (row["id"],))]
        saves = [{"name": s["name"], "created_at": s["created_at"]} for s in c.execute(
            "SELECT name,created_at FROM saves WHERE room_id=? AND created_by<>'auto' ORDER BY created_at", (row["id"],))]
        rewinds = c.execute("SELECT COUNT(*) FROM saves WHERE room_id=? AND created_by='auto'", (row["id"],)).fetchone()[0]
        usage = c.execute("SELECT COUNT(*),COALESCE(SUM(input_tokens+output_tokens),0) FROM model_calls WHERE room_id=?", (row["id"],)).fetchone()
        turn_actor = None if turn is None else c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
    names = {a["id"]: (a["name"] or a["user_name"]) for a in actors}
    pack = shared.world(row)["pack"]
    scene = loads(row["scene_json"], {})
    acts = shared.world(row).get("presentation", {}).get("acts") or []
    hosting = hosted.hosted_data(row)
    narrative = hosting.get("narrative") or {}
    table = shared.table_data(row)
    draft = loads(turn["narrative_json"], {}) if turn is not None and turn["state"] == "review" else None
    return {**summary, "scene": scene, "goal": row["goal"], "act_heading": lifecycle.act_heading(row),
            "acts": [{"number": a["number"], "title": a["title"]} for a in acts], "clock": lifecycle.clock_text(row),
            "host_user_id": row["host_user_id"], "directive": hosted.hosted_data(row).get("directive", ""),
            "actors": actors, "records": records, "events": events, "facts": facts, "npcs": npcs, "saves": saves,
            "usage": {"calls": usage[0], "tokens": usage[1]}, "turn_timeout_seconds": hosted.turn_seconds(app, row),
            "turn_timeout_own": hosted.hosted_data(row).get("turn_seconds") is not None,
            "settings": {"review": bool(hosting.get("review")),
                         "length": {v: k for k, v in hosted.LENGTH_MODES.items()}.get(narrative.get("mode"), "默认"),
                         "preset": hosted.policy_rules.PRESETS.get(narrative.get("preset"), ""), "style": narrative.get("style", ""),
                         "vote_minutes": collaboration.vote_seconds(row) // 60, "seating_locked": bool(table.get("seating_locked")),
                         "removed": [e["name"] for e in table.get("removed", [])],
                         "handover": (table.get("handover") or {}).get("name", ""), "rewinds": rewinds},
            "turn": None if turn is None else {"round": turn["round"], "state": turn["state"], "deadline_at": turn["deadline_at"],
                                               "actor": shared.actor_label(turn_actor) if turn_actor else "",
                                               "draft": None if draft is None else {
                                                   "paragraphs": draft.get("paragraphs") or [],
                                                   "suggestions": draft.get("suggestions") or []},
                                               "choices": [{"label": ch["label"], "text": ch["text"],
                                                            "tag": messages.check_tag(shared.rules(row), ch.get("check") or {})}
                                                           for ch in loads(turn["choices_json"], [])]},
            "vote": None if vote is None else {"title": vote["title"], "options": loads(vote["options_json"], []),
                                               "ballots": len(loads(vote["ballots_json"], {})), "deadline_at": vote["deadline_at"]},
            "people": met,
            "play_groups": [{"play": key, "label": label, "kinds": list(kinds)} for key, label, kinds in PLAY_GROUPS],
            "adjustments": [{**a, "lines": [adjust.describe(row, ch, names) for ch in a["changes"]]} for a in reversed(adjust.history(row))],
            "adjust_options": {"resources": [{"id": r["id"], "name": r["name"]} for r in pack["resources"]],
                               "items": [{"id": i["id"], "name": i["name"]} for i in pack["items"]],
                               "skills": [{"id": s["id"], "name": s["name"]} for s in pack["skills"]],
                               "standing": list(adjust.STANDING)},
            "endings": shared.world(row).get("presentation", {}).get("endings") or []}


async def worlds(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    result = []
    for entry in lifecycle.catalog(app).entries(include_disabled=True):
        pack = entry.pack
        result.append({"id": entry.id, "title": entry.title, "source": entry.source, "enabled": entry.enabled,
                       "worldview": pack["worldview"], "style": pack.get("style", ""),
                       "cover": cover(entry.id, entry.title, entry.presentation), "revision": pack.get("revision", 1),
                       "seed": pack.get("seed", ""),
                       "attributes": [a["name"] for a in pack["attributes"]], "resources": [r["name"] for r in pack["resources"]],
                       "archetypes": [a["name"] for a in pack["archetypes"]], "entries": len(pack["entries"]),
                       "acts": [a["title"] for a in entry.presentation.get("acts", [])],
                       "endings": [e["name"] for e in entry.presentation.get("endings", [])],
                       "shape": {"labels": [a["name"] for a in pack["attributes"]],
                                 "min": min(a["min"] for a in pack["attributes"]), "max": max(a["max"] for a in pack["attributes"]),
                                 "archetypes": [[ar["attributes"].get(a["id"], a["min"]) for a in pack["attributes"]] for ar in pack["archetypes"]]},
                       "skills": len(pack["skills"]), "items": len(pack["items"]),
                       "public_entries": sum(1 for e in pack["entries"] if e.get("public")),
                       "players": f"{pack['rules']['recommendedMin']}–{pack['rules']['recommendedMax']}"})
    return {"worlds": result, "format": WORLD_FORMAT}


async def world(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    entry = lifecycle.catalog(app).get(str(payload.get("id") or ""))
    if entry is None:
        raise WebError("世界不存在")
    return {"id": entry.id, "source": entry.source, "enabled": entry.enabled, "pack": entry.pack,
            "presentation": entry.presentation, "cover": cover(entry.id, entry.title, entry.presentation),
            "bundle_format": BUNDLE_FORMAT, "tones": list(COVER_TONES)}


async def features(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    umo = str(payload.get("umo") or "") or None
    month = (datetime.now(UTC) - timedelta(days=30)).isoformat(timespec="seconds")
    with app.store.read() as c:
        groups = [{"umo": r["umo"], "group_id": r["group_id"], "title": r["title"]} for r in c.execute(
            "SELECT umo,group_id,title FROM rooms WHERE id IN (SELECT MAX(id) FROM rooms GROUP BY umo) ORDER BY updated_at DESC")]
        usage = {r[0]: r[1] for r in c.execute("SELECT play,COUNT(*) FROM records WHERE created_at>=? GROUP BY play", (month,))}
        usage["playActions"] = c.execute("SELECT COUNT(*) FROM turns WHERE state IN ('done','timed_out') AND created_at>=?", (month,)).fetchone()[0]
        usage["playCollaboration"] = c.execute("SELECT COUNT(*) FROM votes WHERE created_at>=?", (month,)).fetchone()[0]
    plays = [{**p, "note": PLAY_NOTES.get(p["key"], ("", ""))[0], "usage": PLAY_NOTES.get(p["key"], ("", ""))[1],
              "count": usage.get(p["key"], 0)} for p in app.features.table(umo)]
    return {"plays": plays, "groups": groups, "umo": umo}


async def usage(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    with app.store.read() as c:
        days = [dict(r) for r in c.execute(
            "SELECT substr(started_at,1,10) AS day,COUNT(*) AS calls,SUM(input_tokens) AS input_tokens,"
            "SUM(output_tokens) AS output_tokens,SUM(status<>'ok') AS failures FROM model_calls "
            "GROUP BY day ORDER BY day DESC LIMIT 14")]
        contracts = [dict(r) for r in c.execute(
            "SELECT contract,COUNT(*) AS calls,SUM(status<>'ok') AS failures FROM model_calls GROUP BY contract ORDER BY calls DESC")]
        failures = [dict(r) for r in c.execute(
            "SELECT m.started_at,m.contract,m.status,m.error,m.note,r.title FROM model_calls m LEFT JOIN rooms r ON r.id=m.room_id "
            "WHERE m.status<>'ok' ORDER BY m.id DESC LIMIT 20")]
        repaired = c.execute("SELECT COUNT(*) FROM model_calls WHERE status='ok' AND note<>''").fetchone()[0]
    return {"days": days, "contracts": contracts, "failures": failures, "repaired": repaired,
            "config": {"provider": app.config.chat_provider_id or "", "timeout": app.config.model_timeout_seconds,
                       "attempts": app.config.model_attempts}}


async def outbox(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    with app.store.read() as c:
        rows = [dict(r) for r in c.execute("SELECT id,umo,text,state,attempts,last_error,created_at,updated_at FROM outbox "
                                           "WHERE state<>'sent' ORDER BY id DESC LIMIT 100")]
    return {"items": rows}


async def audit(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    with app.store.read() as c:
        rows = [{**dict(r), "detail": loads(r["detail_json"], {})} for r in c.execute(
            "SELECT id,actor,action,target,detail_json,created_at FROM audit ORDER BY id DESC LIMIT 200")]
    return {"items": rows}


async def settings(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    with app.store.read() as c:
        every = app.store.get_setting(c, "global", "collective.every", 3)
    cfg = app.config
    return {"config": {"admin_ids": sorted(cfg.admin_ids), "group_whitelist_enabled": cfg.group_whitelist_enabled,
                       "allowed_groups": sorted(cfg.allowed_groups), "chat_provider_id": cfg.chat_provider_id,
                       "model_timeout_seconds": cfg.model_timeout_seconds, "model_attempts": cfg.model_attempts,
                       "turn_timeout_seconds": cfg.turn_timeout_seconds, "default_seat_cap": cfg.default_seat_cap,
                       "max_seat_cap": cfg.max_seat_cap},
            "collective_every": every, "message": load_prefs(app).public(),
            "markdown_platforms": sorted(MARKDOWN_PLATFORMS)}


async def about(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    return {"version": PLUGIN_VERSION, "engine_version": ENGINE_VERSION, "database_schema": DATABASE_SCHEMA,
            "world_format": WORLD_FORMAT, "data_dir": str(app.data_dir), "commands": len(app.router.commands)}


# ---------------------------------------------------------------- writes
async def room_command(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    row = _room_row(app, str(payload.get("id") or ""))
    command = " ".join(str(payload.get("command") or "").split())
    verb = next((v for v in sorted(ROOM_COMMANDS, key=len, reverse=True) if command == v or command.startswith(v + " ")), None)
    if verb is None:
        raise WebError("后台不支持这个操作")
    sent: list[Any] = []

    async def send(item: Any) -> None:
        sent.append(item)
        await app.notifier.send(row["umo"], item)

    caller = Caller(umo=row["umo"], platform_id=row["platform"], group_id=row["group_id"], user_id=f"webui:{username}",
                    user_name=f"后台·{username}", is_admin=True, send=send)
    body = strip_command("团 " + command)
    reply = await app.router.dispatch(app, caller, body or "")
    with app.store.tx() as c:
        app.store.audit(c, f"webui:{username}", "web.room_command", row["id"], {"command": command})
    await app.notifier.send(row["umo"], reply.messages)
    return {"messages": [render(item, PLAIN) for item in sent + reply.messages]}


async def room_adjust(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    """Queue host adjustments; they apply when the next round's narration is committed."""
    row = _room_row(app, str(payload.get("id") or ""))
    if row["state"] not in ("lobby", "running", "paused"):
        raise WebError("只有未完结的团桌可以调整")
    changes = payload.get("changes")
    try:
        with app.store.tx() as c:
            item = adjust.queue(c, row, changes if isinstance(changes, list) else [], f"webui:{username}", str(payload.get("note") or ""))
            app.store.audit(c, f"webui:{username}", "web.room_adjust", row["id"], {"changes": item["changes"]})
    except adjust.AdjustInvalid as exc:
        raise WebError(str(exc)) from exc
    return await room(app, {"id": row["id"]}, username)


async def room_adjust_cancel(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    row = _room_row(app, str(payload.get("id") or ""))
    try:
        with app.store.tx() as c:
            adjust.cancel(c, row, str(payload.get("adjustment") or ""))
            app.store.audit(c, f"webui:{username}", "web.room_adjust_cancel", row["id"], {"adjustment": payload.get("adjustment")})
    except adjust.AdjustInvalid as exc:
        raise WebError(str(exc)) from exc
    return await room(app, {"id": row["id"]}, username)


async def world_toggle(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    try:
        lifecycle.catalog(app).set_enabled(str(payload.get("id") or ""), bool(payload.get("enabled")))
    except WorldInvalid as exc:
        raise WebError(str(exc)) from exc
    with app.store.tx() as c:
        app.store.audit(c, f"webui:{username}", "web.world_toggle", str(payload.get("id")), {"enabled": bool(payload.get("enabled"))})
    return await worlds(app, {}, username)


def _parse_json(value: Any, label: str) -> Any:
    if isinstance(value, (dict, list)) or value is None:
        return value
    try:
        return json.loads(str(value)) if str(value).strip() else None
    except json.JSONDecodeError as exc:
        raise WebError(f"{label} 不是有效的 JSON：第 {exc.lineno} 行第 {exc.colno} 列") from exc


def _world_input(payload: dict[str, Any]) -> tuple[Any, Any]:
    """(pack, presentation) from separate fields or from an exported bundle file in either field."""
    pack = _parse_json(payload.get("pack"), "世界")
    presentation = _parse_json(payload.get("presentation"), "呈现")
    bundle = _parse_json(payload.get("bundle"), "世界文件")
    for candidate in (bundle, pack):
        if isinstance(candidate, dict) and candidate.get("format") == BUNDLE_FORMAT:
            return candidate.get("pack"), presentation or candidate.get("presentation")
    return pack, presentation


async def world_validate(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    pack, presentation = _world_input(payload)
    try:
        pack = validate_world(pack)
        clean = validate_presentation(presentation, pack)
        rules = await app.engine.compile_world(pack)
    except (WorldInvalid, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    existing = lifecycle.catalog(app).get(pack["id"])
    return {"ok": True, "summary": {"id": pack["id"], "title": pack["title"], "attributes": len(pack["attributes"]),
                                    "archetypes": len(pack["archetypes"]), "entries": len(pack["entries"]),
                                    "acts": len(clean["acts"]), "endings": len(clean["endings"]),
                                    "difficulties": rules["difficulties"]},
            "existing": None if existing is None else existing.source}


async def world_save(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    pack, presentation = _world_input(payload)
    try:
        entry = await lifecycle.catalog(app).save_custom(pack, presentation, create=bool(payload.get("create")))
    except (WorldInvalid, ValueError) as exc:
        raise WebError(str(exc)) from exc
    with app.store.tx() as c:
        app.store.audit(c, f"webui:{username}", "web.world_save", entry.id, {"revision": entry.pack["revision"]})
    return {"id": entry.id, "revision": entry.pack["revision"]}


async def world_delete(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    try:
        lifecycle.catalog(app).delete_custom(str(payload.get("id") or ""))
    except WorldInvalid as exc:
        raise WebError(str(exc)) from exc
    with app.store.tx() as c:
        app.store.audit(c, f"webui:{username}", "web.world_delete", str(payload.get("id")), {})
    return await worlds(app, {}, username)


async def feature_set(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    key = str(payload.get("key") or "")
    if key not in BY_KEY:
        raise WebError("玩法不存在")
    umo = str(payload.get("umo") or "") or None
    value = payload.get("value")
    if value is not None:
        value = bool(value)
    try:
        app.features.set(group_scope(umo) if umo else "global", key, value)
    except ValueError as exc:
        raise WebError("这个玩法不能切换") from exc
    with app.store.tx() as c:
        app.store.audit(c, f"webui:{username}", "web.feature_set", key, {"umo": umo, "value": value})
    return await features(app, {"umo": umo}, username)


async def settings_set(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    every = payload.get("collective_every")
    if type(every) is not int or not 0 <= every <= 20:
        raise WebError("集体事件间隔为 0–20 轮")
    with app.store.tx() as c:
        app.store.set_setting(c, "global", "collective.every", every)
        app.store.audit(c, f"webui:{username}", "web.settings_set", "collective.every", {"value": every})
    return await settings(app, {}, username)


async def settings_message(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    if payload.get("format") not in ("markdown", "plain"):
        raise WebError("推送格式只能是 Markdown 或纯文本")
    prefs = save_prefs(app, payload)
    with app.store.tx() as c:
        app.store.audit(c, f"webui:{username}", "web.settings_message", "message.prefs", prefs.public())
    return await settings(app, {}, username)


async def outbox_action(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    item_id, action = payload.get("id"), payload.get("action")
    with app.store.read() as c:
        row = c.execute("SELECT * FROM outbox WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise WebError("消息不存在")
    if action == "retry":
        ok = True
        try:
            await app.notifier.retry(row["umo"], row["text"])
        except Exception as exc:
            ok, error = False, str(exc)[:300]
        with app.store.tx() as c:
            c.execute("UPDATE outbox SET state=?,attempts=attempts+1,last_error=?,updated_at=? WHERE id=?",
                      ("sent" if ok else "pending", "" if ok else error, now(), item_id))
        if not ok:
            raise WebError("重试失败：" + error)
    elif action == "drop":
        with app.store.tx() as c:
            c.execute("UPDATE outbox SET state='dropped',updated_at=? WHERE id=?", (now(), item_id))
    else:
        raise WebError("未知操作")
    return await outbox(app, {}, username)


def export_backup(app: "LiteApp") -> dict[str, Any]:
    with app.store.read() as c:
        return {"format": "321roll-lite-backup/1", "plugin_version": PLUGIN_VERSION, "database_schema": DATABASE_SCHEMA,
                "exported_at": now(), "tables": {t: [dict(r) for r in c.execute(f"SELECT * FROM {t}")] for t in BACKUP_TABLES}}


async def backup_info(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    with app.store.read() as c:
        counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in BACKUP_TABLES}
    size = (app.store.path.stat().st_size if app.store.path.exists() else 0)
    return {"counts": counts, "database_bytes": size, "path": str(app.store.path)}


async def backup_import(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    data = _parse_json(payload.get("data"), "备份")
    if payload.get("confirm") != "覆盖":
        raise WebError("导入会覆盖现有全部数据，请在确认框输入“覆盖”")
    if not isinstance(data, dict) or data.get("format") != "321roll-lite-backup/1" or data.get("database_schema") != DATABASE_SCHEMA:
        raise WebError("备份格式或数据库版本不匹配")
    tables = data.get("tables") or {}
    with app.store.tx() as c:
        for table in reversed(BACKUP_TABLES):
            c.execute(f"DELETE FROM {table}")
        for table in BACKUP_TABLES:
            for row in tables.get(table, []):
                columns = list(row)
                c.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", [row[k] for k in columns])
        app.store.audit(c, f"webui:{username}", "web.backup_import", "database", {"exported_at": data.get("exported_at")})
    return await backup_info(app, {}, username)


GET_ROUTES = {"overview": overview, "rooms": rooms, "room": room, "worlds": worlds, "world": world, "features": features,
              "usage": usage, "outbox": outbox, "audit": audit, "settings": settings, "about": about, "backup": backup_info,
              "messages/preview": message_preview}
POST_ROUTES = {"room/command": room_command, "room/adjust": room_adjust, "room/adjust/cancel": room_adjust_cancel,
               "worlds/toggle": world_toggle, "worlds/validate": world_validate,
               "worlds/save": world_save, "worlds/delete": world_delete, "features/set": feature_set,
               "settings/set": settings_set, "settings/message": settings_message, "outbox/action": outbox_action,
               "backup/import": backup_import}
