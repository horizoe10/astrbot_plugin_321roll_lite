"""Image cards for the status, narration and choices segments, the character sheet, play receipts and room status.

card_html() lays a Msg out as one self-contained HTML page in the 321Roll
white-gold or black-gold style; delivery hands it to AstrBot's html_render.
Every size is in rem tied to the viewport width (html font-size 2.5vw), so the
card keeps its proportions whatever width the render service uses.  Text from
players and the model is always escaped; only the inline code and bold markers
of render.inline() turn into markup.
"""
from __future__ import annotations

import base64
import html
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .messages import act_label, sentence
from .render import _INLINE, BT, OUTCOMES, Block, Msg
from .worlds.catalog import COVER_TONES

THEMES = ("light", "dark")
TEMPLATE = "{{ html | safe }}"
# AstrBot's default is JPEG quality 40, too soft for small CJK text on a phone.
RENDER_OPTIONS = {"type": "jpeg", "quality": 92, "full_page": True}
# Covers are a colour field plus one large character; preset worlds get a hand-picked pair.
COVERS = {"seventh-mystery": ("七", "ink"), "wildfire-hunt": ("狩", "ember"), "neon-pawnshop": ("当", "neon"),
          "nameless-sword-tomb": ("剑", "jade"), "final-curtain": ("戏", "wine"), "greycrown-prequel": ("冠", "slate")}
SEGMENT_LABELS = {"status": "个人状态", "narration": "故事正文", "choices": "行动选项", "sheet": "角色卡",
                  "receipt": "玩法回执", "room": "团桌状态", "moment": "大场面", "daily": "日常"}
_ROOT = Path(__file__).resolve().parent.parent


def cover(world_id: str, title: str, presentation: dict[str, Any] | None = None) -> dict[str, str]:
    chosen = (presentation or {}).get("cover")
    if chosen:
        return dict(chosen)
    if world_id in COVERS:
        mark, tone = COVERS[world_id]
    else:
        name = title.split(" · ")[0].removeprefix("第")
        mark = next((ch for ch in name if not ch.isspace()), "团")
        tone = COVER_TONES[sum(map(ord, world_id)) % len(COVER_TONES)]
    return {"mark": mark, "tone": tone}


@lru_cache(maxsize=1)
def _seal() -> str:
    try:
        return "data:image/png;base64," + base64.b64encode((_ROOT / "pages/admin/assets/solid.png").read_bytes()).decode("ascii")
    except OSError:
        return ""


def e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def rich(text: Any) -> str:
    """Escaped text where `code` becomes a key cap and **bold** stays bold."""
    out = []
    for i, part in enumerate(_INLINE.split(str(text))):
        if i % 2 == 0:
            out.append(e(part))
        elif part.startswith(BT):
            out.append(f'<span class="kbd">{e(part[1:-1])}</span>' if part[1:-1] else "")
        else:
            out.append(f"<b>{e(part[2:-2])}</b>")
    return "".join(out)


ICONS = {
    "skill": '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l2.2 7.8L22 12l-7.8 2.2L12 22l-2.2-7.8L2 12l7.8-2.2z"/></svg>',
    "item": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M5 8h14l-1 12H6z"/><path d="M9 8V6a3 3 0 0 1 6 0v2"/></svg>',
    "quill": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 4c-6 0-11 4-12 11l-2 5"/><path d="M8 15c4 0 8-2 10-6"/><path d="M11 11h5"/></svg>',
    "moon": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/></svg>',
    "vote": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="m8.5 12 2.5 2.5 4.5-5"/></svg>',
    "heart": '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 20.5s-7.5-4.6-9.2-9.4C1.6 7.6 3.9 4.5 7.2 4.5c2 0 3.6 1.1 4.8 2.8 1.2-1.7 2.8-2.8 4.8-2.8 3.3 0 5.6 3.1 4.4 6.6-1.7 4.8-9.2 9.4-9.2 9.4z"/></svg>',
    "dice": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M12 2.8 20.2 7.5v9L12 21.2 3.8 16.5v-9z"/><path d="M3.8 7.5 12 12l8.2-4.5M12 12v9.2"/></svg>',
}


# ---------------------------------------------------------------- pieces
def _flat(msg: Msg) -> list[Block]:
    return [block for section in msg.sections for block in section]


def _chip(label: str, note: str = "", icon: str = "skill", off: bool = False) -> str:
    return (f'<span class="chip{" off" if off else ""}">{ICONS[icon]}{e(label)}'
            + (f"<em>{e(note)}</em>" if note else "") + "</span>")


def _banner(art: dict[str, Any], title: str, sub: str, slim: bool = False) -> str:
    image = art.get("image") or ""
    inner = (f'<img src="{e(image)}" alt="" /><div class="shade"></div>' if image
             else f'<div class="mark">{e(art.get("mark") or "团")}</div>')
    tone = "" if image else f' cover tone-{e(art.get("tone") or "wine")}'
    return (f'<header class="banner{tone}{" slim" if slim else ""}">{inner}'
            + (f'<div class="tag">{e(art["tag"])}</div>' if art.get("tag") else "")
            + f"<h1>{e(title)}</h1>" + (f'<div class="sub">{e(sub)}</div>' if sub else "") + "</header>")


def _foot(right: str) -> str:
    seal = _seal()
    return ('<footer class="foot"><div class="seal">' + (f'<img src="{seal}" alt="" />' if seal else "<i></i>")
            + f"321Roll Lite</div><div>{e(right)}</div></footer>")


def _generic(block: Block) -> str:
    d, k = block.data, block.kind
    if k in ("text", "caption"):
        return f'<div class="line">{rich(d["text"])}</div>'
    if k in ("heading", "banner", "title"):
        return f'<h3 class="subhead">{e(d["text"])}</h3>'
    if k == "para":
        return f'<p class="plain">{e(d["text"])}</p>'
    if k == "quote":
        return f'<blockquote>{e(d["text"])}</blockquote>'
    if k == "field":
        return f'<div class="line"><span class="lab">{e(d["label"])}</span>{rich(d["value"])}</div>'
    if k == "list":
        return '<ul class="items">' + "".join(f"<li>{rich(i)}</li>" for i in d["items"]) + "</ul>"
    if k == "hint":
        return _hint(d)
    if k == "draw":
        return f'<div class="line"><span class="kbd">d20 {e(d["face"])}</span> <b>{e(d["label"])}</b></div>'
    if k == "rule":
        return '<hr />'
    return ""


def _hint(d: dict[str, Any]) -> str:
    if not d.get("cmds"):
        return f'<div class="hint">{rich(d["text"])}</div>'
    cmds = "".join(f'<span class="cmd"><span class="ck">{e(label)}</span><span class="kbd">{e(command)}</span></span>'
                   for label, command in d["cmds"])
    note = f'<div class="note">{rich(d["note"])}</div>' if d.get("note") else ""
    return f'<div class="hint">{note}<div class="cmds">{cmds}</div></div>'


def _ratio(current: int, maximum: int) -> float:
    return max(0.0, min(1.0, current / maximum)) if maximum > 0 else 0.0


def _signed(value: int) -> str:
    return f"{value:+d}".replace("-", "−")


RESOURCE_TONES = ("hp", "mp", "sp", "xp")      # by the resource's place in the world: red, blue, green, violet


def _em(text: Any) -> float:
    """Rough rendered width in em: CJK and full-width characters 1em, spaces .3em, digits and Latin .6em."""
    return sum(1.0 if ord(c) >= 0x2E80 else 0.3 if c == " " else 0.6 for c in str(text))


def _columns(labels: list[Any], values: list[float]) -> str:
    """Shared label and number widths for a group of bars, so every bar in the group starts and ends at the same place
    (the label carries a .8rem colour dot in front)."""
    return (f"--gk:calc({max([_em(x) for x in labels] or [2]):.2f}em + .8rem);"
            f"--gv:{max(values or [2]) + .2:.2f}em")


def _gauge(current: int, maximum: int, delta: int = 0, index: int = 0) -> str:
    """A resource bar in its own colour; this turn's loss stays as a hatched stretch, a gain is lit up."""
    now, before = _ratio(current, maximum) * 100, _ratio(current - delta, maximum) * 100
    mark = ""
    if delta < 0 and before > now:
        mark = f'<b class="lost" style="left:{now:.0f}%;width:{before - now:.0f}%"></b>'
    elif delta > 0 and now > before:
        mark = f'<b class="gain" style="left:{before:.0f}%;width:{now - before:.0f}%"></b>'
    return f'<div class="res rc-{RESOURCE_TONES[index % len(RESOURCE_TONES)]}"><i style="width:{now:.0f}%"></i>{mark}</div>'


def _vitals(meters: list[dict[str, Any]]) -> str:
    rows = []
    widths = []
    for index, m in enumerate(meters):
        delta = m.get("delta") or 0
        tail = f'<span class="delta {"up" if delta > 0 else "down"}">{_signed(delta)}</span>' if delta else ""
        # the change badge is set smaller (.9) with padding and a gap of about 1.45em in all
        widths.append(_em(f'{m["current"]}/{m["maximum"]}') + (0.54 * len(_signed(delta)) + 1.45 if delta else 0))
        tone = RESOURCE_TONES[index % len(RESOURCE_TONES)]
        rows.append(f'<div class="vital rc-{tone}{" low" if _ratio(m["current"], m["maximum"]) <= 0.4 else ""}">'
                    f'<span class="vk">{e(m["label"])}</span>{_gauge(m["current"], m["maximum"], delta, index)}'
                    f'<span class="vv num">{tail}{m["current"]}<small>/{m["maximum"]}</small></span></div>')
    return f'<div class="vitals" style="{_columns([m["label"] for m in meters], widths)}">' + "".join(rows) + "</div>"


def _margin(d: dict[str, Any]) -> str:
    """Where the total landed among all possible totals, against the difficulty: a narrow pass reads differently from a safe one."""
    face, mod, total, dc = int(d["face"]), int(d["modifier"]), int(d["total"]), int(d["dc"])
    lo, hi = 1 + mod, 20 + mod
    pct = lambda v: max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))
    gap = total - dc
    if face == 20:
        label, tone = "天然 20，必定成功", "ok"
    elif face == 1:
        label, tone = "天然 1，必定失败", "bad"
    elif gap >= 0:
        label, tone = ("恰好达到 · 险过" if gap == 0 else f"高出 {gap} 点 · " + ("稳过" if gap >= 5 else "险过")), "ok"
    else:
        label, tone = f"差 {-gap} 点" + (" · 只差一点" if gap >= -2 else ""), "bad"
    return (f'<div class="margin {tone}"><div class="ruler"><span class="zone" style="left:{pct(dc):.0f}%"></span>'
            f'<i class="dcl" style="left:{pct(dc):.0f}%"></i><b class="pt" style="left:{pct(total):.0f}%"></b></div>'
            f'<span class="ml">{e(label)}</span></div>')


def _throw(d: dict[str, Any]) -> str:
    good = d["outcome"] in ("success", "critical")
    passed = d["total"] >= d["dc"]
    terms = (f'<div class="term"><span class="tk">骰面</span><span class="tv num">{d["face"]}</span></div><span class="op">{"+" if d["modifier"] >= 0 else "−"}</span>'
             f'<div class="term"><span class="tk">修正</span><span class="tv num">{abs(d["modifier"])}</span></div><span class="op">=</span>'
             f'<div class="term total"><span class="tk">合计</span><span class="tv num">{d["total"]}</span></div><span class="op">{"≥" if passed else "&lt;"}</span>'
             f'<div class="term vs"><span class="tk">难度</span><span class="tv num">{d["dc"]}</span></div>')
    return (f'<div class="throw"><div class="orbit"><div class="glow"></div><div class="disc"></div><div class="shadow"></div>'
            f'<div class="die"><span class="num">{d["face"]}</span></div></div>'
            f'<div class="verdict{"" if good else " bad"}"><div class="k">{e(d["attribute"])}检定 · {e(d["difficulty"])}</div>'
            f'<div class="h">{e(OUTCOMES.get(d["outcome"], d["outcome"]))}</div><div class="terms">{terms}</div>{_margin(d)}</div></div>')


def _split_entry(text: str) -> tuple[str, str]:
    name, _, note = str(text).partition(" ")
    return name, note.strip()


def _medal(name: str, role: str, line: str = "", image: str = "") -> str:
    """Gold-ringed avatar with name, role tag and an optional line; resources are drawn by _vitals below it."""
    face = f'<img src="{e(image)}" alt="" />' if str(image).startswith("data:image/") else e(name[:1])
    return (f'<div class="me"><div class="medal"><div class="halo"></div><div class="avatar">{face}</div></div><div>'
            f'<div class="me-name">{e(name)}' + (f"<small>{e(role)}</small>" if role else "") + "</div>"
            + (f'<div class="me-line">{e(line)}</div>' if line else "") + "</div></div>")


def _meters(rows: list[Any]) -> list[dict[str, Any]]:
    return [{"label": n, "current": cur, "maximum": mx} for n, cur, mx in rows]


def _sect(title: str, inner: str) -> str:
    return f'<section class="sect"><h4>{e(title)}</h4>{inner}</section>'


_RECORD = re.compile(r"^\*\*#(\d+)\*\* (.+?)「(.*)」　([^　]*)(?:　(.*))?$")
_KIND_GROUPS = {"线索": "inv", "假设": "inv", "证词": "inv", "公开设定": "inv", "交涉": "soc", "关系": "soc", "同伴目标": "soc",
                "对抗": "war", "险关": "war", "计划": "plan", "项目": "plan", "期限": "plan", "日历": "plan",
                "神谕": "fate", "机运": "fate", "转变": "fate", "结局分支": "fate", "结局": "fate"}


def _record(line: str) -> str:
    match = _RECORD.match(str(line))
    if not match:
        return f'<div class="rec"><span></span><div class="rt">{rich(line)}</div><span></span></div>'
    seq, kind, title, state, visual = match.groups()
    return (f'<div class="rec"><span class="no num">#{e(seq)}</span><div><span class="rk g-{_KIND_GROUPS.get(kind, "inv")}">{e(kind)}</span>'
            f'<div class="rt">{e(title)}</div>' + (f'<div class="rv">{glyphs(rich(visual))}</div>' if visual else "")
            + f'</div><span class="rs">{e(state)}</span></div>')

_GLYPH_ON = frozenset("■●▰◆")
_GLYPH_RUN = re.compile(r'<span class="kbd">([■□●○▰▱◆◇]+)</span>')


def glyphs(markup: str) -> str:
    """Draw the text meters (■□, ●○, ▰▱) that rich() left as key caps as small segmented bars."""
    return _GLYPH_RUN.sub(lambda m: '<span class="glyph">' + "".join(
        f'<i class="{"on" if ch in _GLYPH_ON else ""}"></i>' for ch in m.group(1)) + "</span>", markup)


def _avatar(name: str) -> str:
    return f'<span class="ava">{e(str(name)[:1] or "?")}</span>'


def _avatars(names: list[str], limit: int = 8) -> str:
    more = len(names) - limit
    return ('<span class="avs">' + "".join(f'<span class="ava sm" title="{e(n)}">{e(str(n)[:1])}</span>' for n in names[:limit])
            + (f'<span class="ava sm more">+{more}</span>' if more > 0 else "") + "</span>")


def _contribs(values: dict[str, int]) -> str:
    return '<div class="cts">' + "".join(f'<span class="ct {"up" if v > 0 else "down"}">{e(k)} <b class="num">{_signed(v)}</b></span>'
                                         for k, v in values.items() if v) + "</div>"


_OUTCOMES = (("critical", "大成功", "crit"), ("success", "成功", "ok"), ("failure", "失败", "fail"), ("fumble", "大失败", "fum"))


def _outcomes(dist: dict[str, int]) -> str:
    """How the checks went: one bar split by outcome, with a legend of counts and shares."""
    total = sum(int(dist.get(k) or 0) for k, _, _ in _OUTCOMES)
    if not total:
        return ""
    segs = "".join(f'<i class="{cls}" style="flex:{dist[k]}"></i>' for k, _, cls in _OUTCOMES if dist.get(k))
    legend = "".join(f'<span class="{cls}"><i></i>{label}<b class="num">{int(dist.get(k) or 0)}</b>'
                     f'<em class="num">{round(int(dist.get(k) or 0) / total * 100)}%</em></span>' for k, label, cls in _OUTCOMES)
    return f'<div class="outs"><div class="obar">{segs}</div><div class="olegend">{legend}</div></div>'


def _stat_cells(cells: tuple[tuple[str, Any, str], ...]) -> str:
    return '<div class="rstats">' + "".join(f'<div class="rs-cell{c}"><b class="num">{e(v)}</b><span>{k}</span></div>' for k, v, c in cells) + "</div>"


def _scale(standing: int, labels: bool = False) -> str:
    """Seven cells from 敌对 to 盟友: the run from neutral to the current cell is filled, the current one ringed."""
    from .adjust import STANDING
    standing = max(-3, min(3, int(standing)))
    cells = []
    for i in range(7):
        pos = i - 3
        filled = (0 < pos <= standing) or (standing <= pos < 0)
        cells.append(f'<i class="{"pos" if pos > 0 else "neg" if pos < 0 else "mid"}{" on" if filled else ""}'
                     f'{" now" if pos == standing else ""}"></i>')
    row = f'<div class="scale">{"".join(cells)}</div>'
    if labels:
        row += '<div class="scale-k">' + "".join(f'<span class="{"now" if i - 3 == standing else ""}">{e(t)}</span>'
                                                 for i, t in enumerate(STANDING)) + "</div>"
    return row


LEAD_MIN = 56          # shorter first paragraphs get no drop cap: one line beside a two-line initial looks empty


def _paras(text: str, cls: str = "lead") -> str:
    parts = [p.strip() for p in re.split(r"\n\s*\n", str(text)) if p.strip()]
    return '<div class="body">' + "".join(f'<p class="{cls if i == 0 and len(p) >= LEAD_MIN else ""}">{e(p)}</p>'
                                          for i, p in enumerate(parts)) + "</div>"


def _top(art: dict[str, Any] | None, eyebrow: str, title: str, sub: str = "") -> str:
    if art:
        return _banner(art, title, sub)
    return (f'<header class="head"><div class="eyebrow-l">{e(eyebrow)}</div><h2>{e(title)}</h2>'
            + (f'<div class="head-sub">{e(sub)}</div>' if sub else "") + "</header>")


def _cmds(*pairs: tuple[str, str]) -> str:
    return _hint({"text": "", "note": "", "cmds": list(pairs)})


