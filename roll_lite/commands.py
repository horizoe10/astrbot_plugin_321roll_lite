"""'/团' command routing.

Modules register verbs with Router.register().  A verb is one word ("加入") or
two words ("主持 险关"); the two-word form wins when both match.  Handlers are
    async def handler(app, caller, args: str) -> Reply
and raise UserError for anything the player should read.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .app import LiteApp

logger = logging.getLogger("astrbot_plugin_321roll_lite")

COMMAND_WORD = "团"
_PREFIX = re.compile(r"^\s*[/／]?\s*团(?:\s+|$)")


class UserError(Exception):
    """A refusal or validation failure shown to the player as is."""

    def __init__(self, message: str, *, code: str = "rejected") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class Reply:
    """Messages in sending order; each is a render.Msg or a plain string.

    room_umo: set when a command sent from a private chat must post its result to the group;
    ack is then what the private chat receives instead.
    private_only: a query whose answer stays in the private chat even for "room" commands.
    """
    messages: list[Any] = field(default_factory=list)
    room_umo: str | None = None
    ack: list[Any] = field(default_factory=list)
    private_only: bool = False

    def say(self, *items: Any) -> "Reply":
        self.messages.extend(item for item in items if item)
        return self

    def extend(self, other: "Reply | None") -> "Reply":
        if other is not None:
            self.messages.extend(other.messages)
        return self


@dataclass(frozen=True)
class Caller:
    umo: str                 # AstrBot unified_msg_origin of the conversation
    platform_id: str
    group_id: str | None     # None in a private chat
    user_id: str
    user_name: str
    is_admin: bool
    send: Callable[[Any], Awaitable[None]]   # immediate message (Msg or str) into this conversation
    private_umo: str | None = None           # set when a private-chat command runs in its group's context
    mentions: tuple[str, ...] = ()           # user ids @-mentioned in the message, the bot itself excluded

    @property
    def in_group(self) -> bool:
        return self.group_id is not None

    @property
    def in_private(self) -> bool:
        return self.private_umo is not None


Handler = Callable[["LiteApp", Caller, str], Awaitable[Reply]]


@dataclass(frozen=True)
class Command:
    verb: str
    handler: Handler
    summary: str
    usage: str
    topic: str
    admin: bool
    group_only: bool
    # Private chat: "" not allowed, "self" result stays private, "room" result is posted to the group.
    private: str = ""


def strip_command(text: str) -> str | None:
    """Return the text after '/团' or None when the message is not a Lite command."""
    match = _PREFIX.match(text or "")
    if not match:
        return None
    return (text or "")[match.end():].strip()


def ack_text(items: list[Any]) -> str:
    """What a private chat sees after its command was posted to the group: the gist of the first message."""
    from .render import PLAIN, render
    lines = []
    for line in (raw.strip() for raw in render(items[0], PLAIN).split("\n")):
        if line.startswith(("〔接下来", "›")):
            break
        if line:
            lines.append(line)
    gist = [line if len(line) <= 60 else line[:59] + "…" for line in lines[:3]]
    return "已发到群里：\n" + "\n".join(gist) if gist else "已发到群里。"


class Router:
    def __init__(self) -> None:
        self.commands: dict[str, Command] = {}

    def register(self, verbs: str | tuple[str, ...] | list[str], handler: Handler, *, summary: str,
                 usage: str = "", topic: str = "其他", admin: bool = False, group_only: bool = True,
                 private: str = "") -> None:
        for verb in ([verbs] if isinstance(verbs, str) else list(verbs)):
            key = " ".join(verb.split())
            if key in self.commands:
                raise ValueError(f"command already registered: {key}")
            self.commands[key] = Command(key, handler, summary, usage or f"/团 {key}", topic, admin, group_only, private)

    def resolve(self, body: str) -> tuple[Command, str] | None:
        words = body.split(maxsplit=2)
        if len(words) >= 2 and f"{words[0]} {words[1]}" in self.commands:
            return self.commands[f"{words[0]} {words[1]}"], (words[2] if len(words) > 2 else "")
        if words and words[0] in self.commands:
            return self.commands[words[0]], body[len(words[0]):].strip()
        return None

    async def dispatch(self, app: "LiteApp", caller: Caller, body: str) -> Reply:
        if not body:
            body = "帮助"
        found = self.resolve(body)
        if found is None:
            return Reply().say(self.unknown(body))
        command, args = found
        if not caller.in_group:
            from .shared import private_scope
            with app.store.tx() as c:
                if app.store.get_setting(c, private_scope(caller), "private.umo", None) != caller.umo:
                    app.store.set_setting(c, private_scope(caller), "private.umo", caller.umo)
        private_room = None
        if command.group_only and not caller.in_group:
            if not command.private:
                return Reply().say("这个指令只能在群聊里使用。")
            from .shared import private_room as find_private_room
            try:
                private_room = find_private_room(app, caller)
            except UserError as exc:
                return Reply().say(exc.message)
            original = caller
            send = caller.send
            if command.private == "room":
                async def send(item: Any, umo: str = private_room["umo"]) -> None:
                    await app.notifier.send(umo, item)
            caller = replace(caller, umo=private_room["umo"], group_id=private_room["group_id"],
                             platform_id=private_room["platform"], private_umo=original.umo, send=send,
                             is_admin=caller.is_admin)
        if command.admin and not caller.is_admin:
            return Reply().say("这个指令只有管理员可以使用。")
        if caller.in_group and not app.config.group_allowed(caller.group_id):
            return Reply()
        try:
            reply = await command.handler(app, caller, args)
        except UserError as exc:
            return Reply().say(exc.message)
        except Exception:
            logger.exception("321Roll Lite command failed: %s", command.verb)
            return Reply().say("处理指令时出现内部错误，已写入日志。请稍后再试或联系管理员。")
        if private_room is not None and command.private == "room" and reply.messages and not reply.private_only:
            reply.room_umo = private_room["umo"]
            if not reply.ack:
                reply.ack = [ack_text(reply.messages)]
        return reply

    def unknown(self, body: str) -> str:
        words = body.split()
        family = sorted(k for k in self.commands if " " in k and k.split()[0] == words[0])
        if family and len(words) > 1:
            return (f"没有“{words[0]} {words[1]}”这个指令。可用的{words[0]}指令："
                    + "、".join(k.split()[1] for k in family) + f"。发送 /团 帮助 {self.commands[family[0]].topic} 查看写法。")
        if family:
            return f"“{words[0]}”后面要接具体指令：" + "、".join(k.split()[1] for k in family) + "。"
        return f"没有“{words[0]}”这个指令。发送 /团 帮助 查看可用指令。"

    def help_text(self, topic: str = "", *, is_admin: bool = False) -> Any:
        from . import messages
        visible = [c for c in self.commands.values() if is_admin or not c.admin]
        topics: dict[str, list[Command]] = {}
        for command in visible:
            topics.setdefault(command.topic, []).append(command)
        if topic and topic in topics:
            seen: dict[Any, Command] = {}
            for c in topics[topic]:
                seen.setdefault(c.handler, c)
            return messages.help_topic(topic, [(c.usage, c.summary) for c in seen.values()])
        return messages.help_index(list(topics))


def register_core(router: Router) -> None:
    async def help_command(app: "LiteApp", caller: Caller, args: str) -> Reply:
        return Reply().say(app.router.help_text(args.strip(), is_admin=caller.is_admin))

    router.register("帮助", help_command, summary="查看指令", usage="/团 帮助 [分类]", topic="基础", group_only=False)


def parse_check(args: str, attributes: dict[str, str], difficulties: dict[str, Any]) -> tuple[str, dict[str, str] | None]:
    """Split a trailing '[属性 难度]' (half or full-width brackets) off the text.

    attributes maps attribute id -> display name; difficulties maps difficulty key ->
    display name or {'label': ...}.  Returns (remaining text, {'attribute_ref', 'difficulty'} or None).
    Raises UserError for an unknown attribute or difficulty.
    """
    match = re.search(r"[\[［【]\s*([^\]］】]+?)\s*[\]］】]\s*$", args)
    if not match:
        return args.strip(), None
    words = match.group(1).split()
    by_name = {name: ref for ref, name in attributes.items()} | {ref: ref for ref in attributes}
    diff_names = {}
    for key, value in difficulties.items():
        label = value.get("label") if isinstance(value, dict) else value
        diff_names[str(label)] = key
        diff_names[key] = key
    attribute = next((by_name[w] for w in words if w in by_name), None)
    difficulty = next((diff_names[w] for w in words if w in diff_names), None)
    if attribute is None or difficulty is None or len(words) != 2:
        raise UserError("检定写法是句末的 [属性 难度]，例如 [观察 困难]。属性：" + "、".join(attributes.values())
                        + "；难度：" + "、".join(k for k in diff_names if k not in difficulties))
    return args[:match.start()].strip(), {"attribute_ref": attribute, "difficulty": difficulty}


_REF = re.compile(r"[#＃](\d{1,6})")


def parse_refs(args: str) -> tuple[list[int], str]:
    """Pull every '#n' record reference out of the text, in order."""
    refs = [int(n) for n in _REF.findall(args)]
    return refs, _REF.sub(" ", args).strip()


def split_title(text: str) -> tuple[str, str]:
    """'标题：正文' -> (标题, 正文); without a colon the first sentence is the title."""
    for mark in ("：", ":"):
        if mark in text:
            head, body = text.split(mark, 1)
            if head.strip() and body.strip():
                return head.strip(), body.strip()
    first = re.split(r"[。！？!?；;\n]", text.strip(), maxsplit=1)[0].strip()
    return (first[:40] or text.strip()[:40]), text.strip()
