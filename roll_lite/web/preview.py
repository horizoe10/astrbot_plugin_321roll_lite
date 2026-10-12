"""Sample messages for the WebUI message-style preview.

The samples go through the same layouts as the game (roll_lite/messages.py),
so what the admin sees is what the group receives.
"""
from __future__ import annotations

from typing import Any

from .. import messages
from ..cards import THEMES, card_html
from ..delivery import card_art, load_prefs
from ..render import BT, MARKDOWN, MARKDOWN_PLATFORMS, PLAIN, render

WORLD = "第七个不思议 · 钟楼下的旧校舍"


def _turn() -> list[tuple[str, str, Any]]:
    status = messages.action_status(
        "林晓", "侦探", 3, "我借着手电的光，去翻看值班室抽屉里那本发黄的登记簿。",
        {"kind": "check", "attribute": "观察", "difficulty": "hard", "dc": 15, "face": 14, "modifier": 2, "total": 16,
         "outcome": "success"},
        [("体力", 4, 5, None), ("理智", 3, 5, -1)])
    story = messages.narration(
        "登记簿的最后一页停在十二年前的十月七日。字迹到一半忽然变得潦草，墨水在纸上拖出长长的一道。\n\n"
        "你翻过这一页时，走廊尽头的钟楼传来一声闷响——指针倒退了一格。值班室的灯跟着暗了一下，又亮起来。",
        "旧校舍 · 值班室", "第二幕 · 倒走的钟").with_art("seventh-mystery", "act:2", "第七个不思议 · 第二幕")
    choices = messages.turn_prompt("林晓", "小林", "10001", 3, [
        {"label": "A", "text": "撕下最后一页，带去钟楼对照", "tag": "观察·标准", "chance": 70},
        {"label": "B", "text": "沿着墨迹的方向检查地板", "tag": "敏捷·困难·失败受伤", "chance": 35},
        {"label": "C", "text": "先退回走廊，和同伴汇合", "tag": "休整"},
    ], "mixed", 5, loadout=["细节回溯 观察 +2 · 剩 1 次", "手电 ×1"],
        others=messages.others_guide("林晓", crew=True, seats=1))
    return [("status", "个人状态", status), ("narration", "故事正文", story), ("choices", "行动选项", choices)]


def _others() -> list[tuple[str, str, Any]]:
    opening = messages.scene_card(
        "封箱第七夜", "庆和园后台，腊月的穿堂风从门缝里钻进来，混着油彩、刨花和煤油灯的气味。扮戏桌上摊着半开的彩匣。\n\n"
        "那面大穿衣镜立在墙角，红布瘫在地上，像被谁从下往上掀开的。镜面干净得反常，里头映着一张上好妆的脸，可镜子前空无一人。\n\n"
        "“诸位，今晚无论如何得唱完。唱不完，谁也走不了。”班主赵金生说完，往大门的方向瞟了一眼。",
        "让今晚的《夜奔》能唱完，并弄清镜子被揭开、大门被锁的来由。",
        [("赵金生", "庆和园的新班主，四十来岁，圆脸上一直挂着汗。说话总带三分笑"), ("柳三娘", "老板娘，深色旗袍，鬓边一朵白花。"),
         ("老周", "琴师兼检场，六十上下，背有点驼，指节粗大。"), ("二楼的老看客", "旧式长衫，瓜皮帽压得很低。")],
    ).with_art("final-curtain", "act:1", "谢幕之夜 · 第一幕")
    card = messages.character_card({
        "name": "林晓", "archetype": "侦探", "archetype_text": "习惯先看细节再下结论", "user_name": "小林",
        "attributes": [("观察", 14, 2), ("敏捷", 10, 0), ("意志", 12, 1), ("学识", 11, 0), ("交际", 9, -1)],
        "resources": [("体力", 4, 5), ("理智", 3, 5)],
        "skills": [("细节回溯", "回看一次已发生的场景，找出被忽略的线索", 1)],
        "items": ["手电", "发黄的登记簿"], "traits": [],
        "persona": {"name": "林晓", "intro": "报社派来旧校舍采访的实习记者，对十二年前那桩失踪案比谁都上心。", "tags": ["记者", "现代"],
                    "text": "短发，总背着一台旧相机；好奇、嘴硬心软，爱用反问句。报社实习生，正在追一桩旧案。", "avatar": ""}})
    vote = messages.vote_card("钟楼的门要不要现在打开", "门缝里透出微弱的光，门后传来翻书声。", [
        {"key": "A", "label": "现在打开", "description": "趁它还没察觉", "risk": "高"},
        {"key": "B", "label": "等到午夜", "description": "按登记簿上的时间", "cost": "失去一轮"},
    ], 2, 4, 3)
    receipt = messages.play_receipt("林晓", "提出假设「值班员没有离开过钟楼」",
                                    records=[messages.record_line(7, "假设", "值班员没有离开过钟楼", "有支持",
                                                                  "支持 **#2** **#5** · 反驳 **#3**")])
    status = messages.status_card(WORLD, "进行中", (2, 4, "倒走的钟"), 3, "第 1 日 · 深夜", "旧校舍 · 值班室",
                                  "在午夜前找到钟楼钥匙",
                                  {"name": "林晓", "archetype": "侦探", "resources": [("体力", 4, 5), ("理智", 3, 5)]},
                                  ["第 3 轮：林晓（等待行动）"], world="seventh-mystery", party=[
                                      {"name": "林晓", "role": "侦探", "player": "小林", "resources": [("体力", 4, 5), ("理智", 3, 5)],
                                       "acting": True, "away": False},
                                      {"name": "陈默", "role": "校工", "player": "阿野", "resources": [("体力", 2, 5), ("理智", 5, 5)],
                                       "acting": False, "away": False},
                                      {"name": "苏晴", "role": "学生会长", "player": "猫猫", "resources": [("体力", 5, 5), ("理智", 1, 5)],
                                       "acting": False, "away": True}],
                                  npcs=[{"name": "值班老师", "standing": 1, "tier": "友善"}, {"name": "钟楼里的人", "standing": -2, "tier": "戒备"},
                                        {"name": "宿管阿姨", "standing": 0, "tier": "中立"}])
    return [("narration", "开场 · 场景卡", opening), ("choices", "集体表决", vote), ("sheet", "角色卡", card),
            ("receipt", "玩法回执", receipt), ("room", "/团 状态", status), *_moments(),
            ("receipt", "开团 · 入座指南", messages.table_guide(WORLD, 2, 4)), *_queries(), *_daily(), *_fun(),
            *_pastimes(), *_adventure(), *_banter(), *_ties(), *_economy(), *_pacing(), *_personas(), *_building()]


