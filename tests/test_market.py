import hashlib
import io
import json
import unittest
import zipfile
from copy import deepcopy
from unittest import mock

from support import ROOT, Player, make_app
from roll_lite.web import service
from roll_lite.worlds import market
from roll_lite.worlds.package import INDEX_FORMAT, PackageInvalid, build_package, read_package

WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + bytes(8)
INDEX = "https://raw.githubusercontent.com/someone/worlds-repo/worlds/index.json"


def preset(world_id: str) -> tuple[dict, dict]:
    folder = ROOT / "worlds" / world_id
    return (json.loads((folder / "pack.json").read_text(encoding="utf-8")),
            json.loads((folder / "presentation.json").read_text(encoding="utf-8")))


def package(world_id: str = "wildfire-hunt", **changes) -> bytes:
    pack, presentation = preset("wildfire-hunt")
    pack = {**pack, "id": world_id, **changes}
    return build_package(pack, presentation, cover={"mark": "狩", "tone": "ember"},
                         images=[("cover", WEBP), ("act-1", WEBP + b"1")])


def rezip(data: bytes, edit) -> bytes:
    """Copy a package with edit(files) applied to its {name: bytes} members."""
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        files = {name: source.read(name) for name in source.namelist()}
    edit(files)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as target:
        for name, blob in files.items():
            target.writestr(name, blob)
    return buffer.getvalue()


def needs_newer_plugin(files: dict) -> None:
    manifest = json.loads(files["manifest.json"])
    manifest["min_plugin"] = "99.0.0"
    files["manifest.json"] = json.dumps(manifest).encode()


def fake_image(files: dict) -> None:
    """Replace an image with other bytes and list them correctly, so only the image check can catch it."""
    files["assets/cover.webp"] = b"not an image"
    manifest = json.loads(files["manifest.json"])
    manifest["files"]["assets/cover.webp"] = {"size": 12, "sha256": hashlib.sha256(b"not an image").hexdigest()}
    files["manifest.json"] = json.dumps(manifest).encode()


