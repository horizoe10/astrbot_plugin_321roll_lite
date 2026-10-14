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
from time import monotonic
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
# All card attempts in one delivery share this allowance; platform sends and pacing do not spend it.
RENDER_BATCH_BUDGET = 25.0
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
    source: int = 0
    scene_room: str = ""
    scene_key: str = ""
    scene_only: bool = False
    mergeable: bool = True
    owner: int = 0           # outbox row; a merged message can contain parts from several rows
    parts: tuple[Outgoing, ...] = ()
    fallback: tuple[Outgoing, ...] = ()
    scene_art: dict[str, str] | None = None

    def fragments(self) -> tuple[Outgoing, ...]:
        return self.parts or (self,)


@dataclass
class DeliveryProgress:
    confirmed: set[int]
    attempted: set[int]


@dataclass(frozen=True)
class DeferredItem:
    item: Any
    owner: int
    source: int


class DeliveryFailed(Exception):
    def __init__(self, error: Exception, remaining: list[Outgoing], progress: DeliveryProgress,
                 deferred: list[DeferredItem] | None = None):
        super().__init__(str(error))
        self.remaining = remaining
        self.progress = progress
        self.deferred = deferred or []


def _append(outgoing: list[Outgoing], out: Outgoing, merge: bool) -> None:
    last = outgoing[-1] if outgoing else None
    separator = "\n\n---\n\n" if out.markdown else "\n\n┄┄┄┄┄┄┄┄┄┄\n\n"
    if merge and last is not None and not (last.image or out.image or last.scene_only or out.scene_only) \
            and last.mergeable and out.mergeable and last.markdown == out.markdown \
            and not (last.mentions and out.mentions) and len(last.text) + len(separator) + len(out.text) <= MAX_MESSAGE:
        outgoing[-1] = replace(last, text=last.text + separator + out.text, mentions=last.mentions or out.mentions,
                               parts=(*last.fragments(), *out.fragments()), fallback=())
    else:
        outgoing.append(out)


def _plain(out: Outgoing) -> list[Outgoing]:
    result: list[Outgoing] = []
    for part in out.fragments():
        for unit in part.fallback or (replace(part, markdown=False, parts=()),):
            _append(result, unit, bool(out.parts))
    return result


def _remember_sent_scene(app, out, status):
    try:
        _remember_scene(app, out, status)
    except Exception:
        # A failed bookkeeping write must not replay content the platform already accepted.
        logger.exception("321Roll Lite could not remember a delivered scene")


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
    # A launcher install can leave under 64 characters before Windows MAX_PATH.
    # 96-bit cache keys stay compact; the parent directory already isolates world revisions.
    target = folder / (hashlib.sha256(f"banner-v2:{key}".encode()).hexdigest()[:24] + ".jpg")
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


@dataclass
class RenderBudget:
    remaining: float


async def _to_image(app: "LiteApp", item: Any, prefs: MessagePrefs, budget: RenderBudget | None = None) -> Rendered:
    star = getattr(app, "star", None)
    if star is None or not isinstance(item, Msg):
        return Rendered()
    budget = budget if budget is not None else RenderBudget(RENDER_BATCH_BUDGET)
    if budget.remaining <= 0:
        return Rendered(timed_out=True)
    try:
        art = card_art(app, item.art)
    except Exception as exc:
        logger.warning("321Roll Lite card banner unavailable, using the colour cover: %s", exc)
        art = card_art_plain(item.art)
    # Removing a banner is another attempt, not a fresh timeout allowance.
    looks = [art, {**art, "image": ""}] if art and art.get("image") else [art]
    for look in looks:
        timeout = min(RENDER_TIMEOUT, budget.remaining)
        if timeout <= 0:
            return Rendered(timed_out=True)
        banner = bool(look and look.get("image"))
        try:
            page = cards.card_html(item, prefs.card_theme, look)
            started = monotonic()
            try:
                url = await asyncio.wait_for(star.html_render(cards.TEMPLATE, {"html": page}, return_url=True,
                                                              options=dict(cards.RENDER_OPTIONS)), timeout)
            finally:
                budget.remaining = max(0.0, budget.remaining - max(0.0, monotonic() - started))
            if url:
                return Rendered(url, banner)
            reason: Any = "the render service returned no image"
        except asyncio.TimeoutError:
            if not banner or budget.remaining <= 0:
                logger.warning("321Roll Lite card render timed out; sending text for the rest of this batch")
                return Rendered(timed_out=True)
            reason = f"timed out after {timeout}s"
        except Exception as exc:
            reason = exc
        logger.warning("321Roll Lite card render failed (%s); %s", reason,
                       "retrying without the scene banner" if banner and budget.remaining > 0 else "sending text")
    return Rendered(timed_out=budget.remaining <= 0)