def _building() -> list[tuple[str, str, Any]]:
    """/团 建卡: the three depths, a 定制 draft mid-way and an AI 精雕 draft at its last step."""
    rows = [{"key": "quick", "label": "快选", "desc": "挑一个职业就上桌，属性和技能按职业来", "steps": "1 条指令", "time": "30 秒",
             "cmd": "/团 建卡 快选", "closed": ""},
            {"key": "custom", "label": "定制", "steps": "约 7 步", "time": "2–3 分钟", "cmd": "/团 建卡 定制", "closed": "",
             "desc": "在职业上挪最多 4 点属性、换 1 项技能，选出身、多带一件东西、写一句来历"},
            {"key": "forge", "label": "精雕", "steps": "约 10 步", "time": "5–10 分钟", "cmd": "/团 建卡 精雕", "closed": "",
             "desc": "属性同定制，技能从 12 项里任选 2 项，加上装备、背景三问和开局关系"}]
    modes = messages.build_modes({"kind": "build_modes", "world": "灰冠之下：祖约", "facts": "5 项属性 6–16，合计 55；技能每人 2 项",
                                  "rows": rows, "ai": {"open": True, "left": 4, "per_day": 5}, "private": True})
    attrs = [("力量", 10, 0), ("灵巧", 14, 0), ("感知", 8, 0), ("学识", 15, -2), ("魅力", 8, 2)]
    labels = ["职业", "名字", "属性", "技能", "出身", "随身物品", "背景"]
    custom = {"kind": "build_draft", "mode": "custom", "mode_label": "定制", "world": "灰冠之下：祖约",
              "steps": [{"key": str(i), "label": l, "state": "done" if i < 3 else "now" if i == 3 else "todo"} for i, l in enumerate(labels)],
              "position": 4, "total": 7, "archetype": "机工", "name": "老秦", "look": "",
              "attributes": [{"name": n, "base": v, "delta": d, "value": v + d, "min": 6, "max": 16} for n, v, d in attrs],
              "moved": 2, "move_limit": 4, "skills": [{"name": "火泵", "new": False}, {"name": "临时改装", "new": False}],
              "origin": "", "items": [], "kit": "", "answers": [], "relation": "", "relation_kind": "", "ai": None, "notes": [],
              "question": {"key": "skills", "label": "技能", "title": "换一项技能", "skip": True, "example": "/团 建卡 讨价还价 换 火泵",
                           "text": "用技能池里的一项换掉职业自带的一项，最多换 1 项。写法：池子里的技能 换 自带的技能。",
                           "options": [{"name": n, "note": t, "on": n in ("火泵", "临时改装")} for n, t in (
                               ("明守", "正面挡住冲击"), ("火泵", "压住火势与毒烟"), ("临时改装", "现场拼出能用的工具"), ("讨价还价", "让对方松口"),
                               ("救治", "止血、包扎、稳住伤势"), ("航测", "在地脉里找路"))]},
              "ready": True}
    forge = {**custom, "mode": "forge", "mode_label": "精雕", "head": "AI 起草的角色", "position": 10, "total": 10,
             "steps": [{"key": str(i), "label": l, "state": "done" if i < 9 else "now"} for i, l in
                       enumerate(["职业", "名字", "属性", "技能", "出身", "装备包", "背景", "背景", "背景", "开局关系"])],
             "look": "嘴硬心软，袖口总沾着机油", "skills": [{"name": "临时改装", "new": False}, {"name": "救治", "new": True}],
             "origin": "〔灰脊山脉〕", "kit": "矿工包", "items": ["『矿灯』×1", "『绷带卷』×2"],
             "answers": [{"q": "你为什么会来到祖约？", "a": "替死在矿下的徒弟讨个说法"}, {"q": "你欠谁一个人情？", "a": "欠了戍卫队长一条命"},
                         {"q": "你最怕什么？", "a": "再听见塌方前那声闷响"}],
             "ai": {"understood": "嘴硬心软、会修机器的老兵 → 机工，技能换入救治", "notes": ["属性调整要加减相等、合计不超过 4 点，已收拢为 ±2"],
                    "left": 5, "request": "嘴硬心软、会修机器的老兵"},
             "question": {"key": "relation", "label": "开局关系", "title": "开局关系", "skip": True, "example": "/团 建卡 1 发小，欠他一条命",
                          "text": "和同桌的人定一层关系（确认后发出羁绊邀请，对方同意才生效），或者认一位旧识。",
                          "options": [{"name": "林晓", "note": "同桌，确认后发出羁绊邀请"}, {"name": "萨琳", "note": "旧识，只写进故事"}]}}
    return [("sheet", "/团 建卡", modes), ("sheet", "建卡 · 定制中", messages.build_draft(custom)),
            ("sheet", "建卡 · AI 起草", messages.build_draft(forge))]


