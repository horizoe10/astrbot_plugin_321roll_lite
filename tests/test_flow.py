import asyncio
import dataclasses
import unittest

from support import Player, make_app


class LifecycleAndTurns(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.app = make_app()
        self.host = Player(self.app, "admin", "主持")
        self.bob = Player(self.app, "bob", "小明")

    async def asyncTearDown(self) -> None:
        await self.app.stop()

    async def open_and_start(self) -> str:
        self.assertIn("第七个不思议", await self.host.say("/团 世界"))
        opened = await self.host.say("/团 开启 第七个不思议")
        self.assertIn("〖 第七个不思议 〗", opened)
        self.assertIn("席位", opened)
        self.assertIn("入座", await self.host.say("/团 加入"))
        await self.bob.say("/团 加入")
        self.assertIn("学生会长", await self.host.say("/团 职业"))
        card = await self.host.say("/团 选职业 1 林晓")
        self.assertIn("体力", card)
        await self.bob.say("/团 选职业 2 陈默")
        return await self.host.say("/团 开演")

    async def test_full_round_with_choice_free_action_and_vote(self) -> None:
        opening = await self.open_and_start()
        self.assertIn("钟楼下的走廊", opening)
        self.assertIn("▸ 轮到 林晓", opening)
        self.assertIn("现在轮到 林晓", await self.bob.say("/团 选 A"))
        first = await self.host.say("/团 选 A 小心地")
        self.assertIn("检定", first)
        self.assertIn("d20 ", first)
        self.assertIn("▸ 轮到 陈默", first)
        second = await self.bob.say("/团 行动 我去检查闪烁的灯")
        self.assertIn("检定", second)
        self.assertIn("▸ 轮到 林晓", second)
        status = await self.host.say("/团 状态")
        self.assertIn("第 2 轮", status)
        proposal = await self.bob.say("/团 全队 一起冲上钟楼")
        self.assertIn("━━  全队提议", proposal)
        passed = await self.host.say("/团 投 反对")
        self.assertIn("同意 1 · 反对 1", passed)   # tie goes to the host's ballot
        self.assertIn("全队提议未通过", passed)
        proposal = await self.bob.say("/团 全队 一起冲上钟楼")
        passed = await self.host.say("/团 投 同意")
        self.assertIn("同意 2 · 反对 0", passed)
        self.assertIn("全队行动", passed)
        self.assertIn("▸ 轮到 林晓", passed)   # turn handed back
        saved = await self.host.say("/团 存档 第一章")
        self.assertIn("已存档", saved)
        await self.host.say("/团 选 B")
        self.assertIn("已读取存档", await self.host.say("/团 读档 1"))
        self.assertIn("故事继续", await self.host.say("/团 恢复"))
        ended = await self.host.say("/团 完结 全员记起")
        self.assertIn("〖 终章", ended)
        self.assertIn("已收桌", await self.host.say("/团 关闭"))

    async def test_collective_event_and_timeout(self) -> None:
        await self.open_and_start()
        event = await self.host.say("/团 主持 集体事件")
        self.assertIn("钟声又响", event)
        await self.host.say("/团 投 A")
        result = await self.bob.say("/团 投 A")
        self.assertIn("立刻爬上钟楼", result)
        from roll_lite.plays import hosted
        with self.app.store.read() as c:
            turn = hosted.current_turn(c, c.execute("SELECT id FROM rooms").fetchone()[0])
        await hosted.timeout_turn(self.app, turn["room_id"], turn["id"])
        self.assertTrue(any("超时，自动选择" in text for _, text in self.app.context.sent))

    async def test_permissions_and_errors(self) -> None:
        self.assertIn("只有管理员", await self.bob.say("/团 开启"))
        self.assertIn("还没有开团", await self.bob.say("/团 加入"))
        await self.host.say("/团 开启 1")
        self.assertIn("只有主持人", await self.bob.say("/团 开演"))
        self.assertIn("没有“乱码”", await self.bob.say("/团 乱码"))

    async def test_table_turn_time_limit(self) -> None:
        from datetime import UTC, datetime
        from roll_lite.plays import hosted

        def seconds_left() -> float | None:
            with self.app.store.read() as c:
                turn = hosted.current_turn(c, c.execute("SELECT id FROM rooms").fetchone()[0])
            return None if turn["deadline_at"] is None else (datetime.fromisoformat(turn["deadline_at"]) - datetime.now(UTC)).total_seconds()

        await self.open_and_start()
        self.assertIsNone(seconds_left())                      # global default in tests: no limit
        self.assertIn("跟随全局设置", await self.host.say("/团 主持 限时"))
        self.assertIn("只有主持人", await self.bob.say("/团 主持 限时 3"))
        changed = await self.host.say("/团 主持 限时 3")
        self.assertIn("回合限时改为3 分钟", changed)
        self.assertIn("从现在起重新计时", changed)
        self.assertAlmostEqual(seconds_left(), 180, delta=5)
        await self.host.say("/团 选 B")
        self.assertAlmostEqual(seconds_left(), 180, delta=5)    # the next turn uses the table limit too
        self.assertIn("本桌单独设置", await self.host.say("/团 主持 限时"))
        self.assertIn("不限时", await self.host.say("/团 主持 限时 0"))
        self.assertIsNone(seconds_left())
        self.app.config = dataclasses.replace(self.app.config, turn_timeout_seconds=600)
        self.assertIn("跟随全局设置", await self.host.say("/团 主持 限时 默认"))
        self.assertAlmostEqual(seconds_left(), 600, delta=5)
        self.assertIn("写法", await self.host.say("/团 主持 限时 很久"))


if __name__ == "__main__":
    unittest.main()