def _moment(msg: Msg, art: dict[str, Any] | None) -> tuple[str, str]:
    d = msg.data or {}
    kind = d.get("kind")
    if kind == "open":
        cap = int(d.get("cap") or 0)
        return (_top(art, "开团招募", d["title"], d.get("sub", "")) + _paras(d.get("hook", ""))
                + (f'<div class="box"><h4>核心版</h4><div class="goal">{e(d["note"].split("：", 1)[-1])}</div></div>' if d.get("note") else "")
                + f'<div class="seats"><div><span class="lab">席位</span><b class="num">0/{cap}</b>'
                f'<span class="sm">最少 {e(d.get("min"))} 人可开演</span></div><div class="dots">{"<i></i>" * cap}</div></div>'
                + f'<div class="uses"><span class="lab">主持</span>{_chip(d.get("host", ""), icon="quill")}</div>'
                + _cmds(("入座", "/团 加入"), ("建卡", "/团 选职业 1 名字"), ("读设定", "/团 世界观"))), "开团招募"
    if kind == "act":
        number, total = int(d.get("number") or 1), int(d.get("total") or 0)
        heading = act_label(number) + (f" · {d['act_title']}" if d.get("act_title") else "")
        parts = [_top(art, d["title"], heading)]
        if total:
            bar = "".join(f'<i class="{"on" if i < number else ""}{" now" if i == number - 1 else ""}"></i>' for i in range(total))
            parts.append(f'<div class="acts"><div class="al"><span class="lab">幕次</span></div><div class="segs">{bar}</div>'
                         f'<span class="an num">{number}/{total}</span></div>')
        if d.get("lead"):
            parts.append(_paras(d["lead"]))
        recap = d.get("recap")
        if recap:
            cells = _stat_cells((("次行动", recap.get("actions", 0), ""), ("次检定", recap.get("checks", 0), ""),
                                 ("大成功", recap.get("crits", 0), " up"), ("大失败", recap.get("fumbles", 0), " down")))
            best = f'<div class="uses act-best"><span class="lab">本幕最佳</span>{_chip(d["best"], icon="skill")}</div>' if d.get("best") else ""
            parts.append(f'<section class="sect recap"><h4>上一幕回顾</h4>{cells}{best}</section>')
        elif d.get("best"):
            parts.append(f'<div class="uses act-best"><span class="lab">上一幕最佳</span>{_chip(d["best"], icon="skill")}</div>')
        return "".join(parts), act_label(number)
    if kind == "report":
        return _report_card(d, art)
    if kind == "vote":
        counts = [(str(label), int(n)) for label, n in d.get("counts") or []]
        top = max([n for _, n in counts] + [1])
        total = sum(n for _, n in counts)
        voters = d.get("voters") or {}
        cols = (f"--bk:{min(max([_em(label) for label, _ in counts] or [4]), 9):.2f}em;"
                f"--bn:{max([_em(f'{n} 票 · {round(n / total * 100) if total else 0}%') for _, n in counts] or [4]) + .2:.2f}em")
        bars = "".join(f'<div class="bar{" win" if label == d.get("winner") else ""}"><span class="bk">{e(label)}</span>'
                       f'<div class="track"><i style="width:{n / top * 100:.0f}%"></i></div>'
                       f'<span class="bn num">{n} 票 · {round(n / total * 100) if total else 0}%</span>'
                       + (f'<div class="bv">{_avatars(voters[label])}<span>{e("、".join(voters[label]))}</span></div>' if voters.get(label) else "")
                       + "</div>"
                       for label, n in counts)
        return (_top(None, "表决结果", d.get("title", ""))
                + f'<div class="turn"><div class="orb"><div class="r"></div><div class="f">{ICONS["vote"]}</div></div>'
                f'<div><div class="turn-t">结果：<b>{e(d.get("winner", ""))}</b></div><div class="turn-d">共 {total} 票</div></div></div>'
                + f'<div class="bars" style="{cols}">{bars}</div>' + (f'<div class="hint">{rich(d["note"])}</div>' if d.get("note") else "")), "表决结果"
    if kind == "ending":
        heading = "终章" + (f" · {d['ending']}" if d.get("ending") else "")
        return _ending(d, art, heading), d.get("title") or "终章"
    return _narration(msg, art)


def _journey(acts: list[dict[str, Any]], ending: str) -> str:
    """The acts played, top to bottom, closing on the ending's node."""
    nodes = "".join(f'<div class="jn"><span class="jd num">{a["number"]}</span><div><b>{e(act_label(a["number"]))}'
                    + (f' · {e(a["title"])}' if a.get("title") else "") + "</b>"
                    + (f'<div class="sd">本幕最佳 {e(a["best"])}</div>' if a.get("best") else "") + "</div></div>" for a in acts)
    nodes += f'<div class="jn end"><span class="jd">终</span><div><b>{e(ending or "故事完结")}</b></div></div>'
    return f'<div class="journey">{nodes}</div>'


def _ending(d: dict[str, Any], art: dict[str, Any] | None, heading: str) -> str:
    rep = d.get("report") or {}
    parts = [_top(art, "终章", heading, d.get("title", ""))]
    if rep:
        parts.append(_stat_cells((("轮", rep.get("rounds", 0), ""), ("次检定", rep.get("checks", 0), ""),
                                  ("大成功", rep.get("crits", 0), " up"), ("大失败", rep.get("fumbles", 0), " down"))))
        parts.append(_outcomes(rep.get("outcomes") or {}))
        if rep.get("best"):
            parts.append(f'<div class="mvp hero"><span class="stamp">最</span><div><b>{e(rep["best"])}</b><div class="sd">全场最佳</div></div></div>')
        if rep.get("acts"):
            parts.append(_sect("旅程", _journey(rep["acts"], d.get("ending", ""))))
    epis = "".join(f'<div class="epi">{_avatar(n)}<div><b>{e(n)}</b><p>{e(t)}</p></div></div>' for n, t in d.get("epilogues") or [])
    if epis:
        parts.append(_sect("尾声", f'<div class="epis">{epis}</div>') if rep else f'<div class="epis">{epis}</div>')
    if not rep:
        chips = "".join(_chip(s.strip(), icon="vote") for s in str(d.get("stats", "")).split("·") if s.strip())
        parts.append(f'<div class="uses">{chips}</div>' if chips else "")
    return "".join(parts) + _cmds(("收桌", "/团 关闭"))


def _loadout(d: dict[str, Any]) -> tuple[str, str]:
    meters = _meters(d.get("resources") or [])
    parts = [f'<div class="eyebrow"><span>技能与物品</span><b>{e(d.get("name", ""))}</b></div>']
    if meters:
        parts.append(_vitals(meters))
    for kind, label in (("skill", "技能"), ("item", "物品")):
        rows = [x for x in d.get("entries") or [] if x["kind"] == kind]
        if rows:
            parts.append(_sect(label, "".join(
                f'<div class="skill{"" if x["usable"] else " off"}"><span class="ic">{ICONS[kind]}</span><div>'
                f'<b>{e(x["name"])}</b> <span class="kbd">{e(x["effect"])}</span>'
                + (f'<div class="sd">{e(x["note"])}</div>' if x.get("note") else "")
                + (f'<div class="why">{e(x["reason"])}</div>' if x.get("reason") else "") + "</div>"
                + (f'<span class="left num">{e(x["count"])}</span>' if x.get("count") else "<span></span>") + "</div>" for x in rows)))
    if not d.get("entries"):
        parts.append('<div class="line">没有技能或物品。</div>')
    if d.get("own"):
        parts.append(_cmds(("检定加成", "[用 名称]"), ("直接使用", "/团 使用 名称")))
    return "".join(parts), d.get("name") or SEGMENT_LABELS["sheet"]


def _roster(d: dict[str, Any]) -> tuple[str, str]:
    seated, cap = int(d.get("seated") or 0), int(d.get("cap") or 0)
    tone = {"就绪": "ok", "暂离": "away"}
    rows = d.get("rows") or []
    ready = sum(1 for _, _, state in rows if state == "就绪")
    cells = "".join(f'<div class="chair {tone.get(state, "wait")}">{_avatar(user)}<b>{e(user)}</b><div class="sd">{e(role) or "未建卡"}</div>'
                    f'<span class="state {tone.get(state, "wait")}">{e(state)}</span></div>' for user, role, state in rows)
    cells += '<div class="chair empty"><span class="ava">+</span><b>空位</b><div class="sd">/团 加入</div></div>' * max(0, cap - len(rows))
    cols = min(max(cap, len(rows), 1), 4)
    return (f'<div class="eyebrow"><span>阵容</span><b>{seated}/{cap} 人 · {ready} 人就绪</b></div>'
            f'<div class="chairs" style="grid-template-columns:repeat({cols},1fr)">{cells}</div>'), "阵容"


def _people(d: dict[str, Any]) -> tuple[str, str]:
    met = d.get("met") or []
    rows = "".join(f'<div class="npc-row">{_avatar(p["name"])}<div class="nm"><b>{e(p["name"])}</b>'
                   + (_contribs(p["contributions"]) if p.get("contributions") else "")
                   + f'</div><div class="sc">{_scale(p["standing"])}<span class="tier">{e(p["tier"])}</span></div></div>' for p in met)
    body = f'<div class="npc-list">{rows}</div>' if rows else '<div class="line">还没有遇到任何人。剧情里出现的人物会自动记录。</div>'
    return (f'<div class="eyebrow"><span>登场人物</span><b>态度针对整个队伍</b></div>' + body
            + _cmds(("详情", "/团 人物 名字"), ("争取态度", "/团 关系 人物 名字：做法"))), "登场人物"


def _person(d: dict[str, Any]) -> tuple[str, str]:
    name = d.get("name", "")
    standing = int(d.get("standing") or 0)
    tone = "up" if standing > 0 else "down" if standing < 0 else ""
    parts = [f'<div class="eyebrow"><span>{"势力" if d.get("faction") else "人物"}</span><b>{e(d.get("tier", ""))}</b></div>',
             f'<div class="me person"><div class="medal"><div class="halo"></div><div class="avatar">{e(name[:1])}</div></div><div><div class="me-name">{e(name)}</div>'
             + (f'<div class="me-line">{e(d["description"])}</div>' if d.get("description") else "") + "</div>"
             f'<div class="ptier {tone}"><b>{e(d.get("tier", ""))}</b><span>对队伍</span></div></div>']
    contrib = _contribs(d["contributions"]) if d.get("contributions") else ""
    parts.append(_sect("对队伍的态度", _scale(standing, labels=True) + contrib))
    if d.get("motivation"):
        parts.append(f'<div class="box" style="margin-top:1rem"><h4>动机</h4><div class="goal">{e(d["motivation"])}</div></div>')
    if d.get("memories"):
        parts.append(_sect("往来", '<div class="tline">' + "".join(
            f'<div class="tl {"up" if m.get("change", 0) > 0 else "down" if m.get("change", 0) < 0 else ""}"><i></i><b>{e(m["who"])}</b>'
            f'<span>{e(m["text"])}</span>'
            + (f'<em class="num">{"↑" if m["change"] > 0 else "↓"} {_signed(m["change"])}</em>' if m.get("change") else "<em>记录</em>") + "</div>"
            for m in d["memories"]) + "</div>"))
    parts.append(_cmds(("争取态度", f"/团 关系 人物 {name}：做法"), ("记下往来", f"/团 关系 记下 {name}：往来")))
    return "".join(parts), "人物"


def _record_card(d: dict[str, Any]) -> tuple[str, str]:
    parts = ['<div class="eyebrow"><span>记录详情</span></div>', f'<div class="recs">{_record(d.get("line", ""))}</div>']
    parts.append(_record_meter(d.get("meter") or {}))
    parts.extend(f'<blockquote class="rq">{e(t)}</blockquote>' for t in d.get("texts") or [])
    if d.get("rows"):
        parts.append('<div class="box" style="margin-top:1rem"><h4>条目</h4>' + "".join(f'<div class="chg">{glyphs(rich(r))}</div>' for r in d["rows"]) + "</div>")
    if d.get("steps"):
        parts.append('<div class="box"><h4>接下来可以</h4>' + "".join(f'<div class="chg">{rich(s)}</div>' for s in d["steps"]) + "</div>")
    return "".join(parts), "记录详情"


_STEP_MARKS = {"done": ("done", "✓"), "failed": ("failed", "✕"), "withdrawn": ("off", "–")}


def _record_meter(m: dict[str, Any]) -> str:
    kind = m.get("kind")
    if kind == "contest":
        length = max(1, int(m["length"]))
        ticks = "".join(f'<i style="left:{i / length * 100:.1f}%"></i>' for i in range(1, length))
        row = lambda cls, label, value: (f'<div class="race {cls}"><span class="rl">{e(label)}</span><div class="rbar"><b style="width:'
                                         f'{min(value, length) / length * 100:.0f}%"></b>{ticks}</div><span class="num">{value}/{length}</span></div>')
        return (f'<div class="meter">{row("ours", "我方", m["ours"])}{row("theirs", m.get("opponent") or "对方", m["theirs"])}'
                '<div class="mnote">先推满轨道的一方赢下这场对抗</div></div>')
    if kind == "progress":
        total = max(1, int(m["total"]))
        ticks = "".join(f'<i style="left:{i / total * 100:.1f}%"></i>' for i in range(1, total))
        return (f'<div class="meter"><div class="race ours"><span class="rl">进度</span><div class="rbar"><b style="width:'
                f'{min(int(m["done"]), total) / total * 100:.0f}%"></b>{ticks}</div><span class="num">{m["done"]}/{total}{e(m.get("unit", ""))}</span></div></div>')
    if kind == "steps":
        dots = "".join(f'<span class="st {_STEP_MARKS.get(s, ("", ""))[0]}"><b>{_STEP_MARKS.get(s, ("", i + 1))[1]}</b><em>步骤{i + 1}</em></span>'
                       for i, s in enumerate(m["steps"]))
        done = sum(1 for s in m["steps"] if s == "done")
        return f'<div class="meter"><div class="chain">{dots}</div><div class="mnote">已完成 {done}/{len(m["steps"])} 步</div></div>'
    return ""


_LADDER = (("gale", "逆风", "1"), ("cloud", "阴云", "2–7"), ("calm", "平潮", "8–13"), ("fair", "顺风", "14–19"), ("dawn", "天光", "20"))


def _signs(label: str, cls: str, signs: list[list[str]]) -> str:
    rows = "".join(f'<li><b>{e(term)}</b><span>{e(gloss)}</span></li>' for term, gloss in signs)
    return f'<section class="sign {cls}"><div class="stamp">{label}</div><ul>{rows}</ul></section>'


def _daily(msg: Msg, art: dict[str, Any] | None) -> tuple[str, str]:
    d = msg.data or {}
    if d.get("kind") == "board":
        return _daily_board(d)
    if d.get("kind") in _DAILY_CARDS:
        return _DAILY_CARDS[d["kind"]](d)
    if d.get("kind") != "roll":
        return _narration(msg, art)
    tier, face = d.get("tier", "calm"), int(d.get("face") or 0)
    ladder = "".join(f'<div class="rung{" now" if key == tier else ""} t-{key}"><i></i><b>{label}</b><span class="num">{span}</span></div>'
                     for key, label, span in _LADDER)
    return (f'<div class="eyebrow"><span>今日一掷</span><b>{e(d.get("day", ""))}</b></div>'
            f'<div class="omen t-{e(tier)}{" crit" if d.get("crit") else ""}">'
            f'<div class="orbit"><div class="glow"></div><div class="disc"></div><div class="shadow"></div>'
            f'<div class="die"><span class="num">{face}</span></div></div>'
            f'<div class="omen-r"><div class="who">{e(d.get("name", ""))} 的今日一掷</div><div class="fortune">{e(d.get("fortune", ""))}</div>'
            f'<div class="omen-s">{"今天已经掷过，结果不会改变" if d.get("again") else "d20 · 每人每天一次"}</div></div></div>'
            f'<div class="ladder">{ladder}</div>'
            + (f'<div class="crit-line t-{e(tier)}">{e(d["crit"])}</div>' if d.get("crit") else "")
            + f'<div class="signs">{_signs("宜", "yi", d.get("yi") or [])}{_signs("忌", "ji", d.get("ji") or [])}</div>'
            + '<div class="omen-note">每日一次，不改变故事里的检定</div>'), "今日一掷"


def _daily_board(d: dict[str, Any]) -> tuple[str, str]:
    rows = d.get("rows") or []
    counts = {label: 0 for _, label, _ in _LADDER}
    for r in rows:
        counts[r["fortune"]] = counts.get(r["fortune"], 0) + 1
    tiers = {label: key for key, label, _ in _LADDER}
    spread = "".join(f'<div class="tally t-{key}{" on" if counts[label] else ""}"><b class="num">{counts[label]}</b><span>{label}</span></div>'
                     for key, label, _ in reversed(_LADDER))
    parts = [f'<div class="eyebrow"><span>今日一掷 · 本群</span><b>{e(d.get("day", ""))}</b></div>',
             f'<div class="spread"><div class="sum"><b class="num">{len(rows)}</b><span>人已掷</span></div>{spread}</div>']
    if rows:
        by_face: dict[int, list[str]] = {}
        for r in rows:
            by_face.setdefault(int(r["face"]), []).append(r["name"])
        band = lambda f: "gale" if f == 1 else "cloud" if f <= 7 else "calm" if f <= 13 else "fair" if f <= 19 else "dawn"
        cols = "".join(f'<div class="fc t-{band(f)}"><div class="fp">' + "".join(f'<span class="ava sm">{e(n[:1])}</span>' for n in by_face.get(f, [])[:3])
                       + (f'<span class="fmore">+{len(by_face[f]) - 3}</span>' if len(by_face.get(f, [])) > 3 else "")
                       + f'</div><i class="{"on" if f in by_face else ""}"></i><span class="num">{f if f in (1, 5, 10, 15, 20) or f in by_face else ""}</span></div>'
                       for f in range(1, 21))
        parts.append(f'<div class="facestrip">{cols}</div>')
    if rows:
        parts.append('<div class="ranks">' + "".join(
            f'<div class="rank{" top" if i == 0 else ""}"><span class="no num">{i + 1}</span>{_avatar(r["name"])}'
            f'<div class="rn"><b>{e(r["name"])}</b></div><span class="rf t-{tiers.get(r["fortune"], "calm")}">{e(r["fortune"])}</span>'
            f'<span class="face num t-{tiers.get(r["fortune"], "calm")}">{int(r["face"])}</span></div>' for i, r in enumerate(rows)) + "</div>")
    else:
        parts.append('<div class="line" style="margin-top:1rem">今天还没有人掷。</div>')
    parts.append(_cmds(("掷骰", "/团 一掷")))
    return "".join(parts), "本群今日"


