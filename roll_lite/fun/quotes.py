"""金句: story lines a group wants to keep and see again.

/团 金句                 a random saved line; reply to one of the bot's story messages with it to save that line
/团 金句 <那句里的几个字>  save the sentence of this group's story that contains them
/团 金句 +<编号>          save a line already in the book by its number
/团 金句 榜               the lines saved by the most members
/团 金句 删 <编号>        remove one (admins, or whoever first saved it)

Only the bot's own story text (narration and host narration) can be saved, looked up in this group's
tables, newest first; the quote is widened to whole sentences.  Saving a line someone already saved adds a
mark, and marks rank the board.  A story card sent as an image has no text to reply to, so its line is
named by a few of its words instead.
"""
from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING, Any

from .. import messages, shared
from ..commands import Caller, Reply, UserError
from ..rooms import lifecycle
from ..storage import now

if TYPE_CHECKING:
    from ..app import LiteApp

SCAN = 400            # story events searched, newest first
MIN_FRAGMENT = 4
MAX_QUOTE = 120
BOARD_SIZE = 8
BOARD_WORDS = ("榜", "排行", "排行榜")
_SENTENCE = re.compile(r"[^。！？!?…\n]*[。！？!?…]+[”」』\"’）)]*|[^。！？!?…\n]+")
_NOISE = re.compile(r"[\s*_`>#~|【】]+")


def norm(text: str) -> str:
    return _NOISE.sub("", text)


def sentences(text: str) -> list[str]:
    return [s for s in (m.group(0).strip() for m in _SENTENCE.finditer(text)) if s]


def _bare(piece: str) -> bool:
    """A line with no sentence ending, such as a scene title above the story."""
    return not re.search(r"[。！？!?…][”」』\"’）)]*$", piece)


def _source(c: sqlite3.Connection, room_id: str, event_id: int) -> str:
    room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    chapter = c.execute("SELECT text FROM events WHERE room_id=? AND kind='chapter' AND id<? ORDER BY id DESC LIMIT 1",
                        (room_id, event_id)).fetchone()
    act = chapter["text"].split("——")[0] if chapter else lifecycle.act_heading(room, 1).split("\n")[0]
    title = messages.short_title(shared.world(room)["pack"]["title"])
    return " · ".join(p for p in (title, act) if p)


def find(c: sqlite3.Connection, umo: str, fragment: str) -> tuple[str, str] | None:
    """(whole sentences containing the fragment, where they come from) in this group's story, newest first."""
    key = norm(fragment)
    rows = c.execute("SELECT e.id,e.room_id,e.text FROM events e JOIN rooms r ON r.id=e.room_id "
                     "WHERE r.umo=? AND e.kind IN ('narration','host') AND e.text NOT LIKE '主持人调整生效：%' "
                     "ORDER BY e.id DESC LIMIT ?", (umo, SCAN)).fetchall()
    for row in rows:
        parts = sentences(row["text"])
        normed = [norm(s) for s in parts]
        pos = "".join(normed).find(key)
        if pos < 0:
            continue
        start = end = 0
        reach = 0
        for i, piece in enumerate(normed):
            if reach <= pos < reach + len(piece):
                start = i
            if pos + len(key) <= reach + len(piece):
                end = i
                break
            reach += len(piece)
        while start < end and _bare(parts[start]):      # a reply to a whole story message drops its title line
            start += 1
        return "".join(parts[start:end + 1]).strip(), _source(c, row["room_id"], row["id"])
    return None


def marks(c: sqlite3.Connection, quote_id: int) -> int:
    return c.execute("SELECT COUNT(*) FROM quote_marks WHERE quote_id=?", (quote_id,)).fetchone()[0]


def _card(c: sqlite3.Connection, row: sqlite3.Row, kind: str) -> Any:
    return messages.quote_card(row["text"], row["source"], row["id"], marks(c, row["id"]), row["saved_name"], kind)


