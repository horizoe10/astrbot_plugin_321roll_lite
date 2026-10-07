"""Wiring: one LiteApp per plugin instance holds config, storage, engine, router and hooks.

Feature modules expose install(app) and talk to each other only through
app.hooks (see docs/ARCHITECTURE.md for the hook list and payloads).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any

from .commands import Reply, Router, register_core
from .config import LiteConfig
from .delivery import Notifier
from .engine.gateway import EngineGateway
from .features import Features
from .storage import Store

logger = logging.getLogger("astrbot_plugin_321roll_lite")
TICK_SECONDS = 5

HookFn = Callable[..., Awaitable[Reply | None]]
HOOKS = ("story_started", "roster_changed", "room_paused", "room_resumed", "story_completed",
         "room_closed", "room_restored", "status_lines", "tick")


class Hooks:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[HookFn]] = {name: [] for name in HOOKS}

    def on(self, name: str, fn: HookFn) -> None:
        if name not in self._subscribers:
            raise ValueError(f"unknown hook {name}")
        self._subscribers[name].append(fn)

    async def emit(self, name: str, **payload: Any) -> Reply:
        """Run subscribers in registration order and merge their replies.

        Failures propagate so the triggering command can report them; 'tick'
        isolates each subscriber because nobody is waiting for it.
        """
        merged = Reply()
        for fn in self._subscribers[name]:
            if name == "tick":
                try:
                    merged.extend(await fn(**payload))
                except Exception:
                    logger.exception("321Roll Lite tick subscriber failed: %r", fn)
            else:
                merged.extend(await fn(**payload))
        return merged


class LiteApp:
    def __init__(self, context: Any, raw_config: Any, data_dir: Path) -> None:
        self.context = context
        self.raw_config = raw_config
        self.config = LiteConfig.from_mapping(raw_config)
        self.data_dir = Path(data_dir)
        self.store = Store(self.data_dir / "lite.sqlite3")
        self.features = Features(self.store)
        self.engine = EngineGateway(self)
        self.notifier = Notifier(self)
        self.router = Router()
        self.hooks = Hooks()
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task] = set()
        self._ticker: asyncio.Task | None = None

    # ------------------------------------------------------------ assembly
    def install(self) -> None:
        from .plays import collaboration, custom, hosted, kit
        from .rooms import governance, lifecycle
        from .web import api

        register_core(self.router)
        lifecycle.install(self)
        governance.install(self)
        hosted.install(self)
        collaboration.install(self)
        custom.install(self)
        kit.install(self)
        api.install(self)

    def reload_config(self) -> None:
        self.config = LiteConfig.from_mapping(self.raw_config)

    def start(self) -> None:
        if self._ticker is None or self._ticker.done():
            self._ticker = asyncio.create_task(self._tick_loop(), name="321roll-lite-tick")

    async def stop(self) -> None:
        for task in [self._ticker, *self._tasks]:
            if task is not None and not task.done():
                task.cancel()
        self._tasks.clear()

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            try:
                reply = await self.hooks.emit("tick")
                for item in reply.messages:
                    logger.debug("tick produced an undirected message: %s", str(item)[:80])
            except Exception:
                logger.exception("321Roll Lite tick failed")

    # ------------------------------------------------------------ helpers
    def lock(self, key: str) -> asyncio.Lock:
        """Serialize read-model-commit sequences for one room (key = room id)."""
        return self._locks.setdefault(key, asyncio.Lock())

    def spawn(self, coroutine: Coroutine[Any, Any, Any], name: str) -> asyncio.Task:
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)

        def done(t: asyncio.Task) -> None:
            self._tasks.discard(t)
            if not t.cancelled() and t.exception() is not None:
                logger.error("321Roll Lite background task %s failed", name, exc_info=t.exception())

        task.add_done_callback(done)
        return task

    def is_admin_id(self, user_id: str) -> bool:
        return str(user_id) in self.config.admin_ids