def _tiles(terms: list[dict[str, Any]]) -> str:
    out = []
    for t in terms:
        if "faces" not in t:
            out.append(f'<span class="op">{e(t["label"][:1])}</span><span class="tile flat num">{e(t["label"][1:])}</span>')
            continue
        sign = '<span class="op">−</span>' if t["label"].startswith("-") else ('<span class="op">+</span>' if out else "")
        faces = "".join(f'<span class="tile num{"" if k else " drop"}{" hi" if k and f == t["sides"] else ""}">{f}</span>'
                        for f, k in zip(t["faces"], t["kept"]))
        out.append(f'{sign}<span class="group"><span class="gl">{e(t["label"].lstrip("-"))}</span><span class="gt">{faces}</span></span>')
    return "".join(out)


def _dice_card(d: dict[str, Any]) -> tuple[str, str]:
    natural = d.get("natural")
    tone = " crit" if natural == 20 else " fumble" if natural == 1 else ""
    single = natural is not None or (len(d["terms"]) == 1 and d["terms"][0].get("sides") == 20 and len(d["terms"][0].get("faces", [])) == 1)
    figure = (f'<div class="orbit"><div class="glow"></div><div class="disc"></div><div class="shadow"></div>'
              f'<div class="die"><span class="num">{e(d["total"])}</span></div></div>' if single
              else f'<div class="sum-ring"><b class="num">{e(d["total"])}</b><span>合计</span></div>')
    return (f'<div class="eyebrow"><span>{"暗骰" if d.get("hidden") else "掷骰"}</span><b>{e(d.get("reason", ""))}</b></div>'
            f'<div class="omen roll{tone}">{figure}<div class="omen-r"><div class="who">{e(d["name"])} 掷</div>'
            f'<div class="expr num">{e(d["expr"])}</div>'
            + (f'<div class="omen-s nat">天然 {natural}</div>' if natural else "")
            + f'<div class="tiles">{_tiles(d["terms"])}</div></div></div>'
            + ("" if single else _dice_range(d["terms"], int(d["total"])))
            + ('<div class="omen-note">暗骰：只有你能看到</div>' if d.get("hidden") else "")), "暗骰" if d.get("hidden") else "掷骰"


def _dice_range(terms: list[dict[str, Any]], total: int) -> str:
    """Lowest to highest possible total, where this roll fell, and the average when no die was dropped."""
    lo = hi = 0
    dropped = False
    for t in terms:
        if "faces" not in t:
            lo, hi = lo + int(t["value"]), hi + int(t["value"])
            continue
        kept = sum(1 for k in t["kept"] if k)
        dropped = dropped or kept < len(t["kept"])
        low, high = kept, kept * int(t["sides"])
        if str(t["label"]).startswith("-"):
            low, high = -high, -low
        lo, hi = lo + low, hi + high
    if hi <= lo:
        return ""
    pct = lambda v: (v - lo) / (hi - lo) * 100
    avg = (lo + hi) / 2
    mean = "" if dropped else f'<i class="avg" style="left:{pct(avg):.0f}%"><span>平均 {avg:g}</span></i>'
    tone = "hi" if total >= hi else "lo" if total <= lo else ""
    return (f'<div class="drange {tone}"><span class="num">{lo}</span><div class="dr"><b style="width:{pct(total):.0f}%"></b>{mean}'
            f'<em style="left:{pct(total):.0f}%" class="num">{total}</em></div><span class="num">{hi}</span></div>')


def _duel_card(d: dict[str, Any]) -> tuple[str, str]:
    x, y = d["rounds"][-1]
    side = lambda name, face, win: (f'<div class="duelist{" win" if win else ""}">{_avatar(name)}<b>{e(name)}</b>'
                                    f'<div class="die"><span class="num">{face}</span></div>'
                                    f'<span class="crown">{"胜" if win else ""}</span></div>')
    ties = len(d["rounds"]) - 1
    return (f'<div class="eyebrow"><span>骰子对决</span><b>{e(d.get("reason", ""))}</b></div>'
            f'<div class="duel">{side(d["a"], x, d["winner"] == d["a"])}<div class="vs">VS</div>{side(d["b"], y, d["winner"] == d["b"])}</div>'
            + (f'<div class="omen-note">平局重掷 {ties} 次：' + "　".join(f"{a}:{b}" for a, b in d["rounds"][:-1]) + "</div>" if ties else "")
            + ("" if d["winner"] else '<div class="omen-note">连掷十次都是平局，握手言和</div>')), "骰子对决"


def _relay_card(d: dict[str, Any]) -> tuple[str, str]:
    names = list(dict.fromkeys(line["name"] for line in d["lines"]))
    hue = {n: i % 6 for i, n in enumerate(names)}
    lines = "".join(f'<span class="ln h{hue[line["name"]]}">{e(sentence(line["text"]))}<sup>{e(line["name"])}</sup></span>' for line in d["lines"])
    return (f'<header class="head"><div class="eyebrow-l">故事接龙 · {len(d["lines"])} 句</div><h2>{e(d.get("title") or "未完")}</h2></header>'
            f'<div class="relay">{lines}</div>'
            + (f'<div class="box ending-box"><h4>结局 · AI 收尾</h4><div class="goal">{e(d["ending"])}</div></div>' if d.get("ending") else "")
            + '<div class="uses"><span class="lab">执笔</span>' + "".join(
                f'<span class="chip pen h{hue[n]}"><i></i>{e(n)}<em>{sum(1 for x in d["lines"] if x["name"] == n)} 句</em></span>' for n in names)
            + "</div>"), "故事接龙"


_TIER_KEYS = {label: key for key, label, _ in _LADDER}


def _luck_card(d: dict[str, Any]) -> tuple[str, str]:
    key = d.get("tier_key") or "calm"
    faces = d.get("faces") or [0] * 20
    peak = max(faces) or 1
    expect = d["count"] / 20 if d.get("count") else 0
    cols = "".join(
        f'<div class="hc{" crit" if i == 19 else " fumble" if i == 0 else " up" if i >= 10 else ""}">'
        f'<em class="num">{n or ""}</em><i style="height:{max(2, round(n / peak * 100)) if n else 0}%"></i>'
        f'<span class="num">{i + 1 if i + 1 in (1, 5, 10, 15, 20) else ""}</span></div>' for i, n in enumerate(faces))
    line = f'<div class="hist-exp" style="bottom:calc(1.25rem + {expect / peak * 100 * 0.78:.1f}%)"></div>' if expect else ""
    cells = (("count", d.get("count", 0), "次 d20", ""), ("crits", d.get("crits", 0), "大成功", " up"),
             ("fumbles", d.get("fumbles", 0), "大失败", " down"), ("high", f'{d.get("high", 0)}%', "掷出 11+", ""))
    stats = "".join(f'<div class="rs-cell{tone}"><b class="num">{e(v)}</b><span>{e(label)}</span></div>' for _, v, label, tone in cells)
    sources = "".join(_chip(f"{label} {n}", icon="dice") for label, n in d.get("sources") or [])
    body = (f'<div class="eyebrow"><span>骰运 · 本群</span><b>{e(d.get("period", ""))}</b></div>'
            f'<div class="omen t-{e(key)}"><div class="sum-ring luck"><b class="num">{d.get("average", 0):.2f}</b><span>平均点数</span></div>'
            f'<div class="omen-r"><div class="who">{e(d.get("name", ""))} 的骰运</div><div class="fortune">{e(d.get("tier", ""))}</div>'
            f'<div class="omen-s">公平的 d20 平均 10.5 · 全部记录 {e(d.get("total", 0))} 次</div></div></div>')
    if not d.get("count"):
        return body + '<div class="omen-note">这段时间还没掷过 d20</div>' + _cmds(("全部记录", "/团 骰运 全部")), "骰运"
    return (body + f'<div class="hist-wrap"><div class="hist">{cols}{line}</div></div>'
            f'<div class="rstats">{stats}</div>'
            + (f'<div class="uses"><span class="lab">来源</span>{sources}</div>' if sources else "")
            + '<div class="omen-note">虚线是公平骰子每一面的期望次数 · 跑团检定、今日一掷、自由掷骰和对决都算</div>'
            + _cmds(("骰运榜", "/团 骰运 榜"))), "骰运"


def _luck_rows(rows: list[dict[str, Any]], start: int = 0) -> str:
    return "".join(
        f'<div class="rank{" top" if start == 0 and i == 0 else ""} t-{e(r.get("tier_key", "calm"))}"><span class="no num">{start + i + 1}</span>'
        f'{_avatar(r["name"])}<div class="rn"><b>{e(r["name"])}</b><div class="sd">{r["count"]} 次 · 大成功 {r["crits"]} · 大失败 {r["fumbles"]}</div></div>'
        f'<span class="rf">{e(r["tier"])}</span><span class="face num">{r["average"]:.1f}</span></div>' for i, r in enumerate(rows))


def _luck_board(d: dict[str, Any]) -> tuple[str, str]:
    ranked = d.get("ranked") or []
    top = ranked[:3]
    bottom = [r for r in ranked[::-1][:3] if r not in top]
    medal = lambda cls, label, item: (f'<div class="honor {cls}"><span class="stamp">{"20" if cls == "crit" else "1"}</span>'
                                      f'<div><div class="ml">{label}</div><b>{e(item["name"]) if item else "—"}</b>'
                                      f'<div class="sd">{str(item["n"]) + " 次" if item else "还没有人掷出"}</div></div></div>')
    parts = [f'<div class="eyebrow"><span>骰运榜 · 本群</span><b>{e(d.get("month", ""))}</b></div>',
             f'<div class="spread"><div class="sum"><b class="num">{d.get("rolls", 0)}</b><span>颗 d20</span></div>'
             + "".join(f'<div class="tally on t-{key}"><b class="num">{sum(1 for r in ranked if r["tier"] == label)}</b><span>{label}</span></div>'
                       for key, label, _ in reversed(_LADDER)) + "</div>"]
    if ranked:
        parts.append(f'<div class="board-h"><span>欧皇</span><em>平均点数最高</em></div><div class="ranks">{_luck_rows(top)}</div>')
        if bottom:
            parts.append(f'<div class="board-h low"><span>非酋</span><em>平均点数最低</em></div><div class="ranks">{_luck_rows(bottom, len(ranked) - len(bottom))}</div>')
    else:
        parts.append(f'<div class="omen-note" style="margin-top:1.4rem">这个月还没有人掷满 {e(d.get("minimum", 10))} 次 d20</div>')
    parts.append(f'<div class="honors">{medal("crit", "大成功最多", d.get("crit"))}{medal("fumble", "大失败最多", d.get("fumble"))}</div>')
    parts.append(f'<div class="omen-note">掷满 {e(d.get("minimum", 10))} 次 d20 才上榜 · 共 {e(d.get("players", 0))} 人掷过</div>')
    return "".join(parts) + _cmds(("我的骰运", "/团 骰运")), "骰运榜"


def _quote_size(text: str) -> str:
    return "q-l" if len(text) <= 28 else "q-m" if len(text) <= 60 else "q-s"


def _quote_card(d: dict[str, Any]) -> tuple[str, str]:
    cmds = ((("一起收藏", f'/团 金句 +{d.get("no", "")}'), ("金句榜", "/团 金句 榜")) if d.get("mode") == "random"
            else (("随机重温", "/团 金句"), ("金句榜", "/团 金句 榜")))
    return (f'<div class="eyebrow"><span>{e(d.get("head", "金句"))}</span><b class="num">No.{e(d.get("no", ""))}</b></div>'
            f'<figure class="qcard"><div class="qmark">“</div><blockquote class="{_quote_size(d["text"])}">{e(d["text"])}</blockquote>'
            + (f'<figcaption>—— {e(d["source"])}</figcaption>' if d.get("source") else "") + "</figure>"
            f'<div class="qmeta"><span class="qpill">{ICONS["heart"]}<b class="num">{e(d.get("marks", 1))}</b> 人收藏</span>'
            f'<span>{e(d.get("saved_name", ""))} 最先收录</span></div>'
            + _cmds(*cmds)), "金句"


def _quote_board(d: dict[str, Any]) -> tuple[str, str]:
    rows = d.get("rows") or []
    body = "".join(f'<div class="qrow{" top" if i == 0 else ""}"><span class="qno num">{i + 1}</span><div class="qbody">'
                   f'<div class="qt">{e(r["text"])}</div><div class="sd">—— {e(r["source"])} · No.{e(r["id"])}</div></div>'
                   f'<span class="qpill">{ICONS["heart"]}<b class="num">{e(r["marks"])}</b></span></div>' for i, r in enumerate(rows))
    return (f'<div class="eyebrow"><span>金句榜 · 本群</span><b>共 {e(d.get("total", 0))} 句</b></div>'
            + (f'<div class="qlist">{body}</div>' if rows else '<div class="omen-note" style="margin-top:1.4rem">本群还没有金句</div>')
            + _cmds(("按编号收藏", "/团 金句 +编号"), ("随机重温", "/团 金句"))), "金句榜"


def _soup_keys(keys: list[dict[str, Any]], reveal: bool = False) -> str:
    found = sum(1 for k in keys if k.get("by"))
    track = "".join(f'<i class="{"on" if k.get("by") else ""}"></i>' for k in keys)
    rows = "".join(
        f'<div class="key{" on" if k.get("by") else ""}"><span class="kn num">{i + 1}</span>'
        f'<b>{e(k["text"]) if (k.get("by") or reveal) else "尚未解锁"}</b>'
        + (f'<em>{e(k["by"])}</em>' if k.get("by") else "") + "</div>" for i, k in enumerate(keys))
    return (f'<div class="keys-h"><span>关键线索</span><b class="num">{found}/{len(keys)}</b><div class="ktrack">{track}</div></div>'
            f'<div class="keys">{rows}</div>')


def _soup_card(d: dict[str, Any]) -> tuple[str, str]:
    from .messages import SOUP_TONES
    asked = d.get("asked") or []
    qa = "".join(f'<div class="qa"><span class="ans a-{SOUP_TONES.get(a["a"], "skip")}">{e(a["a"])}</span>'
                 f'<div class="qq">{e(a["q"])}</div><span class="qw">{e(a["name"])}</span></div>' for a in asked)
    state = "新汤上桌" if d.get("fresh") else f'已问 {e(d.get("count", 0))} 问'
    return (f'<div class="eyebrow"><span>海龟汤 · {e(d.get("flavor", ""))}</span><b>{state}</b></div>'
            f'<header class="head"><div class="eyebrow-l">{e(d.get("server", ""))} 端上</div><h2>{e(d.get("title", ""))}</h2></header>'
            f'<div class="soup-face flavor-{"red" if d.get("flavor") == "红汤" else "clear"}"><div class="sl">汤面</div><p>{e(d.get("surface", ""))}</p></div>'
            + _soup_keys(d.get("keys") or [])
            + (f'<div class="board-h"><span>最近的提问</span><em>共 {e(d.get("count", 0))} 问 · 猜过 {e(d.get("guesses", 0))} 次</em></div><div class="qas">{qa}</div>' if asked
               else '<div class="omen-note">主持人只回答：是 · 否 · 无关 · 是也不是</div>')
            + _cmds(("提问", "/团 问 是非题"), ("推理", "/团 猜 你的推理"))), "海龟汤"


def _soup_end(d: dict[str, Any]) -> tuple[str, str]:
    solver = d.get("solver") or ""
    keys = d.get("keys") or []
    found = sum(1 for k in keys if k.get("by"))
    cells = ((d.get("count", 0), "次提问"), (d.get("guesses", 0), "次推理"), (f'{found}/{len(keys)}', "条线索"), (d.get("minutes", 0), "分钟"))
    stats = "".join(f'<div class="rs-cell"><b class="num">{e(v)}</b><span>{label}</span></div>' for v, label in cells)
    return (f'<div class="eyebrow"><span>汤底揭晓 · {e(d.get("flavor", ""))}</span><b>{e(d.get("title", ""))}</b></div>'
            + (f'<div class="mvp solved">{_avatar(solver)}<div><b>{e(solver)} 喝透了这碗汤</b><div class="sd">{e(d.get("guess", ""))}</div></div>'
               f'<span class="stamp">破</span></div>' if solver else
               '<div class="mvp unsolved"><span class="stamp">揭</span><div><b>没人喝透，直接揭晓</b><div class="sd">下一碗再来</div></div></div>')
            + f'<div class="soup-face small"><div class="sl">汤面</div><p>{e(d.get("surface", ""))}</p></div>'
            f'<div class="truth"><div class="sl">汤底</div><p>{e(d.get("truth", ""))}</p></div>'
            + _soup_keys(keys, reveal=True)
            + f'<div class="rstats">{stats}</div>'
            + (f'<div class="omen-note">线索功臣：{e(d["top"])}</div>' if d.get("top") else "")
            + _cmds(("再来一碗", "/团 海龟汤"))), "汤底揭晓"


_DAILY_CARDS = {"dice": _dice_card, "duel": _duel_card, "relay": _relay_card, "luck": _luck_card, "luck_board": _luck_board,
                "quote": _quote_card, "quote_board": _quote_board, "soup": _soup_card, "soup_end": _soup_end}


def _report_card(d: dict[str, Any], art: dict[str, Any] | None) -> tuple[str, str]:
    now_act = next((a for a in d.get("acts") or [] if a["number"] == d["act"]), None)
    heading = act_label(d["act"]) + (f" · {now_act['title']}" if now_act and now_act["title"] else "")
    parts = [_top(art, "战报", d["title"], d.get("sub", ""))]
    total = int(d.get("total") or 0)
    bar = ("".join(f'<i class="{"on" if i < d["act"] else ""}{" now" if i == d["act"] - 1 else ""}"></i>' for i in range(total))
           if total else "")
    parts.append(f'<div class="acts"><div class="al"><b>{e(heading)}</b></div>'
                 + (f'<div class="segs">{bar}</div><span class="an num">{d["act"]}/{total}</span>' if total else
                    f'<div></div><span class="an">{e(d["state"])}</span>') + "</div>")
    if d.get("ending"):
        parts.append(f'<div class="crit-line t-dawn">结局 · {e(d["ending"])}</div>')
    parts.append(_stat_cells((("轮", d["rounds"], ""), ("次检定", d["checks"], ""), ("大成功", d["crits"], " up"), ("大失败", d["fumbles"], " down"))))
    parts.append(_outcomes(d.get("outcomes") or {}))
    if d.get("cast"):
        parts.append(_sect("阵容", '<div class="cast">' + "".join(_cast_member(c) for c in d["cast"]) + "</div>"))
    bests = [a for a in d.get("acts") or [] if a.get("best")]
    if d.get("best") or bests:
        rows = (f'<div class="mvp"><span class="stamp">最</span><div><b>{e(d["best"])}</b><div class="sd">全场最佳</div></div></div>' if d.get("best") else "")
        rows += "".join(f'<div class="memo"><b>{e(act_label(a["number"]))}</b><span>{e(a["title"])}</span><em>{e(a["best"])}</em></div>' for a in bests)
        parts.append(_sect("喝彩", rows))
    if d.get("quote"):
        parts.append(f'<blockquote class="rq">{e(d["quote"])}</blockquote>')
    return "".join(parts), "战报"