def scene_file(app: "LiteApp", art: dict[str, str]) -> str:
    """Decode a single pinned asset into a JPEG beside its revision; safe for both QQ adapters."""
    from .worlds import market
    from PIL import Image
    entry = scenes.frozen_entry(app, art)
    if entry is None or not entry.origin:
        return ""
    cache = market.asset_root(app, entry.id) / entry.origin["folder"] / "scene-cache"
    # Keep the path short enough for both local writes and adapter reads on Windows.
    name = hashlib.sha256(art["key"].encode()).hexdigest()[:24] + ".jpg"
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


class PreparationCursor:
    """Prepare one complete item at a time; never wait for another card while ready output can be sent."""

    def __init__(self, app, items, platform_name, platform_id, prefs, owners=None):
        self.app, self.items, self.prefs = app, list(items), prefs
        self.owners = list(owners) if owners is not None else [0] * len(items)
        if len(self.owners) != len(self.items):
            raise ValueError("message owners must match items")
        self.platform_name = platform_name
        self.fmt = target_format(prefs.format, platform_name, platform_id in prefs.blocked)
        self.next_index = 0
        self.ready: list[Outgoing] = []
        self.planned: dict[str, str | None] = {}
        self.cards_on = True
        self.budget = RenderBudget(RENDER_BATCH_BUDGET)

    def deferred(self) -> list[DeferredItem]:
        return [DeferredItem(self.items[i], self.owners[i], i) for i in range(self.next_index, len(self.items))]

    def may_wait(self, item) -> bool:
        if isinstance(item, Outgoing):
            return item.scene_only or bool(item.image)
        if not isinstance(item, Msg):
            return False
        scenic = item.segment == "narration" or (item.data or {}).get("kind") in {"open", "act", "ending"}
        return bool((self.cards_on and self.budget.remaining > 0 and self.prefs.image(item.segment)
                     and getattr(self.app, "star", None) is not None) or (scenic and item.art and self.prefs.scene_images))

    async def fill(self) -> None:
        while self.next_index < len(self.items):
            if self.ready and (not self.prefs.merge or self.may_wait(self.items[self.next_index])):
                return
            await self.advance()
            if any(out.image or out.scene_only or not out.mergeable for out in self.ready):
                return

    async def advance(self) -> None:
        index = self.next_index
        planned = dict(self.planned)
        local, cards_on = await self._item(index, self.items[index], self.owners[index], planned)
        # Commit the whole item together; a preparation failure leaves it entirely in the raw tail.
        for out in local:
            _append(self.ready, out, self.prefs.merge)
        self.planned, self.cards_on = planned, cards_on
        self.next_index += 1

    async def _item(self, index, item, owner, planned):
        app, prefs, fmt, cards_on = self.app, self.prefs, self.fmt, self.cards_on
        local: list[Outgoing] = []

        def add(out: Outgoing) -> None:
            _append(local, replace(out, source=index, owner=owner), prefs.merge)

        if isinstance(item, Outgoing):
            item = replace(item, owner=owner, source=index,
                           fallback=tuple(replace(p, owner=owner, source=index) for p in item.fallback))
            if item.scene_only:
                try:
                    path = scene_file(app, item.scene_art) if prefs.scene_images and item.scene_art else ""
                    if path:
                        add(replace(item, image=path))
                except Exception as exc:
                    logger.warning("321Roll Lite queued scene image unavailable: %s", exc)
                    _remember_sent_scene(app, item, "failed")
            elif item.markdown and fmt == PLAIN:
                for part in _plain(item):
                    add(part)
            else:
                add(item)
            return local, cards_on
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
            rendered = await _to_image(app, item, prefs, self.budget)
            image, banner, cards_on = rendered.url, rendered.banner, not rendered.timed_out
        ending = isinstance(item, Msg) and (item.data or {}).get("kind") == "ending"
        if fresh and prefs.scene_images and (ending or not banner):
            try:
                path = scene_file(app, art)
                if path:
                    add(Outgoing(image=path, scene_room=room_id, scene_key=key, scene_only=True, scene_art=art))
                    planned[room_id] = key
            except Exception as exc:
                logger.warning("321Roll Lite scene image unavailable: %s", exc)
                _remember_sent_scene(app, Outgoing(scene_room=room_id, scene_key=key), "failed")
                planned[room_id] = key
        if ending and prefs.scene_images:
            for extra in (item.data or {}).get("extra_scene_keys", []):
                try:
                    extra_art = {**art, "key": extra}
                    path = scene_file(app, extra_art)
                    if path:
                        add(Outgoing(image=path, scene_only=True, scene_art=extra_art))
                except Exception as exc:
                    logger.warning("321Roll Lite ending image unavailable: %s", exc)
        if image:
            split = bool(mentions) and self.platform_name in QQ_OFFICIAL_PLATFORMS
            fallback = tuple(Outgoing(text=part, mentions=mentions if i == 0 and not split else (), owner=owner,
                                      source=index) for i, part in enumerate(chunks(render(item, PLAIN))))
            add(Outgoing(image=image, mentions=() if split else mentions,
                         scene_room=room_id if fresh and banner else "", scene_key=key, fallback=fallback))
            if split:
                add(Outgoing(text=CARD_MENTION_NOTE, mentions=mentions, markdown=fmt == MARKDOWN, mergeable=False))
            if fresh and banner:
                planned[room_id] = key
            return local, cards_on
        text = render(item, fmt)
        if not text:
            return local, cards_on
        parts = chunks(text)
        # Only a whole single-chunk item can be re-rendered; long text keeps exact fragment boundaries.
        fallback = tuple(Outgoing(text=part, mentions=mentions if i == 0 else (), owner=owner, source=index)
                         for i, part in enumerate(chunks(render(item, PLAIN)))) if fmt == MARKDOWN and len(parts) == 1 else ()
        for part_index, part in enumerate(parts):
            add(Outgoing(text=part, mentions=mentions if part_index == 0 else (),
                         markdown=fmt == MARKDOWN, fallback=fallback, mergeable=len(parts) == 1))
        return local, cards_on


