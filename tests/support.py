"""Test doubles: a scripted AstrBot context and helpers to drive '/团' commands."""
from __future__ import annotations

import json
import atexit
import shutil
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_FOLDERS: list[Path] = []
atexit.register(lambda: [shutil.rmtree(folder, ignore_errors=True) for folder in _FOLDERS])


def _install_astrbot_stub() -> None:
    if "astrbot.api.event" in sys.modules:
        return

    class MessageChain:
        def __init__(self) -> None:
            self.chain: list = []
            self.markdown = None
            self.t2i = None

        def message(self, text: str) -> "MessageChain":
            self.chain.append(("plain", text))
            return self

        def at(self, name: str, qq: str) -> "MessageChain":
            self.chain.append(("at", str(qq)))
            return self

        def use_t2i(self, value: bool) -> "MessageChain":
            self.t2i = value
            return self

        def use_markdown(self, value: bool) -> "MessageChain":
            self.markdown = value
            return self

        @property
        def text(self) -> str:
            return "".join(part for kind, part in self.chain if kind == "plain")

    class Image:
        @staticmethod
        def fromURL(url: str):
            return ("image", url)

        @staticmethod
        def fromFileSystem(path: str):
            return ("image", path)

    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    event.MessageChain = MessageChain
    components = types.ModuleType("astrbot.api.message_components")
    components.Image = Image
    sys.modules.update({"astrbot": astrbot, "astrbot.api": api, "astrbot.api.event": event,
                        "astrbot.api.message_components": components})


_install_astrbot_stub()

from roll_lite.app import LiteApp  # noqa: E402
from roll_lite.commands import Caller, strip_command  # noqa: E402
from roll_lite.render import PLAIN, render  # noqa: E402


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.completion_text = text
        self.usage = None


def _rules(prompt: str) -> dict[str, Any]:
    data = json.loads(prompt)
    return data.get("rules") or data.get("context", {}).get("rules") or {}


def scripted_model(system: str, prompt: str) -> str:
    """Answer each engine method with a contract-valid object built from its input."""
    data = json.loads(prompt)
    if "依据输入中的世界观和开头" in system:
        rules = data["rules"]
        template = next(iter(rules["templates"]))
        attr = next(iter(rules["attributes"]))
        return json.dumps({
            "scene": {"title": "钟楼下的走廊", "description": "放学铃响过很久，走廊尽头的钟楼又敲了一下。"},
            "goal": "弄清钟楼为什么多敲一下",
            "npcs": [{"name": "值班老师", "description": "拿着手电的中年老师", "motivation": "想早点锁门回家"}],
            "characters": [{"member_ref": ref, "display_name": f"角色{i}", "description": "学生", "template_ref": template}
                           for i, ref in enumerate(data["member_refs"], 1)],
            "suggestions": ["去钟楼看看", "询问值班老师"],
            "suggestion_checks": [{"kind": "check", "attribute_ref": attr, "difficulty": "standard", "failure_cost": "harm"},
                                  {"kind": "narrative", "attribute_ref": "", "difficulty": "", "failure_cost": ""}]},
            ensure_ascii=False)
    if "理解行动目标和方法" in system:
        attr = next(iter(data["rules"]["attributes"]))
        return json.dumps({"kind": "check", "attribute_ref": attr, "difficulty": "hard", "failure_cost": "setback",
                           "reason": "有不确定性", "clarification": "", "risk_response": ""}, ensure_ascii=False)
    if "根据机械回执叙述" in system:
        attr = next(iter(data["rules"]["attributes"]))
        return json.dumps({
            "paragraphs": [f"{data['actor']['name']}照着计划行动。", "走廊里的灯闪了一下。"],
            "facts": [{"kind": "world_fact", "subject_ref": "scene", "text": "走廊的灯会在钟响时闪烁"}],
            "npcs": [], "suggestions": ["推开钟楼的门", "检查闪烁的灯", "回教室取手电"],
            "suggestion_checks": [{"kind": "check", "attribute_ref": attr, "difficulty": "easy", "failure_cost": "setback"},
                                  {"kind": "narrative", "attribute_ref": "", "difficulty": "", "failure_cost": ""},
                                  {"kind": "narrative", "attribute_ref": "", "difficulty": "", "failure_cost": ""}],
            "progress": {"scene": None, "goal": None}}, ensure_ascii=False)
    if "评估相对风险" in system:
        return json.dumps({"ranking": [{"choice_ref": c["choice_ref"], "risk": 50 - i, "reason": "依据正文"}
                                       for i, c in enumerate(data["candidates"])]}, ensure_ascii=False)
    if "突发集体事件" in system:
        return json.dumps({"title": "钟声又响", "premise": "钟楼毫无预兆地连敲三下。",
                           "directions": [{"direction_ref": "climb", "label": "立刻爬上钟楼", "description": "趁钟声未停追上去",
                                           "risk": "楼梯朽坏", "cost": ""},
                                          {"direction_ref": "hide", "label": "躲进教室观察", "description": "先看清楚是谁在敲",
                                           "risk": "", "cost": "错过时机"}]}, ensure_ascii=False)
    raise AssertionError("unexpected model call: " + system[:80])


