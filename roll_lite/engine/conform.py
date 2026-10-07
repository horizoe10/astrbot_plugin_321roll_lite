"""Bring a decoded model object to the shape its JSON Schema asks for, and say what still differs.

321Roll calls DeepSeek and similar providers with strict structured output.  Lite goes through
AstrBot's llm_generate, where the schema is only text in the prompt, and such models often drop
a key whose value would be null, echo input fields (fact_ref) or add fields from other contracts.

conform() repairs only those shape slips: it removes keys a closed object does not define and gives
a missing key the empty value its schema allows (null, an empty list, or "" when the enum lists it).
It never writes prose, choices or numbers.  problems() lists what is still wrong, path by path, for
the call journal and the repair prompt.  The engine validation that follows remains the authority.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

_MISSING = object()
_TYPE_NAMES = {"object": "对象", "array": "列表", "string": "文字", "integer": "整数", "number": "数字",
               "boolean": "true/false", "null": "null"}
LIMIT = 12


def _types(schema: dict[str, Any]) -> set[str]:
    value = schema.get("type")
    return set(value) if isinstance(value, list) else ({value} if value else set())


def _allows_null(schema: dict[str, Any]) -> bool:
    return "null" in _types(schema) or any(_allows_null(s) for s in schema.get("anyOf", ()))


def _empty(schema: dict[str, Any]) -> Any:
    """The empty value a missing key may take, or _MISSING when it has none."""
    if _allows_null(schema):
        return None
    kinds = _types(schema)
    if "array" in kinds and not schema.get("minItems"):
        return []
    if "string" in kinds and "" in schema.get("enum", ()):
        return ""
    if "object" in kinds and schema.get("additionalProperties") is False:
        properties = schema.get("properties", {})
        filled = {}
        for key in schema.get("required", []):
            value = _empty(properties.get(key, {}))
            if value is _MISSING:
                return _MISSING
            filled[key] = value
        return filled
    return _MISSING


def _join(path: str, key: Any) -> str:
    return f"{path}[{key}]" if isinstance(key, int) else (f"{path}.{key}" if path else str(key))


def _show(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _fix(value: Any, schema: dict[str, Any], path: str, notes: list[str]) -> Any:
    if value is None and not _allows_null(schema):
        empty = _empty(schema)
        if empty is not _MISSING and empty is not None:
            notes.append(f"{path or '输出'} 由 null 改为 {_show(empty)}")
            return empty
    if isinstance(value, dict) and "anyOf" in schema and "properties" not in schema:
        branch = next((s for s in schema["anyOf"] if "object" in _types(s)), None)
        return _fix(value, branch, path, notes) if branch else value
    if isinstance(value, dict) and isinstance(schema.get("properties"), dict):
        properties = schema["properties"]
        if schema.get("additionalProperties") is False:
            for key in [k for k in value if k not in properties]:
                del value[key]
                notes.append(f"删除多余字段 {_join(path, key)}")
        for key in schema.get("required", []):
            if key not in value:
                empty = _empty(properties.get(key, {}))
                if empty is not _MISSING:
                    value[key] = empty
                    notes.append(f"补上 {_join(path, key)}={_show(empty)}")
        for key, sub in properties.items():
            if key in value and isinstance(sub, dict):
                value[key] = _fix(value[key], sub, _join(path, key), notes)
        return value
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [_fix(item, schema["items"], _join(path, index), notes) for index, item in enumerate(value)]
    return value


def conform(value: Any, schema: dict[str, Any]) -> tuple[Any, list[str]]:
    """A repaired copy of value and one note per change."""
    notes: list[str] = []
    return _fix(copy.deepcopy(value), schema, "", notes), notes


def _type_ok(value: Any, kinds: set[str]) -> bool:
    checks = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
              "string": lambda v: isinstance(v, str), "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
              "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
              "boolean": lambda v: isinstance(v, bool), "null": lambda v: v is None}
    return any(checks[kind](value) for kind in kinds if kind in checks)


def _check(value: Any, schema: dict[str, Any], path: str, out: list[str]) -> None:
    where = path or "输出"
    if "anyOf" in schema:
        attempts = []
        for branch in schema["anyOf"]:
            found: list[str] = []
            _check(value, branch, path, found)
            if not found:
                return
            attempts.append((branch, found))
        typed = [found for branch, found in attempts if _type_ok(value, _types(branch))]
        out.extend(typed[0] if typed else [f"{where} 的类型不对，应为" + "或".join(
            _TYPE_NAMES.get(k, k) for branch, _ in attempts for k in sorted(_types(branch)))])
        return
    kinds = _types(schema)
    if kinds and not _type_ok(value, kinds):
        out.append(f"{where} 应为" + "或".join(_TYPE_NAMES.get(k, k) for k in sorted(kinds)) + f"，实际是 {_show(value)[:40]}")
        return
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{where} 只能取 " + "、".join(_show(v) for v in schema["enum"][:10]) + f"，实际是 {_show(value)[:40]}")
        return
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            out.append(f"{where} 不能为空" if not value else f"{where} 太短")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(f"{where} 超过 {schema['maxLength']} 字（现在 {len(value)} 字）")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{where} 的格式不对：{_show(value)[:40]}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{where} 不能小于 {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{where} 不能大于 {schema['maximum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            out.append(f"{where} 至少要有 {schema['minItems']} 项（现在 {len(value)} 项）")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{where} 最多 {schema['maxItems']} 项（现在 {len(value)} 项）")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                _check(item, schema["items"], _join(path, index), out)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{where} 缺少字段 {key}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    out.append(f"{where} 多了 Schema 之外的字段 {key}")
        for key, sub in properties.items():
            if key in value and isinstance(sub, dict):
                _check(value[key], sub, _join(path, key), out)


def problems(value: Any, schema: dict[str, Any]) -> list[str]:
    """What still differs from the schema, at most LIMIT lines."""
    out: list[str] = []
    _check(value, schema, "", out)
    return out[:LIMIT]
