"""World packages: one zip per world, used by the market, offline install and export.

    manifest.json   PACKAGE_FORMAT: id, revision, title, summary, min_plugin, cover, banner, images, assets, files,
                    and optionally edition (core / pro / max; pro when absent)
    world.json      BUNDLE_FORMAT: {"format", "pack", "presentation"} (the WebUI export document)
    assets.bin      every scene image in one file (only when the world has images)

Scene images show later acts, places and endings, so a package keeps them out of
sight: assets.bin is ASSET_MAGIC followed by the images back to back, each masked
with a SHAKE-256 stream derived from the world id, revision and asset id.  Assets
are numbered a00, a01, ...; manifest.assets lists each one's type, offset, size and
the sha256 of the unmasked image, and manifest.images maps presentation image keys
to asset ids.  This is obfuscation against browsing the files, not secrecy: the
plugin is open source and the world text in world.json stays readable.

read_package() checks structure, sizes, digests, every unmasked image and the world itself
before anything is written; archive names are never used as paths.
build_package() writes byte-for-byte reproducible archives (fixed timestamps, fixed order).

Edition tiers (D031-98, renamed by the owner on 2026-10-09): one package format for every
tier.  core = Core, the world card; pro = Pro, the world package; max = Max, the world module.
321Roll's publishing tool writes ``edition``; Lite's own packer never writes it, so its
packages stay byte-identical and read as pro.  The names of the first hour (lite, plus) are
still read, as core and pro.  People see the tier's letter and the revision (C1, P2, M1).
Lite plays Core and Pro only: read_package refuses Max (it needs the full 321Roll) and any
tier it does not know (it needs a newer plugin) before anything is written; see refusal().

world.json may carry ``extensions`` for the full version (weather, ambience, catalog data...);
Lite reads only the world's narration defaults from them: ``"321roll".randomness`` (0-100,
steps of 5, the improvisation band, see narrative_style()) and ``"321roll-lite".dialogue`` and
``.length``; see roll_lite/narration.py.  Anything else there is ignored.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any

from ..version import PLUGIN_VERSION
from .catalog import COVER_TONES, WorldInvalid, validate_presentation, validate_world

PACKAGE_FORMAT = "321roll-lite.world-package/2"
INDEX_FORMAT = "321roll-lite.world-index/1"
BUNDLE_FORMAT = "321roll-lite.world-bundle/1"
MB = 1024 * 1024
MAX_PACKAGE = 32 * MB
MAX_ASSETS = 200
MAX_IMAGE = 6 * MB
MAX_JSON = 2 * MB
MEMBERS = ("manifest.json", "world.json", "assets.bin")
ASSET_FILE = "assets.bin"
ASSET_MAGIC = b"R3LASSET\x00\x02"
IMAGE_TYPES = {"webp": "image/webp", "png": "image/png", "jpg": "image/jpeg"}
_STAMP = (2026, 1, 1, 0, 0, 0)
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}")
ASSET_ID = re.compile(r"a\d{2,3}")
EDITIONS = {"core": "C", "pro": "P", "max": "M"}
OLD_EDITIONS = {"lite": "core", "plus": "pro"}     # the names used for one hour on 2026-10-09; read only
DEFAULT_EDITION = "pro"
PLAYABLE = ("core", "pro")                          # what Lite installs; Max needs the full 321Roll
EDITION = re.compile(r"[a-z]{1,16}")
MAX_REFUSAL = "这是旗舰版（世界模组），需要 321Roll 全量版"
# 321Roll's narrative styles (party321 narrative_randomness.STYLES): upper bound, name, the instruction for the model.
NARRATIVE_STYLES = (
    (14, "严谨", "叙事风格：严谨。只依据设定与已发生的事实叙述，不新增人物、地点与事件。"),
    (34, "稳健", "叙事风格：稳健。紧贴设定，可以补充细节，不新增重要人物与地点。"),
    (64, "均衡", "叙事风格：均衡。适度发挥，可以引入次要人物与小事件。"),
    (84, "灵动", "叙事风格：灵动。主动制造转折，可以引入新的支线。"),
    (100, "奔放", "叙事风格：奔放。大胆即兴，允许意外的发展，但不推翻设定与已发生的事实。"),
)


class PackageInvalid(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def edition_of(edition: str | None) -> str:
    """A tier as Lite names it: pro when none is given, lite and plus read as core and pro."""
    edition = edition or DEFAULT_EDITION
    return OLD_EDITIONS.get(edition, edition)


def label(edition: str | None, revision: Any) -> str:
    """The version people see: the tier's letter and the revision (C1, P2, M1); pro when no tier is given."""
    edition = edition_of(edition)
    return EDITIONS.get(edition, edition[:1].upper()) + str(revision)


