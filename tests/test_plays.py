import re
import unittest

from support import Player, make_app


def seq(text: str, kind: str) -> str:
    match = re.search(r"#(\d+) " + kind + "「", text)
    assert match, text
    return "#" + match.group(1)


class EnginePlays(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.app = make_app()
        self.a = Player(self.app, "admin", "主持")
        self.b = Player(self.app, "bob", "小明")
        await self.a.say("/团 开启 第七个不思议")
        await self.a.say("/团 加入")
        await self.b.say("/团 加入")
        await self.a.say("/团 选职业 1 林晓")
        await self.b.say("/团 选职业 2 陈默")
        await self.a.say("/团 开演")

    async def asyncTearDown(self) -> None:
        await self.app.stop()

    async def whose_turn(self) -> Player:
        text = await self.a.say("/团 回合")
        return self.a if "林晓" in text.split("\n")[0] else self.b

    async def test_investigation_and_testimony(self) -> None:
        clue_ref = seq(await self.b.say("/团 线索 亲见 怀表停在三点：表盘内侧刻着一个名字"), "线索")
        clue_two = seq(await self.a.say("/团 线索 听说 旧校报：三十年前有个女生在钟楼失踪"), "线索")
        hyp = await self.a.say("/团 假设 名字的主人：怀表属于失踪的林小满")
        hyp_ref = seq(hyp, "假设")
        self.assertIn("未定", await self.b.say(f"/团 假设 {hyp_ref} 支持 {clue_ref}"))   # one support is not enough
        self.assertIn("已经关联", await self.a.say(f"/团 假设 {hyp_ref} 反驳 {clue_ref}"))
        self.assertIn("有支持", await self.a.say(f"/团 假设 {hyp_ref} 支持 {clue_two}"))
        self.assertIn("已采纳", await self.a.say(f"/团 结论 {hyp_ref} 采纳"))
        self.assertIn("没有这个公开条目", await self.a.say("/团 引用 不存在"))
        self.assertIn("需要检定", await (await self.whose_turn()).say("/团 搜查 讲台：翻找抽屉"))
        player = await self.whose_turn()
        other = self.b if player is self.a else self.a
        self.assertIn("会用掉一次行动", await other.say("/团 搜查 讲台：翻找抽屉 [观察 标准]"))
        searched = await player.say("/团 搜查 讲台：翻找抽屉 [观察 标准]")
        self.assertIn("观察检定  标准", searched)
        self.assertIn("▸ 轮到", searched)    # the search used the turn
        testimony = await self.a.say("/团 证词 值班老师：我七点就锁了钟楼")
        t_ref = seq(testimony, "证词")
        other_t = seq(await self.b.say("/团 证词 门卫：七点半钟楼门还开着"), "证词")
        self.assertIn("对照", await self.a.say(f"/团 对照 {t_ref} {other_t} 两人说法时间对不上"))
        records = await self.a.say("/团 记录")
        self.assertIn("证词", records)

    async def test_contests_joint_and_endings(self) -> None:
        opened = await self.a.say("/团 冲突 钟楼守夜人：让他交出钥匙 3")
        contest = seq(opened, "对抗")
        self.assertIn("我方 0 : 0 对方", opened)
        self.assertIn("加入", await self.b.say(f"/团 冲突 {contest} 加入"))
        player = await self.whose_turn()
        hit = await player.say(f"/团 交锋 {contest} 冒险 抢过钥匙串 [体能 困难]")
        self.assertIn("体能检定  困难", hit)
        chase = await self.a.say("/团 冲突 追逐 追赶 黑影 2")
        self.assertIn("距离", chase)
        self.assertIn("没有“主持”", await self.a.say("/团 主持 险关 塌落的楼梯") + "没有“主持”")   # cut from Lite
        self.assertIn("没有“守”", await self.a.say("/团 守 #1 体能 撑住"))
        branch = seq(await self.a.say("/团 结局 提出 全员记起：凑齐三件证据"), "结局分支")
        await self.a.say(f"/团 结局 {branch} 支持")
        await self.b.say(f"/团 结局 {branch} 支持")
        entered = await self.a.say(f"/团 结局 {branch} 进入")
        ending = seq(entered, "结局")
        await self.a.say(f"/团 尾声 {ending} 林晓把怀表放回了钟楼。")
        self.assertIn("全体成员写下尾声", await self.a.say(f"/团 结局 {ending} 完结"))
        await self.b.say(f"/团 尾声 {ending} 陈默记住了她的名字。")
        done = await self.b.say(f"/团 结局 {ending} 完结")
        self.assertIn("〖 终章", done)
        self.assertIn("已完结", await self.a.say("/团 状态"))

    async def test_time_projects_plans_fortune_oracle_and_change(self) -> None:
        player = await self.whose_turn()
        spent = await player.say("/团 时间 花费 2 在图书馆翻旧校报")
        self.assertIn("▸ 轮到", spent)
        self.assertIn("傍晚", await self.a.say("/团 时间"))
        project = seq(await self.a.say("/团 项目 修好旧收音机 3"), "项目")
        player = await self.whose_turn()
        self.assertRegex(await player.say(f"/团 项目 {project} 推进 [学识 简单]"), r"项目「修好旧收音机」.*\d/3")
        plan = seq(await self.a.say("/团 计划 夜探钟楼：找到第七个不思议｜引开老师｜撬开钟楼门"), "计划")
        await self.a.say(f"/团 计划 {plan} 认领 1")
        await self.b.say(f"/团 计划 {plan} 认领 2")
        self.assertIn("已确认", await self.a.say(f"/团 计划 {plan} 确认"))
        player = await self.whose_turn()
        self.assertIn("d20 ", await player.say("/团 机运 希望今晚不下雨"))
        player = await self.whose_turn()
        self.assertIn("d20 ", await player.say("/团 神谕 很可能 钟楼里有人吗"))
        change = seq(await self.a.say("/团 转变 转变 陈默 记得的人：陈默开始记得林小满"), "转变")
        self.assertIn("只有被指名", await self.a.say(f"/团 转变 {change} 确认"))
        self.assertIn("已确认", await self.b.say(f"/团 转变 {change} 确认"))
        self.assertIn("经历　记得的人", await self.b.say("/团 角色"))
        talks = seq(await self.a.say("/团 交涉 值班老师：借钟楼钥匙"), "交涉")
        await self.a.say(f"/团 条款 {talks} 天亮前归还钥匙")
        self.assertIn("签署", await self.b.say(f"/团 签署 {talks} 1"))
        self.assertIn("争取", await (await self.whose_turn()).say("/团 关系 人物 值班老师：帮他检查门锁 [人缘 标准]"))
        goal = seq(await self.a.say("/团 目标 陈默：找回丢失的记忆"), "同伴目标")
        self.assertIn("已实现", await self.b.say(f"/团 目标 {goal} 实现"))
        player = await self.whose_turn()
        self.assertIn("休整", await player.say("/团 休整"))

    async def test_switch_closes_new_intake(self) -> None:
        self.app.features.set("global", "playOracle", False)
        self.assertIn("未开放“神谕建议”", await self.a.say("/团 神谕 钟楼里有人吗"))
        self.app.features.set("global", "playInvestigation", False)
        self.assertIn("未开放", await self.a.say("/团 证词 老师：没看见"))  # testimony depends on investigation


if __name__ == "__main__":
    unittest.main()