def _ties() -> list[tuple[str, str, Any]]:
    """闪回, 羁绊 and 竞猜 cards."""
    cast = [{"id": "a1", "name": "林晓", "role": "侦探"}, {"id": "a2", "name": "陈默", "role": "校工"},
            {"id": "a3", "name": "苏晴", "role": "学生会长"}, {"id": "a4", "name": "周野", "role": "转学生"}]
    bond = lambda a, b, text: {"a": a["name"], "b": b["name"], "a_id": a["id"], "b_id": b["id"], "text": text}
    bonds = [bond(cast[0], cast[1], "发小，欠他一条命"), bond(cast[2], cast[0], "互相看不顺眼的同桌"),
             bond(cast[3], cast[1], "替他瞒着一个秘密")]
    status = messages.action_status(
        "林晓", "侦探", 5, "我想起花盆底下的备用钥匙，和陈默一起撞开钟楼的门。",
        {"kind": "check", "attribute": "敏捷", "difficulty": "hard", "dc": 15, "face": 11, "modifier": 6, "total": 17,
         "outcome": "success", "success": True, "aid": {"name": "陈默", "bonus": 3, "bond": "发小，欠他一条命", "changes": {}},
         "flashback": {"text": "我早就把备用钥匙藏在值班室的花盆底下", "bonus": 2},
         "wager": {"outcome": "success", "right": ["猫猫", "阿丁"], "wrong": ["老丹"]}},
        [("体力", 4, 5, None), ("理智", 2, 5, -1)])
    seers = [{"name": "猫猫", "right": 4, "total": 5}, {"name": "阿丁", "right": 3, "total": 5}, {"name": "老丹", "right": 1, "total": 4}]
    return [
        ("receipt", "/团 闪回", messages.flashback_told("林晓", "我早就把备用钥匙藏在值班室的花盆底下", "理智", -1, 2, 5, 2)),
        ("receipt", "/团 闪回 · 说明", messages.flashback_guide("这一幕你还能闪回一次。")),
        ("receipt", "/团 羁绊 · 提出", messages.bond_proposed("林晓", "陈默", "发小，欠他一条命", "10002", "阿野")),
        ("receipt", "/团 羁绊 同意", messages.bond_formed("林晓", "陈默", "发小，欠他一条命", 3)),
        ("receipt", "/团 羁绊 · 关系图", messages.bond_map(cast, bonds[:2], [bonds[2]])),
        ("moment", "终章 · 人物关系", messages.bond_map(cast, bonds, [], finale=True)),
        ("receipt", "/团 押", messages.wager_board("林晓", 5, [{"name": "猫猫", "pick": "success"}, {"name": "阿丁", "pick": "success"},
                                                          {"name": "老丹", "pick": "failure"}], seers, note="老丹 押 林晓 检定失败")),
        ("status", "个人状态 · 闪回、羁绊援手与竞猜", status),
    ]


