"""The only door into the engine for platform code.

Methods of the hosted-turn dispatcher used by Lite:
  propose_intent / narrate_committed      hosted turn (model, call_sequence 1..3)
  rank_timeout_choices                    timeout ranking (model, call_sequence 1..2)
  propose_collective_event                collective event (model)
  custom_play_catalog / evaluate_custom_play   engine plays (pure, no model)
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from . import VENDOR  # noqa: F401
from story_engine.contracts.port import PortContractError
from story_engine.brief_start import create_embedded_brief_start_engine
from story_engine.custom_plays import CustomPlayError
from story_engine.hosted_turn import create_embedded_hosted_turn_engine
from story_engine.versions import STORY_ENGINE_DISTRIBUTION_VERSION

from .bridge import AstrBotModelBridge, ModelOutputInvalid, ModelUnavailable

if TYPE_CHECKING:
    from ..app import LiteApp

ENGINE_VERSION = STORY_ENGINE_DISTRIBUTION_VERSION
MAX_SEQUENCE = {"rank_timeout_choices": 2, "generate_initial_story": 2}
BRIEF_METHODS = frozenset({"generate_initial_story", "world_rules", "quick_character"})
# Context extensions 321Roll sends and Lite does not; their output fields are dropped from schemas.
OMITTED_OUTPUT_FIELDS = ("annotations", "decision_node", "play_hooks", "chapter_plan", "opening_world")


class EngineInputError(RuntimeError):
    """The platform handed the engine an invalid request; a platform bug, never retried."""


class EngineCallFailed(RuntimeError):
    """Every allowed model attempt was rejected or the provider stayed unavailable."""

    def __init__(self, method: str, category: str, user_message: str) -> None:
        super().__init__(f"{method}: {category}")
        self.method = method
        self.category = category
        self.user_message = user_message


def new_operation_ref(prefix: str = "op") -> str:
    return f"{prefix}.{uuid.uuid4().hex}"


class EngineGateway:
    def __init__(self, app: "LiteApp") -> None:
        self.app = app
        self.engine = create_embedded_hosted_turn_engine()
        self.brief_engine = create_embedded_brief_start_engine()
        self._catalog: dict[str, Any] | None = None

    # ------------------------------------------------------------ pure plays
    async def catalog(self) -> dict[str, Any]:
        if self._catalog is None:
            self._catalog = await self.engine.dispatch("custom_play_catalog", {})
        return self._catalog

    async def evaluate_custom_play(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Raises CustomPlayError('custom_play.<code>') for a rejected action."""
        return await self.engine.dispatch("evaluate_custom_play", payload)

    async def compile_world(self, world: dict[str, Any]) -> dict[str, Any]:
        """321roll.world-template/1 -> engine rules (raises ValueError for an unusable world)."""
        return await self.brief_engine.dispatch("world_rules", {"world": world})

    # ------------------------------------------------------------ model-backed
    async def call(self, method: str, fields: dict[str, Any], *, room_id: str | None, umo: str,
                   rules: dict[str, Any] | None = None, operation_ref: str | None = None) -> dict[str, Any]:
        """Run one model-backed engine method with bounded repair attempts.

        fields are the method's own payload fields: {'context': ...} for hosted-turn methods,
        {'brief', 'member_refs', 'rules'} for generate_initial_story.  rules localize the
        output schema shown to the model.
        """
        operation_ref = operation_ref or new_operation_ref()
        attempts = min(self.app.config.model_attempts, MAX_SEQUENCE.get(method, 3))
        deadline = (datetime.now(UTC) + timedelta(seconds=self.app.config.model_timeout_seconds * attempts + 30)).isoformat()
        bridge = AstrBotModelBridge(self.app, room_id=room_id, umo=umo, rules=rules, omit=OMITTED_OUTPUT_FIELDS)
        engine = self.brief_engine if method in BRIEF_METHODS else self.engine
        category, message = "engine_unknown", "故事引擎没有给出结果。"
        for sequence in range(1, attempts + 1):
            payload = {"operation_ref": operation_ref, "call_sequence": sequence, "deadline_at": deadline,
                       "idempotency_key": f"{operation_ref}.model.{sequence}", **fields}
            try:
                return await engine.dispatch(method, payload, bridge)
            except ModelUnavailable as exc:
                category, message = "provider_unavailable", str(exc)
            except ModelOutputInvalid as exc:
                bridge.reject(sequence, str(exc))
                category, message = str(exc), "模型输出不是有效的 JSON。"
            except (ValueError, TypeError, KeyError, PortContractError) as exc:
                if sequence not in bridge.called_sequences:
                    raise EngineInputError(f"{method}: {exc!r}") from exc
                category = str(exc) or type(exc).__name__
                bridge.reject(sequence, category)
                issue = bridge.first_issue(sequence)
                message = "模型输出的格式不对：" + (issue or category) + "。"
        raise EngineCallFailed(method, category, message)


__all__ = ["CustomPlayError", "ENGINE_VERSION", "EngineCallFailed", "EngineGateway", "EngineInputError",
           "new_operation_ref"]
