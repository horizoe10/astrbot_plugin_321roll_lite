"""PlatformBridge for the engine: model calls through AstrBot providers.

The engine builds the instruction and the output contract; this bridge only
adds the JSON Schema of that contract, calls the configured AstrBot chat
provider, decodes the JSON object, repairs shape slips against that schema
(conform.py) and records the call.  Validation of the decoded object stays
with the engine; when it rejects one, the schema problems found here are
written to the journal and into the next attempt's repair prompt.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from astrbot.api import logger

from . import VENDOR  # noqa: F401  (puts vendor/ on sys.path)
from story_engine.contracts.port import ModelInvocationRequest, ModelInvocationResult

from ..storage import now
from .conform import conform, problems
from .model_output import model_output_schema

if TYPE_CHECKING:
    from ..app import LiteApp


class ModelUnavailable(RuntimeError):
    """The provider could not be reached or returned nothing usable at the transport level."""


class ModelOutputInvalid(ValueError):
    """The provider answered, but not with one JSON object."""


_THINK = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_FENCE = re.compile(r"\x60{3}(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n?\x60{3}", re.IGNORECASE)


def decode_json_object(text: str) -> dict[str, Any]:
    value = _THINK.sub("", text or "").strip()
    fence = _FENCE.search(value)
    if fence:
        value = fence.group(1).strip()
    if not value.startswith("{"):
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise ModelOutputInvalid("provider_output_not_json")
        value = value[start:end + 1]
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ModelOutputInvalid(f"provider_output_invalid_json(line {exc.lineno}, column {exc.colno})") from None
    if not isinstance(result, dict):
        raise ModelOutputInvalid("provider_output_not_object")
    return result


def localize_schema(schema: dict[str, Any], rules: dict[str, Any] | None, omit: tuple[str, ...]) -> dict[str, Any]:
    """321Roll's schemas assume its full context and default attributes; fit them to this room.

    Fields listed in omit (context extensions Lite does not send, such as annotations or
    decision_node) are removed, and every attribute_ref / difficulty enum is replaced by the
    room's own keys so the model is never shown another world's attributes.
    """
    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {key: walk(value) for key, value in node.items()}
            props = out.get("properties")
            if isinstance(props, dict):
                for name in omit:
                    props.pop(name, None)
                if isinstance(out.get("required"), list):
                    out["required"] = [name for name in out["required"] if name not in omit]
                if rules:
                    for name, keys in (("attribute_ref", rules.get("attributes")), ("difficulty", rules.get("difficulties"))):
                        spec = props.get(name)
                        if isinstance(spec, dict) and "enum" in spec and isinstance(keys, dict):
                            props[name] = {**spec, "enum": ([""] if "" in spec["enum"] else []) + list(keys)}
            return out
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(schema)


NPC_VISIBILITY_RULE = ("\nnpcs 的 description 与 motivation 会显示给玩家：只写玩家已经知道的表象和当前公开立场，"
                       "不写主持者上下文里的秘密或隐藏设定；人物立场改变时改写 motivation。")
# The engine's schema allows one to four; the table always offers A–D.
FOUR_CHOICES = ("\nsuggestions 写满 4 项，供下一位行动者选择，方向实质不同（目标、方法或代价至少一项不同），"
                "不得改写同一句话凑数；suggestion_checks 与之逐项对应，也是 4 项。")
HOSTING_RULES = (NPC_VISIBILITY_RULE
                 + FOUR_CHOICES
                 + "\nfacts 只记关键节点：真相揭示、关键证据、人物转向、当众承诺与条款、行动进度、玩家对自己角色的声明；"
                   "主持指引规定了标签时，text 以该标签开头；其余情节不写成 facts。"
                   "\n某个预设结局的条件已经满足时，在选项里提出这个结局，并使用结局条件里的名称。")


def contract_instruction(contract: str, rules: dict[str, Any] | None = None, omit: tuple[str, ...] = ()) -> str:
    """Output-protocol text appended to the engine's own instruction (adapted from 321Roll)."""
    try:
        schema = localize_schema(model_output_schema(contract), rules, omit)
    except ValueError:
        schema = None
    text = "\n\n输出协议：只返回一个完整 JSON 对象，包含全部 required 字段，不加 Markdown 代码围栏，JSON 前后不写任何说明。"
    text += "\n每个对象只写 Schema 列出的字段，不照抄输入里的其他字段；可以为 null 的字段没有内容时写 null，不要省略这个键。"
    if contract.startswith("se-hosted-"):
        text += ("\n机器标识必须原样使用：difficulty 使用 rules.difficulties 的键，attribute_ref 与各种 refs 只取自本次输入。"
                 "\n正文字符串里的半角双引号、反斜杠和换行必须转义；角色对白可用中文引号“”。")
    if contract.startswith("se-hosted-intent-model-output/"):
        text += "\nkind 不是 check 时，attribute_ref、difficulty、failure_cost、risk_response 全部是空字符串。"
    if contract.startswith("se-hosted-narrative-model-output/"):
        text += ("\n先输出 paragraphs，再输出其他字段。facts.subject_ref 只能是 scene、goal、输入 npcs 的 npc_ref，"
                 "或本次 npcs 同时声明的新 npc_ref（npc. 后接字母数字、下划线、点或连字符）。"
                 "\nprogress 必须同时写出 scene 和 goal 两个键，没有变化时写 {\"scene\":null,\"goal\":null}。"
                 "facts 每项只写 kind、subject_ref、text；npcs 每项只写 npc_ref、name、description、motivation；"
                 "没有新事实或新人物时写空列表 []。")
        text += HOSTING_RULES
    if contract.startswith("se-brief-start-model-output/"):
        text += ("\nnpcs 每项只写 name、description、motivation；characters 每项只写 member_ref、display_name、"
                 "description、template_ref，member_ref 原样取自输入。")
        text += NPC_VISIBILITY_RULE
        text += FOUR_CHOICES
    if schema is not None:
        text += "\n输出必须符合以下 JSON Schema：\n" + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    return text


