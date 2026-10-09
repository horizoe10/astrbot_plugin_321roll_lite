"""Battle report card and cheers: something to share from a table, and a per-act favourite.

/团 喝彩 角色名   anyone in the group cheers one character per act (the latest cheer counts); the act's
                 favourite is announced on the next act card and the whole story's on the ending card.
/团 战报          a report of the table so far: cast, acts reached, rounds, checks, critical successes and
                 fumbles, favourites and a quoted line of public story.  It only reads public facts.
"""
from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING, Any

from .. import messages, shared
from ..commands import Caller, Reply, UserError
from ..rooms import lifecycle
from ..storage import loads, now

if TYPE_CHECKING:
    from ..app import LiteApp

OUTCOME_WORDS = {"大成功": "critical", "大失败": "fumble", "成功": "success", "失败": "failure"}
_PLAY_OUTCOME = re.compile(r"→ (大成功|大失败|成功|失败)")


def check_outcomes(c: sqlite3.Connection, room_id: str, after: int = 0) -> list[tuple[str | None, str]]:
    """(actor id, outcome) of every check in the story and in plays after event id 'after', outcome one of
    OUTCOME_WORDS' values or ''."""
    rows = c.execute("SELECT kind,actor_id,text,data_json FROM events WHERE room_id=? AND "
                     "(kind='check' OR (kind='play' AND text LIKE '%【检定】%')) AND id>? ORDER BY id", (room_id, after)).fetchall()
    result = []
    for r in rows:
        if r["kind"] == "check":
            outcome = loads(r["data_json"], {}).get("outcome") or ""
        else:
            found = _PLAY_OUTCOME.search(r["text"])
            outcome = OUTCOME_WORDS[found.group(1)] if found else ""
        result.append((r["actor_id"], outcome))
    return result


def act_recap(c: sqlite3.Connection, room_id: str) -> dict[str, int]:
    """Actions and checks since the current act began (its chapter event, or the start of the story)."""
    since = c.execute("SELECT COALESCE(MAX(id),0) FROM events WHERE room_id=? AND kind='chapter'", (room_id,)).fetchone()[0]
    actions = c.execute("SELECT COUNT(*) FROM events WHERE room_id=? AND kind='narration' AND id>? "
                        "AND data_json NOT LIKE '%\"opening\":true%'", (room_id, since)).fetchone()[0]
    outcomes = [o for _, o in check_outcomes(c, room_id, since)]
    return {"actions": actions, "checks": len(outcomes), "crits": outcomes.count("critical"), "fumbles": outcomes.count("fumble")}


def favourites(c: sqlite3.Connection, room_id: str, act: int | None = None) -> list[tuple[str, int]]:
    """(character, cheers) of the most cheered characters, of one act or of the whole story; ties share."""
    where, args = ("AND h.act=?", (room_id, act)) if act is not None else ("", (room_id,))
    # rowid is insertion order; created_at has one-second steps, so it cannot break a tie on its own
    rows = c.execute("SELECT h.actor_id, COUNT(*) AS n, MIN(h.rowid) AS first FROM cheers h WHERE h.room_id=? " + where +
                     " GROUP BY h.actor_id ORDER BY n DESC, first, h.actor_id", args).fetchall()
    if not rows:
        return []
    top = rows[0]["n"]
    names = {a["id"]: shared.actor_label(a) for a in c.execute("SELECT * FROM actors WHERE room_id=?", (room_id,))}
    return [(names.get(r["actor_id"], "?"), r["n"]) for r in rows if r["n"] == top]


def favourite_line(best: list[tuple[str, int]]) -> str:
    return "、".join(name for name, _ in best) + f"（{best[0][1]} 次喝彩）" if best else ""


