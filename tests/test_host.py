import json
import unittest
from datetime import datetime

from support import Player, group_text, make_app, scripted_model

from roll_lite import shared


class TableCase(unittest.IsolatedAsyncioTestCase):
    """Three seated players, the admin hosting, story started."""
    responder = staticmethod(scripted_model)

    async def asyncSetUp(self) -> None:
        self.app = make_app(responder=self.responder)
        self.host = Player(self.app, "admin", "主持")
        self.bob = Player(self.app, "bob", "小明")
        self.carol = Player(self.app, "carol", "小红")
        await self.host.say("/团 开启 1")
        for player, name in ((self.host, "林晓"), (self.bob, "陈默"), (self.carol, "苏晴")):
            await player.say("/团 加入")
            await player.say(f"/团 选职业 1 {name}")
        await self.host.say("/团 开演")

    async def asyncTearDown(self) -> None:
        await self.app.stop()

    def room(self):
        with self.app.store.read() as c:
            return c.execute("SELECT * FROM rooms").fetchone()


class HostTools(TableCase):
    async def test_handover_needs_acceptance_from_a_regular_host(self) -> None:
        moved = await self.host.say("/团 主持 交棒 陈默")          # an admin hands over at once
        self.assertIn("小明 接任主持人", moved)
        self.assertEqual(self.room()["host_user_id"], "bob")
        offer = await self.bob.say("/团 主持 交棒 苏晴")
        self.assertIn("想把主持人交给 小红", offer)
        self.assertIn("没有交给你的主持人邀请", await self.host.say("/团 接棒"))
        self.assertIn("小红 接任主持人", await self.carol.say("/团 接棒"))
        self.assertEqual(self.room()["host_user_id"], "carol")
        self.assertIn("只有主持人", await self.bob.say("/团 暂停"))

    async def test_remove_readmit_lock_and_presence(self) -> None:
        self.assertIn("不能移出主持人", await self.host.say("/团 主持 移出 林晓"))
        removed = await self.host.say("/团 主持 移出 陈默 刷屏")
        self.assertIn("已被请离", removed)
        self.assertIn("原因：刷屏", removed)
        self.assertIn("主持人已请你离开", await self.bob.say("/团 加入"))
        self.assertIn("小明", await self.host.say("/团 主持 放行"))
        self.assertIn("已放行 小明", await self.host.say("/团 主持 放行 小明"))
        self.assertIn("入座已关闭", await self.host.say("/团 主持 入座 关"))
        self.assertIn("关闭了入座", await self.bob.say("/团 加入"))
        await self.host.say("/团 主持 入座 开")
        self.assertIn("已入座", await self.bob.say("/团 加入"))
        away = await self.host.say("/团 主持 暂离 苏晴")
        self.assertIn("主持人让 苏晴 暂离", away)
        self.assertIn("苏晴 已经是暂离状态", await self.host.say("/团 主持 暂离 苏晴"))
        self.assertIn("回到队列", await self.host.say("/团 主持 返回 2"))   # seat number in /团 阵容 order

    async def test_turn_order_rewind_and_rebuild(self) -> None:
        turned = await self.host.say("/团 主持 轮到 苏晴")
        self.assertIn("▸ 轮到 苏晴", turned)
        order = await self.host.say("/团 主持 顺序 陈默 苏晴")
        self.assertIn("1. 陈默", order)
        self.assertIn("3. 林晓", order)
        acted = await self.carol.say("/团 选 B")
        self.assertIn("▸ 轮到 林晓", acted)                         # after 苏晴 the new order wraps to 林晓
        with self.app.store.read() as c:
            stories = c.execute("SELECT COUNT(*) FROM events WHERE kind='narration'").fetchone()[0]
        rewound = await self.host.say("/团 主持 回退")
        self.assertIn("已回退到「第 1 轮 · 苏晴 行动前」", rewound)
        self.assertIn("▸ 轮到 苏晴", rewound)
        with self.app.store.read() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM events WHERE kind='narration'").fetchone()[0], stories - 1)
        self.assertEqual(self.room()["state"], "running")
        self.assertIn("没有可以回退的行动", await self.host.say("/团 主持 回退"))
        rebuilt = await self.host.say("/团 主持 退回 苏晴 职业不合设定")
        self.assertIn("主持人请 小红 重新建卡", rebuilt)
        self.assertIn("▸ 轮到", rebuilt)                            # the turn moved on
        self.assertIn("苏晴二", await self.carol.say("/团 选职业 2 苏晴二"))

    async def test_host_check_private_adjustments_and_vote_time(self) -> None:
        from roll_lite.dice import roll_check
        from roll_lite.plays import hosted
        attribute = next(iter(shared.rules(self.room())["attributes"].values()))
        checked = await self.host.say(f"/团 主持 检定 陈默 {attribute} 困难 听见楼上的脚步")
        self.assertIn("主持人要求检定：听见楼上的脚步", checked)
        self.assertIn("检定结果已记入剧情", checked)
        with self.app.store.read() as c:
            self.assertIn("【主持检定】", c.execute("SELECT text FROM events WHERE kind='check' ORDER BY id DESC").fetchone()[0])
        original = hosted.roll_check
        hosted.roll_check = lambda mod, dc: roll_check(mod, dc, face=1)
        try:
            hurt = await self.host.say(f"/团 主持 检定 陈默 {attribute} 简单 受伤")
        finally:
            hosted.roll_check = original
        self.assertIn("失败代价将在下一回合正文写完后生效", hurt)
        private = Player(self.app, "admin", "主持", group=None)
        self.assertIn("已撤销调整", await private.say("/团 主持 调整 撤销"))
        queued = await private.say("/团 主持 调整 苏晴 体力 -2")
        self.assertIn("已加入待生效：苏晴 体力 -2", queued)
        self.assertNotIn("苏晴 体力", group_text(self.app))          # nothing reached the group
        self.assertIn("待生效的调整", await private.say("/团 主持 调整"))
        self.assertIn("已撤销调整", await private.say("/团 主持 调整 撤销"))
        self.assertIn("没有待生效的调整", await private.say("/团 主持 调整"))
        self.assertIn("对队伍的态度 → 友善", await private.say("/团 主持 调整 态度 值班老师 友善"))
        self.assertIn("写法", await private.say("/团 主持 调整 苏晴 很多"))
        self.assertIn("表决时限改为 5 分钟", await self.host.say("/团 主持 表决时限 5"))
        await self.bob.say("/团 全队 一起冲上钟楼")
        with self.app.store.read() as c:
            vote = c.execute("SELECT * FROM votes WHERE state='open'").fetchone()
        span = datetime.fromisoformat(vote["deadline_at"]) - datetime.fromisoformat(vote["created_at"])
        self.assertEqual(span.total_seconds(), 300)