def refusal(edition: str | None) -> str | None:
    """Why Lite cannot install this tier, or None for Core and Pro."""
    edition = edition_of(edition)
    if edition in PLAYABLE:
        return None
    if edition == "max":
        return MAX_REFUSAL
    return f"这个世界包的版本档（{edition}）需要更新插件"


def narrative_style(randomness: Any) -> tuple[str, str] | None:
    """(style name, directive text) for a pack's default randomness, or None when it has none or it is not valid."""
    if type(randomness) is not int or not 0 <= randomness <= 100 or randomness % 5:
        return None
    return next((name, text) for top, name, text in NARRATIVE_STYLES if randomness <= top)


def _randomness(bundle: dict[str, Any]) -> int | None:
    """extensions."321roll".randomness of a world.json, or None (anything malformed is ignored, never refused)."""
    own = bundle.get("extensions")
    own = own.get("321roll") if isinstance(own, dict) else None
    value = own.get("randomness") if isinstance(own, dict) else None
    return value if narrative_style(value) else None


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(value))[:3])


def image_kind(data: bytes) -> str | None:
    """'webp', 'png' or 'jpg' from the file signature, else None."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return "jpg" if data[:3] == b"\xff\xd8\xff" else None


def mask(data: bytes, world_id: str, revision: int, asset: str) -> bytes:
    """XOR with a stream bound to one asset of one world revision; applying it twice gives the input back."""
    if not data:
        return data
    stream = hashlib.shake_256(f"321roll-lite/assets:{world_id}:{revision}:{asset}".encode("utf-8")).digest(len(data))
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big")


def summary(pack: dict[str, Any]) -> str:
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


def scenes(presentation: dict[str, Any], images: dict[str, str]) -> dict[str, str]:
    """Image path per story moment: cover, act:<n>, place:<entry>, ending:<id>."""
    result = {"cover": images["cover"]} if "cover" in images else {}
    for group, prefix, field in (("acts", "act", "number"), ("places", "place", "entry"), ("endings", "ending", "id")):
        for item in presentation.get(group) or []:
            if isinstance(item, dict) and item.get("image") in images and item.get(field) not in (None, ""):
                result[f"{prefix}:{item[field]}"] = images[item["image"]]
    return result


def _dump(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build_package(pack: dict[str, Any], presentation: dict[str, Any], *, cover: dict[str, str] | None = None,
                  images: list[tuple[str, bytes]] = (), aliases: dict[str, str] | None = None,
                  extensions: dict[str, Any] | None = None, edition: str | None = None) -> bytes:
    """Zip one world.  images are (key, bytes) in display order; aliases map a key to another key's image;
    extensions go into world.json as they are (the narration defaults of a custom world); edition is written
    to the manifest only when given (a custom world card says core)."""
    bundle = {"format": BUNDLE_FORMAT, "pack": pack, "presentation": presentation}
    if extensions:
        bundle["extensions"] = extensions
    payload = {"world.json": _dump(bundle)}
    shown: dict[str, str] = {}
    table: list[dict[str, Any]] = []
    blobs: list[bytes] = []
    offset = 0
    for index, (key, data) in enumerate(images):
        kind = image_kind(data)
        if kind is None or not _KEY.fullmatch(key):
            raise PackageInvalid(f"{key} 不是 webp/png/jpg 图片或名称无效")
        asset = f"a{index:02d}"
        table.append({"id": asset, "type": kind, "offset": offset, "size": len(data), "sha256": sha256(data)})
        blobs.append(mask(data, pack["id"], pack["revision"], asset))
        offset += len(data)
        shown[key] = asset
    if blobs:
        payload[ASSET_FILE] = ASSET_MAGIC + b"".join(blobs)
    for alias, target in (aliases or {}).items():
        if target in shown:
            shown[alias] = shown[target]
    manifest = {"format": PACKAGE_FORMAT, "id": pack["id"], "revision": pack["revision"], "title": pack["title"],
                "summary": summary(pack), "min_plugin": PLUGIN_VERSION, "cover": cover,
                "banner": shown.get("cover"), "images": shown, "assets": table,
                "files": {name: {"size": len(data), "sha256": sha256(data)} for name, data in payload.items()}}
    if edition:
        manifest["edition"] = edition
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in [("manifest.json", _dump(manifest)), *payload.items()]:
            info = zipfile.ZipInfo(name, _STAMP)
            info.compress_type = zipfile.ZIP_STORED if name == ASSET_FILE else zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


@dataclass(frozen=True)
class Package:
    data: bytes
    sha256: str
    manifest: dict[str, Any]
    pack: dict[str, Any]
    presentation: dict[str, Any]      # validated text presentation (what the catalog stores)
    raw_presentation: dict[str, Any]  # as shipped, with image keys
    files: dict[str, bytes]           # every archive member except manifest.json
    images: dict[str, str]            # presentation image key -> asset id
    assets: dict[str, dict[str, Any]]  # asset id -> {type, offset, size} inside assets.bin (after the magic)
    randomness: int | None = None     # extensions."321roll".randomness: the pack's default narrative style
    extensions: dict[str, Any] | None = None   # world.json's extensions as shipped (narration.from_extensions reads them)

    @property
    def id(self) -> str:
        return self.pack["id"]

    @property
    def revision(self) -> int:
        return self.pack["revision"]

    @property
    def edition(self) -> str:
        return edition_of(self.manifest.get("edition"))

    @property
    def label(self) -> str:
        return label(self.edition, self.revision)

    @property
    def asset_file(self) -> bytes:
        return self.files.get(ASSET_FILE, b"")

    def image(self, asset: str) -> bytes:
        return read_asset(self.asset_file, self.assets[asset], self.id, self.revision, asset)


def read_asset(blob: bytes, meta: dict[str, Any], world_id: str, revision: int, asset: str) -> bytes:
    """One unmasked image from the bytes of assets.bin."""
    start = len(ASSET_MAGIC) + meta["offset"]
    return mask(blob[start:start + meta["size"]], world_id, revision, asset)


def _json(data: bytes, name: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageInvalid(f"{name} 不是有效的 JSON") from exc


def _members(data: bytes) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = [info for info in archive.infolist() if not info.is_dir()]
        files: dict[str, bytes] = {}
        for info in infos:
            name = info.filename
            if name in files:
                raise PackageInvalid(f"安装包里有重复的文件：{name[:80]}")
            if name not in MEMBERS:
                raise PackageInvalid(f"安装包里有不允许的文件：{name[:80]}")
            if info.flag_bits & 0x1:
                raise PackageInvalid("安装包不能加密")
            limit = MAX_PACKAGE if name == ASSET_FILE else MAX_JSON
            if info.file_size > limit:
                raise PackageInvalid(f"{name} 超过大小上限")
            with archive.open(info) as handle:
                blob = handle.read(limit + 1)
            if len(blob) != info.file_size:
                raise PackageInvalid(f"{name} 的大小与记录不符")
            files[name] = blob
        return files
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, EOFError, OSError) as exc:
        raise PackageInvalid(f"不是有效的 zip 安装包（{exc}）") from exc


def read_package(data: bytes, expected_sha256: str | None = None) -> Package:
    """Check one package completely; raises PackageInvalid with a message for the admin."""
    if len(data) > MAX_PACKAGE:
        raise PackageInvalid(f"安装包超过 {MAX_PACKAGE // MB}MB 上限")
    digest = sha256(data)
    if expected_sha256 and digest != expected_sha256.lower():
        raise PackageInvalid("安装包的 sha256 与索引不一致，可能下载不完整或文件已被替换")
    files = _members(data)
    if "manifest.json" not in files or "world.json" not in files:
        raise PackageInvalid("安装包缺少 manifest.json 或 world.json")
    manifest = _json(files.pop("manifest.json"), "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("format") != PACKAGE_FORMAT:
        raise PackageInvalid(f"manifest.json 的 format 必须是 {PACKAGE_FORMAT}")
    edition = manifest.get("edition", DEFAULT_EDITION)
    if not (isinstance(edition, str) and EDITION.fullmatch(edition)):
        raise PackageInvalid("manifest.json 的 edition（版本档）无效：应为 core、pro 或 max")
    if refusal(edition):                        # before the world is read: a Max world may not even be valid for Lite
        raise PackageInvalid(refusal(edition))
    listed = manifest.get("files")
    if not isinstance(listed, dict) or set(listed) != set(files):
        raise PackageInvalid("manifest.json 的文件清单与安装包内容不一致")
    for name, meta in listed.items():
        if not isinstance(meta, dict) or meta.get("size") != len(files[name]) or meta.get("sha256") != sha256(files[name]):
            raise PackageInvalid(f"{name} 的大小或 sha256 与清单不符")
    bundle = _json(files["world.json"], "world.json")
    if not isinstance(bundle, dict) or bundle.get("format") != BUNDLE_FORMAT:
        raise PackageInvalid(f"world.json 的 format 必须是 {BUNDLE_FORMAT}")
    raw_presentation = bundle.get("presentation") if isinstance(bundle.get("presentation"), dict) else {}
    try:
        pack = validate_world(bundle.get("pack"))
        presentation = validate_presentation(raw_presentation, pack)
    except WorldInvalid as exc:
        raise PackageInvalid(f"世界内容无效：{exc}") from exc
    if manifest.get("id") != pack["id"] or manifest.get("revision") != pack["revision"]:
        raise PackageInvalid("manifest.json 的 id 或版本与世界内容不一致")
    assets = _asset_table(manifest.get("assets"), files.get(ASSET_FILE), pack["id"], pack["revision"])
    images = manifest.get("images") or {}
    if not isinstance(images, dict) or len(images) > MAX_ASSETS * 2 or not all(
            isinstance(k, str) and _KEY.fullmatch(k) and isinstance(v, str) and v in assets for k, v in images.items()):
        raise PackageInvalid("manifest.json 的图片对照表无效")
    banner = manifest.get("banner")
    if banner is not None and not (isinstance(banner, str) and banner in assets):
        raise PackageInvalid("manifest.json 的横幅图片无效")
    cover = manifest.get("cover")
    if cover is not None:
        if not (isinstance(cover, dict) and 1 <= len(str(cover.get("mark") or "").strip()) <= 2 and cover.get("tone") in COVER_TONES):
            raise PackageInvalid("manifest.json 的封面无效")
        presentation.setdefault("cover", {"mark": str(cover["mark"]).strip(), "tone": cover["tone"]})
    needed = manifest.get("min_plugin")
    if needed and version_tuple(needed) > version_tuple(PLUGIN_VERSION):
        raise PackageInvalid(f"这个世界需要插件 {needed} 或更新版本")
    extensions = bundle.get("extensions") if isinstance(bundle.get("extensions"), dict) else None
    return Package(data, digest, manifest, pack, presentation, raw_presentation, files, images, assets,
                   randomness=_randomness(bundle), extensions=extensions)


def _asset_table(table: Any, blob: bytes | None, world_id: str, revision: int) -> dict[str, dict[str, Any]]:
    """Check manifest.assets against assets.bin: back-to-back entries, each unmasking to a real image with the listed sha256."""
    table = table or []
    if not isinstance(table, list) or len(table) > MAX_ASSETS:
        raise PackageInvalid("manifest.json 的图片清单无效")
    if not table:
        if blob is not None:
            raise PackageInvalid("安装包里有 assets.bin，但清单里没有图片")
        return {}
    if blob is None or not blob.startswith(ASSET_MAGIC):
        raise PackageInvalid("assets.bin 缺失或不是 321Roll Lite 的图片文件")
    assets: dict[str, dict[str, Any]] = {}
    offset = 0
    for row in table:
        if not (isinstance(row, dict) and isinstance(row.get("id"), str) and ASSET_ID.fullmatch(row["id"])
                and row["id"] not in assets and row.get("type") in IMAGE_TYPES and row.get("offset") == offset
                and type(row.get("size")) is int and 0 < row["size"] <= MAX_IMAGE and isinstance(row.get("sha256"), str)):
            raise PackageInvalid("manifest.json 的图片清单无效")
        meta = {"type": row["type"], "offset": offset, "size": row["size"]}
        image = read_asset(blob, meta, world_id, revision, row["id"])
        if len(image) != row["size"] or sha256(image) != row["sha256"] or image_kind(image) != row["type"]:
            raise PackageInvalid(f"图片 {row['id']} 已损坏或与清单不符")
        assets[row["id"]] = meta
        offset += row["size"]
    if len(ASSET_MAGIC) + offset != len(blob):
        raise PackageInvalid("assets.bin 的长度与清单不符")
    return assets