async def cheer(app: "LiteApp", caller: Caller, args: str) -> Reply:
    shared.require_play(app, caller, "funReport")
    room = shared.require_room(app, caller, "running", "paused")
    token, _ = shared.split_target(args, caller)
    if not token and not caller.mentions:
        raise UserError("写上要喝彩的角色，例如 /团 喝彩 林晓。")
    with app.store.tx() as c:
        actor = shared.find_actor(c, room["id"], token, caller.mentions)
        if actor["user_id"] == caller.user_id:
            raise UserError("不能给自己的角色喝彩。")
        before = c.execute("SELECT actor_id FROM cheers WHERE room_id=? AND act=? AND user_id=?",
                           (room["id"], room["act"], caller.user_id)).fetchone()
        c.execute("INSERT INTO cheers(room_id,act,user_id,user_name,actor_id,created_at) VALUES(?,?,?,?,?,?) "
                  "ON CONFLICT(room_id,act,user_id) DO UPDATE SET actor_id=excluded.actor_id,user_name=excluded.user_name,"
                  "created_at=excluded.created_at", (room["id"], room["act"], caller.user_id, caller.user_name, actor["id"], now()))
        count = c.execute("SELECT COUNT(*) FROM cheers WHERE room_id=? AND act=? AND actor_id=?",
                          (room["id"], room["act"], actor["id"])).fetchone()[0]
    name = shared.actor_label(actor)
    moved = before is not None and before["actor_id"] != actor["id"]
    return Reply().say(f"{caller.user_name} {'改为' if moved else ''}为 {name} 喝彩，{name} 本幕已有 {count} 次喝彩。"
                       "每人每幕一次，换幕时公布本幕最佳。")


def report_data(c: sqlite3.Connection, room: sqlite3.Row) -> dict[str, Any]:
    room_id = room["id"]
    actors = c.execute("SELECT * FROM actors WHERE room_id=? AND archetype_id IS NOT NULL AND archetype_id<>'' "
                       "ORDER BY order_index,created_at", (room_id,)).fetchall()
    pack = shared.world(room)["pack"]
    archetypes = {a["id"]: a["name"] for a in pack["archetypes"]}
    rounds = c.execute("SELECT COALESCE(MAX(round),0) FROM turns WHERE room_id=?", (room_id,)).fetchone()[0]
    checks = check_outcomes(c, room_id)
    outcomes = [o for _, o in checks]
    turns = {r["actor_id"]: r["n"] for r in c.execute(
        "SELECT actor_id, COUNT(*) AS n FROM turns WHERE room_id=? AND state='done' GROUP BY actor_id", (room_id,))}

    def member(a: sqlite3.Row) -> dict[str, Any]:
        own = [o for actor_id, o in checks if actor_id == a["id"]]
        return {"name": shared.actor_label(a), "role": archetypes.get(a["archetype_id"], ""), "player": a["user_name"],
                "turns": turns.get(a["id"], 0), "checks": len(own), "wins": sum(o in ("success", "critical") for o in own)}

    story = c.execute("SELECT text FROM events WHERE room_id=? AND kind='narration' ORDER BY id DESC LIMIT 1", (room_id,)).fetchone()
    quote = ""
    if story is not None:
        paragraphs = [p.strip() for p in str(story["text"]).split("\n") if len(p.strip()) >= 12]
        quote = paragraphs[-1] if paragraphs else ""
        quote = quote if len(quote) <= 120 else quote[:119] + "…"
    ending = (loads(room["data_json"], {}).get("ending") or {}).get("title", "") if room["state"] == "ended" else ""
    acts = [{"number": a["number"], "title": a["title"], "best": favourite_line(favourites(c, room_id, a["number"]))}
            for a in lifecycle.act_list(room) if a["number"] <= room["act"]]
    return {"title": messages.short_title(pack["title"]), "sub": messages.subtitle(pack["title"]), "world": room["world_id"],
            "state": lifecycle.STATE_LABELS.get(room["state"], room["state"]), "ending": ending,
            "act": room["act"], "total": lifecycle.acts_total(room), "acts": acts,
            "cast": [member(a) for a in actors],
            "rounds": rounds, "checks": len(outcomes), "crits": outcomes.count("critical"), "fumbles": outcomes.count("fumble"),
            "outcomes": {k: outcomes.count(k) for k in ("critical", "success", "failure", "fumble")},
            "best": favourite_line(favourites(c, room_id)), "quote": quote}


async def report(app: "LiteApp", caller: Caller, args: str) -> Reply:
    shared.require_play(app, caller, "funReport")
    room = shared.require_room(app, caller, "running", "paused", "ended")
    with app.store.read() as c:
        data = report_data(c, room)
    endings = shared.world(room).get("presentation", {}).get("endings") or []
    shown = next((e for e in endings if data["ending"] and e.get("name") == data["ending"]), None)
    return Reply().say(messages.battle_report(data, art=f"ending:{shown['id']}" if shown and shown.get("id") else "cover"))


def install(app: "LiteApp") -> None:
    r = app.router
    r.register("喝彩", cheer, summary="为同伴的角色喝彩，每人每幕一次", usage="/团 喝彩 角色名", topic="日常")
    r.register("战报", report, summary="生成这一桌的战报卡", topic="日常", private="self")

