"""Sample messages for the WebUI message-style preview.

The samples go through the same layouts as the game (roll_lite/messages.py),
so what the admin sees is what the group receives.
"""
from __future__ import annotations

from typing import Any

from .. import messages
from ..cards import THEMES, card_html
from ..delivery import card_art, load_prefs
from ..render import MARKDOWN, MARKDOWN_PLATFORMS, PLAIN, render

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
        {"label": "A", "text": "撕下最后一页，带去钟楼对照", "tag": "观察·标准"},
        {"label": "B", "text": "沿着墨迹的方向检查地板", "tag": "敏捷·困难·失败受伤"},
        {"label": "C", "text": "先退回走廊，和同伴汇合", "tag": "休整"},
    ], "mixed", 5, loadout=["细节回溯 观察 +2 · 剩 1 次", "手电 ×1"])
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
        "items": ["手电", "发黄的登记簿"], "traits": []})
    vote = messages.vote_card("钟楼的门要不要现在打开", "门缝里透出微弱的光，门后传来翻书声。", [
        {"key": "A", "label": "现在打开", "description": "趁它还没察觉", "risk": "高"},
        {"key": "B", "label": "等到午夜", "description": "按登记簿上的时间", "cost": "失去一轮"},
    ], 2, 4, 3)
    receipt = messages.play_receipt("林晓", "提出假设「值班员没有离开过钟楼」",
                                    records=[messages.record_line(7, "假设", "值班员没有离开过钟楼", "有支持")])
    status = messages.status_card(WORLD, "进行中", (2, 4, "倒走的钟"), 3, "第 1 日 · 深夜", "旧校舍 · 值班室",
                                  "在午夜前找到钟楼钥匙",
                                  {"name": "林晓", "archetype": "侦探", "resources": [("体力", 4, 5), ("理智", 3, 5)]},
                                  ["第 3 轮：林晓（等待行动）"])
    return [("narration", "开场 · 场景卡", opening), ("choices", "集体表决", vote), ("", "角色卡", card),
            ("", "玩法回执", receipt), ("", "/团 状态", status)]


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

