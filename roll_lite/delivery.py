"""Message delivery: format choice, Markdown degrade, images, mentions, pacing.

Replies and proactive messages both pass through deliver().  The admin picks
one global push format; platforms that cannot render Markdown (OneBot and
anything not in render.MARKDOWN_PLATFORMS) always get plain text, and a
platform that refuses Markdown once (QQ official without the native-markdown
permission) is remembered and gets plain text from then on.  Status,
narration and choices segments can each be sent as image cards (cards.py)
rendered by AstrBot's html_render.  Scene banners are scaled down before they
are embedded; a card that fails with its banner is rendered once more without
it, and after that the segment goes out as text.  Each render has a time limit,
and once one times out the rest of that batch skips cards, so a slow render
service cannot hold up a whole table.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import re
from functools import lru_cache
import json
import os
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from astrbot.api import logger

from . import cards
from .render import MARKDOWN, PLAIN, Msg, from_json, mentions_of, render, target_format, to_json
from .storage import dumps, loads, now
from .worlds import scenes

if TYPE_CHECKING:
    from .app import LiteApp

MAX_MESSAGE = 1800
MENTION_PLATFORMS = frozenset({"aiocqhttp"})
# QQ official adapters turn an At into a real mention from AstrBot 4.29.0-beta.1; older ones drop it silently.
QQ_OFFICIAL_PLATFORMS = frozenset({"qq_official", "qq_official_webhook"})
QQ_AT_SINCE = (4, 29, 0, 1, 1)
# QQ shows a mention as a blue @ only in text and Markdown messages; beside a picture it prints the raw tag,
# so a card that mentions someone is followed by this short line carrying the mention.
CARD_MENTION_NOTE = "请看上图 ↑"
SEGMENTS = ("status", "narration", "choices", "sheet", "build", "banter", "ties", "economy", "pacing", "moment", "receipt", "room", "daily")
# Segments split off in 0.7.1: a saved setting without one follows the switch it used to be part of.
SPLIT_FROM = {"build": "sheet", "banter": "receipt", "ties": "receipt", "economy": "receipt", "pacing": "receipt"}
PREF_KEYS = ("format", *(f"image_{s}" for s in SEGMENTS), "scene_images", "card_theme", "interval", "merge")
# Undelivered messages handed over with one incoming message; the rest wait for the next one.
PENDING_BATCH = 10
# Cards are 800 px wide; a banner is scaled to this width and re-encoded so the card HTML stays small.
CARD_BANNER_WIDTH = 960
CARD_BANNER_QUALITY = 80
# The tallest card banner is 13.6rem on a 2.5vw root, i.e. 100:34 of the card width.  The browser crops the
# picture to that box from the centre (object-fit: cover), so cropping it here first changes nothing on screen.
CARD_BANNER_RATIO = 100 / 34
# Seconds one html_render call may take; the public render service can need over ten seconds for a picture card.
RENDER_TIMEOUT = 25
# Reasons a world simply has no picture for a key; anything else is worth a log line.
_NO_PICTURE = ("这个世界没有场景图", "没有这张场景图")


@dataclass(frozen=True)
class MessagePrefs:
    format: str = MARKDOWN
    image_status: bool = False
    image_narration: bool = False
    image_choices: bool = False
    image_sheet: bool = False
    image_build: bool = False
    image_banter: bool = False
    image_ties: bool = False
    image_economy: bool = False
    image_pacing: bool = False
    image_moment: bool = False
    image_receipt: bool = False
    image_room: bool = False
    image_daily: bool = False
    scene_images: bool = True
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
    value = dict(value)
    for segment, parent in SPLIT_FROM.items():
        if f"image_{segment}" not in value and f"image_{parent}" in value:
            value[f"image_{segment}"] = value[f"image_{parent}"]
    return MessagePrefs(**{k: value[k] for k in PREF_KEYS if k in value}, blocked=tuple(blocked))


def save_prefs(app: "LiteApp", value: dict[str, Any]) -> MessagePrefs:
    try:
        interval = max(0.0, min(3.0, float(value.get("interval", 1.0))))
    except (TypeError, ValueError):
        interval = 1.0
    prefs = MessagePrefs(format=MARKDOWN if value.get("format") == MARKDOWN else PLAIN,
                         **{f"image_{s}": bool(value.get(f"image_{s}")) for s in SEGMENTS},
                         scene_images=bool(value.get("scene_images", True)),
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
    scene_room: str = ""
    scene_key: str = ""
    scene_only: bool = False
    mergeable: bool = True


def _version_key(text: str) -> tuple[int, ...] | None:
    """'4.29.0-beta.2' -> (4, 29, 0, 1, 2); alpha/beta/rc rank below the final release."""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)(?:[-.]?(alpha|beta|rc)\.?(\d*))?", str(text).strip().lower())
    if not m:
        return None
    rank = {"alpha": 0, "beta": 1, "rc": 2}.get(m.group(4) or "", 3)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), rank, int(m.group(5) or 0))


@lru_cache(maxsize=1)
def astrbot_version() -> tuple[int, ...] | None:
    try:
        from astrbot.core.config.default import VERSION
    except Exception:
        return None
    return _version_key(VERSION)


def real_mentions(platform_name: str) -> bool:
    if platform_name in MENTION_PLATFORMS:
        return True
    if platform_name in QQ_OFFICIAL_PLATFORMS:
        version = astrbot_version()
        return version is not None and version >= QQ_AT_SINCE
    return False


def _chain(out: Outgoing, platform_name: str) -> Any:
    from astrbot.api.event import MessageChain  # imported lazily so tests run without AstrBot
    chain = MessageChain()
    real_at = bool(out.mentions) and real_mentions(platform_name)
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
    from .worlds import market
    entry = scenes.frozen_entry(app, art)
    image = ""
    problems: list[str] = []
    if entry is not None and entry.origin:
        for key in dict.fromkeys((art.get("key") or "cover", "cover")):
            try:
                image = card_banner(app, entry, key)
                break
            except (market.MarketError, OSError, ValueError) as exc:
                if str(exc) not in _NO_PICTURE:
                    problems.append(f"{key}: {exc}")
                continue
    if not image and problems:
        logger.warning("321Roll Lite: no banner picture for %s, using the colour cover (%s)", art.get("world"), "; ".join(problems))
    look = cards.cover(art.get("world") or "", entry.title if entry else "", entry.presentation if entry else None)
    return {**art, **look, "image": image}


def card_art_plain(art: dict[str, str] | None) -> dict[str, str] | None:
    """The colour-and-mark cover alone, for when the installed world cannot be read."""
    return {**art, **cards.cover(art.get("world") or "", "", None), "image": ""} if art else None


def card_banner(app: "LiteApp", entry: Any, key: str) -> str:
    """A scene image scaled to card width as a JPEG data URL, cached beside the installed revision.

    World packs keep their full-size pictures; only the copy embedded in card HTML is reduced, because a
    multi-megabyte data URL makes the render service time out or refuse the page.
    """
    from PIL import Image
    from .worlds import market
    folder = market.asset_root(app, entry.id) / str(entry.origin.get("folder") or "") / "card-cache"
    target = folder / (hashlib.sha256(f"banner-v2:{key}".encode()).hexdigest() + ".jpg")
    if not target.is_file():
        raw = base64.b64decode(market.image(app, entry, key)["url"].split(",", 1)[1])
        with Image.open(io.BytesIO(raw)) as source:
            picture = source.convert("RGB")
        tallest = round(picture.width / CARD_BANNER_RATIO)
        if picture.height > tallest:
            top = (picture.height - tallest) // 2
            picture = picture.crop((0, top, picture.width, top + tallest))
        if picture.width > CARD_BANNER_WIDTH:
            picture = picture.resize((CARD_BANNER_WIDTH, max(1, round(picture.height * CARD_BANNER_WIDTH / picture.width))),
                                     Image.LANCZOS)
        out = io.BytesIO()
        picture.save(out, "JPEG", quality=CARD_BANNER_QUALITY, optimize=True, progressive=True)
        folder.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(f".{os.getpid()}.part")
        partial.write_bytes(out.getvalue())
        os.replace(partial, target)
    return "data:image/jpeg;base64," + base64.b64encode(target.read_bytes()).decode("ascii")


@dataclass
class Rendered:
    url: str = ""
    banner: bool = False      # the card carries the scene picture, so no separate scene image is needed
    timed_out: bool = False   # the render service is too slow; the rest of the batch goes out as text


async def _to_image(app: "LiteApp", item: Any, prefs: MessagePrefs) -> Rendered:
    star = getattr(app, "star", None)
    if star is None or not isinstance(item, Msg):
        return Rendered()
    try:
        art = card_art(app, item.art)
    except Exception as exc:
        logger.warning("321Roll Lite card banner unavailable, using the colour cover: %s", exc)
        art = card_art_plain(item.art)
    # With a banner the card is tried once more without it: an oversized page is the usual reason it fails.
    looks = [art, {**art, "image": ""}] if art and art.get("image") else [art]
    for look in looks:
        banner = bool(look and look.get("image"))
        try:
            page = cards.card_html(item, prefs.card_theme, look)
            url = await asyncio.wait_for(star.html_render(cards.TEMPLATE, {"html": page}, return_url=True,
                                                          options=dict(cards.RENDER_OPTIONS)), RENDER_TIMEOUT)
            if url:
                return Rendered(url, banner)
            reason: Any = "the render service returned no image"
        except asyncio.TimeoutError:
            if not banner:
                logger.warning("321Roll Lite card render timed out after %ss; sending text for the rest of this batch",
                               RENDER_TIMEOUT)
                return Rendered(timed_out=True)
            reason = f"timed out after {RENDER_TIMEOUT}s"
        except Exception as exc:
            reason = exc
        logger.warning("321Roll Lite card render failed (%s); %s", reason,
                       "retrying without the scene banner" if banner else "sending text")
    return Rendered()


def scene_file(app: "LiteApp", art: dict[str, str]) -> str:
    """Decode a single pinned asset into a JPEG beside its revision; safe for both QQ adapters."""
    from .worlds import market
    from PIL import Image
    entry = scenes.frozen_entry(app, art)
    if entry is None or not entry.origin:
        return ""
    cache = market.asset_root(app, entry.id) / entry.origin["folder"] / "scene-cache"
    name = hashlib.sha256(art["key"].encode()).hexdigest() + ".jpg"
    target = cache / name
    if not target.is_file():
        data = base64.b64decode(market.image(app, entry, art["key"])["url"].split(",", 1)[1])
        cache.mkdir(parents=True, exist_ok=True)
        with Image.open(io.BytesIO(data)) as im:
            im.convert("RGB").save(target, "JPEG", quality=92)
    return str(target)


def _last_scene(app, room_id):
    with app.store.read() as c:
        row = c.execute("SELECT data_json FROM rooms WHERE id=?", (room_id,)).fetchone()
    return (loads(row["data_json"], {}).get("scene_art") or {}).get("key") if row else None


def _remember_scene(app, out, status):
    if not out.scene_room:
        return
    with app.store.tx() as c:
        row = c.execute("SELECT data_json FROM rooms WHERE id=?", (out.scene_room,)).fetchone()
        if row:
            data = loads(row["data_json"], {})
            data["scene_art"] = {"key": out.scene_key, "status": status}
            c.execute("UPDATE rooms SET data_json=? WHERE id=?", (dumps(data), out.scene_room))


async def prepare(app: "LiteApp", items: list[Any], platform_name: str, platform_id: str,
                  prefs: MessagePrefs | None = None) -> list[Outgoing]:
    prefs = prefs or load_prefs(app)
    fmt = target_format(prefs.format, platform_name, platform_id in prefs.blocked)
    separator = "---" if fmt == MARKDOWN else "┄┄┄┄┄┄┄┄┄┄"
    outgoing: list[Outgoing] = []
    planned: dict[str, str | None] = {}
    cards_on = True
    for index, item in enumerate(items):
        segment = item.segment if isinstance(item, Msg) else ""
        mentions = tuple(mentions_of(item))
        art = item.art if isinstance(item, Msg) else None
        scenic = segment == "narration" or (isinstance(item, Msg) and (item.data or {}).get("kind") in {"open", "act", "ending"})
        room_id = (art or {}).get("room", "")
        key = (art or {}).get("key", "")
        if room_id and room_id not in planned:
            planned[room_id] = _last_scene(app, room_id)
        fresh = bool(scenic and art and key and (not room_id or planned[room_id] != key))
        image, banner = "", False
        if cards_on and prefs.image(segment):
            # Every story card carries the current scene as its banner; only the separate picture is deduplicated.
            rendered = await _to_image(app, item, prefs)
            image, banner, cards_on = rendered.url, rendered.banner, not rendered.timed_out
        ending = isinstance(item, Msg) and (item.data or {}).get("kind") == "ending"
        if fresh and prefs.scene_images and (ending or not banner):
            try:
                path = scene_file(app, art)
                if path:
                    outgoing.append(Outgoing(image=path, source=index, scene_room=room_id, scene_key=key, scene_only=True))
                    planned[room_id] = key
            except Exception as exc:
                logger.warning("321Roll Lite scene image unavailable: %s", exc)
                _remember_scene(app, Outgoing(scene_room=room_id, scene_key=key), "failed")
                planned[room_id] = key
        if ending and prefs.scene_images:
            for extra in (item.data or {}).get("extra_scene_keys", []):
                try:
                    path = scene_file(app, {**art, "key": extra})
                    if path:
                        outgoing.append(Outgoing(image=path, source=index, scene_only=True))
                except Exception as exc:
                    logger.warning("321Roll Lite ending image unavailable: %s", exc)
        if image:
            split = bool(mentions) and platform_name in QQ_OFFICIAL_PLATFORMS
            outgoing.append(Outgoing(image=image, mentions=() if split else mentions, source=index,
                                     scene_room=room_id if fresh and banner else "", scene_key=key))
            if split:
                outgoing.append(Outgoing(text=CARD_MENTION_NOTE, mentions=mentions, markdown=fmt == MARKDOWN,
                                         source=index, mergeable=False))
            if fresh and banner:
                planned[room_id] = key
            continue
        text = render(item, fmt)
        if not text:
            continue
        last = outgoing[-1] if outgoing else None
        if prefs.merge and last is not None and not last.image and last.mergeable and not (mentions and last.mentions) \
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
            if out.scene_only:
                logger.warning("321Roll Lite: %s refused a scene image (%s); sending the story text", platform_id, exc)
                _remember_scene(app, out, "failed")
                position += 1
                continue
            if out.image and isinstance(items[out.source], Msg) and items[out.source].art:
                logger.warning("321Roll Lite: %s refused a story card (%s); sending text", platform_id, exc)
                _remember_scene(app, out, "failed")
                outgoing[position:position+1] = [Outgoing(text=part, source=out.source)
                                               for part in chunks(render(items[out.source], PLAIN))]
                continue
            if not out.markdown:
                raise
            logger.warning("321Roll Lite: %s refused Markdown (%s); switching it to plain text", platform_id, exc)
            _block_markdown(app, platform_id)
            plain = replace(prefs, format=PLAIN, blocked=())
            # The mention line after a card is the last part of its item, and the card already went out.
            start = out.source + 1 if not out.mergeable else out.source
            rest = [replace(o, source=o.source + start)
                    for o in await prepare(app, items[start:], platform_name, platform_id, plain)]
            outgoing = outgoing[:position] + ([replace(out, markdown=False)] if not out.mergeable else []) + rest
            continue
        _remember_scene(app, out, "sent")
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