class Market(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.app = make_app()
        self.host = Player(self.app, "admin", "主持")
        self.files: dict[str, bytes] = {}
        self.fetched: list[str] = []
        patcher = mock.patch.object(market, "_download", self.download)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def asyncTearDown(self) -> None:
        await self.app.stop()

    def download(self, url: str, limit: int) -> bytes:
        self.fetched.append(url)
        if url not in self.files:
            raise market.MarketError("HTTP 404")
        if len(self.files[url]) > limit:
            raise market.MarketError("too big")
        return self.files[url]

    def publish(self, *packages: bytes, sha: str | None = None) -> None:
        rows = []
        for data in packages:
            manifest = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("manifest.json"))
            name = f"packs/{manifest['id']}-r{manifest['revision']}.zip"
            self.files[INDEX.rsplit("/", 1)[0] + "/" + name] = data
            rows.append({"id": manifest["id"], "revision": manifest["revision"], "title": manifest["title"],
                         "summary": manifest["summary"], "file": name, "size": len(data),
                         "sha256": sha or hashlib.sha256(data).hexdigest(), "images": 2, "preview": "previews/x.webp"})
        self.files[INDEX] = json.dumps({"format": INDEX_FORMAT, "name": "测试索引", "worlds": rows}).encode()

    async def status(self, world_id: str) -> dict:
        data = await service.market_view(self.app, {"refresh": "1"}, "tester")
        return next(w for w in data["sources"][0]["worlds"] if w["id"] == world_id)

    async def test_install_the_illustrated_preset_then_uninstall_back_to_text(self) -> None:
        data = package()
        self.publish(data)
        await service.market_settings(self.app, {"sources": INDEX, "route": "jsdelivr"}, "tester")
        row = await self.status("wildfire-hunt")
        self.assertEqual(row["status"], "upgrade")
        self.assertEqual(row["previews"][0], "https://cdn.jsdelivr.net/gh/someone/worlds-repo@worlds/previews/x.webp")
        self.assertTrue(self.fetched[0].startswith("https://cdn.jsdelivr.net/"))     # jsDelivr first, then GitHub
        self.assertEqual(self.fetched[1], INDEX)

        done = await service.market_install(self.app, {"source": INDEX, "id": "wildfire-hunt"}, "tester")
        self.assertEqual((done["revision"], done["images"]), (1, 2))
        listed = {w["id"]: w for w in (await service.worlds(self.app, {}, "tester"))["worlds"]}
        self.assertEqual(listed["wildfire-hunt"]["source"], "market")
        self.assertTrue(listed["wildfire-hunt"]["art"])
        self.assertIn("狩火", await self.host.say("/团 世界"))
        image = await service.world_image(self.app, {"id": "wildfire-hunt", "key": "cover"}, "tester")
        self.assertTrue(image["url"].startswith("data:image/webp;base64,"))
        detail = await service.world(self.app, {"id": "wildfire-hunt"}, "tester")
        self.assertEqual([s["key"] for s in detail["scenes"]], ["cover", "act:1"])
        self.assertEqual((await self.status("wildfire-hunt"))["status"], "installed")
        name, _, exported = await service.world_package(self.app, {"id": "wildfire-hunt"}, "tester")
        self.assertEqual((name, exported), ("wildfire-hunt-r1.zip", data))          # the installed zip, unchanged
        self.assertIn("狩火", await self.host.say("/团 开启 狩火"))                    # a table opens on it

        await service.market_uninstall(self.app, {"id": "wildfire-hunt"}, "tester")
        listed = {w["id"]: w for w in (await service.worlds(self.app, {}, "tester"))["worlds"]}
        self.assertEqual(listed["wildfire-hunt"]["source"], "builtin")
        self.assertFalse(market.asset_root(self.app, "wildfire-hunt").exists())
        with self.assertRaises(service.WebError):
            await service.world_image(self.app, {"id": "wildfire-hunt", "key": "cover"}, "tester")

    async def test_index_digest_mismatch_is_refused(self) -> None:
        self.publish(package(), sha="0" * 64)
        await service.market_settings(self.app, {"sources": [INDEX], "route": "direct"}, "tester")
        with self.assertRaisesRegex(service.WebError, "sha256"):
            await service.market_install(self.app, {"source": INDEX, "id": "wildfire-hunt"}, "tester")
        self.assertEqual(self.fetched[0], INDEX)                                      # direct route: no mirror
        with self.assertRaisesRegex(service.WebError, "来源列表"):
            await service.market_install(self.app, {"source": "https://example.com/i.json", "id": "x"}, "tester")

    def test_unsafe_or_tampered_archives_are_rejected_before_install(self) -> None:
        good = package("frost-hunt")
        read_package(good)
        cases = {
            "不允许的文件": lambda f: f.update({"../evil.py": b"print(1)"}),
            "清单": lambda f: f.update({"assets/extra.webp": WEBP}),
            "sha256 与清单不符": lambda f: f.update({"world.json": f["world.json"].replace("狩".encode(), "猎".encode(), 1)}),
            "不是有效的图片": fake_image,
            "需要插件": needs_newer_plugin,
        }
        for message, edit in cases.items():
            with self.subTest(message), self.assertRaisesRegex(PackageInvalid, message):
                read_package(rezip(good, edit))
        with self.assertRaisesRegex(PackageInvalid, "zip"):
            read_package(b"not a zip at all")
        with self.assertRaisesRegex(PackageInvalid, "世界内容无效"):
            read_package(package("frost-hunt", budget=1))

    async def test_upload_update_downgrade_conflict_and_uninstall(self) -> None:
        first = await service.market_upload(self.app, package("frost-hunt", title="霜猎 · 第一版"), "frost.zip", "tester")
        self.assertEqual(first["revision"], 1)
        entry = await service.world(self.app, {"id": "frost-hunt"}, "tester")
        self.assertEqual((entry["source"], entry["market"]["source"]), ("market", "upload"))
        with self.assertRaisesRegex(service.WebError, "市场"):                         # read-only like a preset
            await service.world_save(self.app, {"pack": entry["pack"]}, "tester")
        with self.assertRaisesRegex(service.WebError, "卸载"):
            await service.world_delete(self.app, {"id": "frost-hunt"}, "tester")
        second = await service.market_upload(self.app, package("frost-hunt", revision=2, title="霜猎 · 第二版"), "f.zip", "tester")
        self.assertEqual((second["revision"], second["previous"]), (2, 1))
        self.assertEqual(len(list(market.asset_root(self.app, "frost-hunt").iterdir())), 1)   # old folder removed
        with self.assertRaisesRegex(service.WebError, "降级"):
            await service.market_upload(self.app, package("frost-hunt", title="霜猎 · 第一版"), "f.zip", "tester")
        await service.world_toggle(self.app, {"id": "frost-hunt", "enabled": False}, "tester")
        await service.market_uninstall(self.app, {"id": "frost-hunt"}, "tester")
        self.assertIsNone(self.app.worlds.get("frost-hunt"))
        with self.app.store.read() as c:
            self.assertIsNone(self.app.store.get_setting(c, "global", "world.frost-hunt.enabled"))

        pack, presentation = preset("wildfire-hunt")
        await service.world_save(self.app, {"pack": {**pack, "id": "my-hunt"}, "presentation": presentation}, "tester")
        with self.assertRaisesRegex(service.WebError, "自定义世界"):
            await service.market_upload(self.app, package("my-hunt"), "m.zip", "tester")

    async def test_exported_package_of_a_custom_world_installs_elsewhere(self) -> None:
        pack, presentation = preset("wildfire-hunt")
        presentation = {**deepcopy(presentation), "cover": {"mark": "雪", "tone": "jade"}}
        await service.world_save(self.app, {"pack": {**pack, "id": "snow-hunt", "title": "雪猎"}, "presentation": presentation}, "tester")
        name, kind, data = await service.world_package(self.app, {"id": "snow-hunt"}, "tester")
        self.assertEqual((name, kind), ("snow-hunt-r1.zip", "application/zip"))
        other = make_app()
        self.addAsyncCleanup(other.stop)
        await service.market_upload(other, data, name, "tester")
        installed = await service.world(other, {"id": "snow-hunt"}, "tester")
        self.assertEqual((installed["source"], installed["cover"]["mark"], installed["art"]), ("market", "雪", False))

    def test_routes(self) -> None:
        cfg = {"route": "jsdelivr", "prefix": ""}
        self.assertEqual(market.routes_for("https://raw.githubusercontent.com/a/b/refs/heads/main/x/i.json", cfg),
                         ["https://cdn.jsdelivr.net/gh/a/b@main/x/i.json", "https://raw.githubusercontent.com/a/b/refs/heads/main/x/i.json"])
        self.assertEqual(market.routes_for("https://example.com/i.json", cfg), ["https://example.com/i.json"])
        self.assertEqual(market.routes_for("https://example.com/i.json", {"route": "prefix", "prefix": "https://p.example/"}),
                         ["https://p.example/https://example.com/i.json", "https://example.com/i.json"])
        with self.assertRaises(market.MarketError):
            market.save_settings(self.app, {"sources": "file:///etc/passwd"}, "tester")


if __name__ == "__main__":
    unittest.main()
