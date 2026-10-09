"""Per-play switches: a global default plus an optional per-group override.

Closing a play only stops new intake; records already in progress finish on
their own terms (each play decides which actions count as winding down).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .storage import Store


@dataclass(frozen=True, slots=True)
class Play:
    key: str
    label: str
    status: str            # 'active' | 'deferred' | 'removed'
    depends: tuple[str, ...] = ()
    kind: str = "story"    # 'story': a play at the table; 'fun': a group pastime outside the story


PLAYS: tuple[Play, ...] = (
    Play("playActions", "世界与行动", "active"),
    Play("playCollaboration", "协作与表决", "active"),
    Play("playInvestigation", "调查与线索", "active"),
    Play("playTestimony", "证词与对质", "active", ("playInvestigation",)),
    Play("playNegotiation", "交涉与谈判", "active"),
    Play("playRelations", "关系与声望", "active"),
    Play("playCalendar", "日历与期限", "active"),
    Play("playProjects", "长期项目", "active", ("playCalendar",)),
    Play("playConflict", "独立冲突", "active"),
    Play("playChase", "追逐", "active"),
    Play("playDebate", "辩论", "active"),
    Play("playPlans", "行动计划", "active"),
    Play("playOracle", "神谕建议", "active"),
    Play("playTransformation", "转变与传承", "active"),
    Play("playFortune", "机运与命运", "active"),
    Play("playBranchEndings", "分支与多结局", "active"),
    Play("playPersonas", "人设卡", "active"),
    Play("playPrivatePhases", "私人并行阶段", "deferred"),
    Play("playRegroup", "合法汇合", "deferred", ("playPrivatePhases",)),
    Play("playFlashback", "闪回准备", "deferred", ("playPlans",)),
    Play("playOutfitting", "整备", "removed"),
    Play("funDaily", "今日一掷", "active", kind="fun"),
    Play("funDice", "掷骰与对决", "active", kind="fun"),
    Play("funReport", "战报与喝彩", "active", kind="fun"),
    Play("funSchedule", "约团", "active", kind="fun"),
    Play("funRelay", "故事接龙", "active", kind="fun"),
    Play("funLuck", "骰运", "active", kind="fun"),
    Play("funQuotes", "金句", "active", kind="fun"),
    Play("funSoup", "海龟汤", "active", kind="fun"),
)
BY_KEY = {play.key: play for play in PLAYS}


def group_scope(umo: str) -> str:
    return f"group:{umo}"


class Features:
    def __init__(self, store: "Store") -> None:
        self.store = store

    def _own(self, umo: str | None, key: str) -> bool:
        play = BY_KEY[key]
        if play.status != "active":
            return False
        with self.store.read() as c:
            if umo is not None:
                value = self.store.get_setting(c, group_scope(umo), f"play.{key}")
                if value is not None:
                    return bool(value)
            return bool(self.store.get_setting(c, "global", f"play.{key}", True))

    def enabled(self, umo: str | None, key: str) -> bool:
        """True when the play and every play it depends on are open for this group."""
        play = BY_KEY[key]
        return self._own(umo, key) and all(self.enabled(umo, dep) for dep in play.depends)

    def set(self, scope: str, key: str, value: bool | None) -> None:
        """scope is 'global' or group_scope(umo); None clears a group override."""
        if key not in BY_KEY or BY_KEY[key].status != "active":
            raise ValueError(f"play {key} cannot be switched")
        with self.store.tx() as c:
            if value is None:
                c.execute("DELETE FROM settings WHERE scope=? AND key=?", (scope, f"play.{key}"))
            else:
                self.store.set_setting(c, scope, f"play.{key}", bool(value))

    def table(self, umo: str | None = None) -> list[dict]:
        rows = []
        for play in PLAYS:
            with self.store.read() as c:
                override = None if umo is None else self.store.get_setting(c, group_scope(umo), f"play.{play.key}")
                default = bool(self.store.get_setting(c, "global", f"play.{play.key}", True))
            rows.append({"key": play.key, "label": play.label, "status": play.status, "depends": list(play.depends), "kind": play.kind,
                         "global": default if play.status == "active" else False, "override": override,
                         "effective": self.enabled(umo, play.key)})
        return rows
