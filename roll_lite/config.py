"""Plugin configuration read from AstrBot's _conf_schema.json values."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def _ids(value: Any) -> frozenset[str]:
    if isinstance(value, str):
        value = value.replace("，", ",").split(",")
    if not isinstance(value, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(str(item).strip() for item in value if str(item).strip())


def _int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, number))


@dataclass(frozen=True, slots=True)
class LiteConfig:
    admin_ids: frozenset[str]
    group_whitelist_enabled: bool
    allowed_groups: frozenset[str]
    chat_provider_id: str
    fallback_provider_id: str
    model_timeout_seconds: int
    model_attempts: int
    turn_timeout_seconds: int
    default_seat_cap: int
    max_seat_cap: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "LiteConfig":
        value = value or {}
        max_cap = _int(value.get("max_seat_cap"), 8, 1, 16)
        return cls(
            admin_ids=_ids(value.get("admin_ids")),
            group_whitelist_enabled=bool(value.get("group_whitelist_enabled", False)),
            allowed_groups=_ids(value.get("allowed_groups")),
            chat_provider_id=str(value.get("chat_provider_id") or "").strip(),
            fallback_provider_id=str(value.get("fallback_provider_id") or "").strip(),
            model_timeout_seconds=_int(value.get("model_timeout_seconds"), 120, 15, 600),
            model_attempts=_int(value.get("model_attempts"), 3, 1, 3),
            turn_timeout_seconds=_int(value.get("turn_timeout_seconds"), 300, 0, 86400),
            default_seat_cap=min(max_cap, _int(value.get("default_seat_cap"), 4, 1, 16)),
            max_seat_cap=max_cap,
        )

    def group_allowed(self, group_id: str | None) -> bool:
        return not self.group_whitelist_enabled or (group_id is not None and group_id in self.allowed_groups)
