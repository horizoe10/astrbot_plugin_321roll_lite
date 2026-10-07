"""Build world-market packages, their previews and the index from the preset worlds.

Usage: python -X utf8 tools/pack_worlds.py [--images <321Roll/source/content/world-packs>] [--out dist/worlds]

Output (the layout of the repository's worlds branch):

    index.json                    321roll-lite.world-index/1
    packs/<id>-r<revision>.zip    321roll-lite.world-package/1 (see roll_lite/worlds/package.py)
    previews/<id>-r<revision>.webp  640px card image shown by the WebUI market before installing

The text comes from worlds/ (the copy shipped with the plugin).  Images come from the
full 321Roll world-packs covers/ folders, resized to 1280px wide WebP.  A world without
a covers/ folder is packaged as text only.  Packages are byte-for-byte reproducible, so
a published file keeps its sha256 until its content changes.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from roll_lite.cards import COVERS  # noqa: E402
from roll_lite.version import PLUGIN_VERSION  # noqa: E402
from roll_lite.worlds.catalog import validate_presentation, validate_world  # noqa: E402
from roll_lite.worlds.package import INDEX_FORMAT, build_package, sha256, summary  # noqa: E402
from story_engine.world_rules import compile_world  # noqa: E402

INDEX_NAME = "321Roll 官方世界包"
WIDTH, QUALITY = 1280, 82
PREVIEW_WIDTH, PREVIEW_QUALITY = 640, 78


def image_keys(presentation: dict) -> list[str]:
    keys = ["cover"]
    for group in ("acts", "places", "endings"):
        keys += [item["image"] for item in presentation.get(group) or [] if item.get("image")]
    shared = presentation.get("shared") or {}
    return list(dict.fromkeys(k for k in keys if k not in shared))


def webp(path: Path, width: int, quality: int) -> bytes:
    image = Image.open(path).convert("RGB")
    if image.width > width:
        image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=quality, method=6)
    return buffer.getvalue()


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def build(folder: Path, images: Path, out: Path) -> dict:
    pack = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    presentation = json.loads((folder / "presentation.json").read_text(encoding="utf-8"))
    validate_world(pack)
    validate_presentation(presentation, pack)
    compile_world(pack)
    world_id, revision = pack["id"], pack["revision"]
    mark, tone = COVERS.get(world_id, (pack["title"][0], "ink"))
    covers = images / world_id / "covers"
    scene_images: list[tuple[str, bytes]] = []
    if covers.is_dir():
        for key in image_keys(presentation):
            source = covers / f"{key}.png"
            if not source.is_file():
                raise SystemExit(f"{world_id}: presentation refers to {key} but {source} is missing")
            scene_images.append((key, webp(source, WIDTH, QUALITY)))
    data = build_package(pack, presentation, cover={"mark": mark, "tone": tone}, images=scene_images,
                         aliases=presentation.get("shared") or {})
    name = f"packs/{world_id}-r{revision}.zip"
    write(out / name, data)
    row = {"id": world_id, "revision": revision, "title": pack["title"], "summary": summary(pack),
           "cover": {"mark": mark, "tone": tone}, "images": len(scene_images), "min_plugin": PLUGIN_VERSION,
           "file": name, "size": len(data), "sha256": sha256(data)}
    if covers.is_dir():
        row["preview"] = f"previews/{world_id}-r{revision}.webp"
        write(out / row["preview"], webp(covers / "cover.png", PREVIEW_WIDTH, PREVIEW_QUALITY))
    print(f"{name}  {len(scene_images)} images  {len(data) // 1024} KB")
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, default=ROOT.parent / "321Roll" / "source" / "content" / "world-packs")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "worlds")
    args = parser.parse_args()
    folders = sorted(p for p in (ROOT / "worlds").iterdir() if (p / "pack.json").is_file())
    worlds = [build(folder, args.images.resolve(), args.out) for folder in folders]
    index = {"format": INDEX_FORMAT, "name": INDEX_NAME, "worlds": worlds}
    write(args.out / "index.json", (json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(f"{len(worlds)} packages, index.json  ->  {args.out}")


if __name__ == "__main__":
    main()