async def prepare(app: "LiteApp", items: list[Any], platform_name: str, platform_id: str,
                  prefs: MessagePrefs | None = None, owners: list[int] | None = None) -> list[Outgoing]:
    cursor = PreparationCursor(app, items, platform_name, platform_id, prefs or load_prefs(app), owners)
    while cursor.next_index < len(cursor.items):
        await cursor.advance()
    return cursor.ready


Sender = Callable[[Any], Awaitable[Any]]


async def deliver(app: "LiteApp", send: Sender, items: list[Any], *, platform_name: str, platform_id: str,
                  merge: bool | None = None, owners: list[int] | None = None) -> DeliveryProgress:
    """Send in order; failures carry only the unconfirmed physical fragments, including any fallback.

    merge overrides the admin's choice, so a backlog goes out in as few messages as possible.
    """
    prefs = load_prefs(app)
    if merge is not None:
        prefs = replace(prefs, merge=merge)
    cursor = PreparationCursor(app, items, platform_name, platform_id, prefs, owners)
    progress = DeliveryProgress(set(), set())
    position = 0
    while cursor.ready or cursor.next_index < len(cursor.items):
        if not cursor.ready:
            try:
                await cursor.fill()
            except Exception as exc:
                progress.attempted.add(cursor.owners[cursor.next_index])
                raise DeliveryFailed(exc, list(cursor.ready), progress, cursor.deferred()) from exc
        if not cursor.ready:
            continue
        out = cursor.ready[0]
        if position and prefs.interval:
            await asyncio.sleep(prefs.interval)
        owned = {p.owner for p in out.fragments()}
        progress.attempted.update(owned)
        try:
            result = await send(_chain(out, platform_name))
            if result is False:
                raise RuntimeError("platform refused the message")
        except Exception as exc:
            if out.scene_only:
                logger.warning("321Roll Lite: %s refused a scene image (%s); sending the story text", platform_id, exc)
                _remember_sent_scene(app, out, "failed")
                progress.confirmed.update(owned)   # optional scene images are consumed even when refused
                cursor.ready.pop(0)
                position += 1
                continue
            if out.image and out.fallback:
                logger.warning("321Roll Lite: %s refused a story card (%s); sending text", platform_id, exc)
                _remember_sent_scene(app, out, "failed")
                cursor.ready[:1] = _plain(out)
                continue
            if not out.markdown:
                raise DeliveryFailed(exc, list(cursor.ready), progress, cursor.deferred()) from exc
            logger.warning("321Roll Lite: %s refused Markdown (%s); switching it to plain text", platform_id, exc)
            try:
                _block_markdown(app, platform_id)
            except Exception:
                logger.exception("321Roll Lite could not remember the Markdown fallback")
            cursor.fmt = PLAIN
            cursor.ready = [part for pending in cursor.ready
                            for part in (_plain(pending) if pending.markdown and not pending.image else [pending])]
            continue
        progress.confirmed.update(owned)
        _remember_sent_scene(app, out, "sent")
        cursor.ready.pop(0)
        position += 1
    return progress


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


