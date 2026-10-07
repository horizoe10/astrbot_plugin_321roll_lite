"""Copy the 321Roll world engine package into vendor/ byte for byte.

Usage: python -X utf8 tools/sync_engine.py [--source <321Roll/source/engine>]

The copy keeps every file's bytes; vendor/ENGINE_MANIFEST.json records the
engine version and a SHA-256 for each file so a later sync shows what moved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "321Roll" / "source" / "engine"
SKIP_PARTS = {"__pycache__"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    source = args.source.resolve() / "story_engine"
    if not (source / "versions.py").is_file():
        raise SystemExit(f"not an engine source: {source}")
    target = ROOT / "vendor" / "story_engine"
    if target.exists():
        shutil.rmtree(target)
    files = {}
    for path in sorted(source.rglob("*")):
        if path.is_dir() or SKIP_PARTS & set(path.relative_to(source).parts):
            continue
        rel = path.relative_to(source).as_posix()
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        out.write_bytes(data)
        files[rel] = "sha256:" + hashlib.sha256(data).hexdigest()
    version = re.search(r'STORY_ENGINE_DISTRIBUTION_VERSION = "([^"]+)"', (source / "versions.py").read_text(encoding="utf-8")).group(1)
    manifest = {"engine": "party321-story-engine", "version": version, "file_count": len(files), "files": files}
    (ROOT / "vendor" / "ENGINE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"engine {version}: {len(files)} files")


if __name__ == "__main__":
    main()