def _cast_member(c: dict[str, Any]) -> str:
    """A character with how often they acted and how their checks went."""
    checks, wins = int(c.get("checks") or 0), int(c.get("wins") or 0)
    record = ""
    if "checks" in c:
        record = (f'<div class="cbar"><div class="track"><i style="width:{wins / checks * 100 if checks else 0:.0f}%"></i></div>'
                  f'<span class="num">{f"成功 {wins}/{checks}" if checks else "未检定"} · 出手 {int(c.get("turns") or 0)} 次</span></div>')
    return (f'<div class="castm">{_avatar(c["name"])}<div class="cm"><b>{e(c["name"])}</b>'
            f'<div class="sd">{e(c.get("role", ""))} · {e(c.get("player", ""))}</div>{record}</div></div>')


def _schedule_card(d: dict[str, Any]) -> tuple[str, str]:
    top = max([len(o["names"]) for o in d["options"]] + [1])
    most = max([len(o["names"]) for o in d["options"]] + [0])
    rows = "".join(
        f'<div class="slot{" on" if o["decided"] else ""}"><span class="no num">{i}</span><div class="sl"><b>{e(o["label"])}</b>'
        + ('<span class="tag-most">最多人</span>' if not d["decided"] and most and len(o["names"]) == most else "")
        + f'<div class="track"><i style="width:{len(o["names"]) / top * 100:.0f}%"></i></div>'
        + (f'<div class="sd">{_avatars(o["names"])}<span>{e("、".join(o["names"]))}</span></div>' if o["names"] else "") + "</div>"
        f'<span class="cnt num">{len(o["names"])} 人</span>' + ('<span class="rs">已定档</span>' if o["decided"] else "") + "</div>"
        for i, o in enumerate(d["options"], 1))
    parts = [f'<div class="eyebrow"><span>约团 · {e(d["title"])}</span><b>{"已定档" if d["decided"] else "征集中"}</b></div>',
             f'<div class="slots">{rows}</div>']
    if d.get("declined"):
        parts.append(f'<div class="line" style="margin-top:.8rem"><span class="lab">都不行</span>{e("、".join(d["declined"]))}</div>')
    parts.append(_hint({"text": "开始前 30 分钟会在群里提醒勾选了这个时间的人", "cmds": []}) if d["decided"]
                 else _cmds(("勾选", "/团 约 1 3"), ("定档", "/团 定档 序号")))
    return "".join(parts), "约团"


# ---------------------------------------------------------------- layouts
def _narration(msg: Msg, art: dict[str, Any] | None) -> tuple[str, str]:
    blocks = _flat(msg)
    title = sub = ""
    while blocks and blocks[0].kind in ("heading", "banner", "caption"):
        head = blocks.pop(0)
        if head.kind == "caption":
            sub = sub or head.data["text"]
        else:
            title = title or head.data["text"]
    parts = []
    if art:
        parts.append(_banner(art, title or sub, sub if title else ""))
    elif title or sub:
        parts.append('<header class="head">' + (f'<div class="eyebrow-l">{e(sub)}</div>' if sub else "")
                     + (f"<h2>{e(title)}</h2>" if title else "") + "</header>")
    body, boxes, lead = [], [], True
    for block in blocks:
        d = block.data
        if block.kind == "para":
            text = str(d["text"])
            cls = "say" if text[:1] in "“「\"『" else ("lead" if lead and len(text) >= LEAD_MIN else "")
            lead = False
            body.append(f'<p class="{cls}">{e(text)}</p>')
        elif block.kind == "quote":
            body.append(f'<p class="say">{e(d["text"])}</p>')
        elif block.kind == "field":
            label = "当前目标" if d["label"] == "目标" else d["label"]
            boxes.append(f'<div class="box"><h4>{e(label)}</h4><div class="goal">{rich(d["value"])}</div></div>')
        elif block.kind == "people":
            npcs = "".join(f'<div class="npc"><b>{e(n)}</b><div>{e(t)}</div></div>' for n, t in d["items"])
            boxes.append(f'<div class="box"><h4>登场人物</h4><div class="npcs">{npcs}</div></div>')
        else:
            body.append(_generic(block))
    parts.append('<div class="body">' + "".join(body) + "</div>" + "".join(boxes))
    return "".join(parts), (art or {}).get("tag") or sub or SEGMENT_LABELS["narration"]


def _status(msg: Msg, art: dict[str, Any] | None) -> tuple[str, str]:
    blocks = _flat(msg)
    meters = [b.data for b in blocks if b.kind == "meter"]
    personal = any(b.kind in ("quote", "check", "meter") for b in blocks)
    parts, name, round_label = [], "", ""
    shown_meters = False
    for block in blocks:
        d, k = block.data, block.kind
        if k == "title" and personal:
            name = d["text"]
            pieces = [p.strip() for p in str(d.get("sub") or "").split("｜") if p.strip()]
            round_label = next((p for p in pieces if re.fullmatch(r"第\s*\d+\s*轮", p)), "")
            role = next((p for p in pieces if p != round_label), "")
            parts.append(f'<div class="eyebrow"><span>个人状态</span><b>{e(round_label)}</b></div>' + _medal(name, role))
        elif k == "title":
            parts.append(f'<header class="head"><div class="eyebrow-l">{e(d.get("sub") or "通知")}</div><h2>{e(d["text"])}</h2></header>')
        elif k == "quote":
            parts.append(f'<div class="quote"><div class="who">{e(name)} · 本次行动</div><div class="t">{e(d["text"])}</div></div>')
        elif k == "check":
            parts.append(_throw(d))
        elif k == "field" and d["label"] == "准备":
            chips = "".join(_chip(*_prep(p)) for p in str(d["value"]).split("、") if p)
            parts.append(f'<div class="uses"><span class="lab">本次准备</span>{chips}</div>')
        elif k == "meter":
            if not shown_meters:
                parts.append(_vitals(meters))
                shown_meters = True
        else:
            html_part = _generic(block)
            parts.append(f'<div class="pad">{html_part}</div>' if html_part else "")
    return "".join(parts), round_label or SEGMENT_LABELS["status"]


def _prep(text: str) -> tuple[str, str]:
    match = re.fullmatch(r"(.+?)\s*([+-]\d+)", text.strip())
    return (match.group(1), f"加值 {match.group(2)}") if match else (text.strip(), "")


def _fate(item: dict[str, Any], vote: bool) -> str:
    tag = str(item.get("tag") or "")
    right, sub = "", ""
    if vote:
        tags = "".join(f'<span class="vt {"risk" if t.startswith("风险") else "cost"}">{e(t.replace("：", " · ", 1))}</span>'
                       for t in tag.split("　") if t)
        return (f'<div class="fate"><span class="key">{e(item["label"])}</span><div><div class="title">{e(item["text"])}</div>'
                + (f'<div class="vtags">{tags}</div>' if tags else "") + "</div></div>")
    elif tag == "休整":
        right, sub = f'<div class="odds">{ICONS["moon"]}<span class="k">休整</span></div>', "休整 · 恢复体力，不推进危险"
    elif "·" in tag:
        attr, difficulty, *rest = tag.split("·")
        chance = item.get("chance")
        if chance is None:
            right = f'<div class="odds"><span class="v">{e(difficulty)}</span><span class="k">{e(attr)}检定</span></div>'
        else:
            tone = "hi" if chance >= 70 else "mid" if chance >= 40 else "lo"
            right = (f'<div class="odds chance {tone}"><div class="pie" style="--p:{chance / 100:.2f}"><b class="num">{chance}'
                     f'<small>%</small></b></div><span class="k">{e(attr)} · {e(difficulty)}</span></div>')
        sub = "d20 检定" + "".join(f' · <span class="cost">{e(r)}</span>' if r.startswith("失败") else f" · {e(r)}" for r in rest)
        return (f'<div class="fate"><span class="key">{e(item["label"])}</span><div><div class="title">{e(item["text"])}</div>'
                f'<div class="sub">{sub}</div></div>{right}</div>')
    elif tag:
        sub = tag
    else:
        right, sub = f'<div class="odds">{ICONS["quill"]}<span class="k">叙事</span></div>', "无需检定 · 直接推进叙事"
    return (f'<div class="fate"><span class="key">{e(item["label"])}</span><div><div class="title">{e(item["text"])}</div>'
            + (f'<div class="sub">{e(sub)}</div>' if sub else "") + f"</div>{right}</div>")


def _choices(msg: Msg, art: dict[str, Any] | None) -> tuple[str, str]:
    blocks = _flat(msg)
    vote = any(b.kind == "heading" for b in blocks)
    data = msg.data or {}
    ballot = data if data.get("kind") == "vote_open" else None
    parts, foot = [], SEGMENT_LABELS["choices"]
    for block in blocks:
        d, k = block.data, block.kind
        if k in ("title", "heading"):
            text = str(d["text"]).lstrip("▸ ").strip()
            meta = str(d.get("sub") or "")
            minutes = re.search(r"限时\s*(\d+)\s*分钟", meta)
            meta = re.sub(r"\s*限时\s*\d+\s*分钟", "", meta).strip()
            if text.startswith("轮到 "):
                headline = f"轮到 <b>{e(text[3:])}</b> 行动"
            else:
                headline = e(text)
            foot = meta or foot
            side = (f'<div class="clock num">{minutes.group(1)} 分钟</div>' if minutes else "")
            if ballot:
                voters = max(1, int(ballot.get("voters") or 1))
                side = (f'<div class="turnout"><span>{e(ballot.get("minutes", ""))} 分钟后截止</span><div class="pie mid" '
                        f'style="--p:{int(ballot.get("ballots") or 0) / voters:.2f}"><b class="num">{e(ballot.get("ballots", 0))}'
                        f'<small>/{voters}</small></b></div></div>')
            parts.append(f'<div class="turn"><div class="orb"><div class="r"></div><div class="f">{ICONS["vote" if vote else "quill"]}</div></div>'
                         f'<div><div class="turn-t">{headline}</div>'
                         + (f'<div class="turn-d">{e(meta)}</div>' if meta else "") + "</div>"
                         + side + "</div>")
        elif k == "para":
            parts.append(f'<p class="premise">{e(d["text"])}</p>')
        elif k == "choices":
            parts.append('<div class="fates">' + "".join(_fate(i, vote) for i in d["items"]) + "</div>")
            if not vote and any(i.get("chance") is not None for i in d["items"]):
                parts.append('<div class="fates-note">成功率按当前属性计算，带上技能或物品加值后更高</div>')
        elif k == "field" and d["label"] == "可准备":
            entries = [x for x in str(d["value"]).split("　") if x and x != "…"]
            chips = "".join(_chip(*_split_entry(x)) for x in entries)
            parts.append(f'<div class="preps"><span class="lab">可准备</span>{chips}</div>')
        elif k == "hint" and ballot:
            parts.append(_hint({**d, "note": ""}))          # the turnout ring already says it
        else:
            parts.append(_generic(block))
    return "".join(parts), foot


def _sheet(msg: Msg, art: dict[str, Any] | None) -> tuple[str, str]:
    c = msg.data or {}
    if c.get("kind") == "loadout":
        return _loadout(c)
    if c.get("kind") == "persona":
        return _persona(c)
    if c.get("kind") == "personas":
        return _personas(c)
    player = c.get("user_name") if c.get("user_name") and c.get("user_name") != c.get("name") else ""
    tag = "　·　".join(x for x in (f"玩家 {player}" if player else "", "暂离" if c.get("away") else "") if x)
    meters = _meters(c.get("resources") or [])
    persona = c.get("persona") or {}
    parts = [f'<div class="eyebrow"><span>角色卡</span><b>{e(tag)}</b></div>',
             _medal(c.get("name", ""), c.get("archetype", ""), c.get("archetype_text", "") if c.get("archetype") else "",
                    persona.get("avatar", ""))]
    if persona:
        parts.append(_persona_band(persona))
    if not c.get("archetype"):
        parts.extend(_hint(b.data) for b in _flat(msg) if b.kind == "hint")
        return "".join(parts), SEGMENT_LABELS["sheet"]
    attrs = c.get("attributes") or []
    if attrs:
        tiles = "".join(f'<div class="stat{" up" if mod > 0 else " down" if mod < 0 else ""}"><span class="sk">{e(n)}</span>'
                        f'<span class="sv num">{e(v)}</span><span class="sm num">{"±0" if not mod else f"{mod:+d}".replace("-", "−")}</span></div>'
                        for n, v, mod in attrs)
        parts.append(f'<div class="stats" style="grid-template-columns:repeat({min(len(attrs), 5)},1fr)">{tiles}</div>')
    if meters:
        parts.append(_vitals(meters))
    if c.get("skills"):
        rows = "".join(f'<div class="skill"><span class="ic">{ICONS["skill"]}</span><div><b>{e(n)}</b>'
                       + (f'<div class="sd">{e(t)}</div>' if t else "") + "</div>"
                       + ("" if uses is None else f'<span class="left num{" off" if not uses else ""}">'
                          + (f"剩 {uses} 次" if uses else "已用完") + "</span>") + "</div>"
                       for n, t, uses in c["skills"])
        parts.append(_sect("技能", rows))
    if c.get("items"):
        chips = "".join(_chip(name, f"×{count}" if count else "", "item")
                        for name, _, count in (str(i).partition("×") for i in c["items"]))
        parts.append(_sect("物品", f'<div class="chips">{chips}</div>'))
    if c.get("traits"):
        parts.append(_sect("经历", '<div class="chips">' + "".join(_chip(t, icon="quill") for t in c["traits"]) + "</div>"))
    return "".join(parts), c.get("archetype") or SEGMENT_LABELS["sheet"]


def _persona_band(p: dict[str, Any]) -> str:
    """The persona a character carries: name, its line in this world, and what the hosting AI reads."""
    intro = (f'<div class="pb-intro"><span class="pb-k">在这个世界里</span>{e(p["intro"])}</div>' if p.get("intro")
             else '<div class="pb-intro pending"><span class="pb-k">在这个世界里</span>还没融入，发送 <span class="kbd">/团 人设 融入</span></div>')
    text = str(p.get("text") or "")
    return (f'<div class="pbox"><div class="pb-head"><span class="pb-tag">人设</span><b>{e(p.get("name", ""))}</b>'
            + "".join(f'<span class="chip">{e(t)}</span>' for t in (p.get("tags") or [])[:3]) + "</div>" + intro
            + (f'<div class="pb-text">{e(text if len(text) <= 120 else text[:119] + "…")}</div>' if text else "") + "</div>")


def _length_bar(chars: int, limit: int, summary: bool) -> str:
    """How much of the persona the hosting AI reads: green within the limit, the overflow marked."""
    used = min(chars, limit)
    over = max(0, chars - limit)
    width = max(chars, limit) or 1
    note = ("有摘要，AI 读摘要" if summary else f"AI 读全部 {chars} 字" if not over else f"超出 {over} 字，AI 只读前 {limit} 字")
    return (f'<div class="lenbar"><div class="lb-track"><i class="ok" style="width:{used / width * 100:.1f}%"></i>'
            + (f'<i class="over" style="width:{over / width * 100:.1f}%"></i>' if over and not summary else "")
            + f'</div><div class="lb-cap"><span>{e(note)}</span><span class="num">{chars} / {limit}</span></div></div>')


def _persona(d: dict[str, Any]) -> tuple[str, str]:
    tags = d.get("tags") or []
    parts = [f'<div class="eyebrow"><span>人设卡</span><b>{e("玩家 " + d["owner"]) if d.get("owner") else ""}</b></div>',
             _medal(d.get("name", ""), tags[0] if tags else "", "　".join(tags[1:]), d.get("avatar", ""))]
    rows = "".join(f'<div class="pf"><span class="pf-k">{e(label)}</span><div class="pf-v">{e(value if len(value) <= 260 else value[:259] + "…")}</div></div>'
                   for label, value in d.get("fields") or [])
    parts.append(_sect("设定", rows or '<div class="line" style="padding:0">还没有写内容。</div>'))
    summary = d.get("summary") or ""
    box = (f'<div class="psum"><div class="ps-k">交给 AI 的摘要' + ("<em>AI 整理</em>" if d.get("summary_by") == "ai" else "<em>自己写的</em>" if summary else "")
           + f'</div><div class="ps-v">{e(summary)}</div></div>' if summary else "")
    parts.append(_sect("主持 AI 读到的篇幅", box + _length_bar(int(d.get("chars") or 0), int(d.get("limit") or 300), bool(summary))))
    name = d.get("name", "")
    parts.append(_cmds(("修改", f"/团 人设 改 {name} 性格：……"), ("AI 摘要", f"/团 人设 摘要 {name}"), ("建卡时带上", f"/团 选职业 序号 {name}")))
    return "".join(parts), "人设卡"


def _personas(d: dict[str, Any]) -> tuple[str, str]:
    rows = d.get("rows") or []
    parts = [f'<div class="eyebrow"><span>我的人设卡</span><b class="num">{len(rows)} / {e(d.get("max", 5))}</b></div>']
    if rows:
        parts.append('<div class="plist">' + "".join(
            f'<div class="prow"><span class="ava">' + (f'<img src="{e(r["avatar"])}" alt="" />' if str(r.get("avatar", "")).startswith("data:image/")
                                                    else e(r["name"][:1])) + "</span>"
            f'<div class="pn"><b>{e(r["name"])}</b>' + "".join(f'<span class="chip">{e(t)}</span>' for t in (r.get("tags") or [])[:3])
            + f'<div class="sd">{e(r.get("text", ""))}</div></div>'
            + f'<span class="pl num{" over" if r.get("chars", 0) > 300 and not r.get("summary") else ""}">{"摘要" if r.get("summary") else str(r.get("chars", 0)) + " 字"}</span></div>'
            for r in rows) + "</div>")
    else:
        parts.append('<div class="line">还没有人设卡。人设卡是你自己的角色：名字、外貌、性格、背景和说话方式，可以带进任何一个世界。</div>')
    parts.append(_cmds(("导入酒馆角色卡", "/团 人设 导入"), ("手写", "/团 人设 新建 名字"), ("查看", "/团 人设 名字")))
    return "".join(parts), "人设卡"


