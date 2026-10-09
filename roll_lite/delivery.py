"""Message delivery: format choice, Markdown degrade, images, mentions, pacing.

Replies and proactive messages both pass through deliver().  The admin picks
one global push format; platforms that cannot render Markdown (OneBot and
anything not in render.MARKDOWN_PLATFORMS) always get plain text, and a
platform that refuses Markdown once (QQ official without the native-markdown
permission) is remembered and gets plain text from then on.  Status,
narration and choices segments can each be sent as image cards (cards.py)
rendered by AstrBot's html_render; if that fails AstrBot's own text-to-image
template is tried, and after that the segment goes out as text.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from astrbot.api import logger

from . import cards
from .render import MARKDOWN, PLAIN, Msg, from_json, mentions_of, render, target_format, to_json
from .storage import now

if TYPE_CHECKING:
    from .app import LiteApp

MAX_MESSAGE = 1800
MENTION_PLATFORMS = frozenset({"aiocqhttp"})
SEGMENTS = ("status", "narration", "choices", "moment", "sheet", "receipt", "room", "daily")
PREF_KEYS = ("format", *(f"image_{s}" for s in SEGMENTS), "card_theme", "interval", "merge")
# Undelivered messages handed over with one incoming message; the rest wait for the next one.
PENDING_BATCH = 10


@dataclass(frozen=True)
class MessagePrefs:
    format: str = MARKDOWN
    image_status: bool = False
    image_narration: bool = False
    image_choices: bool = False
    image_moment: bool = False
    image_sheet: bool = False
    image_receipt: bool = False
    image_room: bool = False
    image_daily: bool = False
    card_theme: str = "light"
    interval: float = 1.0
    merge: bool = False
    blocked: tuple[str, ...] = ()

    def image(self, segment: str) -> bool:
        return segment in SEGMENTS and bool(getattr(self, f"image_{segment}"))

    def public(self) -> dict[str, Any]:
        return {**{k: getattr(self, k) for k in PREF_KEYS}, "blocked": list(self.blocked)}


def load_prefs(app: "LiteApp") -> MessagePrefs:
    with app.store.read() as c:
        value = app.store.get_setting(c, "global", "message.prefs", {}) or {}
        blocked = app.store.get_setting(c, "global", "message.markdown_blocked", []) or []
    return MessagePrefs(**{k: value[k] for k in PREF_KEYS if k in value}, blocked=tuple(blocked))


def save_prefs(app: "LiteApp", value: dict[str, Any]) -> MessagePrefs:
    try:
        interval = max(0.0, min(3.0, float(value.get("interval", 1.0))))
    except (TypeError, ValueError):
        interval = 1.0
    prefs = MessagePrefs(format=MARKDOWN if value.get("format") == MARKDOWN else PLAIN,
                         **{f"image_{s}": bool(value.get(f"image_{s}")) for s in SEGMENTS},
                         card_theme=value.get("card_theme") if value.get("card_theme") in cards.THEMES else "light",
                         interval=interval, merge=bool(value.get("merge")))
    with app.store.tx() as c:
        app.store.set_setting(c, "global", "message.prefs", {k: getattr(prefs, k) for k in PREF_KEYS})
        if value.get("reset_blocked"):
            app.store.set_setting(c, "global", "message.markdown_blocked", [])
    return load_prefs(app)


def chunks(text: str, limit: int = MAX_MESSAGE) -> list[str]:
    """Split long text on line boundaries so platforms accept it."""
    parts, current = [], ""
    for block in text.split("\n"):
        candidate = f"{current}\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(block) > limit:
            parts.append(block[:limit])
            block = block[limit:]
        current = block
    if current:
        parts.append(current)
    return parts or [""]


@dataclass
class Outgoing:
    text: str = ""
    image: str = ""
    mentions: tuple[tuple[str, str], ...] = ()
    markdown: bool = False
    source: int = 0          # index of the item it came from (for a plain-text retry)


def _chain(out: Outgoing, platform_name: str) -> Any:
    from astrbot.api.event import MessageChain  # imported lazily so tests run without AstrBot
    chain = MessageChain()
    real_at = platform_name in MENTION_PLATFORMS
    prefix = "" if real_at else "".join(f"@{name} " for _, name in out.mentions)
    if real_at:
        for user_id, name in out.mentions:
            chain.at(name, user_id)
    if out.image:
        from astrbot.api.message_components import Image
        if prefix:
            chain.message(prefix.strip())
        chain.chain.append(Image.fromURL(out.image) if out.image.startswith("http") else Image.fromFileSystem(out.image))
    else:
        chain.message((" " if real_at and out.mentions else "") + prefix + out.text)
    chain.use_t2i(False)
    chain.use_markdown(out.markdown)
    return chain


def card_art(app: "LiteApp", art: dict[str, str] | None) -> dict[str, str] | None:
    """Resolve a message's banner: the installed scene image, else the world cover image, else colour and mark."""
    if not art:
        return None
    from .rooms import lifecycle
    from .worlds import market
    entry = lifecycle.catalog(app).get(art.get("world") or "")
    image = ""
    if entry is not None and entry.origin:
        for key in dict.fromkeys((art.get("key") or "cover", "cover")):
            try:
                image = market.image(app, entry, key)["url"]
                break
            except market.MarketError:
                continue
    look = cards.cover(art.get("world") or "", entry.title if entry else "", entry.presentation if entry else None)
    return {**art, **look, "image": image}