def padded(system: str, prompt: str) -> str:
    """Narration long enough for the '简洁' length (100–300 visible characters)."""
    text = scripted_model(system, prompt)
    if "根据机械回执叙述" in system and "正文篇幅" in system:
        value = json.loads(text)
        value["paragraphs"] = ["走廊尽头的钟楼又敲了一下，声音在空荡的教学楼里来回撞，久久不散。" * 4]
        return json.dumps(value, ensure_ascii=False)
    return text


class NarrativeSettings(TableCase):
    responder = staticmethod(padded)

    async def test_length_and_style_reach_the_model(self) -> None:
        self.assertIn("没有单独设置", await self.host.say("/团 主持 篇幅"))
        self.assertIn("100–300 字", await self.host.say("/团 主持 篇幅 简洁"))
        self.assertIn("对白与描写：多对白；风格：冷峻克制", await self.host.say("/团 主持 文风 多对白 冷峻克制"))
        reply = await self.host.say("/团 选 A")
        self.assertIn("钟楼又敲了一下", reply)
        system = next(s for s, _ in reversed(self.app.context.calls) if "根据机械回执叙述" in s)
        self.assertIn("100—300", system)
        self.assertIn("“多对白”", system)
        self.assertIn("冷峻克制", system)
        self.assertIn("恢复默认", await self.host.say("/团 主持 篇幅 默认"))
        await self.bob.say("/团 选 A")
        prompt = next(p for s, p in reversed(self.app.context.calls) if "根据机械回执叙述" in s)
        self.assertIn("主持人文风要求", prompt)                     # style without a length stays a plain request

    async def test_review_mode_holds_the_draft_for_the_host(self) -> None:
        self.assertIn("先私聊我", await self.host.say("/团 主持 审稿 开"))
        private = Player(self.app, "admin", "主持", group=None)
        await private.say("/团 帮助")
        self.assertIn("审稿模式已开启", await self.host.say("/团 主持 审稿 开"))
        held = await self.host.say("/团 选 A")
        self.assertIn("正在等主持人审阅", held)
        self.assertNotIn("▸ 轮到 陈默", held)
        drafts = [text for umo, text in self.app.context.sent if umo == "fake:FriendMessage:admin"]
        self.assertIn("正文草稿 · 待审阅", drafts[-1])
        self.assertIn("等主持人审阅", await self.bob.say("/团 选 A"))
        await private.say("/团 主持 重写 多写一点钟声")
        prompt = next(p for s, p in reversed(self.app.context.calls) if "根据机械回执叙述" in s)
        self.assertIn("主持人审稿意见", prompt)
        self.assertEqual(len([u for u, _ in self.app.context.sent if u == "fake:FriendMessage:admin"]), len(drafts) + 1)
        ack = await private.say("/团 主持 发布")
        self.assertIn("已发到群里", ack)
        self.assertIn("▸ 轮到 陈默", group_text(self.app))
        self.assertIn("现在没有等待审阅的正文", await private.say("/团 主持 发布"))