def _receipt(msg: Msg, art: dict[str, Any] | None) -> tuple[str, str]:
    kind = (msg.data or {}).get("kind")
    if kind in ("people", "person", "record"):
        return {"people": _people, "person": _person, "record": _record_card}[kind](msg.data)
    parts, changes, steps = [], [], False

    def close_changes() -> None:
        if changes:
            parts.append('<div class="box"><h4>变化</h4>' + "".join(f'<div class="chg">{rich(t)}</div>' for t in changes) + "</div>")
            changes.clear()

    for block in _flat(msg):
        d, k = block.data, block.kind
        if k != "text":
            close_changes()
        if k == "title":
            parts.append(f'<div class="eyebrow"><span>玩法回执</span><b>{e(d["text"])}</b></div>'
                         f'<div class="turn"><div class="orb"><div class="r"></div><div class="f">{ICONS["quill"]}</div></div>'
                         f'<div><div class="turn-t">{rich(d.get("sub") or "")}</div><div class="turn-d">{e(d["text"])} 的行动</div></div></div>')
        elif k == "check":
            parts.append(_throw(d))
        elif k == "draw":
            parts.append(f'<div class="throw"><div class="orbit"><div class="glow"></div><div class="disc"></div><div class="shadow"></div>'
                         f'<div class="die"><span class="num">{e(d["face"])}</span></div></div>'
                         f'<div class="verdict draw"><div class="k">d20 抽取</div><div class="h">{e(d["label"])}</div></div></div>')
        elif k == "text":
            changes.append(d["text"])
        elif k == "caption" and "接下来" in str(d["text"]):
            steps = True
        elif k == "list" and steps:
            parts.append('<div class="box"><h4>接下来可以</h4>' + "".join(f'<div class="chg">{rich(i)}</div>' for i in d["items"]) + "</div>")
            steps = False
        elif k == "list":
            parts.append('<div class="recs">' + "".join(_record(i) for i in d["items"]) + "</div>")
        else:
            parts.append(_generic(block))
    close_changes()
    return "".join(parts), SEGMENT_LABELS["receipt"]


def _room(msg: Msg, art: dict[str, Any] | None) -> tuple[str, str]:
    d = msg.data or {}
    if d.get("kind") == "roster":
        return _roster(d)
    if d.get("kind") == "schedule":
        return _schedule_card(d)
    title, state = d.get("title", ""), d.get("state", "")
    if art:
        parts = [_banner(art, title, state, slim=True)]
    else:
        parts = [f'<header class="head"><div class="eyebrow-l">团桌状态 · {e(state)}</div><h2>{e(title)}</h2></header>']
    if d.get("act"):
        number, total, act_title = d["act"]
        bar = "".join(f'<i class="{"on" if i < number else ""}{" now" if i == number - 1 else ""}"></i>' for i in range(total))
        parts.append(f'<div class="acts"><div class="al"><span class="lab">{e(act_label(number))}</span><b>{e(act_title)}</b></div>'
                     + (f'<div class="segs">{bar}</div><span class="an num">{number}/{total}</span>' if total else "") + "</div>")
    metas = ([_chip(f"第 {d['round']} 轮", icon="vote")] if d.get("round") else []) + ([_chip(d["clock"], icon="moon")] if d.get("clock") else [])
    if metas:
        parts.append(f'<div class="uses">{"".join(metas)}</div>')
    boxes = "".join(f'<div class="box"><h4>{label}</h4><div class="goal">{rich(d[key])}</div></div>'
                    for key, label in (("scene", "场景"), ("goal", "目标")) if d.get(key))
    if boxes:
        parts.append(f'<div class="duo">{boxes}</div>')
    me = d.get("me")
    if d.get("party"):
        rows = "".join(_party_row(p, bool(me and p["name"] == me["name"])) for p in d["party"])
        gauges = [r for p in d["party"] for r in p.get("resources") or []]
        cols = _columns([n for n, _, _ in gauges], [_em(f"{cur}/{mx}") for _, cur, mx in gauges])
        parts.append(_sect("队伍", f'<div class="party" style="{cols}">{rows}</div>'))
    elif me:
        meters = _meters(me.get("resources") or [])
        parts.append('<section class="sect mine"><h4>我的角色</h4>' + _medal(me["name"], me.get("archetype", ""))
                     + (_vitals(meters) if meters else "") + "</section>")
    if d.get("npcs"):
        rows = "".join(f'<div class="nmini"><b>{e(n["name"])}</b>{_scale(n["standing"])}<span class="tier">{e(n["tier"])}</span></div>'
                       for n in d["npcs"])
        parts.append(_sect("人物对队伍的态度", f'<div class="nminis">{rows}</div>'))
    if d.get("table"):
        # the party table already marks whose turn it is and in which state
        lines = [t for t in d["table"] if not (d.get("party") and re.match(r"第 \d+ 轮：", str(t)))]
        if lines:
            parts.append(_sect("动态", '<ul class="items">' + "".join(f"<li>{glyphs(rich(t))}</li>" for t in lines) + "</ul>"))
    return "".join(parts), f"第 {d['round']} 轮" if d.get("round") else SEGMENT_LABELS["room"]


def _party_row(p: dict[str, Any], mine: bool) -> str:
    gauges = "".join(f'<div class="pg rc-{RESOURCE_TONES[i % len(RESOURCE_TONES)]}{" low" if _ratio(cur, mx) <= 0.4 else ""}">'
                     f'<span class="vk">{e(n)}</span>{_gauge(cur, mx, 0, i)}<span class="num">{cur}<small>/{mx}</small></span></div>'
                     for i, (n, cur, mx) in enumerate(p.get("resources") or []))
    acting = p.get("acting")
    label = "行动中" if acting in (True, "等待行动") else str(acting).replace("正文待主持人审阅", "待审阅")
    state = (f'<span class="state wait">{e(label)}</span>' if acting else '<span class="state away">暂离</span>' if p.get("away")
             else "<span></span>")
    who = " · ".join(x for x in (p.get("role"), p.get("player")) if x)
    return (f'<div class="pm{" acting" if p.get("acting") else ""}">{_avatar(p["name"])}<div class="pn"><b>{e(p["name"])}'
            + ('<em class="me-tag">我</em>' if mine else "") + f'</b><div class="sd">{e(who)}</div></div>'
            f'<div class="pgs">{gauges}</div>{state}</div>')


LAYOUTS = {"status": _status, "choices": _choices, "sheet": _sheet, "receipt": _receipt, "room": _room, "moment": _moment, "daily": _daily}


def card_html(msg: Msg, theme: str = "light", art: dict[str, Any] | None = None) -> str:
    """A full HTML page for one message; art is the resolved banner ({'image' or 'mark'/'tone', 'tag'})."""
    body, right = LAYOUTS.get(msg.segment, _narration)(msg, art)
    theme = theme if theme in THEMES else "light"
    return (f'<!doctype html><html lang="zh"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width" />'
            f"<style>{CSS}</style></head><body class=\"{theme} seg-{e(msg.segment or 'other')}\"><main class=\"card\">"
            f'<div class="content">{body}</div>{_foot(right)}</main></body></html>')


