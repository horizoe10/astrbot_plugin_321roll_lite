"""Hosted turns (playActions): opening, intent, platform dice, narration, A-D choices, timeouts.

One awaiting turn exists per running room.  Resolving a turn commits the dice
and resource changes first (turn.receipt_json), then asks the engine for the
narration; if narration fails the receipt stays and the host can retry.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .. import adjust, loadout, narration, personas, quota, shared
from .. import messages
from ..commands import Caller, Reply, UserError, split_title
from ..dice import roll_check, success_chance
from ..engine.gateway import EngineCallFailed, new_operation_ref
from ..fun import luck
from ..rooms import lifecycle
from ..storage import dumps, loads, new_id, now
from ..worlds.catalog import brief as world_brief
from . import story_recap

if TYPE_CHECKING:
    from ..app import LiteApp

LABELS = "ABCD"
DIFFICULTY_LABELS = {"easy": "简单", "standard": "标准", "hard": "困难", "exceptional": "极难"}
NARRATION_KINDS = ("narration", "action", "check", "play", "vote", "host", "chapter")


# ---------------------------------------------------------------- reading
def turn_seconds(app: "LiteApp", room: sqlite3.Row) -> int:
    """This table's turn time limit in seconds (0 = none); without a table setting the global default applies."""
    value = hosted_data(room).get("turn_seconds")
    return app.config.turn_timeout_seconds if value is None else int(value)


def limit_text(seconds: int) -> str:
    if seconds <= 0:
        return "不限时"
    return f"{seconds // 60} 分钟" if seconds % 60 == 0 else f"{seconds} 秒"


