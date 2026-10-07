"""Deterministic DocumentationManifest and Material IR compiler.

This is an independent, non-installable contract slice.  It validates author
documentation, compiles a deliberately small Markdown subset into typed rich
text blocks, proves reference/coverage closure, and emits physically separate
audience slices.  It never reads a package, invokes a provider, or mutates
platform state.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


DOCUMENTATION_MANIFEST_SCHEMA = "documentation-manifest/1.0.0"
DOCUMENTATION_COVERAGE_SCHEMA = "documentation-coverage/1.0.0"
MATERIAL_REFERENCE_CATALOG_SCHEMA = "material-reference-catalog/1.0.0"
MATERIAL_IR_SCHEMA = "se-material-ir/1.0.0"
MATERIAL_SLICE_SCHEMA = "se-material-slice/1.0.0"
MATERIAL_COMPILATION_SCHEMA = "se-material-compilation/1.0.0"

AUDIENCES = ("public", "player", "room_host", "deployment_owner", "author_offline")
ONLINE_AUDIENCES = AUDIENCES[:-1]
SPOILER_CLASSES = frozenset({"none", "mechanics", "progressive", "full_story", "author_internal"})
MATERIAL_TYPES = frozenset({"catalog", "player_guide", "mechanics", "room_host_guide", "owner_story", "reference", "faq", "operations"})
DISPLAY_PURPOSES = frozenset({"catalog", "guide", "mechanics", "story", "search", "readme", "qq_help"})
_AUDIENCE_RANK = {name: index for index, name in enumerate(AUDIENCES)}
_DIGEST_POLICY = "sha256-canonical-json/1"
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,159}$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8})*$")
_BODY_REF_RE = re.compile(r"^author/documentation/[A-Za-z0-9_.@/-]+\.md$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_INLINE_TOKEN_RE = re.compile(r"(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`|\[[^\]\n]+\]\([^\s)]+\))")
_RAW_HTML_RE = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")

_MANIFEST_FIELDS = frozenset({
    "schema", "story_pack_ref", "story_pack_version", "default_locale", "locales",
    "digest_policy", "assets", "materials",
})
_ASSET_FIELDS = frozenset({"asset_ref", "path", "digest"})
_MATERIAL_FIELDS = frozenset({
    "material_id", "section_id", "material_type", "locale", "audience", "spoiler_class",
    "title", "summary", "body_ref", "source_refs", "related_material_ids",
    "display_purposes", "search_terms", "order", "required", "fallback_locale", "version",
})
_CATALOG_FIELDS = frozenset({"schema", "references"})
_REFERENCE_FIELDS = frozenset({"ref", "kind", "audience", "required"})
_COVERAGE_FIELDS = frozenset({"schema", "records"})
_COVERAGE_RECORD_FIELDS = frozenset({"ref", "status", "material_ids"})


@dataclass(frozen=True, slots=True)
class MaterialContractError(ValueError):
    code: str
    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.code}:{self.path}"


def _fail(code: str, path: str, reason: str) -> None:
    raise MaterialContractError(code, path, reason)


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("material.object_invalid", path, "field must be an object")
    return value


def _sequence(value: object, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("material.sequence_invalid", path, "field must be an array")
    return value


def _fields(value: Mapping[str, Any], expected: set[str] | frozenset[str], path: str) -> None:
    if set(value) != set(expected):
        _fail("material.fields_invalid", path, "fields are incomplete or unknown fields are present")


def _text(value: object, path: str, maximum: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > maximum:
        _fail("material.text_invalid", path, "field must be bounded, non-empty, trimmed text")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        _fail("material.text_invalid", path, "control characters are forbidden")
    return value


def _ref(value: object, path: str) -> str:
    result = _text(value, path, 160)
    if not _REF_RE.fullmatch(result) or ".." in result:
        _fail("material.reference_invalid", path, "field must be a stable reference")
    return result


def _source_ref(value: object, path: str) -> str:
    result = _text(value, path, 320)
    if result[0] in "/\\" or "\\" in result or any(char.isspace() or ord(char) < 32 for char in result):
        _fail("material.reference_invalid", path, "source ref must be normalized and whitespace-free")
    source_path = result.split("#", 1)[0]
    if not source_path or ".." in source_path.split("/") or re.match(r"^[A-Za-z]:", source_path):
        _fail("material.reference_invalid", path, "source ref must remain bundle-relative")
    return result


def _locale(value: object, path: str) -> str:
    result = _text(value, path, 40)
    if not _LOCALE_RE.fullmatch(result):
        _fail("material.locale_invalid", path, "locale is invalid")
    return result


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        _fail("material.boolean_invalid", path, "field must be boolean")
    return value


def _integer(value: object, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail("material.integer_invalid", path, f"field must be an integer >= {minimum}")
    return value


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail("material.non_canonical_value", "$", f"value is not canonical JSON: {exc}")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _text_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _refs(value: object, path: str) -> list[str]:
    result = [_ref(item, f"{path}[{index}]") for index, item in enumerate(_sequence(value, path))]
    if len(result) != len(set(result)):
        _fail("material.reference_duplicate", path, "references must be unique")
    return sorted(result)


def _source_refs(value: object, path: str) -> list[str]:
    result = [_source_ref(item, f"{path}[{index}]") for index, item in enumerate(_sequence(value, path))]
    if len(result) != len(set(result)):
        _fail("material.reference_duplicate", path, "source references must be unique")
    return sorted(result)


def _safe_path(value: object, path: str, *, body: bool = False) -> str:
    result = _text(value, path, 240)
    if result.startswith(("/", "\\")) or "\\" in result or ".." in result.split("/") or re.match(r"^[A-Za-z]:", result) or any(char in result for char in "?#"):
        _fail("material.path_invalid", path, "path must be bundle-relative and normalized")
    if body and not _BODY_REF_RE.fullmatch(result):
        _fail("material.path_invalid", path, "body_ref must be controlled author documentation Markdown")
    return result


def _safe_target(target: str, path: str, asset_paths: set[str]) -> str:
    if target.startswith("material:"):
        _ref(target.removeprefix("material:"), path)
        return target
    parsed = urlsplit(target)
    if parsed.scheme:
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            _fail("material.link_unsafe", path, "only ordinary HTTPS external links are allowed")
        return target
    normalized = _safe_path(target, path)
    if normalized not in asset_paths:
        _fail("material.link_undeclared", path, "local target is not a declared asset")
    return normalized


def _inline(text: str, path: str, asset_paths: set[str]) -> list[dict[str, Any]]:
    if not text or text != text.strip():
        _fail("material.markdown_invalid", path, "inline text must be non-empty and trimmed")
    spans: list[dict[str, Any]] = []
    cursor = 0
    for match in _INLINE_TOKEN_RE.finditer(text):
        if match.start() > cursor:
            plain = text[cursor:match.start()]
            if any(mark in plain for mark in ("**", "*", "`", "[", "](")):
                _fail("material.markdown_unsupported", path, "unbalanced or nested inline Markdown is unsupported")
            spans.append({"kind": "text", "text": plain})
        token = match.group(0)
        if token.startswith("**"):
            spans.append({"kind": "strong", "text": token[2:-2]})
        elif token.startswith("*"):
            spans.append({"kind": "emphasis", "text": token[1:-1]})
        elif token.startswith("`"):
            spans.append({"kind": "code", "text": token[1:-1]})
        else:
            label, target = token[1:].split("](", 1)
            spans.append({"kind": "link", "text": label, "target": _safe_target(target[:-1], path, asset_paths)})
        cursor = match.end()
    if cursor < len(text):
        plain = text[cursor:]
        if any(mark in plain for mark in ("**", "*", "`", "[", "](")):
            _fail("material.markdown_unsupported", path, "unbalanced or nested inline Markdown is unsupported")
        spans.append({"kind": "text", "text": plain})
    if not spans or any(not span["text"] for span in spans):
        _fail("material.markdown_invalid", path, "inline content is empty")
    return spans


def _plain(spans: Sequence[Mapping[str, Any]]) -> str:
    return "".join(str(span["text"]) for span in spans)


def compile_markdown_blocks(markdown: str, *, section_id: str, asset_paths: Sequence[str] = ()) -> list[dict[str, Any]]:
    """Compile a strict portable Markdown subset into typed RichText blocks."""
    _ref(section_id, "section_id")
    if not isinstance(markdown, str) or not markdown.strip() or markdown.startswith("\ufeff"):
        _fail("material.markdown_invalid", "body", "Markdown must be non-empty UTF-8 text without BOM")
    if "\r" in markdown or "\x00" in markdown or _RAW_HTML_RE.search(markdown):
        _fail("material.markdown_unsafe", "body", "raw HTML, CR and NUL are forbidden")
    if re.search(r"(?: {2}|\\)\n", markdown):
        _fail("material.markdown_unsafe", "body", "Markdown hard line breaks are forbidden")
    assets = set(asset_paths)
    lines = markdown.split("\n")
    while lines and not lines[-1]:
        lines.pop()
    blocks: list[dict[str, Any]] = []

    def add(kind: str, payload: Mapping[str, Any]) -> None:
        sequence = len(blocks)
        blocks.append({"block_ref": f"{section_id}.block.{sequence + 1}", "sequence": sequence, "kind": kind, **payload})

    index = 0
    while index < len(lines):
        line = lines[index]
        if not line:
            index += 1
            continue
        if line.startswith("```"):
            language = line[3:]
            if language and not re.fullmatch(r"[A-Za-z0-9_+-]{1,24}", language):
                _fail("material.markdown_unsupported", f"body.line[{index + 1}]", "code fence language is invalid")
            body: list[str] = []
            index += 1
            while index < len(lines) and lines[index] != "```":
                body.append(lines[index]); index += 1
            if index >= len(lines) or not body:
                _fail("material.markdown_invalid", f"body.line[{index + 1}]", "code fence is empty or unterminated")
            add("code", {"language": language or "text", "text": "\n".join(body)})
            index += 1
            continue
        if any(token in line for token in ("{{", "}}", "{%", "%}", "<%", "%>")):
            _fail("material.markdown_unsafe", f"body.line[{index + 1}]", "template syntax is forbidden")
        heading = re.fullmatch(r"(#{1,6}) ([^#].*)", line)
        if heading:
            spans = _inline(heading.group(2), f"body.line[{index + 1}]", assets)
            add("heading", {"level": len(heading.group(1)), "spans": spans, "text": _plain(spans)})
            index += 1
            continue
        image_match = re.fullmatch(r"!\[([^\]\n]+)\]\(([^\s)]+)\)", line)
        if image_match:
            target = _safe_path(image_match.group(2), f"body.line[{index + 1}]")
            if target not in assets:
                _fail("material.asset_undeclared", f"body.line[{index + 1}]", "image must reference a declared local asset")
            add("image", {"alt": _text(image_match.group(1), f"body.line[{index + 1}].alt", 300), "asset_ref": target})
            index += 1
            continue
        unordered = re.fullmatch(r"[-*+] (.+)", line)
        ordered = re.fullmatch(r"\d+\. (.+)", line)
        if unordered or ordered:
            is_ordered = ordered is not None
            items: list[dict[str, Any]] = []
            while index < len(lines):
                item = re.fullmatch(r"\d+\. (.+)", lines[index]) if is_ordered else re.fullmatch(r"[-*+] (.+)", lines[index])
                if not item:
                    break
                spans = _inline(item.group(1), f"body.line[{index + 1}]", assets)
                items.append({"spans": spans, "text": _plain(spans)})
                index += 1
            add("list", {"ordered": is_ordered, "items": items})
            continue
        if line.startswith("> "):
            quoted: list[str] = []
            while index < len(lines) and lines[index].startswith("> "):
                quoted.append(lines[index][2:]); index += 1
            spans = _inline(" ".join(quoted), f"body.line[{index - len(quoted) + 1}]", assets)
            add("quote", {"spans": spans, "text": _plain(spans)})
            continue
        if "|" in line and index + 1 < len(lines) and re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*", lines[index + 1]):
            def cells(row: str) -> list[str]:
                return [cell.strip() for cell in row.strip().strip("|").split("|")]
            headers = cells(line)
            if not headers or any(not cell for cell in headers):
                _fail("material.markdown_invalid", f"body.line[{index + 1}]", "table header is invalid")
            rows: list[list[str]] = []
            index += 2
            while index < len(lines) and lines[index] and "|" in lines[index]:
                row = cells(lines[index])
                if len(row) != len(headers) or any(not cell for cell in row):
                    _fail("material.markdown_invalid", f"body.line[{index + 1}]", "table row width is invalid")
                for col, cell in enumerate(row):
                    _inline(cell, f"body.line[{index + 1}].cell[{col}]", assets)
                rows.append(row); index += 1
            if not rows:
                _fail("material.markdown_invalid", f"body.line[{index + 1}]", "table needs a body row")
            for col, cell in enumerate(headers):
                _inline(cell, f"body.header[{col}]", assets)
            add("table", {"headers": headers, "rows": rows, "text_alternative": "; ".join(" / ".join(row) for row in [headers, *rows])})
            continue
        if line.startswith(("#", "    ", "\t")) or line in {"---", "***", "___"}:
            _fail("material.markdown_unsupported", f"body.line[{index + 1}]", "Markdown construct is unsupported")
        paragraph_lines = [line]
        index += 1
        while index < len(lines) and lines[index] and not re.match(r"^(#{1,6} |```|> |[-*+] |\d+\. |!\[)", lines[index]):
            if "|" in lines[index] and index + 1 < len(lines) and "---" in lines[index + 1]:
                break
            paragraph_lines.append(lines[index]); index += 1
        spans = _inline(" ".join(paragraph_lines), f"body.line[{index - len(paragraph_lines) + 1}]", assets)
        add("paragraph", {"spans": spans, "text": _plain(spans)})
    if not blocks:
        _fail("material.markdown_invalid", "body", "Markdown produced no blocks")
    return blocks


def _compile_catalog(value: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    catalog = _mapping(value, "reference_catalog")
    _fields(catalog, _CATALOG_FIELDS, "reference_catalog")
    if catalog["schema"] != MATERIAL_REFERENCE_CATALOG_SCHEMA:
        _fail("material.reference_catalog_incompatible", "reference_catalog.schema", "reference catalog schema is incompatible")
    result: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(_sequence(catalog["references"], "reference_catalog.references")):
        path = f"reference_catalog.references[{index}]"; item = _mapping(raw, path); _fields(item, _REFERENCE_FIELDS, path)
        ref = _source_ref(item["ref"], f"{path}.ref")
        audience = item["audience"]
        if audience not in AUDIENCES:
            _fail("material.audience_invalid", f"{path}.audience", "audience is not registered")
        if ref in result:
            _fail("material.reference_duplicate", f"{path}.ref", "catalog reference is duplicated")
        result[ref] = {"ref": ref, "kind": _ref(item["kind"], f"{path}.kind"), "audience": audience, "required": _boolean(item["required"], f"{path}.required")}
    return result


def _compile_coverage(value: Mapping[str, Any], catalog: Mapping[str, Mapping[str, Any]], materials: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    coverage = _mapping(value, "coverage"); _fields(coverage, _COVERAGE_FIELDS, "coverage")
    if coverage["schema"] != DOCUMENTATION_COVERAGE_SCHEMA:
        _fail("material.coverage_schema_incompatible", "coverage.schema", "coverage schema is incompatible")
    by_id: dict[str, list[Mapping[str, Any]]] = {}
    for item in materials:
        by_id.setdefault(str(item["material_id"]), []).append(item)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(_sequence(coverage["records"], "coverage.records")):
        path = f"coverage.records[{index}]"; item = _mapping(raw, path); _fields(item, _COVERAGE_RECORD_FIELDS, path)
        ref = _source_ref(item["ref"], f"{path}.ref")
        if ref in seen:
            _fail("material.coverage_duplicate", f"{path}.ref", "coverage reference is duplicated")
        if ref not in catalog:
            _fail("material.coverage_extra", f"{path}.ref", "coverage reference is not expected")
        status = item["status"]
        if status not in {"documented", "intentionally_internal", "not_applicable"}:
            _fail("material.coverage_status_invalid", f"{path}.status", "coverage status is invalid")
        material_ids = _refs(item["material_ids"], f"{path}.material_ids")
        if status == "documented" and not material_ids:
            _fail("material.coverage_incomplete", f"{path}.material_ids", "documented reference needs a material")
        if status != "documented" and material_ids:
            _fail("material.coverage_invalid", f"{path}.material_ids", "non-documented records cannot name materials")
        for material_id in material_ids:
            candidates = by_id.get(material_id)
            if not candidates or not any(ref in candidate["source_refs"] for candidate in candidates):
                _fail("material.coverage_invalid", f"{path}.material_ids", "material does not document the reference")
        records.append({"ref": ref, "status": status, "material_ids": material_ids}); seen.add(ref)
    expected = sorted(catalog)
    missing = sorted(set(catalog) - seen)
    if missing:
        _fail("material.coverage_incomplete", "coverage.records", "required references are missing")
    return {
        "schema": DOCUMENTATION_COVERAGE_SCHEMA,
        "expected": expected,
        "records": sorted(records, key=lambda item: item["ref"]),
        "extra": [], "missing": missing,
    }


def _render_spans(spans: Sequence[Mapping[str, Any]]) -> str:
    output: list[str] = []
    for span in spans:
        kind = span["kind"]
        if kind == "text": output.append(str(span["text"]))
        elif kind == "strong": output.append(f"**{span['text']}**")
        elif kind == "emphasis": output.append(f"*{span['text']}*")
        elif kind == "code": output.append(f"`{span['text']}`")
        elif kind == "link": output.append(f"[{span['text']}]({span['target']})")
        else: _fail("material.ir_invalid", "blocks.spans.kind", "unknown inline kind")
    return "".join(output)


def _render_blocks(blocks: Sequence[Mapping[str, Any]]) -> str:
    output: list[str] = []
    for block in blocks:
        kind = block["kind"]
        if kind == "heading": output.append("#" * min(int(block["level"]) + 2, 6) + " " + _render_spans(block["spans"]))
        elif kind == "paragraph": output.append(_render_spans(block["spans"]))
        elif kind == "quote": output.append("> " + _render_spans(block["spans"]))
        elif kind == "list":
            for index, item in enumerate(block["items"]):
                marker = f"{index + 1}." if block["ordered"] else "-"
                output.append(f"{marker} {_render_spans(item['spans'])}")
        elif kind == "code": output.append(f"```{block['language']}\n{block['text']}\n```")
        elif kind == "image": output.append(f"![{block['alt']}]({block['asset_ref']})")
        elif kind == "table":
            output.append("| " + " | ".join(block["headers"]) + " |")
            output.append("| " + " | ".join("---" for _ in block["headers"]) + " |")
            output.extend("| " + " | ".join(row) + " |" for row in block["rows"])
            output.append(f"Equivalent text: {block['text_alternative']}")
        else: _fail("material.ir_invalid", "blocks.kind", "unknown block kind")
        output.append("")
    return "\n".join(output).rstrip()


def render_readme(material_ir: Mapping[str, Any]) -> str:
    """Render the byte-stable default-locale README from validated Material IR."""
    validate_material_ir(material_ir)
    locale = str(material_ir["default_locale"])
    entries = [item for item in material_ir["materials"] if item["locale"] == locale and item["audience"] != "author_offline" and "readme" in item["display_purposes"]]
    safe = [item for item in entries if item["audience"] in {"public", "player"} and item["spoiler_class"] != "full_story"]
    restricted = [item for item in entries if item not in safe]
    lines = [
        f"# {material_ir['story_pack_ref']} {material_ir['story_pack_version']}", "",
        "## Player-safe contents", "",
    ]
    lines.extend(f"- {item['title']} (`{item['section_id']}`)" for item in safe)
    for item in safe:
        lines.extend(["", f"## {item['title']}", "", item["summary"], "", _render_blocks(item["blocks"])])
    if restricted:
        lines.extend(["", "# SPOILER WARNING — FULL STORY AND OPERATIONS", "", "The following sections are intended for authorized hosts and deployment owners."])
        for item in restricted:
            lines.extend(["", f"## {item['title']}", "", f"Audience: `{item['audience']}` · Spoiler: `{item['spoiler_class']}`", "", item["summary"], "", _render_blocks(item["blocks"])])
    return "\n".join(lines).rstrip() + "\n"


def compile_materials(
    manifest: Mapping[str, Any],
    documents: Mapping[str, str],
    reference_catalog: Mapping[str, Any],
    coverage: Mapping[str, Any],
    *,
    required_readme_audiences: Sequence[str] = ONLINE_AUDIENCES,
) -> dict[str, Any]:
    """Compile author inputs into immutable Material IR, slices, and README."""
    source = _mapping(manifest, "manifest"); _fields(source, _MANIFEST_FIELDS, "manifest")
    if source["schema"] != DOCUMENTATION_MANIFEST_SCHEMA:
        _fail("material.manifest_schema_incompatible", "manifest.schema", "manifest schema is incompatible")
    if source["digest_policy"] != _DIGEST_POLICY:
        _fail("material.digest_policy_invalid", "manifest.digest_policy", "digest policy is not frozen")
    story_pack_ref = _ref(source["story_pack_ref"], "manifest.story_pack_ref")
    story_pack_version = _ref(source["story_pack_version"], "manifest.story_pack_version")
    default_locale = _locale(source["default_locale"], "manifest.default_locale")
    locales = sorted(_locale(item, f"manifest.locales[{index}]") for index, item in enumerate(_sequence(source["locales"], "manifest.locales")))
    if len(locales) != len(set(locales)) or default_locale not in locales:
        _fail("material.locale_invalid", "manifest.locales", "locales must be unique and include the default")
    assets: list[dict[str, Any]] = []
    asset_paths: set[str] = set()
    asset_refs: set[str] = set()
    for index, raw in enumerate(_sequence(source["assets"], "manifest.assets")):
        path = f"manifest.assets[{index}]"; item = _mapping(raw, path); _fields(item, _ASSET_FIELDS, path)
        asset_path = _safe_path(item["path"], f"{path}.path")
        digest = _text(item["digest"], f"{path}.digest", 71)
        asset_ref = _ref(item["asset_ref"], f"{path}.asset_ref")
        if not _DIGEST_RE.fullmatch(digest) or asset_path in asset_paths or asset_ref in asset_refs:
            _fail("material.asset_invalid", path, "asset path/digest is invalid or duplicated")
        assets.append({"asset_ref": asset_ref, "path": asset_path, "digest": digest}); asset_paths.add(asset_path); asset_refs.add(asset_ref)
    catalog = _compile_catalog(reference_catalog)
    document_map = _mapping(documents, "documents")
    materials: list[dict[str, Any]] = []
    keys: set[tuple[str, str]] = set()
    sections: set[tuple[str, str]] = set()
    identity_contract: dict[str, tuple[Any, ...]] = {}
    for index, raw in enumerate(_sequence(source["materials"], "manifest.materials")):
        path = f"manifest.materials[{index}]"; item = _mapping(raw, path); _fields(item, _MATERIAL_FIELDS, path)
        material_id = _ref(item["material_id"], f"{path}.material_id"); section_id = _ref(item["section_id"], f"{path}.section_id")
        locale = _locale(item["locale"], f"{path}.locale")
        if locale not in locales: _fail("material.locale_invalid", f"{path}.locale", "locale is not declared")
        audience = item["audience"]
        if audience not in AUDIENCES: _fail("material.audience_invalid", f"{path}.audience", "audience is not registered")
        spoiler = item["spoiler_class"]
        if spoiler not in SPOILER_CLASSES: _fail("material.spoiler_class_invalid", f"{path}.spoiler_class", "spoiler class is not registered")
        if audience in {"public", "player"} and spoiler in {"full_story", "author_internal"}:
            _fail("material.spoiler_leak", path, "public/player material cannot carry full-story or author spoilers")
        material_type = item["material_type"]
        if material_type not in MATERIAL_TYPES: _fail("material.type_invalid", f"{path}.material_type", "material type is not registered")
        source_refs = _source_refs(item["source_refs"], f"{path}.source_refs")
        for ref in source_refs:
            descriptor = catalog.get(ref)
            if descriptor is None: _fail("material.reference_unresolved", f"{path}.source_refs", "source reference is unresolved")
            if _AUDIENCE_RANK[audience] < _AUDIENCE_RANK[str(descriptor["audience"])]:
                _fail("material.audience_violation", f"{path}.source_refs", "material would expose a restricted reference")
        related = _refs(item["related_material_ids"], f"{path}.related_material_ids")
        purposes = sorted(_text(value, f"{path}.display_purposes[{i}]", 40) for i, value in enumerate(_sequence(item["display_purposes"], f"{path}.display_purposes")))
        if not purposes or len(purposes) != len(set(purposes)) or set(purposes) - DISPLAY_PURPOSES:
            _fail("material.display_purpose_invalid", f"{path}.display_purposes", "display purposes are invalid")
        terms = sorted(
            (_text(value, f"{path}.search_terms[{i}]", 120) for i, value in enumerate(_sequence(item["search_terms"], f"{path}.search_terms"))),
            key=str.casefold,
        )
        if len(terms) != len(set(terms)): _fail("material.search_term_duplicate", f"{path}.search_terms", "search terms must be unique")
        body_ref = _safe_path(item["body_ref"], f"{path}.body_ref", body=True)
        body = document_map.get(body_ref)
        if not isinstance(body, str): _fail("material.documentation_missing", f"documents.{body_ref}", "body document is missing")
        fallback_locale = item["fallback_locale"]
        if fallback_locale is not None:
            fallback_locale = _locale(fallback_locale, f"{path}.fallback_locale")
            if fallback_locale != default_locale or locale == default_locale:
                _fail("material.locale_fallback_invalid", f"{path}.fallback_locale", "only non-default entries may fall back to default locale")
        key = (material_id, locale)
        if key in keys or (section_id, locale) in sections:
            _fail("material.identity_duplicate", path, "material or section identity is duplicated in the locale")
        keys.add(key); sections.add((section_id, locale))
        contract = (section_id, material_type, audience, spoiler, _integer(item["order"], f"{path}.order"), _boolean(item["required"], f"{path}.required"), _ref(item["version"], f"{path}.version"))
        if material_id in identity_contract and identity_contract[material_id] != contract:
            _fail("material.translation_contract_mismatch", path, "translations must preserve identity, audience, type and order")
        identity_contract[material_id] = contract
        blocks = compile_markdown_blocks(body, section_id=section_id, asset_paths=sorted(asset_paths))
        materials.append({
            "material_id": material_id, "section_id": section_id, "material_type": material_type,
            "locale": locale, "audience": audience, "spoiler_class": spoiler,
            "title": _text(item["title"], f"{path}.title", 200), "summary": _text(item["summary"], f"{path}.summary", 600),
            "body_sha256": _text_digest(body), "blocks": blocks,
            "source_refs": source_refs, "related_material_ids": related,
            "display_purposes": purposes, "search_terms": terms,
            "order": contract[4], "required": contract[5], "fallback_locale": fallback_locale, "version": contract[6],
        })
    if not materials:
        _fail("material.materials_empty", "manifest.materials", "manifest needs at least one material")
    ids = {item["material_id"] for item in materials}
    default_ids = {item["material_id"] for item in materials if item["locale"] == default_locale}
    if ids != default_ids:
        _fail("material.locale_missing", "manifest.materials", "every material identity needs a default-locale source")
    default_entries = [item for item in materials if item["locale"] == default_locale and "readme" in item["display_purposes"]]
    required_audiences = set(required_readme_audiences)
    if not required_audiences or required_audiences - set(ONLINE_AUDIENCES):
        _fail("material.audience_invalid", "required_readme_audiences", "required README audiences are invalid")
    missing_audiences = required_audiences - {str(item["audience"]) for item in default_entries}
    if missing_audiences:
        _fail("material.documentation_missing", "manifest.materials", "default README source lacks a required audience section")
    for item in materials:
        if item["required"] and item["material_id"] not in default_ids:
            _fail("material.locale_missing", "manifest.materials", "required material lacks default locale")
        for related in item["related_material_ids"]:
            if related not in ids: _fail("material.material_ref_unresolved", f"materials.{item['material_id']}.related_material_ids", "related material is missing")
            targets = [candidate for candidate in materials if candidate["material_id"] == related and candidate["locale"] in {item["locale"], default_locale}]
            if not targets or min(_AUDIENCE_RANK[target["audience"]] for target in targets) > _AUDIENCE_RANK[item["audience"]]:
                _fail("material.audience_violation", f"materials.{item['material_id']}.related_material_ids", "related material is more restricted")
        linked_ids: set[str] = set()
        for block in item["blocks"]:
            span_groups = [block.get("spans", [])]
            span_groups.extend(entry.get("spans", []) for entry in block.get("items", []))
            for spans in span_groups:
                for span in spans:
                    target = span.get("target")
                    if isinstance(target, str) and target.startswith("material:"):
                        linked_ids.add(target.removeprefix("material:"))
        if linked_ids - set(item["related_material_ids"]):
            _fail("material.material_link_undeclared", f"materials.{item['material_id']}.blocks", "material links must be declared in related_material_ids")
    materials.sort(key=lambda item: (item["locale"], item["order"], item["material_id"]))
    compiled_coverage = _compile_coverage(coverage, catalog, materials)
    source_material = {"manifest": source, "documents": {key: document_map[key] for key in sorted(document_map)}, "reference_catalog": reference_catalog, "coverage": coverage}
    ir: dict[str, Any] = {
        "schema": MATERIAL_IR_SCHEMA, "story_pack_ref": story_pack_ref, "story_pack_version": story_pack_version,
        "default_locale": default_locale, "locales": locales, "digest_policy": _DIGEST_POLICY,
        "assets": sorted(assets, key=lambda item: item["asset_ref"]),
        "reference_index": [catalog[ref] for ref in sorted(catalog)], "materials": materials,
        "coverage": compiled_coverage, "source_sha256": _digest(source_material), "coverage_sha256": _digest(compiled_coverage),
    }
    ir["material_ir_sha256"] = _digest(ir)
    validate_material_ir(ir)
    slices: list[dict[str, Any]] = []
    for locale in locales:
        for audience in ONLINE_AUDIENCES:
            allowed = _AUDIENCE_RANK[audience]
            selected: list[dict[str, Any]] = []
            fallback_used: list[str] = []
            for material_id in sorted(ids):
                candidates = [item for item in materials if item["material_id"] == material_id and _AUDIENCE_RANK[item["audience"]] <= allowed]
                localized = next((item for item in candidates if item["locale"] == locale), None)
                if localized is None and locale != default_locale:
                    localized = next((item for item in candidates if item["locale"] == default_locale), None)
                    if localized is not None: fallback_used.append(material_id)
                if localized is not None: selected.append(localized)
            selected.sort(key=lambda item: (item["order"], item["material_id"]))
            toc = [{"material_id": item["material_id"], "section_id": item["section_id"], "title": item["title"], "order": item["order"]} for item in selected]
            search = [{"material_id": item["material_id"], "section_id": item["section_id"], "title": item["title"], "summary": item["summary"], "terms": item["search_terms"]} for item in selected if "search" in item["display_purposes"]]
            slice_value: dict[str, Any] = {"schema": MATERIAL_SLICE_SCHEMA, "story_pack_ref": story_pack_ref, "story_pack_version": story_pack_version, "locale": locale, "effective_audience": audience, "fallback_material_ids": sorted(fallback_used), "toc": toc, "materials": selected, "search_index": search}
            slice_value["slice_sha256"] = _digest(slice_value); slices.append(slice_value)
    readme = render_readme(ir)
    return {
        "schema": MATERIAL_COMPILATION_SCHEMA, "material_ir": ir, "slices": slices,
        "readme_files": {"README.md": readme}, "readme_sha256": _text_digest(readme),
        "model_calls": 0, "installable": "not_verified", "integrated_with_dev6": "not_verified",
    }


def _strict_json(path: Path, *, maximum_bytes: int = 2_000_000) -> tuple[dict[str, Any], bytes]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        _fail("material.candidate_file_missing", str(path.name), f"candidate file cannot be read: {exc}")
    if not payload or len(payload) > maximum_bytes:
        _fail("material.candidate_file_invalid", str(path.name), "candidate file is empty or exceeds its size limit")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                _fail("material.candidate_json_duplicate", str(path.name), f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        decoded = payload.decode("utf-8")
        if decoded.startswith("\ufeff"):
            _fail("material.candidate_file_invalid", str(path.name), "candidate JSON must not contain a BOM")
        value = json.loads(decoded, object_pairs_hook=pairs, parse_constant=lambda token: _fail("material.candidate_json_invalid", str(path.name), f"non-finite number: {token}"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail("material.candidate_json_invalid", str(path.name), f"candidate JSON is invalid: {exc}")
    return dict(_mapping(value, str(path.name))), payload


def _candidate_path(root: Path, relative: object, path: str) -> Path:
    normalized = _safe_path(relative, path)
    candidate = (root / normalized).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError:
        _fail("material.path_invalid", path, "candidate reference escapes Story Pack root")
    if not candidate.is_file():
        _fail("material.candidate_file_missing", path, "referenced candidate source file is absent")
    return candidate


def _raw_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _candidate_digest(value: object, path: str) -> str:
    result = _text(value, path, 64)
    if not re.fullmatch(r"[0-9a-f]{64}", result):
        _fail("material.candidate_digest_invalid", path, "candidate digest must be lowercase raw SHA-256")
    return result


def compile_story_pack_material_candidate(story_pack_root: str | Path) -> dict[str, Any]:
    """Adapt the Thirteenth Seat v02 author candidate into public Engine contracts.

    The adapter reads exactly the three declared candidate JSON documents plus
    their digest-bound source files.  The returned bundle remains explicitly
    non-installable and is not wired into the dev6 compiler or release surface.
    """
    try:
        root = Path(story_pack_root).resolve(strict=True)
    except OSError as exc:
        _fail("material.candidate_root_invalid", "story_pack_root", f"Story Pack root is unavailable: {exc}")
    if not root.is_dir():
        _fail("material.candidate_root_invalid", "story_pack_root", "Story Pack root must be a directory")
    manifest_path = _candidate_path(root, "author/se1/v02/documentation_manifest.json", "candidate.manifest")
    catalog_path = _candidate_path(root, "author/se1/v02/material_catalog.json", "candidate.catalog")
    coverage_path = _candidate_path(root, "author/se1/v02/material_coverage.json", "candidate.coverage")
    manifest, manifest_bytes = _strict_json(manifest_path)
    catalog, catalog_bytes = _strict_json(catalog_path)
    candidate_coverage, coverage_bytes = _strict_json(coverage_path)

    manifest_fields = {"schema", "candidate_version", "installable", "story_pack_ref", "locale", "requirement_refs", "catalog_ref", "coverage_ref", "readme_source_ref", "audience_contract", "markdown_contract", "compile_contract", "entries"}
    catalog_fields = {"schema", "candidate_version", "installable", "story_pack_ref", "locale", "slice_policy", "source_authority", "materials"}
    coverage_fields = {"schema", "candidate_version", "installable", "story_pack_ref", "locale", "manifest_ref", "catalog_ref", "digest_policy", "counts", "records", "release_coverage_complete", "unmet_release_gates"}
    _fields(manifest, manifest_fields, "candidate.manifest"); _fields(catalog, catalog_fields, "candidate.catalog"); _fields(candidate_coverage, coverage_fields, "candidate.coverage")
    if manifest["schema"] != "sp-documentation-manifest-candidate/0.2" or catalog["schema"] != "sp-role-aware-material-catalog-candidate/0.2" or candidate_coverage["schema"] != "sp-role-aware-material-coverage-candidate/0.2":
        _fail("material.candidate_schema_incompatible", "candidate", "candidate schemas are incompatible")
    if any(value["candidate_version"] != "unassigned" or value["installable"] is not False for value in (manifest, catalog, candidate_coverage)):
        _fail("material.candidate_release_boundary_invalid", "candidate", "candidate must remain unassigned and non-installable")
    identity = _ref(manifest["story_pack_ref"], "candidate.manifest.story_pack_ref")
    locale = _locale(manifest["locale"], "candidate.manifest.locale")
    requirement_refs = _refs(manifest["requirement_refs"], "candidate.manifest.requirement_refs")
    if not requirement_refs:
        _fail("material.candidate_coverage_incomplete", "candidate.manifest.requirement_refs", "candidate must cite its governing requirements")
    if any(value["story_pack_ref"] != identity or value["locale"] != locale for value in (catalog, candidate_coverage)):
        _fail("material.candidate_identity_mismatch", "candidate", "candidate identity/locale differs across inputs")
    if manifest["catalog_ref"] != "author/se1/v02/material_catalog.json" or manifest["coverage_ref"] != "author/se1/v02/material_coverage.json":
        _fail("material.candidate_reference_invalid", "candidate.manifest", "candidate manifest does not bind the exact catalog/coverage paths")

    readme_ref = _mapping(manifest["readme_source_ref"], "candidate.manifest.readme_source_ref")
    _fields(readme_ref, {"path", "sha256", "role"}, "candidate.manifest.readme_source_ref")
    if readme_ref["role"] != "composite_author_source_only_not_runtime_authorization":
        _fail("material.candidate_authority_invalid", "candidate.manifest.readme_source_ref.role", "root README cannot become runtime authorization")
    readme_path = _candidate_path(root, readme_ref["path"], "candidate.manifest.readme_source_ref.path")
    if _raw_sha256(readme_path.read_bytes()) != _candidate_digest(readme_ref["sha256"], "candidate.manifest.readme_source_ref.sha256"):
        _fail("material.candidate_digest_mismatch", "candidate.manifest.readme_source_ref", "root README digest differs")

    audience_contract = _mapping(manifest["audience_contract"], "candidate.manifest.audience_contract")
    _fields(audience_contract, {"allowed", "human_gm_audience", "owner_audience", "manifest_is_authoritative", "title_inheritance_allowed"}, "candidate.manifest.audience_contract")
    allowed_audiences = list(_sequence(audience_contract["allowed"], "candidate.manifest.audience_contract.allowed"))
    if allowed_audiences != ["public", "player", "room_host", "deployment_owner"] or audience_contract["human_gm_audience"] != "room_host" or audience_contract["owner_audience"] != "deployment_owner" or audience_contract["manifest_is_authoritative"] is not True or audience_contract["title_inheritance_allowed"] is not False:
        _fail("material.candidate_audience_contract_invalid", "candidate.manifest.audience_contract", "candidate audience boundary is not frozen")
    markdown_contract = _mapping(manifest["markdown_contract"], "candidate.manifest.markdown_contract")
    _fields(markdown_contract, {"media_type", "encoding", "allowed_constructs", "forbidden_constructs", "natural_paragraphs_required"}, "candidate.manifest.markdown_contract")
    required_allowed = {"heading", "paragraph", "list", "table", "blockquote", "emphasis", "controlled_link", "command_example", "declared_local_image"}
    required_forbidden = {"raw_html", "css", "javascript", "iframe", "remote_script", "remote_font", "event_attribute", "data_url", "template", "executable_code"}
    if markdown_contract["media_type"] != "text/markdown" or markdown_contract["encoding"] != "utf-8" or set(markdown_contract["allowed_constructs"]) != required_allowed or set(markdown_contract["forbidden_constructs"]) != required_forbidden or markdown_contract["natural_paragraphs_required"] is not True:
        _fail("material.candidate_markdown_contract_invalid", "candidate.manifest.markdown_contract", "Markdown safety contract is incomplete")
    compile_contract = _mapping(manifest["compile_contract"], "candidate.manifest.compile_contract")
    _fields(compile_contract, {"runtime_model_calls", "runtime_humanizer_calls", "root_readme_is_authority_boundary", "server_authorizes_before_slice_selection", "physical_slice_per_audience_and_locale", "combined_runtime_payload_allowed", "client_side_redaction_allowed", "deterministic"}, "candidate.manifest.compile_contract")
    expected_compile = {"runtime_model_calls": 0, "runtime_humanizer_calls": 0, "root_readme_is_authority_boundary": False, "server_authorizes_before_slice_selection": True, "physical_slice_per_audience_and_locale": True, "combined_runtime_payload_allowed": False, "client_side_redaction_allowed": False, "deterministic": True}
    if dict(compile_contract) != expected_compile:
        _fail("material.candidate_compile_contract_invalid", "candidate.manifest.compile_contract", "candidate compile boundary is unsafe")

    slice_policy = _mapping(catalog["slice_policy"], "candidate.catalog.slice_policy")
    _fields(slice_policy, {"selection_authority", "combined_runtime_payload_allowed", "client_side_redaction_allowed", "search_index_partition", "room_private_data_in_static_materials_allowed"}, "candidate.catalog.slice_policy")
    if slice_policy["selection_authority"] != "server_authorizes_audience_before_selecting_one_physical_slice" or slice_policy["combined_runtime_payload_allowed"] is not False or slice_policy["client_side_redaction_allowed"] is not False or slice_policy["search_index_partition"] != "one_index_per_audience_and_locale" or slice_policy["room_private_data_in_static_materials_allowed"] is not False:
        _fail("material.candidate_slice_policy_invalid", "candidate.catalog.slice_policy", "physical slice policy is unsafe")

    source_authority_fields = {"source_ref", "sha256"}
    authority_receipt: list[dict[str, str]] = []
    authority_seen: set[str] = set()
    for index, raw in enumerate(_sequence(catalog["source_authority"], "candidate.catalog.source_authority")):
        path = f"candidate.catalog.source_authority[{index}]"; authority = _mapping(raw, path); _fields(authority, source_authority_fields, path)
        source_ref = _safe_path(authority["source_ref"], f"{path}.source_ref")
        if source_ref in authority_seen: _fail("material.reference_duplicate", f"{path}.source_ref", "source authority path is duplicated")
        source_path = _candidate_path(root, source_ref, f"{path}.source_ref"); expected = _candidate_digest(authority["sha256"], f"{path}.sha256")
        if _raw_sha256(source_path.read_bytes()) != expected: _fail("material.candidate_digest_mismatch", path, "source authority digest differs")
        authority_receipt.append({"source_ref": source_ref, "sha256": expected}); authority_seen.add(source_ref)

    coverage_manifest_ref = _mapping(candidate_coverage["manifest_ref"], "candidate.coverage.manifest_ref")
    coverage_catalog_ref = _mapping(candidate_coverage["catalog_ref"], "candidate.coverage.catalog_ref")
    for value, expected_path, payload, path in (
        (coverage_manifest_ref, "author/se1/v02/documentation_manifest.json", manifest_bytes, "candidate.coverage.manifest_ref"),
        (coverage_catalog_ref, "author/se1/v02/material_catalog.json", catalog_bytes, "candidate.coverage.catalog_ref"),
    ):
        _fields(value, {"path", "sha256"}, path)
        if value["path"] != expected_path or _candidate_digest(value["sha256"], f"{path}.sha256") != _raw_sha256(payload):
            _fail("material.candidate_digest_mismatch", path, "coverage input digest differs")
    digest_policy = _mapping(candidate_coverage["digest_policy"], "candidate.coverage.digest_policy")
    _fields(digest_policy, {"file_digest", "material_content_digest", "unknown_or_duplicate_ref", "mismatch"}, "candidate.coverage.digest_policy")
    if dict(digest_policy) != {"file_digest": "sha256_raw_bytes", "material_content_digest": "sha256_utf8_markdown_body", "unknown_or_duplicate_ref": "reject", "mismatch": "reject_without_partial_install"}:
        _fail("material.candidate_digest_policy_invalid", "candidate.coverage.digest_policy", "coverage digest policy is not frozen")

    manifest_entry_fields = {"material_ref", "audience", "spoiler_class", "body_ref", "physical_slice", "required", "sort_order", "fallback_locale", "digest_policy"}
    catalog_material_fields = {"material_ref", "audience", "access_guard", "spoiler_class", "physical_slice", "title", "summary", "markdown_body", "source_refs", "requirement_refs", "sort_order", "required", "fallback_locale"}
    coverage_record_fields = {"material_ref", "decision", "audience", "section_ref", "content_sha256", "source_refs", "requirement_refs", "reason"}
    manifest_entries: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(_sequence(manifest["entries"], "candidate.manifest.entries")):
        path = f"candidate.manifest.entries[{index}]"; entry = _mapping(raw, path); _fields(entry, manifest_entry_fields, path)
        material_ref = _ref(entry["material_ref"], f"{path}.material_ref")
        if material_ref in manifest_entries: _fail("material.identity_duplicate", f"{path}.material_ref", "candidate material is duplicated")
        manifest_entries[material_ref] = entry
    catalog_materials: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(_sequence(catalog["materials"], "candidate.catalog.materials")):
        path = f"candidate.catalog.materials[{index}]"; item = _mapping(raw, path); _fields(item, catalog_material_fields, path)
        material_ref = _ref(item["material_ref"], f"{path}.material_ref")
        if material_ref in catalog_materials: _fail("material.identity_duplicate", f"{path}.material_ref", "catalog material is duplicated")
        catalog_materials[material_ref] = item
    coverage_records: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(_sequence(candidate_coverage["records"], "candidate.coverage.records")):
        path = f"candidate.coverage.records[{index}]"; record = _mapping(raw, path); _fields(record, coverage_record_fields, path)
        material_ref = _ref(record["material_ref"], f"{path}.material_ref")
        if material_ref in coverage_records: _fail("material.coverage_duplicate", f"{path}.material_ref", "candidate coverage material is duplicated")
        coverage_records[material_ref] = record
    if set(manifest_entries) != set(catalog_materials) or set(catalog_materials) != set(coverage_records):
        _fail("material.candidate_coverage_incomplete", "candidate", "manifest, catalog and coverage material sets differ")

    documents: dict[str, str] = {}
    native_materials: list[dict[str, Any]] = []
    source_audiences: dict[str, str] = {}
    coverage_by_source: dict[str, set[str]] = {}
    physical_paths: dict[str, str] = {}
    audience_counts = {audience: 0 for audience in allowed_audiences}
    for material_ref in sorted(catalog_materials):
        entry = manifest_entries[material_ref]; item = catalog_materials[material_ref]; record = coverage_records[material_ref]
        audience = item["audience"]
        if audience not in allowed_audiences or entry["audience"] != audience or record["audience"] != audience:
            _fail("material.candidate_audience_mismatch", material_ref, "candidate audience differs or is not allowed")
        audience_counts[audience] += 1
        physical_slice = _safe_path(item["physical_slice"], f"candidate.catalog.materials.{material_ref}.physical_slice")
        expected_prefix = f"materials/{locale}/{audience}/"
        if not physical_slice.startswith(expected_prefix) or not physical_slice.endswith(".json") or entry["physical_slice"] != physical_slice or record["section_ref"] != physical_slice:
            _fail("material.candidate_physical_slice_invalid", material_ref, "physical slice path is missing, duplicated or mismatched")
        prior_physical_path = physical_paths.get(audience)
        if prior_physical_path is not None and prior_physical_path != physical_slice:
            _fail("material.candidate_physical_slice_invalid", material_ref, "one audience declares multiple physical slice files")
        if physical_slice in physical_paths.values() and prior_physical_path != physical_slice:
            _fail("material.candidate_physical_slice_invalid", material_ref, "different audiences share one physical slice file")
        physical_paths[audience] = physical_slice
        body = item["markdown_body"]
        if not isinstance(body, str): _fail("material.markdown_invalid", material_ref, "embedded Markdown body is not text")
        expected_body_ref = f"author/se1/v02/material_catalog.json#materials/{material_ref}/markdown_body"
        if entry["body_ref"] != expected_body_ref or entry["digest_policy"] != "sha256_utf8_markdown_body":
            _fail("material.candidate_reference_invalid", material_ref, "embedded body reference/digest policy differs")
        content_digest = _raw_sha256(body.encode("utf-8"))
        if content_digest != _candidate_digest(record["content_sha256"], f"candidate.coverage.records.{material_ref}.content_sha256"):
            _fail("material.candidate_digest_mismatch", material_ref, "Markdown content digest differs")
        source_refs = _source_refs(item["source_refs"], f"candidate.catalog.materials.{material_ref}.source_refs")
        requirement_refs = _refs(item["requirement_refs"], f"candidate.catalog.materials.{material_ref}.requirement_refs")
        if record["decision"] != "documented" or _source_refs(record["source_refs"], f"candidate.coverage.records.{material_ref}.source_refs") != source_refs or _refs(record["requirement_refs"], f"candidate.coverage.records.{material_ref}.requirement_refs") != requirement_refs:
            _fail("material.candidate_coverage_invalid", material_ref, "coverage record does not match catalog material")
        if any(entry[key] != item[key] for key in ("spoiler_class", "sort_order", "required", "fallback_locale")) or entry["fallback_locale"] != locale:
            _fail("material.candidate_manifest_mismatch", material_ref, "manifest entry does not match catalog material")
        virtual_body_ref = f"author/documentation/{material_ref}.md"
        documents[virtual_body_ref] = body
        material_type = "catalog" if audience == "public" else "player_guide" if audience == "player" else "room_host_guide" if audience == "room_host" else "owner_story"
        purposes = ["catalog", "readme", "search"] if audience == "public" else ["guide", "readme", "search"] if audience != "deployment_owner" else ["readme", "search", "story"]
        if "opening-loop" in material_ref: purposes.append("mechanics")
        if "quickstart" in material_ref: purposes.extend(["catalog", "qq_help"])
        native_materials.append({
            "material_id": material_ref, "section_id": material_ref + ".section", "material_type": material_type,
            "locale": locale, "audience": audience, "spoiler_class": item["spoiler_class"],
            "title": item["title"], "summary": item["summary"], "body_ref": virtual_body_ref,
            "source_refs": source_refs, "related_material_ids": [], "display_purposes": sorted(set(purposes)),
            "search_terms": [item["title"]], "order": item["sort_order"], "required": item["required"],
            "fallback_locale": None, "version": "candidate.0.2",
        })
        for source_ref in source_refs:
            prior = source_audiences.get(source_ref)
            if prior is None or _AUDIENCE_RANK[audience] < _AUDIENCE_RANK[prior]: source_audiences[source_ref] = audience
            coverage_by_source.setdefault(source_ref, set()).add(material_ref)

    counts = _mapping(candidate_coverage["counts"], "candidate.coverage.counts")
    _fields(counts, {"materials", "public", "player", "room_host", "deployment_owner", "documented", "intentionally_internal", "not_applicable"}, "candidate.coverage.counts")
    for key in counts: _integer(counts[key], f"candidate.coverage.counts.{key}")
    expected_counts = {"materials": len(catalog_materials), "public": audience_counts["public"], "player": audience_counts["player"], "room_host": audience_counts["room_host"], "deployment_owner": audience_counts["deployment_owner"], "documented": len(coverage_records), "intentionally_internal": 0, "not_applicable": 0}
    if dict(counts) != expected_counts:
        _fail("material.candidate_coverage_invalid", "candidate.coverage.counts", "coverage counts do not match records")
    if candidate_coverage["release_coverage_complete"] is not False or not list(_sequence(candidate_coverage["unmet_release_gates"], "candidate.coverage.unmet_release_gates")):
        _fail("material.candidate_release_boundary_invalid", "candidate.coverage", "unassigned candidate cannot claim release completion")

    native_manifest = {
        "schema": DOCUMENTATION_MANIFEST_SCHEMA, "story_pack_ref": identity, "story_pack_version": "unassigned",
        "default_locale": locale, "locales": [locale], "digest_policy": _DIGEST_POLICY, "assets": [],
        "materials": native_materials,
    }
    native_catalog = {"schema": MATERIAL_REFERENCE_CATALOG_SCHEMA, "references": [{"ref": ref, "kind": "story_pack_source", "audience": source_audiences[ref], "required": True} for ref in sorted(source_audiences)]}
    native_coverage = {"schema": DOCUMENTATION_COVERAGE_SCHEMA, "records": [{"ref": ref, "status": "documented", "material_ids": sorted(coverage_by_source[ref])} for ref in sorted(coverage_by_source)]}
    compilation = compile_materials(native_manifest, documents, native_catalog, native_coverage, required_readme_audiences=allowed_audiences)
    if set(physical_paths) != set(ONLINE_AUDIENCES):
        _fail("material.candidate_physical_slice_missing", "candidate.manifest.entries", "public/player/room_host/deployment_owner must each declare one physical slice")

    artifact_paths: dict[str, Any] = {
        "documentation_manifest": "materials/documentation-manifest.json",
        "documentation_coverage": "materials/documentation-coverage.json",
        "material_ir": "materials/index.json",
        "readme": "README.md",
        "slices": {audience: physical_paths[audience] for audience in ONLINE_AUDIENCES},
    }
    generated_paths = {
        str(artifact_paths["documentation_manifest"]),
        str(artifact_paths["documentation_coverage"]),
        str(artifact_paths["material_ir"]),
        str(artifact_paths["readme"]),
        *physical_paths.values(),
    }
    collisions = sorted(generated_paths.intersection(documents))
    if collisions or len(generated_paths) != 8:
        _fail("material.candidate_path_collision", "candidate.bundle.files", "generated and authored artifact paths collide")
    platform_files: dict[str, Any] = {
        artifact_paths["documentation_manifest"]: native_manifest,
        artifact_paths["documentation_coverage"]: native_coverage,
        artifact_paths["material_ir"]: compilation["material_ir"],
        artifact_paths["readme"]: compilation["readme_files"]["README.md"],
        **{path: documents[path] for path in sorted(documents)},
    }
    bundle_files: dict[str, Any] = {
        artifact_paths["material_ir"]: compilation["material_ir"],
        artifact_paths["readme"]: compilation["readme_files"]["README.md"],
    }
    for audience in ONLINE_AUDIENCES:
        slice_value = next(item for item in compilation["slices"] if item["locale"] == locale and item["effective_audience"] == audience)
        if not slice_value["materials"]:
            _fail("material.candidate_physical_slice_missing", f"candidate.{audience}", "declared physical audience slice has no authored material")
        validate_material_slice(slice_value)
        bundle_files[physical_paths[audience]] = slice_value
        platform_files[physical_paths[audience]] = slice_value
    bundle_file_digests = {
        path: _text_digest(value) if isinstance(value, str) else _digest(value)
        for path, value in sorted(platform_files.items())
    }
    bundle: dict[str, Any] = {
        "schema": "se-material-bundle-candidate/1.0.0", "candidate_version": "unassigned", "installable": False,
        "story_pack_ref": identity, "locale": locale, "combined_runtime_payload_allowed": False,
        "files": {key: bundle_files[key] for key in sorted(bundle_files)},
    }
    bundle["bundle_sha256"] = _digest(bundle)
    return {
        **compilation,
        "documentation_manifest": native_manifest,
        "documentation_coverage": native_coverage,
        "artifact_paths": artifact_paths,
        "bundle_file_digests": bundle_file_digests,
        "candidate_adapter": {
            "schema": "se-material-candidate-adapter-receipt/1.0.0", "candidate_version": "unassigned", "installable": False,
            "story_pack_ref": identity, "manifest_sha256": _raw_sha256(manifest_bytes), "catalog_sha256": _raw_sha256(catalog_bytes),
            "coverage_sha256": _raw_sha256(coverage_bytes), "source_authority": authority_receipt,
            "physical_slice_paths": [physical_paths[audience] for audience in ONLINE_AUDIENCES], "model_calls": 0,
        },
        "candidate_bundle": bundle,
    }


def compile_documentation_manifest(manifest: Mapping[str, Any], documents: Mapping[str, str], reference_catalog: Mapping[str, Any], coverage: Mapping[str, Any]) -> dict[str, Any]:
    """Compatibility name for the standalone documentation compilation entry."""
    return compile_materials(manifest, documents, reference_catalog, coverage)


def _validate_spans(value: object, path: str) -> None:
    spans = _sequence(value, path)
    if not spans:
        _fail("material.ir_invalid", path, "rich text span list is empty")
    for index, raw in enumerate(spans):
        span_path = f"{path}[{index}]"; span = _mapping(raw, span_path)
        kind = span.get("kind")
        expected = {"kind", "text", "target"} if kind == "link" else {"kind", "text"}
        _fields(span, expected, span_path)
        if kind not in {"text", "strong", "emphasis", "code", "link"}:
            _fail("material.ir_invalid", f"{span_path}.kind", "inline kind is invalid")
        text = span["text"]
        if not isinstance(text, str) or not text or not text.strip() or len(text) > 4000 or "\n" in text:
            _fail("material.ir_invalid", f"{span_path}.text", "inline text is invalid")
        if kind == "link":
            target = _text(span["target"], f"{span_path}.target", 500)
            if target.startswith("material:"):
                _ref(target.removeprefix("material:"), f"{span_path}.target")
            else:
                parsed = urlsplit(target)
                if parsed.scheme:
                    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                        _fail("material.link_unsafe", f"{span_path}.target", "external link is unsafe")
                else:
                    _safe_path(target, f"{span_path}.target")


def _validate_block(value: object, path: str, section_id: str, sequence: int) -> None:
    block = _mapping(value, path); kind = block.get("kind")
    base = {"block_ref", "sequence", "kind"}
    fields = {
        "heading": base | {"level", "spans", "text"}, "paragraph": base | {"spans", "text"},
        "quote": base | {"spans", "text"}, "list": base | {"ordered", "items"},
        "code": base | {"language", "text"}, "image": base | {"alt", "asset_ref"},
        "table": base | {"headers", "rows", "text_alternative"},
    }
    if kind not in fields:
        _fail("material.ir_invalid", f"{path}.kind", "block kind is invalid")
    _fields(block, fields[kind], path)
    if block["sequence"] != sequence or block["block_ref"] != f"{section_id}.block.{sequence + 1}":
        _fail("material.block_sequence_invalid", path, "block sequence is not stable")
    if kind in {"heading", "paragraph", "quote"}:
        _validate_spans(block["spans"], f"{path}.spans")
        if block["text"] != _plain(block["spans"]):
            _fail("material.ir_invalid", f"{path}.text", "plain text does not match spans")
    if kind == "heading" and (isinstance(block["level"], bool) or not isinstance(block["level"], int) or not 1 <= block["level"] <= 6):
        _fail("material.ir_invalid", f"{path}.level", "heading level is invalid")
    if kind == "list":
        _boolean(block["ordered"], f"{path}.ordered"); items = _sequence(block["items"], f"{path}.items")
        if not items: _fail("material.ir_invalid", f"{path}.items", "list is empty")
        for index, raw in enumerate(items):
            item_path = f"{path}.items[{index}]"; item = _mapping(raw, item_path); _fields(item, {"spans", "text"}, item_path)
            _validate_spans(item["spans"], f"{item_path}.spans")
            if item["text"] != _plain(item["spans"]): _fail("material.ir_invalid", f"{item_path}.text", "list text does not match spans")
    if kind == "code":
        if not re.fullmatch(r"[A-Za-z0-9_+-]{1,24}", str(block["language"])): _fail("material.ir_invalid", f"{path}.language", "code language is invalid")
        _text(block["text"], f"{path}.text", 20000)
    if kind == "image":
        _text(block["alt"], f"{path}.alt", 300); _safe_path(block["asset_ref"], f"{path}.asset_ref")
    if kind == "table":
        headers = [_text(cell, f"{path}.headers[{index}]", 500) for index, cell in enumerate(_sequence(block["headers"], f"{path}.headers"))]
        rows = _sequence(block["rows"], f"{path}.rows")
        if not headers or not rows: _fail("material.ir_invalid", path, "table is empty")
        for row_index, raw in enumerate(rows):
            row = _sequence(raw, f"{path}.rows[{row_index}]")
            if len(row) != len(headers): _fail("material.ir_invalid", f"{path}.rows[{row_index}]", "table width differs")
            for col_index, cell in enumerate(row): _text(cell, f"{path}.rows[{row_index}][{col_index}]", 500)
        _text(block["text_alternative"], f"{path}.text_alternative", 10000)


def _validate_compiled_material(value: object, path: str) -> Mapping[str, Any]:
    item = _mapping(value, path)
    expected = {"material_id", "section_id", "material_type", "locale", "audience", "spoiler_class", "title", "summary", "body_sha256", "blocks", "source_refs", "related_material_ids", "display_purposes", "search_terms", "order", "required", "fallback_locale", "version"}
    _fields(item, expected, path)
    material_id = _ref(item["material_id"], f"{path}.material_id"); section_id = _ref(item["section_id"], f"{path}.section_id")
    if item["material_type"] not in MATERIAL_TYPES: _fail("material.ir_invalid", f"{path}.material_type", "material type is invalid")
    _locale(item["locale"], f"{path}.locale")
    if item["audience"] not in AUDIENCES: _fail("material.audience_invalid", f"{path}.audience", "audience is invalid")
    if item["spoiler_class"] not in SPOILER_CLASSES: _fail("material.ir_invalid", f"{path}.spoiler_class", "spoiler class is invalid")
    if item["audience"] in {"public", "player"} and item["spoiler_class"] in {"full_story", "author_internal"}: _fail("material.spoiler_leak", path, "restricted spoiler in public/player material")
    _text(item["title"], f"{path}.title", 200); _text(item["summary"], f"{path}.summary", 600)
    if not isinstance(item["body_sha256"], str) or not _DIGEST_RE.fullmatch(item["body_sha256"]): _fail("material.digest_invalid", f"{path}.body_sha256", "body digest is invalid")
    _source_refs(item["source_refs"], f"{path}.source_refs"); _refs(item["related_material_ids"], f"{path}.related_material_ids")
    purposes = [_text(raw, f"{path}.display_purposes[{index}]", 40) for index, raw in enumerate(_sequence(item["display_purposes"], f"{path}.display_purposes"))]
    if not purposes or len(purposes) != len(set(purposes)) or set(purposes) - DISPLAY_PURPOSES: _fail("material.ir_invalid", f"{path}.display_purposes", "display purposes are invalid")
    terms = [_text(raw, f"{path}.search_terms[{index}]", 120) for index, raw in enumerate(_sequence(item["search_terms"], f"{path}.search_terms"))]
    if len(terms) != len(set(terms)): _fail("material.ir_invalid", f"{path}.search_terms", "search terms are duplicated")
    _integer(item["order"], f"{path}.order"); _boolean(item["required"], f"{path}.required"); _ref(item["version"], f"{path}.version")
    if item["fallback_locale"] is not None: _locale(item["fallback_locale"], f"{path}.fallback_locale")
    blocks = _sequence(item["blocks"], f"{path}.blocks")
    if not blocks: _fail("material.ir_invalid", f"{path}.blocks", "material has no blocks")
    for sequence, block in enumerate(blocks): _validate_block(block, f"{path}.blocks[{sequence}]", section_id, sequence)
    return item


def validate_material_ir(value: Mapping[str, Any]) -> None:
    """Validate deterministic product integrity without consulting author files."""
    ir = _mapping(value, "material_ir")
    expected = {"schema", "story_pack_ref", "story_pack_version", "default_locale", "locales", "digest_policy", "assets", "reference_index", "materials", "coverage", "source_sha256", "coverage_sha256", "material_ir_sha256"}
    _fields(ir, expected, "material_ir")
    if ir["schema"] != MATERIAL_IR_SCHEMA or ir["digest_policy"] != _DIGEST_POLICY:
        _fail("material.ir_schema_incompatible", "material_ir.schema", "Material IR schema/digest policy is incompatible")
    for path in ("source_sha256", "coverage_sha256", "material_ir_sha256"):
        if not isinstance(ir[path], str) or not _DIGEST_RE.fullmatch(ir[path]):
            _fail("material.digest_invalid", f"material_ir.{path}", "digest is invalid")
    if ir["coverage_sha256"] != _digest(ir["coverage"]):
        _fail("material.coverage_digest_mismatch", "material_ir.coverage_sha256", "coverage digest does not match")
    expected_digest = _digest({key: item for key, item in ir.items() if key != "material_ir_sha256"})
    if ir["material_ir_sha256"] != expected_digest:
        _fail("material.digest_mismatch", "material_ir.material_ir_sha256", "Material IR digest does not match")
    default_locale = _locale(ir["default_locale"], "material_ir.default_locale")
    locales = [_locale(raw, f"material_ir.locales[{index}]") for index, raw in enumerate(_sequence(ir["locales"], "material_ir.locales"))]
    if locales != sorted(set(locales)) or default_locale not in locales:
        _fail("material.ir_invalid", "material_ir.locales", "locales are not canonical or lack the default")
    assets = _sequence(ir["assets"], "material_ir.assets")
    asset_paths: set[str] = set()
    for index, raw in enumerate(assets):
        path = f"material_ir.assets[{index}]"; asset = _mapping(raw, path); _fields(asset, _ASSET_FIELDS, path)
        _ref(asset["asset_ref"], f"{path}.asset_ref"); asset_paths.add(_safe_path(asset["path"], f"{path}.path"))
        if not isinstance(asset["digest"], str) or not _DIGEST_RE.fullmatch(asset["digest"]): _fail("material.digest_invalid", f"{path}.digest", "asset digest is invalid")
    reference_index: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(_sequence(ir["reference_index"], "material_ir.reference_index")):
        path = f"material_ir.reference_index[{index}]"; descriptor = _mapping(raw, path); _fields(descriptor, _REFERENCE_FIELDS, path)
        ref = _source_ref(descriptor["ref"], f"{path}.ref")
        if ref in reference_index or descriptor["audience"] not in AUDIENCES: _fail("material.ir_invalid", path, "reference descriptor is duplicated or invalid")
        _ref(descriptor["kind"], f"{path}.kind"); _boolean(descriptor["required"], f"{path}.required"); reference_index[ref] = descriptor
    coverage = _mapping(ir["coverage"], "material_ir.coverage")
    _fields(coverage, {"schema", "expected", "records", "extra", "missing"}, "material_ir.coverage")
    if coverage["schema"] != DOCUMENTATION_COVERAGE_SCHEMA or list(coverage["extra"]) or list(coverage["missing"]): _fail("material.coverage_incomplete", "material_ir.coverage", "coverage is not closed")
    if coverage["expected"] != sorted(reference_index): _fail("material.coverage_incomplete", "material_ir.coverage.expected", "coverage expected refs differ from reference index")
    seen: set[tuple[str, str]] = set()
    material_items: list[Mapping[str, Any]] = []
    for index, raw in enumerate(_sequence(ir["materials"], "material_ir.materials")):
        item = _validate_compiled_material(raw, f"material_ir.materials[{index}]")
        key = (str(item["material_id"]), str(item["locale"]))
        if key in seen: _fail("material.ir_invalid", f"material_ir.materials[{index}]", "duplicate material identity")
        if item["locale"] not in locales: _fail("material.ir_invalid", f"material_ir.materials[{index}].locale", "material locale is undeclared")
        for ref in item["source_refs"]:
            descriptor = reference_index.get(ref)
            if descriptor is None: _fail("material.reference_unresolved", f"material_ir.materials[{index}].source_refs", "source ref is absent from reference index")
            if _AUDIENCE_RANK[str(item["audience"])] < _AUDIENCE_RANK[str(descriptor["audience"])]: _fail("material.audience_violation", f"material_ir.materials[{index}].source_refs", "material exposes a restricted reference")
        for block in item["blocks"]:
            if block["kind"] == "image" and block["asset_ref"] not in asset_paths: _fail("material.asset_undeclared", f"material_ir.materials[{index}].blocks", "image asset is absent")
        seen.add(key); material_items.append(item)
    if material_items != sorted(material_items, key=lambda item: (item["locale"], item["order"], item["material_id"])):
        _fail("material.ir_invalid", "material_ir.materials", "materials are not in canonical order")
    ids = {str(item["material_id"]) for item in material_items}
    if ids != {str(item["material_id"]) for item in material_items if item["locale"] == default_locale}:
        _fail("material.locale_missing", "material_ir.materials", "a material lacks default locale")
    by_id: dict[str, list[Mapping[str, Any]]] = {}
    for item in material_items: by_id.setdefault(str(item["material_id"]), []).append(item)
    for index, item in enumerate(material_items):
        for related in item["related_material_ids"]:
            targets = [target for target in by_id.get(related, []) if target["locale"] in {item["locale"], default_locale}]
            if not targets: _fail("material.material_ref_unresolved", f"material_ir.materials[{index}].related_material_ids", "related material is absent")
            if min(_AUDIENCE_RANK[str(target["audience"])] for target in targets) > _AUDIENCE_RANK[str(item["audience"])]:
                _fail("material.audience_violation", f"material_ir.materials[{index}].related_material_ids", "related material is restricted")
        linked_ids: set[str] = set()
        for block in item["blocks"]:
            span_groups = [block.get("spans", [])]
            span_groups.extend(entry.get("spans", []) for entry in block.get("items", []))
            for spans in span_groups:
                for span in spans:
                    target = span.get("target")
                    if isinstance(target, str) and target.startswith("material:"):
                        linked_ids.add(target.removeprefix("material:"))
        if linked_ids - set(item["related_material_ids"]):
            _fail("material.material_link_undeclared", f"material_ir.materials[{index}].blocks", "material links are absent from related_material_ids")
    coverage_seen: set[str] = set()
    for index, raw in enumerate(_sequence(coverage["records"], "material_ir.coverage.records")):
        path = f"material_ir.coverage.records[{index}]"; record = _mapping(raw, path); _fields(record, _COVERAGE_RECORD_FIELDS, path)
        ref = _source_ref(record["ref"], f"{path}.ref")
        if ref in coverage_seen or ref not in reference_index: _fail("material.coverage_invalid", path, "coverage ref is duplicate or unexpected")
        status = record["status"]; material_ids = _refs(record["material_ids"], f"{path}.material_ids")
        if status not in {"documented", "intentionally_internal", "not_applicable"} or (status == "documented") != bool(material_ids): _fail("material.coverage_invalid", path, "coverage status/material IDs disagree")
        for material_id in material_ids:
            if not any(ref in item["source_refs"] for item in by_id.get(material_id, [])): _fail("material.coverage_invalid", path, "coverage material does not document ref")
        coverage_seen.add(ref)
    if coverage_seen != set(reference_index): _fail("material.coverage_incomplete", "material_ir.coverage.records", "coverage records are incomplete")


def validate_material_slice(value: Mapping[str, Any]) -> None:
    """Validate one audience slice and prove it contains no wider entry."""
    item = _mapping(value, "material_slice")
    expected = {"schema", "story_pack_ref", "story_pack_version", "locale", "effective_audience", "fallback_material_ids", "toc", "materials", "search_index", "slice_sha256"}
    _fields(item, expected, "material_slice")
    if item["schema"] != MATERIAL_SLICE_SCHEMA or item["effective_audience"] not in ONLINE_AUDIENCES:
        _fail("material.slice_invalid", "material_slice", "slice schema or audience is invalid")
    allowed = _AUDIENCE_RANK[str(item["effective_audience"])]
    materials = _sequence(item["materials"], "material_slice.materials")
    if not materials:
        _fail("material.slice_invalid", "material_slice.materials", "physical audience slice must not be empty")
    compiled = [_validate_compiled_material(material, f"material_slice.materials[{index}]") for index, material in enumerate(materials)]
    ids = {str(material["material_id"]) for material in compiled}
    for index, material in enumerate(compiled):
        if not isinstance(material, Mapping) or material.get("audience") not in AUDIENCES or _AUDIENCE_RANK[str(material["audience"])] > allowed:
            _fail("material.audience_violation", f"material_slice.materials[{index}]", "slice contains a wider audience")
    by_id = {str(material["material_id"]): material for material in compiled}
    for index, raw in enumerate(_sequence(item["search_index"], "material_slice.search_index")):
        path = f"material_slice.search_index[{index}]"; hit = _mapping(raw, path); _fields(hit, {"material_id", "section_id", "title", "summary", "terms"}, path)
        source = by_id.get(str(hit["material_id"]))
        if source is None or any(hit[key] != source[source_key] for key, source_key in (("section_id", "section_id"), ("title", "title"), ("summary", "summary"), ("terms", "search_terms"))):
            _fail("material.search_index_leak", path, "search index does not exactly match an included material")
    expected_toc = [{"material_id": material["material_id"], "section_id": material["section_id"], "title": material["title"], "order": material["order"]} for material in compiled]
    if item["toc"] != expected_toc: _fail("material.slice_invalid", "material_slice.toc", "TOC does not exactly match included materials")
    expected_digest = _digest({key: current for key, current in item.items() if key != "slice_sha256"})
    if item["slice_sha256"] != expected_digest:
        _fail("material.slice_digest_mismatch", "material_slice.slice_sha256", "slice digest does not match")
