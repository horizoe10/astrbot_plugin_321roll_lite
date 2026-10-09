"""Free dice and dice duels: group pastimes outside the story; nothing here touches a table.

/团 掷 [表达式] [理由]   e.g. 2d6+1, d20, d%, 4d6kh3 (keep the highest 3), 2d20kl1; "优势"/"劣势" with a
                       single d20 roll two and keep one.  In a private chat the roll is a hidden roll.
/团 对决 [@某人] [理由] a challenge; /团 应战 accepts it.  Both roll a d20, ties roll again.
A challenge waits five minutes in the duels table, so a restart in between keeps it.
"""
from __future__ import annotations

import random
import re
import sqlite3
import time
from typing import TYPE_CHECKING, Any

from .. import messages, shared
from ..commands import Caller, Reply, UserError
from ..storage import dumps, loads, now
from . import luck

if TYPE_CHECKING:
    from ..app import LiteApp

MAX_TERMS = 10
MAX_DICE = 100
MAX_SIDES = 1000
DUEL_SECONDS = 300
MAX_TIES = 10
_TERM = re.compile(r"([+-]?)(?:(\d*)[dD](\d+|%)(?:[kK]([hHlL])(\d+))?|(\d+))")
_EXPR = re.compile(r"[0-9dDkKhHlL%+\-]+")

# Replaced in tests.
_rng: random.Random = random.SystemRandom()


def parse(expr: str) -> list[dict[str, Any]]:
    """Dice terms of an expression; raises UserError with the accepted forms."""
    text, terms, pos, dice = expr.strip(), [], 0, 0
    while pos < len(text):
        match = _TERM.match(text, pos)
        if match is None or match.end() == pos or (terms and not match.group(1)):
            raise UserError("看不懂这个骰子式。可以写 d20、2d6+1、d%、4d6kh3（取最高 3 个）、2d20kl1（取最低 1 个）。")
        sign = -1 if match.group(1) == "-" else 1
        if match.group(6) is not None:
            terms.append({"sign": sign, "value": int(match.group(6))})
        else:
            count = int(match.group(2) or 1)
            sides = 100 if match.group(3) == "%" else int(match.group(3))
            keep = (match.group(4).lower(), int(match.group(5))) if match.group(4) else None
            if not 1 <= count or not 2 <= sides <= MAX_SIDES or (keep and not 1 <= keep[1] <= count):
                raise UserError(f"骰子数至少 1 个、面数 2–{MAX_SIDES}，取的个数不能超过骰子数。")
            dice += count
            terms.append({"sign": sign, "count": count, "sides": sides, "keep": keep})
        pos = match.end()
    if not terms:
        raise UserError("请写一个骰子式，例如 /团 掷 2d6+1。")
    if len(terms) > MAX_TERMS or dice > MAX_DICE:
        raise UserError(f"一次最多 {MAX_TERMS} 项、{MAX_DICE} 个骰子。")
    return terms


def roll(terms: list[dict[str, Any]], rng: random.Random) -> tuple[list[dict[str, Any]], int]:
    """Each term with its faces and which were kept, and the total."""
    shown, total = [], 0
    for term in terms:
        if "value" in term:
            shown.append({"label": f"{'-' if term['sign'] < 0 else '+'}{term['value']}", "value": term["value"] * term["sign"]})
            total += term["value"] * term["sign"]
            continue
        faces = [rng.randint(1, term["sides"]) for _ in range(term["count"])]
        kept = [True] * len(faces)
        if term["keep"]:
            how, n = term["keep"]
            order = sorted(range(len(faces)), key=lambda i: faces[i], reverse=how == "h")
            kept = [i in order[:n] for i in range(len(faces))]
        value = sum(f for f, k in zip(faces, kept) if k) * term["sign"]
        sides = "%" if term["sides"] == 100 else str(term["sides"])
        label = f"{term['count'] if term['count'] > 1 else ''}d{sides}" + (f"k{term['keep'][0]}{term['keep'][1]}" if term["keep"] else "")
        shown.append({"label": ("-" if term["sign"] < 0 else "") + label, "faces": faces, "kept": kept, "sides": term["sides"],
                      "value": value})
        total += value
    return shown, total


def _split(args: str) -> tuple[str, str]:
    """(expression, reason): the first word is the expression when it looks like one; d20 by default."""
    words = args.strip().split(maxsplit=1)
    if words and _EXPR.fullmatch(words[0]) and re.search(r"[dD]|^\d+$", words[0]):
        return words[0], (words[1] if len(words) > 1 else "").strip()
    reason = args.strip()
    for word, expr in (("优势", "2d20kh1"), ("劣势", "2d20kl1")):
        if reason.startswith(word):
            return expr, reason[len(word):].strip()
    return "d20", reason


