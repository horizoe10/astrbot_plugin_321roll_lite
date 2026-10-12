"""Pacing at a hosted table: how long a scene, an act and the story run, and how the story winds down.

Every table is paced (worlds/pacing.py has the settings).  A round is every seated player acting once.

- Scene: from sceneRounds on, each narration is told the situation must change; graceRounds later the
  world pushes by itself (a narrator turn), which also starts the count again.
- Act: at actRounds the table is offered the next act; graceRounds later it opens by itself.  The last
  preset act of a Pro world offers to wind down instead.
- Story: at targetRounds, or when a player picks a closing option ("收束：…" from the model), the table
  votes whether to wind down; at hardRounds the wind-down starts regardless.
- Wind-down: CLOSING_ROUNDS rounds without new threads, then the finale (a narrator turn), then
  EPILOGUE_MINUTES for everyone's one-line epilogue, then the ending card.

State lives in rooms.data_json["hosted"]["pacing"]; the host's own settings in ["hosted"]["pacing_own"].
hosted.commit_narration asks after_narration() what to do once a narration is stored.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .. import messages, shared
from ..commands import Caller, Reply, UserError
from ..rooms import lifecycle
from ..storage import dumps, loads, new_id, now
from ..worlds import pacing as rules

if TYPE_CHECKING:
    from ..app import LiteApp

CLOSING_ROUNDS = 2
OFFER_ROUNDS = 3             # a closing proposal without a majority lapses after this many rounds
EPILOGUE_MINUTES = 5
RESUME_SECONDS = 120         # an epilogue resumed after a pause keeps at least this long
EPILOGUE_LIMIT = 100
YES = ("同意", "好", "收", "收尾", "赞成", "可以")
NO = ("再玩", "继续", "不", "不要", "反对", "再等等")
# "收束：灰冠归位——带着契约回到地表", also with brackets or 结局 as the word.
CLOSING_MARK = re.compile(r"^\s*[【\[〔(（]?\s*(?:收束|收尾|结局)\s*[】\]〕)）]?\s*[:：·]?\s*(?=\S)")
SOURCES = {"option": "有人选了收束选项", "target": "故事已经走到预期篇幅", "act_end": "最后一幕已经走满",
           "down": "全员倒下", "host": "主持人提议"}


# ---------------------------------------------------------------- settings and state
def conf(room: sqlite3.Row) -> dict[str, Any]:
    world = shared.world(room)
    acts = len(world.get("presentation", {}).get("acts") or [])
    own = loads(room["data_json"], {}).get("hosted", {}).get("pacing_own")
    return rules.settings(world["pack"].get("pacing"), acts, lifecycle.improvises(room), own)


def _fresh(round_number: int) -> dict[str, Any]:
    return {"scene_since": round_number, "act_since": round_number, "story_since": round_number, "seen": round_number}


def state(room: sqlite3.Row, round_number: int = 1) -> dict[str, Any]:
    """The table's counters; a table that started before pacing counts from round_number."""
    st = loads(room["data_json"], {}).get("hosted", {}).get("pacing")
    return dict(st) if st else _fresh(round_number)


def _save(c: sqlite3.Connection, room_id: str, st: dict[str, Any] | None = None, own: Any = ...) -> None:
    row = c.execute("SELECT data_json FROM rooms WHERE id=?", (room_id,)).fetchone()
    data = loads(row["data_json"], {})
    hosted = data.setdefault("hosted", {})
    if st is not None:
        hosted["pacing"] = st
    if own is not ...:
        if own:
            hosted["pacing_own"] = own
        else:
            hosted.pop("pacing_own", None)
    c.execute("UPDATE rooms SET data_json=? WHERE id=?", (dumps(data), room_id))


def current_round(c: sqlite3.Connection, room_id: str) -> int:
    row = c.execute("SELECT MAX(round) FROM turns WHERE room_id=?", (room_id,)).fetchone()
    return int(row[0] or 1)


def counts(st: dict[str, Any], r: int) -> dict[str, int]:
    """Whole rounds played in this scene, this act and the story by the start of round r."""
    return {"scene": max(0, r - st["scene_since"]), "act": max(0, r - st["act_since"]), "story": max(0, r - st["story_since"])}


def start(c: sqlite3.Connection, room_id: str) -> None:
    """A story that just opened counts from round 1."""
    _save(c, room_id, _fresh(1))


def last_act(room: sqlite3.Row) -> bool:
    total = lifecycle.acts_total(room)
    return bool(total) and room["act"] >= total


def next_act(room: sqlite3.Row) -> dict[str, Any]:
    target = room["act"] + 1
    known = next((a for a in lifecycle.act_list(room) if a["number"] == target), None)
    return {"number": target, "title": (known or {}).get("title", ""), "lead": (known or {}).get("lead", "")}


def _voters(c: sqlite3.Connection, room_id: str) -> list[sqlite3.Row]:
    from .hosted import eligible_actors
    seen, people = set(), []
    for a in eligible_actors(c, room_id):
        if a["user_id"] not in seen:
            seen.add(a["user_id"])
            people.append(a)
    return people


def closing_name(text: str) -> tuple[str, str | None]:
    """(option text without the mark, ending name or None) for one suggestion from the model."""
    match = CLOSING_MARK.match(text or "")
    if not match:
        return text, None
    rest = text[match.end():].strip()
    name = re.split(r"[——:：，,。；;（(]", rest, maxsplit=1)[0].strip()
    return rest, (name or rest)[:24]


# ---------------------------------------------------------------- the plan after a narration
@dataclass
class Plan:
    cards: list[Any] = field(default_factory=list)   # after the narration, before the next turn
    act_change: int | None = None                     # the act that opens by itself now
    push: int = 0                                     # rounds the scene ran when the world pushes
    push_note: int = 0                                # the same, folded into the next rush narration
    finale: str | None = None                         # the ending to write now ('' lets the story decide)


