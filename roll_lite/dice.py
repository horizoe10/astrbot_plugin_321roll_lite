"""The platform's fair dice.  Only the platform rolls; engines and models never do."""
from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass


def d20() -> int:
    return secrets.randbelow(20) + 1


def modifier(score: int, baseline: int = 10, divisor: int = 2) -> int:
    """World-template modifier: floor((score - baseline) / divisor)."""
    return (score - baseline) // divisor


@dataclass(frozen=True, slots=True)
class CheckRoll:
    face: int
    modifier: int
    total: int
    dc: int
    success: bool
    critical: bool
    fumble: bool

    def to_dict(self) -> dict:
        return asdict(self)


def roll_check(mod: int, dc: int, face: int | None = None) -> CheckRoll:
    """d20 + modifier against dc; a natural 20 always succeeds and a natural 1 always fails."""
    face = d20() if face is None else face
    total = face + mod
    success = face == 20 or (face != 1 and total >= dc)
    return CheckRoll(face, mod, total, dc, success, face == 20, face == 1)
