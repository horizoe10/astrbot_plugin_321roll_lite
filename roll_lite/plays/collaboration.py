"""Collaboration (playCollaboration): party proposals, collective events and votes.

A party proposal ('/团 全队') passes on a majority of present players and is
then resolved like a hosted action by its proposer without using up the
waiting player's turn.  Collective events come from the engine
(propose_collective_event) every few rounds or on the host's request; the
party votes on two or three directions and the winner is narrated.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .. import shared
from .. import messages
from ..commands import Caller, Reply, UserError
from ..engine.gateway import EngineCallFailed
from ..storage import dumps, loads, new_id, now
from . import hosted

if TYPE_CHECKING:
    from ..app import LiteApp

VOTE_SECONDS = 120
DEFAULT_EVENT_EVERY = 3
YES_NO = [{"key": "A", "label": "同意"}, {"key": "B", "label": "反对"}]
SNAPSHOT_SCHEMA = "321roll-collective-event-snapshot/1.0.0"


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def open_vote(c: sqlite3.Connection, room_id: str) -> sqlite3.Row | None:
    return c.execute("SELECT * FROM votes WHERE room_id=? AND state='open' ORDER BY created_at DESC LIMIT 1", (room_id,)).fetchone()


def vote_text(vote: sqlite3.Row, voters: int) -> Any:
    data = loads(vote["data_json"], {})
    span = (datetime.fromisoformat(vote["deadline_at"]) - datetime.fromisoformat(vote["created_at"])).total_seconds()
    return messages.vote_card(vote["title"], data.get("premise", ""), loads(vote["options_json"], []),
                              len(loads(vote["ballots_json"], {})), voters, max(1, round(span / 60)),
                              kind="突发" if vote["kind"] == "event" else "全队提议")


def vote_seconds(room: sqlite3.Row) -> int:
    """This table's vote window; without a table setting the default two minutes."""
    return int(hosted.hosted_data(room).get("vote_seconds") or VOTE_SECONDS)


def _create_vote(c: sqlite3.Connection, room_id: str, kind: str, title: str, options: list[dict[str, Any]],
                 data: dict[str, Any]) -> sqlite3.Row:
    vote_id = new_id("vote")
    room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    created = datetime.now(UTC)
    deadline = (created + timedelta(seconds=vote_seconds(room))).isoformat(timespec="seconds")
    c.execute("INSERT INTO votes(id,room_id,kind,title,options_json,state,deadline_at,data_json,created_at,updated_at) "
              "VALUES(?,?,?,?,?,'open',?,?,?,?)", (vote_id, room_id, kind, title, dumps(options), deadline, dumps(data),
                                                   created.isoformat(timespec="seconds"), now()))
    return c.execute("SELECT * FROM votes WHERE id=?", (vote_id,)).fetchone()


def tally(vote: sqlite3.Row, host_user: str, voters: dict[str, str]) -> str:
    """Winning option key: plurality; a tie goes to the host's ballot, else the earliest option."""
    options = [o["key"] for o in loads(vote["options_json"], [])]
    ballots = loads(vote["ballots_json"], {})
    counts = {key: sum(1 for choice in ballots.values() if choice == key) for key in options}
    best = max(counts.values()) if counts else 0
    tied = [key for key in options if counts[key] == best]
    if len(tied) > 1:
        host_actor = next((actor for actor, user in voters.items() if user == host_user), None)
        if host_actor and ballots.get(host_actor) in tied:
            return ballots[host_actor]
    return tied[0]


async def close_vote(app: "LiteApp", vote_id: str) -> Reply:
    """Close a vote and act on its result (narration for passed proposals and events)."""
    with app.store.tx() as c:
        vote = c.execute("SELECT * FROM votes WHERE id=?", (vote_id,)).fetchone()
        if vote is None or vote["state"] != "open":
            return Reply()
        room = c.execute("SELECT * FROM rooms WHERE id=?", (vote["room_id"],)).fetchone()
        voters = {a["id"]: a["user_id"] for a in hosted.eligible_actors(c, room["id"])}
        winner = tally(vote, room["host_user_id"], voters)
        ballots = loads(vote["ballots_json"], {})
        option = next(o for o in loads(vote["options_json"], []) if o["key"] == winner)
        c.execute("UPDATE votes SET state='closed',result_json=?,updated_at=? WHERE id=?",
                  (dumps({"winner": winner, "ballots": len(ballots)}), now(), vote_id))
        app.store.add_event(c, room["id"], "vote", f"表决「{vote['title']}」结果：{option['label']}")
    data = loads(vote["data_json"], {})
    passed = vote["kind"] != "proposal" or winner == "A"
    counts = [(o["label"], sum(1 for choice in ballots.values() if choice == o["key"])) for o in loads(vote["options_json"], [])]
    reply = Reply().say(messages.vote_result(vote["title"], option["label"], counts, "" if passed else "全队提议未通过"))
    if room["state"] != "running":
        return reply
    if vote["kind"] == "proposal":
        if winner != "A":
            return reply
        action, actor_id, intent = f"全队行动：{data['action']}", data["actor_id"], None
    else:
        action = f"队伍共同决定：{option['label']}——{option.get('description', '')}"
        actor_id, intent = data["leader_actor_id"], {"kind": "narrative", "attribute_ref": "", "difficulty": "",
                                                     "failure_cost": "", "reason": "队伍表决结果", "clarification": "",
                                                     "risk_response": ""}
    return reply.extend(await run_party_action(app, room["id"], actor_id, action, intent))