def _economy() -> list[tuple[str, str, Any]]:
    """整备、商店、买卖、转交与故事得失."""
    ware = lambda name, price, owned=0, text="": {"name": name, "price": price, "sell": price // 2, "text": text, "owned": owned}
    shops = [{"name": "卡隆商行", "kind": "杂货", "text": "门口挂着冬粮价目，掌柜正往账本上记赊欠。", "place": "", "open": True,
              "wares": [ware("麦饼", 2, 3, "一块顶半天"), ware("绷带卷", 4, 1), ware("矿灯油", 3), ware("火绒盒", 5)]},
             {"name": "老铁匠铺", "kind": "武器", "text": "", "place": "锻铁街", "open": False,
              "wares": [ware("短柄镐", 12), ware("铁皮护臂", 15)]}]
    members = [{"name": "诺安", "done": True}, {"name": "萨琳", "done": False}, {"name": "李逍遥", "done": True}]
    rows = [{"name": "诺安", "bought": ["麦饼×2", "绷带卷×1"], "sold": [], "shops": ["卡隆商行"], "spent": 8, "earned": 0, "after": 17,
             "done": True},
            {"name": "萨琳", "bought": ["矿灯油×1"], "sold": ["短柄镐×1"], "shops": ["卡隆商行"], "spent": 3, "earned": 6, "after": 31,
             "done": True},
            {"name": "李逍遥", "bought": [], "sold": [], "shops": [], "spent": 0, "earned": 0, "after": 12, "done": True}]
    ledger = [{"who": "诺安", "kind": "money", "name": "铜轮", "delta": 6, "reason": "替泵房修好了阀门，工头当场结了工钱", "after": 23},
              {"who": "萨琳", "kind": "item", "name": "绷带卷", "delta": -1, "reason": "给受伤的矿工包扎", "after": 0}]
    return [
        ("receipt", "/团 商店", messages.shop_card(shops, "铜轮", 25, place="卡隆镇 · 傍晚", outfit=True, sell=50, single=False)),
        ("receipt", "/团 主持 整备", messages.outfit_card("整备开始", "卡隆镇 · 傍晚", ["卡隆商行"], members, 3, "铜轮")),
        ("receipt", "/团 买", messages.trade_card("buy", "诺安", "卡隆商行", "麦饼", 2, -4, 21, "铜轮", held=5)),
        ("receipt", "/团 给", messages.gift_card("萨琳", "诺安", "5 铜轮", 26, "铜轮")),
        ("receipt", "整备汇总", messages.outfit_summary(rows, "铜轮", "卡隆镇 · 傍晚", "全员整备好了", ["萨琳 → 诺安：5 铜轮"])),
        ("receipt", "故事里的得失", messages.ledger_card(ledger, "铜轮")),
        ("receipt", "走进有店的地点", messages.shops_nearby(["卡隆商行", "老铁匠铺"], "卡隆镇 · 傍晚")),
        ("receipt", "新的一幕 · 工钱", messages.wage_card(4, "铜轮", [{"name": "诺安", "after": 27}, {"name": "萨琳", "after": 35}])),
        ("receipt", "/团 主持 记账", messages.ledger_draft(["诺安 铜轮 +6　替泵房修好了阀门", "萨琳 绷带卷 -1　给受伤的矿工包扎"],
                                                      "李逍遥 铜轮 +20　捡到一袋钱")),
    ]


def _pacing() -> list[tuple[str, str, Any]]:
    """节奏、换幕提议、收尾表决、世界推进与尾声."""
    view = {"scene": {"done": 5, "limit": 4, "title": "钟楼下的走廊"}, "act": {"done": 7, "limit": 8, "number": 2, "title": "倒走的钟",
            "last": False}, "story": {"done": 13, "target": 32, "hard": 48}, "grace": 2, "ending": True, "preset": "标准", "off": False,
            "source": "世界设置", "own": {}, "state": {"label": "局势在酝酿", "detail": "这个场景已经 5 轮，正文会让局面变化；1 轮后世界会自己推进"},
            "offer": None, "closing": None, "epilogue": None}
    choices = [{"label": "A", "text": "钟声归位——把钟楼还给夜晚", "tag": "", "chance": None, "closing": "钟声归位"},
               {"label": "B", "text": "追上楼梯口的人影", "tag": "敏捷·困难", "chance": 45},
               {"label": "C", "text": "翻看值班室的登记簿", "tag": "观察·简单", "chance": 75},
               {"label": "D", "text": "叫醒宿管阿姨", "tag": "", "chance": None}]
    return [
        ("receipt", "/团 节奏", messages.pace_card(view, True)),
        ("choices", "收尾提议期间的行动卡", messages.turn_prompt("林晓", "林晓", "u1", 14, choices, "hybrid", 5,
                                                         pace=("收尾提议", "要不要给「钟声归位」收尾？在座的人发送 /团 收尾 同意 或 /团 收尾 再玩"))),
        ("receipt", "/团 节奏 · 玩家看到的表决提示", messages.pace_card({**view, "stage": "offer", "state": {
            "label": "收尾提议", "detail": "要不要给「钟声归位」收尾？在座的人发送 /团 收尾 同意 或 /团 收尾 再玩；2 轮内没过半就继续冒险"}}, False)),
        ("receipt", "本幕将尽", messages.act_offer(3, "空着的座位", "第三排最左边的位子，一直没人坐。", 2, 8, False)),
        ("receipt", "本幕将尽 · 核心版待命名", messages.act_offer(2, "", "", 2, 8, True)),
        ("receipt", "收尾提议", messages.closing_offer("钟声归位", "有人选了收束选项", "option", ["林晓"], ["陈默"], ["苏晴"], 2, 2)),
        ("receipt", "继续冒险", messages.closing_kept("钟声归位", ["陈默", "苏晴"])),
        ("receipt", "继续冒险 · 表决到期", messages.closing_kept("钟声归位", [], expired=True)),
        ("receipt", "进入收尾", messages.closing_start("钟声归位", 2, False, "有人选了收束选项")),
        ("receipt", "世界推进", messages.world_push(6, "钟楼下的走廊", "陈默")),
        ("receipt", "世界推进 · 快团", messages.world_push(6, "钟楼下的走廊", "全队", rush=True)),
        ("receipt", "尾声", messages.epilogue_call("钟声归位", [("林晓", "她把钟楼的门锁好，第二天照常去上早自习。"),
                                                           ("陈默", "他把那张照片夹进了校刊的样稿里。")], ["苏晴"], 4)),
        ("receipt", "尾声 · 跳过终章", messages.epilogue_call("钟声归位", [], ["林晓", "陈默", "苏晴"], 5,
                                                             "终章没写出来，主持人跳过了它：故事停在上一段正文，直接写尾声。")),
        ("receipt", "尾声 · 暂停后继续", messages.epilogue_call("钟声归位", [("林晓", "她把钟楼的门锁好，第二天照常去上早自习。")],
                                                              ["陈默"], 2, "故事回来了，接着写尾声：计时从暂停的地方继续。")),
        ("choices", "快团 · 收尾提议期间", messages.rush_prompt(9, choices[:3], 3, "hybrid",
                                                         [("林晓", "小林", "u1", True), ("陈默", "阿野", "u2", False)],
                                                         pace=("收尾提议", "要不要给「钟声归位」收尾？在座的人发送 /团 收尾 同意 或 /团 收尾 再玩"))),
        ("receipt", "/团 X · 尾声阶段", messages.xcard_raised("epilogue")),
    ]

def _adventure() -> list[tuple[str, str, Any]]:
    steps = [("穿过倒塌的石门", "力量", "hard", 15, 0, 30), ("沿溪水绕行", "感知", "easy", 8, 1, 70), ("摇灯呼喊", "魅力", "standard", 12, -1, 40)]
    options = [{"label": "ABC"[i], "text": t, "tag": f"{a}·{messages.DIFFICULTY[d]}", "chance": ch} for i, (t, a, d, dc, m, ch) in enumerate(steps)]
    roll = lambda step, label, text, face, mod, dc, ok, outcome, crit=False, fumble=False: {
        "step": step, "label": label, "text": text, "attr": "感知", "difficulty": "简单", "face": face, "modifier": mod, "total": face + mod,
        "dc": dc, "ok": ok, "crit": crit, "fumble": fumble, "outcome": outcome}
    results = [roll(1, "B", "沿溪水绕行", 14, 1, 8, True, "溪水边你找到守夜人掉落的铜铃，铃舌上缠着一缕红线。"),
               roll(2, "A", "推开倒塌的石门", 6, 0, 15, False, "石块滚下来擦伤了你的手臂，门后的脚印却更清楚了。"),
               roll(3, "C", "摇灯呼喊", 20, -1, 12, True, "雾里有人回应了你的呼喊，守夜人从石碑后探出头来。", crit=True)]
    base = {"title": "雾中的铃", "world": "灰冠之下", "world_id": "greycrown-prequel", "hero": "小林", "role": "戍卫",
            "hook": "你被派去山门外找回失踪的守夜人，只带着一盏风灯。雾越来越浓，远处传来一阵铃声，像是有人在为你引路。",
            "total": 3, "options": options}
    first = messages.adventure_stage({**base, "step": 0, "scene": "雾里有两条路：一条沿着溪水，一条穿过倒塌的石门。铃声似乎从石门那边来。",
                                      "results": []}, fresh=True)
    middle = messages.adventure_stage({**base, "step": 1, "scene": "脚印在一块刻满祖约的石碑前断了。石碑背后有人在喘气，风灯照不过去。",
                                       "results": results[:1]})
    end = messages.adventure_end({**base, "step": 3, "scene": "", "options": [], "results": results, "wins": 2, "tier": "凯旋",
                                  "ending": "你把守夜人带回了山门。他一路上什么也没说，只在进门前把那缕红线塞进了你手里。"})
    return [("daily", "/团 冒险", first), ("daily", "/团 冒险 A", middle), ("daily", "/团 冒险 · 结束", end)]


def _banter() -> list[tuple[str, str, Any]]:
    """台词, 起哄, 援手, 密信, X 卡 and 快团 cards."""
    party = [("林晓", "小林", "10001", True), ("陈默", "阿野", "10002", False), ("苏晴", "猫猫", "10003", True)]
    board = [(name, done) for name, _, _, done in party]
    note = "值班老师在撒谎。他袖口上沾着钟楼的灰，别把登记簿交给他。"
    letters = [("苏晴", "林晓", note), ("林晓", "陈默", "十二点前别上钟楼，我在楼下等你。"),
               ("陈默", "苏晴", "钥匙在我这儿，别告诉任何人。")]
    status = messages.action_status(
        "林晓", "侦探", 4, "我咬牙撞向那扇门，陈默在身后顶着。",
        {"kind": "check", "attribute": "敏捷", "difficulty": "hard", "dc": 15, "face": 13, "modifier": 4, "total": 17,
         "outcome": "success", "all_in": True, "success": True, "aid": {"name": "陈默", "bonus": 2, "changes": {"体力": -1}}},
        [("体力", 3, 5, -1), ("理智", 3, 5, None)])
    return [
        ("receipt", "开演 · 群聊玩法", messages.plays_intro()),
        ("receipt", "/团 说", messages.line_said("林晓", "你们先走，我断后。门后那个声音，我认得。", "陈默：这门打不开")),
        ("receipt", "/团 起哄", messages.heckle_board([(1, "让钟楼的灯突然灭掉", 4, "阿丁"), (2, "宿管阿姨端着一碗夜宵出现", 2, "老丹"),
                                                     (3, "登记簿自己翻到了下一页", 1, "猫猫")], 1, 2)),
        ("receipt", "起哄采纳", messages.heckle_adopted("让钟楼的灯突然灭掉", 4)),
        ("receipt", "/团 援手", messages.aid_offered("陈默", "林晓", "用肩膀顶住门，给她争取三秒", 2)),
        ("status", "个人状态 · 援手与孤注", status),
        ("receipt", "密信 · 群里", messages.letter_passed("苏晴", "林晓", delivered=False, user_id="10001", user_name="小林")),
        ("receipt", "密信 · 收信人私聊", messages.letter_received("苏晴", "林晓", note)),
        ("receipt", "密信 · 递出回执", messages.letter_sent("林晓", True)),
        ("receipt", "/团 密信", messages.letter_inbox("林晓", [("收到", "苏晴", note), ("递出", "陈默", letters[1][2])])),
        ("moment", "终章 · 纸条公开", messages.letters_revealed(letters)),
        ("receipt", "/团 X", messages.xcard_raised()),
        ("moment", "快团开启", messages.rush_toggled(True, 3)),
        ("choices", "快团 · 选项", messages.rush_prompt(4, [
            {"label": "A", "text": "一起撞开钟楼的门", "tag": "敏捷·困难·失败受伤"},
            {"label": "B", "text": "分头找另一条上楼的路", "tag": "观察·标准"},
            {"label": "C", "text": "守在楼下，听门后的动静", "tag": "休整"}], 3, "hybrid", party,
            others=messages.others_guide("", seats=1, bets=False))),
        ("receipt", "快团 · 进度", messages.rush_progress(board)),
        ("receipt", "快团 · 剩 1 分钟", messages.rush_reminder([("陈默", "阿野", "10002")], board)),
    ]


def _personas() -> list[tuple[str, str, Any]]:
    from .. import personas
    row = {"id": "persona-1", "platform": "aiocqhttp", "user_id": "10001", "user_name": "小林", "name": "林晓", "avatar": "",
           "created_at": "2026-10-01T12:00:00+00:00", "updated_at": "2026-10-01T12:00:00+00:00",
           "data_json": '{"appearance": "短发，总背着一台旧相机", "personality": "好奇、嘴硬心软", '
                        '"background": "报社实习生，正在追一桩十二年前的旧案。为了这条新闻，她已经在旧校舍附近蹲了一个星期。", '
                        '"speech": "爱用反问句：“你不觉得奇怪吗？”", "tags": ["记者", "现代"], "summary": "", "source": "card"}'}
    other = {**row, "id": "persona-2", "name": "沈砚", "data_json": '{"personality": "沉默寡言的剑客", "tags": ["武侠"], '
                                                                  '"summary": "出身没落剑庄，说话只说半句。", "summary_by": "manual"}'}
    return [("sheet", "/团 人设 名字", personas.card_msg(personas.view(row))), ("sheet", "/团 人设", personas.list_msg([row, other]))]


def _fun() -> list[tuple[str, str, Any]]:
    dice = messages.dice_roll("小林", "4d6kh3+1", "撬开钟楼的锁", [
        {"label": "4d6kh3", "faces": [6, 2, 5, 1], "kept": [True, True, True, False], "sides": 6, "value": 13},
        {"label": "+1", "value": 1}], 14)
    natural = messages.dice_roll("阿野", "d20", "先手", [{"label": "d20", "faces": [20], "kept": [True], "sides": 20, "value": 20}], 20)
    duel = messages.duel_result("小林", "猫猫", [(12, 12), (17, 9)], "小林", "谁去敲钟楼的门")
    report = messages.battle_report({
        "title": "第七个不思议", "sub": "钟楼下的旧校舍", "world": "seventh-mystery", "state": "进行中", "ending": "", "act": 2, "total": 4,
        "acts": [{"number": 1, "title": "放学后", "best": "陈默（3 次喝彩）"}, {"number": 2, "title": "倒走的钟", "best": ""}],
        "cast": [{"name": "林晓", "role": "侦探", "player": "小林", "turns": 7, "checks": 10, "wins": 7},
                 {"name": "陈默", "role": "校工", "player": "阿野", "turns": 6, "checks": 9, "wins": 5},
                 {"name": "苏晴", "role": "学生会长", "player": "猫猫", "turns": 5, "checks": 7, "wins": 3}],
        "rounds": 18, "checks": 26, "crits": 3, "fumbles": 1, "best": "陈默（5 次喝彩）",
        "outcomes": {"critical": 3, "success": 12, "failure": 10, "fumble": 1},
        "seer": {"name": "猫猫", "right": 7, "total": 9},
        "quote": "钟楼的指针倒退了一格，值班室的灯跟着暗了一下，又亮起来。"})
    schedule = messages.schedule_board("第七个不思议 · 钟楼下的旧校舍", [
        {"label": "10 月 10 日 周六 20:00", "names": ["小林", "猫猫", "阿野"], "decided": False},
        {"label": "10 月 11 日 周日 14:00", "names": ["小林"], "decided": False},
        {"label": "10 月 11 日 周日 20:00", "names": ["猫猫", "老丹"], "decided": False}], ["阿丁"], decided=False)
    relay = messages.relay_story("钟楼里的第八声", [
        {"name": "小林", "text": "放学后，钟楼敲了第八下"}, {"name": "猫猫", "text": "可学校的钟从来只敲七下"},
        {"name": "阿野", "text": "值班老师拿着手电往楼上走"}, {"name": "老丹", "text": "楼梯尽头站着一个穿旧校服的人"}],
        "那人回过头，手里捧着一本发黄的登记簿。老师认出那是十二年前的自己。钟声停了，楼梯上只剩下一行湿漉漉的脚印，一直通向值班室。")
    return [("daily", "/团 掷", dice), ("daily", "/团 掷 · 天然 20", natural), ("daily", "/团 对决", duel),
            ("moment", "/团 战报", report), ("room", "/团 约团", schedule), ("daily", "/团 接龙", relay)]


def _daily() -> list[tuple[str, str, Any]]:
    day = "10 月 9 日 · 周五"
    mine = messages.daily_roll("小林", day, 17, "顺风", "fair", [["探幽", "未启之门，不妨一推"], ["拾遗", "旁人略过之处，留心记下"]],
                               [["独行", "无灯长廊，莫要孤身"], ["强辩", "骰子已落，不与天争"]])
    best = messages.daily_roll("阿野", day, 20, "天光", "dawn", [["赴险", "难行之路，今日可走"], ["立誓", "出口之言，故事自会记得"]],
                               [["喧宾", "主角今日，或许不是你"], ["夸口", "话说太满，骰子会听见"]],
                               again=True, crit="天光乍破，今日所掷，皆有回响。")
    group = messages.daily_board(day, [{"name": "阿野", "face": 20, "fortune": "天光"}, {"name": "小林", "face": 17, "fortune": "顺风"},
                                       {"name": "猫猫", "face": 9, "fortune": "平潮"}, {"name": "老丹", "face": 3, "fortune": "阴云"}])
    return [("daily", "/团 一掷", mine), ("daily", "/团 一掷 · 天光", best), ("daily", "/团 一掷 全群", group)]


def _pastimes() -> list[tuple[str, str, Any]]:
    """骰运, 金句 and 海龟汤 cards."""
    faces = [2, 3, 4, 2, 5, 3, 4, 3, 2, 4, 3, 5, 4, 3, 4, 5, 3, 4, 2, 4]
    luck = messages.luck_card("小林", "2026 年 10 月", {
        "count": sum(faces), "average": 11.41, "faces": faces, "crits": 4, "fumbles": 2, "high": 56, "tier": "顺风", "tier_key": "fair",
        "sources": [["检定", 41], ["一掷", 9], ["掷骰", 15], ["对决", 2]]}, 180)
    row = lambda name, n, avg, crits, fumbles, tier, key: {"name": name, "count": n, "average": avg, "crits": crits,
                                                           "fumbles": fumbles, "tier": tier, "tier_key": key}
    ranked = [row("阿野", 38, 12.71, 5, 1, "天光", "dawn"), row("小林", 67, 11.41, 4, 2, "顺风", "fair"),
              row("猫猫", 22, 10.32, 1, 1, "平潮", "calm"), row("老丹", 41, 9.05, 2, 4, "阴云", "cloud"),
              row("阿丁", 15, 7.6, 0, 3, "逆风", "gale")]
    board = messages.luck_board("2026 年 10 月", ranked, ranked, 10)
    quote = messages.quote_card("钟楼的指针倒退了一格，值班室的灯跟着暗了一下，又亮起来。", "第七个不思议 · 第二幕 · 倒走的钟",
                                12, 4, "猫猫", "saved")
    quote_board = messages.quote_board([
        {"id": 12, "text": "钟楼的指针倒退了一格，值班室的灯跟着暗了一下，又亮起来。", "source": "第七个不思议 · 第二幕", "marks": 4, "saved_name": "猫猫"},
        {"id": 7, "text": "“契约写在石头上，人会忘，石头不会。”", "source": "灰冠之下 · 第一幕", "marks": 3, "saved_name": "阿野"},
        {"id": 15, "text": "火把在风里斜成一条线，像在替你们指路。", "source": "狩火 · 第三幕", "marks": 2, "saved_name": "小林"}], 23)
    soup = {"title": "半碗汤", "flavor": "清汤", "name": "小林", "count": 9, "guesses": 1,
            "surface": "男人在餐馆点了一碗汤，只喝了一口就哭着结了账，第二天又来点了同一碗汤。为什么？",
            "truth": "男人的母亲生前常给他煮这道汤，去世后他再没喝到过。他在餐馆尝到一模一样的味道，后厨说那是一位老太太留下的配方。"
                     "他第二天又来，只为了再确认一次，那真的是母亲的味道。",
            "keys": [{"text": "汤的味道和母亲做的一样", "by": "猫猫"}, {"text": "母亲已经去世", "by": "阿野"},
                     {"text": "配方来自一位老太太", "by": None}],
            "asked": [{"name": "猫猫", "q": "汤有问题吗", "a": "否"}, {"name": "阿野", "q": "他认识做汤的人吗", "a": "是也不是"},
                      {"name": "老丹", "q": "和他的家人有关吗", "a": "是"}, {"name": "猫猫", "q": "汤的味道很特别吗", "a": "是"},
                      {"name": "阿丁", "q": "餐馆老板是坏人吗", "a": "无关"}]}
    served = messages.soup_board(soup)
    solved = messages.soup_reveal({**soup, "guesses": 2}, "猫猫", "汤是他过世母亲的配方，他是来找回妈妈的味道。", 18)
    return [("daily", "/团 骰运", luck), ("daily", "/团 骰运 榜", board), ("daily", "/团 金句", quote),
            ("daily", "/团 金句 榜", quote_board), ("daily", "/团 海龟汤", served), ("daily", "/团 海龟汤 · 汤底", solved)]


def _moments() -> list[tuple[str, str, Any]]:
    recruit = messages.open_card(WORLD, "放学铃响过很久，钟楼又敲了一下。值班室的登记簿停在十二年前的十月七日。",
                                 4, 2, "管理员", world="seventh-mystery")
    act = messages.act_card(WORLD, 2, "倒走的钟", "指针倒退了一格。从这一刻起，旧校舍里的时间开始往回走。",
                            world="seventh-mystery", total=4, best="陈默（3 次喝彩）",
                            recap={"actions": 9, "checks": 12, "crits": 2, "fumbles": 1})
    result = messages.vote_result("钟楼的门要不要现在打开", "现在打开", [("现在打开", 3), ("等到午夜", 1)],
                                  voters={"现在打开": ["林晓", "陈默", "苏晴"], "等到午夜": ["周野"]})
    ending = messages.ending_card(WORLD, "钟声停在十二点", [
        ("林晓", "她把登记簿还给了值班室，最后一页从此空着。"), ("周野", "他再也没在夜里听见钟声，却总在十二点醒来。")],
        "共 18 轮 · 26 次检定", world="seventh-mystery", report={
            "rounds": 18, "checks": 26, "crits": 3, "fumbles": 1, "best": "林晓（6 次喝彩）",
            "seer": {"name": "猫猫", "right": 7, "total": 9},
            "outcomes": {"critical": 3, "success": 12, "failure": 10, "fumble": 1},
            "acts": [{"number": 1, "title": "放学后", "best": "周野（3 次喝彩）"}, {"number": 2, "title": "倒走的钟", "best": "林晓（2 次喝彩）"},
                     {"number": 3, "title": "十二年前", "best": ""}, {"number": 4, "title": "第八声", "best": "林晓（4 次喝彩）"}]})
    return [("moment", "开团招募", recruit), ("moment", "换幕", act), ("moment", "表决结果", result), ("moment", "终章", ending)]


def _queries() -> list[tuple[str, str, Any]]:
    kit = messages.loadout_card("林晓", [
        {"name": "细节回溯", "kind": "skill", "modifier": 2, "attribute_label": "观察", "cost": {}, "gain": {}, "quantity": None,
         "remaining": 1, "uses": 2, "reset_label": "每幕恢复", "usable": True, "reason": "", "text": "回看一次已发生的场景"},
        {"name": "手电", "kind": "item", "modifier": 1, "attribute_label": "观察", "cost": {}, "gain": {}, "quantity": 1,
         "remaining": None, "uses": None, "reset_label": "", "equipment": {"equipped": True}, "usable": True, "reason": "", "text": ""},
        {"name": "镇静剂", "kind": "item", "modifier": 0, "attribute_label": "", "cost": {}, "gain": {"理智": 1}, "quantity": 0,
         "remaining": None, "uses": None, "reset_label": "", "usable": False, "reason": "已经用完", "text": ""},
    ], [("体力", 4, 5), ("理智", 3, 5)], own=True)
    roster = messages.roster(3, 4, [("小林", "林晓 · 侦探", "就绪"), ("阿野", "周野 · 校工", "暂离"), ("新来的", "", "未选职业")])
    people = messages.people_list([
        {"name": "值班老师", "standing": 1, "tier": "友善", "contributions": {"林晓": 1}},
        {"name": "钟楼里的人", "standing": -2, "tier": "戒备", "contributions": {"周野": -1, "林晓": -1}}])
    person = messages.person_card({
        "name": "值班老师", "kind": "person", "description": "拿着手电的中年老师，总在十一点半巡完最后一层。",
        "motivation": "想早点锁门回家，但不愿意让学生出事。", "standing": 1, "tier": "友善", "contributions": {"林晓": 2, "周野": -1},
        "memories": [{"who": "周野", "text": "半夜翻进值班室，被他撞个正着", "change": -1},
                     {"who": "林晓", "text": "替他把漏锁的窗户关上了", "change": 1},
                     {"who": "林晓", "text": "告诉他钟楼里有人", "change": 1}]})
    record = messages.record_detail(messages.record_line(9, "对抗", "在钟声停止前爬上钟楼", "进行中", "我方 **3** : **2** 对方"),
                                    ["楼梯朽坏，每一步都可能塌。"], [], ["`/团 交锋 #9 做法`　推进这场冲突"],
                                    meter={"kind": "contest", "ours": 3, "theirs": 2, "length": 5, "opponent": "钟楼里的人"})
    return [("sheet", "/团 背包", kit), ("room", "/团 阵容", roster), ("receipt", "/团 人物", people),
            ("receipt", "人物详情", person), ("receipt", "记录详情", record)]


async def message_preview(app: Any, payload: dict[str, Any], username: str) -> dict[str, Any]:
    prefs = load_prefs(app)

    def entry(segment: str, label: str, item: Any) -> dict[str, Any]:
        art = card_art(app, getattr(item, "art", None)) if segment else None
        return {"segment": segment, "label": label, "image": prefs.image(segment),
                "markdown": render(item, MARKDOWN), "plain": render(item, PLAIN),
                "mentions": [name for _, name in getattr(item, "mentions", [])],
                "card": {theme: card_html(item, theme, art) for theme in THEMES} if segment else None}

    return {"prefs": prefs.public(), "markdown_platforms": sorted(MARKDOWN_PLATFORMS),
            "turn": [entry(*sample) for sample in _turn()], "others": [entry(*sample) for sample in _others()]}

