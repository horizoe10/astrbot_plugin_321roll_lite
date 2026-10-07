"""World market: install world packages from GitHub-hosted indexes, a direct URL or an upload.

An index (package.INDEX_FORMAT) lists packages by path relative to the index, with size
and sha256.  Downloads use the admin-chosen route (jsDelivr for GitHub raw URLs, a proxy
prefix, or GitHub directly) and fall back to the direct URL once.  Installing checks the
whole archive first (package.read_package), compiles the world with the engine, writes the
original zip and its images to <data>/market/<world>/r<revision>-<sha8>/, records the world
(catalog.save_market) and only then removes the previous folder.  Packages carry JSON and
images only; nothing from a package is ever executed.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import http.client
import json
import re
import shutil
import time
import urllib.error
import urllib.request
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

from ..storage import now
from ..version import PLUGIN_VERSION
from .catalog import COVER_TONES, WorldEntry, WorldInvalid
from .package import (IMAGE_TYPES, INDEX_FORMAT, MAX_PACKAGE, MB, PackageInvalid, build_package, read_package,
                      scenes, version_tuple)

if TYPE_CHECKING:
    from ..app import LiteApp

OFFICIAL_INDEX = "https://raw.githubusercontent.com/horizoe10/astrbot_plugin_321roll_lite/worlds/index.json"
ROUTES = {"jsdelivr": "jsDelivr 加速", "direct": "GitHub 直连", "prefix": "代理前缀"}
DEFAULT_ROUTE = "jsdelivr"
MAX_INDEX = MB
MAX_SOURCES = 10
INDEX_TTL = 600
INDEX_TIMEOUT = 15       # an unreachable index should fail fast; the market page waits for it
PACKAGE_TIMEOUT = 90
_RAW = re.compile(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/(?:refs/heads/)?([^/]+)/(.+)")
_GITHUB = re.compile(r"https://github\.com/([^/]+)/([^/]+)/(?:raw|blob)/([^/]+)/(.+)")
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,100}")
_SHA = re.compile(r"[0-9a-f]{64}")
_ASSET = re.compile(r"assets/[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\.(?:webp|png|jpg|jpeg)")
_cache: "weakref.WeakKeyDictionary[Any, dict[str, tuple[float, dict[str, Any]]]]" = weakref.WeakKeyDictionary()


class MarketError(Exception):
    pass


def _catalog(app: "LiteApp"):
    from ..rooms import lifecycle
    return lifecycle.catalog(app)


def _audit(app: "LiteApp", username: str, action: str, target: str, detail: dict[str, Any]) -> None:
    with app.store.tx() as c:
        app.store.audit(c, f"webui:{username}", action, target, detail)


# ---------------------------------------------------------------- settings and routes
def settings(app: "LiteApp") -> dict[str, Any]:
    with app.store.read() as c:
        sources = app.store.get_setting(c, "global", "market.sources", [OFFICIAL_INDEX])
        route = app.store.get_setting(c, "global", "market.route", DEFAULT_ROUTE)
        prefix = app.store.get_setting(c, "global", "market.prefix", "")
    return {"sources": list(sources), "route": route if route in ROUTES else DEFAULT_ROUTE, "prefix": str(prefix or ""),
            "official": OFFICIAL_INDEX, "routes": ROUTES}


def _http_url(value: Any, label: str) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or len(text) > 500:
        raise MarketError(f"{label}必须是 http(s) 地址：{text[:60] or '（空）'}")
    return text


def save_settings(app: "LiteApp", payload: dict[str, Any], username: str) -> dict[str, Any]:
    raw = payload.get("sources")
    lines = raw if isinstance(raw, list) else str(raw or "").splitlines()
    sources = list(dict.fromkeys(_http_url(line, "索引地址") for line in lines if str(line).strip()))
    if len(sources) > MAX_SOURCES:
        raise MarketError(f"最多 {MAX_SOURCES} 个索引地址")
    route = str(payload.get("route") or DEFAULT_ROUTE)
    if route not in ROUTES:
        raise MarketError("未知的下载线路")
    prefix = str(payload.get("prefix") or "").strip()
    if prefix or route == "prefix":
        prefix = _http_url(prefix, "代理前缀")
        prefix += "" if prefix.endswith("/") else "/"
    with app.store.tx() as c:
        app.store.set_setting(c, "global", "market.sources", sources)
        app.store.set_setting(c, "global", "market.route", route)
        app.store.set_setting(c, "global", "market.prefix", prefix)
        app.store.audit(c, f"webui:{username}", "web.market_settings", "market", {"sources": sources, "route": route})
    _cache.pop(app, None)
    return settings(app)


def routes_for(url: str, cfg: dict[str, Any]) -> list[str]:
    """Download candidates for one URL: the chosen route first, then the URL itself."""
    first = url
    if cfg["route"] == "jsdelivr":
        match = _RAW.fullmatch(url) or _GITHUB.fullmatch(url)
        if match:
            first = "https://cdn.jsdelivr.net/gh/{}/{}@{}/{}".format(*match.groups())
    elif cfg["route"] == "prefix" and cfg["prefix"]:
        first = cfg["prefix"] + url
    return list(dict.fromkeys([first, url]))


# ---------------------------------------------------------------- downloads
def _download(url: str, limit: int) -> bytes:
    _http_url(url, "下载地址")
    request = urllib.request.Request(url, headers={"User-Agent": f"321RollLite/{PLUGIN_VERSION}", "Accept": "*/*"})
    too_big = f"文件超过 {max(1, limit // MB)}MB 上限" if limit >= MB else "文件比索引记录的大"
    try:
        with urllib.request.urlopen(request, timeout=INDEX_TIMEOUT if limit <= MAX_INDEX else PACKAGE_TIMEOUT) as response:
            declared = str(response.headers.get("Content-Length") or "")
            if declared.isdigit() and int(declared) > limit:
                raise MarketError(too_big)
            data = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise MarketError(f"HTTP {exc.code}" + ("，地址不存在或仓库未公开" if exc.code == 404 else "")) from exc
    except urllib.error.URLError as exc:
        raise MarketError(f"连接失败（{exc.reason}）") from exc
    except TimeoutError as exc:
        raise MarketError("连接超时") from exc
    except (http.client.HTTPException, OSError) as exc:
        raise MarketError(f"连接中断（{exc.__class__.__name__}）") from exc
    if len(data) > limit:
        raise MarketError(too_big)
    return data


async def fetch(app: "LiteApp", url: str, limit: int, cfg: dict[str, Any] | None = None) -> bytes:
    cfg = cfg or settings(app)
    errors = []
    for candidate in routes_for(url, cfg):
        try:
            return await asyncio.to_thread(_download, candidate, limit)
        except MarketError as exc:
            errors.append(f"{urlparse(candidate).netloc or candidate[:40]}：{exc}")
    raise MarketError("；".join(errors))


# ---------------------------------------------------------------- index
def _index_row(base: str, row: Any) -> dict[str, Any]:
    def need(ok: Any) -> None:
        if not ok:
            raise ValueError
    need(isinstance(row, dict) and _ID.fullmatch(str(row["id"])) and type(row["revision"]) is int and row["revision"] >= 1)
    need(isinstance(row["title"], str) and 0 < len(row["title"]) <= 100)
    need(type(row["size"]) is int and 0 < row["size"] <= MAX_PACKAGE and isinstance(row["sha256"], str) and _SHA.fullmatch(row["sha256"]))
    file_url = urljoin(base, str(row["file"]))
    preview = urljoin(base, str(row["preview"])) if row.get("preview") else None
    need(urlparse(file_url).scheme in ("http", "https") and (preview is None or urlparse(preview).scheme in ("http", "https")))
    cover = row.get("cover")
    mark = str(cover.get("mark") or "").strip()[:2] if isinstance(cover, dict) else ""
    return {"id": row["id"], "revision": row["revision"], "title": row["title"], "summary": str(row.get("summary") or "")[:200],
            "size": row["size"], "sha256": row["sha256"], "file_url": file_url, "preview": preview,
            "cover": {"mark": mark, "tone": cover["tone"]} if mark and cover.get("tone") in COVER_TONES else None,
            "images": row["images"] if type(row.get("images")) is int else 0, "min_plugin": str(row.get("min_plugin") or "")[:20]}


def parse_index(url: str, data: bytes) -> dict[str, Any]:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketError("索引不是有效的 JSON") from exc
    if not isinstance(doc, dict) or doc.get("format") != INDEX_FORMAT:
        raise MarketError(f"索引的 format 必须是 {INDEX_FORMAT}")
    worlds, skipped = [], 0
    for row in (doc.get("worlds") if isinstance(doc.get("worlds"), list) else [])[:500]:
        try:
            worlds.append(_index_row(url, row))
        except (KeyError, TypeError, ValueError, AttributeError):
            skipped += 1
    return {"name": str(doc.get("name") or "")[:60], "worlds": worlds, "skipped": skipped}


async def load_index(app: "LiteApp", url: str, refresh: bool = False, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or settings(app)
    key = f"{cfg['route']}|{cfg['prefix']}|{url}"
    cached = _cache.setdefault(app, {}).get(key)
    if cached and not refresh and time.monotonic() - cached[0] < INDEX_TTL:
        return cached[1]
    index = parse_index(url, await fetch(app, url, MAX_INDEX, cfg))
    index["fetched_at"] = now()
    _cache.setdefault(app, {})[key] = (time.monotonic(), index)
    return index


def _status(app: "LiteApp", row: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """available | upgrade (text-only preset) | installed | update | changed | older | conflict | plugin"""
    catalog = _catalog(app)
    stored = catalog.stored(row["id"])
    builtin = catalog.builtin_revision(row["id"])
    installed = stored.pack["revision"] if stored is not None and stored.origin else None
    if stored is not None and not stored.origin:
        status = "conflict"
    elif builtin is not None and row["revision"] < builtin:
        status = "older"
    elif row["min_plugin"] and version_tuple(row["min_plugin"]) > version_tuple(PLUGIN_VERSION):
        status = "plugin"
    elif installed is None:
        status = "upgrade" if builtin is not None else "available"
    elif row["revision"] > installed:
        status = "update"
    elif row["revision"] == installed and row["sha256"] != stored.origin.get("sha256"):
        status = "changed"
    else:
        status = "installed"
    return {**{k: v for k, v in row.items() if k != "preview"}, "status": status, "installed_revision": installed,
            "builtin_revision": builtin, "previews": routes_for(row["preview"], cfg) if row["preview"] else []}


async def listing(app: "LiteApp", refresh: bool = False) -> dict[str, Any]:
    cfg = settings(app)

    async def one(url: str) -> dict[str, Any]:
        try:
            index = await load_index(app, url, refresh, cfg)
        except MarketError as exc:
            return {"url": url, "ok": False, "error": str(exc), "name": "", "worlds": [], "skipped": 0, "fetched_at": None}
        return {"url": url, "ok": True, "error": "", "name": index["name"], "skipped": index["skipped"],
                "fetched_at": index["fetched_at"], "worlds": [_status(app, w, cfg) for w in index["worlds"]]}

    return {"settings": cfg, "sources": list(await asyncio.gather(*(one(url) for url in cfg["sources"])))}


# ---------------------------------------------------------------- install / uninstall
def asset_root(app: "LiteApp", world_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", world_id)[:60]
    return Path(app.data_dir) / "market" / f"{safe}-{hashlib.sha256(world_id.encode()).hexdigest()[:8]}"


def _write_folder(folder: Path, data: bytes, assets: dict[str, bytes]) -> None:
    staging = folder.with_name(folder.name + ".part")
    shutil.rmtree(staging, ignore_errors=True)
    (staging / "assets").mkdir(parents=True)
    (staging / "package.zip").write_bytes(data)
    for name, blob in assets.items():          # names are assets/<whitelisted file name>
        (staging / name).write_bytes(blob)
    if folder.exists():
        shutil.rmtree(folder)
    staging.rename(folder)


async def install_bytes(app: "LiteApp", data: bytes, *, origin: dict[str, str], username: str,
                        expected_sha256: str | None = None) -> dict[str, Any]:
    try:
        package = read_package(data, expected_sha256)
    except PackageInvalid as exc:
        raise MarketError(str(exc)) from exc
    catalog = _catalog(app)
    async with app.lock(f"market:{package.id}"):
        try:
            catalog.check_install(package.id, package.revision)
            await app.engine.compile_world(package.pack)
        except (WorldInvalid, ValueError) as exc:
            raise MarketError(f"不能安装：{exc}") from exc
        previous = catalog.stored(package.id)
        root = asset_root(app, package.id)
        name = f"r{package.revision}-{package.sha256[:8]}"
        existed = (root / name).exists()
        await asyncio.to_thread(_write_folder, root / name, package.data, package.assets)
        record = {"source": origin["source"], "file": origin["file"], "sha256": package.sha256, "size": len(package.data),
                  "revision": package.revision, "installed_at": now(), "by": username, "folder": name,
                  "summary": str(package.manifest.get("summary") or "")[:200], "images": package.images,
                  "banner": package.manifest.get("banner"), "scenes": scenes(package.raw_presentation, package.images)}
        try:
            catalog.save_market(package.pack, package.presentation, record)
        except Exception:
            if not existed:
                shutil.rmtree(root / name, ignore_errors=True)
            raise
        for child in root.iterdir():
            if child.name != name:
                shutil.rmtree(child, ignore_errors=True)
    _audit(app, username, "web.market_install", package.id,
           {"revision": package.revision, "sha256": package.sha256, "source": origin["source"]})
    return {"id": package.id, "title": package.pack["title"], "revision": package.revision, "images": len(package.assets),
            "previous": previous.pack["revision"] if previous is not None and previous.origin else None}


async def install_from_index(app: "LiteApp", source: str, world_id: str, username: str) -> dict[str, Any]:
    cfg = settings(app)
    if source not in cfg["sources"]:
        raise MarketError("这个索引不在来源列表里")
    row = None
    for refresh in (False, True):
        index = await load_index(app, source, refresh, cfg)
        row = next((w for w in index["worlds"] if w["id"] == world_id), None)
        if row is not None:
            break
    if row is None:
        raise MarketError("索引里没有这个世界")
    data = await fetch(app, row["file_url"], row["size"], cfg)
    if len(data) != row["size"]:
        raise MarketError("下载的文件大小与索引不一致，可能下载不完整")
    return await install_bytes(app, data, origin={"source": source, "file": row["file_url"]}, username=username,
                               expected_sha256=row["sha256"])


async def install_url(app: "LiteApp", url: Any, sha: Any, username: str) -> dict[str, Any]:
    url = _http_url(url, "安装包地址")
    sha = str(sha or "").strip().lower() or None
    if sha is not None and not _SHA.fullmatch(sha):
        raise MarketError("sha256 应为 64 位十六进制")
    data = await fetch(app, url, MAX_PACKAGE)
    return await install_bytes(app, data, origin={"source": "url", "file": url}, username=username, expected_sha256=sha)


async def install_upload(app: "LiteApp", data: bytes, filename: str, username: str) -> dict[str, Any]:
    return await install_bytes(app, data, origin={"source": "upload", "file": Path(filename or "upload.zip").name[:120]},
                               username=username)


async def uninstall(app: "LiteApp", world_id: str, username: str) -> dict[str, Any]:
    catalog = _catalog(app)
    async with app.lock(f"market:{world_id}"):
        try:
            removed = catalog.remove_market(world_id)
        except WorldInvalid as exc:
            raise MarketError(str(exc)) from exc
        await asyncio.to_thread(shutil.rmtree, asset_root(app, world_id), True)
    _audit(app, username, "web.market_uninstall", world_id, {"revision": removed.pack["revision"]})
    return {"id": world_id, "title": removed.title, "builtin": catalog.builtin_revision(world_id) is not None}


# ---------------------------------------------------------------- images and export
def image(app: "LiteApp", entry: WorldEntry | None, key: str) -> dict[str, str]:
    """One installed scene image as a data URL (plugin pages cannot load files from the data folder)."""
    origin = entry.origin if entry is not None else None
    if not origin:
        raise MarketError("这个世界没有场景图")
    path = origin.get("banner") if key == "cover" else (origin.get("scenes") or {}).get(key) or (origin.get("images") or {}).get(key)
    if not isinstance(path, str) or not _ASSET.fullmatch(path):
        raise MarketError("没有这张场景图")
    file = asset_root(app, entry.id) / str(origin.get("folder") or "") / path
    if not file.is_file():
        raise MarketError("场景图文件缺失，可以在市场里重新安装这个世界")
    mime = IMAGE_TYPES[file.suffix.lower()]
    return {"key": key, "url": f"data:{mime};base64," + base64.b64encode(file.read_bytes()).decode("ascii")}


def package_file(app: "LiteApp", entry: WorldEntry, cover: dict[str, str] | None) -> tuple[str, bytes]:
    """The installed zip for a market world (unchanged, same sha256); a text-only package otherwise."""
    name = f"{entry.id}-r{entry.pack['revision']}.zip".replace(":", "_")
    if entry.origin:
        stored = asset_root(app, entry.id) / str(entry.origin.get("folder") or "") / "package.zip"
        if stored.is_file():
            return name, stored.read_bytes()
    return name, build_package(entry.pack, entry.presentation, cover=cover)