def ending_title(room: sqlite3.Row, title: str) -> str:
    """The world's own ending name when the given one clearly means it (so its banner and rule match)."""
    title = (title or "").strip()
    endings = shared.world(room).get("presentation", {}).get("endings") or []
    names = [e["name"] for e in endings if e.get("name")]
    if not title or title in names:
        return title
    by_id = next((e["name"] for e in endings if e.get("id") == title and e.get("name")), None)
    if by_id:
        return by_id
    hits = [n for n in names if len(n) >= 2 and len(title) >= 2 and (n in title or title in n)]
    return hits[0] if len(hits) == 1 else title


def branch_ending(c: sqlite3.Connection, room_id: str) -> sqlite3.Row | None:
    """The ending entered through the ending play (/团 结局 #n 进入); pacing stops proposing then."""
    return c.execute("SELECT * FROM records WHERE room_id=? AND kind='ending' AND state='entered' ORDER BY seq DESC LIMIT 1",
                     (room_id,)).fetchone()


def _offer(st: dict[str, Any], room: sqlite3.Row, source: str, title: str, r: int, yes: list[str] | None = None) -> None:
    st["offer"] = {"title": ending_title(room, title), "source": source, "round": r, "yes": yes or [], "no": []}


def _offer_left(st: dict[str, Any], r: int) -> int:
    offer = st.get("offer") or {}
    return max(1, offer.get("round", r) + OFFER_ROUNDS - r)


def _settle(c: sqlite3.Connection, room: sqlite3.Row, st: dict[str, Any], r: int, cf: dict[str, Any]) -> Any | None:
    """Close the proposal once a majority has spoken; returns the card that says so, or None."""
    offer = st.get("offer")
    if not offer:
        return None
    voters = _voters(c, room["id"])
    ids = {a["user_id"] for a in voters}
    need = len(ids) // 2 + 1
    yes, no = [u for u in offer["yes"] if u in ids], [u for u in offer["no"] if u in ids]
    if ids and len(yes) >= need:
        st["offer"] = None
        return _begin_closing(st, offer["title"], r, False, SOURCES.get(offer["source"], ""))
    if ids and len(no) > len(ids) - need:
        st["offer"] = None
        st["cooldown"] = r + max(4, cf["scene"] or 4)
        return messages.closing_kept(offer["title"], [shared.actor_label(a) for a in voters if a["user_id"] in no])
    return None


def _begin_closing(st: dict[str, Any], title: str, r: int, forced: bool, reason: str) -> Any:
    st["closing"] = {"title": title, "since": r, "until": r + CLOSING_ROUNDS, "forced": forced}
    st["act_offer"] = None
    return messages.closing_start(title, CLOSING_ROUNDS, forced, reason)


