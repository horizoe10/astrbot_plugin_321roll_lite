"""Load the plugin against a real AstrBot installation without installing it.

Usage: <astrbot venv python> -X utf8 tools/astrbot_smoke.py --core <AstrBot core dir>

Imports main.py through AstrBot's real API (decorators, Star, StarTools, events),
builds the plugin with a temporary data directory and a minimal context, then
sends a few '/团' commands through the registered message handler on a OneBot
and a QQ official event, printing what event.send() received and whether the
chain asked for Markdown.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", type=Path, required=True)
    args = parser.parse_args()
    os.chdir(args.core)
    sys.path.insert(0, str(args.core))
    data = Path(tempfile.mkdtemp(prefix="roll-lite-smoke-"))

    from astrbot.api.star import StarTools
    StarTools.get_data_dir = classmethod(lambda cls, name=None: data / (name or "plugin"))  # isolate from the real instance
    spec = importlib.util.spec_from_file_location("astrbot_plugin_321roll_lite", ROOT / "__init__.py",
                                                  submodule_search_locations=[str(ROOT)])
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    plugin_main = importlib.import_module("astrbot_plugin_321roll_lite.main")

    from astrbot.core.star.star_handler import star_handlers_registry
    handlers = [h for h in star_handlers_registry if h.handler_module_path == plugin_main.__name__]
    print("registered handlers:", [h.handler_name for h in handlers])

    class Context:
        registered = []

        def register_web_api(self, route, handler, methods, desc):
            self.registered.append((route, methods))

        async def send_message(self, umo, chain):
            return True

    from astrbot.api.event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.platform.platform_metadata import PlatformMetadata

    context = Context()
    plugin = plugin_main.RollLitePlugin(context, {"admin_ids": ["10001"]})
    print("web routes:", len(context.registered), "commands:", len(plugin.app.router.commands))

    async def say(text: str, platform: str) -> list[str]:
        message = AstrBotMessage()
        message.type = MessageType.GROUP_MESSAGE
        message.group_id = "20001"
        message.sender = MessageMember(user_id="10001", nickname="管理员")
        message.message_str = text
        message.message = []
        message.self_id = "bot"
        message.session_id = "20001"
        message.message_id = "m1"
        meta = PlatformMetadata(name=platform, description="smoke", id="smoke-" + platform)
        event = AstrMessageEvent(text, message, meta, "20001")
        event.is_at_or_wake_command = True
        replies = []

        async def send(chain):
            mark = "md" if chain.use_markdown_ else "plain"
            replies.append(f"[{mark}] " + chain.get_plain_text(with_other_comps_mark=True))

        event.send = send
        async for result in plugin.on_message(event):
            replies.append("[yielded] " + str(result))
        print("stopped:", event.is_stopped())
        return replies

    async def run() -> None:
        from astrbot_plugin_321roll_lite.roll_lite.delivery import save_prefs
        await plugin.initialize()
        save_prefs(plugin.app, {"format": "markdown", "interval": 0})
        for text, platform in (("团 帮助", "aiocqhttp"), ("团 世界", "qq_official"), ("团 开启 1", "aiocqhttp"),
                               ("团 加入", "aiocqhttp"), ("团 状态", "qq_official")):
            print(">>", platform, text)
            for reply in await say(text, platform):
                print(reply[:200].replace("\n", " / "))
        await plugin.terminate()

    try:
        asyncio.run(run())
    finally:
        shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    main()
