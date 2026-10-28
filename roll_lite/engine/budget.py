"""One request/time budget shared by generation, repair and its continuity review."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import monotonic


class ModelUnavailable(RuntimeError):
    """No usable response at the provider transport boundary."""


class ModelLimitReached(ModelUnavailable):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


class ModelBudget:
    def __init__(self, max_calls: int, seconds: float) -> None:
        self.max_calls = max_calls
        self.calls = 0
        self._ends = monotonic() + seconds
        self.deadline_at = (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()

    def remaining(self, deadline_at: str | None = None) -> float:
        seconds = self._ends - monotonic()
        if deadline_at is not None:
            deadline = datetime.fromisoformat(deadline_at)
            if deadline.tzinfo is None:
                raise ValueError('model deadline must include a timezone')
            seconds = min(seconds, (deadline - datetime.now(UTC)).total_seconds())
        if seconds <= 0:
            raise ModelLimitReached('model_deadline_exceeded', '本次模型处理已达到总等待时间上限。')
        return seconds

    def claim(self, timeout: float, deadline_at: str | None = None) -> float:
        remaining = self.remaining(deadline_at)
        if self.calls >= self.max_calls:
            raise ModelLimitReached('model_budget_exhausted', '本次模型处理已达到总调用次数上限。')
        self.calls += 1
        return min(timeout, remaining)


LIMIT_CATEGORIES = frozenset({'model_budget_exhausted', 'model_deadline_exceeded'})
