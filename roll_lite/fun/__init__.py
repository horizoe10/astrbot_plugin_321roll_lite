"""Group pastimes outside the story: free dice and duels, luck stats, battle reports and cheers, saved lines,
scheduling, story relays and turtle soup.

Each has its own switch on the WebUI plays page (features kind 'fun').  Today's roll lives in roll_lite/daily.py.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..app import LiteApp


def install(app: "LiteApp") -> None:
    from . import dice, luck, quotes, relay, report, schedule, soup
    dice.install(app)
    luck.install(app)
    report.install(app)
    quotes.install(app)
    schedule.install(app)
    relay.install(app)
    soup.install(app)

