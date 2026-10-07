"""Copy the six preset world packs from 321Roll as text only.

Usage: python -X utf8 tools/sync_worlds.py [--source <321Roll/source/content/world-packs>]

pack.json and presentation.json are copied byte for byte; covers/ (scene
images) is left behind because Lite is text only.  worlds/MANIFEST.json lists
each pack with its file digests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "321Roll" / "source" / "content" / "world-packs"
FILES = ("pack.json", "presentation.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    source = args.source.resolve()
    target = ROOT / "worlds"
    target.mkdir(exist_ok=True)
    packs = []
    for folder in sorted(p for p in source.iterdir() if p.is_dir() and (p / "pack.json").is_file()):
        out = target / folder.name
        out.mkdir(exist_ok=True)
        digests = {}
        for name in FILES:
            data = (folder / name).read_bytes()
            (out / name).write_bytes(data)
            digests[name] = "sha256:" + hashlib.sha256(data).hexdigest()
        pack = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
        packs.append({"id": folder.name, "title": pack["title"], "revision": pack["revision"], "files": digests})
    (target / "MANIFEST.json").write_text(json.dumps({"packs": packs}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(packs)} packs")


if __name__ == "__main__":
    main()