class FakeContext:
    def __init__(self, responder: Callable[[str, str], str] = scripted_model) -> None:
        self.responder = responder
        self.calls: list[tuple[str, str]] = []
        self.sent: list[tuple[str, str]] = []
        self.chains: list[tuple[str, Any]] = []
        self.web_apis: list[tuple[str, Any, list[str], str]] = []

    def get_platform_inst(self, platform_id: str) -> Any:
        return None

    async def llm_generate(self, *, chat_provider_id: str, prompt: str | None = None, system_prompt: str | None = None, **_: Any):
        self.calls.append((system_prompt or "", prompt or ""))
        return FakeResponse(self.responder(system_prompt or "", prompt or ""))

    async def get_current_chat_provider_id(self, umo: str) -> str:
        return "fake-provider"

    async def send_message(self, umo: str, chain: Any) -> bool:
        self.sent.append((umo, chain.text))
        self.chains.append((umo, chain))
        return True

    def register_web_api(self, route: str, handler: Any, methods: list[str], desc: str) -> None:
        self.web_apis.append((route, handler, methods, desc))


def make_app(config: dict[str, Any] | None = None, responder: Callable[[str, str], str] = scripted_model) -> LiteApp:
    folder = Path(tempfile.mkdtemp(prefix="roll-lite-test-"))
    _FOLDERS.append(folder)
    app = LiteApp(FakeContext(responder), {"admin_ids": ["admin"], "turn_timeout_seconds": 0, **(config or {})}, folder)
    app.install()
    return app


class Player:
    """Drives commands as one user; group=None makes it a private chat with the bot."""

    def __init__(self, app: LiteApp, user_id: str, name: str | None = None, group: str | None = "g1") -> None:
        self.app = app
        self.sent: list[str] = []

        async def send(item: Any) -> None:
            self.sent.append(render(item, PLAIN))

        umo = f"fake:GroupMessage:{group}" if group else f"fake:FriendMessage:{user_id}"
        self.caller = Caller(umo=umo, platform_id="fake", group_id=group, user_id=user_id,
                             user_name=name or user_id, is_admin=user_id in app.config.admin_ids, send=send)

    async def say(self, text: str) -> str:
        body = strip_command(text)
        assert body is not None, text
        reply = await self.app.router.dispatch(self.app, self.caller, body)
        self.last = reply
        items = reply.messages
        if reply.room_umo:
            await self.app.notifier.send(reply.room_umo, reply.messages)
            items = reply.ack
        return "\n".join(render(m, PLAIN) for m in items)


def group_text(app: LiteApp, group: str = "g1") -> str:
    """Everything the bot pushed into a group outside direct replies."""
    return "\n".join(text for umo, text in app.context.sent if umo == f"fake:GroupMessage:{group}")