async def run_party_action(app: "LiteApp", room_id: str, actor_id: str, action: str, intent: dict[str, Any] | None) -> Reply:
    """Resolve a party action through the hosted flow, then hand the turn back to the waiting player."""
    with app.store.tx() as c:
        current = hosted.current_turn(c, room_id)
        if current is not None and current["state"] != "awaiting":
            raise UserError("当前行动还在结算，稍后再执行全队行动。")
        resume = current["actor_id"] if current is not None else actor_id
        turn_id = new_id("turn")
        c.execute("INSERT INTO turns(id,room_id,round,actor_id,state,choices_json,data_json,created_at,updated_at) "
                  "VALUES(?,?,?,?,'awaiting','[]',?,?,?)",
                  (turn_id, room_id, current["round"] if current is not None else 1, actor_id,
                   dumps({"resume_actor": resume, "party": True}), now(), now()))
    try:
        return await hosted.resolve(app, room_id, turn_id, action, intent)
    except UserError:
        with app.store.tx() as c:
            c.execute("UPDATE turns SET state='superseded' WHERE id=?", (turn_id,))
        raise


def _snapshot(c: sqlite3.Connection, room: sqlite3.Row, leader: sqlite3.Row, party: list[sqlite3.Row], generation: int) -> dict[str, Any]:
    scene = loads(room["scene_json"], {})
    facts = [r["text"] for r in c.execute("SELECT text FROM facts WHERE room_id=? AND kind='world_fact' ORDER BY created_at DESC LIMIT 24",
                                          (room["id"],))]
    npcs = [{"name": r["name"], "description": r["description"][:300]}
            for r in c.execute("SELECT name,description FROM npcs WHERE room_id=? ORDER BY updated_at DESC LIMIT 16", (room["id"],))]
    recent = [r["text"][:2000] for r in c.execute("SELECT text FROM events WHERE room_id=? AND kind='narration' ORDER BY id DESC LIMIT 6",
                                                  (room["id"],))]
    context = {"schema": SNAPSHOT_SCHEMA, "room_ref": room["id"], "event_ref": new_id("event"), "generation": generation,
               "source_receipt_ref": f"round.{generation}", "rule_source": {"world": room["world_id"]},
               "cadence": {"kind": "rounds"}, "scene": {"title": scene.get("title", ""), "description": scene.get("description", "")[:1000]},
               "goal": room["goal"] or "继续当前的冒险", "leader": {"display_name": shared.actor_label(leader), "unit": "队伍"},
               "party": [{"display_name": shared.actor_label(a)} for a in party], "roster_digest": _digest(sorted(a["id"] for a in party)),
               "npcs": npcs, "public_facts": list(reversed(facts)), "recent_public": list(reversed(recent))}
    context["snapshot_sha256"] = _digest(context)
    return context


async def start_event(app: "LiteApp", room_id: str) -> Reply:
    with app.store.read() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        if room["state"] != "running" or open_vote(c, room_id) is not None:
            return Reply()
        party = hosted.eligible_actors(c, room_id)
        if len(party) < 2:
            raise UserError("集体事件至少需要 2 名在场玩家。")
        turn = hosted.current_turn(c, room_id)
        leader = next((a for a in party if turn is not None and a["id"] == turn["actor_id"]), party[0])
        generation = c.execute("SELECT COUNT(*) FROM votes WHERE room_id=? AND kind='event'", (room_id,)).fetchone()[0] + 1
        context = _snapshot(c, room, leader, party, generation)
    proposal = await app.engine.call("propose_collective_event", {"context": context}, room_id=room_id, umo=room["umo"])
    options = [{"key": "ABC"[i], "label": d["label"], "description": d["description"], "risk": d["risk"], "cost": d["cost"]}
               for i, d in enumerate(proposal["directions"])]
    with app.store.tx() as c:
        if open_vote(c, room_id) is not None:
            return Reply()
        vote = _create_vote(c, room_id, "event", proposal["title"], options,
                            {"premise": proposal["premise"], "leader_actor_id": leader["id"]})
        voters = len(hosted.eligible_actors(c, room_id))
        app.store.add_event(c, room_id, "vote", f"突发事件「{proposal['title']}」：{proposal['premise']}")
    return Reply().say(vote_text(vote, voters))


