"""SillyTavern formats: character cards (V1, V2 and V3, as PNG or JSON) and World Info lorebooks.

Only reading and writing the documents lives here; personas.py turns a card into a persona and
worlds/tavern_import.py turns a lorebook or a scenario card into a world draft.  A card PNG keeps
its JSON base64-encoded in a tEXt chunk named "chara" (V2) or "ccv3" (V3).  Chat apps that
re-encode pictures drop those chunks, so a picture without them is reported as such.
"""
from __future__ import annotations

import base64
import json
import re
import struct
import zlib
from typing import Any

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_INPUT = 8 * 1024 * 1024
STRIPPED = ("这张图片里没有角色卡数据，多半是聊天软件压缩时去掉了。请把原图以“文件”形式发送，"
            "或在 SillyTavern 里导出 JSON 后粘贴。")


class TavernError(ValueError):
    """The input is not a card or lorebook this module can read; the message is shown as is."""


def png_texts(data: bytes) -> dict[str, str]:
    """Text chunks of a PNG (tEXt, zTXt, iTXt) by keyword; an empty dict for anything else."""
    if not data.startswith(PNG_SIGNATURE):
        return {}
    found: dict[str, str] = {}
    pos = len(PNG_SIGNATURE)
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        try:
            if kind == b"tEXt":
                key, _, value = body.partition(b"\0")
                found[key.decode("latin-1")] = value.decode("latin-1")
            elif kind == b"zTXt":
                key, _, rest = body.partition(b"\0")
                found[key.decode("latin-1")] = zlib.decompress(rest[1:]).decode("latin-1")
            elif kind == b"iTXt":
                key, _, rest = body.partition(b"\0")
                compressed, rest = rest[0], rest[2:]
                _, _, rest = rest.partition(b"\0")          # language tag
                _, _, text = rest.partition(b"\0")          # translated keyword
                found[key.decode("latin-1")] = (zlib.decompress(text) if compressed else text).decode("utf-8")
        except (zlib.error, UnicodeDecodeError, IndexError):
            continue
        if kind == b"IEND":
            break
    return found


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise TavernError(f"不是有效的 JSON：第 {exc.lineno} 行第 {exc.colno} 列") from None


