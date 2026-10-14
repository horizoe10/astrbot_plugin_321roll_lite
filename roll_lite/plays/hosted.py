"""Hosted turns (playActions): opening, intent, platform dice, narration, A-D choices, timeouts.

One awaiting turn exists per running room.  Resolving a turn commits the dice
and resource changes first (turn.receipt_json), then asks the engine for the
narration; if narration fails the receipt stays and the host can retry.
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from astrbot.api import logger

from .. import adjust, clock, continuity, economy, loadout, narration, personas, quota, shared
from .. import messages
from ..commands import Caller, Reply, UserError, split_title
from ..dice import roll_check, success_chance
from ..engine.gateway import EngineCallFailed, EngineInputError, new_operation_ref
from ..fun import luck
from ..rooms import lifecycle
from ..rooms.build import trait_bonus
from ..storage import dumps, loads, new_id, now
from ..worlds.catalog import brief as world_brief
from . import banter, pacing, story_recap, ties, wager

if TYPE_CHECKING:
    from ..app import LiteApp

LABELS = "ABCD"
DIFFICULTY_LABELS = {"easy": "简单", "standard": "标准", "hard": "困难", "exceptional": "极难"}
NARRATION_KINDS = ("narration", "action", "check", "play", "vote", "host", "chapter")
# The engine keeps only the last six recent events: five turns of story, then one line of table notes.
HISTORY_TURNS = 5


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
    from ..rooms.build import model_line as background
    told = background(actor)
    if told:
        view["background"] = told
    return view


def story_turns(c: sqlite3.Connection, room: sqlite3.Row) -> list[str]:
    """The last few turns, one string each: who did what and the dice, then the narration that answered them.

    A turn still being narrated (its action and check already logged) comes last, unfinished.
    """
    rows = c.execute(f"SELECT kind,text FROM events WHERE room_id=? AND kind IN ({','.join('?' * len(NARRATION_KINDS))}) "
                     "ORDER BY id DESC LIMIT 40", (room["id"], *NARRATION_KINDS)).fetchall()
    turns: list[list[str]] = [[]]
    for row in reversed(rows):
        turns[-1].append(row["text"])
        if row["kind"] == "narration":
            turns.append([])
    turns = [t for t in turns if t][-HISTORY_TURNS:]
    # The latest turn is kept whole; earlier narration is cut shorter so five turns fit the model's budget.
    return ["\n".join(text[:3000 if i == len(turns) - 1 else 1200] for text in turn) for i, turn in enumerate(turns)]


NARRATOR_KINDS = ("host_advance", "world_pulse", "pace_push", "finale")     # receipts of a turn no player acted in


def party_line(c: sqlite3.Connection, room: sqlite3.Row, actor: sqlite3.Row, narrator: bool = False) -> str:
    """Who sits at the table, so the model keeps each player's character apart from the one acting now."""
    others = []
    for a in eligible_actors(c, room["id"]):
        if a["id"] == actor["id"] and not narrator:
            continue
        persona = personas.active(room, a) or {}
        archetype = next((t["name"] for t in shared.world(room)["pack"]["archetypes"] if t["id"] == a["archetype_id"]), "")
        intro = (persona.get("intro") or "")[:80]
        others.append(shared.actor_label(a) + "（" + "，".join(filter(None, [archetype, "在本世界中：" + intro if intro else ""])) + "）")
    if narrator:
        return ("本轮没有玩家行动，由主持推进剧情；写完后轮到 " + shared.actor_label(actor) + " 行动。同桌玩家角色："
                + "、".join(others) + "。他们由真人扮演：可以写他们在场、被看见或被搭话，但不替他们说话、行动、做决定或描写内心。")
    line = f"本轮行动者：{shared.actor_label(actor)}。"
    if others:
        line += ("同桌其他玩家角色：" + "、".join(others) + "。他们由其他真人扮演，只作为在场同伴出现："
                 "不替他们说话、行动、做决定或描写内心；actor 的人设只属于本轮行动者，不安到别人身上；"
                 "最近几轮里别人做过的事仍归别人，不挪给本轮行动者。")
    return line


def table_notes(c: sqlite3.Connection, room: sqlite3.Row, actor: sqlite3.Row | None, note: str = "",
                narrator: bool = False, extra: list[str] | None = None, party: str | None = None) -> str:
    """Everything about the table that is not story, as one recent event so it never pushes story turns out."""
    lines = ["【本桌备注，不是剧情】"] + ([party or party_line(c, room, actor, narrator)] if actor is not None else [])
    heading = lifecycle.act_heading(room)
    if heading:
        lines.append("当前幕：" + heading.replace("\n", "——"))
    when = lifecycle.clock_text(room)
    if when:
        lines.append("当前时间：" + when)
        lines.append('历史facts中的记录回合与记录场景只是来源，不是现在或预约履行日。'
                     '历史里的明天、后天按原记录日期解释；跨日约定用明确的第N日，正文与facts保持一致。'
                     '已知对象的归属地点不能随当前场景移动；未确认的计划不当作已完成，日期或地点有冲突时先核实。')
    lines += narration.prompt_lines(room)
    directive = hosted_data(room).get("directive")
    if directive and not narration.is_legacy_directive(directive):    # an old table's world style is read as its improv
        lines.append("主持人指引（优先遵循）：" + directive)
    if note:
        lines.append("主持人审稿意见（本次重写必须遵循）：" + note[:500])
    lines += extra or []
    return "\n".join(lines)


def receipt_notes(receipt: dict[str, Any] | None) -> list[str]:
    """A teammate's hand and an all-in bet change how a check reads; the narration has to say so."""
    if not receipt:
        return []
    lines = []
    if receipt.get('settled_items'):
        lines.append('本轮机械回执的settled_items是平台已经结算的物品消耗，actor.items也是结算后的背包。'
                     '正文只叙述这次既成使用，ledger不得再次扣除；同种物品的额外转交留到另一次行动。')
    if receipt.get("kind") != "check":
        return lines
    aid = receipt.get("aid")
    if aid:
        lines.append(f"援手：{aid['name']}" + (f"（{aid['text']}）" if aid.get("text") else "") + f"协助了这次检定，修正 {aid['bonus']:+d}；"
                     + (f"两人的羁绊（{aid['bond']}）让这次配合格外默契；" if aid.get("bond") else "")
                     + ("检定成功，写出两人配合的样子。" if receipt.get("success") else f"检定失败，{aid['name']}也被卷进了后果。"))
    if receipt.get("all_in"):
        lines.append("孤注一掷：" + ("成功，按大成功的效果来写，收获比平时更多。" if receipt.get("success")
                                  else "失败，后果比平时更重，角色受了伤。"))
    flash = receipt.get("flashback")
    if flash:
        lines.append(f"闪回兑现：之前补写的回忆（{flash['text']}）在这次检定里派上了用场，修正 {flash['bonus']:+d}；正文里点出这层准备。")
    trait = receipt.get("trait")
    if trait:
        effect = "帮了忙" if trait["bonus"] > 0 else "拖了后腿" if trait["bonus"] < 0 else "有利有弊，正好抵消"
        lines.append(f"特质：{trait['name']}" + (f"（{trait['text']}）" if trait.get("text") else "")
                     + f"在这次检定里{effect}，修正 {trait['bonus']:+d}；正文里可以带一笔这个性格。")
    return lines


def narrative_policy(room: sqlite3.Row) -> dict[str, Any] | None:
    """The engine's length-and-style policy, only once the table has a length."""
    return narration.policy(room, shared.world(room)["pack"].get("style") or "")


def dated_facts(c: sqlite3.Connection, room_id: str) -> list[dict[str, Any]]:
    """Project committed memory with its original story time/place; never edit the source facts."""
    sources = {}
    scene = None
    for turn in c.execute("SELECT receipt_json,narrative_json,data_json FROM turns WHERE room_id=? AND state='done' ORDER BY rowid", (room_id,)):
        receipt = loads(turn['receipt_json'], {}) or {}
        progress = (loads(turn['narrative_json'], {}) or {}).get('progress', {})
        data = loads(turn['data_json'], {})
        scene = progress.get('scene') or data.get('narration_scene') or scene
        start, end = data.get('narration_clock'), progress.get('clock')
        def stamp(value):
            return f"第 {value['day']} 日 · {('清晨','白天','傍晚','夜晚')[value['slot']]}"
        tags = []
        if start and end:
            tags.append('记录回合：' + stamp(start) + (' → ' + stamp(end) if end != start else ''))
        if scene and scene.get('title'):
            tags.append('记录场景：' + scene['title'])
        if receipt.get('receipt_ref') and tags:
            sources[receipt['receipt_ref']] = '〔' + '；'.join(tags) + '〕'
    return [{"fact_ref": r["fact_ref"], "kind": r["kind"], "subject_ref": r["subject_ref"],
             "text": sources.get(r['source_receipt_ref'], '') + continuity.clean_fact(r['text']), "source_receipt_ref": r["source_receipt_ref"]}
            for r in c.execute("SELECT * FROM facts WHERE room_id=? ORDER BY created_at,rowid", (room_id,))]