async def after_round(app: "LiteApp", room_id: str, round_number: int) -> Reply:
    """Called by hosted turns when a new round starts; may schedule a collective event."""
    with app.store.read() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        every = app.store.get_setting(c, "global", "collective.every", DEFAULT_EVENT_EVERY)
    if not every or round_number <= 1 or (round_number - 1) % int(every) != 0 \
            or not app.features.enabled(room["umo"], "playCollaboration"):
        return Reply()

    async def run() -> None:
        try:
            reply = await start_event(app, room_id)
        except (EngineCallFailed, UserError):
            return
        if reply.messages:
            await app.notifier.send(room["umo"], reply.messages)

    app.spawn(run(), name=f"321roll-event-{room_id}")
    return Reply()


# ---------------------------------------------------------------- commands
async def propose(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "running")
    shared.require_play(app, caller, "playCollaboration")
    actor = shared.require_actor(app, caller, room)
    text = args.strip()
    if not 2 <= len(text) <= 300:
        raise UserError("写法：/团 全队 <全队一起做的事>")
    with app.store.tx() as c:
        if open_vote(c, room["id"]) is not None:
            raise UserError("已有进行中的表决，先投完它。")
        party = hosted.eligible_actors(c, room["id"])
        vote = _create_vote(c, room["id"], "proposal", f"{shared.actor_label(actor)} 提议：{text}", YES_NO,
                            {"action": text, "actor_id": actor["id"]})
        if len(party) <= 1:
            c.execute("UPDATE votes SET ballots_json=? WHERE id=?", (dumps({actor["id"]: "A"}), vote["id"]))
    if len(party) <= 1:
        return await close_vote(app, vote["id"])
    return await ballot(app, caller, "A", announce=vote_text(vote, len(party)))


async def ballot(app: "LiteApp", caller: Caller, args: str, announce: Any = None) -> Reply:
    room = shared.require_room(app, caller, "running")
    actor = shared.require_actor(app, caller, room)
    choice = args.strip().upper()[:1].replace("Ａ", "A").replace("Ｂ", "B").replace("Ｃ", "C")
    choice = {"同": "A", "赞": "A", "反": "B", "否": "B"}.get(args.strip()[:1], choice)
    with app.store.tx() as c:
        vote = open_vote(c, room["id"])
        if vote is None:
            raise UserError("现在没有进行中的表决。")
        if choice not in {o["key"] for o in loads(vote["options_json"], [])}:
            raise UserError("请投给列出的选项之一，例如 /团 投 A。")
        ballots = loads(vote["ballots_json"], {})
        ballots[actor["id"]] = choice
        c.execute("UPDATE votes SET ballots_json=?,updated_at=? WHERE id=?", (dumps(ballots), now(), vote["id"]))
        voters = {a["id"] for a in hosted.eligible_actors(c, room["id"])}
    reply = Reply().say(announce) if announce else Reply().say(f"{shared.actor_label(actor)} 已投票（{len(ballots)}/{len(voters)}）。")
    if voters <= set(ballots):
        reply.extend(await close_vote(app, vote["id"]))
    return reply


async def show_vote(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller)
    with app.store.read() as c:
        vote = open_vote(c, room["id"])
        voters = len(hosted.eligible_actors(c, room["id"]))
    return Reply().say(vote_text(vote, voters) if vote is not None else "现在没有进行中的表决。")


async def host_event(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "running")
    shared.require_host(app, caller, room)
    shared.require_play(app, caller, "playCollaboration")
    with app.store.read() as c:
        if open_vote(c, room["id"]) is not None:
            raise UserError("已有进行中的表决。")
    await caller.send("正在生成集体事件……")
    try:
        reply = await start_event(app, room["id"])
    except EngineCallFailed as exc:
        raise UserError("集体事件生成失败：" + exc.user_message) from exc
    return reply if reply.messages else Reply().say("现在不能发起集体事件。")


async def host_close_vote(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "running", "paused")
    shared.require_host(app, caller, room)
    with app.store.read() as c:
        vote = open_vote(c, room["id"])
    if vote is None:
        raise UserError("现在没有进行中的表决。")
    return await close_vote(app, vote["id"])