CSS = """
:root{--bg:#FBFAF7;--surface:#FFFFFF;--surface-2:#F5F2EB;--line:rgba(26,22,16,.08);--line-strong:rgba(26,22,16,.14);--text:#1A1712;--text-2:#3D372E;--muted:#6E665A;--faint:#8A8274;--gold:#81632F;--gold-ink:#6B5226;--gold-line:#CDB078;--gold-soft:rgba(205,176,120,.16);--gold-grad:linear-gradient(180deg,#EAD3A0 0%,#CDAA66 100%);--gold-solid:#DBBF85;--on-gold:#2A2012;--danger:#A2433A;--ok:#497157;--r1:#566F51;--r2:#798391;--glow:rgba(219,191,133,.45);
--die:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 128 128'%3E%3Cpath d='M64 12 64 28 22 38Z' fill='%23FBF7EE'/%3E%3Cpath d='M64 12 106 38 64 28Z' fill='%23FBF7EE'/%3E%3Cpath d='M64 28 90 78H38Z' fill='%23F4ECDC'/%3E%3Cpath d='M64 28 22 38 38 78Z' fill='%23E9DEC9'/%3E%3Cpath d='M64 28 90 78 106 38Z' fill='%23E9DEC9'/%3E%3Cpath d='M22 38 38 78 22 84Z' fill='%23DDCFB6'/%3E%3Cpath d='M106 38V84L90 78Z' fill='%23DDCFB6'/%3E%3Cpath d='M38 78H90L64 112Z' fill='%23CDBC9F'/%3E%3Cpath d='M22 84 38 78 64 112Z' fill='%23CDBC9F'/%3E%3Cpath d='M106 84 64 112 90 78Z' fill='%23CDBC9F'/%3E%3Cpath d='M64 12v16M22 38l42-10 42 10M64 28 38 78h52ZM22 38l16 40-16 6M106 38 90 78l16 6M38 78l26 34 26-34' fill='none' stroke='%2381632F' stroke-opacity='.85' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/%3E%3Cpath d='m64 12 42 26v46l-42 28-42-28V38Z' fill='none' stroke='%2381632F' stroke-width='2.2' stroke-linejoin='round'/%3E%3C/svg%3E");--serif:"Noto Serif SC","Source Han Serif SC","Songti SC","STSong","SimSun",serif;--mono:"JetBrains Mono","Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace}
body.dark{--bg:#12100C;--surface:#17150F;--surface-2:#1E1B15;--line:rgba(255,236,200,.08);--line-strong:rgba(255,236,200,.14);--text:#EDE6D8;--text-2:#CFC7B8;--muted:#9A9284;--faint:#8A8276;--gold:#D2A667;--gold-ink:#D9B079;--gold-line:#9C7440;--gold-soft:rgba(196,146,82,.11);--gold-grad:linear-gradient(180deg,#DDB073 0%,#A9793B 100%);--gold-solid:#C3955A;--on-gold:#140F08;--danger:#D98B80;--ok:#8DB595;--r1:#8FAF86;--r2:#8E98A6;--glow:rgba(195,149,90,.30);--die:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 128 128'%3E%3Cpath d='M64 12 64 28 22 38Z' fill='%23EFE6D3'/%3E%3Cpath d='M64 12 106 38 64 28Z' fill='%23EFE6D3'/%3E%3Cpath d='M64 28 90 78H38Z' fill='%23E4D8BF'/%3E%3Cpath d='M64 28 22 38 38 78Z' fill='%23D3C4A6'/%3E%3Cpath d='M64 28 90 78 106 38Z' fill='%23D3C4A6'/%3E%3Cpath d='M22 38 38 78 22 84Z' fill='%23C2B08E'/%3E%3Cpath d='M106 38V84L90 78Z' fill='%23C2B08E'/%3E%3Cpath d='M38 78H90L64 112Z' fill='%23AD9A77'/%3E%3Cpath d='M22 84 38 78 64 112Z' fill='%23AD9A77'/%3E%3Cpath d='M106 84 64 112 90 78Z' fill='%23AD9A77'/%3E%3Cpath d='M64 12v16M22 38l42-10 42 10M64 28 38 78h52ZM22 38l16 40-16 6M106 38 90 78l16 6M38 78l26 34 26-34' fill='none' stroke='%23D2A667' stroke-opacity='.85' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/%3E%3Cpath d='m64 12 42 26v46l-42 28-42-28V38Z' fill='none' stroke='%23D2A667' stroke-width='2.2' stroke-linejoin='round'/%3E%3C/svg%3E")}
html{font-size:2.5vw}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:"PingFang SC","Microsoft YaHei","Noto Sans CJK SC","Source Han Sans SC","WenQuanYi Micro Hei",sans-serif;-webkit-font-smoothing:antialiased;word-break:break-word}
body.dark{background:#0E0D0B}
/* The card fills the render viewport so a short card never leaves a strip below the footer. */
.card{position:relative;min-height:100vh;display:flex;flex-direction:column}
.content{flex:1;padding-bottom:.7rem}
body.dark .card{background:linear-gradient(180deg,#17140F 0%,#0E0D0B 100%);box-shadow:inset 0 0 0 1px rgba(210,166,103,.16)}
svg{width:.82rem;height:.82rem;flex:none}
.num{font-variant-numeric:tabular-nums}
.kbd{font-family:var(--mono);font-size:.76rem;color:var(--gold-ink);background:var(--gold-soft);padding:.12rem .5rem;border-radius:.4rem;white-space:nowrap}
b{font-weight:600}
/* banner */
.banner{position:relative;height:13.6rem;color:#F5EAD6;padding:1.5rem 1.9rem;display:flex;flex-direction:column;justify-content:flex-end;overflow:hidden;background:#1C1410}
.banner img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.banner .shade{position:absolute;inset:0;background:linear-gradient(180deg,rgba(12,9,6,.28) 0%,rgba(12,9,6,0) 34%,rgba(12,9,6,.78) 100%)}
.banner.cover{background:var(--tone-a);background-image:radial-gradient(120% 90% at 85% 10%,var(--tone-b),transparent 60%),linear-gradient(160deg,var(--tone-a),var(--tone-c))}
.banner .mark{position:absolute;right:2rem;top:50%;transform:translateY(-52%);font-family:var(--serif);font-size:10.5rem;line-height:1;font-weight:700;color:rgba(245,234,214,.13)}
.banner .tag{position:absolute;top:1.15rem;left:1.9rem;font-size:.75rem;letter-spacing:.2em;color:#E6C68A;text-shadow:0 1px 6px rgba(0,0,0,.4)}
.banner h1{position:relative;font-family:var(--serif);font-size:2.05rem;font-weight:600;letter-spacing:.06em;line-height:1.3;text-shadow:0 2px 14px rgba(0,0,0,.45)}
.banner .sub{position:relative;font-size:.82rem;color:rgba(245,234,214,.8);margin-top:.35rem}
body.dark .banner::after{content:"";position:absolute;left:0;right:0;bottom:0;height:1px;background:linear-gradient(90deg,transparent,rgba(210,166,103,.6),transparent)}
.tone-ink{--tone-a:#1B2338;--tone-b:#3E5583;--tone-c:#10151F}.tone-ember{--tone-a:#3A160D;--tone-b:#B4572A;--tone-c:#1E0B06}
.tone-neon{--tone-a:#24123D;--tone-b:#8A3C8E;--tone-c:#0F0A1C}.tone-jade{--tone-a:#10302C;--tone-b:#3B7D6E;--tone-c:#091A18}
.tone-wine{--tone-a:#3A101B;--tone-b:#94374A;--tone-c:#1C070D}.tone-slate{--tone-a:#24272C;--tone-b:#6C717A;--tone-c:#121417}
/* plain header */
.head{padding:1.5rem 2rem 0}
.head .eyebrow-l{font-size:.75rem;letter-spacing:.22em;color:var(--gold)}
.head h2{font-family:var(--serif);font-size:1.45rem;font-weight:600;letter-spacing:.04em;line-height:1.4;margin-top:.25rem}
.head::after{content:"";display:block;width:2.4rem;height:2px;border-radius:1px;background:var(--gold-grad);margin-top:.85rem}
/* narration */
.body{padding:1.4rem 2rem .3rem}
.body p{font-family:var(--serif);font-size:1.03rem;line-height:1.95;margin:0 0 .9rem;text-align:justify;color:var(--text)}
.body p.lead::first-letter{float:left;font-size:4.15rem;line-height:.98;font-weight:600;color:var(--gold);margin:.4rem .6rem 0 0}
body.dark .body p.lead::first-letter{background:linear-gradient(180deg,#EBC98C,#B5843F);-webkit-background-clip:text;background-clip:text;color:transparent}
.body p.say{padding-left:1rem;border-left:2px solid var(--gold-line);color:var(--text-2)}
.box{margin:.3rem 2rem 1.1rem;border-radius:.75rem;background:var(--gold-soft);padding:.85rem 1.1rem}
body.dark .box{box-shadow:inset 0 0 0 1px rgba(210,166,103,.14)}
.box+.box{margin-top:-.4rem}
.box h4{font-size:.74rem;letter-spacing:.2em;color:var(--gold);font-weight:500;margin-bottom:.4rem}
.box .goal{font-family:var(--serif);font-size:.95rem;line-height:1.75}
.npcs{display:grid;grid-template-columns:1fr 1fr;gap:.6rem 1rem}
.npc b{font-size:.9rem}.npc div{font-size:.78rem;color:var(--muted);line-height:1.6;margin-top:.1rem}
/* generic */
.line{font-size:.9rem;line-height:1.75;color:var(--text-2);padding:0 2rem;margin:.2rem 0 .5rem}
.pad .line{padding:0}
.pad{padding:0 1.75rem}
.lab{font-size:.74rem;letter-spacing:.14em;color:var(--muted);margin-right:.5rem}
.subhead{font-family:var(--serif);font-size:1.1rem;font-weight:600;padding:0 2rem;margin:.6rem 0 .4rem}
p.plain,p.premise{font-family:var(--serif);font-size:.98rem;line-height:1.85;color:var(--text-2);padding:0 1.75rem;margin:.2rem 0 .6rem}
blockquote{margin:.4rem 2rem;padding-left:1rem;border-left:2px solid var(--gold-line);font-family:var(--serif);color:var(--text-2);line-height:1.8}
.items{list-style:none;padding:.3rem 1.75rem .2rem}
.items li{position:relative;padding:.45rem 0 .45rem 1.1rem;font-size:.9rem;line-height:1.6;border-bottom:1px solid var(--line)}
.items li::before{content:"";position:absolute;left:.15rem;top:1rem;width:.36rem;height:.36rem;border-radius:50%;background:var(--gold-solid)}
hr{border:0;border-top:1px solid var(--line);margin:.6rem 2rem}
.foot{display:flex;justify-content:space-between;align-items:center;gap:1rem;padding:.75rem 1.75rem .85rem;border-top:1px solid var(--line);font-size:.72rem;color:var(--faint)}
.foot .seal{display:flex;align-items:center;gap:.45rem;letter-spacing:.06em}
.foot .seal img{width:1.05rem;height:1.05rem}
.foot .seal i{width:1rem;height:1rem;border-radius:50%;background:var(--gold-grad)}
/* status */
.eyebrow{display:flex;justify-content:space-between;align-items:center;padding:1.15rem 1.75rem 0;font-size:.75rem;letter-spacing:.24em;color:var(--faint)}
.eyebrow b{color:var(--gold);font-weight:500;letter-spacing:.12em}
.me{display:flex;align-items:center;gap:1.1rem;padding:1rem 1.75rem 1.1rem}
.medal{position:relative;width:5.25rem;height:5.25rem;flex:none}
.halo{position:absolute;inset:4%;border-radius:50%;background-color:var(--gold-solid);background-image:var(--gold-grad);-webkit-mask-image:radial-gradient(farthest-side,transparent calc(100% - 2.5px),#000 calc(100% - 2px));mask-image:radial-gradient(farthest-side,transparent calc(100% - 2.5px),#000 calc(100% - 2px))}
.avatar{position:absolute;inset:13%;border-radius:50%;background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--line-strong);display:flex;align-items:center;justify-content:center;font-family:var(--serif);font-size:1.6rem;font-weight:600;color:var(--gold)}
body.dark .avatar{box-shadow:inset 0 0 0 1px rgba(210,166,103,.28)}
.me-name{font-family:var(--serif);font-size:1.3rem;font-weight:600;display:flex;align-items:baseline;gap:.5rem}
.me-name small{font-family:"PingFang SC","Microsoft YaHei",sans-serif;font-size:.74rem;font-weight:400;color:var(--gold-ink);background:var(--gold-soft);padding:.06rem .55rem;border-radius:999px}
.quote{margin:0 1.75rem;padding:.1rem 0 .1rem 1rem;border-left:2px solid var(--gold-line)}
.quote .who{font-size:.74rem;letter-spacing:.12em;color:var(--gold)}
.quote .t{font-family:var(--serif);font-size:.97rem;line-height:1.8;color:var(--text-2);margin-top:.1rem}
.throw{display:grid;grid-template-columns:9.4rem 1fr;align-items:center;gap:1.3rem;padding:1.1rem 1.75rem .4rem}
.orbit{position:relative;width:9.4rem;height:9.4rem;display:flex;align-items:center;justify-content:center}
.orbit .glow{position:absolute;inset:0;border-radius:50%;background:radial-gradient(circle,var(--glow) 0%,transparent 66%)}
.orbit .disc{position:absolute;inset:.6rem;border-radius:50%;background:radial-gradient(circle,var(--gold-soft) 0%,transparent 70%);box-shadow:inset 0 0 0 1px var(--gold-soft)}
.orbit .shadow{position:absolute;left:24%;bottom:11%;width:52%;height:.6rem;border-radius:50%;background:radial-gradient(closest-side,rgba(40,26,8,.28),transparent)}
body.dark .orbit .shadow{background:radial-gradient(closest-side,rgba(0,0,0,.6),transparent)}
.die{position:relative;width:7.25rem;height:7.25rem;background-image:var(--die);background-size:contain;background-repeat:no-repeat;background-position:center;filter:drop-shadow(0 .6rem 1.1rem rgba(60,40,14,.22));display:flex;align-items:center;justify-content:center}
body.dark .die{filter:drop-shadow(0 .7rem 1.3rem rgba(0,0,0,.5))}
.die span{position:relative;top:-.2rem;font-family:var(--serif);font-size:2rem;font-weight:700;color:#2A2014;text-shadow:0 1px 0 rgba(255,252,244,.7)}
.verdict .k{font-size:.75rem;letter-spacing:.22em;color:var(--faint)}
.verdict .h{font-family:var(--serif);font-size:1.9rem;font-weight:600;letter-spacing:.08em;line-height:1.35;color:var(--ok)}
.verdict.bad .h{color:var(--danger)}
.terms{display:flex;flex-wrap:wrap;align-items:center;gap:.38rem;margin-top:.5rem}
.term{display:flex;flex-direction:column;align-items:center;min-width:3.1rem;padding:.25rem .6rem .3rem;border-radius:.6rem;background:var(--gold-soft)}
.term .tk{font-size:.7rem;letter-spacing:.12em;color:var(--muted)}
.term .tv{font-family:var(--mono);font-size:1rem;font-weight:500;line-height:1.2}
.term.total .tv{color:var(--gold-ink);font-weight:700}
.term.vs{background:transparent;box-shadow:inset 0 0 0 1px var(--line-strong)}
.op{font-family:var(--mono);font-size:.75rem;color:var(--faint)}
.vitals{margin:.7rem 1.75rem 0;padding:.9rem 0 .3rem;border-top:1px solid var(--line);display:grid;grid-template-columns:1fr 1fr;gap:.65rem 1.75rem}
.vital{display:grid;grid-template-columns:var(--gk,auto) minmax(0,1fr) var(--gv,auto);align-items:center;gap:.6rem;font-size:.78rem}
.vital .vk{color:var(--muted);white-space:nowrap}
.vital .vv{text-align:right;white-space:nowrap}
.track{position:relative;height:3px;border-radius:2px;background:var(--line-strong);overflow:hidden}.track i{display:block;height:100%;border-radius:2px;background:var(--gold)}
.rc-hp{--rc:#B9533E;--rc2:#DE8B6E}.rc-mp{--rc:#3F6797;--rc2:#7FA0C9}.rc-sp{--rc:#3F7A5E;--rc2:#82B394}.rc-xp{--rc:#74559E;--rc2:#A98FCB}
body.dark .rc-hp{--rc:#D8735B;--rc2:#F0A88E}body.dark .rc-mp{--rc:#6C93C6;--rc2:#A9C3E4}body.dark .rc-sp{--rc:#6FA787;--rc2:#A8D1B6}body.dark .rc-xp{--rc:#A086C7;--rc2:#CDB9E6}
.res{position:relative;height:.5rem;border-radius:.25rem;background:var(--line-strong);overflow:hidden;min-width:0}
.res i{display:block;height:100%;border-radius:.25rem;background:linear-gradient(90deg,var(--rc),var(--rc2))}
.res b{position:absolute;top:0;bottom:0}
.res b.lost{background:repeating-linear-gradient(135deg,var(--rc) 0 2px,transparent 2px 5px);opacity:.55}
.res b.gain{background:rgba(255,255,255,.42);box-shadow:inset 0 0 0 1px rgba(255,255,255,.6)}
.vital .vk,.pg .vk{display:inline-flex;align-items:center;gap:.35rem}
.vital .vk::before,.pg .vk::before{content:"";width:.45rem;height:.45rem;border-radius:50%;background:var(--rc)}
.vital .vv{font-weight:600}.vital .vv small{font-weight:400;color:var(--muted);font-size:.74rem}
.vital.low .vv{color:var(--danger)}
.delta{font-family:var(--mono);font-size:.7rem;font-weight:600;margin-right:.4rem;padding:.02rem .35rem;border-radius:.3rem;box-shadow:inset 0 0 0 1px currentColor}.delta.down{color:var(--danger)}.delta.up{color:var(--ok)}
.uses,.preps{display:flex;flex-wrap:wrap;align-items:center;gap:.4rem;margin:.9rem 1.75rem 0}
.chip{display:inline-flex;align-items:center;gap:.32rem;font-size:.78rem;padding:.2rem .65rem;border-radius:999px;background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--line);color:var(--text-2)}
body.dark .chip{box-shadow:inset 0 0 0 1px rgba(210,166,103,.16)}
.chip svg{color:var(--gold)}
.chip em{font-style:normal;color:var(--faint);font-size:.72rem}
.chip.off{opacity:.7;color:var(--faint)}
/* choices */
.turn{display:flex;align-items:center;gap:.9rem;margin:1.05rem 1.5rem .4rem;padding:.8rem 1rem;border-radius:.75rem;background:var(--gold-soft)}
body.dark .turn{box-shadow:inset 0 0 0 1px rgba(210,166,103,.14)}
.orb{position:relative;width:2.5rem;height:2.5rem;flex:none}
.orb .r{position:absolute;inset:-.3rem;border-radius:50%;background:var(--gold-line);-webkit-mask-image:radial-gradient(farthest-side,transparent calc(100% - 2.5px),#000 calc(100% - 2px));mask-image:radial-gradient(farthest-side,transparent calc(100% - 2.5px),#000 calc(100% - 2px))}
.orb .f{position:absolute;inset:0;border-radius:50%;background-color:var(--gold-solid);background-image:var(--gold-grad);color:var(--on-gold);display:flex;align-items:center;justify-content:center;box-shadow:inset 0 1px 0 rgba(255,255,255,.35)}
.orb .f svg{width:1rem;height:1rem}
.turn-t{font-size:.95rem;line-height:1.55}.turn-t b{color:var(--gold-ink)}
.turn-d{font-size:.75rem;color:var(--muted);line-height:1.6}
.clock{margin-left:auto;font-family:var(--mono);font-size:.8rem;color:var(--gold-ink);background:var(--bg);padding:.2rem .65rem;border-radius:999px;box-shadow:inset 0 0 0 1px var(--gold-line);white-space:nowrap}
body.dark .clock{background:#0F0E0C}
.fates{margin:.6rem 1.5rem 0;border-top:1px solid var(--line)}
.fate{display:grid;grid-template-columns:1.9rem minmax(0,1fr) auto;align-items:center;gap:.9rem;padding:.95rem .5rem .95rem .35rem;border-bottom:1px solid var(--line)}
.fate .key{font-family:var(--mono);font-size:.82rem;font-weight:600;color:var(--gold)}
.fate .title{font-family:var(--serif);font-size:1.1rem;font-weight:500;line-height:1.45}
.fate .sub{font-size:.75rem;line-height:1.5;color:var(--faint);margin-top:.2rem}
.fate .sub .cost{color:var(--danger)}
.odds{display:flex;flex-direction:column;align-items:flex-end;gap:.2rem;color:var(--gold);min-width:3.2rem}
.odds svg{width:1rem;height:1rem}
.odds .v{font-family:var(--serif);font-size:1.15rem;font-weight:600;line-height:1;color:var(--text-2)}
.odds .k{font-size:.72rem;letter-spacing:.06em;color:var(--faint)}
.pie{--tc:var(--gold-solid);position:relative;width:2.9rem;height:2.9rem;border-radius:50%;background:conic-gradient(var(--tc) calc(var(--p)*360deg),var(--line-strong) 0);display:flex;align-items:center;justify-content:center}
.pie::before{content:"";position:absolute;inset:.22rem;border-radius:50%;background:var(--bg)}
body.dark .pie::before{background:#141210}
.pie b{position:relative;font-family:var(--serif);font-size:.95rem;font-weight:700;color:var(--tc)}
.pie b small{font-size:.6rem;font-weight:500;margin-left:.04rem}
.pie.hi{--tc:var(--ok)}.pie.lo{--tc:var(--danger)}.pie.mid b{color:var(--gold-ink)}
.odds.chance{align-items:center;min-width:4.4rem;gap:.3rem}
.odds.chance.hi .pie{--tc:var(--ok)}.odds.chance.lo .pie{--tc:var(--danger)}.odds.chance.mid .pie b{color:var(--gold-ink)}
.fates-note{margin:.55rem 1.85rem 0;font-size:.72rem;color:var(--faint);letter-spacing:.04em}
.turnout{margin-left:auto;display:flex;align-items:center;gap:.7rem}
.turnout span{font-size:.74rem;color:var(--muted);white-space:nowrap}
.turnout .pie{width:3.1rem;height:3.1rem}
.turnout .pie::before{background:var(--bg)}
.vtags{display:flex;flex-wrap:wrap;gap:.35rem;margin-top:.4rem}
.vt{font-size:.72rem;padding:.1rem .55rem;border-radius:.35rem;background:var(--surface-2);color:var(--text-2);box-shadow:inset 0 0 0 1px var(--line)}
.vt.risk{color:var(--danger);box-shadow:inset 0 0 0 1px var(--danger);background:transparent}
.preps .lab{margin-right:.2rem}
.hint{margin:.9rem 1.5rem 0;padding:.8rem 0 .3rem;border-top:1px solid var(--line);font-size:.76rem;color:var(--muted);line-height:1.7}
.uses+.hint,.preps+.hint{margin-top:1rem}
.hint .note{margin-bottom:.55rem}
.cmds{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem 1.15rem}
.cmd{display:inline-flex;align-items:center;gap:.45rem;white-space:nowrap}
.cmd .ck{font-size:.74rem;color:var(--faint)}
/* character sheet, play receipt, room status */
.me-line{font-size:.8rem;color:var(--muted);margin-top:.3rem;line-height:1.55}
.stats{display:grid;gap:.5rem;margin:.1rem 1.75rem 0}
.stat{display:flex;flex-direction:column;align-items:center;padding:.55rem .3rem .5rem;border-radius:.7rem;background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--line)}
body.dark .stat{box-shadow:inset 0 0 0 1px rgba(210,166,103,.14)}
.stat .sk{font-size:.72rem;letter-spacing:.14em;color:var(--muted)}
.stat .sv{font-family:var(--serif);font-size:1.55rem;font-weight:600;line-height:1.3}
.stat .sm{font-family:var(--mono);font-size:.7rem;color:var(--faint)}
.stat.up{background:var(--gold-soft)}.stat.up .sv{color:var(--gold-ink)}.stat.up .sm{color:var(--gold)}
.stat.down .sm{color:var(--danger)}
.sect{margin:1rem 1.75rem 0;padding-top:.85rem;border-top:1px solid var(--line)}
.sect h4{font-size:.74rem;letter-spacing:.2em;color:var(--gold);font-weight:500;margin-bottom:.55rem}
.sect .items{padding:0}
.sect .me{padding:.1rem 0 0}
.sect .vitals{margin:.6rem 0 0}
.skill{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:start;gap:.7rem;padding:.55rem 0;border-bottom:1px solid var(--line)}
.skill:last-child{border-bottom:0}
.skill .ic{width:1.7rem;height:1.7rem;border-radius:50%;background:var(--gold-soft);color:var(--gold);display:flex;align-items:center;justify-content:center}
.skill b{font-size:.92rem;line-height:1.7}
.skill .sd{font-size:.78rem;color:var(--muted);line-height:1.6}
.left{font-size:.72rem;color:var(--gold-ink);background:var(--gold-soft);padding:.12rem .55rem;border-radius:999px;white-space:nowrap;margin-top:.2rem}
.left.off{color:var(--faint);background:transparent;box-shadow:inset 0 0 0 1px var(--line-strong)}
.chips{display:flex;flex-wrap:wrap;gap:.4rem}
.recs{margin:.8rem 1.5rem 0;border-top:1px solid var(--line)}
.rec{display:grid;grid-template-columns:2.6rem minmax(0,1fr) auto;align-items:center;gap:.7rem;padding:.75rem .35rem;border-bottom:1px solid var(--line)}
.rec .no{font-family:var(--mono);font-size:.82rem;font-weight:600;color:var(--gold)}
.rec .rk{font-size:.7rem;letter-spacing:.14em;color:var(--faint)}
.rec .rt{font-family:var(--serif);font-size:1.02rem;line-height:1.5}
.rec .rv{font-size:.74rem;color:var(--muted)}
.rs{font-size:.72rem;color:var(--gold-ink);padding:.12rem .55rem;border-radius:999px;box-shadow:inset 0 0 0 1px var(--gold-line);white-space:nowrap}
.chg{font-size:.88rem;line-height:1.8;color:var(--text-2)}
.verdict.draw .h{color:var(--gold-ink)}
.banner.slim{height:8.4rem;padding:1.1rem 1.75rem}
.banner.slim h1{font-size:1.6rem}
.banner.slim .mark{font-size:7rem}
.banner.slim .tag{left:1.75rem}
.acts{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:.9rem;margin:1.1rem 1.75rem .1rem}
.acts .al b{font-family:var(--serif);font-size:1.05rem;font-weight:600}
.segs{display:flex;gap:.3rem}
.segs i{flex:1;height:.32rem;border-radius:.2rem;background:var(--line-strong)}
.segs i.on{background:var(--gold-solid)}
.segs i.now{background-image:var(--gold-grad);box-shadow:0 0 .5rem var(--glow)}
.an{font-family:var(--mono);font-size:.78rem;color:var(--faint)}
.duo{display:grid;grid-template-columns:1fr 1fr;gap:.6rem;margin:.9rem 1.75rem 0}
.duo .box,.duo .box+.box{margin:0}
/* moments, loadout, roster, people, record detail */
.head-sub{font-size:.8rem;color:var(--muted);margin-top:.2rem}
.glyph{display:inline-flex;gap:.16rem;vertical-align:middle;margin:0 .25rem}
.glyph i{width:.62rem;height:.32rem;border-radius:.12rem;background:var(--line-strong)}
.glyph i.on{background:var(--gold-solid)}
.seats{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin:.6rem 1.75rem 0;padding:.85rem 1.1rem;border-radius:.75rem;background:var(--gold-soft)}
body.dark .seats{box-shadow:inset 0 0 0 1px rgba(210,166,103,.14)}
.seats b{font-family:var(--serif);font-size:1.35rem;font-weight:600;margin-right:.6rem}
.seats .sm{font-size:.75rem;color:var(--muted)}
.dots{display:flex;gap:.4rem}
.dots i{width:1rem;height:1rem;border-radius:50%;box-shadow:inset 0 0 0 1.5px var(--gold-line)}
.dots i.on{background-image:var(--gold-grad);box-shadow:none}
.bars{margin:.7rem 1.75rem 0;display:grid;gap:.75rem}
.bar{display:grid;grid-template-columns:var(--bk,minmax(4rem,auto)) minmax(0,1fr) var(--bn,auto);align-items:center;gap:.8rem;font-size:.88rem}
.bar .bk{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar .bn{text-align:right;white-space:nowrap}
.bar .track{height:.55rem;border-radius:.3rem}
.bar .track i{border-radius:.3rem;background:var(--line-strong)}
.bar.win .track i{background-image:var(--gold-grad)}
.bar.win .bk{color:var(--gold-ink);font-weight:600}
.bn{font-family:var(--mono);font-size:.8rem;color:var(--muted)}
.ava{flex:none;width:2.3rem;height:2.3rem;border-radius:50%;background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--gold-line);display:flex;align-items:center;justify-content:center;font-family:var(--serif);font-size:1rem;font-weight:600;color:var(--gold)}
.epis{margin:1rem 1.75rem 0;display:grid;gap:.95rem}
.epi{display:flex;gap:.85rem;align-items:flex-start}
.epi b{font-size:.92rem}
.epi p{font-family:var(--serif);font-size:.98rem;line-height:1.85;color:var(--text-2);margin-top:.15rem}
.why{font-size:.74rem;color:var(--danger);margin-top:.15rem}
.skill.off b{color:var(--faint)}
.skill .kbd{font-size:.7rem}
.seat-list{margin:.8rem 1.75rem 0;border-top:1px solid var(--line)}
.seat{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:.8rem;padding:.7rem .2rem;border-bottom:1px solid var(--line)}
.seat b{font-size:.95rem}
.state{font-size:.72rem;padding:.12rem .6rem;border-radius:999px;box-shadow:inset 0 0 0 1px currentColor;white-space:nowrap}
.state.ok{color:var(--ok)}.state.away{color:var(--faint)}.state.wait{color:var(--gold-ink)}
.npc-list{margin:.8rem 1.75rem 0;border-top:1px solid var(--line)}
.npc-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:.8rem;padding:.75rem .2rem;border-bottom:1px solid var(--line)}
.npc-row b{font-size:.95rem}
.npc-row .sc{display:flex;flex-direction:column;align-items:flex-end;gap:.3rem}
.tier{font-size:.74rem;color:var(--gold-ink)}
.scale{display:grid;grid-template-columns:repeat(7,1fr);gap:.22rem;min-width:9.5rem}
.scale i{height:.5rem;border-radius:.2rem;background:var(--line-strong)}
.scale i.mid{background:var(--line-strong);opacity:.8}
.scale i.pos.on{background:var(--gold-solid)}
.scale i.neg.on{background:var(--danger);opacity:.75}
.scale i.now{box-shadow:0 0 0 2px var(--bg),0 0 0 3.5px var(--gold);background-image:var(--gold-grad)}
.scale i.neg.now{background:var(--danger);box-shadow:0 0 0 2px var(--bg),0 0 0 3.5px var(--danger)}
.sect .scale{min-width:0}
.sect .scale i{height:.65rem}
.scale-k{display:grid;grid-template-columns:repeat(7,1fr);gap:.22rem;margin-top:.45rem;font-size:.7rem;color:var(--faint);text-align:center}
.scale-k .now{color:var(--gold-ink);font-weight:600}
.memo{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:.6rem;align-items:baseline;padding:.4rem 0;font-size:.85rem;border-bottom:1px solid var(--line)}
.memo:last-child{border-bottom:0}
.memo span{color:var(--text-2);line-height:1.6}
.memo em{font-style:normal;font-family:var(--mono);font-size:.74rem}.memo em.up{color:var(--ok)}.memo em.down{color:var(--danger)}
blockquote.rq{margin:.8rem 1.75rem 0}
/* today's roll */
.t-dawn{--tc:var(--gold-ink)}.t-fair{--tc:var(--ok)}.t-calm{--tc:var(--text-2)}.t-cloud{--tc:var(--r2)}.t-gale{--tc:var(--danger)}
.omen{display:grid;grid-template-columns:9.4rem 1fr;align-items:center;gap:1.3rem;padding:1.1rem 1.75rem .2rem}
.omen .who{font-size:.75rem;letter-spacing:.22em;color:var(--faint)}
.omen .fortune{font-family:var(--serif);font-size:2.7rem;font-weight:600;letter-spacing:.18em;line-height:1.3;color:var(--tc)}
.omen .omen-s{font-size:.76rem;color:var(--muted)}
.omen.crit .orbit .glow{background:radial-gradient(circle,var(--glow) 0%,transparent 72%);transform:scale(1.12)}
.omen.t-gale.crit .orbit .glow{background:radial-gradient(circle,rgba(162,67,58,.32) 0%,transparent 70%)}
.ladder{display:grid;grid-template-columns:repeat(5,1fr);gap:.35rem;margin:.8rem 1.75rem 0}
.rung{display:flex;flex-direction:column;align-items:center;gap:.25rem}
.rung i{width:100%;height:.36rem;border-radius:.2rem;background:var(--line-strong)}
.rung b{font-size:.76rem;font-weight:500;color:var(--faint);letter-spacing:.12em}
.rung span{font-size:.66rem;color:var(--faint)}
.rung.now i{background:var(--tc);box-shadow:0 0 .5rem var(--glow)}
.rung.now.t-dawn i{background-image:var(--gold-grad)}
.rung.now b{color:var(--tc);font-weight:700}
.crit-line{margin:1rem 1.75rem 0;padding:.75rem 1.1rem;border-radius:.75rem;background:var(--gold-soft);font-family:var(--serif);font-size:1rem;letter-spacing:.06em;color:var(--tc);text-align:center}
body.dark .crit-line{box-shadow:inset 0 0 0 1px rgba(210,166,103,.2)}
.signs{display:grid;grid-template-columns:1fr 1fr;margin:1.2rem 1.75rem 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.sign{display:flex;gap:1rem;padding:1.1rem .2rem 1.05rem}
.sign+.sign{border-left:1px solid var(--line);padding-left:1.2rem}
.stamp{flex:none;width:2.6rem;height:2.6rem;border-radius:.45rem;display:flex;align-items:center;justify-content:center;font-family:var(--serif);font-size:1.45rem;font-weight:700}
.yi .stamp{background-color:var(--gold-solid);background-image:var(--gold-grad);color:var(--on-gold);box-shadow:inset 0 1px 0 rgba(255,255,255,.35)}
.ji .stamp{color:var(--danger);box-shadow:inset 0 0 0 2px var(--danger)}
.sign ul{list-style:none;display:grid;gap:.75rem;min-width:0}
.sign li b{display:block;font-family:var(--serif);font-size:1.5rem;font-weight:600;letter-spacing:.14em;line-height:1.3}
.yi li b{color:var(--gold-ink)}.ji li b{color:var(--text)}
.sign li span{display:block;font-size:.78rem;line-height:1.6;color:var(--muted)}
.omen-note{margin:.75rem 1.75rem 0;font-size:.72rem;letter-spacing:.14em;color:var(--faint);text-align:center}
/* group pastimes */
.sum-ring{width:9.4rem;height:9.4rem;border-radius:50%;display:flex;flex-direction:column;align-items:center;justify-content:center;background:radial-gradient(circle,var(--gold-soft) 0%,transparent 70%);box-shadow:inset 0 0 0 2px var(--gold-line)}
.sum-ring b{font-family:var(--serif);font-size:3rem;font-weight:700;line-height:1.1;color:var(--gold-ink)}
.sum-ring span{font-size:.72rem;letter-spacing:.2em;color:var(--faint)}
.omen.roll .expr{font-family:var(--mono);font-size:1.5rem;font-weight:600;color:var(--text);margin:.15rem 0 .2rem}
.omen.roll .nat{color:var(--gold-ink);font-weight:600;letter-spacing:.12em}
.omen.roll.fumble .nat{color:var(--danger)}
.omen.roll.crit .orbit .glow{transform:scale(1.12)}
.tiles{display:flex;flex-wrap:wrap;align-items:center;gap:.35rem;margin-top:.55rem}
.group{display:inline-flex;align-items:center;gap:.3rem;padding:.2rem .3rem .2rem .55rem;border-radius:.6rem;background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--line)}
.group .gl{font-family:var(--mono);font-size:.7rem;color:var(--faint)}
.gt{display:inline-flex;flex-wrap:wrap;gap:.22rem}
.tile{min-width:1.75rem;height:1.75rem;padding:0 .3rem;border-radius:.4rem;display:inline-flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:.86rem;font-weight:600;background:var(--gold-soft);color:var(--gold-ink)}
.tile.hi{background-image:var(--gold-grad);color:var(--on-gold)}
.tile.drop{background:transparent;color:var(--faint);text-decoration:line-through;box-shadow:inset 0 0 0 1px var(--line-strong)}
.tile.flat{background:transparent;color:var(--text-2);box-shadow:inset 0 0 0 1px var(--line-strong)}
.duel{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:.6rem;margin:1rem 1.75rem 0}
.duelist{display:flex;flex-direction:column;align-items:center;gap:.45rem;padding:1rem .5rem .8rem;border-radius:.9rem;background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--line)}
.duelist b{font-size:1rem}
.duelist .die{width:5.6rem;height:5.6rem}.duelist .die span{font-size:1.6rem}
.duelist.win{background:var(--gold-soft);box-shadow:inset 0 0 0 1.5px var(--gold-line),0 0 1.4rem var(--glow)}
.duelist:not(.win) .die{opacity:.6;filter:grayscale(.5)}
.crown{height:1.6rem;min-width:1.6rem;font-family:var(--serif);font-size:1rem;font-weight:700;color:var(--gold-ink)}
.duelist.win .crown{padding:0 .5rem;border-radius:.4rem;background-image:var(--gold-grad);color:var(--on-gold);display:flex;align-items:center}
.vs{font-family:var(--serif);font-size:1.4rem;font-weight:700;letter-spacing:.1em;color:var(--faint)}
.relay{padding:1.2rem 2rem .4rem;font-family:var(--serif);font-size:1.03rem;line-height:2.05;text-align:justify}
.relay .ln sup{font-family:"PingFang SC","Microsoft YaHei",sans-serif;font-size:.62rem;color:var(--gold);margin:0 .3rem 0 .1rem;letter-spacing:.04em}
.ending-box{border-left:3px solid var(--gold-line)}
.rstats{display:grid;grid-template-columns:repeat(4,1fr);gap:.5rem;margin:1rem 1.75rem 0}
.rs-cell{display:flex;flex-direction:column;align-items:center;padding:.7rem .3rem .55rem;border-radius:.7rem;background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--line)}
.rs-cell b{font-family:var(--serif);font-size:1.7rem;font-weight:600;line-height:1.2}
.rs-cell span{font-size:.72rem;letter-spacing:.14em;color:var(--muted)}
.rs-cell.up b{color:var(--gold-ink)}.rs-cell.down b{color:var(--danger)}
.outs{margin:.75rem 1.75rem 0}
.obar{display:flex;gap:2px;height:.6rem;border-radius:.3rem;overflow:hidden}
.obar i{min-width:.3rem}
.obar i.crit,.olegend .crit i{background-color:var(--gold-solid);background-image:var(--gold-grad)}
.obar i.ok,.olegend .ok i{background:var(--ok)}
.obar i.fail,.olegend .fail i{background:var(--faint);opacity:.55}
.obar i.fum,.olegend .fum i{background:var(--danger)}
.olegend{display:flex;flex-wrap:wrap;gap:.4rem 1.2rem;margin-top:.55rem;font-size:.75rem;color:var(--muted)}
.olegend span{display:inline-flex;align-items:center;gap:.35rem}
.olegend i{width:.55rem;height:.55rem;border-radius:.15rem}
.olegend b{color:var(--text-2);font-weight:600}
.olegend em{font-style:normal;color:var(--faint);font-size:.7rem}
.castm .cm{flex:1;min-width:0}
.cbar{display:grid;grid-template-columns:minmax(0,1fr);gap:.25rem;margin-top:.35rem}
.cbar .track{height:.32rem;border-radius:.2rem}
.cbar .track i{background:var(--ok);border-radius:.2rem}
.cbar span{font-size:.7rem;color:var(--faint)}
.mvp.hero{margin:.9rem 1.75rem 0;padding:.75rem 1rem;border-radius:.75rem;background:var(--gold-soft)}
.journey{position:relative}
.jn{position:relative;display:grid;grid-template-columns:1.7rem 1fr;gap:.8rem;align-items:start;padding:.3rem 0 .55rem}
.jn::before{content:"";position:absolute;left:.85rem;top:1.9rem;bottom:-.3rem;width:1px;background:var(--gold-line)}
.jn.end::before{display:none}
.jn b{font-family:var(--serif);font-size:.98rem;font-weight:600;line-height:1.7rem}
.jn .sd{font-size:.74rem;color:var(--muted)}
.jd{position:relative;z-index:1;width:1.7rem;height:1.7rem;border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:var(--serif);font-size:.8rem;color:var(--gold);background:var(--bg);box-shadow:inset 0 0 0 1px var(--gold-line)}
.jn.end .jd{background-color:var(--gold-solid);background-image:var(--gold-grad);color:var(--on-gold);box-shadow:0 0 .6rem var(--glow)}
.jn.end b{color:var(--gold-ink)}
.sect .epis{margin:.2rem 0 0}
.party{display:grid;border-top:1px solid var(--line)}
.pm{display:grid;grid-template-columns:auto 8.5rem minmax(0,1fr) 3.6rem;align-items:center;gap:.85rem;padding:.65rem .5rem;border-bottom:1px solid var(--line)}
.pm.acting{background:var(--gold-soft);border-radius:.6rem;border-bottom-color:transparent}
.pm.acting .ava{background-color:var(--gold-solid);background-image:var(--gold-grad);color:var(--on-gold);box-shadow:0 0 .55rem var(--glow)}
.pn b{font-size:.95rem;display:flex;align-items:center;gap:.35rem}
.pn .sd{font-size:.72rem;color:var(--muted)}
.me-tag{font-style:normal;font-size:.62rem;font-weight:500;padding:.02rem .35rem;border-radius:.3rem;color:var(--gold-ink);box-shadow:inset 0 0 0 1px var(--gold-line)}
.pgs{display:grid;gap:.35rem}
.pg{display:grid;grid-template-columns:var(--gk,2.4rem) minmax(0,1fr) var(--gv,2.6rem);align-items:center;gap:.5rem;font-size:.72rem}
.pg .vk{color:var(--muted);white-space:nowrap}
.pg .num{text-align:right;font-weight:600;color:var(--text-2)}
.pg .num small{font-weight:400;color:var(--faint)}
.pg .res{height:.4rem}
.pg.low .num{color:var(--danger)}
.pm .state{justify-self:end}
.nminis{display:grid;grid-template-columns:1fr 1fr;gap:.55rem 1.4rem}
.nmini{display:grid;grid-template-columns:minmax(0,1fr) 6.6rem 2.4rem;align-items:center;gap:.6rem;font-size:.82rem}
.nmini b{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nmini .scale{min-width:0}
.nmini .scale i{height:.42rem}
.nmini .tier{text-align:right}
.cts{display:flex;flex-wrap:wrap;gap:.3rem;margin-top:.3rem}
.ct{font-size:.7rem;padding:.06rem .45rem;border-radius:.3rem;color:var(--text-2);background:var(--surface-2)}
.ct b,.npc-row .ct b{font-family:var(--mono);font-size:.72rem;font-weight:600}
.ct.up b{color:var(--ok)}.ct.down b{color:var(--danger)}
.cast{display:grid;grid-template-columns:1fr 1fr;gap:.7rem 1rem}
.castm{display:flex;align-items:center;gap:.7rem}
.castm b{font-size:.95rem}
.castm .sd,.mvp .sd{font-size:.74rem;color:var(--muted)}
.mvp{display:flex;align-items:center;gap:.85rem;padding:.2rem 0 .6rem}
.mvp .stamp{background-color:var(--gold-solid);background-image:var(--gold-grad);color:var(--on-gold)}
.mvp b{font-family:var(--serif);font-size:1.15rem}
.memo em{font-style:normal;font-size:.8rem;color:var(--gold-ink)}
.slots{margin:.8rem 1.75rem 0;border-top:1px solid var(--line)}
.slot{display:grid;grid-template-columns:1.8rem minmax(0,1fr) auto auto;align-items:center;gap:.8rem;padding:.75rem .5rem;border-bottom:1px solid var(--line)}
.slot.on{background:var(--gold-soft);border-radius:.6rem;border-bottom-color:transparent}
.slot .no{width:1.6rem;height:1.6rem;border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:.78rem;color:var(--gold);box-shadow:inset 0 0 0 1px var(--gold-line)}
.slot.on .no{background-image:var(--gold-grad);color:var(--on-gold);box-shadow:none}
.slot .sl b{font-family:var(--serif);font-size:1.05rem;font-weight:600}
.slot .track{height:.4rem;border-radius:.2rem;margin:.35rem 0 .25rem}
.slot .track i{border-radius:.2rem;background-image:var(--gold-grad)}
.slot .sd{font-size:.74rem;color:var(--muted)}
.slot .cnt{font-family:var(--mono);font-size:.8rem;color:var(--text-2)}
.act-best{margin:.9rem 1.75rem 0}

.spread{display:grid;grid-template-columns:1.3fr repeat(5,1fr);gap:.4rem;margin:.9rem 1.75rem 0;padding:.8rem 1rem;border-radius:.75rem;background:var(--gold-soft)}
body.dark .spread{box-shadow:inset 0 0 0 1px rgba(210,166,103,.14)}
.spread .sum,.tally{display:flex;flex-direction:column;align-items:center;justify-content:center}
.spread .sum{border-right:1px solid var(--line-strong);align-items:flex-start;padding-left:.2rem}
.spread .sum b{font-family:var(--serif);font-size:1.7rem;font-weight:600;line-height:1.2;color:var(--gold-ink)}
.spread span{font-size:.72rem;color:var(--muted);letter-spacing:.12em}
.tally b{font-family:var(--serif);font-size:1.25rem;font-weight:600;line-height:1.3;color:var(--faint)}
.tally.on b{color:var(--tc)}
.ranks{margin:.8rem 1.75rem 0;border-top:1px solid var(--line)}
.rank{display:grid;grid-template-columns:1.6rem auto minmax(0,1fr) auto 3.6rem;align-items:center;gap:.8rem;padding:.6rem .5rem;border-bottom:1px solid var(--line)}
.rank.top{background:var(--gold-soft);border-radius:.6rem;border-bottom-color:transparent}
.rank .no{font-family:var(--mono);font-size:.8rem;color:var(--faint);text-align:center}
.rank.top .no{color:var(--gold)}
.rank .rn b{font-size:.95rem}
.rf{font-size:.74rem;padding:.1rem .6rem;border-radius:999px;color:var(--tc);box-shadow:inset 0 0 0 1px currentColor;white-space:nowrap}
.rank .face{font-family:var(--serif);font-size:1.45rem;font-weight:700;text-align:right;color:var(--tc);white-space:nowrap}
.rank .sd,.honor .sd,.qrow .sd,.mvp .sd{font-size:.72rem;color:var(--muted)}
/* luck */
.sum-ring.luck{box-shadow:inset 0 0 0 2px var(--tc)}
.sum-ring.luck b{color:var(--tc);font-size:2.6rem}
.sum-ring span{font-size:.72rem;letter-spacing:.18em;color:var(--muted)}
.hist-wrap{margin:1.1rem 1.75rem 0;padding:1rem 1rem .6rem;border-radius:.9rem;background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--line)}
.hist{position:relative;height:9.5rem;display:grid;grid-template-columns:repeat(20,1fr);gap:.22rem;align-items:end}
.hc{position:relative;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center}
.hc i{display:block;width:100%;border-radius:.22rem .22rem .08rem .08rem;background:var(--line-strong);min-height:0;max-height:calc(100% - 2.4rem)}
.hc.up i{background:var(--gold-line)}
.hc.crit i{background-image:var(--gold-grad);box-shadow:0 0 .6rem var(--glow)}
.hc.fumble i{background:var(--danger);opacity:.8}
.hc em{font-style:normal;font-size:.58rem;color:var(--faint);margin-bottom:.15rem;height:.8rem}
.hc span{height:1.1rem;margin-top:.3rem;font-size:.66rem;color:var(--muted)}
.hc.crit span,.hc.crit em{color:var(--gold-ink);font-weight:600}.hc.fumble span,.hc.fumble em{color:var(--danger);font-weight:600}
.hist-exp{position:absolute;left:0;right:0;border-top:1px dashed var(--gold-line);pointer-events:none}
.board-h{display:flex;align-items:baseline;gap:.7rem;margin:1.15rem 1.75rem 0}
.board-h span{font-family:var(--serif);font-size:1.05rem;font-weight:600;letter-spacing:.12em;color:var(--gold-ink)}
.board-h.low span{color:var(--danger)}
.board-h em{font-style:normal;font-size:.72rem;color:var(--faint)}
.board-h+.ranks{margin-top:.45rem}
.honors{display:grid;grid-template-columns:1fr 1fr;gap:.7rem;margin:1.1rem 1.75rem 0}
.honor{display:flex;align-items:center;gap:.8rem;padding:.8rem .9rem;border-radius:.8rem;background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--line)}
.honor .ml{font-size:.7rem;letter-spacing:.16em;color:var(--muted)}
.honor b{font-size:1rem}
.honor.crit .stamp{background-color:var(--gold-solid);background-image:var(--gold-grad);color:var(--on-gold);font-size:1.05rem}
.honor.fumble .stamp{background:transparent;color:var(--danger);box-shadow:inset 0 0 0 1.5px var(--danger);font-size:1.05rem}
/* quotes */
.qcard{position:relative;margin:1.2rem 1.75rem 0;padding:2.6rem 2rem 1.4rem;border-radius:1rem;background:linear-gradient(160deg,var(--gold-soft),transparent 75%);box-shadow:inset 0 0 0 1px var(--gold-line)}
.qmark{position:absolute;left:1.85rem;top:.35rem;font-family:Georgia,"Times New Roman",serif;font-size:4.6rem;line-height:1;color:var(--gold-line);opacity:.7}
.qcard blockquote{position:relative;margin:0;padding:0;border:0;font-family:var(--serif);font-weight:600;letter-spacing:.04em;color:var(--text);line-height:1.75;text-align:justify}
.qcard blockquote.q-l{font-size:1.7rem;line-height:1.6}.qcard blockquote.q-m{font-size:1.35rem}.qcard blockquote.q-s{font-size:1.1rem;line-height:1.85}
.qcard figcaption{margin-top:1rem;text-align:right;font-size:.8rem;letter-spacing:.1em;color:var(--gold-ink)}
.qmeta{display:flex;justify-content:space-between;align-items:center;margin:.9rem 1.85rem 0;font-size:.76rem;color:var(--muted)}
.qpill{display:inline-flex;align-items:center;gap:.35rem;padding:.2rem .7rem;border-radius:999px;background:var(--gold-soft);color:var(--gold-ink);font-size:.76rem}
.qpill svg{width:.78rem;height:.78rem}.qpill b{font-size:.86rem}
.qlist{margin:.8rem 1.75rem 0;border-top:1px solid var(--line)}
.qrow{display:grid;grid-template-columns:2rem minmax(0,1fr) auto;gap:.8rem;align-items:center;padding:.8rem .4rem;border-bottom:1px solid var(--line)}
.qrow.top{background:var(--gold-soft);border-radius:.7rem;border-bottom-color:transparent}
.qno{font-family:var(--serif);font-size:1.35rem;font-weight:700;color:var(--faint);text-align:center}
.qrow.top .qno{color:var(--gold-ink)}
.qrow .qt{font-family:var(--serif);font-size:.98rem;line-height:1.7;color:var(--text)}
/* turtle soup */
.soup-face{margin:1rem 1.75rem 0;padding:1rem 1.25rem 1.1rem;border-radius:.9rem;background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--line);border-left:3px solid var(--gold-line)}
.soup-face.flavor-red{border-left-color:var(--danger)}
.soup-face .sl,.truth .sl{font-size:.7rem;letter-spacing:.26em;color:var(--gold);margin-bottom:.35rem}
.soup-face p{font-family:var(--serif);font-size:1.12rem;line-height:1.9;text-align:justify}
.soup-face.small p{font-size:.9rem;color:var(--text-2);line-height:1.75}
.truth{margin:.8rem 1.75rem 0;padding:1.05rem 1.25rem 1.15rem;border-radius:.9rem;background:var(--gold-soft);box-shadow:inset 0 0 0 1.5px var(--gold-line),0 0 1.2rem var(--glow)}
.truth p{font-family:var(--serif);font-size:1.05rem;line-height:1.9;text-align:justify}
.keys-h{display:flex;align-items:center;gap:.7rem;margin:1.1rem 1.75rem 0}
.keys-h span{font-size:.74rem;letter-spacing:.2em;color:var(--gold)}
.keys-h b{font-family:var(--serif);font-size:1rem;color:var(--gold-ink)}
.ktrack{flex:1;display:flex;gap:.25rem}
.ktrack i{flex:1;height:.35rem;border-radius:.2rem;background:var(--line-strong)}
.ktrack i.on{background-image:var(--gold-grad)}
.keys{margin:.5rem 1.75rem 0;display:flex;flex-direction:column;gap:.35rem}
.key{display:grid;grid-template-columns:1.5rem minmax(0,1fr) auto;align-items:center;gap:.6rem;padding:.45rem .7rem;border-radius:.6rem;box-shadow:inset 0 0 0 1px var(--line)}
.key .kn{width:1.35rem;height:1.35rem;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:.7rem;color:var(--faint);box-shadow:inset 0 0 0 1px var(--line-strong)}
.key b{font-size:.86rem;font-weight:500;color:var(--faint);letter-spacing:.04em}
.key em{font-style:normal;font-size:.7rem;color:var(--muted)}
.key.on{background:var(--gold-soft);box-shadow:inset 0 0 0 1px var(--gold-line)}
.key.on .kn{background-image:var(--gold-grad);color:var(--on-gold);box-shadow:none}
.key.on b{color:var(--text);font-weight:600}
.qas{margin:.5rem 1.75rem 0;border-top:1px solid var(--line)}
.qa{display:grid;grid-template-columns:4.4rem minmax(0,1fr) auto;gap:.7rem;align-items:center;padding:.5rem .2rem;border-bottom:1px solid var(--line)}
.qa .qq{font-size:.86rem;color:var(--text-2);line-height:1.5}
.qa .qw{font-size:.7rem;color:var(--faint)}
.ans{justify-self:stretch;text-align:center;font-size:.76rem;font-weight:600;padding:.12rem .3rem;border-radius:.4rem;white-space:nowrap}
.a-yes{color:var(--ok);box-shadow:inset 0 0 0 1px var(--ok)}
.a-no{color:var(--danger);box-shadow:inset 0 0 0 1px var(--danger)}
.a-skip{color:var(--muted);background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--line)}
.a-half{color:var(--gold-ink);background:var(--gold-soft)}
.mvp.solved,.mvp.unsolved{margin:1rem 1.75rem 0;padding:.8rem 1rem;border-radius:.9rem;background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--line)}
.mvp.solved{background:var(--gold-soft);box-shadow:inset 0 0 0 1.5px var(--gold-line)}
.mvp.solved .stamp{margin-left:auto}
.mvp.unsolved .stamp{background:var(--surface);color:var(--muted);box-shadow:inset 0 0 0 1px var(--line-strong)}
.margin{display:flex;align-items:center;gap:.7rem;margin-top:.6rem}
.ruler{position:relative;flex:1;max-width:13rem;height:.4rem;border-radius:.2rem;background:var(--line-strong)}
.ruler .zone{position:absolute;top:0;bottom:0;right:0;border-radius:0 .2rem .2rem 0;background:var(--ok);opacity:.28}
.ruler .dcl{position:absolute;top:-.25rem;bottom:-.25rem;width:2px;margin-left:-1px;background:var(--text-2)}
.ruler .pt{position:absolute;top:50%;width:.8rem;height:.8rem;margin:-.4rem 0 0 -.4rem;border-radius:50%;background:var(--ok);box-shadow:0 0 0 2px var(--bg)}
.margin.bad .ruler .pt{background:var(--danger)}
.margin .ml{font-size:.74rem;color:var(--ok);white-space:nowrap}.margin.bad .ml{color:var(--danger)}
.rec .rk{display:inline-block;padding:.02rem .45rem;border-radius:.3rem;letter-spacing:.08em;margin-bottom:.15rem}
.rk.g-inv{color:#3F6797;background:rgba(63,103,151,.1)}.rk.g-soc{color:#3F7A5E;background:rgba(63,122,94,.1)}
.rk.g-war{color:#A2433A;background:rgba(162,67,58,.1)}.rk.g-plan{color:var(--gold-ink);background:var(--gold-soft)}
.rk.g-fate{color:#74559E;background:rgba(116,85,158,.1)}
body.dark .rk.g-inv{color:#A9C3E4}body.dark .rk.g-soc{color:#A8D1B6}body.dark .rk.g-war{color:#F0A88E}body.dark .rk.g-fate{color:#CDB9E6}
.avs{display:inline-flex;margin-right:.45rem;vertical-align:middle}
.ava.sm{width:1.35rem;height:1.35rem;font-size:.68rem;margin-left:-.3rem;box-shadow:inset 0 0 0 1px var(--gold-line),0 0 0 2px var(--bg)}
.avs .ava.sm:first-child{margin-left:0}
.ava.sm.more{font-family:var(--mono);font-size:.58rem;color:var(--muted)}
.bar .bv{grid-column:2/4;display:flex;align-items:center;font-size:.72rem;color:var(--muted);margin-top:-.35rem}
.recap .rstats{margin:.2rem 0 0}
.recap .rs-cell b{font-size:1.35rem}
.recap .act-best{margin:.7rem 0 0}
.chairs{display:grid;gap:.6rem;margin:.9rem 1.75rem 0}
.chair{display:flex;flex-direction:column;align-items:center;gap:.25rem;padding:.9rem .4rem .75rem;border-radius:.8rem;background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--line);text-align:center}
.chair .ava{width:2.8rem;height:2.8rem;font-size:1.15rem}
.chair b{font-size:.9rem;margin-top:.2rem}
.chair .sd{font-size:.72rem;color:var(--muted);min-height:1rem}
.chair .state{margin-top:.25rem}
.chair.ok{background:var(--gold-soft);box-shadow:inset 0 0 0 1px var(--gold-line)}
.chair.ok .ava{background-color:var(--gold-solid);background-image:var(--gold-grad);color:var(--on-gold);box-shadow:none}
.chair.away{opacity:.7}
.chair.empty{background:transparent;box-shadow:none;border:1.5px dashed var(--line-strong)}
.chair.empty .ava{box-shadow:inset 0 0 0 1px var(--line-strong);color:var(--faint);background:transparent}
.chair.empty b,.chair.empty .sd{color:var(--faint)}
.ptier{margin-left:auto;display:flex;flex-direction:column;align-items:flex-end;flex:none}
.ptier b{font-family:var(--serif);font-size:1.9rem;font-weight:600;line-height:1.2;color:var(--text-2)}
.ptier.up b{color:var(--gold-ink)}.ptier.down b{color:var(--danger)}
.ptier span{font-size:.7rem;letter-spacing:.18em;color:var(--faint)}
.sect .cts{margin-top:.7rem}
.tl{position:relative;display:grid;grid-template-columns:1rem auto minmax(0,1fr) auto;gap:.6rem;align-items:baseline;padding:.4rem 0;font-size:.85rem}
.tl::before{content:"";position:absolute;left:.29rem;top:1.15rem;bottom:-.45rem;width:1px;background:var(--line-strong)}
.tl:last-child::before{display:none}
.tl i{width:.6rem;height:.6rem;border-radius:50%;background:var(--line-strong);align-self:center}
.tl.up i{background:var(--ok)}.tl.down i{background:var(--danger)}
.tl span{color:var(--text-2);line-height:1.6}
.tl em{font-style:normal;font-family:var(--mono);font-size:.74rem;color:var(--faint)}
.tl.up em{color:var(--ok)}.tl.down em{color:var(--danger)}
.meter{margin:.7rem 1.75rem 0;padding:.8rem 1rem;border-radius:.75rem;background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--line)}
.race{display:grid;grid-template-columns:4.5rem minmax(0,1fr) 3rem;align-items:center;gap:.7rem;font-size:.8rem;padding:.25rem 0}
.race .rl{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.race .num{text-align:right;font-weight:600}
.rbar{position:relative;height:.7rem;border-radius:.35rem;background:var(--line-strong);overflow:hidden}
.rbar b{display:block;height:100%;border-radius:.35rem}
.rbar i{position:absolute;top:0;bottom:0;width:2px;margin-left:-1px;background:var(--surface-2)}
.race.ours b{background-color:var(--gold-solid);background-image:var(--gold-grad)}.race.theirs b{background:var(--danger);opacity:.8}
.mnote{font-size:.72rem;color:var(--faint);margin-top:.35rem}
.chain{display:flex;align-items:flex-start}
.chain .st{flex:1;position:relative;display:flex;flex-direction:column;align-items:center;gap:.3rem}
.chain .st::after{content:"";position:absolute;top:.8rem;left:calc(50% + .9rem);right:calc(-50% + .9rem);height:2px;background:var(--line-strong)}
.chain .st:last-child::after{display:none}
.chain .st.done::after{background:var(--ok)}
.chain .st b{width:1.6rem;height:1.6rem;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:.8rem;color:var(--muted);box-shadow:inset 0 0 0 1.5px var(--line-strong);background:var(--bg)}
.chain .st.done b{background:var(--ok);color:#fff;box-shadow:none}
.chain .st.failed b{background:var(--danger);color:#fff;box-shadow:none}
.chain .st.off b{opacity:.5}
.chain .st em{font-style:normal;font-size:.7rem;color:var(--muted)}
.facestrip{display:grid;grid-template-columns:repeat(20,1fr);gap:.18rem;margin:.9rem 1.75rem 0;align-items:end}
.fc{display:flex;flex-direction:column;align-items:center;gap:.2rem}
.fc .fp{display:flex;flex-direction:column-reverse;align-items:center;min-height:1.4rem}
.fc .fp .ava.sm{margin:0 0 -.35rem;width:1.3rem;height:1.3rem}
.fc .fmore{font-size:.55rem;color:var(--muted)}
.fc i{width:100%;height:.4rem;border-radius:.15rem;background:var(--tc);opacity:.22}
.fc i.on{opacity:1}
.fc .num{font-size:.62rem;color:var(--faint);min-height:.8rem}
.drange{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:.7rem;margin:.9rem 1.75rem 0;font-size:.72rem;color:var(--faint)}
.dr{position:relative;height:.5rem;border-radius:.25rem;background:var(--line-strong);margin:1.2rem 0 1.1rem}
.dr b{display:block;height:100%;border-radius:.25rem;background-color:var(--gold-solid);background-image:var(--gold-grad)}
.dr em{position:absolute;top:-1.35rem;transform:translateX(-50%);font-style:normal;font-size:.8rem;font-weight:700;color:var(--gold-ink)}
.dr .avg{position:absolute;top:-.2rem;bottom:-.2rem;width:2px;margin-left:-1px;background:var(--text-2);opacity:.6}
.dr .avg span{position:absolute;top:.95rem;left:50%;transform:translateX(-50%);white-space:nowrap;font-style:normal;font-size:.65rem;color:var(--faint)}
.drange.hi .dr em{color:var(--ok)}.drange.lo .dr em{color:var(--danger)}
.h0{--pc:#B9533E}.h1{--pc:#3F6797}.h2{--pc:#3F7A5E}.h3{--pc:#74559E}.h4{--pc:#B07A2A}.h5{--pc:#2F8A8A}
body.dark .h0{--pc:#E08B73}body.dark .h1{--pc:#86A8D4}body.dark .h2{--pc:#86BC9C}body.dark .h3{--pc:#B49CD8}body.dark .h4{--pc:#DDB073}body.dark .h5{--pc:#7FC4C4}
.relay .ln{text-decoration:underline;text-decoration-color:var(--pc);text-decoration-thickness:2px;text-underline-offset:.35rem}
.relay .ln sup{color:var(--pc)}
.chip.pen i{width:.5rem;height:.5rem;border-radius:50%;background:var(--pc)}
.tag-most{display:inline-block;margin-left:.5rem;font-size:.66rem;padding:.04rem .45rem;border-radius:.3rem;vertical-align:.15rem;background-color:var(--gold-solid);background-image:var(--gold-grad);color:var(--on-gold)}
.slot .sd{display:flex;align-items:center}
/* personas */
.avatar img,.ava img{width:100%;height:100%;border-radius:50%;object-fit:cover;display:block}
.ava{overflow:hidden}
.pbox{margin:0 1.75rem .2rem;padding:.8rem 1rem;border-radius:.75rem;background:var(--gold-soft);box-shadow:inset 0 0 0 1px rgba(205,176,120,.32)}
.pb-head{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}
.pb-head b{font-family:var(--serif);font-size:1rem}
.pb-tag{font-size:.66rem;letter-spacing:.18em;color:var(--on-gold);background-color:var(--gold-solid);background-image:var(--gold-grad);padding:.08rem .5rem;border-radius:.3rem}
.pb-intro{font-family:var(--serif);font-size:.92rem;line-height:1.7;margin-top:.45rem;color:var(--text)}
.pb-intro.pending{font-family:inherit;font-size:.8rem;color:var(--muted)}
.pb-k{font-family:"PingFang SC","Microsoft YaHei",sans-serif;font-size:.68rem;letter-spacing:.12em;color:var(--gold);margin-right:.6rem}
.pb-text{font-size:.78rem;line-height:1.65;color:var(--muted);margin-top:.35rem}
.pf{display:grid;grid-template-columns:4.6rem minmax(0,1fr);gap:.8rem;padding:.55rem 0;border-bottom:1px solid var(--line)}
.pf:last-child{border-bottom:0}
.pf-k{font-size:.76rem;color:var(--gold);letter-spacing:.08em;padding-top:.15rem}
.pf-v{font-family:var(--serif);font-size:.92rem;line-height:1.75;white-space:pre-line}
.psum{border-radius:.7rem;background:var(--surface-2);padding:.75rem .95rem;margin-bottom:.75rem}
.ps-k{font-size:.7rem;letter-spacing:.14em;color:var(--gold);margin-bottom:.3rem}
.ps-k em{font-style:normal;margin-left:.5rem;font-size:.66rem;letter-spacing:0;color:var(--muted)}
.ps-v{font-family:var(--serif);font-size:.9rem;line-height:1.75}
.lenbar .lb-track{display:flex;height:.5rem;border-radius:999px;background:var(--surface-2);overflow:hidden;box-shadow:inset 0 0 0 1px var(--line)}
.lenbar i.ok{background:var(--ok)}
.lenbar i.over{background:repeating-linear-gradient(135deg,var(--danger) 0 .25rem,transparent .25rem .5rem);opacity:.75}
.lb-cap{display:flex;justify-content:space-between;font-size:.72rem;color:var(--muted);margin-top:.35rem}
.plist{padding:0 1.75rem}
.prow{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:.85rem;align-items:center;padding:.75rem 0;border-bottom:1px solid var(--line)}
.prow .ava{width:2.8rem;height:2.8rem;font-size:1.15rem}
.prow .pn b{font-family:var(--serif);font-size:1rem;margin-right:.45rem}
.prow .pn .chip{font-size:.66rem;padding:.06rem .45rem;margin-right:.25rem}
.prow .sd{font-size:.76rem;color:var(--muted);margin-top:.25rem;line-height:1.55}
.prow .pl{font-size:.72rem;color:var(--ok)}
.prow .pl.over{color:var(--danger)}

"""

