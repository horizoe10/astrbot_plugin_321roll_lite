"""Build world-market packages and their index from the preset worlds.

Usage: python -X utf8 tools/pack_worlds.py [--images <321Roll/source/content/world-packs>] [--out dist/worlds]

Each world becomes packs/<id>-r<revision>.zip holding

    manifest.json   321roll-lite.world-package/1: id, revision, title, summary, cover, images, file digests
    world.json      321roll-lite.world-bundle/1: the same document the WebUI exports and imports
    assets/*.webp   scene images named by their presentation keys (cover, act-N, place-*, ending-*)

The text comes from worlds/ (the copy shipped with the plugin).  Images come from
the full 321Roll world-packs covers/ folders, resized to 1280px wide WebP.  A world
without a covers/ folder is packaged as text only.  Archives are byte-for-byte
reproducible, so a published file keeps its sha256 until its content changes.
index.json lists every package with its relative path, size and sha256.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from roll_lite.version import PLUGIN_VERSION  # noqa: E402
from roll_lite.worlds.catalog import validate_presentation, validate_world  # noqa: E402
from story_engine.world_rules import compile_world  # noqa: E402

PACKAGE_FORMAT = "321roll-lite.world-package/1"
INDEX_FORMAT = "321roll-lite.world-index/1"
BUNDLE_FORMAT = "321roll-lite.world-bundle/1"
COVERS = {"seventh-mystery": ("七", "ink"), "wildfire-hunt": ("狩", "ember"), "neon-pawnshop": ("当", "neon"),
          "nameless-sword-tomb": ("剑", "jade"), "final-curtain": ("戏", "wine"), "greycrown-prequel": ("冠", "slate")}
STAMP = (2026, 1, 1, 0, 0, 0)
WIDTH = 1280
QUALITY = 82


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def summary(pack: dict) -> str:
    """Whole sentences from the opening seed, up to 60 characters, never cut inside quotes."""
    text = pack["seed"].strip().split("\n")[0].strip()
    result = candidate = ""
    for sentence in re.findall(r"[^。！？]+[。！？]*[\"”」』]?", text):
        candidate += sentence
        if len(candidate) > 60:
            break
        if candidate.count('"') % 2 == 0 and candidate.count("“") == candidate.count("”") \
                and candidate.count("「") == candidate.count("」"):
            result = candidate
    return result or text[:59] + "…"


def image_keys(presentation: dict) -> list[str]:
    keys = ["cover"]
    for group in ("acts", "places", "endings"):
        keys += [item["image"] for item in presentation.get(group) or [] if item.get("image")]
    shared = presentation.get("shared") or {}
    return list(dict.fromkeys(k for k in keys if k not in shared))


def webp(path: Path) -> bytes:
    image = Image.open(path).convert("RGB")
    if image.width > WIDTH:
        image = image.resize((WIDTH, round(image.height * WIDTH / image.width)), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=QUALITY, method=6)
    return buffer.getvalue()


def dump(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build(folder: Path, images: Path, out: Path) -> dict:
    pack = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    presentation = json.loads((folder / "presentation.json").read_text(encoding="utf-8"))
    validate_world(pack)
    validate_presentation(presentation, pack)
    compile_world(pack)
    world_id, revision = pack["id"], pack["revision"]
    mark, tone = COVERS.get(world_id, (pack["title"][0], "ink"))
    payload = {"world.json": dump({"format": BUNDLE_FORMAT, "pack": pack, "presentation": presentation})}
    shown: dict[str, str] = {}
    covers = images / world_id / "covers"
    if covers.is_dir():
        for key in image_keys(presentation):
            source = covers / f"{key}.png"
            if not source.is_file():
                raise SystemExit(f"{world_id}: presentation refers to {key} but {source} is missing")
            payload[f"assets/{key}.webp"] = webp(source)
            shown[key] = f"assets/{key}.webp"
        for alias, target in (presentation.get("shared") or {}).items():
            shown[alias] = shown[target]
    manifest = {"format": PACKAGE_FORMAT, "id": world_id, "revision": revision, "title": pack["title"],
                "summary": summary(pack), "min_plugin": PLUGIN_VERSION, "cover": {"mark": mark, "tone": tone},
                "banner": shown.get("cover"), "images": shown,
                "files": {name: {"size": len(data), "sha256": sha(data)} for name, data in payload.items()}}
    name = f"packs/{world_id}-r{revision}.zip"
    target = out / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w") as archive:
        for entry, data in [("manifest.json", dump(manifest)), *payload.items()]:
            info = zipfile.ZipInfo(entry, STAMP)
            info.compress_type = zipfile.ZIP_STORED if entry.endswith(".webp") else zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    data = target.read_bytes()
    print(f"{name}  {len(shown)} images  {len(data) // 1024} KB")
    return {"id": world_id, "revision": revision, "title": pack["title"], "summary": manifest["summary"],
            "cover": manifest["cover"], "images": len(payload) - 1, "min_plugin": PLUGIN_VERSION,
            "file": name, "size": len(data), "sha256": sha(data)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, default=ROOT.parent / "321Roll" / "source" / "content" / "world-packs")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "worlds")
    args = parser.parse_args()
    folders = sorted(p for p in (ROOT / "worlds").iterdir() if (p / "pack.json").is_file())
    worlds = [build(folder, args.images.resolve(), args.out) for folder in folders]
    (args.out / "index.json").write_bytes(dump({"format": INDEX_FORMAT, "worlds": worlds}))
    print(f"{len(worlds)} packages, index.json  ->  {args.out}")


if __name__ == "__main__":
    main()