async def host_event_every(app: "LiteApp", caller: Caller, args: str) -> Reply:
    if not caller.is_admin:
        raise UserError("只有管理员可以修改集体事件频率。")
    if not args.strip().isdigit() or not 0 <= int(args) <= 20:
        raise UserError("写法：/团 主持 事件频率 <0-20>（每多少轮一次，0 为关闭）")
    with app.store.tx() as c:
        app.store.set_setting(c, "global", "collective.every", int(args))
    return Reply().say(messages.notice("已关闭自动集体事件" if int(args) == 0 else f"每 {int(args)} 轮触发一次集体事件", hint="主持人随时可以发送 /团 主持 集体事件 手动发起"))


async def host_vote_time(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "lobby", "running", "paused")
    shared.require_host(app, caller, room)
    text = args.strip().removesuffix("分钟").strip()
    usage = "发送 /团 主持 表决时限 分钟数（1–30），默认 恢复 2 分钟"
    if not text:
        own = hosted.hosted_data(room).get("vote_seconds") is not None
        return Reply().say(messages.notice(f"表决时限：{vote_seconds(room) // 60} 分钟", ("本桌单独设置" if own else "默认设置")
                                           + "。全员投完会立即结算，到时未投的人不计票。", usage))
    if text in ("默认", "全局"):
        value = None
    elif text.isdigit() and 1 <= int(text) <= 30:
        value = int(text) * 60
    else:
        raise UserError("写法：/团 主持 表决时限 分钟数（1–30），或 默认")
    with app.store.tx() as c:
        hosted.set_hosted_data(c, room["id"], vote_seconds=value)
        app.store.add_event(c, room["id"], "system", f"{caller.user_name} 把表决时限改为 {(value or VOTE_SECONDS) // 60} 分钟")
    return Reply().say(messages.notice(f"表决时限改为 {(value or VOTE_SECONDS) // 60} 分钟", "从下一次表决开始生效，进行中的表决不变。"))


async def on_tick(*, app: "LiteApp") -> Reply:
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    with app.store.read() as c:
        due = c.execute("SELECT v.id,v.room_id,r.umo FROM votes v JOIN rooms r ON r.id=v.room_id WHERE v.state='open' "
                        "AND r.state='running' AND v.deadline_at<=?", (stamp,)).fetchall()
    for row in due:
        if app.lock(row["room_id"]).locked():
            continue

        async def run(vote_id: str = row["id"], umo: str = row["umo"]) -> None:
            try:
                reply = await close_vote(app, vote_id)
            except UserError as exc:
                reply = Reply().say(exc.message)
            if reply.messages:
                await app.notifier.send(umo, reply.messages)

        app.spawn(run(), name=f"321roll-vote-{row['id']}")
    return Reply()


async def on_status(room_id: str, *, app: "LiteApp") -> Reply:
    with app.store.read() as c:
        vote = open_vote(c, room_id)
    return Reply().say(f"表决中：{vote['title']}") if vote is not None else Reply()


async def on_story_completed(room_id: str, ending: Any, *, app: "LiteApp") -> Reply:
    with app.store.tx() as c:
        c.execute("UPDATE votes SET state='cancelled',updated_at=? WHERE room_id=? AND state='open'", (now(), room_id))
    return Reply()


def install(app: "LiteApp") -> None:
    r = app.router
    r.register(("全队", "全队行动"), propose, summary="提议全队一起行动", usage="/团 全队 <行动>", topic="行动", private="room")
    r.register(("投", "投票"), ballot, summary="参与表决", usage="/团 投 A", topic="行动", private="room")
    r.register("表决", show_vote, summary="查看进行中的表决", topic="行动", private="self")
    r.register("主持 集体事件", host_event, summary="发起一次集体事件", topic="主持")
    r.register("主持 结束表决", host_close_vote, summary="立即结算表决", topic="主持")
    r.register("主持 事件频率", host_event_every, summary="自动集体事件间隔（管理员）", usage="/团 主持 事件频率 <轮数>", topic="主持")
    r.register("主持 表决时限", host_vote_time, summary="调整本桌表决的截止时间", usage="/团 主持 表决时限 [分钟|默认]", topic="主持")

    def bind(fn):
        async def handler(**payload):
            return await fn(app=app, **payload)
        return handler

    app.hooks.on("tick", bind(on_tick))
    app.hooks.on("status_lines", bind(on_status))
    app.hooks.on("story_completed", bind(on_story_completed))
    app.hooks.on("room_closed", bind(lambda room_id, app: on_story_completed(room_id, None, app=app)))