RESUME_TYPE = "321roll.delivery.resume"


def _resume_payload(outgoing: list[Outgoing], deferred: list[DeferredItem] | None = None) -> dict[str, Any]:
    def units(out: Outgoing) -> list[dict[str, Any]]:
        if out.parts:
            return [unit for part in out.parts for unit in units(part)]
        if out.scene_only:
            return [{"kind": "scene", "art": out.scene_art, "room": out.scene_room, "key": out.scene_key}]
        if out.image:
            # Render service URLs can expire; a partly delivered row resumes its remaining cards as text.
            return [unit for part in out.fallback for unit in units(part)]
        return [{"kind": "text", "text": out.text, "mentions": [list(m) for m in out.mentions],
                 "markdown": out.markdown, "mergeable": out.mergeable,
                 "fallback": [unit for part in out.fallback for unit in units(part)]}]
    remaining = [unit for out in outgoing for unit in units(out)]
    for pending in deferred or []:
        if isinstance(pending.item, Outgoing):
            remaining.extend(units(pending.item))
        else:
            remaining.append({"kind": "item", "value": to_json(pending.item)})
    return {"type": RESUME_TYPE, "version": 3, "units": remaining}


def _decode_payload(row) -> list[Any]:
    if not row["items_json"]:
        return [row["text"]]
    value = json.loads(row["items_json"])
    if isinstance(value, list):
        return [from_json(item) for item in value]
    if not isinstance(value, dict) or value.get("type") != RESUME_TYPE or value.get("version") not in (2, 3) \
            or not isinstance(value.get("units"), list):
        raise ValueError("无法读取待发消息的续传格式")

    def unit(data, *, fallback=False) -> Any:
        if not isinstance(data, dict):
            raise ValueError("待发消息片段格式不正确")
        if data.get("kind") == "item" and value["version"] == 3 and not fallback:
            original = data.get("value")
            if not isinstance(original, str) and not (isinstance(original, dict) and isinstance(original.get("sections"), list)):
                raise ValueError("待发原始消息格式不正确")
            return from_json(original)
        if data.get("kind") == "scene" and not fallback:
            art = data.get("art")
            if not isinstance(art, dict) or not art or not all(isinstance(k, str) and isinstance(v, str) for k, v in art.items()):
                raise ValueError("待发场景图缺少资源信息")
            if not isinstance(data.get("room", ""), str) or not isinstance(data.get("key", ""), str):
                raise ValueError("待发场景图标记不正确")
            return Outgoing(scene_only=True, scene_art=art, scene_room=data.get("room", ""), scene_key=data.get("key", ""))
        if data.get("kind") != "text" or not isinstance(data.get("text"), str) or len(data["text"]) > MAX_MESSAGE:
            raise ValueError("待发文字片段格式不正确")
        mentions = data.get("mentions", [])
        if not isinstance(mentions, list) or not all(isinstance(m, list) and len(m) == 2
                                                    and all(isinstance(s, str) for s in m) for m in mentions):
            raise ValueError("待发消息提及格式不正确")
        if type(data.get("markdown", False)) is not bool or type(data.get("mergeable", True)) is not bool:
            raise ValueError("待发消息排版格式不正确")
        plain = data.get("fallback", [])
        if not isinstance(plain, list) or (fallback and (plain or data.get("markdown"))):
            raise ValueError("待发消息降级片段格式不正确")
        return Outgoing(text=data["text"], mentions=tuple(tuple(m) for m in mentions), markdown=data.get("markdown", False),
                        mergeable=data.get("mergeable", True), fallback=tuple(unit(p, fallback=True) for p in plain))
    return [unit(item) for item in value["units"]]


