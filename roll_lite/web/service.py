"""WebUI backend as plain async functions: (app, payload, username) -> JSON-ready dict.

web/api.py registers them with AstrBot.  Room operations run the same '/团' commands as an administrator so
the group sees the same receipts and the same rules apply.
FILE_ROUTES return (filename, content type, bytes) for downloads; UPLOAD_ROUTES
take the uploaded bytes and file name.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .. import adjust, loadout, messages, narration, people, personas, shared, tavern
from ..cards import cover
from ..commands import Caller, UserError, strip_command
from ..delivery import load_prefs, save_prefs
from ..engine.bridge import ModelOutputInvalid, ModelUnavailable
from ..engine.gateway import ENGINE_VERSION
from ..features import BY_KEY, group_scope
from ..fun import relay
from ..fun import soup
from .. import quota
from .. import story_export
from ..render import MARKDOWN_PLATFORMS, PLAIN, inline, render
from ..rooms import lifecycle
from ..storage import dumps, loads, now
from ..version import DATABASE_SCHEMA, PLUGIN_VERSION, WORLD_FORMAT
from ..worlds import market
from ..worlds import tavern_import
from ..worlds.catalog import COVER_TONES, WorldInvalid, validate_presentation, validate_world
from ..worlds.package import MAX_PACKAGE, edition_of, label
from . import insight
from .preview import message_preview

if TYPE_CHECKING:
    from ..app import LiteApp

ROOM_COMMANDS = ("暂停", "恢复", "开演", "主持 全员准备", "完结", "关闭", "主持 跳过", "主持 直述", "主持 指引", "主持 推进", "主持 重试", "主持 换幕",
                 "主持 选项", "主持 集体事件", "主持 结束表决", "主持 限时", "存档", "读档", "人数",
                 "主持 交棒", "主持 移出", "主持 放行", "主持 暂离", "主持 返回", "主持 入座", "主持 退回", "主持 顺序",
                 "主持 轮到", "主持 回退", "主持 篇幅", "主持 文风", "主持 即兴", "主持 检定", "主持 审稿", "主持 发布", "主持 重写",
                 "主持 表决时限", "主持 人设")
BACKUP_TABLES = ("settings", "worlds", "rooms", "actors", "records", "turns", "events", "facts", "npcs", "votes", "saves",
                 "personas", "outbox", "audit")


class WebError(Exception):
    pass


# Export file: one JSON holding both documents, so a world can be saved and imported again as is.
BUNDLE_FORMAT = "321roll-lite.world-bundle/1"


def _origin(entry: Any) -> dict[str, Any] | None:
    """What the WebUI shows about a market install."""
    o = entry.origin
    if not o:
        return None
    return {"source": o.get("source"), "file": o.get("file"), "revision": o.get("revision"), "edition": edition_of(o.get("edition")),
            "label": label(o.get("edition"), o.get("revision")), "sha256": o.get("sha256"),
            "size": o.get("size"), "installed_at": o.get("installed_at"), "images": len(set((o.get("images") or {}).values())),
            "banner": bool(o.get("banner"))}


def _label(entry: Any) -> str:
    """The version shown for a world: its tier (market package or a custom world's own), else Pro (P)."""
    return label(entry.edition, entry.pack.get("revision", 1))


def _edition(entry: Any) -> str:
    return edition_of(entry.edition)


def _scenes(entry: Any) -> list[dict[str, str]]:
    """Installed scene images in story order with readable labels, for the world gallery."""
    found = (entry.origin or {}).get("scenes") or {}
    pres = entry.presentation
    labels = [("cover", "封面")]
    labels += [(f"act:{a['number']}", f"第 {a['number']} 幕 · {a['title']}") for a in pres.get("acts", [])]
    labels += [(f"place:{p['entry']}", p["name"]) for p in pres.get("places", [])]
    labels += [(f"ending:{e['id']}", f"结局 · {e['name']}") for e in pres.get("endings", [])]
    return [{"key": key, "label": label} for key, label in labels if key in found]


async def _market(call: Any) -> Any:
    try:
        return await call
    except market.MarketError as exc:
        raise WebError(str(exc)) from exc


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
            "act": room["act"], "acts_total": lifecycle.acts_total(room) or len(lifecycle.act_list(room)),
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
    "funDaily": ("每人每天一次 d20 与两宜两忌，附本群今日榜；不影响检定。", "/团 一掷　/团 一掷 全群"),
    "funDice": ("不开团也能掷的自由骰，私聊里是暗骰；两人掷 d20 比大小。", "/团 掷 2d6+1　/团 对决 @某人"),
    "funReport": ("每人每幕给同伴喝彩一次，换幕与终章公布最佳；随时生成战报卡。", "/团 喝彩 林晓　/团 战报"),
    "funSchedule": ("主持人给出几个时间，大家勾选，定档后开始前 30 分钟提醒。", "/团 约团 周六 20:00｜周日 14:00"),
    "funRelay": ("群友一人一句写故事，满 8 句由 AI 收尾，每群每天有次数上限。", "/团 接龙 第一句"),
    "funLuck": ("统计每人在本群掷出的每一颗 d20，看平均点数和大成功大失败，附本月骰运榜。", "/团 骰运　/团 骰运 榜"),
    "funQuotes": ("收藏跑团正文里的好句子，随机重温，按收藏人数排出金句榜。", "/团 金句 几个字　/团 金句 +编号　/团 金句 榜"),
    "funSoup": ("AI 出一道海龟汤，全群问是非题、猜汤底；每群每天有碗数上限。", "/团 海龟汤　/团 问 …　/团 猜 …"),
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
        hours = insight.hourly(c, moment)
        speed = insight.latency(c.execute("SELECT started_at,completed_at FROM model_calls WHERE started_at>=? AND status='ok'",
                                          (since,)).fetchall())
        outbox = c.execute("SELECT COUNT(*) FROM outbox WHERE state='pending'").fetchone()[0]
        events = [dict(r) for r in c.execute(
            "SELECT e.created_at,e.kind,e.text,r.title,r.id AS room_id FROM events e JOIN rooms r ON r.id=e.room_id "
            "WHERE e.kind IN ('narration','action','play','vote','check','system') ORDER BY e.id DESC LIMIT 40")]
        seated = c.execute("SELECT COUNT(*) FROM actors a JOIN rooms r ON r.id=a.room_id "
                           "WHERE r.state IN ('lobby','running','paused') AND a.presence<>'left'").fetchone()[0]
        rounds_today = c.execute("SELECT COUNT(*) FROM turns WHERE state IN ('done','timed_out') AND updated_at>=?", (since,)).fetchone()[0]
        plays = {r[0]: r[1] for r in c.execute("SELECT play,COUNT(*) FROM records WHERE created_at>=? GROUP BY play", (month,))}
        plays["playActions"] = c.execute("SELECT COUNT(*) FROM turns WHERE state IN ('done','timed_out') AND created_at>=?", (month,)).fetchone()[0]
        plays["playCollaboration"] = c.execute("SELECT COUNT(*) FROM votes WHERE created_at>=?", (month,)).fetchone()[0]
        by_world = {r[0]: (r[1], r[2], r[3]) for r in c.execute(
            "SELECT world_id,COUNT(*),SUM(created_at>=?),MAX(created_at) FROM rooms GROUP BY world_id", (month,))}
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
            "model_24h": {"calls": calls[0], "input_tokens": calls[1], "output_tokens": calls[2], "failures": calls[3],
                          "latency": speed},
            "model_week": series, "model_hours": hours,
            "outbox_pending": outbox, "worlds": {"total": len(worlds), "enabled": sum(w.enabled for w in worlds)},
            "world_usage": sorted(({"id": wid, "title": entries[wid].title if wid in entries else wid, "rooms": n[0],
                                    "month": n[1] or 0, "last_at": n[2],
                                    "cover": cover(wid, entries[wid].title if wid in entries else wid,
                                                   entries[wid].presentation if wid in entries else None)}
                                   for wid, n in by_world.items()), key=lambda x: -x["rooms"])[:6],
            "custom_worlds": sum(w.source == "custom" for w in worlds),
            "seated": seated, "rounds_24h": rounds_today, "feature": feature, "attention": attention,
            "plays": sorted(({"key": k, "label": BY_KEY[k].label, "count": n} for k, n in plays.items() if k in BY_KEY and n),
                            key=lambda x: -x["count"]),
            "plays_enabled": sum(1 for p in app.features.table() if p["status"] == "active" and p["effective"] and p["kind"] == "story"),
            "plays_total": sum(1 for p in app.features.table() if p["status"] == "active" and p["kind"] == "story"),
            "message": {**prefs.public(), "blocked": list(blocked)},
            "ready": {"admins": len(app.config.admin_ids), "whitelist": app.config.group_whitelist_enabled,
                      "provider": (app.config.chat_provider_id or "跟随会话")
                      + (" · 备用 " + app.config.fallback_provider_id if app.config.fallback_provider_id else ""),
                      "turn_timeout": app.config.turn_timeout_seconds,
                      "collective_every": every, "allowed_groups": len(app.config.allowed_groups),
                      "round_limit": quota.daily_limit(app)},
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
            "traits": [t["title"] for t in loads(actor["traits_json"], [])],
            "persona": personas.attached(actor)}


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
        records = [{"id": r["id"], "seq": r["seq"], "kind": r["kind"], "kind_label": custom.KIND_LABELS.get(r["kind"], r["kind"]), "state": r["state"],
                    "state_label": custom.STATE_LABELS.get(r["state"], r["state"]), "line": inline(custom.record_line(r), PLAIN),
                    "document": loads(r["document_json"]), "updated_at": r["updated_at"],
                    "steps": [inline(s, PLAIN) for s in custom.record_steps(r)]}
                   for r in c.execute("SELECT * FROM records WHERE room_id=? AND kind<>'calendar' ORDER BY seq DESC", (row["id"],))]
        met = people.people(c, row["id"])
        history, per_act = insight.timeline(c, row, turn["round"] if turn is not None else None)
        events = history[::-1][:120]
        stats = insight.room_stats(c, row, per_act)
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
    acts = lifecycle.act_list(row)
    hosting = hosted.hosted_data(row)
    table = shared.table_data(row)
    draft = loads(turn["narrative_json"], {}) if turn is not None and turn["state"] == "review" else None
    return {**summary, "scene": scene, "goal": row["goal"], "act_heading": lifecycle.act_heading(row),
            "acts": [{"number": a["number"], "title": a["title"]} for a in acts], "clock": lifecycle.clock_text(row),
            "host_user_id": row["host_user_id"], "directive": hosted.hosted_data(row).get("directive", ""),
            "actors": actors, "records": records, "events": events, "facts": facts, "npcs": npcs, "saves": saves,
            "stats": stats,
            "usage": {"calls": usage[0], "tokens": usage[1]}, "turn_timeout_seconds": hosted.turn_seconds(app, row),
            "turn_timeout_own": hosted.hosted_data(row).get("turn_seconds") is not None,
            "settings": {"review": bool(hosting.get("review")),
                         "narration": narration.room_view(row), "world_style": shared.world(row)["pack"].get("style", ""),
                         "vote_minutes": collaboration.vote_seconds(row) // 60, "seating_locked": bool(table.get("seating_locked")),
                         "removed": [e["name"] for e in table.get("removed", [])],
                         "handover": (table.get("handover") or {}).get("name", ""), "rewinds": rewinds,
                         "personas_off": bool(table.get("personas_off"))},
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
            "attribute_ranges": [{"name": a["name"], "min": a.get("min", 1), "max": a.get("max", 20)} for a in pack["attributes"]],
            "play_groups": [{"play": key, "label": label, "kinds": list(kinds)} for key, label, kinds in PLAY_GROUPS],
            "adjustments": [{**a, "lines": [adjust.describe(row, ch, names) for ch in a["changes"]]} for a in reversed(adjust.history(row))],
            "adjust_options": {"resources": [{"id": r["id"], "name": r["name"]} for r in pack["resources"]],
                               "items": [{"id": i["id"], "name": i["name"]} for i in pack["items"]],
                               "skills": [{"id": s["id"], "name": s["name"]} for s in pack["skills"]],
                               "standing": list(adjust.STANDING)},
            "endings": shared.world(row).get("presentation", {}).get("endings") or []}


