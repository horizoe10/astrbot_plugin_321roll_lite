"""Image cards for the status, narration and choices segments.

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

from .render import _INLINE, BT, OUTCOMES, Block, Msg
from .worlds.catalog import COVER_TONES

THEMES = ("light", "dark")
TEMPLATE = "{{ html | safe }}"
# AstrBot's default is JPEG quality 40, too soft for small CJK text on a phone.
RENDER_OPTIONS = {"type": "jpeg", "quality": 92, "full_page": True}
# Covers are a colour field plus one large character; preset worlds get a hand-picked pair.
COVERS = {"seventh-mystery": ("七", "ink"), "wildfire-hunt": ("狩", "ember"), "neon-pawnshop": ("当", "neon"),
          "nameless-sword-tomb": ("剑", "jade"), "final-curtain": ("戏", "wine"), "greycrown-prequel": ("冠", "slate")}
SEGMENT_LABELS = {"status": "个人状态", "narration": "故事正文", "choices": "行动选项"}
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
}


# ---------------------------------------------------------------- pieces
def _flat(msg: Msg) -> list[Block]:
    return [block for section in msg.sections for block in section]


def _chip(label: str, note: str = "", icon: str = "skill", off: bool = False) -> str:
    return (f'<span class="chip{" off" if off else ""}">{ICONS[icon]}{e(label)}'
            + (f"<em>{e(note)}</em>" if note else "") + "</span>")


def _banner(art: dict[str, Any], title: str, sub: str) -> str:
    image = art.get("image") or ""
    inner = (f'<img src="{e(image)}" alt="" /><div class="shade"></div>' if image
             else f'<div class="mark">{e(art.get("mark") or "团")}</div>')
    tone = "" if image else f' cover tone-{e(art.get("tone") or "wine")}'
    return (f'<header class="banner{tone}">{inner}'
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


def _vitals(meters: list[dict[str, Any]]) -> str:
    rows = []
    for m in meters:
        ratio = _ratio(m["current"], m["maximum"])
        delta = m.get("delta")
        tail = (f'<span class="delta {"up" if delta > 0 else "down"}">{delta:+d}</span>' if delta else "")
        rows.append(f'<div class="vital{" low" if ratio <= 0.4 else ""}"><span class="vk">{e(m["label"])}</span>'
                    f'<div class="track"><i style="width:{ratio * 100:.0f}%"></i></div>'
                    f'<span class="vv num">{tail}{m["current"]}<small>/{m["maximum"]}</small></span></div>')
    return '<div class="vitals">' + "".join(rows) + "</div>"


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
            f'<div class="h">{e(OUTCOMES.get(d["outcome"], d["outcome"]))}</div><div class="terms">{terms}</div></div></div>')


def _split_entry(text: str) -> tuple[str, str]:
    name, _, note = str(text).partition(" ")
    return name, note.strip()


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
            cls = "say" if text[:1] in "“「\"『" else ("lead" if lead else "")
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
            rings = "".join(f'<div class="ring {cls}" style="--p:{_ratio(m["current"], m["maximum"]):.3f}"></div>'
                            for cls, m in zip(("r1", "r2"), meters))
            vals = '<span class="sep"> · </span>'.join(
                f'<span class="{cls}">{m["current"]}</span>/{m["maximum"]} {e(m["label"])}' for cls, m in zip(("r1", "r2"), meters))
            parts.append(f'<div class="eyebrow"><span>个人状态</span><b>{e(round_label)}</b></div>'
                         f'<div class="me"><div class="medal">{rings}<div class="avatar">{e(name[:1])}</div></div><div>'
                         f'<div class="me-name">{e(name)}' + (f"<small>{e(role)}</small>" if role else "") + "</div>"
                         + (f'<div class="me-vals num">{vals}</div>' if vals else "") + "</div></div>")
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


def _fate(item: dict[str, str], vote: bool) -> str:
    tag = str(item.get("tag") or "")
    right, sub = "", ""
    if vote:
        sub = tag
    elif tag == "休整":
        right, sub = f'<div class="odds">{ICONS["moon"]}<span class="k">休整</span></div>', "休整 · 恢复体力，不推进危险"
    elif "·" in tag:
        attr, difficulty, *rest = tag.split("·")
        right = f'<div class="odds"><span class="v">{e(difficulty)}</span><span class="k">{e(attr)}检定</span></div>'
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
            parts.append(f'<div class="turn"><div class="orb"><div class="r"></div><div class="f">{ICONS["vote" if vote else "quill"]}</div></div>'
                         f'<div><div class="turn-t">{headline}</div>'
                         + (f'<div class="turn-d">{e(meta)}</div>' if meta else "") + "</div>"
                         + (f'<div class="clock num">{minutes.group(1)} 分钟</div>' if minutes else "") + "</div>")
        elif k == "para":
            parts.append(f'<p class="premise">{e(d["text"])}</p>')
        elif k == "choices":
            parts.append('<div class="fates">' + "".join(_fate(i, vote) for i in d["items"]) + "</div>")
        elif k == "field" and d["label"] == "可准备":
            entries = [x for x in str(d["value"]).split("　") if x and x != "…"]
            chips = "".join(_chip(*_split_entry(x)) for x in entries)
            parts.append(f'<div class="preps"><span class="lab">可准备</span>{chips}</div>')
        else:
            parts.append(_generic(block))
    return "".join(parts), foot


LAYOUTS = {"status": _status, "choices": _choices}


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
.ring{position:absolute;border-radius:50%;-webkit-mask-image:radial-gradient(farthest-side,transparent calc(100% - 3px),#000 calc(100% - 2.5px));mask-image:radial-gradient(farthest-side,transparent calc(100% - 3px),#000 calc(100% - 2.5px))}
.ring.r1{inset:5%;background:conic-gradient(var(--r1) calc(var(--p)*360deg),var(--line-strong) 0)}
.ring.r2{inset:11.5%;background:conic-gradient(var(--r2) calc(var(--p)*360deg),var(--line-strong) 0)}
.avatar{position:absolute;inset:18.5%;border-radius:50%;background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--line-strong);display:flex;align-items:center;justify-content:center;font-family:var(--serif);font-size:1.5rem;font-weight:600;color:var(--gold)}
body.dark .avatar{box-shadow:inset 0 0 0 1px rgba(210,166,103,.28)}
.me-name{font-family:var(--serif);font-size:1.3rem;font-weight:600;display:flex;align-items:baseline;gap:.5rem}
.me-name small{font-family:"PingFang SC","Microsoft YaHei",sans-serif;font-size:.74rem;font-weight:400;color:var(--gold-ink);background:var(--gold-soft);padding:.06rem .55rem;border-radius:999px}
.me-vals{font-size:.78rem;margin-top:.4rem;color:var(--text-2)}
.me-vals .r1{color:var(--r1);font-weight:600}.me-vals .r2{color:var(--r2);font-weight:600}.me-vals .sep{color:var(--faint)}
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
.vital{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:.6rem;font-size:.78rem}
.vital .vk{color:var(--muted)}
.track{height:3px;border-radius:2px;background:var(--line-strong);overflow:hidden}.track i{display:block;height:100%;border-radius:2px;background:var(--gold)}
.vital.low .track i{background:var(--danger)}
.vital .vv{font-weight:600}.vital .vv small{font-weight:400;color:var(--muted);font-size:.74rem}
.vital.low .vv{color:var(--danger)}
.delta{font-family:var(--mono);font-size:.7rem;font-weight:500;margin-right:.35rem}.delta.down{color:var(--danger)}.delta.up{color:var(--ok)}
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
.preps .lab{margin-right:.2rem}
.hint{margin:.9rem 1.5rem 0;padding:.8rem 0 .3rem;border-top:1px solid var(--line);font-size:.76rem;color:var(--muted);line-height:1.7}
.uses+.hint,.preps+.hint{margin-top:1rem}
.hint .note{margin-bottom:.55rem}
.cmds{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem 1.15rem}
.cmd{display:inline-flex;align-items:center;gap:.45rem;white-space:nowrap}
.cmd .ck{font-size:.74rem;color:var(--faint)}
"""