async def _to_image(app: "LiteApp", item: Any, prefs: MessagePrefs) -> str:
    star = getattr(app, "star", None)
    if star is None:
        return ""
    if isinstance(item, Msg):
        try:
            page = cards.card_html(item, prefs.card_theme, card_art(app, item.art))
            url = await star.html_render(cards.TEMPLATE, {"html": page}, return_url=True, options=dict(cards.RENDER_OPTIONS))
            if url:
                return url
        except Exception as exc:
            logger.warning("321Roll Lite card render failed, trying AstrBot text-to-image: %s", exc)
    try:
        return await star.text_to_image(render(item, MARKDOWN), return_url=True) or ""
    except Exception as exc:
        logger.warning("321Roll Lite text-to-image failed, sending text: %s", exc)
        return ""


async def prepare(app: "LiteApp", items: list[Any], platform_name: str, platform_id: str,
                  prefs: MessagePrefs | None = None) -> list[Outgoing]:
    prefs = prefs or load_prefs(app)
    fmt = target_format(prefs.format, platform_name, platform_id in prefs.blocked)
    separator = "---" if fmt == MARKDOWN else "┄┄┄┄┄┄┄┄┄┄"
    outgoing: list[Outgoing] = []
    for index, item in enumerate(items):
        segment = item.segment if isinstance(item, Msg) else ""
        mentions = tuple(mentions_of(item))
        if prefs.image(segment):
            image = await _to_image(app, item, prefs)
            if image:
                outgoing.append(Outgoing(image=image, mentions=mentions, source=index))
                continue
        text = render(item, fmt)
        if not text:
            continue
        last = outgoing[-1] if outgoing else None
        if prefs.merge and last is not None and not last.image and not (mentions and last.mentions) \
                and len(last.text) + len(text) < MAX_MESSAGE:
            last.text += f"\n\n{separator}\n\n{text}"
            last.mentions = last.mentions or mentions
            continue
        for part_index, part in enumerate(chunks(text)):
            outgoing.append(Outgoing(text=part, mentions=mentions if part_index == 0 else (),
                                     markdown=fmt == MARKDOWN, source=index))
    return outgoing


Sender = Callable[[Any], Awaitable[Any]]


async def deliver(app: "LiteApp", send: Sender, items: list[Any], *, platform_name: str, platform_id: str,
                  merge: bool | None = None) -> None:
    """Send items in order with the configured pacing; raises if the platform refuses plain text too.

    merge overrides the admin's choice, so a backlog goes out in as few messages as possible.
    """
    prefs = load_prefs(app)
    if merge is not None:
        prefs = replace(prefs, merge=merge)
    outgoing = await prepare(app, items, platform_name, platform_id, prefs)
    position = 0
    while position < len(outgoing):
        out = outgoing[position]
        if position and prefs.interval:
            await asyncio.sleep(prefs.interval)
        try:
            result = await send(_chain(out, platform_name))
            if result is False:
                raise RuntimeError("platform refused the message")
        except Exception as exc:
            if not out.markdown:
                raise
            logger.warning("321Roll Lite: %s refused Markdown (%s); switching it to plain text", platform_id, exc)
            _block_markdown(app, platform_id)
            remaining = items[out.source:]
            outgoing = outgoing[:position] + await prepare(app, remaining, platform_name, platform_id,
                                                           replace(prefs, format=PLAIN, blocked=()))
            continue
        position += 1


def _block_markdown(app: "LiteApp", platform_id: str) -> None:
    with app.store.tx() as c:
        blocked = app.store.get_setting(c, "global", "message.markdown_blocked", []) or []
        if platform_id not in blocked:
            app.store.set_setting(c, "global", "message.markdown_blocked", [*blocked, platform_id])


def platform_of(app: "LiteApp", umo: str) -> tuple[str, str]:
    """(platform type, platform instance id) for a unified message origin."""
    platform_id = umo.split(":", 1)[0]
    try:
        inst = app.context.get_platform_inst(platform_id)
        return (inst.meta().name if inst is not None else ""), platform_id
    except Exception:
        return "", platform_id


QQ_OFFICIAL = frozenset({"qq_official", "qq_official_webhook"})