def _deadline(app: "LiteApp", room: sqlite3.Row) -> str | None:
    seconds = turn_seconds(app, room)
    return None if seconds <= 0 else (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


TURN_STATES = {"awaiting": "等待行动", "resolving": "结算中", "narration_failed": "正文待重试", "review": "正文待主持人审阅"}


def current_turn(c: sqlite3.Connection, room_id: str) -> sqlite3.Row | None:
    return c.execute("SELECT * FROM turns WHERE room_id=? AND state IN ('awaiting','resolving','narration_failed','review') "
                     "ORDER BY created_at DESC LIMIT 1", (room_id,)).fetchone()


def hosted_data(room: sqlite3.Row) -> dict[str, Any]:
    return loads(room["data_json"], {}).get("hosted", {})


def set_hosted_data(c: sqlite3.Connection, room_id: str, **values: Any) -> None:
    row = c.execute("SELECT data_json FROM rooms WHERE id=?", (room_id,)).fetchone()
    data = loads(row["data_json"], {})
    data.setdefault("hosted", {}).update(values)
    c.execute("UPDATE rooms SET data_json=? WHERE id=?", (dumps(data), room_id))


def eligible_actors(c: sqlite3.Connection, room_id: str) -> list[sqlite3.Row]:
    return [a for a in shared.present_actors(c, room_id) if a["archetype_id"]]


def next_actor(c: sqlite3.Connection, room_id: str, after: sqlite3.Row | None) -> tuple[sqlite3.Row | None, bool]:
    """The next eligible actor after 'after' in seat order; the flag tells whether the order wrapped."""
    actors = eligible_actors(c, room_id)
    if not actors:
        return None, False
    if after is None:
        return actors[0], False
    later = [a for a in actors if (a["order_index"], a["created_at"]) > (after["order_index"], after["created_at"])]
    return (later[0], False) if later else (actors[0], True)


def actor_view(room: sqlite3.Row, actor: sqlite3.Row) -> dict[str, Any]:
    pack = shared.world(room)["pack"]
    archetype = next((a for a in pack["archetypes"] if a["id"] == actor["archetype_id"]), {"name": ""})
    skills = loads(actor["skills_json"], {})
    items = loads(actor["items_json"], {})
    view = {"actor_ref": actor["id"], "name": shared.actor_label(actor), "archetype": archetype["name"],
            "attributes": loads(actor["attributes_json"], {}),
            "resources": {k: v["current"] for k, v in loads(actor["resources_json"], {}).items()},
            "skills": [s["name"] for s in pack["skills"] if s["id"] in skills],
            "items": [f"{i['name']}×{items[i['id']]['quantity']}" for i in pack["items"] if items.get(i["id"], {}).get("quantity")]}
    persona = personas.model_line(room, actor)
    if persona:
        view["persona"] = persona
    return view


def recent_events(c: sqlite3.Connection, room: sqlite3.Row) -> list[str]:
    rows = c.execute(f"SELECT text FROM events WHERE room_id=? AND kind IN ({','.join('?' * len(NARRATION_KINDS))}) "
                     "ORDER BY id DESC LIMIT 6", (room["id"], *NARRATION_KINDS)).fetchall()
    result = [row["text"][:3000] for row in reversed(rows)]
    heading = lifecycle.act_heading(room)
    if heading:
        result.append("当前幕：" + heading.replace("\n", "——"))
    when = lifecycle.clock_text(room)
    if when:
        result.append("当前时间：" + when)
    result += narration.prompt_lines(room)
    directive = hosted_data(room).get("directive")
    if directive and not narration.is_legacy_directive(directive):    # an old table's world style is read as its improv
        result.append("主持人指引（优先遵循）：" + directive)
    return result


def narrative_policy(room: sqlite3.Row) -> dict[str, Any] | None:
    """The engine's length-and-style policy, only once the table has a length."""
    return narration.policy(room, shared.world(room)["pack"].get("style") or "")


def build_context(c: sqlite3.Connection, room: sqlite3.Row, actor: sqlite3.Row, action: str,
                  receipt: dict[str, Any] | None, note: str = "") -> dict[str, Any]:
    facts = [{"fact_ref": r["fact_ref"], "kind": r["kind"], "subject_ref": r["subject_ref"], "text": r["text"],
              "source_receipt_ref": r["source_receipt_ref"]}
             for r in c.execute("SELECT * FROM facts WHERE room_id=? ORDER BY created_at", (room["id"],))]
    npcs = [{"npc_ref": r["npc_ref"], "name": r["name"], "description": r["description"], "motivation": r["motivation"]}
            for r in c.execute("SELECT * FROM npcs WHERE room_id=? ORDER BY updated_at", (room["id"],))]
    scene = loads(room["scene_json"], {})
    events = recent_events(c, room)
    if note:
        events.append("主持人审稿意见（本次重写必须遵循）：" + note[:500])
    context = {"brief": world_brief(shared.world(room), lifecycle.current_act(room)),
               "scene": {"title": scene.get("title") or "当前场景",
                                                                 "description": scene.get("description") or ""},
               "goal": room["goal"] or "", "actor": actor_view(room, actor), "npcs": npcs, "facts": facts,
               "recent_events": events, "action": action[:2000], "mechanical_receipt": receipt,
               "rules": shared.rules(room)}
    policy = narrative_policy(room)
    if policy is not None:
        context["narrative_policy"] = policy
    return context


# ---------------------------------------------------------------- choices
def make_choices(suggestions: list[str], checks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result = []
    for index, text in enumerate(suggestions[:4]):
        check = (checks or [])[index] if checks and index < len(checks) else {"kind": "narrative", "attribute_ref": "",
                                                                                "difficulty": "", "failure_cost": ""}
        result.append({"label": LABELS[index], "text": text, "check": dict(check)})
    return result


def check_label(rules: dict[str, Any], check: dict[str, Any]) -> str:
    if check.get("kind") == "check":
        attr = rules["attributes"].get(check["attribute_ref"], check["attribute_ref"])
        cost = "，失败受伤" if check.get("failure_cost") == "harm" else ""
        return f"〔{attr}·{DIFFICULTY_LABELS.get(check['difficulty'], check['difficulty'])}{cost}〕"
    if check.get("kind") == "recover":
        return "〔休整〕"
    return ""


def turn_prompt(room: sqlite3.Row, turn: sqlite3.Row, actor: sqlite3.Row) -> Any:
    rules = shared.rules(room)
    scores, base = loads(actor["attributes_json"], {}), rules["modifier"]

    def chance(check: dict[str, Any]) -> int | None:
        """The actor's odds on a check option before any preparation; the image card shows them."""
        if check.get("kind") != "check" or check.get("difficulty") not in rules["difficulties"]:
            return None
        mod = (scores.get(check.get("attribute_ref"), base["baseline"]) - base["baseline"]) // base["divisor"]
        return success_chance(mod, rules["difficulties"][check["difficulty"]])

    choices = [{"label": c["label"], "text": c["text"], "tag": messages.check_tag(rules, c["check"]), "chance": chance(c["check"])}
               for c in loads(turn["choices_json"], [])]
    minutes = None
    if turn["deadline_at"]:
        minutes = max(1, round((datetime.fromisoformat(turn["deadline_at"]) - datetime.now(UTC)).total_seconds() / 60))
    ready = [f"{e['name']} {loadout.effect_text(e)}" for e in loadout.entries(room, actor) if e["usable"]]
    return messages.turn_prompt(shared.actor_label(actor), actor["user_name"], actor["user_id"], turn["round"], choices,
                                rules.get("action_mode", "hybrid"), minutes, loadout=ready)


def status_message(room: sqlite3.Row, actor: sqlite3.Row, round_number: int, action: str, receipt: dict[str, Any],
                   announce: str = "") -> Any:
    pack = shared.world(room)["pack"]
    archetype = next((a["name"] for a in pack["archetypes"] if a["id"] == actor["archetype_id"]), "")
    changes = receipt.get("resource_changes") or {}
    after = receipt.get("resources_after") or {}
    meters = [(r["name"], after.get(r["name"], r["initial"]), r["max"], changes.get(r["name"])) for r in pack["resources"]]
    return messages.action_status(shared.actor_label(actor), archetype, round_number, action, receipt, meters, announce=announce)


def open_turn(app: "LiteApp", c: sqlite3.Connection, room: sqlite3.Row, actor: sqlite3.Row | None,
              choices: list[dict[str, Any]], round_number: int) -> sqlite3.Row | None:
    c.execute("UPDATE turns SET state='superseded',updated_at=? WHERE room_id=? AND state IN ('awaiting','narration_failed','review')",
              (now(), room["id"]))
    if actor is None:
        return None
    turn_id = new_id("turn")
    c.execute("INSERT INTO turns(id,room_id,round,actor_id,state,choices_json,deadline_at,created_at,updated_at) "
              "VALUES(?,?,?,?,'awaiting',?,?,?,?)", (turn_id, room["id"], round_number, actor["id"], dumps(choices),
                                                    _deadline(app, room), now(), now()))
    return c.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()


# ---------------------------------------------------------------- commits
def _store_story(c: sqlite3.Connection, room_id: str, proposal: dict[str, Any], receipt_ref: str) -> None:
    count = c.execute("SELECT COUNT(*) FROM facts WHERE room_id=?", (room_id,)).fetchone()[0]
    for offset, fact in enumerate(proposal.get("facts") or [], 1):
        c.execute("INSERT INTO facts(room_id,fact_ref,kind,subject_ref,text,source_receipt_ref,created_at) VALUES(?,?,?,?,?,?,?)",
                  (room_id, f"fact.{count + offset}", fact["kind"], fact["subject_ref"], fact["text"], receipt_ref, now()))
    for npc in proposal.get("npcs") or []:
        c.execute("INSERT INTO npcs(room_id,npc_ref,name,description,motivation,updated_at) VALUES(?,?,?,?,?,?) "
                  "ON CONFLICT(room_id,npc_ref) DO UPDATE SET name=excluded.name,description=excluded.description,"
                  "motivation=excluded.motivation,updated_at=excluded.updated_at",
                  (room_id, npc["npc_ref"], npc["name"], npc["description"], npc["motivation"], now()))
    progress = proposal.get("progress") or {}
    if progress.get("scene"):
        c.execute("UPDATE rooms SET scene_json=? WHERE id=?", (dumps(progress["scene"]), room_id))
    if progress.get("goal"):
        c.execute("UPDATE rooms SET goal=? WHERE id=?", (progress["goal"], room_id))


def narration_text(proposal: dict[str, Any]) -> str:
    return "\n\n".join(str(p).strip() for p in proposal.get("paragraphs") or [] if str(p).strip())


def apply_deltas(resources: dict[str, Any], deltas: dict[str, int]) -> dict[str, int]:
    """Clamp each change to the resource range; returns what actually changed."""
    applied = {}
    for ref, delta in deltas.items():
        if ref not in resources or not delta:
            continue
        slot = resources[ref]
        after = max(slot.get("min", 0), min(slot.get("max", slot["current"]), slot["current"] + delta))
        if after != slot["current"]:
            applied[ref] = after - slot["current"]
            slot["current"] = after
    return applied


def mechanics(room: sqlite3.Row, actor: sqlite3.Row, intent: dict[str, Any], prepared: list[dict[str, Any]] | None = None
              ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Platform dice and costs for one intent → (receipt, new actor loadout document).

    A preparation is spent first (its modifiers join a check); failure costs and rest effects follow.
    """
    rules = shared.rules(room)
    pack = shared.world(room)["pack"]
    doc = loadout.state(actor)
    before = {k: v["current"] for k, v in doc["resources"].items()}
    bonus = 0
    receipt: dict[str, Any] = {"receipt_ref": new_id("receipt"), "kind": intent["kind"], "actor_ref": actor["id"]}
    if prepared:
        doc, summary = loadout.plan(room, doc, prepared, attribute=intent.get("attribute_ref") if intent["kind"] == "check" else None)
        bonus = summary["modifier"]
        receipt["prepared"] = [{"name": p["name"], "modifier": p["modifier"]} for p in prepared]
    resources = doc["resources"]
    deltas: dict[str, int] = {}
    if intent["kind"] == "check":
        attr = intent["attribute_ref"]
        score = loads(actor["attributes_json"], {}).get(attr, rules["modifier"]["baseline"])
        base = (score - rules["modifier"]["baseline"]) // rules["modifier"]["divisor"]
        mod = base + bonus
        dc = rules["difficulties"][intent["difficulty"]]
        roll = roll_check(mod, dc)
        receipt.update(attribute_ref=attr, attribute=rules["attributes"][attr], difficulty=intent["difficulty"], dc=dc,
                       face=roll.face, modifier=mod, attribute_modifier=base, total=roll.total,
                       outcome="critical" if roll.critical else "fumble" if roll.fumble else "success" if roll.success else "failure",
                       success=roll.success, failure_cost=intent.get("failure_cost") or "setback")
        if not roll.success and receipt["failure_cost"] == "harm":
            deltas = dict(rules["failure_costs"].get("harm") or {})
    elif intent["kind"] == "recover":
        rest = rules.get("recovery", {}).get("rest", {})
        deltas = {**rest.get("cost", {})}
        for ref, value in rest.get("effect", {}).items():
            deltas[ref] = deltas.get(ref, 0) + value
    apply_deltas(resources, deltas)
    applied = {k: v["current"] - before[k] for k, v in resources.items() if k in before and v["current"] != before[k]}
    names = {r["id"]: r["name"] for r in pack["resources"]}
    receipt["resource_changes"] = {names.get(k, k): v for k, v in applied.items()}
    receipt["resources_after"] = {names.get(k, k): v["current"] for k, v in resources.items()}
    receipt["exhausted"] = [names.get(k, k) for k, v in resources.items() if v["current"] <= v.get("min", 0) and k in applied]
    return receipt, doc


def receipt_text(receipt: dict[str, Any]) -> str:
    parts = []
    if receipt.get("kind") == "check":
        outcome = {"critical": "大成功", "fumble": "大失败", "success": "成功", "failure": "失败"}[receipt["outcome"]]
        parts.append(f"【检定】{receipt['attribute']}·{DIFFICULTY_LABELS.get(receipt['difficulty'], receipt['difficulty'])}："
                     f"d20={receipt['face']} {receipt['modifier']:+d} = {receipt['total']}，对抗 {receipt['dc']} → {outcome}")
    elif receipt.get("kind") == "recover":
        parts.append("【休整】")
    if receipt.get("prepared"):
        parts.append("准备：" + "、".join(p["name"] for p in receipt["prepared"]))
    changes = receipt.get("resource_changes") or {}
    if changes:
        parts.append("　".join(f"{k} {v:+d}" for k, v in changes.items()))
    if receipt.get("exhausted"):
        parts.append("（" + "、".join(receipt["exhausted"]) + "已耗尽）")
    return "".join(parts[:1]) + ("　" + "　".join(parts[1:]) if len(parts) > 1 else "")


# ---------------------------------------------------------------- resolution
async def narrate(app: "LiteApp", room_id: str, turn_id: str, *, advance: bool = True, note: str = "") -> Reply:
    """Ask the engine to narrate a committed receipt, then commit story and open the next turn.

    With review on, the draft goes to the host's private chat first (state 'review') and waits
    for /团 主持 发布 or /团 主持 重写; note carries the host's rewrite request.
    """
    with app.store.read() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        turn = c.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
        context = build_context(c, room, actor, turn["action_text"], loads(turn["receipt_json"]), note)
        reviewer = shared.private_umo(c, room["platform"], room["host_user_id"]) if hosted_data(room).get("review") else None
    # Group actions and host advances return the turn to the actor who was waiting.
    advance = advance and not loads(turn["data_json"], {}).get("resume_actor")
    try:
        result = await app.engine.call("narrate_committed", {"context": context}, room_id=room_id, umo=room["umo"],
                                       rules=shared.rules(room))
    except EngineCallFailed as exc:
        with app.store.tx() as c:
            c.execute("UPDATE turns SET state='narration_failed',updated_at=? WHERE id=?", (now(), turn_id))
        reason = "模型暂时连不上。" if exc.category == "provider_unavailable" else "模型几次回复都不合格式。"
        return Reply().say(messages.notice("这一段正文没写出来", reason + "骰果和资源变化已经保存，故事停在这里等主持人处理。",
                                           "主持人发送 /团 主持 重试 重新生成正文，或 /团 主持 跳过 直接轮到下一位；"
                                           "具体原因可在后台“运行”页查看"))
    proposal = result["proposal"]
    if reviewer:
        with app.store.tx() as c:
            data = {**loads(turn["data_json"], {}), "advance": advance}
            c.execute("UPDATE turns SET state='review',narrative_json=?,data_json=?,updated_at=? WHERE id=?",
                      (dumps(proposal), dumps(data), now(), turn_id))
        await app.notifier.send(reviewer, draft_card(room, turn, actor, proposal))
        return Reply().say(messages.notice("正文已写好，正在等主持人审阅", "主持人确认后会发到群里。"))
    return await commit_narration(app, room_id, turn_id, proposal, advance)


def draft_card(room: sqlite3.Row, turn: sqlite3.Row, actor: sqlite3.Row, proposal: dict[str, Any]) -> Any:
    from ..render import Msg
    rules = shared.rules(room)
    choices = make_choices(proposal["suggestions"], proposal.get("suggestion_checks"))
    m = Msg().title("正文草稿 · 待审阅", f"{room['title'].split(' · ')[0]}　第 {turn['round']} 轮　{shared.actor_label(actor)}")
    m.gap().para(narration_text(proposal)).gap()
    m.items([f"**{ch['label']}.** {ch['text']}" + (f"　〔{messages.check_tag(rules, ch['check'])}〕"
                                                   if messages.check_tag(rules, ch["check"]) else "") for ch in choices])
    return m.gap().hint("发送 /团 主持 发布 公开到群里，或 /团 主持 重写 意见 按意见重新生成")


async def commit_narration(app: "LiteApp", room_id: str, turn_id: str, proposal: dict[str, Any], advance: bool) -> Reply:
    """Store the narration, apply queued host adjustments and open the next turn."""
    with app.store.read() as c:
        turn = c.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
    text = narration_text(proposal)
    choices = make_choices(proposal["suggestions"], proposal.get("suggestion_checks"))
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        old_scene = loads(room["scene_json"], {}).get("title", "")
        shown_act = hosted_data(room).get("shown_act")
        act_heading = lifecycle.act_heading(room).split("\n")[0] if shown_act != room["act"] else ""
        if act_heading:
            set_hosted_data(c, room_id, shown_act=room["act"])
        c.execute("UPDATE turns SET state='done',narrative_json=?,updated_at=? WHERE id=?", (dumps(proposal), now(), turn_id))
        receipt = loads(turn["receipt_json"], {})
        _store_story(c, room_id, proposal, receipt.get("receipt_ref") or turn_id)
        app.store.add_event(c, room_id, "narration", text, actor_id=turn["actor_id"], data={"turn": turn_id})
        adjusted = adjust.apply_pending(c, room_id)
        if adjusted:
            app.store.add_event(c, room_id, "host", "主持人调整生效：" + "；".join(adjusted))
        round_number = turn["round"]
        if advance:
            following, wrapped = next_actor(c, room_id, actor)
            round_number += 1 if wrapped else 0
        else:
            following = c.execute("SELECT * FROM actors WHERE id=?", (loads(turn["data_json"], {}).get("resume_actor")
                                                                       or turn["actor_id"],)).fetchone()
        app.store.bump_room(c, room_id)
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        new_turn = open_turn(app, c, room, following, choices, round_number) if room["state"] == "running" else None
        if new_turn is None and room["state"] == "running":
            app.store.add_event(c, room_id, "system", "没有在场的玩家，故事停在这里。")
    scene_title = loads(room["scene_json"], {}).get("title", "")
    story = messages.narration(text, scene_title, act_heading)
    if act_heading or (scene_title and scene_title != old_scene):
        story.with_art(room["world_id"], f"act:{room['act']}", _art_tag(room))
    reply = Reply().say(story)
    if adjusted:
        reply.say(messages.adjustments_applied(adjusted))
    if new_turn is not None:
        reply.say(turn_prompt(room, new_turn, following))
        if advance and round_number != turn["round"]:
            from . import collaboration
            reply.extend(await collaboration.after_round(app, room_id, round_number))
    return reply


async def resolve(app: "LiteApp", room_id: str, turn_id: str, action: str, intent: dict[str, Any] | None,
                  *, announce: str = "", prepared: list[dict[str, Any]] | None = None) -> Reply:
    """Resolve the awaiting turn: intent (model unless given) → dice → narration."""
    async with app.lock(room_id):
        with app.store.tx() as c:
            turn = c.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
            if turn is None or turn["state"] != "awaiting":
                raise UserError("这个回合已经在处理或已结束。")
            quota.require_round(app, c, c.execute("SELECT umo FROM rooms WHERE id=?", (room_id,)).fetchone()["umo"])
            actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
            lifecycle.auto_snapshot(c, room_id, f"第 {turn['round']} 轮 · {shared.actor_label(actor)} 行动前")
            c.execute("UPDATE turns SET state='resolving',action_text=?,updated_at=? WHERE id=?", (action, now(), turn_id))
            room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
            context = build_context(c, room, actor, action, None)
        try:
            if intent is None:
                try:
                    result = await app.engine.call("propose_intent", {"context": context}, room_id=room_id, umo=room["umo"],
                                                   rules=shared.rules(room))
                except EngineCallFailed as exc:
                    with app.store.tx() as c:
                        c.execute("UPDATE turns SET state='awaiting',updated_at=? WHERE id=?", (now(), turn_id))
                    raise UserError("行动理解失败：" + exc.user_message + " 你可以换个说法再试，或选择 A–D。") from exc
                intent = result["proposal"]
                if intent["kind"] in ("clarify", "impossible"):
                    with app.store.tx() as c:
                        c.execute("UPDATE turns SET state='awaiting',updated_at=? WHERE id=?", (now(), turn_id))
                    prefix = "需要澄清：" if intent["kind"] == "clarify" else "这样做行不通："
                    return Reply().say(prefix + (intent.get("clarification") or intent.get("reason") or ""))
            with app.store.tx() as c:
                actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
                receipt, doc = mechanics(room, actor, intent, prepared)
                receipt["intent_reason"] = intent.get("reason", "")
                loadout.save(c, actor["id"], doc)
                if receipt.get("face"):
                    luck.record(c, room["umo"], actor["user_id"], actor["user_name"], "check", [receipt["face"]])
                if intent["kind"] == "recover":
                    loadout.refill(c, room, "rest", [actor["id"]])
                c.execute("UPDATE turns SET intent_json=?,receipt_json=?,updated_at=? WHERE id=?",
                          (dumps(intent), dumps(receipt), now(), turn_id))
                app.store.add_event(c, room_id, "action", f"{shared.actor_label(actor)}：{action}", actor_id=actor["id"])
                dice = receipt_text(receipt)
                if dice:
                    app.store.add_event(c, room_id, "check", f"{shared.actor_label(actor)} {dice}", actor_id=actor["id"],
                                        data=receipt)
        except Exception:
            with app.store.tx() as c:
                c.execute("UPDATE turns SET state='awaiting',updated_at=? WHERE id=? AND state='resolving'", (now(), turn_id))
            raise
        reply = Reply().say(status_message(room, actor, turn["round"], action, receipt, announce))
        return reply.extend(await narrate(app, room_id, turn_id))


# ---------------------------------------------------------------- hook handlers
async def on_story_started(room_id: str, *, app: "LiteApp") -> Reply:
    with app.store.read() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        actors = eligible_actors(c, room_id)
    rules = shared.rules(room)
    fields = {"brief": world_brief(shared.world(room), lifecycle.current_act(room)),
              "member_refs": [a["id"] for a in actors], "rules": rules}
    proposal = await app.engine.call("generate_initial_story", fields, room_id=room_id, umo=room["umo"], rules=rules)
    with app.store.tx() as c:
        c.execute("UPDATE rooms SET scene_json=?,goal=? WHERE id=?", (dumps(proposal["scene"]), proposal["goal"], room_id))
        for index, npc in enumerate(proposal["npcs"], 1):
            c.execute("INSERT OR REPLACE INTO npcs(room_id,npc_ref,name,description,motivation,updated_at) VALUES(?,?,?,?,?,?)",
                      (room_id, f"npc.opening{index}", npc["name"], npc["description"], npc["motivation"], now()))
        opening = f"{proposal['scene']['title']}\n{proposal['scene']['description']}"
        app.store.add_event(c, room_id, "narration", opening, data={"opening": True})
        set_hosted_data(c, room_id, shown_act=1)
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        first, _ = next_actor(c, room_id, None)
        turn = open_turn(app, c, room, first, make_choices(proposal["suggestions"], proposal.get("suggestion_checks")), 1)
        app.store.bump_room(c, room_id)
    acts = shared.world(room).get("presentation", {}).get("acts") or []
    act = next((a for a in acts if a["number"] == room["act"]), {"title": "", "lead": ""})
    reply = Reply().say(messages.act_card(shared.world(room)["pack"]["title"], room["act"], act["title"], act["lead"],
                                          world=room["world_id"], art="cover", total=lifecycle.acts_total(room)))
    reply.say(messages.scene_card(proposal["scene"]["title"], proposal["scene"]["description"], proposal["goal"],
                                  [(n["name"], n["description"]) for n in proposal["npcs"]])
              .with_art(room["world_id"], f"act:{room['act']}", _art_tag(room, act["title"])))
    if turn is not None:
        reply.say(turn_prompt(room, turn, first))
    if lifecycle.improvises(room):
        reply.say(messages.notice("核心版", "预设剧情只写到第一幕，之后由 AI 即兴续写，不推翻设定与已发生的事。",
                                  "主持人想开新的一幕时发送 /团 主持 换幕 标题：引子；收尾时发送 /团 主持 完结 结局名"))
    return reply


def _art_tag(room: sqlite3.Row, act_title: str = "") -> str:
    """Small caption on a scene banner: world name and act."""
    title = messages.short_title(shared.world(room)["pack"]["title"])
    return " · ".join(p for p in (title, messages.act_label(room["act"]), act_title) if p)


async def on_roster_changed(room_id: str, actor_id: str, change: str, *, app: "LiteApp") -> Reply:
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        turn = current_turn(c, room_id)
        if room["state"] != "running":
            return Reply()
        if turn is None:
            actor, _ = next_actor(c, room_id, None)
            new = open_turn(app, c, room, actor, [], 1) if actor is not None else None
            return Reply().say(turn_prompt(room, new, actor)) if new is not None else Reply()
        if change in ("left", "away", "rebuild") and turn["actor_id"] == actor_id and turn["state"] == "awaiting":
            leaving = c.execute("SELECT * FROM actors WHERE id=?", (actor_id,)).fetchone()
            following, wrapped = next_actor(c, room_id, leaving)
            new = open_turn(app, c, room, following, loads(turn["choices_json"], []), turn["round"] + (1 if wrapped else 0))
            if new is not None:
                return Reply().say(turn_prompt(room, new, following))
    return Reply()


async def on_room_resumed(room_id: str, *, app: "LiteApp") -> Reply:
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        turn = current_turn(c, room_id)
        if turn is None:
            actor, _ = next_actor(c, room_id, None)
            turn = open_turn(app, c, room, actor, [], 1) if actor is not None else None
        elif turn["state"] == "awaiting":
            c.execute("UPDATE turns SET deadline_at=? WHERE id=?", (_deadline(app, room), turn["id"]))
            turn = c.execute("SELECT * FROM turns WHERE id=?", (turn["id"],)).fetchone()
        if turn is None or turn["state"] != "awaiting":
            return Reply()
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
    reply = Reply()
    recap = await story_recap.on_resume(app, room_id)
    if recap is not None:
        reply.say(recap)
    return reply.say(turn_prompt(room, turn, actor))


async def on_room_restored(room_id: str, *, app: "LiteApp") -> Reply:
    with app.store.tx() as c:
        c.execute("UPDATE turns SET state='awaiting',updated_at=? WHERE room_id=? AND state='resolving'", (now(), room_id))
    return Reply()


async def on_story_completed(room_id: str, ending: Any, *, app: "LiteApp") -> Reply:
    with app.store.tx() as c:
        c.execute("UPDATE turns SET state='superseded',updated_at=? WHERE room_id=? AND state IN ('awaiting','narration_failed','review')",
                  (now(), room_id))
    return Reply()


async def on_status(room_id: str, *, app: "LiteApp") -> Reply:
    with app.store.read() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        turn = current_turn(c, room_id)
        if turn is None or room["state"] not in ("running", "paused"):
            return Reply()
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
    return Reply().say(f"第 {turn['round']} 轮：{shared.actor_label(actor)}（{TURN_STATES.get(turn['state'], turn['state'])}）")


async def on_tick(*, app: "LiteApp") -> Reply:
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    with app.store.read() as c:
        due = c.execute("SELECT t.id,t.room_id FROM turns t JOIN rooms r ON r.id=t.room_id WHERE t.state='awaiting' "
                        "AND r.state='running' AND t.deadline_at IS NOT NULL AND t.deadline_at<=?", (stamp,)).fetchall()
    for row in due:
        if app.lock(row["room_id"]).locked():
            continue
        app.spawn(timeout_turn(app, row["room_id"], row["id"]), name=f"321roll-timeout-{row['id']}")
    return Reply()


async def timeout_turn(app: "LiteApp", room_id: str, turn_id: str) -> None:
    with app.store.tx() as c:
        turn = c.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
        if turn is None or turn["state"] != "awaiting" or loads(turn["data_json"], {}).get("timeout"):
            return
        c.execute("UPDATE turns SET data_json=? WHERE id=?", (dumps({**loads(turn["data_json"], {}), "timeout": True}), turn_id))
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
        history = [r["text"][:6000] for r in c.execute(
            "SELECT text FROM events WHERE room_id=? AND kind='narration' ORDER BY id DESC LIMIT 3", (room_id,))]
    choices = loads(turn["choices_json"], [])
    label = shared.actor_label(actor)
    if not choices:
        with app.store.tx() as c:
            following, wrapped = next_actor(c, room_id, actor)
            new = open_turn(app, c, room, following, [], turn["round"] + (1 if wrapped else 0))
            app.store.add_event(c, room_id, "system", f"{label} 超时，回合跳过", actor_id=actor["id"])
        items = [f"{label} 超时未行动，回合跳过。"] + ([turn_prompt(room, new, following)] if new is not None else [])
        await app.notifier.send(room["umo"], items)
        return
    chosen = choices[0]
    try:
        with app.store.read() as c:
            quota.require_round(app, c, room["umo"])
    except UserError as exc:
        await app.notifier.send(room["umo"], f"{label} 超时未行动。{exc.message}")
        return
    try:
        context = {"round_ref": turn_id, "actor": label,
                   "candidates": [{"choice_ref": ch["label"], "text": ch["text"]} for ch in choices],
                   "visible_history": list(reversed(history))}
        ranking = (await app.engine.call("rank_timeout_choices", {"context": context}, room_id=room_id, umo=room["umo"]))["ranking"]
        best = min(ranking, key=lambda r: (r["risk"], r["choice_ref"]))
        chosen = next(ch for ch in choices if ch["label"] == best["choice_ref"])
    except EngineCallFailed:
        pass
    try:
        reply = await resolve(app, room_id, turn_id, chosen["text"], intent_from_choice(chosen),
                              announce=f"{label} 超时，自动选择 {chosen['label']}。")
    except UserError:
        return
    await app.notifier.send(room["umo"], reply.messages)


def intent_from_choice(choice: dict[str, Any]) -> dict[str, Any]:
    check = choice["check"]
    return {"kind": check["kind"], "attribute_ref": check.get("attribute_ref", ""), "difficulty": check.get("difficulty", ""),
            "failure_cost": check.get("failure_cost", ""), "reason": "玩家选择了平台核验过的选项", "clarification": "",
            "risk_response": ""}


# ---------------------------------------------------------------- player commands
def _my_turn(app: "LiteApp", caller: Caller) -> tuple[sqlite3.Row, sqlite3.Row, sqlite3.Row]:
    room = shared.require_room(app, caller, "running")
    shared.require_play(app, caller, "playActions")
    actor = shared.require_actor(app, caller, room)
    with app.store.read() as c:
        turn = current_turn(c, room["id"])
    if turn is None or turn["state"] != "awaiting":
        raise UserError("现在没有等待行动的回合。" if turn is None else
                        "上一段正文正在等主持人审阅，请稍候。" if turn["state"] == "review" else "上一个行动还在结算，请稍候。")
    if turn["actor_id"] != actor["id"]:
        with app.store.read() as c:
            holder = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
        raise UserError(f"现在轮到 {shared.actor_label(holder)} 行动。")
    return room, actor, turn


async def choose(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room, actor, turn = _my_turn(app, caller)
    if shared.rules(room).get("action_mode") == "dialogue_only":
        raise UserError("本世界只接受自由描述行动：/团 行动 <描述>")
    args, names = loadout.split_marker(args)
    words = args.split(maxsplit=1)
    label = words[0].upper().replace("Ａ", "A").replace("Ｂ", "B").replace("Ｃ", "C").replace("Ｄ", "D") if words else ""
    choice = next((ch for ch in loads(turn["choices_json"], []) if ch["label"] == label), None)
    if choice is None:
        raise UserError("请选择本轮列出的 A–D 之一，例如 /团 选 A。")
    check = choice["check"]
    prepared = loadout.freeze(room, actor, names, check.get("attribute_ref") if check.get("kind") == "check" else None) if names else None
    flourish = words[1].strip() if len(words) > 1 else ""
    action = choice["text"] + (f"（{flourish[:200]}）" if flourish else "")
    with app.store.read() as c:
        quota.require_round(app, c, room["umo"])
    await story_recap.before_action(app, caller, room["id"])
    return await resolve(app, room["id"], turn["id"], action, intent_from_choice(choice), prepared=prepared)


async def act(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room, actor, turn = _my_turn(app, caller)
    if shared.rules(room).get("action_mode") == "choice_only":
        raise UserError("本世界只接受选项行动：/团 选 A")
    text, names = loadout.split_marker(args)
    if not 2 <= len(text) <= 500:
        raise UserError("写一句 2–500 字的行动描述，例如 /团 行动 推开音乐室的门看看。")
    prepared = loadout.freeze(room, actor, names) if names else None
    with app.store.read() as c:
        quota.require_round(app, c, room["umo"])        # before "正在结算" goes out
    await story_recap.before_action(app, caller, room["id"])
    await caller.send("正在结算……")
    return await resolve(app, room["id"], turn["id"], text, None, prepared=prepared)


async def skip(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room, actor, turn = _my_turn(app, caller)
    return _advance_without_action(app, room, turn, f"{shared.actor_label(actor)} 跳过了本回合。")


def _advance_without_action(app: "LiteApp", room: sqlite3.Row, turn: sqlite3.Row, message: str) -> Reply:
    with app.store.tx() as c:
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
        c.execute("UPDATE turns SET state='skipped',updated_at=? WHERE id=?", (now(), turn["id"]))
        following, wrapped = next_actor(c, room["id"], actor)
        new = open_turn(app, c, room, following, loads(turn["choices_json"], []), turn["round"] + (1 if wrapped else 0))
        app.store.add_event(c, room["id"], "system", message, actor_id=actor["id"])
    reply = Reply().say(message)
    if new is not None:
        reply.say(turn_prompt(room, new, following))
    return reply


def pass_turn(app: "LiteApp", room: sqlite3.Row, turn: sqlite3.Row, message: str) -> Reply:
    """Hand the awaiting turn to the next player after a turn-bound engine play."""
    return _advance_without_action(app, room, turn, message)


async def show_turn(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "running", "paused")
    with app.store.read() as c:
        turn = current_turn(c, room["id"])
        actor = None if turn is None else c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
    if turn is None:
        return Reply().say("现在没有进行中的回合。")
    if turn["state"] != "awaiting":
        return Reply().say({"resolving": f"{shared.actor_label(actor)} 的行动正在结算。",
                            "review": "上一段正文正在等主持人审阅。"}.get(turn["state"], "上一回合的正文待主持人 /团 主持 重试。"))
    return Reply().say(turn_prompt(room, turn, actor))


async def order(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, "running", "paused")
    with app.store.read() as c:
        actors = eligible_actors(c, room["id"])
        turn = current_turn(c, room["id"])
    current = turn["actor_id"] if turn else None
    from ..render import Msg
    return Reply().say(Msg().title("行动顺序").gap().items(
        [(f"**▸ {shared.actor_label(a)}**" if a["id"] == current else shared.actor_label(a)) + f"　{a['user_name']}" for a in actors]))


async def recap(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller)
    count = int(args) if args.strip().isdigit() and 1 <= int(args) <= 5 else 2
    with app.store.read() as c:
        rows = c.execute("SELECT text FROM events WHERE room_id=? AND kind='narration' ORDER BY id DESC LIMIT ?",
                         (room["id"], count)).fetchall()
    if not rows:
        return Reply().say("还没有剧情可以回顾。")
    reply = Reply()
    for row in reversed(rows):
        reply.say(messages.narration(row["text"]))
    return reply


# ---------------------------------------------------------------- host commands
def _host_room(app: "LiteApp", caller: Caller, *states: str) -> sqlite3.Row:
    room = shared.require_room(app, caller, *(states or ("running", "paused")))
    shared.require_host(app, caller, room)
    return room


async def host_narrate(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller)
    text = args.strip()
    if not 2 <= len(text) <= 1000:
        raise UserError("写法：/团 主持 直述 <公开剧情，2–1000 字>")
    with app.store.tx() as c:
        count = c.execute("SELECT COUNT(*) FROM facts WHERE room_id=?", (room["id"],)).fetchone()[0]
        c.execute("INSERT INTO facts(room_id,fact_ref,kind,subject_ref,text,source_receipt_ref,created_at) VALUES(?,?,?,?,?,?,?)",
                  (room["id"], f"fact.{count + 1}", "world_fact", "scene", text, "host." + caller.user_id, now()))
        app.store.add_event(c, room["id"], "host", text)
    return Reply().say(messages.host_line(text))


async def host_directive(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, "lobby", "running", "paused")
    text = args.strip()
    if not text:
        current = hosted_data(room).get("directive")
        if not current:
            return Reply().say(messages.notice("现在没有主持人指引", "", "发送 /团 主持 指引 内容 记录一条，只有叙事模型会看到"))
        return Reply().say(messages.notice("当前的主持人指引", current, "发送 /团 主持 指引 新内容 替换，/团 主持 指引 清除 取消"))
    with app.store.tx() as c:
        set_hosted_data(c, room["id"], directive="" if text == "清除" else text[:600])
    return Reply().say(messages.notice("已清除主持人指引") if text == "清除" else messages.notice("已记录主持人指引", "之后的叙事会参考它，不会发到群里。", "发送 /团 主持 指引 清除 取消"))


async def host_time_limit(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, "lobby", "running", "paused")
    text = args.strip().removesuffix("分钟").strip()
    usage = "发送 /团 主持 限时 分钟数（1–1440）修改，0 为不限时，默认 恢复全局设置"
    if not text:
        own = hosted_data(room).get("turn_seconds") is not None
        return Reply().say(messages.notice(f"回合限时：{limit_text(turn_seconds(app, room))}",
                                           ("本桌单独设置" if own else "跟随全局设置") + "。超时后自动选择风险最低的选项。", usage))
    if text in ("默认", "全局"):
        value = None
    elif text in ("0", "不限", "不限时", "关闭"):
        value = 0
    elif text.isdigit() and 1 <= int(text) <= 1440:
        value = int(text) * 60
    else:
        raise UserError("写法：/团 主持 限时 分钟数（1–1440），0 为不限时，默认 恢复全局设置")
    with app.store.tx() as c:
        set_hosted_data(c, room["id"], turn_seconds=value)
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
        label = limit_text(turn_seconds(app, room))
        app.store.add_event(c, room["id"], "system", f"{caller.user_name} 把回合限时改为{label}")
        turn = current_turn(c, room["id"])
        holder = None
        if room["state"] == "running" and turn is not None and turn["state"] == "awaiting" and turn["actor_id"]:
            c.execute("UPDATE turns SET deadline_at=?,updated_at=? WHERE id=?", (_deadline(app, room), now(), turn["id"]))
            holder = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
    detail = ("跟随全局设置。" if value is None else "") + (
        f"{shared.actor_label(holder)} 的这一回合从现在起重新计时。" if holder is not None else "从下一回合开始生效。")
    return Reply().say(messages.notice(f"回合限时改为{label}", detail, "超时后自动选择风险最低的选项；" + usage.removeprefix("发送 ")))


async def host_advance(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, "running")
    with app.store.read() as c:
        turn = current_turn(c, room["id"])
    if turn is None or turn["state"] != "awaiting":
        raise UserError("当前回合正在结算或没有回合。")
    action = "（主持人推进剧情）" + (args.strip()[:300] or "让局势自然发展一步")
    await caller.send("正在推进……")
    with app.store.tx() as c:
        lifecycle.auto_snapshot(c, room["id"], f"第 {turn['round']} 轮 · 主持人推进前")
        c.execute("UPDATE turns SET state='superseded',updated_at=? WHERE id=?", (now(), turn["id"]))
        host_turn = new_id("turn")
        c.execute("INSERT INTO turns(id,room_id,round,actor_id,state,choices_json,action_text,receipt_json,data_json,created_at,updated_at) "
                  "VALUES(?,?,?,?,'resolving','[]',?,?,?,?,?)",
                  (host_turn, room["id"], turn["round"], turn["actor_id"], action,
                   dumps({"receipt_ref": new_id("receipt"), "kind": "host_advance"}), dumps({"resume_actor": turn["actor_id"]}),
                   now(), now()))
    async with app.lock(room["id"]):
        return await narrate(app, room["id"], host_turn, advance=False)


async def host_skip(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, "running")
    with app.store.read() as c:
        turn = current_turn(c, room["id"])
    if turn is None or turn["state"] not in ("awaiting", "narration_failed", "review"):
        raise UserError("当前没有可以跳过的回合。")
    return _advance_without_action(app, room, turn, "主持人跳过了当前回合。")


async def host_choices(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, "running")
    texts = [t.strip() for t in args.replace("|", "｜").split("｜") if t.strip()][:4]
    if not texts:
        raise UserError("写法：/团 主持 选项 选项一｜选项二｜选项三")
    with app.store.tx() as c:
        turn = current_turn(c, room["id"])
        if turn is None or turn["state"] != "awaiting":
            raise UserError("当前没有等待行动的回合。")
        c.execute("UPDATE turns SET choices_json=?,updated_at=? WHERE id=?", (dumps(make_choices(texts, None)), now(), turn["id"]))
        turn = c.execute("SELECT * FROM turns WHERE id=?", (turn["id"],)).fetchone()
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
    return Reply().say("主持人更新了选项。", turn_prompt(room, turn, actor))


async def host_retry(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, "running")
    with app.store.tx() as c:
        turn = current_turn(c, room["id"])
        if turn is None or turn["state"] != "narration_failed":
            raise UserError("没有需要重试的正文。")
        c.execute("UPDATE turns SET state='resolving',updated_at=? WHERE id=?", (now(), turn["id"]))
    await caller.send("正在重新生成正文……")
    advance = not loads(turn["data_json"], {}).get("resume_actor")
    async with app.lock(room["id"]):
        return await narrate(app, room["id"], turn["id"], advance=advance)


async def host_next_act(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller)
    preset = shared.world(room).get("presentation", {}).get("acts") or []
    words = args.strip().split(maxsplit=1)
    number = words[0] if words and words[0].isdigit() else ""
    target = int(number) if number else room["act"] + 1
    named = (words[1] if len(words) > 1 else "") if number else args.strip()
    improvised = None
    if preset and not any(a["number"] == target for a in preset):
        if not lifecycle.improvises(room):
            raise UserError(f"本世界共 {len(preset)} 幕。")
        if target < 1 or target > max(room["act"], len(preset)) + 1:
            raise UserError(f"下一幕是第 {max(room['act'], len(preset)) + 1} 幕。")
        # A Core edition stops at its first act; the host names each later act and the model improvises it.
        title, lead = split_title(named) if "：" in named or ":" in named else (named, "")
        known = next((a for a in lifecycle.act_list(room) if a["number"] == target), None)
        improvised = {"title": (title or (known or {}).get("title", ""))[:40], "lead": (lead or (known or {}).get("lead", ""))[:300]}
    with app.store.tx() as c:
        from ..fun.report import act_recap, favourite_line, favourites
        best = favourite_line(favourites(c, room["id"], room["act"])) if target != room["act"] else ""
        recap = act_recap(c, room["id"]) if target != room["act"] else None
        c.execute("UPDATE rooms SET act=?,chapter=chapter+1 WHERE id=?", (target, room["id"]))
        if improvised is not None:
            extra = hosted_data(room).get("acts") or {}
            set_hosted_data(c, room["id"], acts={**extra, str(target): improvised})
        app.store.bump_room(c, room["id"])
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
        heading = lifecycle.act_heading(room) or f"第 {target} 幕"
        app.store.add_event(c, room["id"], "chapter", heading.replace("\n", "——"))
        set_hosted_data(c, room["id"], shown_act=target)
        refilled = loadout.refill(c, room, "scene")
        turn = current_turn(c, room["id"])
        holder = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone() \
            if turn is not None and turn["state"] == "awaiting" and turn["actor_id"] else None
    act = next((a for a in lifecycle.act_list(room) if a["number"] == target), {"title": "", "lead": ""})
    reply = Reply().say(messages.act_card(room["title"], target, act["title"] or f"第 {target} 幕", act["lead"],
                                          world=room["world_id"], total=lifecycle.acts_total(room), best=best, recap=recap))
    if refilled:
        reply.say(f"新的一幕：按“每幕恢复”的技能与物品次数已恢复（{refilled} 名角色）。")
    if holder is not None and room["state"] == "running":
        reply.say(turn_prompt(room, turn, holder))
    return reply


async def host_turn_to(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, "running")
    token, _ = shared.split_target(args, caller)
    with app.store.tx() as c:
        turn = current_turn(c, room["id"])
        if turn is None or turn["state"] != "awaiting":
            raise UserError("现在没有等待行动的回合。")
        target = shared.find_actor(c, room["id"], token, caller.mentions)
        if target["presence"] != "present" or not target["archetype_id"]:
            raise UserError(f"{shared.actor_label(target)} 现在不能行动（暂离或还没建卡）。")
        if target["id"] == turn["actor_id"]:
            raise UserError(f"现在就是 {shared.actor_label(target)} 的回合。")
        new = open_turn(app, c, room, target, loads(turn["choices_json"], []), turn["round"])
        app.store.add_event(c, room["id"], "system", f"主持人把回合交给 {shared.actor_label(target)}", actor_id=target["id"])
    return Reply().say(f"主持人把这一回合交给了 {shared.actor_label(target)}。", turn_prompt(room, new, target))


async def host_rewind(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, "running", "paused")
    async with app.lock(room["id"]):
        with app.store.tx() as c:
            turn = current_turn(c, room["id"])
            if turn is not None and turn["state"] == "resolving":
                raise UserError("有行动正在结算，等它结束后再回退。")
            snapshot = c.execute("SELECT * FROM saves WHERE room_id=? AND created_by=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                                 (room["id"], lifecycle.AUTO_SAVE)).fetchone()
            if snapshot is None:
                raise UserError("没有可以回退的行动。每次行动结算前会自动留一份记录，最多保留最近 5 步。")
            lifecycle.restore_snapshot(c, room["id"], loads(snapshot["data_json"]))
            c.execute("DELETE FROM saves WHERE id=?", (snapshot["id"],))
            if room["state"] == "running":
                c.execute("UPDATE rooms SET state='running' WHERE id=?", (room["id"],))
            restored = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
            turn = current_turn(c, room["id"])
            holder = None
            if turn is not None and turn["state"] == "awaiting":
                c.execute("UPDATE turns SET deadline_at=?,data_json=?,updated_at=? WHERE id=?",
                          (_deadline(app, restored) if restored["state"] == "running" else turn["deadline_at"],
                           dumps({k: v for k, v in loads(turn["data_json"], {}).items() if k != "timeout"}), now(), turn["id"]))
                turn = c.execute("SELECT * FROM turns WHERE id=?", (turn["id"],)).fetchone()
                holder = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
            left = c.execute("SELECT COUNT(*) FROM saves WHERE room_id=? AND created_by=?", (room["id"], lifecycle.AUTO_SAVE)).fetchone()[0]
            app.store.add_event(c, room["id"], "system", f"主持人回退到「{snapshot['name']}」")
            app.store.audit(c, caller.user_id, "room.rewind", room["id"], {"to": snapshot["name"]})
            app.store.bump_room(c, room["id"])
    reply = Reply().say(messages.notice(f"已回退到「{snapshot['name']}」",
                                        "这一步的骰子、资源变化、正文和玩法记录都已撤回。" + (f"还可以再回退 {left} 步。" if left else "这是能回退的最早一步。"),
                                        "" if restored["state"] == "running" else "故事处于暂停状态，主持人发送 /团 恢复 继续"))
    if holder is not None and restored["state"] == "running":
        reply.say(turn_prompt(restored, turn, holder))
    return reply


def set_narration(app: "LiteApp", room_id: str, changes: dict[str, Any], by: str) -> sqlite3.Row:
    """Change the table's narration settings (group commands and the WebUI); the next narration uses them."""
    what = "、".join(narration.FIELD_LABELS.get(f, "风格描述") for f in changes)
    try:
        with app.store.tx() as c:
            narration.set_room(c, room_id, changes)
            app.store.add_event(c, room_id, "system", f"{by} 调整了{what}")
            return c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    except ValueError as exc:
        raise UserError(str(exc)) from exc


def _style_detail(view: dict[str, Any]) -> str:
    return "对白与描写：" + narration.describe(view, "dialogue") + (f"；风格补充：{view['style']}" if view["style"] else "")


async def host_length(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, "lobby", "running", "paused")
    word = args.strip()
    usage = "发送 /团 主持 篇幅 不限、简洁（100–300 字）、均衡（300–600 字）或 长篇（600–1000 字）；写“默认”跟随世界"
    if word:
        value = None if word == "默认" else narration.parse("length", word)
        if value is None and word != "默认":
            raise UserError("写法：/团 主持 篇幅 不限｜简洁｜均衡｜长篇｜默认")
        room = set_narration(app, room["id"], {"length": value}, caller.user_name)
    view = narration.room_view(room)
    detail = narration.length_detail(view["length"]["value"]) + ("。从下一段正文开始生效。" if word else "。")
    return Reply().say(messages.notice("正文篇幅：" + narration.describe(view, "length"), detail,
                                       usage if not word else "发送 /团 主持 文风 调整对白与描写的比例"))


async def host_style(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, "lobby", "running", "paused")
    text = args.strip()
    usage = "发送 /团 主持 文风 [多对白｜偏对白｜均衡｜偏描写｜多描写] [风格补充]；写“默认”跟随世界并清除风格补充"
    if text:
        words = text.split(maxsplit=1)
        dialogue = narration.parse("dialogue", words[0])
        changes: dict[str, Any] = {"dialogue": None, "style": ""} if text == "默认" else {}
        if dialogue is not None:
            changes["dialogue"] = dialogue
            text = words[1].strip() if len(words) > 1 else ""
        if text and text != "默认":
            changes["style"] = text
        room = set_narration(app, room["id"], changes, caller.user_name)
    view = narration.room_view(room)
    return Reply().say(messages.notice("正文文风", _style_detail(view) + ("。从下一段正文开始生效。" if args.strip() else "。"), usage))


async def host_improv(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, "lobby", "running", "paused")
    word = args.strip()
    usage = "发送 /团 主持 即兴 严谨｜稳健｜均衡｜灵动｜奔放；写“默认”跟随世界"
    if word:
        value = None if word == "默认" else narration.parse("improv", word)
        if value is None and word != "默认":
            raise UserError("写法：/团 主持 即兴 严谨｜稳健｜均衡｜灵动｜奔放｜默认")
        room = set_narration(app, room["id"], {"improv": value}, caller.user_name)
    view = narration.room_view(room)
    current = view["improv"]["value"]
    detail = (narration.IMPROV_TEXT[current] if current else "没有设置，模型按自己的习惯发挥。") + ("从下一段正文开始生效。" if word else "")
    return Reply().say(messages.notice("即兴程度：" + narration.describe(view, "improv"), detail, usage))


async def host_check(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller)
    rules = shared.rules(room)
    token, rest = shared.split_target(args, caller)
    words = rest.split()
    usage = ("写法：/团 主持 检定 角色 属性 难度 [受伤] [理由]。属性：" + "、".join(rules["attributes"].values())
             + "；难度：" + "、".join(DIFFICULTY_LABELS.get(k, k) for k in rules["difficulties"]))
    if len(words) < 2:
        raise UserError(usage)
    attribute = next((ref for ref, name in rules["attributes"].items() if words[0] in (ref, name)), None)
    difficulty = next((key for key in rules["difficulties"] if words[1] in (key, DIFFICULTY_LABELS.get(key))), None)
    if attribute is None or difficulty is None:
        raise UserError(usage)
    harm = len(words) > 2 and words[2] in ("受伤", "伤害")
    reason = " ".join(words[3 if harm else 2:])[:200]
    with app.store.tx() as c:
        actor = shared.find_actor(c, room["id"], token, caller.mentions)
        if not actor["archetype_id"]:
            raise UserError(f"{actor['user_name']} 还没有建卡。")
        mod = rules["modifier"]
        score = loads(actor["attributes_json"], {}).get(attribute, mod["baseline"])
        base = (score - mod["baseline"]) // mod["divisor"]
        roll = roll_check(base, rules["difficulties"][difficulty])
        outcome = "critical" if roll.critical else "fumble" if roll.fumble else "success" if roll.success else "failure"
        names = {r["id"]: r["name"] for r in shared.world(room)["pack"]["resources"]}
        receipt = {"kind": "check", "attribute_ref": attribute, "attribute": rules["attributes"][attribute], "difficulty": difficulty,
                   "dc": roll.dc, "face": roll.face, "modifier": base, "total": roll.total, "outcome": outcome, "success": roll.success,
                   "resource_changes": {}, "resources_after": {names.get(k, k): v["current"] for k, v in loads(actor["resources_json"], {}).items()},
                   "host_check": True}
        label = shared.actor_label(actor)
        app.store.add_event(c, room["id"], "check", f"{label} 【主持检定】{receipt_text(receipt).removeprefix('【检定】')}"
                            + (f"（{reason}）" if reason else ""), actor_id=actor["id"], data=receipt)
        luck.record(c, room["umo"], actor["user_id"], actor["user_name"], "check", [roll.face])
        queued: list[str] = []
        deltas = (rules.get("failure_costs") or {}).get("harm") or {}
        if harm and not roll.success and deltas:
            fresh = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
            item = adjust.queue(c, fresh, [{"kind": "resource", "actor": actor["id"], "ref": ref, "delta": delta}
                                           for ref, delta in deltas.items() if delta], caller.user_id, "主持检定的失败代价")
            queued = [adjust.describe(fresh, change, {actor["id"]: label}) for change in item["changes"]]
        turn = current_turn(c, room["id"])
        round_number = turn["round"] if turn is not None else c.execute(
            "SELECT COALESCE(MAX(round),1) FROM turns WHERE room_id=?", (room["id"],)).fetchone()[0]
    reply = Reply().say(status_message(room, actor, round_number, "主持人要求检定" + (f"：{reason}" if reason else ""), receipt))
    if queued:
        reply.say(messages.notice("失败代价将在下一回合正文写完后生效", "；".join(queued)))
    reply.say("检定结果已记入剧情，下一段正文会据此叙述。")
    return reply


async def host_review(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, "lobby", "running", "paused")
    text = args.strip()
    on = bool(hosted_data(room).get("review"))
    usage = "发送 /团 主持 审稿 开 或 /团 主持 审稿 关"
    if not text:
        return Reply().say(messages.notice("审稿模式：" + ("开启" if on else "关闭"),
                                           "开启后，模型写好的正文先私发给主持人，确认后才发到群里。", usage))
    if text not in ("开", "开启", "关", "关闭"):
        raise UserError("写法：/团 主持 审稿 开｜关")
    enable = text in ("开", "开启")
    if enable:
        with app.store.read() as c:
            reachable = shared.private_umo(c, room["platform"], room["host_user_id"])
        if not reachable:
            raise UserError("审稿时草稿会私发给主持人。请主持人先私聊我发送任意 /团 指令（例如 /团 帮助），再开启审稿。")
    with app.store.tx() as c:
        set_hosted_data(c, room["id"], review=enable)
        app.store.add_event(c, room["id"], "system", f"{caller.user_name} {'开启' if enable else '关闭'}了审稿模式")
    if enable:
        return Reply().say(messages.notice("审稿模式已开启", "之后每段正文先私发给主持人；群里会看到“正在等主持人审阅”。",
                                           "主持人在私聊里发送 /团 主持 发布 公开，/团 主持 重写 意见 重新生成"))
    return Reply().say(messages.notice("审稿模式已关闭", "正文写好后直接发到群里。"))


def _review_turn(app: "LiteApp", room: sqlite3.Row) -> sqlite3.Row:
    with app.store.read() as c:
        turn = current_turn(c, room["id"])
    if turn is None or turn["state"] != "review":
        raise UserError("现在没有等待审阅的正文。")
    return turn


async def host_publish(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, "running")
    turn = _review_turn(app, room)
    async with app.lock(room["id"]):
        with app.store.tx() as c:
            if c.execute("UPDATE turns SET state='resolving',updated_at=? WHERE id=? AND state='review'",
                         (now(), turn["id"])).rowcount != 1:
                raise UserError("这段正文刚刚已经处理过了。")
        return await commit_narration(app, room["id"], turn["id"], loads(turn["narrative_json"]),
                                      loads(turn["data_json"], {}).get("advance", True))


async def host_rewrite(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, "running")
    turn = _review_turn(app, room)
    with app.store.tx() as c:
        if c.execute("UPDATE turns SET state='resolving',updated_at=? WHERE id=? AND state='review'",
                     (now(), turn["id"])).rowcount != 1:
            raise UserError("这段正文刚刚已经处理过了。")
    await caller.send("正在按意见重写……")
    async with app.lock(room["id"]):
        reply = await narrate(app, room["id"], turn["id"], advance=loads(turn["data_json"], {}).get("advance", True),
                              note=args.strip() or "换一种写法，保持已发生的结果不变")
    return reply




def install(app: "LiteApp") -> None:
    r = app.router
    r.register(("选", "选择"), choose, summary="选择本轮选项", usage="/团 选 A [补充演绎]", topic="行动", private="room")
    r.register("行动", act, summary="自由描述行动", usage="/团 行动 <描述>", topic="行动", private="room")
    r.register("跳过", skip, summary="跳过自己的回合", topic="行动", private="room")
    r.register(("回合", "倒计时"), show_turn, summary="查看当前回合与选项", topic="行动", private="self")
    r.register(("顺序", "轮次"), order, summary="查看行动顺序", topic="行动", private="self")
    r.register("回顾", recap, summary="回顾最近剧情", usage="/团 回顾 [1-5]", topic="行动", private="self")
    r.register("主持 直述", host_narrate, summary="直接叙述一段公开剧情", usage="/团 主持 直述 <内容>", topic="主持")
    r.register("主持 指引", host_directive, summary="给叙事模型的私下指引", usage="/团 主持 指引 <内容|清除>", topic="主持", private="self")
    r.register("主持 限时", host_time_limit, summary="调整本桌每回合的行动时间", usage="/团 主持 限时 [分钟|0|默认]", topic="主持")
    r.register("主持 推进", host_advance, summary="让剧情推进一步", usage="/团 主持 推进 [说明]", topic="主持")
    r.register(("主持 跳过", "强制下一位"), host_skip, summary="跳过当前玩家", topic="主持")
    r.register("主持 选项", host_choices, summary="手动设置本轮选项", usage="/团 主持 选项 一｜二｜三", topic="主持")
    r.register("主持 重试", host_retry, summary="重新生成失败的正文", topic="主持")
    r.register("主持 换幕", host_next_act, summary="进入下一幕；核心版写完第一幕后可以自己命名新的一幕",
               usage="/团 主持 换幕 [幕号] [标题：引子]", topic="主持")
    r.register("主持 轮到", host_turn_to, summary="把当前回合交给指定玩家", usage="/团 主持 轮到 <角色|@对方>", topic="主持")
    r.register("主持 回退", host_rewind, summary="撤回最近一步行动（最多 5 步）", topic="主持")
    r.register("主持 篇幅", host_length, summary="正文篇幅：不限、简洁、均衡或长篇", usage="/团 主持 篇幅 [不限|简洁|均衡|长篇|默认]", topic="主持")
    r.register("主持 文风", host_style, summary="对白与描写的比例和风格补充", usage="/团 主持 文风 [多对白|偏对白|均衡|偏描写|多描写] [补充]", topic="主持")
    r.register("主持 即兴", host_improv, summary="即兴程度：从严谨到奔放", usage="/团 主持 即兴 [严谨|稳健|均衡|灵动|奔放|默认]", topic="主持")
    r.register("主持 检定", host_check, summary="要求一位玩家立即检定", usage="/团 主持 检定 <角色> <属性> <难度> [受伤] [理由]", topic="主持")
    r.register("主持 审稿", host_review, summary="正文先私发主持人审阅再公开", usage="/团 主持 审稿 [开|关]", topic="主持")
    r.register("主持 发布", host_publish, summary="公开待审阅的正文", topic="主持", private="room")
    r.register("主持 重写", host_rewrite, summary="按意见重写待审阅的正文", usage="/团 主持 重写 [意见]", topic="主持", private="self")

    def bind(fn):
        async def handler(**payload):
            return await fn(app=app, **payload)
        return handler

    app.hooks.on("story_started", bind(on_story_started))
    app.hooks.on("roster_changed", bind(on_roster_changed))
    app.hooks.on("room_resumed", bind(on_room_resumed))
    app.hooks.on("room_restored", bind(on_room_restored))
    app.hooks.on("story_completed", bind(on_story_completed))
    app.hooks.on("status_lines", bind(on_status))
    app.hooks.on("tick", bind(on_tick))