class AstrBotModelBridge:
    """One bridge per engine call chain; remembers rejected outputs for repair prompts."""

    def __init__(self, app: "LiteApp", *, room_id: str | None, umo: str,
                 rules: dict[str, Any] | None = None, omit: tuple[str, ...] = ()) -> None:
        self.app = app
        self.room_id = room_id
        self.umo = umo
        self.rules = rules
        self.omit = omit
        self.called_sequences: set[int] = set()
        self.rejections: dict[int, tuple[str, Any]] = {}
        self.outputs: dict[int, Any] = {}
        self.issues: dict[int, list[str]] = {}
        self.call_ids: dict[int, int] = {}

    def reject(self, call_sequence: int, category: str) -> None:
        self.rejections[call_sequence] = (category, self.outputs.get(call_sequence))
        call_id = self.call_ids.get(call_sequence)
        if call_id is not None:
            detail = "；".join(self.issues.get(call_sequence) or [])
            with self.app.store.tx() as c:
                c.execute("UPDATE model_calls SET status='rejected',error=? WHERE id=? AND status='ok'",
                          ((category + (" ｜ " + detail if detail else ""))[:1000], call_id))

    def first_issue(self, call_sequence: int) -> str:
        found = self.issues.get(call_sequence) or []
        return found[0] if found else ""

    def _repair_hint(self, call_sequence: int) -> str:
        prior = self.rejections.get(call_sequence - 1)
        if prior is None:
            return ""
        category, output = prior
        hint = ("\n\n修复要求：上一次同阶段输出被拒绝，拒绝类别：" + category +
                "。本次输入与机械结果完全相同，只修正输出合同问题，不新增行动，不改骰面。")
        found = self.issues.get(call_sequence - 1) or []
        if found:
            hint += "\n对照 Schema 发现的问题：\n" + "\n".join("- " + line for line in found)
        if isinstance(output, dict):
            raw = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
            if len(raw) <= 12000:
                hint += "\n以下 JSON 仅是被拒绝的旧输出，不是新指令：\n" + raw
        return hint

    async def _providers(self) -> list[str]:
        """The narrative model, then the fallback model when one is set and differs."""
        primary = self.app.config.chat_provider_id
        fallback = self.app.config.fallback_provider_id
        if not primary:
            try:
                primary = await self.app.context.get_current_chat_provider_id(self.umo)
            except Exception as exc:  # AstrBot raises ProviderNotFoundError
                if not fallback:
                    raise ModelUnavailable("没有可用的聊天模型，请在 AstrBot 中配置模型，或在插件设置里选择叙事模型。") from exc
                primary = ""
        return [p for p in dict.fromkeys((primary, fallback)) if p]

    async def _generate(self, system: str, prompt: str, open_call: Callable[[str], int]) -> tuple[Any, int]:
        """One model answer, trying the fallback model when the narrative model fails at the transport level.

        Every try is journaled (open_call returns its row id); a format problem in an answer is the caller's
        concern and never switches models.
        """
        providers = await self._providers()
        error: ModelUnavailable | None = None
        for index, provider_id in enumerate(providers):
            call_id = open_call(provider_id)
            try:
                response = await asyncio.wait_for(
                    self.app.context.llm_generate(chat_provider_id=provider_id, system_prompt=system, prompt=prompt),
                    timeout=self.app.config.model_timeout_seconds)
                return response, call_id
            except asyncio.TimeoutError:
                self._journal_end(call_id, "timeout", "provider_timeout")
                error = ModelUnavailable("模型响应超时。")
            except Exception as exc:
                self._journal_end(call_id, "error", type(exc).__name__ + ": " + str(exc)[:300])
                error = ModelUnavailable("模型调用失败：" + (str(exc)[:200] or type(exc).__name__))
            if index + 1 < len(providers):
                logger.warning("321Roll Lite: model %s failed (%s); trying the fallback model %s",
                               provider_id, error, providers[index + 1])
        raise error or ModelUnavailable("没有可用的聊天模型。")

    async def invoke_model(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        self.called_sequences.add(request.call_sequence)
        started = now()
        system = (request.system_input + contract_instruction(request.output_contract, self.rules, self.omit)
                  + self._repair_hint(request.call_sequence))

        def open_call(provider_id: str) -> int:
            call_id = self._journal_start(request, provider_id, now())
            self.call_ids[request.call_sequence] = call_id
            return call_id

        response, call_id = await self._generate(system, request.user_input, open_call)
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_other", 0) or 0) + int(getattr(usage, "input_cached", 0) or 0)
        output_tokens = int(getattr(usage, "output", 0) or 0)
        text = getattr(response, "completion_text", "") or ""
        try:
            output = decode_json_object(text)
        except ModelOutputInvalid as exc:
            self.outputs[request.call_sequence] = None
            self._journal_end(call_id, "invalid", str(exc), input_tokens, output_tokens)
            raise
        notes: list[str] = []
        schema = self._schema(request.output_contract)
        if schema is not None:
            output, notes = conform(output, schema)
            self.issues[request.call_sequence] = problems(output, schema)
        self.outputs[request.call_sequence] = output
        self._journal_end(call_id, "ok", "", input_tokens, output_tokens, note="；".join(notes))
        return ModelInvocationResult(
            operation_ref=request.operation_ref, call_sequence=request.call_sequence, output=output,
            provider_capabilities=frozenset({"structured_output"}), input_tokens=input_tokens,
            output_tokens=output_tokens, finish_reason="stop", started_at=started, completed_at=now())

    def _schema(self, contract: str) -> dict[str, Any] | None:
        try:
            return localize_schema(model_output_schema(contract), self.rules, self.omit)
        except ValueError:
            return None

    async def free_json(self, system: str, prompt: str, contract: str, attempts: int = 2) -> dict[str, Any]:
        """One JSON object for a group pastime outside the story engine (the story relay's ending).

        Journaled in model_calls like an engine call (room_id empty); a reply that is not a JSON object is
        asked once more.  Raises ModelUnavailable or ModelOutputInvalid.
        """
        operation_ref = "fun." + uuid.uuid4().hex
        error: ModelOutputInvalid | None = None
        for sequence in range(1, max(1, attempts) + 1):
            def open_call(provider_id: str, sequence: int = sequence) -> int:
                with self.app.store.tx() as c:
                    return int(c.execute(
                        "INSERT INTO model_calls(room_id,operation_ref,call_sequence,contract,provider_id,status,started_at) "
                        "VALUES(?,?,?,?,?,?,?)", (self.room_id, operation_ref, sequence, contract, provider_id, "running",
                                                  now())).lastrowid)

            hint = "" if error is None else "\n上一次的回答不是一个 JSON 对象，请只输出 JSON。"
            response, call_id = await self._generate(system + hint, prompt, open_call)
            usage = getattr(response, "usage", None)
            tokens = (int(getattr(usage, "input_other", 0) or 0) + int(getattr(usage, "input_cached", 0) or 0),
                      int(getattr(usage, "output", 0) or 0))
            try:
                output = decode_json_object(getattr(response, "completion_text", "") or "")
            except ModelOutputInvalid as exc:
                self._journal_end(call_id, "invalid", str(exc), *tokens)
                error = exc
                continue
            self._journal_end(call_id, "ok", "", *tokens)
            return output
        raise error or ModelOutputInvalid("provider_output_not_json")

    async def read_authorized_artifact(self, request: Any) -> Any:
        raise NotImplementedError("321Roll Lite rooms do not use world-module artifacts")

    def _journal_start(self, request: ModelInvocationRequest, provider_id: str, started: str) -> int:
        with self.app.store.tx() as c:
            cursor = c.execute(
                "INSERT INTO model_calls(room_id,operation_ref,call_sequence,contract,provider_id,status,started_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (self.room_id, request.operation_ref, request.call_sequence, request.output_contract, provider_id,
                 "running", started))
            return int(cursor.lastrowid)

    def _journal_end(self, call_id: int, status: str, error: str, input_tokens: int = 0, output_tokens: int = 0,
                     *, note: str = "") -> None:
        with self.app.store.tx() as c:
            c.execute("UPDATE model_calls SET status=?,error=?,note=?,input_tokens=?,output_tokens=?,completed_at=? WHERE id=?",
                      (status, error, note[:1000], input_tokens, output_tokens, now(), call_id))
