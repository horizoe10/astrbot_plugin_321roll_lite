"""Build a world package from a world folder, for authors publishing their own worlds.

    python -X utf8 -m roll_lite.worlds.make <world folder> [--out <market folder>] [--name <index name>]

Run it from the plugin folder (the one holding roll_lite/ and vendor/); Pillow is needed for images.
A world folder holds (see worlds/_template and docs/WORLD_PACK_SPEC.md):

    pack.json           321roll.world-template/1
    presentation.json   acts, places, endings and cover (optional)
    images/             cover.<ext> plus one file per image key (optional; webp, png or jpg)

An act, place or ending without an "image" key uses act-<number>, place-<entry> or
ending-<id> when images/ has that file.  The output is laid out like a market repository:

    <out>/packs/<id>-r<revision>.zip        the package (package.PACKAGE_FORMAT)
    <out>/previews/<id>-r<revision>.webp    640px card image, when there is a cover image
    <out>/index.json                        created, or updated with this world's row

The package is checked exactly as the market checks it before install.  With the same
Pillow version, the same input always gives the same bytes.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any

from ..version import PLUGIN_VERSION
from .catalog import COVER_TONES, WorldInvalid, validate_presentation, validate_world
from .package import INDEX_FORMAT, PackageInvalid, build_package, read_package, sha256, summary

ROOT = Path(__file__).resolve().parents[2]
WIDTH, QUALITY = 1280, 82
PREVIEW_WIDTH, PREVIEW_QUALITY = 640, 78
EXTENSIONS = (".webp", ".png", ".jpg", ".jpeg")
GROUPS = (("acts", "act", "number"), ("places", "place", "entry"), ("endings", "ending", "id"))


class BuildError(Exception):
    pass


def webp(path: Path, width: int, quality: int) -> bytes:
    """The image as WebP, scaled down to width when wider."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise BuildError("处理图片需要 Pillow：pip install pillow") from exc
    image = Image.open(path).convert("RGB")
    if image.width > width:
        image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=quality, method=6)
    return buffer.getvalue()


def find_image(folder: Path, key: str) -> Path | None:
    return next((folder / (key + ext) for ext in EXTENSIONS if (folder / (key + ext)).is_file()), None)


def image_keys(presentation: dict[str, Any]) -> list[str]:
    """Image keys in display order: cover, then acts, places and endings; shared aliases excluded."""
    keys = ["cover"]
    for group, _, _ in GROUPS:
        keys += [item["image"] for item in presentation.get(group) or [] if isinstance(item, dict) and item.get("image")]
    shared = presentation.get("shared") or {}
    return list(dict.fromkeys(k for k in keys if k not in shared))


def _default_images(presentation: dict[str, Any], images: Path) -> dict[str, Any]:
    """Fill in act-<n>, place-<entry>, ending-<id> for items without an image key when that file exists."""
    result = json.loads(json.dumps(presentation))
    for group, prefix, field in GROUPS:
        for item in result.get(group) or []:
            if isinstance(item, dict) and not item.get("image") and item.get(field) not in (None, ""):
                key = f"{prefix}-{item[field]}"
                if find_image(images, key):
                    item["image"] = key
    return result


def _read(path: Path, required: bool) -> Any:
    if not path.is_file():
        if required:
            raise BuildError(f"缺少 {path.name}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"{path.name} 不是有效的 JSON（{exc}）") from exc


def build(folder: Path, out: Path, *, images: Path | None = None, cover: dict[str, str] | None = None) -> dict[str, Any]:
    """Write one world's package (and preview) under out; returns its index row."""
    vendor = str(ROOT / "vendor")
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    from story_engine.world_rules import compile_world

    pack = _read(folder / "pack.json", True)
    presentation = _read(folder / "presentation.json", False) or {}
    images = images or folder / "images"
    try:
        pack = validate_world(pack)
        clean = validate_presentation(presentation, pack)
        compile_world(pack)
    except (WorldInvalid, ValueError) as exc:
        raise BuildError(f"世界内容无效：{exc}") from exc
    if images.is_dir():
        presentation = _default_images(presentation, images)
    cover = cover or clean.get("cover") or {"mark": pack["title"].strip()[0], "tone": COVER_TONES[sum(map(ord, pack["id"])) % len(COVER_TONES)]}
    world_id, revision = pack["id"], pack["revision"]
    scene_images: list[tuple[str, bytes]] = []
    if images.is_dir():
        keys = image_keys(presentation)
        for key in keys:
            source = find_image(images, key)
            if source is None:
                raise BuildError(f"presentation.json 用到了图片 {key}，但 {images.name}/ 里没有 {key}.webp/.png/.jpg")
            scene_images.append((key, webp(source, WIDTH, QUALITY)))
        unused = sorted(p.name for p in images.iterdir() if p.suffix.lower() in EXTENSIONS and p.stem not in keys)
        if unused:
            print(f"提示：{images.name}/ 里有没用到的图片：{'、'.join(unused)}")
    try:
        data = build_package(pack, presentation, cover=cover, images=scene_images, aliases=presentation.get("shared") or {})
        read_package(data)
    except PackageInvalid as exc:
        raise BuildError(str(exc)) from exc
    name = f"packs/{world_id}-r{revision}.zip"
    if (out / name).is_file() and (out / name).read_bytes() != data:
        print(f"提示：{name} 已存在且内容不同。已经发布过的版本请先把 pack.json 的 revision 加 1，再重新打包。")
    _write(out / name, data)
    row = {"id": world_id, "revision": revision, "title": pack["title"], "summary": summary(pack), "cover": cover,
           "images": len(scene_images), "min_plugin": PLUGIN_VERSION, "file": name, "size": len(data), "sha256": sha256(data)}
    if scene_images:
        row["preview"] = f"previews/{world_id}-r{revision}.webp"
        _write(out / row["preview"], webp(find_image(images, "cover"), PREVIEW_WIDTH, PREVIEW_QUALITY))
    print(f"{name}  {len(scene_images)} 张图片  {len(data) // 1024} KB  sha256 {row['sha256']}")
    return row


def write_index(out: Path, rows: list[dict[str, Any]], name: str | None = None, *, replace: bool = False) -> Path:
    """Write out/index.json; unless replace, keep rows of other worlds from the existing index."""
    path = out / "index.json"
    existing = None if replace else _read(path, False)
    if existing is not None and not (isinstance(existing, dict) and existing.get("format") == INDEX_FORMAT):
        raise BuildError(f"{path} 不是 {INDEX_FORMAT} 索引，不会覆盖它")
    ids = {row["id"] for row in rows}
    kept = [row for row in (existing or {}).get("worlds") or [] if isinstance(row, dict) and row.get("id") not in ids]
    index = {"format": INDEX_FORMAT, "name": name or (existing or {}).get("name") or "我的世界包", "worlds": kept + rows}
    _write(path, (json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return path


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m roll_lite.worlds.make", description="把一个世界文件夹打包成 321Roll Lite 世界安装包")
    parser.add_argument("folder", type=Path, help="含 pack.json 的世界文件夹")
    parser.add_argument("--out", type=Path, default=Path("world-market"), help="输出目录，结构与世界市场仓库相同（默认 ./world-market）")
    parser.add_argument("--name", help="索引名称，显示在世界市场的来源标题上")
    args = parser.parse_args(argv)
    try:
        row = build(args.folder.resolve(), args.out.resolve())
        path = write_index(args.out.resolve(), [row], args.name)
    except BuildError as exc:
        print(f"打包失败：{exc}", file=sys.stderr)
        return 1
    print(f"已更新 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