def qq_reachable(app: "LiteApp", umo: str) -> bool:
    """Whether AstrBot's QQ official adapter will really post a proactive message to this conversation.

    Its send_by_session returns quietly, without raising, for a group it has not heard from since the
    last restart (no remembered scene or message id).  Such a message must wait in the outbox instead
    of being counted as sent.  Private chats always go out.  An adapter without these fields (another
    AstrBot version) is trusted to raise on its own.
    """
    platform_id, message_type, session_id = (umo.split(":", 2) + ["", ""])[:3]
    if message_type != "GroupMessage":
        return True
    try:
        inst = app.context.get_platform_inst(platform_id)
    except Exception:
        return True
    scenes = getattr(inst, "_session_scene", None)
    message_ids = getattr(inst, "_session_last_message_id", None)
    if not isinstance(scenes, dict) or not isinstance(message_ids, dict):
        return True
    if message_ids.get(session_id):
        return True
    return scenes.get(session_id) == "group" and bool(getattr(inst, "_allow_group_proactive_send", False))


class Notifier:
    """Messages the plugin sends on its own (timeouts, votes, announcements from a private chat).

    A platform may refuse them: a QQ official bot posts to a group on its own only when the group
    allows it ("允许机器人主动在群聊内发言") and only after the group has spoken to it since AstrBot
    started.  A refused message waits in the outbox with its full structure; the next /团 in that
    conversation carries it as part of the reply (take_pending/settle in main.py).
    """

    def __init__(self, app: "LiteApp") -> None:
        self.app = app
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, umo: str) -> asyncio.Lock:
        """One sender at a time per conversation, so a background message never lands inside a multi-part reply."""
        return self._locks.setdefault(umo, asyncio.Lock())

    async def _send_items(self, umo: str, items: list[Any]) -> None:
        platform_name, platform_id = platform_of(self.app, umo)
        if platform_name in QQ_OFFICIAL and not qq_reachable(self.app, umo):
            raise RuntimeError("QQ 官方机器人自启动后还没收到过这个群的消息，暂时无法主动发送")
        async with self.lock(umo):
            await deliver(self.app, lambda chain: self.app.context.send_message(umo, chain), items,
                          platform_name=platform_name, platform_id=platform_id)

    async def send(self, umo: str, items: Any) -> bool:
        items = [i for i in (items if isinstance(items, list) else [items]) if i]
        if not items:
            return True
        try:
            await self._send_items(umo, items)
            return True
        except Exception as exc:
            logger.warning("321Roll Lite proactive send failed for %s: %s", umo, exc)
            text = "\n\n".join(render(i, PLAIN) for i in items)
            with self.app.store.tx() as c:
                c.execute("INSERT INTO outbox(umo,text,items_json,state,attempts,last_error,created_at,updated_at) "
                          "VALUES(?,?,?,'pending',1,?,?,?)",
                          (umo, text, json.dumps([to_json(i) for i in items], ensure_ascii=False), str(exc)[:300], now(), now()))
            return False

    def take_pending(self, umo: str) -> tuple[list[int], list[Any]]:
        """Ids and messages still waiting for this conversation, oldest first (rows without items_json are plain text)."""
        with self.app.store.read() as c:
            rows = c.execute("SELECT id,text,items_json FROM outbox WHERE umo=? AND state='pending' ORDER BY id LIMIT ?",
                             (umo, PENDING_BATCH)).fetchall()
        items: list[Any] = []
        for row in rows:
            items.extend([from_json(i) for i in json.loads(row["items_json"])] if row["items_json"] else [row["text"]])
        return [row["id"] for row in rows], items

    def settle(self, ids: list[int], error: Exception | None) -> None:
        """Mark a carried backlog sent, or count the failed try (a row is dropped after five)."""
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        with self.app.store.tx() as c:
            if error is None:
                c.execute(f"UPDATE outbox SET state='sent',attempts=attempts+1,last_error='',updated_at=? WHERE id IN ({marks})",
                          (now(), *ids))
            else:
                c.execute(f"UPDATE outbox SET state=CASE WHEN attempts>=5 THEN 'dropped' ELSE 'pending' END,"
                          f"attempts=attempts+1,last_error=?,updated_at=? WHERE id IN ({marks})", (str(error)[:300], now(), *ids))

    async def carry(self, umo: str, send: Sender, *, platform_name: str, platform_id: str) -> None:
        """Answer an incoming message with the backlog for its conversation, merged into few messages.

        A reply is accepted where a proactive message is not (QQ official groups), so the backlog rides on it.
        """
        ids, items = self.take_pending(umo)
        if not ids:
            return
        error: Exception | None = None
        try:
            async with self.lock(umo):
                await deliver(self.app, send, items, platform_name=platform_name, platform_id=platform_id, merge=True)
        except Exception as exc:
            error = exc
            logger.warning("321Roll Lite could not deliver the backlog for %s: %s", umo, exc)
        self.settle(ids, error)

    async def retry(self, umo: str, text: str) -> None:
        await self._send_items(umo, [text])
