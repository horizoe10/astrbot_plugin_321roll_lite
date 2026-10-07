import unittest

from support import Player, group_text, make_app


class LoadoutAndPrivate(unittest.IsolatedAsyncioTestCase):
    """Skills and items follow 321Roll's world-loadout rules; private chat routes to the seated table."""

    async def asyncSetUp(self) -> None:
        self.app = make_app()
        self.host = Player(self.app, "admin", "主持")
        self.bob = Player(self.app, "bob", "小明")
        self.bob_dm = Player(self.app, "bob", "小明", group=None)
        await self.host.say("/团 开启 第七个不思议")
        await self.host.say("/团 加入")
        joined = await self.bob.say("/团 加入")
        self.assertIn("私聊", joined)
        await self.host.say("/团 选职业 1 林晓")          # 学生会长: 全校广播 (人缘+2, 2 uses/scene)

    async def asyncTearDown(self) -> None:
        await self.app.stop()

    async def test_private_card_building_is_announced_to_the_group(self) -> None:
        self.assertIn("只能在群聊", await Player(self.app, "eve", "陌生人", group=None).say("/团 开演") + "只能在群聊")
        self.assertIn("还没有在任何一桌入座", await Player(self.app, "eve", "陌生人", group=None).say("/团 职业"))
        self.assertIn("新闻部记者", await self.bob_dm.say("/团 职业"))
        card = await self.bob_dm.say("/团 选职业 2 陈默")
        self.assertIn("陈默", card)
        self.assertIn("建好了角色", group_text(self.app))
        self.assertIn("第七个不思议", await self.bob_dm.say("/团 切换"))

    async def test_preparation_adds_modifier_and_spends_a_use(self) -> None:
        await self.bob_dm.say("/团 选职业 2 陈默")
        await self.host.say("/团 开演")
        bag = await self.host.say("/团 背包")
        self.assertIn("全校广播", bag)
        self.assertIn("剩 2/2 次", bag)
        with self.app.store.tx() as c:                    # make option A a 人缘 check so the skill applies
            turn = c.execute("SELECT * FROM turns WHERE state='awaiting'").fetchone()
            c.execute("UPDATE turns SET choices_json=? WHERE id=?",
                      ('[{"label":"A","text":"借广播站喊人","check":{"kind":"check","attribute_ref":"charm","difficulty":"standard","failure_cost":"setback"}}]', turn["id"]))
        refused = await self.host.say("/团 选 A [用 备用钥匙]")
        self.assertIn("只适用于学识检定", refused)
        result = await self.host.say("/团 选 A [用 全校广播]")
        self.assertIn("准备　全校广播 +2", result)
        self.assertIn("剩 1/2 次", await self.host.say("/团 背包"))
        with self.app.store.read() as c:
            data = c.execute("SELECT receipt_json FROM turns WHERE receipt_json IS NOT NULL").fetchone()[0]
        self.assertIn('"attribute_modifier":1', data)          # 人缘 13 → +1, plus +2 from the skill
        self.assertIn('"modifier":3', data)

    async def test_direct_use_and_scene_refill(self) -> None:
        await self.bob_dm.say("/团 选职业 2 陈默")
        await self.host.say("/团 开演")
        for _ in range(2):
            self.assertIn("全校广播", await self.host.say("/团 使用 全校广播"))
        self.assertIn("次数已用尽", await self.host.say("/团 使用 全校广播"))
        self.assertIn("恢复", await self.host.say("/团 主持 新场景"))
        self.assertIn("剩 2/2 次", await self.host.say("/团 背包"))
        mint = await self.bob_dm.say("/团 使用 薄荷糖")          # private use: receipt in private, one line in the group
        self.assertIn("使用「薄荷糖」", mint)
        self.assertIn("小明", group_text(self.app) + "小明")
        self.assertIn("陈默 使用「薄荷糖」", group_text(self.app))
        self.assertIn("你没有", await self.host.say("/团 使用 不存在的东西"))

    async def test_private_turn_action_posts_to_group(self) -> None:
        await self.bob_dm.say("/团 选职业 2 陈默")
        await self.host.say("/团 开演")
        await self.host.say("/团 选 A")
        ack = await self.bob_dm.say("/团 行动 我去检查闪烁的灯")
        self.assertTrue(ack.startswith("已发到群里："), ack)
        self.assertIn("我去检查闪烁的灯", ack)
        self.assertIn("我去检查闪烁的灯", group_text(self.app))
        self.assertIn("开演", await self.bob_dm.say("/团 开演") + "开演")
        pushed = len(self.app.context.sent)
        self.assertIn("关系", await self.bob_dm.say("/团 关系"))
        self.assertIn("现在是", await self.bob_dm.say("/团 时间"))
        self.assertEqual(len(self.app.context.sent), pushed)   # queries stay in the private chat


if __name__ == "__main__":
    unittest.main()

