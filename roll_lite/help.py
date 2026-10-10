"""/团 帮助, read from the top down: sections, then groups, then the commands, then one command.

/团 帮助            the sections, one line each
/团 帮助 玩法       a section: its groups with a line and the commands used most
/团 帮助 调查       a group: every command with its usage
/团 帮助 选         one command: usage, other names, where it works
Numbers work too: /团 帮助 4, /团 帮助 主持 2.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .messages import cmd
from .render import BT, Msg, safe

if TYPE_CHECKING:
    from .commands import Command, Router


@dataclass(frozen=True)
class Group:
    name: str
    desc: str
    verbs: tuple[str, ...] = ()     # these commands, in this order
    topics: tuple[str, ...] = ()    # or every command registered under these topics
    common: tuple[str, ...] = ()    # shown on the section page as the ones to start with


@dataclass(frozen=True)
class Section:
    name: str
    desc: str
    intro: str
    groups: tuple[Group, ...] = ()


SECTIONS = (
    Section("上手", "第一次玩看这里：一局怎么开、怎么行动", ""),
    Section("开团", "开桌、入座建卡、阵容，暂停后的准备大厅", "开一桌、坐下、建好角色，就能等主持人开演。", (
        Group("开桌", "看世界、开桌、入座、建卡、看角色与团桌",
              ("世界", "开启", "世界观", "加入", "职业", "选职业", "角色", "阵容", "状态", "切换"), common=("加入", "选职业")),
        Group("座位", "离座、暂离、回到队列，准备大厅里的准备", ("退出", "暂离", "返回", "准备"), common=("暂离", "准备")),
    )),
    Section("行动", "轮到你时：选项、自由行动、技能物品、全队表决", "轮到你时选一项或自己写行动；技能和物品写在句末带上。", (
        Group("回合", "选项、自由行动、跳过、回顾剧情、全队行动与表决", topics=("行动",), common=("选", "行动")),
        Group("道具", "背包、直接使用、装备与丢弃", topics=("道具",), common=("背包", "使用")),
    )),
    Section("玩法", "线索推理、交涉、对抗、计划、命运与结局", "故事里随时可用的团桌玩法，每条回执都会写下一步怎么做。", (
        Group("调查", "线索、搜查、假设与结论，证词的追问、出示和对照", topics=("调查",), common=("线索", "假设")),
        Group("交涉", "和人物谈条件、签条款，争取态度，同伴目标", topics=("交涉",), common=("交涉", "人物")),
        Group("对抗", "冲突、追逐和辩论，在对抗中出手", topics=("对抗",), common=("冲突", "交锋")),
        Group("计划", "多步计划、项目进度、时间与期限、休整", topics=("计划",), common=("计划", "休整")),
        Group("命运", "机运、神谕、角色转变，提出与走向结局、写尾声", topics=("叙事",), common=("神谕", "结局")),
        Group("记录", "查看所有玩法留下的记录", topics=("玩法",), common=("记录",)),
    )),
    Section("人设", "带着自己的角色去任何世界：导入酒馆角色卡或手写", "人设卡只带文字：性格、经历和说话方式；属性和技能仍按世界的职业。", (
        Group("人设卡", "导入、新建、修改、整理摘要，建卡时带上并融入世界", topics=("人设",), common=("人设 导入", "人设 融入")),
    )),
    Section("日常", "不开团也能玩：一掷、掷骰、对决、约团、接龙、海龟汤", "群聊小玩法，管理员可以在后台逐项开关。", (
        Group("骰子", "今日一掷、自由掷骰、骰子对决、骰运统计",
              ("一掷", "一掷 全群", "掷", "对决", "应战", "骰运"), common=("一掷", "掷")),
        Group("约团", "给出几个时间、大家勾选、定档提醒", ("约团", "约", "定档"), common=("约团",)),
        Group("故事", "故事接龙、喝彩、战报、金句收藏", ("接龙", "喝彩", "战报", "金句"), common=("接龙", "金句")),
        Group("海龟汤", "AI 出题，全群提问推理", ("海龟汤", "问", "猜", "汤底"), common=("海龟汤", "问")),
    )),
    Section("主持", "主持人的指令：节奏存档、回合、叙事设置、座位", "主持人和管理员可用；大多数调整从下一段正文起生效。", (
        Group("节奏", "开演、暂停与准备大厅、完结收桌、存档读档",
              ("开演", "暂停", "恢复", "主持 全员准备", "完结", "关闭", "存档", "存档列表", "读档", "人数"),
              common=("暂停", "恢复")),
        Group("回合控制", "推进、跳过、指定行动者、改选项、重试、回退、限时、要求检定、换幕",
              ("主持 推进", "主持 跳过", "主持 轮到", "主持 选项", "主持 重试", "主持 回退", "主持 限时", "主持 检定",
               "主持 直述", "主持 换幕", "主持 新场景"), common=("主持 推进", "主持 重试")),
        Group("叙事设置", "篇幅、文风、即兴程度、私下指引、审稿、人设开关",
              ("主持 篇幅", "主持 文风", "主持 即兴", "主持 指引", "主持 审稿", "主持 发布", "主持 重写", "主持 人设"),
              common=("主持 文风", "主持 审稿")),
        Group("座位管理", "交棒、请离与放行、暂离与返回、入座开关、退回重建、行动顺序",
              ("主持 交棒", "接棒", "拒绝接棒", "主持 移出", "主持 放行", "主持 暂离", "主持 返回", "主持 入座", "主持 退回", "主持 顺序"),
              common=("主持 交棒", "主持 顺序")),
        Group("事件与调整", "集体事件、表决时限、调整资源与态度",
              ("主持 集体事件", "主持 结束表决", "主持 事件频率", "主持 表决时限", "主持 调整"), common=("主持 集体事件", "主持 调整")),
    )),
)

WHERE = {"": "只能在群里用", "self": "群里或私聊都行；私聊里结果只有你看到", "room": "群里或私聊都行；私聊里发，结果会发到群里"}


def _aliases(router: "Router", command: "Command") -> list[str]:
    return [v for v, c in router.commands.items() if c.handler is command.handler and c.topic == command.topic]


def group_commands(router: "Router", group: Group, is_admin: bool) -> list["Command"]:
    if group.verbs:
        found = [router.commands[v] for v in group.verbs if v in router.commands]
    else:
        found = [c for c in router.commands.values() if c.topic in group.topics]
    seen, result = set(), []
    for c in found:
        if (c.handler, c.topic) in seen or (c.admin and not is_admin):
            continue
        seen.add((c.handler, c.topic))
        result.append(c)
    return result


def _find(name: str) -> tuple[Section | None, Group | None]:
    for section in SECTIONS:
        if section.name == name:
            return section, None
        for group in section.groups:
            if group.name == name:
                return section, group
    return None, None


def render_help(router: "Router", query: str, is_admin: bool) -> Msg:
    words = query.replace("/团", " ").split()
    if not words:
        return index()
    verb = " ".join(words)
    if len(words) > 1 and verb in router.commands and (is_admin or not router.commands[verb].admin):
        return command_page(router, router.commands[verb])        # /团 帮助 主持 推进
    if words[0].isdigit() and 1 <= int(words[0]) <= len(SECTIONS):
        words[0] = SECTIONS[int(words[0]) - 1].name
    section, group = _find(words[0])
    if section is not None and group is None and len(words) > 1 and words[1].isdigit() \
            and 1 <= int(words[1]) <= len(section.groups):
        group = section.groups[int(words[1]) - 1]
    if section is not None:
        if section.name == "上手":
            return quick_start()
        if group is None and len(section.groups) == 1:
            group = section.groups[0]
        if group is None:
            return section_page(router, section, is_admin)
        return group_page(router, section, group, is_admin)
    command = router.commands.get(verb) or router.commands.get(words[0])
    if command is not None and (is_admin or not command.admin):
        return command_page(router, command)
    # A topic name from an older hint (e.g. 基础): show the group holding that topic's first command.
    for section in SECTIONS:
        for group in section.groups:
            if verb in group.topics:
                return group_page(router, section, group, is_admin)
    return index(f"没有找到“{safe(verb)}”。")


def index(note: str = "") -> Msg:
    m = Msg().title("321Roll Lite 帮助", "群聊文字跑团")
    if note:
        m.text(note)
    m.gap().items([f"**{i}. {s.name}**　{s.desc}" + (f"（{'·'.join(g.name for g in s.groups)}）" if len(s.groups) > 1 else "")
                   for i, s in enumerate(SECTIONS, 1)])
    return m.gap().hint(f"发送 {cmd('/团 帮助 序号或名称')} 往下看，例如 {cmd('/团 帮助 2')}、{cmd('/团 帮助 调查')}；"
                        f"也可以直接查一条指令：{cmd('/团 帮助 选')}。第一次玩先看 {cmd('/团 帮助 上手')}")


def quick_start() -> Msg:
    m = Msg().title("帮助 · 上手", "一局大概这样玩").gap()
    m.items([f"管理员发送 {cmd('/团 开启')}，从列表里选一个世界开桌",
             f"在群里发送 {cmd('/团 加入')} 入座",
             f"私聊我发送 {cmd('/团 职业')} 看职业，{cmd('/团 选职业 序号 角色名')} 建卡（群里发也可以）",
             f"主持人发送 {cmd('/团 开演')}；轮到你时选 {cmd('/团 选 A')}，或写 {cmd('/团 行动 你的做法')}",
             f"检定时在句末写 {cmd('[用 名称]')} 带上技能或物品；{cmd('/团 背包')} 看手里有什么",
             f"线索、交涉、对抗、计划等玩法随时可用，回执里会写下一步怎么做"])
    m.gap().caption("还可以")
    m.items([f"私聊里建卡、查角色和背包；在私聊里行动，结果会发到群里",
             f"{cmd('/团 人设 导入')} 带上自己的酒馆角色卡",
             f"{cmd('/团 一掷')} 掷出今天的 d20 和宜忌"])
    return m.gap().hint(f"接着看 {cmd('/团 帮助 开团')}、{cmd('/团 帮助 行动')}；回到目录发送 {cmd('/团 帮助')}")


def section_page(router: "Router", section: Section, is_admin: bool) -> Msg:
    m = Msg().title(f"帮助 · {section.name}", section.desc)
    if section.intro:
        m.text(section.intro)
    rows = []
    for i, group in enumerate(section.groups, 1):
        count = len(group_commands(router, group, is_admin))
        common = "　".join(cmd("/团 " + v) for v in group.common if v in router.commands)
        rows.append(f"**{i}. {group.name}**　{group.desc}　{BT}{count} 条{BT}" + (f"\n　常用 {common}" if common else ""))
    m.gap().items(rows)
    first = section.groups[0].name
    return m.gap().hint(f"发送 {cmd('/团 帮助 ' + first)} 或 {cmd('/团 帮助 ' + section.name + ' 1')} 看这一组的全部指令；"
                        f"回到目录发送 {cmd('/团 帮助')}")


def group_page(router: "Router", section: Section, group: Group, is_admin: bool) -> Msg:
    commands = group_commands(router, group, is_admin)
    title = f"帮助 · {section.name}" + (f" › {group.name}" if len(section.groups) > 1 else "")
    m = Msg().title(title, f"{len(commands)} 条").gap()
    m.text(group.desc if len(section.groups) > 1 else section.intro or group.desc)
    m.gap().items([f"{BT}{c.usage}{BT}　{c.summary}" for c in commands])
    back = f"回到上一级 {cmd('/团 帮助 ' + section.name)}" if len(section.groups) > 1 else f"回到目录 {cmd('/团 帮助')}"
    example = commands[0].verb if commands else "选"
    return m.gap().hint(f"查一条指令的细节：{cmd('/团 帮助 ' + example)}；{back}")


def command_page(router: "Router", command: "Command") -> Msg:
    names = _aliases(router, command)
    m = Msg().title(f"/团 {command.verb}", command.summary).gap()
    m.field("写法", f"{BT}{command.usage}{BT}")
    if len(names) > 1:
        m.field("也可以写", "、".join(f"{BT}/团 {n}{BT}" for n in names if n != command.verb))
    m.field("在哪用", "群里和私聊都行" if not command.group_only and not command.private else WHERE.get(command.private, ""))
    if command.admin:
        m.field("权限", "仅管理员")
    elif command.topic == "主持" or command.verb.startswith("主持 "):
        m.field("权限", "主持人或管理员")
    home = next(((s, g) for s in SECTIONS for g in s.groups if command in group_commands(router, g, True)), None)
    if home is not None:
        s, g = home
        m.field("所在", s.name + (f" › {g.name}" if len(s.groups) > 1 else ""))
        return m.gap().hint(f"同组指令：{cmd('/团 帮助 ' + (g.name if len(s.groups) > 1 else s.name))}；回到目录 {cmd('/团 帮助')}")
    return m.gap().hint(f"回到目录 {cmd('/团 帮助')}")
