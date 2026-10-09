"""AstrBot entry point for 321Roll Lite."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

from .roll_lite import personas
from .roll_lite.app import LiteApp
from .roll_lite.commands import Attachment, Caller, conversation_origin, strip_command
from .roll_lite.delivery import deliver
from .roll_lite.version import PLUGIN_NAME, PLUGIN_VERSION

MAX_ATTACHMENT = 8 * 1024 * 1024


class RollLitePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.app = LiteApp(context, config, Path(StarTools.get_data_dir(PLUGIN_NAME)))
        self.app.star = self  # text_to_image for image segments
        self.app.install()

    async def initialize(self) -> None:
        self.app.start()
        logger.info("321Roll Lite %s loaded", PLUGIN_VERSION)

    async def terminate(self) -> None:
        await self.app.stop()

    def _caller(self, event: AstrMessageEvent) -> Caller:
        user_id = str(event.get_sender_id() or "")
        platform_name = str(event.get_platform_name() or "")
        platform_id = str(event.get_platform_id() or "")
        umo = conversation_origin(event)
        group_id = str(event.get_group_id() or "") or None
        if group_id:
            self.app.adopt_group_room(umo, platform_id, group_id)

        async def send(item) -> None:
            async with self.app.notifier.lock(umo):
                await deliver(self.app, event.send, [item], platform_name=platform_name, platform_id=platform_id)

        return Caller(
            umo=umo,
            platform_id=platform_id,
            group_id=group_id,
            user_id=user_id,
            user_name=str(event.get_sender_name() or user_id),
            is_admin=bool(event.is_admin()) or self.app.is_admin_id(user_id),
            send=send,
            mentions=self._mentions(event),
            quote=self._quote(event),
            attachments=self._attachments(event),
        )

    @staticmethod
    def _attachments(event: AstrMessageEvent) -> tuple[Attachment, ...]:
        """Files and pictures in the message; their bytes are read only when a command needs them."""
        try:
            from astrbot.api.message_components import File, Image
            parts = list(event.get_messages())
        except Exception:
            return ()

        async def read(path: str) -> bytes:
            if not path or str(path).startswith(("http://", "https://")) or not os.path.isfile(path):
                return b""
            if os.path.getsize(path) > MAX_ATTACHMENT:
                return b""
            return await asyncio.to_thread(Path(path).read_bytes)

        found: list[Attachment] = []
        for part in parts:
            if isinstance(part, File):
                async def fetch(part=part) -> bytes:
                    return await read(await part.get_file())
                found.append(Attachment("file", str(part.name or "file"), fetch))
            elif isinstance(part, Image):
                async def fetch(part=part) -> bytes:
                    return await read(await part.convert_to_file_path())
                found.append(Attachment("image", "image", fetch))
        return tuple(found)

    @staticmethod
    def _quote(event: AstrMessageEvent) -> str:
        """Plain text of the message being replied to (OneBot and QQ official both fill message_str)."""
        try:
            from astrbot.api.message_components import Plain, Reply
            for part in event.get_messages():
                if isinstance(part, Reply):
                    text = str(part.message_str or part.text or "")
                    if not text and part.chain:
                        text = "".join(str(p.text) for p in part.chain if isinstance(p, Plain))
                    return text.strip()
        except Exception:
            return ""
        return ""

    @staticmethod
    def _mentions(event: AstrMessageEvent) -> tuple[str, ...]:
        """Users @-mentioned in the message (the bot excluded), so host commands can name a player with @."""
        try:
            from astrbot.api.message_components import At
            own = str(event.get_self_id() or "")
            found = [str(part.qq) for part in event.get_messages() if isinstance(part, At)]
        except Exception:
            return ()
        return tuple(dict.fromkeys(q for q in found if q and q != own and q != "all"))

    @filter.event_message_type(filter.EventMessageType.ALL, priority=100)
    async def on_message(self, event: AstrMessageEvent):
        raw = str(event.message_str or "").strip()
        woke = bool(getattr(event, "is_at_or_wake_command", False))
        if not raw.startswith(("/", "／")) and not event.get_group_id() and \
                personas.waiting(self.app, str(event.get_platform_id() or ""), str(event.get_sender_id() or "")):
            # A card or picture sent after /团 人设 导入 or /团 人设 头像 in a private chat.
            caller = self._caller(event)
            reply = await personas.receive(self.app, caller)
            if reply is not None:
                event.stop_event()
                async with self.app.notifier.lock(caller.umo):
                    await deliver(self.app, event.send, reply.messages, platform_name=str(event.get_platform_name() or ""),
                                  platform_id=caller.platform_id)
                return
        if not (woke or raw.startswith(("/", "／"))):
            return
        body = strip_command(raw)
        if body is None:
            return
        event.stop_event()
        caller = self._caller(event)
        platform_name = str(event.get_platform_name() or "")
        await self.app.notifier.carry(caller.umo, event.send, platform_name=platform_name, platform_id=caller.platform_id)
        reply = await self.app.router.dispatch(self.app, caller, body)
        items = reply.messages
        if reply.room_umo:
            await self.app.notifier.send(reply.room_umo, reply.messages)
            items = reply.ack
        try:
            async with self.app.notifier.lock(caller.umo):
                await deliver(self.app, event.send, items, platform_name=platform_name, platform_id=caller.platform_id)
        except Exception:
            logger.exception("321Roll Lite failed to deliver a reply")
        return
        yield  # keeps this handler an async generator as AstrBot registers it
