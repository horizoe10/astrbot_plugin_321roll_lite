import json
import unittest
from pathlib import Path

from support import ROOT, Player, make_app
from roll_lite.web import service


class WebService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.app = make_app()
        self.host = Player(self.app, "admin", "主持")
        await self.host.say("/团 开启 第七个不思议")
        await self.host.say("/团 加入")
        await self.host.say("/团 选职业 1 林晓")
        await self.host.say("/团 开演")
        with self.app.store.read() as c:
            self.room_id = c.execute("SELECT id FROM rooms").fetchone()[0]

    async def asyncTearDown(self) -> None:
        await self.app.stop()

    async def test_reads(self) -> None:
        overview = await service.overview(self.app, {}, "tester")
        self.assertEqual(overview["rooms"], {"running": 1})
        room = await service.room(self.app, {"id": self.room_id}, "tester")
        self.assertEqual(room["turn"]["actor"], "林晓")
        self.assertEqual(len(room["actors"][0]["attributes"]), 5)
        worlds = await service.worlds(self.app, {}, "tester")
        self.assertEqual(len(worlds["worlds"]), 6)
        with self.assertRaises(service.WebError):
            await service.room(self.app, {"id": "missing"}, "tester")

    async def test_room_command_runs_as_admin_and_reaches_the_group(self) -> None:
        result = await service.room_command(self.app, {"id": self.room_id, "command": "主持 直述 钟楼的指针倒退了一格。"}, "tester")
        self.assertTrue(any("钟楼的指针倒退了一格。" in m for m in result["messages"]))
        self.assertTrue(any("倒退了一格" in text for _, text in self.app.context.sent))
        with self.assertRaises(service.WebError):
            await service.room_command(self.app, {"id": self.room_id, "command": "开启 1"}, "tester")
        result = await service.room_command(self.app, {"id": self.room_id, "command": "暂停"}, "tester")
        self.assertIn("已暂停", result["messages"][0])
        audit = await service.audit(self.app, {}, "tester")
        self.assertEqual(audit["items"][0]["action"], "web.room_command")

    async def test_host_adjustments_wait_for_the_next_narration(self) -> None:
        room = await service.room(self.app, {"id": self.room_id}, "tester")
        actor = room["actors"][0]
        stamina = next(r for r in actor["resources"] if r["name"] == "体力")
        with self.assertRaises(service.WebError):
            await service.room_adjust(self.app, {"id": self.room_id, "changes": [{"kind": "resource", "actor": actor["id"], "ref": "nope", "delta": 1}]}, "tester")
        queued = await service.room_adjust(self.app, {"id": self.room_id, "changes": [
            {"kind": "resource", "actor": actor["id"], "ref": stamina["id"], "delta": -3},
            {"kind": "item", "actor": actor["id"], "ref": "mint", "delta": 2},
            {"kind": "attitude", "subject": "值班老师", "standing": 2}]}, "tester")
        self.assertEqual(queued["adjustments"][0]["state"], "pending")
        self.assertEqual(next(r for r in queued["actors"][0]["resources"] if r["name"] == "体力")["current"], stamina["current"])
        with self.app.store.tx() as c:                         # a narrative option, so no dice can move stamina too
            c.execute("UPDATE turns SET choices_json=? WHERE state='awaiting'",
                      ('[{"label":"A","text":"四处看看","check":{"kind":"narrative","attribute_ref":"","difficulty":"","failure_cost":""}}]',))
        reply = await self.host.say("/团 选 A")                 # the model narrates this round; adjustments apply after it
        self.assertIn("主持人调整生效", reply)
        after = await service.room(self.app, {"id": self.room_id}, "tester")
        self.assertEqual(after["adjustments"][0]["state"], "applied")
        self.assertEqual(next(r for r in after["actors"][0]["resources"] if r["name"] == "体力")["current"], stamina["current"] - 3)
        mint = next(e for e in after["actors"][0]["loadout"] if e["name"] == "薄荷糖")
        self.assertEqual(mint["quantity"], 4)
        teacher = next(p for p in after["people"] if p["name"] == "值班老师")
        self.assertEqual(teacher["tier"], "信任")
        self.assertIn("信任", await self.host.say("/团 人物 值班老师"))
        cancelled = await service.room_adjust(self.app, {"id": self.room_id, "changes": [{"kind": "attitude", "subject": "门卫", "standing": -1}]}, "tester")
        await service.room_adjust_cancel(self.app, {"id": self.room_id, "adjustment": cancelled["adjustments"][0]["id"]}, "tester")
        await self.host.say("/团 选 A")
        self.assertFalse(any(p["name"] == "门卫" for p in (await service.room(self.app, {"id": self.room_id}, "tester"))["people"]))

    async def test_message_settings_and_preview(self) -> None:
        with self.assertRaises(service.WebError):
            await service.settings_message(self.app, {"format": "html"}, "tester")
        saved = await service.settings_message(self.app, {"format": "plain", "image_narration": True, "interval": 9}, "tester")
        self.assertEqual(saved["message"]["format"], "plain")
        self.assertTrue(saved["message"]["image_narration"])
        self.assertFalse(saved["message"]["image_status"])
        self.assertEqual(saved["message"]["interval"], 3.0)
        preview = await service.GET_ROUTES["messages/preview"](self.app, {}, "tester")
        segments = [(e["segment"], e["image"]) for e in preview["turn"]]
        self.assertEqual(segments, [("status", False), ("narration", True), ("choices", False)])
        self.assertIn("**", preview["turn"][0]["markdown"])
        self.assertNotIn("**", preview["turn"][0]["plain"])
        self.assertEqual(preview["turn"][2]["mentions"], ["小林"])
        room = await service.room(self.app, {"id": self.room_id}, "tester")
        self.assertEqual(room["cover"]["mark"], "七")
        self.assertTrue(all("tag" in c for c in room["turn"]["choices"]))

    async def test_feature_override_per_group(self) -> None:
        umo = self.host.caller.umo
        await service.feature_set(self.app, {"key": "playOracle", "umo": umo, "value": False}, "tester")
        self.assertIn("未开放", await self.host.say("/团 神谕 钟楼里有人吗"))
        table = await service.features(self.app, {}, "tester")
        self.assertTrue(next(p for p in table["plays"] if p["key"] == "playOracle")["effective"])
        await service.feature_set(self.app, {"key": "playOracle", "umo": umo, "value": None}, "tester")
        self.assertNotIn("未开放", await self.host.say("/团 神谕 钟楼里有人吗"))
        with self.assertRaises(service.WebError):
            await service.feature_set(self.app, {"key": "playOutfitting", "value": True}, "tester")

    async def test_world_import_and_backup_roundtrip(self) -> None:
        pack = json.loads((ROOT / "worlds" / "wildfire-hunt" / "pack.json").read_text(encoding="utf-8"))
        pack["id"] = "my-hunt"
        pack["title"] = "我的狩猎"
        checked = await service.world_validate(self.app, {"pack": json.dumps(pack, ensure_ascii=False)}, "tester")
        self.assertTrue(checked["ok"])
        broken = await service.world_validate(self.app, {"pack": json.dumps({**pack, "budget": 1})}, "tester")
        self.assertFalse(broken["ok"])
        await service.world_save(self.app, {"pack": pack}, "tester")
        self.assertIn("我的狩猎", await self.host.say("/团 世界"))
        backup = service.export_backup(self.app)
        await service.world_delete(self.app, {"id": "my-hunt"}, "tester")
        self.assertNotIn("我的狩猎", await self.host.say("/团 世界"))
        with self.assertRaises(service.WebError):
            await service.backup_import(self.app, {"data": backup}, "tester")
        await service.backup_import(self.app, {"data": json.dumps(backup, ensure_ascii=False), "confirm": "覆盖"}, "tester")
        self.assertIn("我的狩猎", await self.host.say("/团 世界"))

    async def test_copy_edit_export_and_reimport_a_world(self) -> None:
        preset = await service.world(self.app, {"id": "wildfire-hunt"}, "tester")
        pack, presentation = dict(preset["pack"]), dict(preset["presentation"])
        pack.update(id="my-hunt", title="我的狩猎 · 雪季", revision=1)
        presentation["cover"] = {"mark": "雪", "tone": "jade"}
        saved = await service.world_save(self.app, {"pack": pack, "presentation": presentation, "create": True}, "tester")
        self.assertEqual(saved["revision"], 1)
        with self.assertRaises(service.WebError):          # a new world may not take an existing id
            await service.world_save(self.app, {"pack": pack, "presentation": presentation, "create": True}, "tester")
        pack["worldview"] = "雪原上的狩猎。"
        edited = await service.world_save(self.app, {"pack": pack, "presentation": presentation}, "tester")
        self.assertEqual(edited["revision"], 2)            # editing moves the revision forward
        exported = await service.world(self.app, {"id": "my-hunt"}, "tester")
        self.assertEqual(exported["cover"], {"mark": "雪", "tone": "jade"})
        bundle = json.dumps({"format": exported["bundle_format"], "pack": exported["pack"],
                             "presentation": exported["presentation"]}, ensure_ascii=False)
        await service.world_delete(self.app, {"id": "my-hunt"}, "tester")
        checked = await service.world_validate(self.app, {"pack": bundle}, "tester")   # the export file pasted as is
        self.assertTrue(checked["ok"])
        self.assertIsNone(checked["existing"])
        await service.world_save(self.app, {"pack": bundle}, "tester")
        again = await service.world(self.app, {"id": "my-hunt"}, "tester")
        self.assertEqual(again["pack"]["worldview"], "雪原上的狩猎。")
        self.assertEqual(len(again["presentation"]["acts"]), len(preset["presentation"]["acts"]))
        listed = {w["id"]: w for w in (await service.worlds(self.app, {}, "tester"))["worlds"]}
        self.assertEqual(listed["my-hunt"]["cover"]["mark"], "雪")
        with self.assertRaises(service.WebError):
            await service.world_save(self.app, {"pack": {**pack, "id": "seventh-mystery"}}, "tester")
        broken = await service.world_validate(self.app, {"pack": pack, "presentation": {**presentation, "cover": {"mark": "", "tone": "jade"}}}, "tester")
        self.assertFalse(broken["ok"])

    def test_routes_cover_every_page_call(self) -> None:
        calls = set()
        for path in (ROOT / "pages" / "admin" / "js").rglob("*.js"):
            text = path.read_text(encoding="utf-8")
            for method in ("get", "post"):
                marker = f"api.{method}(\""
                start = 0
                while (index := text.find(marker, start)) >= 0:
                    end = text.index('"', index + len(marker))
                    calls.add((method, text[index + len(marker):end]))
                    start = end
        for method, endpoint in calls:
            table = service.GET_ROUTES if method == "get" else service.POST_ROUTES
            self.assertIn(endpoint, table, f"{method} {endpoint}")


if __name__ == "__main__":
    unittest.main()
