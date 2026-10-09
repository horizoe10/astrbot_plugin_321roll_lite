"""Today's roll: one d20 per player per day, with two 宜 and two 忌 drawn alongside.

Follows 321Roll's daily roll: the day is the UTC+8 calendar date, the first roll
of the day is stored and every later ask returns it unchanged.  It grants
nothing and never touches a check.  A player is the same person in every group
(platform + user id); the group board lists who asked in this group today.
"""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from . import messages, shared
from .commands import Caller, Reply, UserError
from .fun import luck
from .storage import dumps, loads, now

if TYPE_CHECKING:
    from .app import LiteApp

FORTUNES = ((20, "天光", "dawn"), (14, "顺风", "fair"), (8, "平潮", "calm"), (2, "阴云", "cloud"), (1, "逆风", "gale"))
CRIT = {20: "天光乍破，今日所掷，皆有回响。", 1: "逆风亦是风，好故事常从这里写起。"}
BOARD_WORDS = ("全群", "榜", "群榜", "本群")
KEEP_DAYS = 7
WEEKDAYS = "一二三四五六日"

# (词条, 短注, 话题).  Same-topic 宜 and 忌 never appear together.  Table manners only: no commands,
# no system terms, nothing about real-life luck.
YI = (
    ("探幽", "未启之门，不妨一推", "explore"), ("拾遗", "旁人略过之处，留心记下", "clue"),
    ("推演", "大胆立论，静待验证", "theory"), ("斡旋", "与人方便，留一步余地", "parley"),
    ("赴险", "难行之路，今日可走", "risk"), ("结伴", "并肩而行，胜于独往", "company"),
    ("问卜", "悬而未决，付与骰子", "dice"), ("立誓", "出口之言，故事自会记得", "vow"),
    ("守望", "他人当值，替他留灯", "watch"), ("题名", "为这一幕起个名字", "name"),
    ("启程", "行囊已备，即可出发", "depart"), ("夜读", "旧卷深处，或有遗文", "lore"),
    ("问路", "向生人打听，多半有获", "ask"), ("设伏", "先布一子，后发制人", "plan"),
    ("疗伤", "伤处先裹，再图后计", "heal"), ("对质", "前言后语，当面一核", "testimony"),
    ("收束", "散落的线头，今日可收", "wrap"), ("换位", "换个立场，再看一遍", "view"),
    ("留白", "话说七分，余韵自生", "press"), ("应和", "接住同伴抛来的话头", "support"),
    ("慎言", "一字一句，皆可为凭", "speech"), ("筹谋", "走一步前，先看三步", "haste"),
    ("登门", "久未拜访之处，宜走一趟", "visit"), ("寻踪", "足迹未冷，循之可得", "track"),
    ("护持", "挡在同伴身前一次", "protect"), ("示好", "一句软话，胜过十句硬话", "kind"),
    ("守约", "前日之诺，今日兑现", "promise"), ("回望", "前幕旧事，或藏伏笔", "recall"),
    ("静听", "先听人说完，再开口", "listen"), ("举杯", "胜负之外，先敬同席", "cheer"),
    ("涉水", "浅处可渡，莫要回头", "cross"), ("小憩", "暂歇片刻，看看这方天地", "rest"),
    ("交心", "与同伴说一句真话", "truth"), ("藏锋", "底牌未亮，不急一时", "card"),
    ("解惑", "为后来者讲讲前情", "newbie"), ("守静", "风雨欲来，按兵不动", "calm"),
    ("远行", "地图边缘，今日可去", "far"), ("求援", "力有不逮，开口不难", "help"),
    ("落笔", "把这一幕好好记下", "record"), ("让贤", "今日的高光，让给同伴", "spotlight"),
)
JI = (
    ("独行", "无灯长廊，莫要孤身", "company"), ("强辩", "骰子已落，不与天争", "dice"),
    ("越俎", "同伴的抉择，留给同伴", "choice"), ("窥卷", "已读的设定，按下不表", "spoiler"),
    ("迟疑", "轮到你时，莫让众人久候", "turn"), ("吝药", "最后一剂，当用则用", "heal"),
    ("逼问", "话问七分，余下留白", "press"), ("悔棋", "落子既定，不复更改", "regret"),
    ("轻诺", "许不下的约，不必许", "promise"), ("喧宾", "主角今日，或许不是你", "spotlight"),
    ("冒进", "未探之地，先缓一步", "haste"), ("抢白", "他人话未尽，莫要接口", "listen"),
    ("夜游", "子时之后，少出门户", "night"), ("贪功", "功劳一半，记在同伴", "glory"),
    ("轻信", "笑脸之下，未必真心", "trust"), ("失言", "秘密一出口，便收不回", "speech"),
    ("恋战", "胜负已分，见好就收", "fight"), ("弃卷", "线索虽乱，莫要轻抛", "clue"),
    ("怠慢", "主人家的茶，喝一口再走", "courtesy"), ("绝路", "莫把对方逼到无路可退", "parley"),
    ("夸口", "话说太满，骰子会听见", "boast"), ("犯禁", "此地的规矩，先问清楚", "taboo"),
    ("离席", "故事正酣，莫要走开", "leave"), ("翻旧", "已了之事，不必重提", "recall"),
    ("亮底", "底牌未到时候，先压着", "card"), ("迁怒", "骰子无情，莫怪同伴", "blame"),
    ("误时", "约好的时辰，莫要迟到", "late"), ("妄断", "证据未齐，莫下定论", "theory"),
    ("轻敌", "看似弱小者，最难缠", "foe"), ("絮叨", "一言能尽，不必十句", "verbose"),
    ("贪多", "一次只办一件事", "greed"), ("硬闯", "锁着的门，先找钥匙", "risk"),
    ("忘本", "莫忘最初为何出发", "goal"), ("冷场", "同伴开了口，记得回应", "support"),
    ("晚归", "天黑之前，记得回营", "dusk"), ("争先", "先后有序，各守其时", "order"),
    ("讳疾", "伤了就说，莫要硬撑", "hurt"), ("欺生", "新来的同伴，多照应些", "newbie"),
    ("慌乱", "越是急处，越要从容", "flurry"), ("散伙", "再难的局，莫轻言散", "quit"),
)