def build_context(c: sqlite3.Connection, room: sqlite3.Row, actor: sqlite3.Row, action: str,
                  receipt: dict[str, Any] | None, note: str = "", extra: list[str] | None = None) -> dict[str, Any]:
    action = action[:2000]
    facts = dated_facts(c, room['id'])
    if len(facts) > 2000:
        # Match the engine's literal relevance/recency ranking for its input ceiling only.
        # It still owns the final 24-fact / 12000-character selection; history stays whole.
        terms = set(re.findall(r'[\w]{2,12}', action))
        terms.update(action[index:index+2] for index in range(len(action)-1) if not action[index:index+2].isspace())
        ranked = sorted(enumerate(facts), key=lambda item: (sum(term in item[1]['text'] for term in terms), item[0]),
                        reverse=True)
        facts = [fact for _, fact in sorted(ranked[:2000])]
    npcs = [{"npc_ref": r["npc_ref"], "name": r["name"], "description": r["description"], "motivation": r["motivation"]}
            for r in c.execute("SELECT * FROM npcs WHERE room_id=? ORDER BY updated_at", (room["id"],))]
    scene = loads(room["scene_json"], {})
    from . import rush
    party = rush.party_line(receipt) if receipt and receipt.get("rush") else None
    events = story_turns(c, room) + [table_notes(c, room, actor, note, (receipt or {}).get("kind") in NARRATOR_KINDS,
                                                 receipt_notes(receipt) + (extra or []), party)]
    context = {"brief": world_brief(shared.world(room), lifecycle.current_act(room)),
               "scene": {"title": scene.get("title") or "当前场景",
                                                                 "description": scene.get("description") or ""},
               "goal": room["goal"] or "", "actor": actor_view(room, actor), "npcs": npcs, "facts": facts,
               "recent_events": events, "action": action, "mechanical_receipt": receipt,
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
        text, closing = pacing.closing_name(text)
        item = {"label": LABELS[index], "text": text, "check": dict(check)}
        if closing:
            item["closing"] = closing      # a "收束：…" option: picking it proposes winding the story down
        result.append(item)
    return result


def check_label(rules: dict[str, Any], check: dict[str, Any]) -> str:
    if check.get("kind") == "check":
        attr = rules["attributes"].get(check["attribute_ref"], check["attribute_ref"])
        cost = "，失败受伤" if check.get("failure_cost") == "harm" else ""
        return f"〔{attr}·{DIFFICULTY_LABELS.get(check['difficulty'], check['difficulty'])}{cost}〕"
    if check.get("kind") == "recover":
        return "〔休整〕"
    return ""


def turn_prompt(app: "LiteApp", room: sqlite3.Row, turn: sqlite3.Row, actor: sqlite3.Row) -> Any:
    from . import rush
    if rush.is_round(turn):
        return rush.prompt(app, room, turn)
    rules = shared.rules(room)
    scores, base = loads(actor["attributes_json"], {}), rules["modifier"]

    def chance(check: dict[str, Any]) -> int | None:
        """The actor's odds on a check option before any preparation; the image card shows them."""
        if check.get("kind") != "check" or check.get("difficulty") not in rules["difficulties"]:
            return None
        mod = (scores.get(check.get("attribute_ref"), base["baseline"]) - base["baseline"]) // base["divisor"]
        trait = trait_bonus(room, actor, check.get("attribute_ref") or "", check["difficulty"])
        mod += trait["bonus"] if trait else 0
        return success_chance(mod, rules["difficulties"][check["difficulty"]])

    closing = pacing.closing_open(room)
    choices = [{"label": c["label"], "text": c["text"], "tag": messages.check_tag(rules, c["check"]), "chance": chance(c["check"]),
                **({"closing": c["closing"]} if closing and c.get("closing") else {})}
               for c in loads(turn["choices_json"], [])]
    minutes = None
    if turn["deadline_at"]:
        minutes = max(1, round((datetime.fromisoformat(turn["deadline_at"]) - datetime.now(UTC)).total_seconds() / 60))
    ready = [f"{e['name']} {loadout.effect_text(e)}" for e in loadout.entries(room, actor) if e["usable"]]
    with app.store.read() as c:
        following, _ = next_actor(c, room["id"], actor)
        others = others_guide(c, room, actor, turn)
    upcoming = shared.actor_label(following) if following is not None and following["id"] != actor["id"] else ""
    return messages.turn_prompt(shared.actor_label(actor), actor["user_name"], actor["user_id"], turn["round"], choices,
                                rules.get("action_mode", "hybrid"), minutes, loadout=ready, upcoming=upcoming,
                                tips=bool(loads(turn["data_json"], {}).get("tips")), others=others,
                                pace=pacing.band(room, turn["round"]))


def others_guide(c: sqlite3.Connection, room: sqlite3.Row, actor: sqlite3.Row | None, turn: sqlite3.Row) -> dict[str, Any]:
    """What teammates and the gallery can do during this turn, from the table as it stands."""
    from . import rush
    in_rush = rush.is_round(turn)
    crew = not in_rush and actor is not None and any(a["id"] != actor["id"] for a in eligible_actors(c, room["id"]))
    seated = c.execute("SELECT COUNT(*) FROM actors WHERE room_id=? AND presence<>'left'", (room["id"],)).fetchone()[0]
    seats = 0 if shared.table_data(room).get("seating_locked") else max(0, room["seat_cap"] - seated)
    aid = (loads(turn["data_json"], {}).get("aid") or {}).get("name", "")
    return messages.others_guide(shared.actor_label(actor) if actor is not None else "", crew=crew, aid=aid, seats=seats,
                                 heckles=banter._heckles_left(room) > 0, bets=not in_rush)


def status_message(room: sqlite3.Row, actor: sqlite3.Row, round_number: int, action: str, receipt: dict[str, Any],
                   announce: str = "") -> Any:
    pack = shared.world(room)["pack"]
    archetype = next((a["name"] for a in pack["archetypes"] if a["id"] == actor["archetype_id"]), "")
    changes = receipt.get("resource_changes") or {}
    after = receipt.get("resources_after") or {}
    meters = [(r["name"], after.get(r["name"], r["initial"]), r["max"], changes.get(r["name"])) for r in pack["resources"]]
    return messages.action_status(shared.actor_label(actor), archetype, round_number, action, receipt, meters, announce=announce,
                                  wallet=economy.wallet_view(room, actor))


def open_turn(app: "LiteApp", c: sqlite3.Connection, room: sqlite3.Row, actor: sqlite3.Row | None,
              choices: list[dict[str, Any]], round_number: int, *, cheat_sheet: bool = True) -> sqlite3.Row | None:
    c.execute("UPDATE turns SET state='superseded',updated_at=? WHERE room_id=? AND state IN ('awaiting','narration_failed','review')",
              (now(), room["id"]))
    if actor is None:
        return None
    turn_id = new_id("turn")
    # The player's first turn at this table carries a short cheat sheet (read by turn_prompt, which never writes).
    actor_data = loads(c.execute("SELECT data_json FROM actors WHERE id=?", (actor["id"],)).fetchone()["data_json"], {})
    tips = cheat_sheet and not actor_data.get("tips_seen")
    if tips:
        c.execute("UPDATE actors SET data_json=? WHERE id=?", (dumps({**actor_data, "tips_seen": True}), actor["id"]))
    c.execute("INSERT INTO turns(id,room_id,round,actor_id,state,choices_json,deadline_at,data_json,created_at,updated_at) "
              "VALUES(?,?,?,?,'awaiting',?,?,?,?,?)", (turn_id, room["id"], round_number, actor["id"], dumps(choices),
                                                      _deadline(app, room), dumps({"tips": True} if tips else {}), now(), now()))
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


def mechanics(room: sqlite3.Row, actor: sqlite3.Row, intent: dict[str, Any], prepared: list[dict[str, Any]] | None = None,
              *, aid: dict[str, Any] | None = None, all_in: bool = False,
              flashback: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Platform dice and costs for one intent → (receipt, new actor loadout document).

    A preparation is spent first (its modifiers join a check); failure costs and rest effects follow.
    A teammate's aid adds its bonus to a check; an all-in bet makes a failed check cost harm.
    """
    rules = shared.rules(room)
    pack = shared.world(room)["pack"]
    doc = loadout.state(actor)
    before = {k: v["current"] for k, v in doc["resources"].items()}
    items_before = {ref: item['quantity'] for ref, item in doc['items'].items()}
    bonus = 0
    receipt: dict[str, Any] = {"receipt_ref": new_id("receipt"), "kind": intent["kind"], "actor_ref": actor["id"]}
    if prepared:
        doc, summary = loadout.plan(room, doc, prepared, attribute=intent.get("attribute_ref") if intent["kind"] == "check" else None)
        bonus = summary["modifier"]
        receipt["prepared"] = [{"name": p["name"], "modifier": p["modifier"]} for p in prepared]
        spent = [{'actor_ref': actor['id'], 'item_ref': ref, 'delta': item['quantity'] - items_before.get(ref, 0)}
                 for ref, item in doc['items'].items() if item['quantity'] < items_before.get(ref, 0)]
        if spent:
            receipt['settled_items'] = spent
    resources = doc["resources"]
    deltas: dict[str, int] = {}
    if intent["kind"] == "check":
        attr = intent["attribute_ref"]
        score = loads(actor["attributes_json"], {}).get(attr, rules["modifier"]["baseline"])
        base = (score - rules["modifier"]["baseline"]) // rules["modifier"]["divisor"]
        if aid:
            bonus += aid["bonus"]
            receipt["aid"] = dict(aid)
        if flashback:
            bonus += int(flashback["bonus"])
            receipt["flashback"] = dict(flashback)
        trait = trait_bonus(room, actor, attr, intent["difficulty"], aid=bool(aid), all_in=all_in,
                            resources={k: v["current"] for k, v in resources.items()})
        if trait:
            bonus += trait["bonus"]
            receipt["trait"] = trait
        mod = base + bonus
        dc = rules["difficulties"][intent["difficulty"]]
        roll = roll_check(mod, dc)
        receipt.update(attribute_ref=attr, attribute=rules["attributes"][attr], difficulty=intent["difficulty"], dc=dc,
                       face=roll.face, modifier=mod, attribute_modifier=base, total=roll.total,
                       outcome="critical" if roll.critical else "fumble" if roll.fumble else "success" if roll.success else "failure",
                       success=roll.success, failure_cost=intent.get("failure_cost") or "setback")
        if all_in:
            receipt["all_in"] = True
            if not roll.success:
                receipt["failure_cost"] = "harm"
        if not roll.success and receipt["failure_cost"] == "harm":
            deltas = dict(rules["failure_costs"].get("harm") or {})
    elif intent["kind"] == "recover":
        rest = rules.get("recovery", {}).get("rest", {})
        deltas = {**rest.get("cost", {})}
        for ref, value in rest.get("effect", {}).items():
            deltas[ref] = deltas.get(ref, 0) + value
    if all_in and intent["kind"] != "check":
        receipt["all_in_unused"] = True        # nothing was rolled: the bet stays for later this act
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
    if receipt.get("aid"):
        parts.append(f"援手：{receipt['aid']['name']} {receipt['aid']['bonus']:+d}" + ("（羁绊）" if receipt["aid"].get("bond") else ""))
    if receipt.get("flashback"):
        parts.append(f"闪回 {receipt['flashback']['bonus']:+d}")
    if receipt.get("trait"):
        parts.append(f"特质 {receipt['trait']['name']} {receipt['trait']['bonus']:+d}")
    if receipt.get("all_in"):
        parts.append("孤注")
    changes = receipt.get("resource_changes") or {}
    if changes:
        parts.append("　".join(f"{k} {v:+d}" for k, v in changes.items()))
    if receipt.get("exhausted"):
        parts.append("（" + "、".join(receipt["exhausted"]) + "已耗尽）")
    return "".join(parts[:1]) + ("　" + "　".join(parts[1:]) if len(parts) > 1 else "")


# ---------------------------------------------------------------- resolution
def _require_active_turn(c: sqlite3.Connection, room_id: str, turn_id: str,
                         states: tuple[str, ...] = ("resolving",)) -> tuple[sqlite3.Row, sqlite3.Row]:
    """Check the authoritative lifecycle again after an asynchronous model call."""
    room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    turn = c.execute("SELECT * FROM turns WHERE id=? AND room_id=?", (turn_id, room_id)).fetchone()
    if room is None or room["state"] not in ("running", "paused"):
        raise UserError("团桌已经结束或关闭，旧的模型结果未提交。")
    if turn is not None and turn["state"] == "done":
        raise UserError("这段正文已经发布，不能重复提交。")
    if turn is None or turn["state"] not in states:
        raise UserError("这个回合已经结束或被替换，旧的模型结果未提交。")
    return room, turn


async def narrate(app: "LiteApp", room_id: str, turn_id: str, *, advance: bool = True, note: str = "") -> Reply:
    """Ask the engine to narrate a committed receipt, then commit story and open the next turn.

    With review on, the draft goes to the host's private chat first (state 'review') and waits
    for /团 主持 发布 or /团 主持 重写; note carries the host's rewrite request.
    """
    with app.store.read() as c:
        room, turn = _require_active_turn(c, room_id, turn_id)
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
        # Lines, heckles, the X card and secret notes left since the last narration go with this one.
        extra, mark = banter.story_notes(room)
        extra += economy.story_notes(room)      # what the last 整备 bought, sold and handed over
        extra += pacing.story_notes(room, turn["round"])
        archive = continuity.sources(c, room)
        extra.append(continuity.prompt(archive, turn['action_text']))
        context = build_context(c, room, actor, turn["action_text"], loads(turn["receipt_json"]), note, extra)
        context['clock'] = loads(room['clock_json'])
        ledger_options = economy.ledger_options(c, room)
        if ledger_options is not None:
            context["economy_options"] = ledger_options
        names = {a["id"]: shared.actor_label(a) for a in c.execute("SELECT * FROM actors WHERE room_id=?", (room_id,))}
        reviewer = shared.private_umo(c, room["platform"], room["host_user_id"]) if hosted_data(room).get("review") else None
    with app.store.tx() as c:
        data = loads(c.execute("SELECT data_json FROM turns WHERE id=?", (turn_id,)).fetchone()["data_json"], {})
        c.execute("UPDATE turns SET data_json=? WHERE id=?", (dumps({**data, "banter_mark": mark,
                                                                    "narration_clock": context['clock'],
                                                                    "narration_chapter": room['chapter'],
                                                                    "narration_scene": context['scene']}), turn_id))
        turn = c.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
    # Group actions and host advances return the turn to the actor who was waiting.
    advance = advance and not loads(turn["data_json"], {}).get("resume_actor")
    # One automatic second try: a network blip or one malformed reply should not stop the table.
    for attempt in range(2):
        with app.store.read() as c:
            _require_active_turn(c, room_id, turn_id)
        try:
            result = await app.engine.call("narrate_committed", {"context": context}, room_id=room_id, umo=room["umo"],
                                           rules=shared.rules(room), continuity_sources=archive)
            break
        except EngineInputError:
            # Settlement is already committed. Invalid input cannot be repaired by re-rolling
            # or another model attempt; keep the receipt, draft and special-turn markers.
            with app.store.tx() as c:
                _, turn = _require_active_turn(c, room_id, turn_id)
                c.execute("UPDATE turns SET state='narration_failed',updated_at=? WHERE id=?", (now(), turn_id))
            logger.exception("321Roll Lite: narration input rejected for room %s turn %s", room_id, turn_id)
            kind = (loads(turn["receipt_json"], {}) or {}).get("kind")
            if kind == "finale":
                return Reply(status="error").say(messages.notice(
                    "终章输入校验失败", "终章输入未通过引擎校验，本次未自动重试，故事停在终章前。",
                    "请联系管理员检查输入问题；修复后主持人发送 /团 主持 重试 重新写终章，"
                    f"或 /团 主持 跳过 不写终章、直接请大家写尾声；主持人 {PLAYER_RETRY_AFTER_MINUTES} 分钟内"
                    "没处理的话，在座的玩家也可以发送 /团 重试"))
            skip = ("不写这段、直接轮到 " + shared.actor_label(actor)) if kind in NARRATOR_KINDS else "直接轮到下一位"
            return Reply(status="error").say(messages.notice(
                "正文输入校验失败", "正文输入未通过引擎校验，本次未自动重试。骰果和资源变化已经保存，故事停在这里等主持人处理。",
                f"请联系管理员检查输入问题；修复后主持人发送 /团 主持 重试 重新生成正文，或 /团 主持 跳过 {skip}；"
                f"主持人 {PLAYER_RETRY_AFTER_MINUTES} 分钟内没处理的话，在座的玩家也可以发送 /团 重试"))
        except EngineCallFailed as exc:
            with app.store.read() as c:
                _require_active_turn(c, room_id, turn_id)
            if attempt == 0:
                logger.warning("321Roll Lite: narration for turn %s failed (%s); trying once more", turn_id, exc.category)
                await asyncio.sleep(AUTO_RETRY_DELAY)
                continue
            with app.store.tx() as c:
                c.execute("UPDATE turns SET state='narration_failed',updated_at=? WHERE id=?", (now(), turn_id))
            reason = ("模型暂时连不上。" if exc.category == "provider_unavailable" else
                      "历史日期或物品来历未通过核对。" if exc.category.startswith('continuity.') else "模型几次回复都不合格式。")
            kind = (loads(turn["receipt_json"], {}) or {}).get("kind")
            if kind == "finale":
                return Reply(status="error").say(messages.notice(
                    "终章没写出来", reason + "已经自动重试过一次，故事停在终章前。",
                    f"主持人发送 /团 主持 重试 重新写终章，或 /团 主持 跳过 不写终章、直接请大家写尾声；主持人 "
                    f"{PLAYER_RETRY_AFTER_MINUTES} 分钟内没处理的话，在座的玩家也可以发送 /团 重试"))
            skip = ("不写这段、直接轮到 " + shared.actor_label(actor)) if kind in NARRATOR_KINDS else "直接轮到下一位"
            return Reply(status="error").say(messages.notice(
                "这一段正文没写出来", reason + "已经自动重试过一次。骰果和资源变化已经保存，故事停在这里等主持人处理。",
                f"主持人发送 /团 主持 重试 重新生成正文，或 /团 主持 跳过 {skip}；主持人 {PLAYER_RETRY_AFTER_MINUTES} 分钟内"
                "没处理的话，在座的玩家也可以发送 /团 重试。具体原因可在后台“运行”页查看"))
    proposal = result["proposal"]
    with app.store.tx() as c:
        _, turn = _require_active_turn(c, room_id, turn_id)
        data = {**loads(turn['data_json'], {}), 'continuity_approval': result['continuity_approval']}
        c.execute('UPDATE turns SET data_json=? WHERE id=?', (dumps(data), turn_id))
    if reviewer:
        with app.store.tx() as c:
            room, turn = _require_active_turn(c, room_id, turn_id)
            data = {**loads(turn["data_json"], {}), "advance": advance}
            c.execute("UPDATE turns SET state='review',narrative_json=?,data_json=?,updated_at=? WHERE id=?",
                      (dumps(proposal), dumps(data), now(), turn_id))
        await app.notifier.send(reviewer, draft_card(room, turn, actor, proposal, names))
        return Reply().say(messages.notice("正文已写好，正在等主持人审阅", "主持人确认后会发到群里。"))
    try:
        return await commit_narration(app, room_id, turn_id, proposal, advance)
    except UserError:
        with app.store.tx() as c:
            c.execute("UPDATE turns SET state='narration_failed',updated_at=? WHERE id=? AND state='resolving'",
                      (now(), turn_id))
        raise


def draft_card(room: sqlite3.Row, turn: sqlite3.Row, actor: sqlite3.Row, proposal: dict[str, Any],
               names: dict[str, str] | None = None) -> Any:
    from ..render import Msg
    rules = shared.rules(room)
    choices = make_choices(proposal["suggestions"], proposal.get("suggestion_checks"))
    m = Msg().title("正文草稿 · 待审阅", f"{room['title'].split(' · ')[0]}　第 {turn['round']} 轮　{shared.actor_label(actor)}")
    m.gap().para(narration_text(proposal)).gap()
    m.items([f"**{ch['label']}.** {ch['text']}" + (f"　〔{messages.check_tag(rules, ch['check'])}〕"
                                                   if messages.check_tag(rules, ch["check"]) else "") for ch in choices])
    ledger = proposal.get("ledger") or []
    if ledger:
        m.gap().caption("钱物变化（发布时生效）")
        m.items([f"**{i}.** {economy.describe_entry(room, e, names or {})}（{e['reason']}）" for i, e in enumerate(ledger, 1)])
        return m.gap().hint("发送 /团 主持 发布 公开到群里，/团 主持 重写 意见 按意见重新生成；"
                            "不认可某一笔钱物变化，发送 /团 主持 记账 撤回 序号")
    return m.gap().hint("发送 /团 主持 发布 公开到群里，或 /团 主持 重写 意见 按意见重新生成")


async def commit_narration(app: "LiteApp", room_id: str, turn_id: str, proposal: dict[str, Any], advance: bool) -> Reply:
    """Store the narration, apply queued host adjustments and open the next turn.

    Pacing may instead hand the table to the world (a push or the finale, written right after this one)
    or open the next act; the finale itself opens the epilogues instead of a turn.
    """
    # Draft edits and intervening public history invalidate the previous check.
    with app.store.read() as c:
        room, turn = _require_active_turn(c, room_id, turn_id, ("resolving", "review"))
        archive = continuity.sources(c, room)
        checked = continuity.approval(proposal, archive)
        prior = loads(turn['data_json'], {}).get('continuity_approval')
    if prior != checked:
        context = {'action': turn['action_text'], 'clock': loads(turn['data_json'], {}).get('narration_clock')}
        try:
            findings = await continuity.review(app, room_id, room['umo'], context, proposal, archive, new_operation_ref('continuity'))
        except EngineCallFailed as exc:
            raise UserError('历史连续性核对暂未完成，请稍后重试发布。') from exc
        if findings:
            raise UserError('历史日期或物品来历有冲突，请重写后再发布：' + continuity.rejection(findings))
    text = narration_text(proposal)
    choices = make_choices(proposal["suggestions"], proposal.get("suggestion_checks"))
    plan = pacing.Plan()
    special: str | None = None            # a narrator turn written right after this narration
    voided: str | None = None             # a vote the finale cut short
    epilogues = None
    from . import rush
    with app.store.tx() as c:
        room, turn = _require_active_turn(c, room_id, turn_id, ("resolving", "review"))
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
        receipt = loads(turn['receipt_json'], {}) or {}
        try:
            economy.reject_settled_items(proposal.get('ledger') or [], receipt)
        except ValueError as exc:
            raise UserError('本轮用物已经结算，这段正文又扣了同种物品，请重写后再发布。') from exc
        finale = receipt.get("kind") == "finale"
        source_chapter = loads(turn['data_json'], {}).get('narration_chapter', room['chapter'])
        if source_chapter != room['chapter']:
            raise UserError('正文生成后已经换幕，请重写这段正文后再发布。')
        if checked != continuity.approval(proposal, continuity.sources(c, room)):
            raise UserError('历史记录在核对后变化，请重新发布以再次核对日期和物品来历。')
        if 'clock' in proposal.get('progress', {}):
            source_clock = loads(turn['data_json'], {}).get('narration_clock')
            clock.commit(app, c, room, turn['actor_id'], source_clock, proposal['progress']['clock'], turn['action_text'])
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
        ledger = economy.apply_ledger(c, room, proposal.get("ledger") or [])
        if ledger:
            app.store.add_event(c, room_id, "system", "故事里的得失：" + "；".join(
                f"{x['who']} {x['name']} {x['delta']:+d}（{x['reason']}）" for x in ledger),
                data={'economy': 'story_ledger', 'turn': turn_id, 'clock': proposal.get('progress', {}).get('clock'),
                      'applied': ledger})
        economy.clear_notes(c, room_id)
        table_talk = banter.consume(c, room_id, loads(turn["data_json"], {}).get("banter_mark"))
        round_number = turn["round"]
        rushing = rush.is_round(turn) and rush.enabled(room)
        if rushing and advance:
            following, _ = next_actor(c, room_id, None)
            round_number += 1
        elif advance:
            following, wrapped = next_actor(c, room_id, actor)
            round_number += 1 if wrapped else 0
        else:
            following = c.execute("SELECT * FROM actors WHERE id=?", (loads(turn["data_json"], {}).get("resume_actor")
                                                                       or turn["actor_id"],)).fetchone()
        app.store.bump_room(c, room_id)
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        new_turn = None
        if finale:
            epilogues = pacing.finale_written(c, room, pacing.finale_title(room, receipt, proposal.get("suggestions") or []))
        else:
            new_scene = loads(room["scene_json"], {}).get("title", "")
            plan = pacing.after_narration(c, room, turn, round_number, bool(new_scene) and new_scene != old_scene,
                                          rushing=rushing and advance)
            room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
            pushing = bool(plan.push)
            if room["state"] == "running" and following is not None and (plan.finale is not None or pushing):
                special = pacing.narrator_turn(app, c, room, "finale" if plan.finale is not None else "pace_push", following,
                                               round_number, title=plan.finale, rounds=plan.push)
                if plan.finale is not None:
                    from .collaboration import void_open
                    voided = void_open(c, room_id)
            elif room["state"] in ("running", "paused"):
                # Paused while the story was being written: the next turn still opens (and waits) so its options survive.
                new_turn = (rush.open_round(app, c, room, choices, round_number) if rushing and advance else
                            open_turn(app, c, room, following, choices, round_number))
            if new_turn is None and special is None and room["state"] == "running":
                app.store.add_event(c, room_id, "system", "没有在场的玩家，故事停在这里。")
    scene_title = loads(room["scene_json"], {}).get("title", "")
    story = messages.narration(text, scene_title, "终章" if finale else act_heading)
    from ..worlds import scenes
    scenes.bind(story, room, tag=_art_tag(room))
    reply = Reply().say(story)
    for item in table_talk:
        reply.say(item)
    if adjusted:
        reply.say(messages.adjustments_applied(adjusted))
    if ledger:
        reply.say(messages.ledger_card(ledger, (economy.of_room(room) or {}).get("currency", "")))
    if epilogues is not None:
        return reply.say(epilogues)
    nearby = economy.new_place_shops(room, old_scene)
    outfitting = False
    if nearby and room["state"] == "running":
        money = economy.of_room(room)
        if money and money["auto_outfit"] and special is None:
            try:                           # the world opens 整备 by itself where there are shops
                reply.extend(economy.open_outfit(app, room_id, economy.OUTFIT_MINUTES, "走进有店的地点"))
                outfitting = True
            except UserError:
                pass
        if not outfitting:
            reply.say(messages.shops_nearby([s["name"] for s in nearby], scene_title))
    for card in plan.cards:
        reply.say(card)
    if plan.push_note and room["state"] == "running":
        reply.say(messages.world_push(plan.push_note, scene_title, "全队", rush=True))
    if plan.act_change is not None and room["state"] == "running":
        reply.extend(await change_act(app, room_id, plan.act_change, None if not lifecycle.improvises(room) else {},
                                      prompt=False))
        with app.store.read() as c:
            room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    if special is not None:
        if plan.finale is not None:
            reply.say(messages.notice("正在写终章", (f"结局：{plan.finale}。" if plan.finale else "")
                                      + "收尾的几轮已经走完，AI 正在写最后一段正文；写完后每位玩家留一句尾声。"
                                      + pacing.finale_vote_note(voided)))
        else:
            reply.say(messages.world_push(plan.push, scene_title, shared.actor_label(following)))
        reply.extend(await narrate(app, room_id, special, advance=False))
        if advance and round_number != turn["round"] and plan.finale is None:
            from . import collaboration
            reply.extend(await collaboration.after_round(app, room_id, round_number))
        return reply
    if new_turn is not None and room["state"] == "paused":
        reply.say(f"故事正在暂停：下一轮由 {shared.actor_label(following)} 行动，主持人发送 /团 恢复 打开准备大厅后继续。")
    elif new_turn is not None:
        if not outfitting:                 # closing 整备 shows the waiting turn again
            with app.store.read() as c:
                new_turn = c.execute("SELECT * FROM turns WHERE id=?", (new_turn["id"],)).fetchone()
            reply.say(turn_prompt(app, room, new_turn, following))
        if advance and round_number != turn["round"]:
            from . import collaboration
            reply.extend(await collaboration.after_round(app, room_id, round_number))
    return reply


CLARIFY_GRACE = timedelta(minutes=2)
# Sent with the answer to this turn's question when the model asks back regardless: the player is not asked twice.
FIRM_NOTE = ("\n（玩家已经回答过追问，本次不得 clarify：按最合理的理解处理。行动有失败可能或风险时必须选 check，"
             "按危险程度定属性、难度和 failure_cost；只有毫无阻碍的小动作才选 narrative。）")


def fallback_check(room: sqlite3.Row, actor: sqlite3.Row, turn: sqlite3.Row, action: str) -> dict[str, Any]:
    """A standard check for an answered action the model still would not read.

    The attribute comes from this turn's checked option closest in wording to the action, else the
    character's best attribute; a free action is never waved through without dice.
    """
    rules = shared.rules(room)
    options = [c for c in loads(turn["choices_json"], [])
               if (c.get("check") or {}).get("kind") == "check" and c["check"].get("attribute_ref")]
    words = set(re.sub(r"[\s，。、！？；：“”‘’（）()…—,.!?;:]", "", action))
    if options:
        attribute = max(options, key=lambda c: len(words & set(c["text"])))["check"]["attribute_ref"]
    else:
        scores = loads(actor["attributes_json"], {})
        attribute = max(scores, key=lambda k: scores[k]) if scores else ""
    levels = rules["difficulties"]
    difficulty = "standard" if "standard" in levels else sorted(levels, key=levels.get)[len(levels) // 2]
    costs = rules.get("failure_costs") or {"setback": {}}
    return {"kind": "check", "attribute_ref": attribute, "difficulty": difficulty,
            "failure_cost": "setback" if "setback" in costs else next(iter(costs)),
            "reason": "玩家已回答追问，按最接近的属性检定", "clarification": "", "risk_response": ""}


async def firm_intent(app: "LiteApp", room: sqlite3.Row, actor: sqlite3.Row, turn: sqlite3.Row,
                      context: dict[str, Any], action: str) -> dict[str, Any]:
    """The player answered the question and the model asked again: one firmer request, then a platform check."""
    firm = {**context, "action": (str(context["action"]) + FIRM_NOTE)[:2000]}
    try:
        result = await app.engine.call("propose_intent", {"context": firm}, room_id=room["id"], umo=room["umo"],
                                       rules=shared.rules(room))
        if result["proposal"]["kind"] != "clarify":
            return result["proposal"]
        logger.info("321Roll Lite: the model asked back twice after an answer; using a standard check")
    except EngineCallFailed as exc:
        logger.warning("321Roll Lite: second intent request failed (%s); using a standard check", exc.user_message)
    return fallback_check(room, actor, turn, action)


def _mark_act(c: sqlite3.Connection, actor_id: str, key: str, act: int) -> None:
    """Remember the act a once-per-act play (aid, all-in) was spent in."""
    data = loads(c.execute("SELECT data_json FROM actors WHERE id=?", (actor_id,)).fetchone()["data_json"], {})
    c.execute("UPDATE actors SET data_json=? WHERE id=?", (dumps({**data, key: act}), actor_id))


def _share_failure(c: sqlite3.Connection, room: sqlite3.Row, helper_id: str, receipt: dict[str, Any]) -> dict[str, int]:
    """The helper's aid is spent with this check; a failure that costs harm hurts the helper too."""
    _mark_act(c, helper_id, "aid_act", room["act"])
    if receipt["success"] or receipt["failure_cost"] != "harm":
        return {}
    helper = c.execute("SELECT * FROM actors WHERE id=?", (helper_id,)).fetchone()
    doc = loadout.state(helper)
    applied = apply_deltas(doc["resources"], dict(shared.rules(room)["failure_costs"].get("harm") or {}))
    loadout.save(c, helper_id, doc)
    names = {r["id"]: r["name"] for r in shared.world(room)["pack"]["resources"]}
    return {names.get(k, k): v for k, v in applied.items()}


def _ask_back(app: "LiteApp", room_id: str, turn_id: str, intent: dict[str, Any], action: str,
              asked: dict[str, Any] | None) -> Reply:
    """The model asked back (clarify) or refused (impossible): the turn waits for the same player again.

    One clarifying question per turn: the answer goes back with the original action, and a second
    question re-sends this turn's options instead of asking again.  The timer keeps at least two
    minutes so an answer is not overtaken by the timeout pick.
    """
    question = (intent.get("clarification") or intent.get("reason") or "").strip()
    again = intent["kind"] == "clarify" and bool(asked)
    with app.store.tx() as c:
        _, turn = _require_active_turn(c, room_id, turn_id)
        data = loads(turn["data_json"], {})
        if intent["kind"] == "clarify":
            data["clarify"] = {"spent": True} if again else {"action": action[:500], "question": question[:300]}
        else:                                   # refused outright: the next action starts fresh
            data.pop("clarify", None)
        deadline = turn["deadline_at"]
        if deadline:
            deadline = max(datetime.fromisoformat(deadline), datetime.now(UTC) + CLARIFY_GRACE).isoformat(timespec="seconds")
        c.execute("UPDATE turns SET state='awaiting',data_json=?,deadline_at=?,updated_at=? WHERE id=?",
                  (dumps(data), deadline, now(), turn_id))
        turn = c.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
    minutes = None
    if deadline:
        minutes = max(1, round((datetime.fromisoformat(deadline) - datetime.now(UTC)).total_seconds() / 60))
    mode = shared.rules(room).get("action_mode", "hybrid")
    has_choices = bool(loads(turn["choices_json"], [])) and mode != "dialogue_only"
    reply = Reply().say(messages.ask_back(shared.actor_label(actor), actor["user_name"], actor["user_id"], question,
                                          intent["kind"], again=again, minutes=minutes, choices=has_choices))
    if again:
        reply.say(turn_prompt(app, room, turn, actor))
    return reply


async def resolve(app: "LiteApp", room_id: str, turn_id: str, action: str, intent: dict[str, Any] | None,
                  *, announce: str = "", prepared: list[dict[str, Any]] | None = None,
                  early: Callable[[Any], Awaitable[Any]] | None = None, all_in: bool = False) -> Reply:
    """Resolve the awaiting turn: intent (model unless given) → dice → narration.

    With early, the dice and status go out as soon as they are committed and the reply carries
    only what follows the narration call, so players see the roll while the story is written.
    """
    async with app.lock(room_id):
        with app.store.tx() as c:
            turn = c.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
            if turn is None or turn["state"] != "awaiting":
                raise UserError("这个回合已经在处理或已结束。")
            quota.require_round(app, c, c.execute("SELECT umo FROM rooms WHERE id=?", (room_id,)).fetchone()["umo"])
            actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
            lifecycle.auto_snapshot(c, room_id, f"第 {turn['round']} 轮 · {shared.actor_label(actor)} 行动前")
            # A free action written after this turn's clarifying question answers it: the model reads both.
            asked = loads(turn["data_json"], {}).get("clarify") if intent is None else None
            if asked and asked.get("question"):
                action = f"{asked['action']}（补充：{action}）"[:2000]
            c.execute("UPDATE turns SET state='resolving',action_text=?,updated_at=? WHERE id=?", (action, now(), turn_id))
            room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
            context = build_context(c, room, actor, action, None)
            if asked and asked.get("question"):
                context["action"] = (action + f"\n（主持刚才追问：{asked['question']}；括号里的补充就是玩家的回答）")[:2000]
        try:
            if intent is None:
                try:
                    result = await app.engine.call("propose_intent", {"context": context}, room_id=room_id, umo=room["umo"],
                                                   rules=shared.rules(room))
                except EngineCallFailed as exc:
                    with app.store.tx() as c:
                        _require_active_turn(c, room_id, turn_id)
                        c.execute("UPDATE turns SET state='awaiting',updated_at=? WHERE id=?", (now(), turn_id))
                    raise UserError("行动理解失败：" + exc.user_message + " 你可以换个说法再试，或选择 A–D。") from exc
                with app.store.read() as c:
                    _require_active_turn(c, room_id, turn_id)
                intent = result["proposal"]
                if intent["kind"] == "clarify" and asked and asked.get("question"):
                    intent = await firm_intent(app, room, actor, turn, context, action)
                if intent["kind"] in ("clarify", "impossible"):
                    return _ask_back(app, room_id, turn_id, intent, action, asked)
            flash_review = await ties.review_for_check(app, room, actor, action, intent)
            with app.store.tx() as c:
                fresh_room, turn = _require_active_turn(c, room_id, turn_id)
                if fresh_room['chapter'] != room['chapter']:
                    raise UserError('行动理解期间已经换幕，请按当前剧情重新行动。')
                room = fresh_room
                actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
                flash_bonus, flash_notice = ties.checked_bonus(app, c, room, actor, flash_review)
                turn_data = loads(c.execute("SELECT data_json FROM turns WHERE id=?", (turn_id,)).fetchone()["data_json"], {})
                offer = turn_data.get("aid")
                aid = None
                if offer:
                    bonus, bond = ties.aid_bonus(room, offer["actor_id"], actor["id"])
                    aid = {"name": offer["name"], "text": offer.get("text", ""), "bonus": bonus, **({"bond": bond} if bond else {})}
                receipt, doc = mechanics(room, actor, intent, prepared, aid=aid, all_in=all_in, flashback=flash_bonus)
                if flash_notice:
                    receipt['flashback_notice'] = flash_notice
                receipt["intent_reason"] = intent.get("reason", "")
                loadout.save(c, actor["id"], doc)
                ties.spend(c, actor["id"], receipt)
                guessed = wager.settle(c, room_id, turn_data.get("bets") or {}, receipt)
                if guessed:
                    receipt["wager"] = guessed
                if receipt.get("all_in"):
                    _mark_act(c, actor["id"], "all_in_act", room["act"])
                if receipt.get("aid"):
                    receipt["aid"]["changes"] = _share_failure(c, room, offer["actor_id"], receipt)
                elif offer:
                    receipt["aid_unused"] = offer["name"]      # no check: the helper keeps this act's aid
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
        status = status_message(room, actor, turn["round"], action, receipt, announce)
        reply = Reply()
        if early is None:
            reply.say(status)
        else:
            try:
                await early(status)
            except Exception:
                logger.exception("321Roll Lite could not send the roll before the narration")
                reply.say(status)
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
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        if room["state"] not in ("running", "paused"):
            raise UserError("团桌已经结束或关闭，开场未提交。")
        c.execute("UPDATE rooms SET scene_json=?,goal=? WHERE id=?", (dumps(proposal["scene"]), proposal["goal"], room_id))
        pacing.start(c, room_id)
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
    from ..worlds import scenes
    reply = Reply().say(scenes.bind(messages.act_card(shared.world(room)["pack"]["title"], room["act"], act["title"], act["lead"],
                                          world=room["world_id"], art="cover", total=lifecycle.acts_total(room)), room, "cover"))
    reply.say(scenes.bind(messages.scene_card(proposal["scene"]["title"], proposal["scene"]["description"], proposal["goal"],
                                  [(n["name"], n["description"]) for n in proposal["npcs"]]), room, tag=_art_tag(room, act["title"])))
    if turn is not None:
        reply.say(turn_prompt(app, room, turn, first))
    if lifecycle.improvises(room):
        reply.say(messages.notice("核心版", "预设剧情只写到第一幕，之后由 AI 即兴续写，不推翻设定与已发生的事。",
                                  "主持人想开新的一幕时发送 /团 主持 换幕 标题：引子；收尾时发送 /团 完结 结局名"))
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
        if turn is None and shared.ending_step(room):
            return Reply()      # between the finale and the ending nobody takes a turn
        if turn is None:
            actor, _ = next_actor(c, room_id, None)
            new = open_turn(app, c, room, actor, [], 1) if actor is not None else None
            return Reply().say(turn_prompt(app, room, new, actor)) if new is not None else Reply()
        from . import rush
        if rush.is_round(turn):
            return Reply()      # the round waits for whoever is present; leavers simply stop counting
        if change in ("left", "away", "rebuild") and turn["actor_id"] == actor_id and turn["state"] == "awaiting":
            leaving = c.execute("SELECT * FROM actors WHERE id=?", (actor_id,)).fetchone()
            following, wrapped = next_actor(c, room_id, leaving)
            new = open_turn(app, c, room, following, loads(turn["choices_json"], []), turn["round"] + (1 if wrapped else 0))
            if new is not None:
                return Reply().say(turn_prompt(app, room, new, following))
    return Reply()


def reopen_turn(app: "LiteApp", c: sqlite3.Connection, room: sqlite3.Row) -> sqlite3.Row | None:
    """A table with no open turn (paused while a story was being written by an older version): open the turn
    that should have followed the last story, with that story's options and round."""
    last = c.execute("SELECT * FROM turns WHERE room_id=? AND state='done' ORDER BY created_at DESC, rowid DESC LIMIT 1",
                     (room["id"],)).fetchone()
    if last is None:
        actor, _ = next_actor(c, room["id"], None)
        return open_turn(app, c, room, actor, [], 1) if actor is not None else None
    proposal = loads(last["narrative_json"], {}) or {}
    choices = make_choices(proposal.get("suggestions") or [], proposal.get("suggestion_checks"))
    resume = loads(last["data_json"], {}).get("resume_actor")
    previous = c.execute("SELECT * FROM actors WHERE id=?", (resume or last["actor_id"],)).fetchone()
    if resume and previous["presence"] == "present" and previous["archetype_id"]:
        following, wrapped = previous, False
    else:
        following, wrapped = next_actor(c, room["id"], previous)
    if following is None:
        return None
    return open_turn(app, c, room, following, choices, last["round"] + (1 if wrapped else 0))


async def on_room_resumed(room_id: str, joined: list[str] | None = None, left: list[str] | None = None,
                          send: Callable[[Any], Awaitable[Any]] | None = None, *, app: "LiteApp") -> Reply:
    """After the lobby: the story so far, a world pulse when people came or went, then the paused player's turn.

    With send, everything before the pulse goes out first so the group reads it while the pulse is written.
    """
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        epilogues = pacing.epilogue_resumed(c, room)
        written = epilogues is not None and pacing.epilogues_done(c, room_id)
        last = c.execute("SELECT text FROM events WHERE room_id=? AND kind='narration' ORDER BY id DESC LIMIT 1",
                         (room_id,)).fetchone()
    if epilogues is not None:       # after the finale there is no turn to reopen: the epilogues go on
        reply = Reply()
        if last is not None:
            reply.say(messages.narration(last["text"], "终章"))
        if written:                 # everyone wrote theirs during the pause: the story ends now
            async with app.lock(room_id):
                return reply.extend(await pacing._finish(app, room_id, "system"))
        return reply.say(epilogues)
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        turn = current_turn(c, room_id)
        if turn is None:
            turn = reopen_turn(app, c, room)
        elif turn["state"] == "awaiting":
            holder = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
            if holder["presence"] != "present" or not holder["archetype_id"]:
                following, wrapped = next_actor(c, room_id, holder)
                turn = open_turn(app, c, room, following, loads(turn["choices_json"], []), turn["round"] + (1 if wrapped else 0))
            else:
                c.execute("UPDATE turns SET deadline_at=? WHERE id=?", (_deadline(app, room), turn["id"]))
                turn = c.execute("SELECT * FROM turns WHERE id=?", (turn["id"],)).fetchone()
        last = c.execute("SELECT text FROM events WHERE room_id=? AND kind='narration' ORDER BY id DESC LIMIT 1",
                         (room_id,)).fetchone()
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone() if turn is not None else None
    reply = Reply()
    recap = await story_recap.on_resume(app, room_id)
    if recap is not None:
        reply.say(recap)
    if last is not None:
        scene = loads(room["scene_json"], {}).get("title", "")
        reply.say(messages.narration(last["text"], "上一轮的故事" + (" · " + scene if scene else "")))
    if turn is None:
        return reply.say("没有在场的玩家，故事停在这里。")
    if turn["state"] != "awaiting":
        return reply.say(messages.notice(f"这一回合{TURN_STATES.get(turn['state'], turn['state'])}",
                                         hint="主持人发送 /团 主持 重试 重新生成正文，或 /团 主持 跳过；主持人 5 分钟没处理时，在座的玩家也可以 /团 重试"))
    if joined or left:
        if send is not None:
            for item in reply.messages:
                await send(item)
            reply = Reply()
        return reply.extend(await world_pulse(app, room_id, turn, joined or [], left or [], send))
    return reply.say(turn_prompt(app, room, turn, actor))


async def world_pulse(app: "LiteApp", room_id: str, turn: sqlite3.Row, joined: list[str], left: list[str],
                      send: Callable[[Any], Awaitable[Any]] | None = None) -> Reply:
    """Write the people who joined or left during the pause into the story, then give the waiting player new options."""
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        names = {a["id"]: a["name"] for a in shared.world(room)["pack"]["archetypes"]}
        came, went = [], []
        for actor_id in joined:
            a = c.execute("SELECT * FROM actors WHERE id=?", (actor_id,)).fetchone()
            intro = ((personas.active(room, a) or {}).get("intro") or "")[:80]
            came.append(shared.actor_label(a) + "（" + "，".join(filter(None, [names.get(a["archetype_id"], ""),
                                                                             "在本世界中：" + intro if intro else ""])) + "）")
        went = [shared.actor_label(c.execute("SELECT * FROM actors WHERE id=?", (i,)).fetchone()) for i in left]
        holder = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
        summary = "；".join(filter(None, ["新加入：" + "、".join(came) if came else "", "离开：" + "、".join(went) if went else ""]))
        action = ("（世界脉冲）队伍的人员有了变动——" + summary + "。把这些变动写成一段符合世界观的剧情："
                  "新来的角色以合理的方式来到队伍身边、与大家照面；离开的角色以合理的方式暂别，不写死、不写伤。"
                  f"最后把场面交还给 {shared.actor_label(holder)}，选项写 {shared.actor_label(holder)} 接下来可以做的事。")
        lifecycle.auto_snapshot(c, room_id, f"第 {turn['round']} 轮 · 世界脉冲前")
        c.execute("UPDATE turns SET state='superseded',updated_at=? WHERE id=?", (now(), turn["id"]))
        pulse = new_id("turn")
        c.execute("INSERT INTO turns(id,room_id,round,actor_id,state,choices_json,action_text,receipt_json,data_json,created_at,updated_at) "
                  "VALUES(?,?,?,?,'resolving','[]',?,?,?,?,?)",
                  (pulse, room_id, turn["round"], turn["actor_id"], action,
                   dumps({"receipt_ref": new_id("receipt"), "kind": "world_pulse"}), dumps({"resume_actor": turn["actor_id"]}),
                   now(), now()))
        app.store.add_event(c, room_id, "host", "世界脉冲：" + summary)
    notice = messages.notice("世界脉冲", summary.replace("；", "\n") + "\nAI 正在把这些变动写进故事。")
    reply = Reply()
    if send is not None:
        await send(notice)
    else:
        reply.say(notice)
    async with app.lock(room_id):
        return reply.extend(await narrate(app, room_id, pulse, advance=False))


async def on_room_restored(room_id: str, *, app: "LiteApp") -> Reply:
    with app.store.tx() as c:
        c.execute("UPDATE turns SET state='awaiting',updated_at=? WHERE room_id=? AND state='resolving'", (now(), room_id))
    return Reply()


async def on_room_closed(room_id: str, *, app: "LiteApp") -> Reply:
    with app.store.tx() as c:
        c.execute("UPDATE turns SET state='superseded',updated_at=? WHERE room_id=? "
                  "AND state IN ('awaiting','resolving','narration_failed','review')", (now(), room_id))
    return Reply()


async def on_story_completed(room_id: str, ending: Any, *, app: "LiteApp") -> Reply:
    await on_room_closed(room_id, app=app)
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        bonds = ties.reveal(c, room)
    reply = Reply()
    for item in (banter.reveal(room), bonds):
        if item is not None:
            reply.say(item)
    return reply


async def on_status(room_id: str, *, app: "LiteApp") -> Reply:
    with app.store.read() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        turn = current_turn(c, room_id)
        if turn is None or room["state"] not in ("running", "paused"):
            return Reply()
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
    return Reply().say(f"第 {turn['round']} 轮：{shared.actor_label(actor)}（{TURN_STATES.get(turn['state'], turn['state'])}）") \
        .say(pacing.status_line(room, turn["round"]))


async def on_tick(*, app: "LiteApp") -> Reply:
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    with app.store.read() as c:
        # A table in 整备 keeps its turn clock still; closing 整备 moves the deadline on.
        due = c.execute("SELECT t.id,t.room_id FROM turns t JOIN rooms r ON r.id=t.room_id WHERE t.state='awaiting' "
                        "AND r.state='running' AND json_extract(r.data_json,'$.outfit') IS NULL "
                        "AND t.deadline_at IS NOT NULL AND t.deadline_at<=?", (stamp,)).fetchall()
        soon = c.execute("SELECT t.id FROM turns t JOIN rooms r ON r.id=t.room_id WHERE t.state='awaiting' "
                         "AND r.state='running' AND json_extract(r.data_json,'$.outfit') IS NULL "
                         "AND t.deadline_at IS NOT NULL AND t.deadline_at>? AND t.deadline_at<=?",
                         (stamp, (datetime.now(UTC) + REMIND_BEFORE).isoformat(timespec="seconds"))).fetchall()
    for row in due:
        if app.lock(row["room_id"]).locked():
            continue
        app.spawn(timeout_turn(app, row["room_id"], row["id"]), name=f"321roll-timeout-{row['id']}")
    for row in soon:
        remind_turn(app, row["id"])
    return Reply()


REMIND_BEFORE = timedelta(minutes=1)
REMIND_MIN_LIMIT = 180      # shorter limits are already short enough to keep an eye on
AWAY_AFTER_TIMEOUTS = 2


def remind_turn(app: "LiteApp", turn_id: str) -> None:
    """One @ per turn a minute before its deadline: the options message is easily buried in a busy group."""
    with app.store.tx() as c:
        turn = c.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
        data = loads(turn["data_json"], {})
        if turn["state"] != "awaiting" or data.get("reminded"):
            return
        c.execute("UPDATE turns SET data_json=? WHERE id=?", (dumps({**data, "reminded": True}), turn_id))
        room = c.execute("SELECT * FROM rooms WHERE id=?", (turn["room_id"],)).fetchone()
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
    from . import rush
    if rush.is_round(turn):
        with app.store.read() as c:
            board = rush.members(c, room["id"], turn)
        missing = [(shared.actor_label(a), a["user_name"], a["user_id"]) for a, done in board if not done]
        if missing:
            reminder = messages.rush_reminder(missing, [(shared.actor_label(a), done) for a, done in board])
            app.spawn(app.notifier.send(room["umo"], reminder), name=f"321roll-remind-{turn_id}")
        return
    if turn_seconds(app, room) < REMIND_MIN_LIMIT or actor is None:
        return
    app.spawn(app.notifier.send(room["umo"], messages.turn_reminder(shared.actor_label(actor), actor["user_name"],
                                                                    actor["user_id"], bool(loads(turn["choices_json"], [])))),
              name=f"321roll-remind-{turn_id}")


def _timeout_streak(c: sqlite3.Connection, room_id: str, actor: sqlite3.Row) -> bool:
    """Count this timeout; True when the player has now missed enough turns in a row and someone else can play on."""
    data = loads(actor["data_json"], {})
    streak = int(data.get("timeouts") or 0) + 1
    others = [a for a in eligible_actors(c, room_id) if a["id"] != actor["id"]]
    away = streak >= AWAY_AFTER_TIMEOUTS and bool(others)
    data["timeouts"] = 0 if away else streak
    c.execute("UPDATE actors SET data_json=?" + (",presence='away',revision=revision+1" if away else "") + ",updated_at=? WHERE id=?",
              (dumps(data), now(), actor["id"]))
    return away


async def timeout_turn(app: "LiteApp", room_id: str, turn_id: str) -> None:
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        if room is None or room['state'] != 'running':
            return  # A queued timeout must not advance a table that has since been parked.
        turn = c.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
        if turn is None or turn["state"] != "awaiting" or loads(turn["data_json"], {}).get("timeout"):
            return
        c.execute("UPDATE turns SET data_json=? WHERE id=?", (dumps({**loads(turn["data_json"], {}), "timeout": True}), turn_id))
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
        from . import rush
        rushing = rush.is_round(turn)
        gone = not rushing and _timeout_streak(c, room_id, actor)
        if gone:
            # Missed turns in a row: set away and hand the turn on instead of acting for them again.
            label = shared.actor_label(actor)
            c.execute("UPDATE turns SET state='skipped',updated_at=? WHERE id=?", (now(), turn_id))
            app.store.add_event(c, room_id, "system", f"{label} 连续 {AWAY_AFTER_TIMEOUTS} 轮超时，自动暂离", actor_id=actor["id"])
            app.store.bump_room(c, room_id)
            following, wrapped = next_actor(c, room_id, actor)
            new = open_turn(app, c, room, following, loads(turn["choices_json"], []), turn["round"] + (1 if wrapped else 0))
        history = [r["text"][:6000] for r in c.execute(
            "SELECT text FROM events WHERE room_id=? AND kind='narration' ORDER BY id DESC LIMIT 3", (room_id,))]
    if rushing:
        async with app.lock(room_id):
            reply = await rush.close(app, room_id, turn_id)
        await app.notifier.send(room["umo"], [f"第 {turn['round']} 轮快团时间到，没交的人这一轮旁观。"] + reply.messages)
        return
    if gone:
        items: list[Any] = [messages.auto_away(label, actor["user_name"], actor["user_id"], AWAY_AFTER_TIMEOUTS)]
        if new is not None:
            items.append(turn_prompt(app, room, new, following))
        await app.notifier.send(room["umo"], items)
        return
    choices = loads(turn["choices_json"], [])
    label = shared.actor_label(actor)
    if not choices:
        with app.store.tx() as c:
            following, wrapped = next_actor(c, room_id, actor)
            new = open_turn(app, c, room, following, [], turn["round"] + (1 if wrapped else 0))
            app.store.add_event(c, room_id, "system", f"{label} 超时，回合跳过", actor_id=actor["id"])
        items = [f"{label} 超时未行动，回合跳过。"] + ([turn_prompt(app, room, new, following)] if new is not None else [])
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
                              announce=f"{label} 超时，自动选择 {chosen['label']}。",
                              early=lambda item: app.notifier.send(room["umo"], item))
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
    economy.guard(room)
    shared.require_play(app, caller, "playActions")
    actor = shared.require_actor(app, caller, room)
    with app.store.read() as c:
        turn = current_turn(c, room["id"])
    if (turn is None or turn["state"] != "awaiting") and shared.ending_step(room):
        raise UserError(shared.ending_step(room))
    if turn is None or turn["state"] != "awaiting":
        raise UserError("现在没有等待行动的回合。" if turn is None else
                        "上一段正文正在等主持人审阅，请稍候。" if turn["state"] == "review" else
                        f"上一段正文没写出来，正在等主持人 /团 主持 重试；主持人 {PLAYER_RETRY_AFTER_MINUTES} 分钟内没处理的话，"
                        "在座的玩家也可以发送 /团 重试。" if turn["state"] == "narration_failed" else "上一个行动还在结算，请稍候。")
    if turn["actor_id"] != actor["id"]:
        with app.store.read() as c:
            holder = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
        name = shared.actor_label(holder)
        raise UserError(f"现在轮到 {name} 行动，轮到你时会在群里 @ 你。这会儿可以 /团 说 台词、/团 援手 帮 {name} 一把，"
                        f"或 /团 押 成 竞猜这一掷。")
    if loads(actor["data_json"], {}).get("timeouts"):
        with app.store.tx() as c:     # acting on one's own turn ends a run of timeouts
            data = {**loads(actor["data_json"], {}), "timeouts": 0}
            c.execute("UPDATE actors SET data_json=? WHERE id=?", (dumps(data), actor["id"]))
    return room, actor, turn


def awaits(app: "LiteApp", caller: Caller) -> bool:
    """Whether this group message comes from the player the open turn is waiting for (bare-letter choices)."""
    from . import rush
    try:
        if rush.my_round(app, caller) is not None:
            return True
        _my_turn(app, caller)
    except UserError:
        return False
    return True


async def choose(app: "LiteApp", caller: Caller, args: str) -> Reply:
    from . import rush
    rushing = rush.my_round(app, caller)
    room, actor, turn = rushing or _my_turn(app, caller)
    if shared.rules(room).get("action_mode") == "dialogue_only":
        raise UserError("本世界只接受自由描述行动：/团 行动 <描述>")
    args, names = loadout.split_marker(args)
    words = args.split(maxsplit=1)
    label = words[0].upper().replace("Ａ", "A").replace("Ｂ", "B").replace("Ｃ", "C").replace("Ｄ", "D") if words else ""
    choice = next((ch for ch in loads(turn["choices_json"], []) if ch["label"] == label), None)
    if choice is None:
        labels = [ch["label"] for ch in loads(turn["choices_json"], [])]
        if not labels:
            raise UserError("这一轮没有选项，用 /团 行动 你的做法 写下你要做什么。")
        raise UserError(f"这一轮可选 {'、'.join(labels)}，例如 /团 选 {labels[0]}；也可以 /团 行动 你的做法。")
    check = choice["check"]
    flourish = words[1].strip() if len(words) > 1 else ""
    all_in, flourish = _all_in(room, actor, flourish)
    if all_in and check.get("kind") != "check":
        raise UserError(f"{label} 这一项不掷骰，孤注用不上。去掉“孤注”再选，或换一个要检定的选项。")
    prepared = loadout.freeze(room, actor, names, check.get("attribute_ref") if check.get("kind") == "check" else None) if names else None
    action = choice["text"] + (f"（{flourish[:200]}）" if flourish else "")
    with app.store.read() as c:
        quota.require_round(app, c, room["umo"])
    await story_recap.before_action(app, caller, room["id"])
    if rushing:
        return await rush.submit(app, room, actor, turn, action, intent_from_choice(choice), prepared=prepared,
                                 all_in=all_in, early=caller.send)
    return await resolve(app, room["id"], turn["id"], action, intent_from_choice(choice), prepared=prepared, early=caller.send,
                         all_in=all_in)


async def act(app: "LiteApp", caller: Caller, args: str) -> Reply:
    from . import rush
    rushing = rush.my_round(app, caller)
    room, actor, turn = rushing or _my_turn(app, caller)
    if shared.rules(room).get("action_mode") == "choice_only":
        raise UserError("本世界只接受选项行动：/团 选 A")
    text, names = loadout.split_marker(args)
    all_in, text = _all_in(room, actor, text)
    if not 2 <= len(text) <= 500:
        raise UserError("写一句 2–500 字的行动描述，例如 /团 行动 推开音乐室的门看看。")
    prepared = loadout.freeze(room, actor, names) if names else None
    with app.store.read() as c:
        quota.require_round(app, c, room["umo"])        # before "正在结算" goes out
    await story_recap.before_action(app, caller, room["id"])
    await caller.send("正在结算……")
    if rushing:
        return await rush.submit(app, room, actor, turn, text, None, prepared=prepared, all_in=all_in, early=caller.send)
    return await resolve(app, room["id"], turn["id"], text, None, prepared=prepared, early=caller.send, all_in=all_in)


ALL_IN_WORDS = ("[孤注一掷]", "【孤注一掷】", "[孤注]", "【孤注】", "孤注一掷", "孤注")


def _all_in(room: sqlite3.Row, actor: sqlite3.Row, text: str) -> tuple[bool, str]:
    """'孤注' at the start or end of the flourish (or [孤注] anywhere) stakes this check; once per act."""
    text = text.strip()
    for word in ALL_IN_WORDS:
        if word.startswith(("[", "【")) and word in text:
            text = text.replace(word, " ").strip()
            break
        if text == word or text.startswith(word + " ") or text.endswith(" " + word):
            text = (text[len(word):] if text.startswith(word) else text[:-len(word)]).strip()
            break
    else:
        return False, text
    if loads(actor["data_json"], {}).get("all_in_act") == room["act"]:
        raise UserError("这一幕你已经孤注过一次了，下一幕再来。")
    return True, text


async def all_in_help(app: "LiteApp", caller: Caller, args: str) -> Reply:
    """孤注 is a word added to a choice, not a command of its own: explain it and say whether it is still free."""
    left = ""
    try:
        room = shared.require_room(app, caller, "running", "paused")
        with app.store.read() as c:
            actor = shared.actor_for(c, room["id"], caller.user_id)
        if actor is not None:
            used = loads(actor["data_json"], {}).get("all_in_act") == room["act"]
            left = "这一幕你已经孤注过了，下一幕再来。" if used else "这一幕你还能孤注一次。"
    except UserError:
        pass
    return Reply().say(messages.all_in_guide(left))


async def skip(app: "LiteApp", caller: Caller, args: str) -> Reply:
    from . import rush
    rushing = rush.my_round(app, caller)
    if rushing:
        return await rush.skip(app, *rushing)
    room, actor, turn = _my_turn(app, caller)
    return _advance_without_action(app, room, turn, f"{shared.actor_label(actor)} 跳过了本回合。")


def _advance_without_action(app: "LiteApp", room: sqlite3.Row, turn: sqlite3.Row, message: str) -> Reply:
    with app.store.tx() as c:
        actor = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
        if loads(c.execute("SELECT data_json FROM turns WHERE id=?", (turn["id"],)).fetchone()["data_json"], {}).get("bets"):
            message += "这一轮没有掷骰，竞猜作废。"
        c.execute("UPDATE turns SET state='skipped',updated_at=? WHERE id=?", (now(), turn["id"]))
        following, wrapped = next_actor(c, room["id"], actor)
        new = open_turn(app, c, room, following, loads(turn["choices_json"], []), turn["round"] + (1 if wrapped else 0))
        app.store.add_event(c, room["id"], "system", message, actor_id=actor["id"])
    reply = Reply().say(message)
    if new is not None:
        reply.say(turn_prompt(app, room, new, following))
    return reply


def _skip_narrator(app: "LiteApp", room: sqlite3.Row, turn: sqlite3.Row, kind: str) -> Reply:
    """/团 主持 跳过 on a world-written passage that failed: the finale goes straight to the epilogues;
    a push, pulse or host advance is dropped and the waiting player gets the last story's options back."""
    with app.store.tx() as c:
        c.execute("UPDATE turns SET state='skipped',updated_at=? WHERE id=?", (now(), turn["id"]))
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
        if kind == "finale":
            app.store.add_event(c, room["id"], "host", "主持人跳过了终章，直接征集尾声")
            return Reply().say(pacing.finale_skipped(c, room))
        last = c.execute("SELECT * FROM turns WHERE room_id=? AND state='done' ORDER BY created_at DESC LIMIT 1",
                         (room["id"],)).fetchone()
        proposal = loads(last["narrative_json"], {}) if last is not None else {}
        choices = make_choices(proposal.get("suggestions") or [], proposal.get("suggestion_checks"))
        waiting = c.execute("SELECT * FROM actors WHERE id=?", (loads(turn["data_json"], {}).get("resume_actor") or turn["actor_id"],)).fetchone()
        following, wrapped = (waiting, False) if waiting["presence"] == "present" and waiting["archetype_id"] else next_actor(c, room["id"], waiting)
        new = open_turn(app, c, room, following, choices, turn["round"] + (1 if wrapped else 0)) if following is not None else None
        label = {"pace_push": "世界推进", "world_pulse": "世界脉冲", "host_advance": "主持人推进"}.get(kind, "这段正文")
        app.store.add_event(c, room["id"], "host", f"主持人跳过了没写出来的{label}")
    reply = Reply().say(messages.notice(f"跳过了{label}", "这一段没写出来，故事接着上一段正文继续。"))
    if new is not None:
        reply.say(turn_prompt(app, room, new, following))
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
    if room["state"] == "paused":
        # The choices come back when the story resumes; showing them now would invite a /团 选 that cannot work.
        return Reply().say(shared.paused_step(room) + (f"开演后由 {shared.actor_label(actor)} 接着行动，选项会重新发出。" if actor else ""))
    if turn["state"] != "awaiting":
        return Reply().say({"resolving": f"{shared.actor_label(actor)} 的行动正在结算。",
                            "review": "上一段正文正在等主持人审阅。"}.get(turn["state"], "上一回合的正文没写出来，等主持人 /团 主持 重试；主持人 5 分钟没处理时，在座的玩家也可以 /团 重试。"))
    return Reply().say(turn_prompt(app, room, turn, actor))


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
    for i, row in enumerate(reversed(rows), 1):
        text = re.sub(r"(?<!\n)\n(?!\n)", "\n\n", row["text"])      # a scene line above its prose is its own paragraph
        reply.say(messages.narration(text, f"剧情回顾 · 第 {i}/{len(rows)} 段"))
    if len(rows) < 5:
        reply.say("想看更早的，发送 /团 回顾 5（最多 5 段）。")
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
        return Reply().say(messages.notice("当前的主持人指引", current, f"发送 {messages.cmd('/团 主持 指引 新内容')} 替换，"
                                                                        f"{messages.cmd('/团 主持 指引 清除')} 取消"))
    with app.store.tx() as c:
        set_hosted_data(c, room["id"], directive="" if text == "清除" else text[:600])
    return Reply().say(messages.notice("已清除主持人指引") if text == "清除" else messages.notice(
        "已记录主持人指引", "之后的叙事会参考它，不会发到群里。", f"发送 {messages.cmd('/团 主持 指引 清除')} 取消"))


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
        raise UserError(shared.ending_step(room, "推进") or "当前回合正在结算或没有回合。")
    economy.host_guard(room, "推进")
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
        raise UserError(shared.ending_step(room) or "当前没有可以跳过的回合。")
    kind = (loads(turn["receipt_json"], {}) or {}).get("kind")
    if kind in NARRATOR_KINDS and turn["state"] != "awaiting":
        return _skip_narrator(app, room, turn, kind)
    from . import rush
    if rush.is_round(turn) and turn["state"] == "awaiting":
        async with app.lock(room["id"]):    # a rush round: stop waiting and write what came in
            return Reply().say("主持人收了这一轮，没交的人旁观。").extend(await rush.close(app, room["id"], turn["id"]))
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
    return Reply().say("主持人更新了选项。", turn_prompt(app, room, turn, actor))


async def host_retry(app: "LiteApp", caller: Caller, args: str) -> Reply:
    return await _retry(app, caller, _host_room(app, caller, "running"))


AUTO_RETRY_DELAY = 2.0
PLAYER_RETRY_AFTER_MINUTES = 5


async def player_retry(app: "LiteApp", caller: Caller, args: str) -> Reply:
    """Any seated player may retry a failed narration once the host has had a few minutes to deal with it."""
    room = shared.require_room(app, caller, "running")
    if not shared.is_host(app, caller, room):
        shared.require_actor(app, caller, room)
        with app.store.read() as c:
            turn = current_turn(c, room["id"])
        if turn is not None and turn["state"] == "narration_failed":
            waited = datetime.now(UTC) - datetime.fromisoformat(turn["updated_at"])
            left = timedelta(minutes=PLAYER_RETRY_AFTER_MINUTES) - waited
            if left > timedelta(0):
                raise UserError(f"正文刚失败不久，先等主持人处理；{max(1, round(left.total_seconds() / 60))} 分钟后"
                                "在座的玩家也可以发送 /团 重试。")
    return await _retry(app, caller, room)


async def _retry(app: "LiteApp", caller: Caller, room: sqlite3.Row) -> Reply:
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
            raise UserError(f"本世界共 {len(preset)} 幕。故事走到这里，想收尾就发送 /团 主持 收尾 结局名。")
        if target < 1 or target > max(room["act"], len(preset)) + 1:
            raise UserError(f"下一幕是第 {max(room['act'], len(preset)) + 1} 幕。")
        # A Core edition stops at its first act; the host names each later act and the model improvises it.
        title, lead = split_title(named) if "：" in named or ":" in named else (named, "")
        improvised = {"title": title[:40], "lead": lead[:300]}
    return await change_act(app, room["id"], target, improvised)


async def change_act(app: "LiteApp", room_id: str, target: int, improvised: dict[str, str] | None = None, *,
                     prompt: bool = True) -> Reply:
    """Open act 'target' (by the host, or by pacing once an act has run its rounds).

    improvised: a Core-edition act past the preset ones; empty title and lead keep what the table named before.
    prompt=False leaves the waiting turn's card to the caller.
    """
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        preset = shared.world(room).get("presentation", {}).get("acts") or []
        if improvised is not None and any(a["number"] == target for a in preset):
            improvised = None
        if improvised is not None:
            known = next((a for a in lifecycle.act_list(room) if a["number"] == target), None) or {}
            improvised = {"title": (improvised.get("title") or known.get("title", ""))[:40],
                          "lead": (improvised.get("lead") or known.get("lead", ""))[:300]}
        from ..fun.report import act_recap, favourite_line, favourites
        best = favourite_line(favourites(c, room["id"], room["act"])) if target != room["act"] else ""
        recap = act_recap(c, room["id"]) if target != room["act"] else None
        changed = target != room["act"]
        c.execute("UPDATE rooms SET act=?,chapter=chapter+1 WHERE id=?", (target, room["id"]))
        if improvised is not None:
            extra = hosted_data(room).get("acts") or {}
            set_hosted_data(c, room["id"], acts={**extra, str(target): improvised})
        app.store.bump_room(c, room["id"])
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
        heading = lifecycle.act_heading(room) or f"第 {target} 幕"
        app.store.add_event(c, room["id"], "chapter", heading.replace("\n", "——"))
        set_hosted_data(c, room["id"], shown_act=target)
        pacing.act_changed(c, c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone())
        refilled = loadout.refill(c, room, "scene")
        wage, paid = economy.pay_wage(c, room) if changed else (0, [])
        turn = current_turn(c, room["id"])
        holder = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone() \
            if prompt and turn is not None and turn["state"] == "awaiting" and turn["actor_id"] else None
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
    act = next((a for a in lifecycle.act_list(room) if a["number"] == target), {"title": "", "lead": ""})
    from ..worlds import scenes
    reply = Reply().say(scenes.bind(messages.act_card(room["title"], target, act["title"] or f"第 {target} 幕", act["lead"],
                                          world=room["world_id"], total=lifecycle.acts_total(room), best=best, recap=recap), room, f"act:{target}"))
    if refilled:
        reply.say(f"新的一幕：按“每幕恢复”的技能与物品次数已恢复（{refilled} 名角色）。")
    if wage:
        reply.say(messages.wage_card(wage, economy.of_room(room)["currency"], paid))
    if holder is not None and room["state"] == "running":
        reply.say(turn_prompt(app, room, turn, holder))
    return reply


async def host_turn_to(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, "running")
    token, _ = shared.split_target(args, caller)
    with app.store.tx() as c:
        turn = current_turn(c, room["id"])
        if turn is None or turn["state"] != "awaiting":
            raise UserError(shared.ending_step(room, "交接回合") or "现在没有等待行动的回合。")
        target = shared.find_actor(c, room["id"], token, caller.mentions)
        if target["presence"] != "present" or not target["archetype_id"]:
            raise UserError(f"{shared.actor_label(target)} 现在不能行动（暂离或还没建卡）。")
        if target["id"] == turn["actor_id"]:
            raise UserError(f"现在就是 {shared.actor_label(target)} 的回合。")
        new = open_turn(app, c, room, target, loads(turn["choices_json"], []), turn["round"])
        app.store.add_event(c, room["id"], "system", f"主持人把回合交给 {shared.actor_label(target)}", actor_id=target["id"])
    return Reply().say(f"主持人把这一回合交给了 {shared.actor_label(target)}。", turn_prompt(app, room, new, target))


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
            before_finale = lifecycle.restore_snapshot(c, room["id"], loads(snapshot["data_json"]))
            c.execute("DELETE FROM saves WHERE id=?", (snapshot["id"],))
            if room["state"] == "running":
                c.execute("UPDATE rooms SET state='running' WHERE id=?", (room["id"],))
            restored = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
            turn = current_turn(c, room["id"])
            if turn is None and restored["state"] == "running":
                turn = reopen_turn(app, c, restored)    # saved between a story and the turn after it
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
                                        "这一步的骰子、资源变化、正文和玩法记录都已撤回。" + (f"还可以再回退 {left} 步。" if left else "这是能回退的最早一步。")
                                        + ("终章撤回了，故事回到收尾的最后一轮：这一轮走完会自动写终章。" if before_finale else ""),
                                        ("想现在就写终章，发送 /团 主持 收尾 终章" if before_finale else "")
                                        if restored["state"] == "running" else "故事处于暂停状态，主持人发送 /团 恢复 打开准备大厅"))
    if holder is not None and restored["state"] == "running":
        reply.say(turn_prompt(app, restored, turn, holder))
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
    economy.host_guard(room, "要求检定")
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
        trait = trait_bonus(room, actor, attribute, difficulty)
        base += trait["bonus"] if trait else 0
        roll = roll_check(base, rules["difficulties"][difficulty])
        outcome = "critical" if roll.critical else "fumble" if roll.fumble else "success" if roll.success else "failure"
        names = {r["id"]: r["name"] for r in shared.world(room)["pack"]["resources"]}
        receipt = {"kind": "check", "attribute_ref": attribute, "attribute": rules["attributes"][attribute], "difficulty": difficulty,
                   "dc": roll.dc, "face": roll.face, "modifier": base, "total": roll.total, "outcome": outcome, "success": roll.success,
                   "resource_changes": {}, "resources_after": {names.get(k, k): v["current"] for k, v in loads(actor["resources_json"], {}).items()},
                   "host_check": True, **({"trait": trait} if trait else {})}
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
        with app.store.read() as c:
            room, turn = _require_active_turn(c, room["id"], turn["id"], ("review",))
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
    r.register(("选", "选择"), choose, summary="选择本轮选项（也可以简写成 /团 A）",
               usage="/团 选 A [补充演绎] [用 名称] [孤注]", topic="行动", private="room")
    r.register("行动", act, summary="自由描述行动", usage="/团 行动 <描述> [用 名称] [孤注]", topic="行动", private="room")
    r.register(("孤注", "孤注一掷"), all_in_help, summary="押上这次检定：成功按大成功写，失败必定受伤，每幕一次",
               usage="/团 选 A 孤注｜/团 行动 做法 [孤注]", topic="互动", private="self")
    r.register("跳过", skip, summary="跳过自己的回合", topic="行动", private="room")
    r.register("重试", player_retry, summary="正文生成失败、主持人 5 分钟没处理时重新生成", topic="行动", private="room")
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
    app.hooks.on("room_closed", bind(on_room_closed))
    app.hooks.on("story_completed", bind(on_story_completed))
    app.hooks.on("status_lines", bind(on_status))
    app.hooks.on("tick", bind(on_tick))
    pacing.install(app)