def offer_card(c: sqlite3.Connection, room: sqlite3.Row, st: dict[str, Any]) -> Any:
    offer = st["offer"]
    voters = _voters(c, room["id"])
    names = {a["user_id"]: shared.actor_label(a) for a in voters}
    return messages.closing_offer(offer["title"], SOURCES.get(offer["source"], ""), offer["source"],
                                  [names[u] for u in offer["yes"] if u in names], [names[u] for u in offer["no"] if u in names],
                                  [names[u] for u in names if u not in offer["yes"] and u not in offer["no"]],
                                  len(names) // 2 + 1, _offer_left(st, current_round(c, room["id"])))


def _all_down(c: sqlite3.Connection, room: sqlite3.Row) -> bool:
    pack_rules = shared.world(room)["pack"]["rules"]
    ref = pack_rules.get("failureResource")
    if not ref or not pack_rules.get("failureCost"):
        return False
    from .hosted import eligible_actors
    actors = eligible_actors(c, room["id"])
    if not actors:
        return False
    for a in actors:
        res = loads(a["resources_json"], {}).get(ref)
        if not res or res["current"] > res.get("min", 0):
            return False
    return True


def after_narration(c: sqlite3.Connection, room: sqlite3.Row, turn: sqlite3.Row, round_number: int,
                    scene_changed: bool, rushing: bool = False) -> Plan:
    """Run inside commit_narration's transaction, after the story is stored and before the next turn opens.

    rushing: the next round is a 快团 round, where the world cannot take a turn of its own; a due push
    then goes into the next narration's notes instead.
    """
    plan = Plan()
    receipt = loads(turn["receipt_json"], {}) or {}
    if receipt.get("kind") == "finale":
        return plan
    st, cf = state(room, turn["round"]), conf(room)
    if st.get("branch") or branch_ending(c, room["id"]) is not None:
        cf = {**cf, "ending": False, "hard": 0}     # the ending play has taken the story to its end
        st.update(branch=True, offer=None)
    if st.get("push_due"):                          # this narration carried the world's push
        st["push_due"] = None
        st["scene_since"] = turn["round"]
    if scene_changed or receipt.get("kind") in ("host_advance", "pace_push", "world_pulse"):
        st["scene_since"] = round_number if scene_changed else turn["round"]
    chosen = _picked_closing(turn)
    picked = chosen[0][1] if chosen else None
    busy = st.get("closing") or st.get("finale") or st.get("epilogue")
    if picked is not None and cf["ending"] and not busy:
        users = []
        for actor_id, _ in chosen:                  # in a rush round everyone who picked it agrees at once
            row = c.execute("SELECT user_id FROM actors WHERE id=?", (actor_id,)).fetchone()
            if row is not None and row["user_id"] not in users:
                users.append(row["user_id"])
        offer = st.get("offer")
        if not offer:
            _offer(st, room, "option", picked, round_number, users)
        else:                                       # picking a closing option is a yes to the open proposal
            if not offer["title"]:                  # and names it when it had no ending yet
                offer["title"] = ending_title(room, picked)
            for user in users:
                if user not in offer["yes"]:
                    offer["yes"].append(user)
                if user in offer["no"]:
                    offer["no"].remove(user)
        settled = _settle(c, room, st, round_number, cf)
        plan.cards.append(settled if settled is not None else offer_card(c, room, st))
    elif picked is not None and st.get("closing") and not st["closing"]["title"]:
        st["closing"]["title"] = ending_title(room, picked)   # the wind-down had no direction yet: this is it
        plan.cards.append(messages.notice("结局方向定了", f"「{st['closing']['title']}」：再过 {max(0, st['closing']['until'] - round_number)} 轮写终章。",
                                          "还有想交代的事、想说的话，趁这几轮"))
    elif cf["ending"] and not busy and not st.get("offer") and round_number >= st.get("cooldown", 0) and _all_down(c, room):
        _offer(st, room, "down", "败局", round_number)
        plan.cards.append(offer_card(c, room, st))
    if room["state"] == "running" and round_number > st.get("seen", 0):
        st["seen"] = round_number
        _new_round(c, room, st, cf, round_number, plan, rushing)
    _save(c, room["id"], st)
    return plan


def _picked_closing(turn: sqlite3.Row) -> list[tuple[str, str]]:
    """(actor id, ending name) for everyone whose action this turn was a closing option; a rush round has several."""
    closing = [ch for ch in loads(turn["choices_json"], []) or [] if ch.get("closing")]
    if not closing:
        return []
    rush = loads(turn["data_json"], {}).get("rush")
    acts = ([(ref, e.get("action") or "") for ref, e in rush.get("entries", {}).items() if not e.get("skip")] if rush
            else [(turn["actor_id"], turn["action_text"] or "")])
    picked = []
    for ref, action in acts:
        ch = next((ch for ch in closing if action.startswith(ch["text"])), None)
        if ch is not None:
            picked.append((ref, ch["closing"]))
    return picked


def _new_round(c: sqlite3.Connection, room: sqlite3.Row, st: dict[str, Any], cf: dict[str, Any], r: int, plan: Plan,
               rushing: bool = False) -> None:
    n = counts(st, r)
    if st.get("finale") or st.get("epilogue"):
        return
    if st.get("closing"):
        if r >= st["closing"]["until"]:
            plan.finale = st["closing"]["title"]
            st["finale"] = {"title": plan.finale}
            st["closing"] = None
        return
    if cf["hard"] and n["story"] >= cf["hard"]:
        title = (st.get("offer") or {}).get("title", "")
        st["offer"] = None
        plan.cards.append(_begin_closing(st, title, r, True, f"已经走过 {n['story']} 轮，到了本桌的篇幅上限"))
        return
    offer = st.get("offer")
    if offer and r >= offer["round"] + OFFER_ROUNDS:   # no majority in time: the story goes on
        st["offer"] = None
        st["cooldown"] = r + max(4, cf["scene"] or 4)
        plan.cards.append(messages.closing_kept(offer["title"], [], expired=True))
    can_offer = cf["ending"] and not st.get("offer") and r >= st.get("cooldown", 0)
    if can_offer and cf["target"] and n["story"] >= cf["target"]:
        _offer(st, room, "target", "", r)
        plan.cards.append(offer_card(c, room, st))
        can_offer = False
    limit = rules.act_rounds(cf, room["act"])
    if limit and n["act"] >= limit:
        if last_act(room):
            if can_offer and st.get("act_end_offered") != room["act"]:
                st["act_end_offered"] = room["act"]
                _offer(st, room, "act_end", "", r)
                plan.cards.append(offer_card(c, room, st))
        elif not st.get("act_offer"):
            coming = next_act(room)
            st["act_offer"] = {"round": r, "target": coming["number"]}
            plan.cards.append(messages.act_offer(coming["number"], coming["title"], coming["lead"], cf["grace"], n["act"],
                                                 lifecycle.improvises(room)))
        elif r >= st["act_offer"]["round"] + cf["grace"]:
            plan.act_change = st["act_offer"]["target"]
            return
    if cf["scene"] and n["scene"] >= cf["scene"] + cf["grace"]:
        if rushing:            # the next rush narration pushes; its count starts again once it is written
            if not st.get("push_due"):
                st["push_due"] = n["scene"]
                plan.push_note = n["scene"]
        else:
            plan.push = n["scene"]
            st["scene_since"] = r


def act_changed(c: sqlite3.Connection, room: sqlite3.Row) -> None:
    """A new act (by hand or by itself) starts the act and scene counts again."""
    st = state(room, current_round(c, room["id"]))
    r = current_round(c, room["id"])
    st.update(act_since=r, scene_since=r, act_offer=None)
    _save(c, room["id"], st)


def scene_reset(c: sqlite3.Connection, room: sqlite3.Row) -> None:
    st = state(room, current_round(c, room["id"]))
    st["scene_since"] = current_round(c, room["id"])
    _save(c, room["id"], st)


# ---------------------------------------------------------------- what the model and the players see
def story_notes(room: sqlite3.Row, r: int) -> list[str]:
    """Lines for the table notes of a narration in round r."""
    st, cf = state(room, r), conf(room)
    if st.get("finale") or st.get("epilogue"):
        return []
    closing = st.get("closing")
    if closing:
        left = max(0, closing["until"] - r)
        return ["节奏 · 收尾阶段：" + (f"结局方向是「{closing['title']}」；" if closing["title"] else "")
                + f"再过 {left} 轮写终章。不再开新的支线、不引入新的重要人物；把已有伏笔、人物关系和未了之事交代清楚；"
                "选项都朝收尾的方向写，可以有不同的收尾方式。"
                + ("" if closing["title"] else "其中一项写成收束选项（“收束：结局名——走向”），结局名照抄结局条件里最贴近已发生之事的一个，"
                   "都不贴近时自拟四到八字；玩家选它就定下结局方向。")]
    n, lines = counts(st, r), []
    if st.get("push_due"):
        lines.append(f"节奏（世界推进）：这个场景已经停留 {st['push_due']} 轮。本段正文由世界推动局势：让一项局面向前走一步、"
                     "新的人物或消息登场，或转到新的场景（转场时更新 progress.scene）；变化从已发生的事里长出来，不强行拉回预设主线。")
    if st.get("offer") or (cf["target"] and n["story"] >= cf["target"]):
        lines.append(f"节奏：故事已经走过 {n['story']} 轮，接近这一桌的篇幅。开始收拢线索；选项里至少写一项收束选项。")
    elif last_act(room) and rules.act_rounds(cf, room["act"]) and n["act"] >= rules.act_rounds(cf, room["act"]):
        lines.append("节奏：这是最后一幕，已经走满预定的轮数。开始收拢已有线索，为结局铺路；选项里可以出现收束选项。")
    offer = st.get("act_offer")
    if offer:
        left = max(1, offer["round"] + cf["grace"] - r)
        coming = next_act(room)
        if coming["title"]:
            lines.append(f"节奏：本幕即将结束（约 {left} 轮后进入第 {coming['number']} 幕 · {coming['title']}"
                         + (f"——{coming['lead']}" if coming["lead"] else "") + "）。正文开始把局面引向下一幕，但不直接跳过去，也不改写已发生的事。")
        else:
            lines.append(f"节奏：本幕即将结束（约 {left} 轮后开启新的一幕）。正文开始收拢这一段的线索，为新的一段故事铺路。")
    if cf["scene"] and n["scene"] >= cf["scene"] and not st.get("push_due"):
        lines.append(f"节奏：这个场景已经持续 {n['scene']} 轮。本段正文必须让局势发生实质变化：推进一项局面、"
                     "让新的人物或消息登场，或转到新场景（转场时更新 progress.scene）。变化从已发生的事里长出来，不强行拉回预设主线。")
    return lines


def closing_open(room: sqlite3.Row) -> bool:
    """Whether picking a closing option would propose winding down (the badge on the turn card says so)."""
    st = loads(room["data_json"], {}).get("hosted", {}).get("pacing") or {}
    return conf(room)["ending"] and not (st.get("closing") or st.get("finale") or st.get("epilogue") or st.get("branch"))


def mark_branch(c: sqlite3.Connection, room_id: str) -> None:
    """The ending play entered an ending: drop any closing proposal and stop proposing new ones."""
    if branch_ending(c, room_id) is None:
        return
    room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    st = state(room, current_round(c, room_id))
    st.update(branch=True, offer=None)
    _save(c, room_id, st)


def band(room: sqlite3.Row, r: int, c: sqlite3.Connection | None = None) -> tuple[str, str] | None:
    """(label, detail) for the line on the turn card, or None when nothing is coming."""
    st, cf = state(room, r), conf(room)
    if st.get("finale") or st.get("epilogue"):
        return None
    closing = st.get("closing")
    if closing:
        left = max(0, closing["until"] - r)
        return "收尾阶段", (f"结局「{closing['title']}」 · " if closing["title"] else "") + (f"再过 {left} 轮写终章" if left else "这一轮后写终章")
    offer = st.get("offer")
    if offer:
        title = f"「{offer['title']}」" if offer["title"] else "故事"
        return "收尾提议", (f"要不要给{title}收尾？在座的人发送 /团 收尾 同意 或 /团 收尾 再玩；"
                            f"{_offer_left(st, r)} 轮内没过半就继续冒险")
    n = counts(st, r)
    if st.get("act_offer"):
        left = max(1, st["act_offer"]["round"] + cf["grace"] - r)
        return "本幕将尽", f"{left} 轮后进入第 {st['act_offer']['target']} 幕；主持人可以 /团 主持 换幕 提前进入"
    if cf["scene"] and n["scene"] >= cf["scene"]:
        left = cf["scene"] + cf["grace"] - n["scene"]
        return "局势在酝酿", f"这个场景已经 {n['scene']} 轮，正文会让局面变化" + (f"；{left} 轮后世界会自己推进" if left > 0 else "")
    if cf["scene"] and cf["scene"] > 1 and n["scene"] == cf["scene"] - 1:
        return "局势在酝酿", f"这个场景已经 {n['scene']} 轮，下一轮起局面会有变化"
    return None


def view(room: sqlite3.Row, r: int) -> dict[str, Any]:
    """Everything the 节奏 card and the WebUI show."""
    st, cf = state(room, r), conf(room)
    n = counts(st, r)
    scene = loads(room["scene_json"], {}).get("title", "")
    act = lifecycle.current_act(room) or {}
    own = loads(room["data_json"], {}).get("hosted", {}).get("pacing_own") or {}
    world_block = shared.world(room)["pack"].get("pacing")
    source = "主持人调整" if own else "世界设置" if world_block else "默认"
    pending = band(room, r)
    offer = st.get("offer")
    stage = ("epilogue" if st.get("epilogue") else "finale" if st.get("finale") else "closing" if st.get("closing")
             else "offer" if offer else "")
    return {"scene": {"done": n["scene"], "limit": cf["scene"], "title": scene},
            "act": {"done": n["act"], "limit": rules.act_rounds(cf, room["act"]), "number": room["act"], "title": act.get("title", ""),
                    "last": last_act(room)},
            "story": {"done": n["story"], "target": cf["target"], "hard": cf["hard"]},
            "grace": cf["grace"], "ending": cf["ending"], "preset": cf["preset"], "off": cf["off"], "source": source,
            "own": {k: v for k, v in own.items() if k in ("scene", "act", "target", "hard")},
            "state": {"label": pending[0], "detail": pending[1]} if pending else None,
            "stage": stage, "branch": bool(st.get("branch")),
            "offer": None if not offer else {"title": offer["title"], "source": SOURCES.get(offer["source"], ""),
                                              "yes": len(offer["yes"]), "no": len(offer["no"]), "left": _offer_left(st, r)},
            "closing": st.get("closing"), "epilogue": None if not st.get("epilogue") else {
                "title": st["epilogue"]["title"], "written": len(st["epilogue"]["texts"]), "deadline": st["epilogue"]["deadline"]}}


def stage(c: sqlite3.Connection, room: sqlite3.Row) -> dict[str, Any] | None:
    """Where the wind-down stands, for the WebUI's table cards and its to-do list; None while the story just runs."""
    if room["state"] not in ("running", "paused"):
        return None
    st = loads(room["data_json"], {}).get("hosted", {}).get("pacing") or {}
    paused = room["state"] == "paused"
    if st.get("epilogue"):
        from .hosted import eligible_actors
        ep = st["epilogue"]
        actors = eligible_actors(c, room["id"])
        written = sum(a["id"] in ep["texts"] for a in actors)
        return {"key": "epilogue", "label": "尾声中", "tone": "gold", "icon": "feather",
                "detail": (f"结局「{ep['title']}」 · " if ep["title"] else "") + f"已写 {written}/{len(actors)}" + (" · 暂停中" if paused else ""),
                "deadline_at": None if paused else ep["deadline"], "written": written, "total": len(actors)}
    if st.get("finale"):
        from .hosted import current_turn
        turn = current_turn(c, room["id"])
        failed = turn is not None and turn["state"] == "narration_failed"
        return {"key": "finale", "label": "终章没写出来" if failed else "正在写终章", "tone": "err" if failed else "", "icon": "alert" if failed else "flag",
                "detail": "主持人重试，或跳过直接写尾声" if failed else (f"结局「{st['finale']['title']}」" if st["finale"].get("title") else "AI 正在写最后一段")}
    r = current_round(c, room["id"])
    if st.get("closing"):
        closing = st["closing"]
        left = max(0, closing["until"] - r)
        return {"key": "closing", "label": "收尾阶段", "tone": "", "icon": "flag",
                "detail": (f"结局「{closing['title']}」 · " if closing["title"] else "") + (f"再过 {left} 轮写终章" if left else "这一轮后写终章")}
    offer = st.get("offer")
    if offer:
        voters = {a["user_id"] for a in _voters(c, room["id"])}
        need = len(voters) // 2 + 1
        yes = sum(u in voters for u in offer["yes"])
        return {"key": "offer", "label": "收尾提议待表决", "tone": "gold", "icon": "vote",
                "detail": (f"「{offer['title']}」 · " if offer["title"] else "") + f"同意 {yes}/{need} · 还剩 {_offer_left(st, r)} 轮",
                "yes": yes, "need": need}
    return None


def status_line(room: sqlite3.Row, r: int) -> str:
    v = view(room, r)
    parts = []
    if v["scene"]["limit"]:
        parts.append(f"场景 {v['scene']['done']}/{v['scene']['limit']}")
    if v["act"]["limit"]:
        parts.append(f"第 {v['act']['number']} 幕 {v['act']['done']}/{v['act']['limit']}")
    if v["story"]["target"]:
        parts.append(f"全程 {v['story']['done']}/{v['story']['target']} 轮")
    line = "节奏：" + (" · ".join(parts) if parts else "不限")
    return line + (f"（{v['state']['label']}）" if v["state"] else "")


# ---------------------------------------------------------------- finale and epilogues
FINALE_ACTION = ("（终章）故事在这里收束{ending}。按已经发生的事写最后一段正文：交代主要人物的去向、核心矛盾的结果和付出的代价，"
                 "预设结局只提供方向，不改写已经发生的事，不留新的悬念；同桌玩家角色只写他们已经做过的事和此刻在场的样子，"
                 "不替他们决定去向，他们会自己写尾声。suggestions 第一项写成“收束：结局名——走向”，结局名{name}；"
                 "其余照常给出，不会使用。")
PUSH_ACTION = ("（世界推进）这个场景已经停留了 {rounds} 轮。由世界推动局势：让一项局面向前走一步、新的人物或消息登场，"
               "或转到新的场景（转场时更新 progress.scene）；变化从已发生的事里长出来，不强行拉回预设主线。"
               "最后把场面交还给 {actor}，选项写 {actor} 接下来可以做的事。")


def narrator_turn(app: "LiteApp", c: sqlite3.Connection, room: sqlite3.Row, kind: str, actor: sqlite3.Row,
                  round_number: int, **values: Any) -> str:
    """A turn no player acts in: the world's push or the finale; the given actor's turn follows a push."""
    label = shared.actor_label(actor)
    if kind == "finale":
        title = values.get("title") or ""
        action = FINALE_ACTION.format(ending=f"，结局：{title}" if title else "",
                                      name=f"就写「{title}」" if title else "照抄结局条件里最贴近这个结果的一个，都不贴近时自拟四到八字")
        lifecycle.auto_snapshot(c, room["id"], f"第 {round_number} 轮 · 终章前")
    else:
        action = PUSH_ACTION.format(rounds=values.get("rounds", 0), actor=label)
    c.execute("UPDATE turns SET state='superseded',updated_at=? WHERE room_id=? AND state IN ('awaiting','narration_failed','review')",
              (now(), room["id"]))
    turn_id = new_id("turn")
    c.execute("INSERT INTO turns(id,room_id,round,actor_id,state,choices_json,action_text,receipt_json,data_json,created_at,updated_at) "
              "VALUES(?,?,?,?,'resolving','[]',?,?,?,?,?)",
              (turn_id, room["id"], round_number, actor["id"], action,
               dumps({"receipt_ref": new_id("receipt"), "kind": kind, **({"title": values.get("title") or ""} if kind == "finale" else {})}),
               dumps({"resume_actor": actor["id"]}), now(), now()))
    app.store.add_event(c, room["id"], "host", "终章" if kind == "finale" else f"世界推进：这个场景已经停留 {values.get('rounds', 0)} 轮")
    return turn_id


def finale_vote_note(voided: str | None) -> str:
    return f"进行中的表决「{voided}」不再结算：故事已经走向终章。" if voided else ""


def finale_written(c: sqlite3.Connection, room: sqlite3.Row, title: str, note: str = "") -> Any:
    """The finale is out: open the epilogues and return the card that asks for them."""
    st = state(room, current_round(c, room["id"]))
    deadline = (datetime.now(UTC) + timedelta(minutes=EPILOGUE_MINUTES)).isoformat(timespec="seconds")
    st.update(finale=None, closing=None, offer=None, epilogue={"title": title, "deadline": deadline, "texts": {}})
    _save(c, room["id"], st)
    return epilogue_card(c, room, st, note)


def finale_title(room: sqlite3.Row, receipt: dict[str, Any], suggestions: list[str]) -> str:
    """The ending's name: the one the finale was asked for, else the one the finale itself gave."""
    if receipt.get("title"):
        return receipt["title"]
    named = next((n for _, n in (closing_name(s) for s in suggestions) if n), "")
    return ending_title(room, named)


def finale_skipped(c: sqlite3.Connection, room: sqlite3.Row) -> Any:
    """/团 主持 跳过 on a finale that failed: no finale text, straight to the epilogues."""
    st = state(room, current_round(c, room["id"]))
    title = (st.get("finale") or st.get("closing") or {}).get("title", "")
    card = finale_written(c, room, title, note="终章没写出来，主持人跳过了它：故事停在上一段正文，直接写尾声。")
    return card


def epilogue_card(c: sqlite3.Connection, room: sqlite3.Row, st: dict[str, Any], note: str = "") -> Any:
    ep = st["epilogue"]
    from .hosted import eligible_actors
    actors = eligible_actors(c, room["id"])
    written = [(shared.actor_label(a), ep["texts"][a["id"]]) for a in actors if a["id"] in ep["texts"]]
    waiting = [shared.actor_label(a) for a in actors if a["id"] not in ep["texts"]]
    left = max(1, round((datetime.fromisoformat(ep["deadline"]) - datetime.now(UTC)).total_seconds() / 60))
    return messages.epilogue_call(ep["title"], written, waiting, left, note)


def epilogue_resumed(c: sqlite3.Connection, room: sqlite3.Row) -> Any | None:
    """Back from a pause while the epilogues were open: the clock picks up where it stopped (at least 2 minutes)."""
    st = state(room, current_round(c, room["id"]))
    ep = st.get("epilogue")
    if not ep:
        return None
    left = ep.pop("left", None)
    if left is None:
        left = (datetime.fromisoformat(ep["deadline"]) - datetime.now(UTC)).total_seconds()
    ep["deadline"] = (datetime.now(UTC) + timedelta(seconds=max(RESUME_SECONDS, int(left)))).isoformat(timespec="seconds")
    _save(c, room["id"], st)
    return epilogue_card(c, room, st, "故事回来了，接着写尾声：计时从暂停的地方继续。")


def epilogues_done(c: sqlite3.Connection, room_id: str) -> bool:
    """Everyone at the table has written an epilogue (checked when the story comes back from a pause)."""
    from .hosted import eligible_actors
    room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    ep = state(room).get("epilogue")
    actors = eligible_actors(c, room_id)
    return bool(ep) and bool(actors) and all(a["id"] in ep["texts"] for a in actors)


def after_restore(c: sqlite3.Connection, room_id: str) -> bool:
    """A save from the moment the finale was started has no finale turn to finish: go back to the last
    round of the wind-down instead, so the finale comes at the next round or by /团 主持 收尾 终章."""
    room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    st = loads(room["data_json"], {}).get("hosted", {}).get("pacing")
    if not st or not st.get("finale"):
        return False
    from .hosted import current_turn
    turn = current_turn(c, room_id)
    if turn is not None and turn["state"] != "awaiting" and (loads(turn["receipt_json"], {}) or {}).get("kind") == "finale":
        return False
    r = current_round(c, room_id)
    st["closing"] = {"title": st["finale"].get("title", ""), "since": r, "until": r, "forced": True}
    st["finale"] = None
    _save(c, room_id, st)
    return True


def ending_from_state(room: sqlite3.Row) -> dict[str, Any] | None:
    """The ending /团 完结 uses when the host names none: the one being written, with the epilogues so far."""
    st = loads(room["data_json"], {}).get("hosted", {}).get("pacing") or {}
    ep = st.get("epilogue")
    if ep:
        return {"title": ep["title"], "epilogues": [{"actor_ref": k, "text": v} for k, v in ep["texts"].items()]}
    closing = st.get("closing") or st.get("finale")
    return {"title": closing["title"]} if closing and closing.get("title") else None


async def _finish(app: "LiteApp", room_id: str, by: str) -> Reply:
    with app.store.read() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    ending = ending_from_state(room) or {"title": ""}
    return await lifecycle.complete_story(app, room_id, ending if ending.get("title") or ending.get("epilogues") else None, by=by)


def in_epilogue(room: sqlite3.Row) -> bool:
    return bool((loads(room["data_json"], {}).get("hosted", {}).get("pacing") or {}).get("epilogue"))


def turn_block(room: sqlite3.Row) -> str | None:
    """Why no turn is open right now, when the story is between its finale and its ending."""
    st = loads(room["data_json"], {}).get("hosted", {}).get("pacing") or {}
    if st.get("epilogue"):
        return "终章已经写完，正在征集尾声：发送 /团 尾声 一句话，写下你的角色最后的去向。"
    if st.get("finale"):
        return "终章正在生成，请稍候。"
    return None


# ---------------------------------------------------------------- commands
def _room(app: "LiteApp", caller: Caller, *states: str) -> sqlite3.Row:
    room = shared.require_room(app, caller, *(states or ("running", "paused")))
    shared.require_play(app, caller, "playActions")
    return room


async def show(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _room(app, caller, "running", "paused")
    with app.store.read() as c:
        v = view(room, current_round(c, room["id"]))
    reply = Reply().say(messages.pace_card(v, shared.is_host(app, caller, room)))
    reply.private_only = True
    return reply


async def vote(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _room(app, caller)
    word = args.strip()
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
        r = current_round(c, room["id"])
        st, cf = state(room, r), conf(room)
        if not st.get("offer"):
            if st.get("closing"):
                raise UserError(f"已经在收尾了：再过 {max(0, st['closing']['until'] - r)} 轮写终章。")
            if st.get("epilogue"):
                raise UserError("终章已经写完：发送 /团 尾声 一句话，写下你的角色最后的去向。")
            raise UserError("现在没有收尾提议。选项里出现“收束”时选它，或等故事走到预期篇幅，就会发起收尾表决；"
                            "主持人也可以直接发送 /团 主持 收尾。")
        if not word:
            return Reply().say(offer_card(c, room, st))
        mine = [a for a in _voters(c, room["id"]) if a["user_id"] == caller.user_id]
        if not mine:
            raise UserError("入座并建好角色的玩家才能表决收尾。")
        if word.startswith(YES):
            side, other = "yes", "no"
        elif word.startswith(NO):
            side, other = "no", "yes"
        else:
            raise UserError("写法：/团 收尾 同意，或 /团 收尾 再玩")
        offer = st["offer"]
        if caller.user_id not in offer[side]:
            offer[side].append(caller.user_id)
        if caller.user_id in offer[other]:
            offer[other].remove(caller.user_id)
        settled = _settle(c, room, st, r, cf)
        card = settled if settled is not None else offer_card(c, room, st)
        _save(c, room["id"], st)
        app.store.add_event(c, room["id"], "vote", f"{shared.actor_label(mine[0])} 对收尾提议：{'同意' if side == 'yes' else '再玩'}",
                            actor_id=mine[0]["id"])
    return Reply().say(card)


async def host_close(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _room(app, caller)
    shared.require_host(app, caller, room)
    word = args.strip()
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
        r = current_round(c, room["id"])
        st = state(room, r)
        if st.get("epilogue"):
            raise UserError("终章已经写完，正在等尾声；不等了就发送 /团 完结 直接落幕。")
        if st.get("finale"):
            raise UserError(shared.ending_step(room))
        if word in ("取消", "撤回"):
            if not st.get("offer") and not st.get("closing"):
                raise UserError("现在没有收尾提议，也不在收尾阶段。")
            st.update(offer=None, closing=None, cooldown=r + max(4, conf(room)["scene"] or 4))
            _save(c, room["id"], st)
            app.store.add_event(c, room["id"], "host", "主持人取消了收尾")
            return Reply().say(messages.notice("收尾已取消", "故事照常继续，几轮之内不会再自动提议收尾。",
                                               "想收尾时发送 /团 主持 收尾 结局名"))
        if word in ("终章", "立即", "现在"):
            finale = (st.get("closing") or st.get("offer") or {}).get("title", "")
            if not finale and st.get("branch"):
                entered = branch_ending(c, room["id"])
                finale = loads(entered["document_json"], {}).get("title", "") if entered is not None else ""
        else:
            finale = None
        title = ending_title(room, word[:24]) or (st.get("offer") or st.get("closing") or {}).get("title", "")
        if finale is None:
            st["offer"] = None
            card = _begin_closing(st, title, r, False, SOURCES["host"])
            _save(c, room["id"], st)
            app.store.add_event(c, room["id"], "host", "主持人开始收尾" + (f"：{title}" if title else ""))
    if finale is not None:
        return await write_finale_now(app, caller, room, finale)
    return Reply().say(card)


async def write_finale_now(app: "LiteApp", caller: Caller, room: sqlite3.Row, title: str) -> Reply:
    from . import hosted
    with app.store.read() as c:
        turn = hosted.current_turn(c, room["id"])
    if room["state"] != "running" or turn is None or turn["state"] != "awaiting":
        raise UserError("等当前回合结算完、故事在进行中时再写终章。")
    from .collaboration import void_open
    with app.store.tx() as c:
        holder = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
        st = state(room, turn["round"])
        st.update(finale={"title": title}, closing=None, offer=None)
        _save(c, room["id"], st)
        finale = narrator_turn(app, c, room, "finale", holder, turn["round"], title=title)
        voided = void_open(c, room["id"])
    await caller.send(messages.notice("正在写终章", (f"结局：{title}。" if title else "") + "写完后每位玩家可以留一句尾声。"
                                      + finale_vote_note(voided)))
    async with app.lock(room["id"]):
        return await hosted.narrate(app, room["id"], finale, advance=False)


async def epilogue(app: "LiteApp", caller: Caller, text: str) -> Reply:
    """/团 尾声 一句话 while the epilogues are open."""
    room = _room(app, caller, "running", "paused")
    text = " ".join(text.split())
    if not 1 <= len(text) <= EPILOGUE_LIMIT:
        raise UserError(f"尾声写 1–{EPILOGUE_LIMIT} 字，例如 /团 尾声 她把契约烧了，回到了地表。")
    from .hosted import eligible_actors
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
        st = state(room, current_round(c, room["id"]))
        if not st.get("epilogue"):
            entered = branch_ending(c, room["id"])
            if entered is not None:
                raise UserError(f"结局 #{entered['seq']} 已经进入：发送 /团 尾声 #{entered['seq']} 内容，写下你的角色的去向。")
            raise UserError("现在不是写尾声的时候：故事写完终章后，每位玩家用 /团 尾声 一句话 写下角色的去向。")
        actor = next((a for a in eligible_actors(c, room["id"]) if a["user_id"] == caller.user_id), None)
        if actor is None:
            raise UserError("入座并建好角色的玩家才能写尾声。")
        st["epilogue"]["texts"][actor["id"]] = text
        _save(c, room["id"], st)
        app.store.add_event(c, room["id"], "play", f"{shared.actor_label(actor)} 的尾声：{text}", actor_id=actor["id"])
        done = all(a["id"] in st["epilogue"]["texts"] for a in eligible_actors(c, room["id"]))
        paused = room["state"] == "paused"
        card = None if done and not paused else epilogue_card(
            c, room, st, "尾声都写齐了：故事正在暂停，主持人开演后就落幕。" if done else "")
    if done and not paused:
        return await _finish(app, room["id"], caller.user_id)
    return Reply().say(card)


async def host_pacing(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _room(app, caller)
    shared.require_host(app, caller, room)
    words = args.split()
    if not words:
        return await show(app, caller, "")
    head = words[0]
    numbers = {"场景": "scene", "每幕": "act", "幕": "act", "全程": "target", "全局": "target", "目标": "target", "上限": "hard"}
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
        r = current_round(c, room["id"])
        own = dict(loads(room["data_json"], {}).get("hosted", {}).get("pacing_own") or {})
        st, cf = state(room, r), conf(room)
        if head in ("默认", "恢复", "重置"):
            own, said = {}, "节奏恢复世界设置"
        elif head in rules.PRESETS:
            own["preset"] = head
            said = f"节奏调为“{head}”" + ("" if head == "标准" else "：场景、每幕和全程轮数都按比例" + ("缩短" if head == "短" else "放长"))
        elif head in ("关", "关闭"):
            own["off"], said = True, "自动推进关闭：不再催场景、换幕或到点提议收尾；收束选项和 /团 主持 收尾 照常可用"
        elif head in ("开", "开启"):
            own.pop("off", None)
            said = "自动推进重新开启"
        elif head == "延后":
            n = counts(st, r)
            if st.get("act_offer"):
                st["act_offer"]["round"] += cf["grace"]
                said = f"换幕延后 {cf['grace']} 轮"
            elif cf["scene"] and n["scene"] >= cf["scene"]:
                st["scene_since"] += cf["grace"]
                said = f"世界推进延后 {cf['grace']} 轮"
            else:
                raise UserError("现在没有要延后的推进。想整体放慢，发送 /团 主持 节奏 长。")
            _save(c, room["id"], st)
        elif head in numbers and len(words) > 1 and words[1].isdigit():
            key, value = numbers[head], int(words[1])
            top = 100 if key in ("scene", "act") else 1000
            if value > top:
                raise UserError(f"{head}轮数写 0–{top}，0 表示这一层不催。")
            own[key] = value
            said = f"{head}改为 {value} 轮" if value else f"{head}不再设轮数"
        else:
            raise UserError("写法：/团 主持 节奏 [短|标准|长｜场景 4｜每幕 8｜全程 30｜上限 45｜延后｜关|开｜默认]")
        _save(c, room["id"], None, own)
        app.store.add_event(c, room["id"], "host", "主持人调整节奏：" + said)
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone()
        v = view(room, r)
    return Reply().say(messages.pace_card(v, True, said))


async def on_roster_changed(room_id: str, actor_id: str, change: str, *, app: "LiteApp") -> Reply:
    """Someone came, left or stepped away: the majority a proposal needs and the epilogues still due change."""
    from .hosted import eligible_actors
    finish = False
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        if room is None or room["state"] != "running":
            return Reply()
        r = current_round(c, room_id)
        st, cf = state(room, r), conf(room)
        card = None
        if st.get("offer"):
            card = _settle(c, room, st, r, cf)
            if card is not None:
                _save(c, room_id, st)
        elif st.get("epilogue"):
            actors = eligible_actors(c, room_id)
            finish = bool(actors) and all(a["id"] in st["epilogue"]["texts"] for a in actors)
    if finish:
        async with app.lock(room_id):
            return await _finish(app, room_id, "system")
    return Reply().say(card) if card is not None else Reply()


async def on_room_paused(room_id: str, *, app: "LiteApp") -> Reply:
    """A pause stops the epilogue clock too: remember what was left."""
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        st = state(room, current_round(c, room_id))
        ep = st.get("epilogue")
        if ep and "left" not in ep:
            ep["left"] = max(0, int((datetime.fromisoformat(ep["deadline"]) - datetime.now(UTC)).total_seconds()))
            _save(c, room_id, st)
    return Reply()


async def on_tick(*, app: "LiteApp") -> Reply:
    """Epilogues that ran out of time end the story with whatever was written."""
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    with app.store.read() as c:
        due = c.execute("SELECT id,umo FROM rooms WHERE state='running' "
                        "AND json_extract(data_json,'$.hosted.pacing.epilogue.deadline')<=?", (stamp,)).fetchall()
    for row in due:
        if app.lock(row["id"]).locked():
            continue
        async with app.lock(row["id"]):
            reply = await _finish(app, row["id"], "system")
        await app.notifier.send(row["umo"], ["尾声时间到，故事在这里落幕。"] + reply.messages)
    return Reply()


def install(app: "LiteApp") -> None:
    r = app.router
    r.register("节奏", show, summary="看本桌节奏：场景、本幕和全程走了几轮，接下来会发生什么", topic="行动", private="self")
    r.register("收尾", vote, summary="对收尾提议表决：同意就开始收尾，再玩就继续冒险", usage="/团 收尾 [同意|再玩]",
               topic="行动", private="room")
    r.register("主持 节奏", host_pacing, summary="调整本桌节奏：长短档、各层轮数、延后一次推进或关闭自动推进",
               usage="/团 主持 节奏 [短|标准|长｜场景 4｜每幕 8｜全程 30｜上限 45｜延后｜关|开｜默认]", topic="主持")
    r.register("主持 收尾", host_close, summary="直接开始收尾、立刻写终章，或取消收尾",
               usage="/团 主持 收尾 [结局名｜终章｜取消]", topic="主持")

    async def tick(**_: Any) -> Reply:
        return await on_tick(app=app)

    async def roster(room_id: str, actor_id: str = "", change: str = "", **_: Any) -> Reply:
        return await on_roster_changed(room_id, actor_id, change, app=app)

    async def paused(room_id: str, **_: Any) -> Reply:
        return await on_room_paused(room_id, app=app)
    app.hooks.on("tick", tick)
    app.hooks.on("roster_changed", roster)
    app.hooks.on("room_paused", paused)