# Replaced in tests.
_rng: random.Random = random.SystemRandom()


def _clock() -> datetime:
    return datetime.now(UTC)


def day_key(moment: datetime | None = None) -> str:
    """The calendar date at UTC+8, like 321Roll's settlement day."""
    return ((moment or _clock()) + timedelta(hours=8)).date().isoformat()


def day_label(day: str) -> str:
    date = datetime.fromisoformat(day)
    return f"{date.month} 月 {date.day} 日 · 周{WEEKDAYS[date.weekday()]}"


def fortune(face: int) -> tuple[str, str]:
    return next((label, key) for low, label, key in FORTUNES if face >= low)


def draw(rng: random.Random) -> dict[str, Any]:
    face = rng.randint(1, 20)
    yi = rng.sample(YI, 2)
    topics = {topic for _, _, topic in yi}
    ji = rng.sample([entry for entry in JI if entry[2] not in topics], 2)
    return {"face": face, "yi": [[t, g] for t, g, _ in yi], "ji": [[t, g] for t, g, _ in ji]}


def roll(app: "LiteApp", caller: Caller) -> tuple[dict[str, Any], bool]:
    """Today's roll for the caller, drawing it on the first ask; also puts the caller on this group's board."""
    day = day_key()
    stamp = now()
    with app.store.tx() as c:
        row = c.execute("SELECT * FROM daily_rolls WHERE platform=? AND user_id=? AND day=?",
                        (caller.platform_id, caller.user_id, day)).fetchone()
        created = row is None
        if created:
            drawn = draw(_rng)
            c.execute("INSERT INTO daily_rolls(platform,user_id,day,face,signs_json,rolled_at) VALUES(?,?,?,?,?,?)",
                      (caller.platform_id, caller.user_id, day, drawn["face"], dumps({"yi": drawn["yi"], "ji": drawn["ji"]}), stamp))
            cutoff = (datetime.fromisoformat(day) - timedelta(days=KEEP_DAYS)).date().isoformat()
            c.execute("DELETE FROM daily_rolls WHERE day<?", (cutoff,))
            c.execute("DELETE FROM daily_board WHERE day<?", (cutoff,))
            result = {"face": drawn["face"], "yi": drawn["yi"], "ji": drawn["ji"], "rolled_at": stamp}
        else:
            signs = loads(row["signs_json"], {})
            result = {"face": int(row["face"]), "yi": signs.get("yi", []), "ji": signs.get("ji", []), "rolled_at": row["rolled_at"]}
        if caller.in_group:
            shown = c.execute("SELECT 1 FROM daily_board WHERE umo=? AND day=? AND platform=? AND user_id=?",
                              (caller.umo, day, caller.platform_id, caller.user_id)).fetchone()
            if shown is None:          # the day's face counts once in each group it is shown in
                luck.record(c, caller.umo, caller.user_id, caller.user_name, "daily", [result["face"]])
            c.execute("INSERT INTO daily_board(umo,day,platform,user_id,user_name,seen_at) VALUES(?,?,?,?,?,?) "
                      "ON CONFLICT(umo,day,platform,user_id) DO UPDATE SET user_name=excluded.user_name",
                      (caller.umo, day, caller.platform_id, caller.user_id, caller.user_name, stamp))
    return {**result, "day": day}, created


def board(app: "LiteApp", umo: str, day: str | None = None) -> list[dict[str, Any]]:
    day = day or day_key()
    with app.store.read() as c:
        rows = c.execute("SELECT b.user_name, r.face, r.rolled_at FROM daily_board b JOIN daily_rolls r "
                         "ON r.platform=b.platform AND r.user_id=b.user_id AND r.day=b.day "
                         "WHERE b.umo=? AND b.day=? ORDER BY r.face DESC, r.rolled_at", (umo, day)).fetchall()
    return [{"name": r["user_name"], "face": int(r["face"]), "fortune": fortune(int(r["face"]))[0]} for r in rows]


async def roll_command(app: "LiteApp", caller: Caller, args: str) -> Reply:
    shared.require_play(app, caller, "funDaily")
    if args.strip() in BOARD_WORDS:
        return await board_command(app, caller, "")
    result, created = roll(app, caller)
    label, tier = fortune(result["face"])
    return Reply().say(messages.daily_roll(caller.user_name, day_label(result["day"]), result["face"], label, tier,
                                           result["yi"], result["ji"], again=not created, crit=CRIT.get(result["face"], "")))


async def board_command(app: "LiteApp", caller: Caller, args: str) -> Reply:
    shared.require_play(app, caller, "funDaily")
    if not caller.in_group:
        raise UserError("本群的今日一掷只能在群里查看。")
    day = day_key()
    return Reply().say(messages.daily_board(day_label(day), board(app, caller.umo, day)))


def install(app: "LiteApp") -> None:
    r = app.router
    r.register(("一掷", "今日一掷", "每日一掷"), roll_command, summary="掷出今天的 d20 和宜忌，每天一次，不影响检定",
               usage="/团 一掷", topic="日常", group_only=False)
    r.register(("一掷 全群", "一掷 榜"), board_command, summary="看本群今天谁掷了多少", usage="/团 一掷 全群", topic="日常",
               group_only=False)