def _payload_text(items: list[Any]) -> str:
    # This is only the operator's preview; malformed content must not prevent saving exact progress.
    parts = []
    for item in items:
        try:
            parts.append(("[场景图]" if item.scene_only else item.text) if isinstance(item, Outgoing) else render(item, PLAIN))
        except Exception as exc:
            logger.warning("321Roll Lite could not render an outbox preview: %s", exc)
            parts.append("[消息暂时无法排版，原始内容已保留]")
    return "\n\n".join(parts)


class Notifier:
    """Messages the plugin sends on its own (timeouts, votes, announcements from a private chat).

    A platform may refuse them: a QQ official bot posts to a group on its own only when the group
    allows it ("允许机器人主动在群聊内发言") and only after the group has spoken to it since AstrBot
    started.  A refused message waits in the outbox with its full structure; the next /团 in that
    conversation carries it as part of the reply. Claiming, sending and settling share one conversation lock.
    """

    def __init__(self, app: "LiteApp") -> None:
        self.app = app
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, umo: str) -> asyncio.Lock:
        """One sender at a time per conversation, so a background message never lands inside a multi-part reply."""
        return self._locks.setdefault(umo, asyncio.Lock())

    def _target(self, umo: str) -> tuple[str, str]:
        platform_name, platform_id = platform_of(self.app, umo)
        if platform_name in QQ_OFFICIAL and not qq_reachable(self.app, umo):
            raise RuntimeError("QQ 官方机器人自启动后还没收到过这个群的消息，暂时无法主动发送")
        return platform_name, platform_id

    async def send(self, umo: str, items: Any) -> bool:
        items = [i for i in (items if isinstance(items, list) else [items]) if i]
        if not items:
            return True
        async with self.lock(umo):
            try:
                platform_name, platform_id = self._target(umo)
                await deliver(self.app, lambda chain: self.app.context.send_message(umo, chain), items,
                              platform_name=platform_name, platform_id=platform_id)
                return True
            except Exception as exc:
                logger.warning("321Roll Lite proactive send failed for %s: %s", umo, exc)
                partial = isinstance(exc, DeliveryFailed) and bool(exc.progress.confirmed)
                payload = _resume_payload(exc.remaining, exc.deferred) if partial else [to_json(i) for i in items]
                encoded = json.dumps(payload, ensure_ascii=False)
                text = _payload_text(_decode_payload({"items_json": encoded}) if partial else items)
                with self.app.store.tx() as c:
                    c.execute("INSERT INTO outbox(umo,text,items_json,state,attempts,last_error,created_at,updated_at) "
                              "VALUES(?,?,?,'pending',1,?,?,?)", (umo, text, encoded, str(exc)[:300], now(), now()))
                return False

    def _settle(self, rows, error: Exception | None, *, manual: bool = False) -> None:
        remaining: dict[int, list[Outgoing]] = {}
        deferred: dict[int, list[DeferredItem]] = {}
        if isinstance(error, DeliveryFailed):
            for out in error.remaining:
                for part in out.fragments():
                    remaining.setdefault(part.owner, []).append(part)
            for pending in error.deferred:
                deferred.setdefault(pending.owner, []).append(pending)
        with self.app.store.tx() as c:
            for row in rows:
                owner = row["id"]
                if isinstance(error, DeliveryFailed):
                    if owner not in error.progress.attempted and owner not in error.progress.confirmed:
                        continue
                    failed = owner in remaining or owner in deferred
                else:
                    failed = error is not None
                state = ("pending" if manual or row["attempts"] < 5 else "dropped") if failed else "sent"
                encoded, text = row["items_json"], row["text"]
                if failed and isinstance(error, DeliveryFailed) and (owner in error.progress.confirmed
                        or (encoded and isinstance(json.loads(encoded), dict))):
                    encoded = json.dumps(_resume_payload(remaining.get(owner, []), deferred.get(owner, [])), ensure_ascii=False)
                    text = _payload_text(_decode_payload({"items_json": encoded}))
                c.execute("UPDATE outbox SET state=?,items_json=?,text=?,attempts=attempts+1,last_error=?,updated_at=? WHERE id=?",
                          (state, encoded, text, str(error)[:300] if failed else "", now(), owner))

    async def _deliver_rows(self, rows, send: Sender, *, platform_name: str, platform_id: str,
                            manual: bool = False, proactive: bool = False) -> Exception | None:
        """The caller holds the conversation lock; never hold a database transaction across a send."""
        items, owners = [], []
        for row in rows:
            try:
                decoded = _decode_payload(row)
            except Exception as exc:
                self._settle([row], exc, manual=manual)
                return exc
            items.extend(decoded)
            owners.extend([row["id"]] * len(decoded))
        try:
            if proactive:
                platform_name, platform_id = self._target(rows[0]["umo"])
            await deliver(self.app, send, items, platform_name=platform_name, platform_id=platform_id,
                          merge=True, owners=owners)
        except Exception as exc:
            # Incremental preparation errors carry progress too; only setup/reachability failures lack it.
            self._settle(rows if isinstance(exc, DeliveryFailed) else rows[:1], exc, manual=manual)
            return exc
        self._settle(rows, None, manual=manual)
        return None

    async def carry(self, umo: str, send: Sender, *, platform_name: str, platform_id: str) -> None:
        """Carry a backlog on an incoming reply, atomically with respect to other senders in this conversation."""
        async with self.lock(umo):
            with self.app.store.read() as c:
                rows = c.execute("SELECT * FROM outbox WHERE umo=? AND state='pending' ORDER BY id LIMIT ?",
                                 (umo, PENDING_BATCH)).fetchall()
            if not rows:
                return
            error = await self._deliver_rows(rows, send, platform_name=platform_name, platform_id=platform_id)
            if error is not None:
                logger.warning("321Roll Lite could not deliver the backlog for %s: %s", umo, error)

    async def retry(self, item_id: int) -> None:
        with self.app.store.read() as c:
            row = c.execute("SELECT * FROM outbox WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise ValueError("消息不存在")
        umo = row["umo"]
        async with self.lock(umo):
            with self.app.store.read() as c:
                row = c.execute("SELECT * FROM outbox WHERE id=?", (item_id,)).fetchone()
            if row is None:
                raise ValueError("消息不存在")
            if row["state"] == "sent":
                return
            error = await self._deliver_rows([row], lambda chain: self.app.context.send_message(umo, chain),
                                             platform_name="", platform_id="", manual=True, proactive=True)
            if error is not None:
                raise error

    async def drop(self, item_id: int) -> None:
        with self.app.store.read() as c:
            row = c.execute("SELECT umo FROM outbox WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise ValueError("消息不存在")
        async with self.lock(row["umo"]):
            with self.app.store.tx() as c:
                c.execute("UPDATE outbox SET state='dropped',updated_at=? WHERE id=? AND state<>'sent'", (now(), item_id))
