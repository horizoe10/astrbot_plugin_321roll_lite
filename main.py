"""AstrBot entry point for 321Roll Lite."""
from __future__ import annotations

from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

from .roll_lite.app import LiteApp
from .roll_lite.commands import Caller, strip_command
from .roll_lite.delivery import deliver
from .roll_lite.version import PLUGIN_NAME, PLUGIN_VERSION


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

        async def send(item) -> None:
            async with self.app.notifier.lock(str(event.unified_msg_origin)):
                await deliver(self.app, event.send, [item], platform_name=platform_name, platform_id=platform_id)

        return Caller(
            umo=str(event.unified_msg_origin),
            platform_id=platform_id,
            group_id=str(event.get_group_id() or "") or None,
            user_id=user_id,
            user_name=str(event.get_sender_name() or user_id),
            is_admin=bool(event.is_admin()) or self.app.is_admin_id(user_id),
            send=send,
            mentions=self._mentions(event),
        )

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
        if not (woke or raw.startswith(("/", "／"))):
            return
        body = strip_command(raw)
        if body is None:
            return
        event.stop_event()
        caller = self._caller(event)
        await self.app.notifier.flush(caller.umo)
        reply = await self.app.router.dispatch(self.app, caller, body)
        items = reply.messages
        if reply.room_umo:
            await self.app.notifier.send(reply.room_umo, reply.messages)
            items = reply.ack
        try:
            async with self.app.notifier.lock(caller.umo):
                await deliver(self.app, event.send, items, platform_name=str(event.get_platform_name() or ""),
                              platform_id=caller.platform_id)
        except Exception:
            logger.exception("321Roll Lite failed to deliver a reply")
        return
        yield  # keeps this handler an async generator as AstrBot registers it