async def worlds(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    month = (datetime.now(UTC) - timedelta(days=30)).isoformat(timespec="seconds")
    with app.store.read() as c:
        played = {r[0]: {"rooms": r[1], "month": r[2] or 0, "last_at": r[3]} for r in c.execute(
            "SELECT world_id,COUNT(*),SUM(created_at>=?),MAX(created_at) FROM rooms GROUP BY world_id", (month,))}
    result = []
    for entry in lifecycle.catalog(app).entries(include_disabled=True):
        pack = entry.pack
        result.append({"id": entry.id, "title": entry.title, "source": entry.source, "enabled": entry.enabled,
                       "worldview": pack["worldview"], "style": pack.get("style", ""),
                       "played": played.get(entry.id, {"rooms": 0, "month": 0, "last_at": None}),
                       "narration": narration.world_defaults(app, entry),
                       "cover": cover(entry.id, entry.title, entry.presentation), "revision": pack.get("revision", 1),
                       "label": _label(entry), "edition": _edition(entry),
                       "market": _origin(entry), "art": bool(entry.origin and entry.origin.get("banner")),
                       "seed": pack.get("seed", ""),
                       "attributes": [a["name"] for a in pack["attributes"]], "resources": [r["name"] for r in pack["resources"]],
                       "archetypes": [a["name"] for a in pack["archetypes"]], "entries": len(pack["entries"]),
                       "acts": [a["title"] for a in entry.presentation.get("acts", [])],
                       "endings": [e["name"] for e in entry.presentation.get("endings", [])],
                       "skills": len(pack["skills"]), "items": len(pack["items"]),
                       "public_entries": sum(1 for e in pack["entries"] if e.get("public")),
                       "players": f"{pack['rules']['recommendedMin']}–{pack['rules']['recommendedMax']}"})
    return {"worlds": result, "format": WORLD_FORMAT}


async def world(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    entry = lifecycle.catalog(app).get(str(payload.get("id") or ""))
    if entry is None:
        raise WebError("世界不存在")
    builtin = lifecycle.catalog(app).builtin_revision(entry.id)
    return {"id": entry.id, "source": entry.source, "enabled": entry.enabled, "pack": entry.pack,
            "presentation": entry.presentation, "cover": cover(entry.id, entry.title, entry.presentation),
            "bundle_format": BUNDLE_FORMAT, "tones": list(COVER_TONES), "market": _origin(entry),
            "art": bool(entry.origin and entry.origin.get("banner")), "scenes": _scenes(entry), "label": _label(entry),
            "edition": _edition(entry),
            "builtin_revision": builtin, "builtin_label": label(None, builtin) if builtin is not None else None,
            "narration": narration.world_defaults(app, entry)}


async def world_image(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    entry = lifecycle.catalog(app).get(str(payload.get("id") or ""))
    try:
        return market.image(app, entry, str(payload.get("key") or "cover"))
    except market.MarketError as exc:
        raise WebError(str(exc)) from exc


async def market_view(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    data = await market.listing(app, refresh=str(payload.get("refresh") or "") in ("1", "true"))
    data["max_package_mb"] = MAX_PACKAGE // (1024 * 1024)
    return data


async def features(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    umo = str(payload.get("umo") or "") or None
    month = (datetime.now(UTC) - timedelta(days=30)).isoformat(timespec="seconds")
    with app.store.read() as c:
        groups = [{"umo": r["umo"], "group_id": r["group_id"], "title": r["title"]} for r in c.execute(
            "SELECT umo,group_id,title FROM rooms WHERE id IN (SELECT MAX(id) FROM rooms GROUP BY umo) ORDER BY updated_at DESC")]
        usage = {r[0]: r[1] for r in c.execute("SELECT play,COUNT(*) FROM records WHERE created_at>=? GROUP BY play", (month,))}
        usage["playActions"] = c.execute("SELECT COUNT(*) FROM turns WHERE state IN ('done','timed_out') AND created_at>=?", (month,)).fetchone()[0]
        usage["playCollaboration"] = c.execute("SELECT COUNT(*) FROM votes WHERE created_at>=?", (month,)).fetchone()[0]
        usage["funDaily"] = c.execute("SELECT COUNT(*) FROM daily_rolls WHERE rolled_at>=?", (month,)).fetchone()[0]
        usage["funReport"] = c.execute("SELECT COUNT(*) FROM cheers WHERE created_at>=?", (month,)).fetchone()[0]
        for kind, key in (("dice", "funDice"), ("duel", "funDice"), ("relay", "funRelay"), ("soup", "funSoup")):
            usage[key] = usage.get(key, 0) + c.execute("SELECT COUNT(*) FROM fun_log WHERE kind=? AND created_at>=?", (kind, month)).fetchone()[0]
        usage["funLuck"] = c.execute("SELECT COUNT(*) FROM d20_log WHERE created_at>=?", (month,)).fetchone()[0]
        usage["funQuotes"] = c.execute("SELECT COUNT(*) FROM quote_marks WHERE created_at>=?", (month,)).fetchone()[0]
    plays = [{**p, "note": PLAY_NOTES.get(p["key"], ("", ""))[0], "usage": PLAY_NOTES.get(p["key"], ("", ""))[1],
              "count": usage.get(p["key"], 0)} for p in app.features.table(umo)]
    return {"plays": plays, "groups": groups, "umo": umo, "relay_limit": relay.daily_limit(app), "relay_max": relay.MAX_LIMIT,
            "soup_limit": soup.daily_limit(app), "soup_max": soup.MAX_LIMIT}


async def usage(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    moment = datetime.now(UTC)
    fortnight = (moment - timedelta(days=14)).isoformat(timespec="seconds")
    with app.store.read() as c:
        days = [dict(r) for r in c.execute(
            "SELECT substr(started_at,1,10) AS day,COUNT(*) AS calls,SUM(input_tokens) AS input_tokens,"
            "SUM(output_tokens) AS output_tokens,SUM(status<>'ok') AS failures FROM model_calls "
            "GROUP BY day ORDER BY day DESC LIMIT 14")]
        rows = c.execute("SELECT contract,COUNT(*) AS calls,SUM(status<>'ok') AS failures FROM model_calls GROUP BY contract").fetchall()
        timed = c.execute("SELECT contract,started_at,completed_at FROM model_calls WHERE status='ok' AND started_at>=?",
                          (fortnight,)).fetchall()
        hours = insight.hourly(c, moment)
        failures = [dict(r) for r in c.execute(
            "SELECT m.started_at,m.contract,m.status,m.error,m.note,r.title FROM model_calls m LEFT JOIN rooms r ON r.id=m.room_id "
            "WHERE m.status<>'ok' ORDER BY m.id DESC LIMIT 20")]
        repaired = c.execute("SELECT COUNT(*) FROM model_calls WHERE status='ok' AND note<>''").fetchone()[0]
    def family(contract: str) -> str:
        # one row per contract family: an engine update bumps the version after the slash, the use stays the same
        return str(contract).split("/")[0]

    merged: dict[str, dict[str, Any]] = {}
    for r in rows:
        item = merged.setdefault(family(r["contract"]), {"contract": family(r["contract"]), "calls": 0, "failures": 0})
        item["calls"] += r["calls"]
        item["failures"] += r["failures"] or 0
    contracts = sorted(merged.values(), key=lambda x: -x["calls"])
    for item in contracts:
        item["latency"] = insight.latency([r for r in timed if family(r["contract"]) == item["contract"]])
    return {"days": days, "hours": hours, "contracts": contracts, "failures": failures, "repaired": repaired,
            "latency": insight.latency(timed),
            "config": {"provider": app.config.chat_provider_id or "", "fallback": app.config.fallback_provider_id,
                       "timeout": app.config.model_timeout_seconds, "attempts": app.config.model_attempts}}


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
        today = quota.rounds_by_group(c)
    cfg = app.config
    return {"config": {"admin_ids": sorted(cfg.admin_ids), "group_whitelist_enabled": cfg.group_whitelist_enabled,
                       "allowed_groups": sorted(cfg.allowed_groups), "chat_provider_id": cfg.chat_provider_id,
                       "fallback_provider_id": cfg.fallback_provider_id,
                       "model_timeout_seconds": cfg.model_timeout_seconds, "model_attempts": cfg.model_attempts,
                       "turn_timeout_seconds": cfg.turn_timeout_seconds, "default_seat_cap": cfg.default_seat_cap,
                       "max_seat_cap": cfg.max_seat_cap},
            "collective_every": every, "round_limit": quota.daily_limit(app), "round_limit_max": quota.MAX_LIMIT,
            "rounds_today": today,
            "message": load_prefs(app).public(),
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


async def world_narration(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    """This machine's narration defaults for one world: {changes: {field: step or null}}; null goes back to the package."""
    entry = lifecycle.catalog(app).get(str(payload.get("id") or ""))
    changes = payload.get("changes")
    if entry is None:
        raise WebError("世界不存在")
    if not isinstance(changes, dict) or not changes:
        raise WebError("没有要调整的设置")
    try:
        with app.store.tx() as c:
            values = narration.set_world(c, app, entry.id, changes)
            app.store.audit(c, f"webui:{username}", "web.world_narration", entry.id, {"values": values})
    except ValueError as exc:
        raise WebError(str(exc)) from exc
    return await world(app, {"id": entry.id}, username)


async def room_narration(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    """Table overrides: {changes: {improv|dialogue|length: step or null to follow the world, style: text}}."""
    from ..plays import hosted
    row = _room_row(app, str(payload.get("id") or ""))
    changes = payload.get("changes")
    if row["state"] not in ("lobby", "running", "paused"):
        raise WebError("只有未完结的团桌可以调整")
    if not isinstance(changes, dict) or not changes or not set(changes) <= {*narration.FIELDS, "style"}:
        raise WebError("没有要调整的设置")
    try:
        hosted.set_narration(app, row["id"], changes, f"后台·{username}")
    except UserError as exc:
        raise WebError(str(exc)) from exc
    with app.store.tx() as c:
        app.store.audit(c, f"webui:{username}", "web.room_narration", row["id"], {"changes": changes})
    return await room(app, {"id": row["id"]}, username)


def _parse_json(value: Any, label: str) -> Any:
    if isinstance(value, (dict, list)) or value is None:
        return value
    try:
        return json.loads(str(value)) if str(value).strip() else None
    except json.JSONDecodeError as exc:
        raise WebError(f"{label} 不是有效的 JSON：第 {exc.lineno} 行第 {exc.colno} 列") from exc


def _world_input(payload: dict[str, Any]) -> tuple[Any, Any, dict[str, str] | None]:
    """(pack, presentation, narration defaults) from separate fields or from an exported bundle file in either field.
    The editor sends the defaults as narration; a bundle file carries them in its extensions."""
    pack = _parse_json(payload.get("pack"), "世界")
    presentation = _parse_json(payload.get("presentation"), "呈现")
    bundle = _parse_json(payload.get("bundle"), "世界文件")
    given = narration.clean(payload["narration"]) if isinstance(payload.get("narration"), dict) else None
    for candidate in (bundle, pack):
        if isinstance(candidate, dict) and candidate.get("format") == BUNDLE_FORMAT:
            carried = narration.from_extensions(candidate.get("extensions"))
            return candidate.get("pack"), presentation or candidate.get("presentation"), given if given is not None else carried
    return pack, presentation, given


async def world_validate(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    pack, presentation, _ = _world_input(payload)
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
    pack, presentation, defaults = _world_input(payload)
    try:
        entry = await lifecycle.catalog(app).save_custom(pack, presentation, create=bool(payload.get("create")))
    except (WorldInvalid, ValueError) as exc:
        raise WebError(str(exc)) from exc
    with app.store.tx() as c:
        if defaults is not None:
            narration.set_world(c, app, entry.id, defaults, replace=True)
        app.store.audit(c, f"webui:{username}", "web.world_save", entry.id, {"revision": entry.pack["revision"]})
    return {"id": entry.id, "revision": entry.pack["revision"], "label": _label(entry)}


async def world_delete(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    try:
        lifecycle.catalog(app).delete_custom(str(payload.get("id") or ""))
    except WorldInvalid as exc:
        raise WebError(str(exc)) from exc
    with app.store.tx() as c:
        app.store.audit(c, f"webui:{username}", "web.world_delete", str(payload.get("id")), {})
    return await worlds(app, {}, username)


async def market_install(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    return await _market(market.install_from_index(app, str(payload.get("source") or ""), str(payload.get("id") or ""), username))


async def market_install_url(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    return await _market(market.install_url(app, payload.get("url"), payload.get("sha256"), username))


async def market_upload(app: "LiteApp", data: bytes, filename: str, username: str) -> dict[str, Any]:
    return await _market(market.install_upload(app, data, filename, username))


async def market_uninstall(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    return await _market(market.uninstall(app, str(payload.get("id") or ""), username))


async def market_settings(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    """Save only; the page then reloads the indexes so the switch itself never waits on the network."""
    try:
        return {"settings": market.save_settings(app, payload, username)}
    except market.MarketError as exc:
        raise WebError(str(exc)) from exc


async def world_package(app: "LiteApp", payload: dict[str, Any], username: str) -> tuple[str, str, bytes]:
    entry = lifecycle.catalog(app).get(str(payload.get("id") or ""))
    if entry is None:
        raise WebError("世界不存在")
    name, data = market.package_file(app, entry, cover(entry.id, entry.title, entry.presentation))
    return name, "application/zip", data


async def room_story(app: "LiteApp", payload: dict[str, Any], username: str) -> tuple[str, str, bytes]:
    room = _room_row(app, str(payload.get("id") or ""))
    with app.store.read() as c:
        name, data = story_export.export(c, room)
    return name, "text/markdown; charset=utf-8", data


async def feature_set(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    if "relay_limit" in payload:
        try:
            limit = relay.set_daily_limit(app, int(payload["relay_limit"]))
        except (TypeError, ValueError) as exc:
            raise WebError(f"接龙收尾次数要在 0–{relay.MAX_LIMIT} 之间") from exc
        with app.store.tx() as c:
            app.store.audit(c, f"webui:{username}", "web.relay_limit", "funRelay", {"limit": limit})
        return await features(app, {"umo": payload.get("umo")}, username)
    if "soup_limit" in payload:
        try:
            limit = soup.set_daily_limit(app, int(payload["soup_limit"]))
        except (TypeError, ValueError) as exc:
            raise WebError(f"海龟汤每天的碗数要在 0–{soup.MAX_LIMIT} 之间") from exc
        with app.store.tx() as c:
            app.store.audit(c, f"webui:{username}", "web.soup_limit", "funSoup", {"limit": limit})
        return await features(app, {"umo": payload.get("umo")}, username)
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
    if "collective_every" in payload:
        every = payload["collective_every"]
        if type(every) is not int or not 0 <= every <= 20:
            raise WebError("集体事件间隔为 0–20 轮")
        with app.store.tx() as c:
            app.store.set_setting(c, "global", "collective.every", every)
            app.store.audit(c, f"webui:{username}", "web.settings_set", "collective.every", {"value": every})
    if "round_limit" in payload:
        try:
            limit = quota.set_daily_limit(app, payload["round_limit"])
        except ValueError as exc:
            raise WebError(str(exc)) from None
        with app.store.tx() as c:
            app.store.audit(c, f"webui:{username}", "web.settings_set", quota.KEY, {"value": limit})
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


async def backup_file(app: "LiteApp", payload: dict[str, Any], username: str) -> tuple[str, str, bytes]:
    return "321roll-lite-backup.json", "application/json", json.dumps(export_backup(app), ensure_ascii=False).encode("utf-8")


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


# ---------------------------------------------------------------- personas (人设卡)
MAX_UPLOAD = 8 * 1024 * 1024


def _decode(value: Any) -> bytes:
    """A file the page read in the browser: base64, optionally as a data: URI."""
    raw = str(value or "")
    if raw.startswith("data:"):
        raw = raw.partition(",")[2]
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WebError("文件读取失败，请重新选择") from exc
    if not data:
        raise WebError("文件是空的")
    if len(data) > MAX_UPLOAD:
        raise WebError(f"文件超过 {MAX_UPLOAD // (1024 * 1024)}MB 上限")
    return data


def _persona_usage(c: Any) -> dict[str, list[dict[str, Any]]]:
    """Tables where each persona is seated right now: persona id -> [{room, title, actor, state, intro, off}]."""
    out: dict[str, list[dict[str, Any]]] = {}
    for row in c.execute("SELECT a.data_json,a.name,a.user_name,r.id AS room_id,r.title,r.state,r.data_json AS room_data FROM actors a "
                         "JOIN rooms r ON r.id=a.room_id WHERE r.state IN ('lobby','running','paused') AND a.presence<>'left' "
                         "AND a.data_json LIKE '%\"persona\"%'"):
        persona = loads(row["data_json"], {}).get("persona")
        if not persona:
            continue
        off = bool(loads(row["room_data"], {}).get("table", {}).get("personas_off"))
        out.setdefault(persona["id"], []).append({"room": row["room_id"], "title": row["title"], "state": row["state"],
                                                  "actor": row["name"] or row["user_name"], "intro": persona.get("intro", ""),
                                                  "off": off})
    return out


def _persona_out(row: Any, usage: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    v = personas.view(row)
    return {**v, "full": personas.full_text(v["data"]), "usage": usage.get(v["id"], [])}


async def personas_view(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    with app.store.read() as c:
        rows = c.execute("SELECT * FROM personas ORDER BY user_name, created_at").fetchall()
        usage = _persona_usage(c)
        players = [dict(r) for r in c.execute(
            "SELECT r.platform,a.user_id,MAX(a.user_name) AS user_name,MAX(a.updated_at) AS seen FROM actors a JOIN rooms r ON r.id=a.room_id "
            "WHERE a.user_id NOT LIKE 'webui:%' GROUP BY r.platform,a.user_id ORDER BY seen DESC LIMIT 200")]
    items = [_persona_out(r, usage) for r in rows]
    owners: dict[tuple[str, str], dict[str, Any]] = {}
    for p in items:
        owner = owners.setdefault((p["platform"], p["user_id"]), {"platform": p["platform"], "user_id": p["user_id"],
                                                                  "user_name": p["user_name"], "count": 0})
        owner["count"] += 1
    known = {(p["platform"], p["user_id"]) for p in players}
    players += [{"platform": o["platform"], "user_id": o["user_id"], "user_name": o["user_name"], "seen": None}
                for key, o in owners.items() if key not in known]
    return {"personas": items, "owners": list(owners.values()), "players": players,
            "stats": {"total": len(items), "owners": len(owners), "summarized": sum(1 for p in items if p["data"].get("summary")),
                      "long": sum(1 for p in items if p["long"]), "in_use": sum(1 for p in items if p["usage"]),
                      "imported": sum(1 for p in items if p["data"].get("source") == "card")},
            "limits": {"per_user": personas.MAX_PER_USER, "summary": personas.SUMMARY_LIMIT, "field": personas.FIELD_LIMIT,
                       "name": personas.NAME_LIMIT},
            "fields": [{"key": k, "label": label_} for k, label_ in personas.FIELDS]}


def _owner(payload: dict[str, Any]) -> tuple[str, str, str]:
    platform, user_id = str(payload.get("platform") or "").strip(), str(payload.get("user_id") or "").strip()
    if not platform or not user_id:
        raise WebError("请选择这张人设卡属于哪位玩家")
    return platform, user_id, str(payload.get("user_name") or user_id).strip()


def _one_persona(app: "LiteApp", persona_id: str) -> dict[str, Any]:
    with app.store.read() as c:
        row = personas.by_id(c, persona_id)
        if row is None:
            raise WebError("人设卡不存在，可能已被玩家删除")
        return _persona_out(row, _persona_usage(c))


async def persona_save(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    persona_id = str(payload.get("id") or "") or None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    try:
        with app.store.tx() as c:
            if persona_id:
                row = personas.by_id(c, persona_id)
                if row is None:
                    raise WebError("人设卡不存在，可能已被玩家删除")
                platform, user_id, user_name = row["platform"], row["user_id"], row["user_name"]
                old = loads(row["data_json"], {})
                data = {**old, **data, "source": old.get("source") or "webui"}
            else:
                platform, user_id, user_name = _owner(payload)
                data = {**data, "source": "webui"}
            if data.get("summary") and data.get("summary_by") not in ("ai", "manual"):
                data["summary_by"] = "manual"
            avatar = payload.get("avatar")
            persona_id = personas.store(c, platform=platform, user_id=user_id, user_name=user_name, name=str(payload.get("name") or ""),
                                        data=data, avatar=None if avatar is None else str(avatar), persona_id=persona_id)
            app.store.audit(c, f"webui:{username}", "web.persona_save", persona_id, {"name": payload.get("name")})
    except UserError as exc:
        raise WebError(exc.message) from exc
    return _one_persona(app, persona_id)


async def persona_delete(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    with app.store.tx() as c:
        row = personas.by_id(c, str(payload.get("id") or ""))
        if row is None:
            raise WebError("人设卡不存在，可能已被玩家删除")
        c.execute("DELETE FROM personas WHERE id=?", (row["id"],))
        app.store.audit(c, f"webui:{username}", "web.persona_delete", row["id"], {"name": row["name"]})
    return await personas_view(app, {}, username)


async def persona_digest(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    with app.store.read() as c:
        row = personas.by_id(c, str(payload.get("id") or ""))
    if row is None:
        raise WebError("人设卡不存在，可能已被玩家删除")
    data = loads(row["data_json"], {})
    if not personas.full_text(data):
        raise WebError("这张人设卡还是空的")
    try:
        data["summary"] = await personas.digest(app, row["name"], data)
    except (ModelUnavailable, ModelOutputInvalid) as exc:
        raise _model_error(exc) from exc
    data["summary_by"] = "ai"
    with app.store.tx() as c:
        personas.store(c, platform=row["platform"], user_id=row["user_id"], user_name=row["user_name"], name=row["name"],
                       data=data, persona_id=row["id"])
        app.store.audit(c, f"webui:{username}", "web.persona_digest", row["id"], {})
    return _one_persona(app, row["id"])


async def persona_import(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    """A SillyTavern character card (PNG or JSON) for one player; the page reads the file and sends it as base64."""
    platform, user_id, user_name = _owner(payload)
    try:
        if payload.get("text"):
            parsed = tavern.parse(_parse_json(payload["text"], "角色卡"))
        else:
            parsed = await asyncio.to_thread(tavern.read, _decode(payload.get("data")), str(payload.get("filename") or ""))
    except tavern.TavernError as exc:
        raise WebError(str(exc)) from exc
    if parsed["type"] != "card":
        raise WebError("这是一份世界书，不是角色卡。世界书请在“世界 → 新建世界 → 从酒馆导入”里做成世界卡。")
    card = parsed["data"]
    name = str(payload.get("name") or card["name"] or "未命名")
    avatar = await asyncio.to_thread(personas.avatar_uri, parsed["image"]) if parsed.get("image") else None
    try:
        with app.store.tx() as c:
            existing = personas.by_name(c, platform, user_id, name)
            persona_id = personas.store(c, platform=platform, user_id=user_id, user_name=user_name, name=name,
                                        data=personas.from_card(card), avatar=avatar,
                                        persona_id=existing["id"] if existing and payload.get("replace") else None)
            app.store.audit(c, f"webui:{username}", "web.persona_import", persona_id, {"name": name})
    except UserError as exc:
        raise WebError(exc.message) from exc
    return _one_persona(app, persona_id)


async def persona_avatar(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    persona_id = str(payload.get("id") or "")
    avatar = ""
    if payload.get("data"):
        avatar = await asyncio.to_thread(personas.avatar_uri, _decode(payload["data"]))
        if not avatar:
            raise WebError("这张图片读不出来，换一张试试")
    with app.store.tx() as c:
        if personas.by_id(c, persona_id) is None:
            raise WebError("人设卡不存在，可能已被玩家删除")
        c.execute("UPDATE personas SET avatar=?,updated_at=? WHERE id=?", (avatar, now(), persona_id))
    return _one_persona(app, persona_id)


async def persona_export(app: "LiteApp", payload: dict[str, Any], username: str) -> tuple[str, str, bytes]:
    """The persona as a SillyTavern chara_card_v2 JSON file."""
    with app.store.read() as c:
        row = personas.by_id(c, str(payload.get("id") or ""))
    if row is None:
        raise WebError("人设卡不存在，可能已被玩家删除")
    document = tavern.export_card({"name": row["name"], "data": loads(row["data_json"], {})})
    return f"{row['name']}.json", "application/json", json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")


# ---------------------------------------------------------------- SillyTavern world import (酒馆世界 -> 世界卡)
TAVERN_KINDS = (("region", "地区"), ("place", "地点"), ("faction", "势力"), ("npc", "人物"), ("goal", "目标"), ("clue", "线索"),
                ("worldview", "并入世界观"), ("guidance", "主持要点"), ("skip", "不导入"))


async def tavern_templates(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    return {"templates": tavern_import.template_summary(), "kinds": [{"key": k, "label": v} for k, v in TAVERN_KINDS],
            "limits": {"worldview": tavern_import.WORLDVIEW_LIMIT, "worldview_advised": tavern_import.WORLDVIEW_ADVISED,
                       "guidance": tavern_import.GUIDANCE_LIMIT, "entry": tavern_import.ENTRY_LIMIT,
                       "entries": tavern_import.MAX_ENTRIES, "host": tavern_import.HOST_CONTEXT_LIMIT}}


async def tavern_parse(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    try:
        if payload.get("text"):
            return tavern_import.parse_text(str(payload["text"]))
        data = _decode(payload.get("data"))
        return await asyncio.to_thread(tavern_import.parse_upload, data, str(payload.get("filename") or ""))
    except tavern.TavernError as exc:
        raise WebError(str(exc)) from exc


def _model_error(exc: Exception) -> WebError:
    if isinstance(exc, ModelUnavailable):
        return WebError(f"没有可用的模型（{exc}）。请在插件配置里选择叙事模型，或跳过 AI 手动整理")
    return WebError(f"模型的回答没能用上（{exc}），可以再试一次或手动整理")


def _entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("entries")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


async def tavern_classify(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    entries = _entries(payload)
    if not entries:
        raise WebError("没有可以整理的条目")
    try:
        return {"entries": await tavern_import.classify(app, str(payload.get("title") or ""), entries)}
    except (ModelUnavailable, ModelOutputInvalid) as exc:
        raise _model_error(exc) from exc


async def tavern_condense(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    entries = [e for e in _entries(payload) if isinstance(e.get("i"), int)]
    worldview = str(payload.get("worldview") or "")
    if not worldview.strip() and not entries:
        raise WebError("没有需要压缩的内容")
    try:
        limit = int(payload.get("limit") or tavern_import.WORLDVIEW_ADVISED)
    except (TypeError, ValueError):
        limit = tavern_import.WORLDVIEW_ADVISED
    try:
        return await tavern_import.condense(app, worldview, entries, max(500, min(limit, tavern_import.WORLDVIEW_LIMIT)))
    except (ModelUnavailable, ModelOutputInvalid) as exc:
        raise _model_error(exc) from exc


async def tavern_complete(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    try:
        return await tavern_import.complete(app, str(payload.get("title") or ""), str(payload.get("worldview") or ""),
                                            _entries(payload), str(payload.get("template") or "adventure"),
                                            bool(payload.get("want_opening", True)))
    except (ModelUnavailable, ModelOutputInvalid) as exc:
        raise _model_error(exc) from exc


async def tavern_build(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    """The world-card draft for the editor; nothing is saved until the editor saves it."""
    draft = payload.get("draft") if isinstance(payload.get("draft"), dict) else None
    if draft is None:
        raise WebError("缺少导入草稿，请从第一步重新开始")
    extras = payload.get("extras") if isinstance(payload.get("extras"), dict) else {}
    result = tavern_import.build(draft, str(payload.get("template") or "adventure"), extras)
    taken = {e.id for e in lifecycle.catalog(app).entries(include_disabled=True)}
    base, n = result["pack"]["id"], 2
    while result["pack"]["id"] in taken:
        result["pack"]["id"], n = f"{base}-{n}", n + 1
    if not result["issues"]:
        try:
            await app.engine.compile_world(validate_world(result["pack"]))
        except (WorldInvalid, ValueError) as exc:
            result["issues"].append(str(exc))
    result["cover"] = cover(result["pack"]["id"], result["pack"]["title"], result["presentation"])
    return result



GET_ROUTES = {"overview": overview, "rooms": rooms, "room": room, "worlds": worlds, "world": world, "features": features,
              "usage": usage, "outbox": outbox, "audit": audit, "settings": settings, "about": about, "backup": backup_info,
              "messages/preview": message_preview, "market": market_view, "worlds/image": world_image,
              "personas": personas_view, "worlds/tavern/templates": tavern_templates}
POST_ROUTES = {"room/command": room_command, "room/adjust": room_adjust, "room/adjust/cancel": room_adjust_cancel,
               "worlds/toggle": world_toggle, "worlds/validate": world_validate, "worlds/narration": world_narration,
               "room/narration": room_narration,
               "worlds/save": world_save, "worlds/delete": world_delete, "features/set": feature_set,
               "settings/set": settings_set, "settings/message": settings_message, "outbox/action": outbox_action,
               "backup/import": backup_import, "market/install": market_install, "market/install-url": market_install_url,
               "market/uninstall": market_uninstall, "market/settings": market_settings,
               "personas/save": persona_save, "personas/delete": persona_delete, "personas/digest": persona_digest,
               "personas/import": persona_import, "personas/avatar": persona_avatar,
               "worlds/tavern/parse": tavern_parse, "worlds/tavern/classify": tavern_classify,
               "worlds/tavern/condense": tavern_condense, "worlds/tavern/complete": tavern_complete,
               "worlds/tavern/build": tavern_build}
FILE_ROUTES = {"backup/export": backup_file, "worlds/package": world_package, "room/story": room_story,
               "personas/export": persona_export}
UPLOAD_ROUTES = {"market/upload": market_upload}