def _log(app: "LiteApp", caller: Caller, kind: str, data: dict[str, Any]) -> None:
    with app.store.tx() as c:
        c.execute("INSERT INTO fun_log(umo,kind,user_id,data_json,created_at) VALUES(?,?,?,?,?)",
                  (caller.umo, kind, caller.user_id, dumps(data), now()))


async def roll_command(app: "LiteApp", caller: Caller, args: str) -> Reply:
    shared.require_play(app, caller, "funDice")
    expr, reason = _split(args)
    terms, total = roll(parse(expr), _rng)
    _log(app, caller, "dice", {"expr": expr, "total": total})
    if caller.in_group:
        with app.store.tx() as c:
            luck.record(c, caller.umo, caller.user_id, caller.user_name, "dice",
                        [f for t in terms if t.get("sides") == 20 for f in t["faces"]])
    return Reply().say(messages.dice_roll(caller.user_name, expr, reason[:60], terms, total, hidden=not caller.in_group))


def _pending(c: sqlite3.Connection, umo: str) -> dict[str, Any] | None:
    """The open challenge of this conversation; expired ones are cleared on the way."""
    c.execute("DELETE FROM duels WHERE expires_at<?", (time.time(),))
    row = c.execute("SELECT data_json FROM duels WHERE umo=?", (umo,)).fetchone()
    return None if row is None else loads(row["data_json"], {})


async def duel_command(app: "LiteApp", caller: Caller, args: str) -> Reply:
    shared.require_play(app, caller, "funDice")
    with app.store.tx() as c:
        pending = _pending(c, caller.umo)
        if args.strip() == "取消":
            if pending is None or pending["by"] != caller.user_id:
                raise UserError("你没有在等人应战的对决。")
            c.execute("DELETE FROM duels WHERE umo=?", (caller.umo,))
            return Reply().say("对决已取消。")
        if pending is not None and pending["by"] != caller.user_id:
            raise UserError(f"{pending['by_name']} 发起的对决还在等人应战，发送 /团 应战 接下它。")
        target = caller.mentions[0] if caller.mentions else None
        if target == caller.user_id:
            raise UserError("不能和自己对决。")
        reason = re.sub(r"@\S+", "", args).strip()[:60]
        data = {"by": caller.user_id, "by_name": caller.user_name, "target": target, "reason": reason}
        c.execute("INSERT OR REPLACE INTO duels(umo,data_json,expires_at) VALUES(?,?,?)",
                  (caller.umo, dumps(data), time.time() + DUEL_SECONDS))
    return Reply().say(messages.duel_challenge(caller.user_name, target, reason, DUEL_SECONDS // 60))


async def accept_command(app: "LiteApp", caller: Caller, args: str) -> Reply:
    shared.require_play(app, caller, "funDice")
    with app.store.tx() as c:
        pending = _pending(c, caller.umo)
        if pending is None:
            raise UserError("现在没有等人应战的对决。发送 /团 对决 发起一场。")
        if pending["by"] == caller.user_id:
            raise UserError("要等别人来应战。不想等了可以发送 /团 对决 取消。")
        if pending["target"] and pending["target"] != caller.user_id:
            raise UserError("这场对决点名了别人。")
        c.execute("DELETE FROM duels WHERE umo=?", (caller.umo,))
    rounds = []
    for _ in range(MAX_TIES):
        pair = (_rng.randint(1, 20), _rng.randint(1, 20))
        rounds.append(pair)
        if pair[0] != pair[1]:
            break
    a, b = rounds[-1]
    winner = "" if a == b else (pending["by_name"] if a > b else caller.user_name)
    _log(app, caller, "duel", {"by": pending["by"], "faces": [a, b]})
    with app.store.tx() as c:
        luck.record(c, caller.umo, pending["by"], pending["by_name"], "duel", [x for x, _ in rounds])
        luck.record(c, caller.umo, caller.user_id, caller.user_name, "duel", [y for _, y in rounds])
    return Reply().say(messages.duel_result(pending["by_name"], caller.user_name, rounds, winner, pending["reason"]))


def install(app: "LiteApp") -> None:
    r = app.router
    r.register(("掷", "掷骰", "骰"), roll_command, summary="自由掷骰，私聊里是暗骰", usage="/团 掷 [2d6+1] [理由]", topic="日常",
               group_only=False)
    r.register("对决", duel_command, summary="发起骰子对决，可以 @ 指定对手", usage="/团 对决 [@某人] [理由]", topic="日常")
    r.register("应战", accept_command, summary="接下别人发起的对决", topic="日常")

