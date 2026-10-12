"""Pure validation and settings of a world's optional 'pacing' block; usable by offline pack tools.

A round is every seated player acting once.  The block says how many rounds a scene and an act
run before the table is nudged, how long the whole story is meant to be and whether the table
may propose winding down.  Every world is paced: a world without the block uses the defaults.

    "pacing": {"sceneRounds": 4, "actRounds": 8, "acts": {"3": 10}, "graceRounds": 2,
               "targetRounds": 32, "hardRounds": 48, "endingPrompt": true}

0 turns a level off (sceneRounds, actRounds, targetRounds, hardRounds).  targetRounds left out is
the sum of the acts' rounds (a Core edition counts three acts); hardRounds left out is 1.5 times
the target, and at least two rounds past it.
"""
from __future__ import annotations

import math
from typing import Any

KEYS = ("sceneRounds", "actRounds", "acts", "graceRounds", "targetRounds", "hardRounds", "endingPrompt")
SCENE_ROUNDS, ACT_ROUNDS, GRACE_ROUNDS = 4, 8, 2
CORE_ACTS = 3          # a Core edition writes its first act only; its length is reckoned as three
PRESETS = {"短": 0.75, "标准": 1.0, "长": 1.5}
LIMITS = {"sceneRounds": (0, 50), "actRounds": (0, 100), "graceRounds": (1, 10), "targetRounds": (0, 1000),
          "hardRounds": (0, 1000)}


def validate(value: Any) -> None:
    """Raise ValueError when a world's optional 'pacing' block is malformed."""
    def require(ok: Any, message: str) -> None:
        if not ok:
            raise ValueError("pacing：" + message)

    require(isinstance(value, dict) and set(value) <= set(KEYS), "只能包含 " + "、".join(KEYS))
    for key, (low, high) in LIMITS.items():
        if key in value:
            require(type(value[key]) is int and low <= value[key] <= high, f"{key} 是 {low}–{high} 的整数")
    require(type(value.get("endingPrompt", True)) is bool, "endingPrompt 是 true 或 false")
    acts = value.get("acts", {})
    require(isinstance(acts, dict) and len(acts) <= 50
            and all(isinstance(k, str) and k.isdigit() and 1 <= int(k) <= 50 and type(v) is int and 1 <= v <= 100
                    for k, v in acts.items()), "acts 是“幕号 → 1–100 轮”")
    target, hard = value.get("targetRounds"), value.get("hardRounds")
    require(not (target and hard) or hard >= target, "hardRounds 不能小于 targetRounds")


def _scaled(value: int, factor: float) -> int:
    return value if not value or factor == 1 else max(1, math.ceil(value * factor))


def settings(block: dict[str, Any] | None, acts_total: int, core: bool, own: dict[str, Any] | None = None) -> dict[str, Any]:
    """The table's pacing: the world's block (or the defaults), then the host's preset, numbers or 'off'.

    Returns scene, act (default per act), acts (act number → rounds), grace, target, hard, ending and
    preset; act_rounds(settings, n) reads one act.
    """
    p, own = block or {}, own or {}
    factor = PRESETS.get(own.get("preset") or "标准", 1.0)
    scene = _scaled(p.get("sceneRounds", SCENE_ROUNDS), factor)
    act = _scaled(p.get("actRounds", ACT_ROUNDS), factor)
    acts = {k: _scaled(v, factor) for k, v in (p.get("acts") or {}).items()}
    count = CORE_ACTS if core or not acts_total else acts_total
    if p.get("targetRounds") is None:
        target = sum(acts.get(str(n), act) for n in range(1, count + 1)) if act else 0
    else:
        target = _scaled(p["targetRounds"], factor)
    hard = (target + max(2, target // 2) if target else 0) if p.get("hardRounds") is None else _scaled(p["hardRounds"], factor)
    result = {"scene": scene, "act": act, "acts": acts, "grace": p.get("graceRounds", GRACE_ROUNDS), "target": target,
              "hard": hard, "ending": p.get("endingPrompt", True), "preset": own.get("preset") or "标准",
              "off": bool(own.get("off")), "own": bool(own)}
    for key in ("scene", "act", "target", "hard"):
        if own.get(key) is not None:
            result[key] = own[key]
            if key == "act":
                result["acts"] = {}
    if result["hard"] and result["target"] and result["hard"] < result["target"]:
        result["hard"] = result["target"]
    if result["off"]:
        result.update(scene=0, act=0, acts={}, target=0, hard=0)
    return result


def act_rounds(conf: dict[str, Any], number: int) -> int:
    return conf["acts"].get(str(number), conf["act"])
