"""Build the uploadable AstrBot plugin zip: dist/astrbot_plugin_321roll_lite-v<version>.zip.

Usage: python -X utf8 tools/build_zip.py

The archive holds one folder named after the plugin with the runtime files only
(no tests, tools, docs or caches).
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("__init__.py", "main.py", "metadata.yaml", "_conf_schema.json", "requirements.txt", "README.md", "LICENSE", "logo.png")
FOLDERS = ("roll_lite", "vendor", "worlds", "pages")
PAGES = ROOT / "pages" / "admin"
_ASSET = re.compile(r'((?:from|import)\s*\(?\s*"\.{1,2}/[^"?]+\.js|href="\./style\.css|src="\./js/app\.js)(\?v=[^"]*)?"')


def stamp_pages() -> str:
    """Short hash of the admin page sources; packaged asset URLs carry it so browsers drop stale copies."""
    digest = hashlib.sha256()
    for path in sorted(PAGES.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(PAGES).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def packaged(path: Path, stamp: str) -> bytes:
    data = path.read_bytes()
    if PAGES in path.parents and path.suffix in (".html", ".js"):
        data = _ASSET.sub(lambda m: f'{m.group(1)}?v={stamp}"', data.decode("utf-8")).encode("utf-8")
    return data


def main() -> None:
    version = re.search(r'PLUGIN_VERSION = "([^"]+)"', (ROOT / "roll_lite" / "version.py").read_text(encoding="utf-8")).group(1)
    meta = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
    if f"version: {version}" not in meta:
        raise SystemExit(f"metadata.yaml version does not match roll_lite/version.py ({version})")
    name = "astrbot_plugin_321roll_lite"
    target = ROOT / "dist" / f"{name}-v{version}.zip"
    target.parent.mkdir(exist_ok=True)
    paths = [ROOT / f for f in FILES if (ROOT / f).is_file()]
    for folder in FOLDERS:
        paths += [p for p in sorted((ROOT / folder).rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
    stamp = stamp_pages()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.writestr(f"{name}/{path.relative_to(ROOT).as_posix()}", packaged(path, stamp))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f"{target.relative_to(ROOT)}  {len(paths)} files  {target.stat().st_size // 1024} KB  pages {stamp}  sha256 {digest}")


if __name__ == "__main__":
    main()