def save(app: "LiteApp", caller: Caller, fragment: str, *, typed: bool) -> Reply:
    if len(norm(fragment)) < MIN_FRAGMENT:
        raise UserError(f"至少写上那句话里连续的 {MIN_FRAGMENT} 个字，例如 /团 金句 钟楼又敲了一下。")
    with app.store.tx() as c:
        found = find(c, caller.umo, fragment)
        if found is None:
            raise UserError("没在本群的故事里找到这段话。金句只收 Bot 讲过的故事正文；正文是图片卡片时，"
                            "在指令后写上那句话里的几个字就行。" if not typed else
                            "没在本群的故事里找到这几个字，检查一下有没有错字，或者换几个字试试。")
        text, source = found
        if len(text) > MAX_QUOTE:
            raise UserError("这一段有好几句，太长了。在指令后面写上想收的那一句里的几个字，例如 /团 金句 钟楼又敲了一下。")
        row = c.execute("SELECT * FROM quotes WHERE umo=? AND text=?", (caller.umo, text)).fetchone()
        if row is None:          # inserting only when new keeps the numbers free of gaps
            c.execute("INSERT INTO quotes(umo,text,source,saved_by,saved_name,created_at) VALUES(?,?,?,?,?,?)",
                      (caller.umo, text, source, caller.user_id, caller.user_name, now()))
            row = c.execute("SELECT * FROM quotes WHERE umo=? AND text=?", (caller.umo, text)).fetchone()
        fresh = c.execute("INSERT OR IGNORE INTO quote_marks(quote_id,user_id,created_at) VALUES(?,?,?)",
                          (row["id"], caller.user_id, now())).rowcount == 1
        if not fresh:
            raise UserError(f"你已经收藏过这句了（No.{row['id']}）。")
        return Reply().say(_card(c, row, "saved"))


def mark(app: "LiteApp", caller: Caller, number: int) -> Reply:
    with app.store.tx() as c:
        row = c.execute("SELECT * FROM quotes WHERE id=? AND umo=?", (number, caller.umo)).fetchone()
        if row is None:
            raise UserError(f"本群没有 No.{number} 这句金句。发送 /团 金句 榜 看看编号。")
        if c.execute("INSERT OR IGNORE INTO quote_marks(quote_id,user_id,created_at) VALUES(?,?,?)",
                     (row["id"], caller.user_id, now())).rowcount != 1:
            raise UserError(f"你已经收藏过这句了（No.{row['id']}）。")
        return Reply().say(_card(c, row, "marked"))


async def quote_command(app: "LiteApp", caller: Caller, args: str) -> Reply:
    shared.require_play(app, caller, "funQuotes")
    text = args.strip()
    if text in BOARD_WORDS:
        with app.store.read() as c:
            rows = c.execute("SELECT q.*, (SELECT COUNT(*) FROM quote_marks m WHERE m.quote_id=q.id) AS marks FROM quotes q "
                             "WHERE umo=? ORDER BY marks DESC, q.id LIMIT ?", (caller.umo, BOARD_SIZE)).fetchall()
            total = c.execute("SELECT COUNT(*) FROM quotes WHERE umo=?", (caller.umo,)).fetchone()[0]
        return Reply().say(messages.quote_board([dict(r) for r in rows], total))
    marking = re.fullmatch(r"[+＋]\s*(?:No\.?)?\s*(\d+)", text, re.IGNORECASE)
    if marking:
        return mark(app, caller, int(marking.group(1)))
    deleting = re.fullmatch(r"(?:删|删除)\s*(?:No\.?)?\s*(\d+)", text, re.IGNORECASE)
    if deleting:
        with app.store.tx() as c:
            row = c.execute("SELECT * FROM quotes WHERE id=? AND umo=?", (int(deleting.group(1)), caller.umo)).fetchone()
            if row is None:
                raise UserError("本群没有这个编号的金句。")
            if not (caller.is_admin or row["saved_by"] == caller.user_id):
                raise UserError("只有管理员或最早收录这句的人可以删除。")
            c.execute("DELETE FROM quotes WHERE id=?", (row["id"],))
        return Reply().say(f"已删除金句 No.{row['id']}。")
    if text or caller.quote:
        return save(app, caller, text or caller.quote, typed=bool(text))
    with app.store.read() as c:
        row = c.execute("SELECT * FROM quotes WHERE umo=? ORDER BY RANDOM() LIMIT 1", (caller.umo,)).fetchone()
        if row is None:
            raise UserError("本群还没有金句。跑团时看到喜欢的句子，回复那条消息发送 /团 金句，"
                            "或者发送 /团 金句 加上那句话里的几个字，就能收进来。")
        return Reply().say(_card(c, row, "random"))


def install(app: "LiteApp") -> None:
    app.router.register("金句", quote_command, summary="收藏跑团里的好句子，随机重温或看金句榜",
                        usage="/团 金句 [那句话里的几个字|+编号|榜|删 编号]", topic="日常")
