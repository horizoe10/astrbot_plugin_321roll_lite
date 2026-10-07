"""Structured chat messages rendered as Markdown or plain text.

A Msg is a list of sections; blocks in a section are joined by line breaks and
sections by a blank line.  Feature code builds messages in roll_lite/messages.py
and never formats for a particular platform.  Backticks inside text(), field()
and hint() mark inline code (commands, tags) and **double stars** mark bold;
Markdown keeps both, plain text drops the markers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MARKDOWN = "markdown"
PLAIN = "plain"
# AstrBot adapters that render Markdown.  QQ official also needs the bot's native-markdown permission.
MARKDOWN_PLATFORMS = frozenset({"qq_official", "qq_official_webhook", "telegram", "lark", "kook", "discord", "mattermost"})
BT = "\x60"


def target_format(preferred: str, platform_name: str | None, blocked: bool = False) -> str:
    """Markdown only when chosen, supported by the platform and not refused before; otherwise plain."""
    if preferred == MARKDOWN and not blocked and (platform_name or "") in MARKDOWN_PLATFORMS:
        return MARKDOWN
    return PLAIN


_MD_SPECIAL = re.compile(r"([\\*_~|\x60\[\]])")
_MD_LINE_START = re.compile(r"^(\s*)(?:([#>+\-])|(\d+)\.)(?=\s)", re.MULTILINE)
_INLINE = re.compile(r"(\x60[^\x60\n]*\x60|\*\*[^*\n]+?\*\*)")


def esc_inline(text: Any) -> str:
    """Escape text that sits inside a line (after a marker or inside bold)."""
    return _MD_SPECIAL.sub(r"\\\1", str(text))


def esc(text: Any) -> str:
    """Escape text that may start a line, so '- ', '# ' or '1. ' stay literal."""
    return _MD_LINE_START.sub(lambda m: m.group(1) + ("\\" + m.group(2) if m.group(2) else m.group(3) + "\\."),
                              esc_inline(text))


def inline(text: Any, fmt: str, start: bool = True) -> str:
    """Template text with inline code and bold markers; everything else is escaped.

    start=False for text that follows a marker on the same line (list item, label, quote mark).
    """
    out = []
    for i, part in enumerate(_INLINE.split(str(text))):
        if i % 2 == 0:
            out.append(part if fmt == PLAIN else (esc(part) if i == 0 and start else esc_inline(part)))
        elif part.startswith(BT):
            code = part[1:-1]
            out.append(code if fmt == PLAIN or not code else BT + code + BT)
        else:
            out.append(part[2:-2] if fmt == PLAIN else f"**{esc_inline(part[2:-2])}**")
    return "".join(out)


def safe(text: Any) -> str:
    """User or model text placed inside template markup: drop the marker characters."""
    return str(text).replace(BT, "'").replace("**", "*")


def meter(current: int, maximum: int, width: int = 10) -> str:
    if maximum <= 0:
        return ""
    cells = min(width, maximum)
    filled = round(cells * max(0, min(current, maximum)) / maximum)
    return "▰" * filled + "▱" * (cells - filled)


def dots(filled: int, total: int, on: str = "●", off: str = "○") -> str:
    total = max(0, min(total, 12))
    filled = max(0, min(filled, total))
    return on * filled + off * (total - filled)


OUTCOMES = {"critical": "大成功", "success": "成功", "failure": "失败", "fumble": "大失败"}


@dataclass
class Block:
    kind: str
    data: dict[str, Any]

    def render(self, fmt: str) -> str:
        d, k, md = self.data, self.kind, fmt == MARKDOWN
        if k == "title":
            sub = d.get("sub") or ""
            if md:
                return f"**{esc_inline(d['text'])}**" + (f"　{inline(sub, fmt, False)}" if sub else "")
            return f"{d['text']}" + (f"　{inline(sub, fmt)}" if sub else "")
        if k == "banner":
            return f"## {esc_inline(d['text'])}" if md else f"〖 {d['text']} 〗"
        if k == "heading":
            return f"### {esc_inline(d['text'])}" if md else f"━━  {d['text']}  ━━"
        if k == "caption":
            return f"*{esc_inline(d['text'])}*" if md else f"〔{d['text']}〕"
        if k == "quote":
            lines = str(d["text"]).splitlines() or [""]
            return "\n".join("> " + esc(line) for line in lines) if md else "「" + "\n".join(lines) + "」"
        if k == "text":
            return inline(d["text"], fmt)
        if k == "para":
            return esc(d["text"]) if md else str(d["text"])
        if k == "field":
            return f"**{esc_inline(d['label'])}**　{inline(d['value'], fmt, False)}" if md else f"{d['label']}　{inline(d['value'], fmt)}"
        if k == "meter":
            bar, tail, delta = meter(d["current"], d["maximum"]), f"{d['current']}/{d['maximum']}", d.get("delta")
            if md:
                return f"{esc(d['label'])}　{BT}{bar}{BT}　{tail}" + (f"　**{delta:+d}**" if delta else "")
            return f"{d['label']}  {bar}  {tail}" + (f"  {delta:+d}" if delta else "")
        if k == "check":
            mod, label = d["modifier"], OUTCOMES.get(d["outcome"], d["outcome"])
            if md:
                return (f"**{esc_inline(d['attribute'])}检定** · {esc_inline(d['difficulty'])} {d['dc']}　"
                        f"{BT}d20 {d['face']}{BT} {mod:+d} ＝ **{d['total']}**　**【{label}】**")
            return f"{d['attribute']}检定  {d['difficulty']} {d['dc']}\nd20 {d['face']} {mod:+d} ＝ {d['total']}　【{label}】"
        if k == "draw":
            return f"{BT}d20 {d['face']}{BT}　**【{esc_inline(d['label'])}】**" if md else f"d20 {d['face']}　【{d['label']}】"
        if k == "choices":
            rows = []
            for item in d["items"]:
                tag = item.get("tag") or ""
                if md:
                    rows.append(f"- **{item['label']}**　{esc_inline(item['text'])}" + (f"　{BT}{tag}{BT}" if tag else ""))
                else:
                    rows.append(f" {item['label']} │ {item['text']}" + (f"　〈{tag}〉" if tag else ""))
            return "\n".join(rows)
        if k == "list":
            return "\n".join((f"- {inline(i, fmt, False)}" if md else f"· {inline(i, fmt)}") for i in d["items"])
        if k == "people":
            if md:
                return f"**{esc_inline(d['label'])}**\n" + "\n".join(f"- **{esc_inline(n)}**　{esc_inline(t)}" for n, t in d["items"])
            return d["label"] + "\n" + "\n".join(f"· {n}　{t}" for n, t in d["items"])
        if k == "hint":
            return f"> {inline(d['text'], fmt, False)}" if md else f"› {inline(d['text'], fmt)}"
        if k == "rule":
            return "---" if md else "┄┄┄┄┄┄┄┄┄┄"
        raise ValueError(k)


# Markdown blocks that must stand apart; inline blocks next to each other get a hard line break,
# because CommonMark folds single newlines and lets text continue a quote or list item.
BLOCK_LEVEL = frozenset({"banner", "heading", "quote", "choices", "list", "people", "hint", "rule"})


@dataclass
class Msg:
    sections: list[list[Block]] = field(default_factory=list)
    mentions: list[tuple[str, str]] = field(default_factory=list)   # (user_id, display name), put before the text
    # 'status' | 'narration' | 'choices' | '': segments the admin may send as images.
    segment: str = ""
    # Scene banner for the image card: {'world': id, 'key': 'act:2', 'tag': '…'}; set at opening, act or scene change.
    art: dict[str, str] | None = None

    def as_segment(self, name: str) -> "Msg":
        self.segment = name
        return self

    def with_art(self, world: str, key: str, tag: str = "") -> "Msg":
        self.art = {"world": world, "key": key, "tag": tag}
        return self

    def _add(self, kind: str, **data: Any) -> "Msg":
        if not self.sections:
            self.sections.append([])
        self.sections[-1].append(Block(kind, data))
        return self

    def gap(self) -> "Msg":
        if self.sections and self.sections[-1]:
            self.sections.append([])
        return self

    def title(self, text: str, sub: str = "") -> "Msg":
        return self._add("title", text=text, sub=sub)

    def banner(self, text: str) -> "Msg":
        return self._add("banner", text=text)

    def heading(self, text: str) -> "Msg":
        return self._add("heading", text=text)

    def caption(self, text: str) -> "Msg":
        return self._add("caption", text=text)

    def quote(self, text: str) -> "Msg":
        return self._add("quote", text=text)

    def text(self, text: str) -> "Msg":
        return self._add("text", text=text)

    def para(self, text: str) -> "Msg":
        """Prose; every blank-line separated paragraph becomes its own section."""
        for paragraph in [p.strip() for p in re.split(r"\n\s*\n", str(text)) if p.strip()]:
            self.gap()._add("para", text=paragraph)
        return self.gap()

    def field(self, label: str, value: str) -> "Msg":
        return self._add("field", label=label, value=value)

    def meter(self, label: str, current: int, maximum: int, delta: int | None = None) -> "Msg":
        return self._add("meter", label=label, current=current, maximum=maximum, delta=delta)

    def check(self, **data: Any) -> "Msg":
        return self._add("check", **data)

    def draw(self, face: int, label: str) -> "Msg":
        return self._add("draw", face=face, label=label)

    def choices(self, items: list[dict[str, str]]) -> "Msg":
        return self._add("choices", items=items)

    def items(self, items: list[str]) -> "Msg":
        return self._add("list", items=items)

    def people(self, label: str, items: list[tuple[str, str]]) -> "Msg":
        return self._add("people", label=label, items=items)

    def hint(self, text: str, *, note: str = "", cmds: list[tuple[str, str]] | None = None) -> "Msg":
        """note and cmds (label, command) lay the hint out for image cards; text is what chat messages show."""
        return self._add("hint", text=text, note=note, cmds=cmds or [])

    def rule(self) -> "Msg":
        return self._add("rule")

    def mention(self, user_id: str, name: str) -> "Msg":
        self.mentions.append((str(user_id), name))
        return self

    def render(self, fmt: str) -> str:
        if fmt != MARKDOWN:
            return "\n\n".join("\n".join(b.render(fmt) for b in section) for section in self.sections if section)
        out = []
        for section in self.sections:
            parts, prev = [], ""
            for block in section:
                if parts:
                    parts.append("\n\n" if prev in BLOCK_LEVEL or block.kind in BLOCK_LEVEL else "  \n")
                parts.append(block.render(fmt))
                prev = block.kind
            if parts:
                out.append("".join(parts))
        return "\n\n".join(out)


Item = "Msg | str"


def render(item: Any, fmt: str) -> str:
    return item.render(fmt) if isinstance(item, Msg) else str(item)


def mentions_of(item: Any) -> list[tuple[str, str]]:
    return list(item.mentions) if isinstance(item, Msg) else []