def read(data: bytes, filename: str = "") -> dict[str, Any]:
    """{'type': 'card' | 'lorebook', 'data': normalized document, 'image': PNG bytes or None}."""
    if not data:
        raise TavernError("文件是空的。")
    if len(data) > MAX_INPUT:
        raise TavernError("文件超过 8MB。")
    image = None
    if data.startswith(PNG_SIGNATURE):
        texts = png_texts(data)
        raw = texts.get("ccv3") or texts.get("chara")
        if not raw:
            raise TavernError(STRIPPED)
        try:
            document = _json(base64.b64decode(raw).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise TavernError("图片里的角色卡数据损坏了。") from exc
        image = data
    elif data[:3] == b"\xff\xd8\xff" or data[:4] in (b"RIFF", b"GIF8"):
        raise TavernError(STRIPPED)
    else:
        try:
            document = _json(data.decode("utf-8-sig"))
        except UnicodeDecodeError as exc:
            raise TavernError("文件不是 UTF-8 文本，也不是 PNG 角色卡。") from exc
    return parse(document, image=image)


def parse(document: Any, *, image: bytes | None = None) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise TavernError("文件内容应该是一个 JSON 对象。")
    if document.get("spec") in ("chara_card_v2", "chara_card_v3") and isinstance(document.get("data"), dict):
        return {"type": "card", "data": card(document["data"]), "image": image}
    if isinstance(document.get("entries"), (dict, list)) and not document.get("first_mes"):
        return {"type": "lorebook", "data": lorebook(document), "image": image}
    if isinstance(document.get("data"), dict) and document["data"].get("name"):
        return {"type": "card", "data": card(document["data"]), "image": image}
    if document.get("name") and any(k in document for k in ("description", "personality", "first_mes", "char_persona")):
        return {"type": "card", "data": card(document), "image": image}
    raise TavernError("认不出这个文件：需要 SillyTavern 角色卡（PNG 或 JSON）或世界书（World Info）JSON。")


_TAGS = re.compile(r"<[^>]{1,200}>")


def clean(text: Any, name: str = "", user: str = "玩家") -> str:
    """Card text as plain prose: macros resolved, HTML tags and runs of blank lines removed."""
    value = str(text or "").replace("\r\n", "\n")
    value = re.sub(r"\{\{\s*char\s*\}\}|<BOT>", name or "角色", value, flags=re.IGNORECASE)
    value = re.sub(r"\{\{\s*user\s*\}\}|<USER>", user, value, flags=re.IGNORECASE)
    value = _TAGS.sub("", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def card(data: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name") or "").strip()[:80]
    book = data.get("character_book")
    tags = data.get("tags") if isinstance(data.get("tags"), list) else []
    return {"name": name,
            "description": clean(data.get("description") or data.get("char_persona"), name),
            "personality": clean(data.get("personality"), name),
            "scenario": clean(data.get("scenario") or data.get("world_scenario"), name),
            "first_mes": clean(data.get("first_mes") or data.get("char_greeting"), name),
            "mes_example": clean(data.get("mes_example") or data.get("example_dialogue"), name),
            "creator_notes": clean(data.get("creator_notes"), name),
            "creator": str(data.get("creator") or "").strip()[:80],
            "tags": [str(t).strip()[:20] for t in tags if str(t).strip()][:12],
            "entries": lorebook(book, name)["entries"] if isinstance(book, dict) else []}


def lorebook(document: dict[str, Any], owner: str = "") -> dict[str, Any]:
    """World Info file or embedded character_book -> {'name', 'entries': [...]} in display order."""
    raw = document.get("entries")
    rows = list(raw.values()) if isinstance(raw, dict) else list(raw or [])
    entries = []
    for index, row in enumerate(r for r in rows if isinstance(r, dict)):
        keys = row.get("key") if isinstance(row.get("key"), list) else row.get("keys")
        keys = [str(k).strip() for k in (keys if isinstance(keys, list) else []) if str(k).strip()][:12]
        content = clean(row.get("content"), owner)
        title = str(row.get("comment") or row.get("name") or "").strip() or (keys[0] if keys else "")
        if not content:
            continue
        disabled = bool(row.get("disable")) or row.get("enabled") is False
        order = row.get("displayIndex", row.get("order", row.get("insertion_order", index)))
        entries.append({"name": (title or content[:12]).strip()[:60], "content": content, "keys": keys,
                        "constant": bool(row.get("constant")), "enabled": not disabled,
                        "order": order if isinstance(order, (int, float)) else index, "index": index})
    entries.sort(key=lambda e: (e["order"], e["index"]))
    name = str(document.get("name") or "").strip()[:80]
    return {"name": name, "entries": entries}


def export_card(persona: dict[str, Any]) -> dict[str, Any]:
    """A chara_card_v2 document for a persona, so a player can take it back to SillyTavern."""
    data = persona.get("data") or {}
    description = "\n\n".join(f"{label}：{data[key]}" for key, label in (("appearance", "外貌"), ("background", "背景"))
                              if data.get(key))
    return {"spec": "chara_card_v2", "spec_version": "2.0",
            "data": {"name": persona["name"], "description": description, "personality": data.get("personality", ""),
                     "scenario": "", "first_mes": "", "mes_example": data.get("speech", ""),
                     "creator_notes": "由 321Roll Lite 人设卡导出", "system_prompt": "", "post_history_instructions": "",
                     "alternate_greetings": [], "tags": list(data.get("tags") or []), "creator": data.get("creator", ""),
                     "character_version": "", "extensions": {"321roll_lite": {"summary": data.get("summary", "")}}}}
