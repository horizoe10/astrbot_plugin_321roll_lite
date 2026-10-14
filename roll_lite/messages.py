"""Every chat message style in one place.

Functions take plain data and return render.Msg, so the game code and the
WebUI message preview share exactly the same layouts.  Short refusals and
confirmations stay plain strings.
"""
from __future__ import annotations

import re
from typing import Any

from .render import BT, Msg, dots, safe

DIFFICULTY = {"easy": "简单", "standard": "标准", "hard": "困难", "exceptional": "极难"}
NUMERALS = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二")


def act_label(number: int) -> str:
    return f"第{NUMERALS[number - 1]}幕" if 1 <= number <= len(NUMERALS) else f"第 {number} 幕"


def short_title(title: str) -> str:
    return title.split(" · ")[0]


def subtitle(title: str) -> str:
    return title.split(" · ", 1)[1] if " · " in title else ""


def shelf_list(tables: list[dict[str, Any]], active: str = "") -> Msg:
    note = f"当前桌：《{active}》。先暂存当前桌，再取回旧桌。" if active else "本群桌位空闲，可以取回一桌继续。"
    msg = Msg().title("暂存的故事", f"本群共 {len(tables)} 桌").para(note)
    for i, table in enumerate(tables, 1):
        progress = "尚未开演" if table['lobby'] else f"第 {table['act']} 幕 · 第 {table['round']} 轮"
        msg.heading(f"{i}. {table['name']}").field("世界", table['title']).field("进度", progress)
        msg.field("阵容", f"{table['players']} 人").text(f"取回：/团 取回 {i}").gap()
    if not tables:
        msg.para("还没有暂存的团桌。想换个世界、以后再回来时，由主持人发送 /团 暂存 名称。")
    msg.hint("主持人或管理员发送 /团 暂存；原主持人或管理员发送 /团 取回 序号。",
             note="角色、背包、剧情和存档随原桌保留。取回后准备好再开演。", cmds=[("暂存当前桌", "/团 暂存"), ("开新世界", "/团 开启")])
    return msg.as_segment('room').with_data({'kind': 'shelf', 'tables': tables, 'active': active, 'mode': 'list'})


def shelf_result(table: dict[str, Any], *, retrieved: bool) -> Msg:
    title = "故事已取回" if retrieved else "故事已暂存"
    note = ("回到筹备阶段，大家入座、建卡后再开演。" if table['lobby'] else "准备大厅已打开，大家准备好后由主持人开演。") if retrieved else "本群位置已腾出，可以开另一个世界；以后再取回这一桌。"
    cmds = ([("查看阵容", "/团 阵容"), ("开演", "/团 开演")] if table['lobby'] else [("准备", "/团 准备"), ("开演继续", "/团 开演")]) if retrieved else [("开新世界", "/团 开启"), ("取回旧桌", "/团 暂存列表")]
    msg = Msg().title(title).heading(table['name']).field("世界", table['title'])
    msg.field("进度", "尚未开演" if table['lobby'] else f"第 {table['act']} 幕 · 第 {table['round']} 轮")
    msg.para(note).hint("；".join(f"{label}：{cmd}" for label, cmd in cmds), note="角色、背包、剧情与手动存档均保留。", cmds=cmds)
    return msg.as_segment('room').with_data({'kind': 'shelf', 'tables': [table], 'mode': 'retrieve' if retrieved else 'save', 'note': note, 'cmds': cmds})


def check_tag(rules: dict[str, Any], check: dict[str, Any]) -> str:
    if check.get("kind") == "check":
        attr = rules["attributes"].get(check["attribute_ref"], check["attribute_ref"])
        tag = f"{attr}·{DIFFICULTY.get(check['difficulty'], check['difficulty'])}"
        return tag + ("·失败受伤" if check.get("failure_cost") == "harm" else "")
    return "休整" if check.get("kind") == "recover" else ""


def cmd(text: str) -> str:
    return BT + text + BT


def first_sentence(text: str, limit: int = 60) -> str:
    """An NPC's description up to its first full stop, so the line ends cleanly."""
    text = " ".join(str(text).split())
    match = re.search(r"[。！？!?；;…]+", text)
    head = text[:match.end()] if match else text
    return head if len(head) <= limit else head[:limit - 1] + "…"


# ---------------------------------------------------------------- lobby
def world_list(entries: list[dict[str, Any]], picking: bool = False) -> Msg:
    """The enabled worlds, numbered for /团 开启; picking=True when /团 开启 came without a world."""
    m = Msg().title("选一个世界开团" if picking else "可开的世界").gap()
    for i, e in enumerate(entries, 1):
        m.text(f"**{i}. {safe(short_title(e['title']))}**　{safe(subtitle(e['title']))}")
        m.text(f"{BT}{e['label']}{BT} {e['kind']}　{e['players']} 人").gap()
    if picking:
        return m.hint(f"发送 {cmd('/团 开启 序号')} 开一桌，例如 {cmd('/团 开启 1')}；也可以写世界名，如 {cmd('/团 开启 ' + short_title(entries[0]['title']))}",
                      note="核心版只预设第一幕，之后由 AI 即兴续写；更多世界在后台“世界 → 世界市场”安装")
    return m.hint(f"管理员发送 {cmd('/团 开启 序号')} 开一桌；更多世界可以在后台“世界 → 世界市场”安装")


def open_card(title: str, hook: str, seat_cap: int, min_players: int, host: str, world: str = "", note: str = "") -> Msg:
    m = Msg().banner(short_title(title))
    m.as_segment("moment").with_data({"kind": "open", "title": short_title(title), "sub": subtitle(title), "hook": hook,
                                      "cap": seat_cap, "min": min_players, "host": host, "note": note})
    if world:
        m.with_art(world, "cover", "开团招募")
    if subtitle(title):
        m.caption(subtitle(title))
    m.para(hook)
    if note:
        m.caption(note)
    m.field("席位", f"0/{seat_cap}　最少 {min_players} 人可开演").field("主持", host).gap()
    return m.hint(f"{cmd('/团 加入')} 入座　{cmd('/团 世界观')} 读设定；完整步骤见下一条入座指南")


def table_guide(title: str, min_players: int, seat_cap: int) -> Msg:
    """Sent to the whole group right after a table opens: how to get seated, then what a turn asks of you."""
    # Descriptions name commands as {/团 …}: backticked in chat text, plain inside the image card.
    steps = [("入座", "/团 加入", "想上桌的每个人都在群里发一次"),
             ("建卡", "/团 建卡", "私聊我选快选、定制、精雕，或 {/团 建卡 AI 想要的角色}"),
             ("读设定", "/团 世界观", "{/团 阵容} 看谁已入座、谁还没建卡"),
             ("等开演", "", f"{min_players} 人建好卡就能开演，最多 {seat_cap} 人")]
    after = [("dice", "轮到你", "/团 A", "我会点你的名；想自己写就发 {/团 行动 你的做法}"),
             ("skill", "用技能物品", "[用 名称]", "写在指令末尾，加值计入检定；{/团 背包} 看手里有什么"),
             ("hand", "不轮到你", "/团 说 台词", "也能插话、援手、竞猜，开演时细说")]
    chat = lambda desc: re.sub(r"\{(/团 [^}]+)\}", lambda x: cmd(x.group(1)), desc)
    card = lambda desc: re.sub(r"\{(/团 [^}]+)\}", r"\1", desc)
    m = Msg().title("📜 入座指南", f"《{short_title(title)}》{min_players} 人起开演 · 最多 {seat_cap} 人").gap()
    for i, (label, command, desc) in enumerate(steps, 1):
        m.text(f"**{i}. {label}**　" + (cmd(command) + "　" if command else "") + chat(desc))
    m.gap().caption("开演后")
    m.items([f"**{name}**　{cmd(command)}　{chat(desc)}" for _, name, command, desc in after])
    m.gap().hint(f"第一次玩发送 {cmd('/团 帮助 上手')}，一页看懂一局怎么玩")
    return m.as_segment("receipt").with_data({"kind": "table_guide", "title": short_title(title), "min": min_players, "cap": seat_cap,
                                              "steps": [[a, b, card(c)] for a, b, c in steps],
                                              "after": [[i, n, c, card(d)] for i, n, c, d in after]})


def worldview(title: str, worldview: str, entries: list[tuple[str, str, str]]) -> Msg:
    m = Msg().banner(short_title(title)).para(worldview)
    if entries:
        m.title("公开条目").items([f"**{safe(name)}**〔{kind}〕{safe(summary)}" for name, kind, summary in entries])
    return m


def archetype_list(title: str, archetypes: list[dict[str, Any]]) -> Msg:
    m = Msg().title("职业", short_title(title))
    for i, a in enumerate(archetypes, 1):
        m.gap().text(f"**{i}. {safe(a['name'])}**　{safe(a['text'])}")
        m.text(BT + "　".join(f"{n} {v}" for n, v in a["attributes"]) + BT)
        for name, text in a["skills"]:
            m.text(f"· {safe(name)}：{safe(text)}")
    return m.gap().hint(f"{cmd('/团 选职业 序号 角色名')}，例如 {cmd('/团 选职业 1 林晓')}")


def character_card(c: dict[str, Any]) -> Msg:
    m = Msg().title(c["name"], f"{c['archetype']}　{c['archetype_text']}".strip() if c.get("archetype") else "")
    m.as_segment("sheet").with_data(c)
    if c.get("user_name") and c["user_name"] != c["name"]:
        m.text(f"玩家 {safe(c['user_name'])}" + ("　· 暂离" if c.get("away") else ""))
    persona = c.get("persona")
    if persona:
        m.field("人设", f"「{safe(persona['name'])}」" + (f"　{safe(persona['intro'])}" if persona.get("intro") else ""))
    if not c.get("archetype"):
        return m.gap().hint(f"还没选职业，发送 {cmd('/团 职业')} 查看")
    m.gap().text("　".join(f"{n} **{v}**" if mod > 0 else f"{n} {v}" for n, v, mod in c["attributes"]))
    m.gap()
    for name, current, maximum in c["resources"]:
        m.meter(name, current, maximum)
    if c.get("skills"):
        m.gap().items([f"**{safe(n)}**　{safe(t)}" + (f"（剩 {u} 次）" if u is not None else "") for n, t, u in c["skills"]])
    if c.get("items"):
        m.gap().field("物品", safe("、".join(c["items"])))
    if c.get("traits"):
        m.field("经历", safe("、".join(c["traits"])))
    p = c.get("profile") or {}
    if p.get("origin") or p.get("look") or p.get("answers") or p.get("relation") or p.get("details") or p.get("trait"):
        m.gap()
        if p.get("origin"):
            m.field("出身", safe(p["origin"]["name"]))
        if p.get("look"):
            m.field("外貌与性格", safe(p["look"]))
        for name, value in p.get("details") or []:
            m.field(safe(name), safe(value))
        if p.get("trait"):
            m.field("特质", trait_line(p["trait"]))
        for q, a in p.get("answers") or []:
            m.field(safe(q), safe(a))
        if p.get("relation"):
            r = p["relation"]
            m.field("同伴羁绊" if r["kind"] == "teammate" else "旧识", safe(r["name"]) + (f"：{safe(r['text'])}" if r.get("text") else ""))
    return m


# ---------------------------------------------------------------- building a character
def trait_line(t: dict[str, Any]) -> str:
    """'**临危不乱**　越危险越冷静（利 困难及以上的胆量检定 +1；弊 没人援手时的检定 −1）'."""
    sides = "；".join(x for x in (f"利 {t['up_text']}" if t.get("up_text") else "", f"弊 {t['down_text']}" if t.get("down_text") else "") if x)
    return f"**{safe(t['name'])}**" + (f"　{safe(t['text'])}" if t.get("text") else "") + (f"（{sides}）" if sides else "")


def build_modes(v: dict[str, Any]) -> Msg:
    """/团 建卡 with no draft: the three depths and the AI draft, with what each lets you change."""
    m = Msg().title("建卡", f"{safe(v['world'])}　{v['facts']}").as_segment("build").with_data(v).gap()
    rows = []
    for i, r in enumerate(v["rows"], 1):
        head = f"**{i}. {r['label']}**　{r['desc']}　· {r['steps']} · 约 {r['time']}"
        rows.append(head + (f"　（暂不可用：{r['closed']}）" if r["closed"] else f"　{cmd(r['cmd'])}"))
    ai = v["ai"]
    if ai["open"]:
        rows.append(f"**AI 建卡**　说一句想要的角色，AI 按当前模式起草，你再改（可用自然语言改 5 次）　"
                    f"{cmd(ai.get('cmd') or '/团 建卡 AI 嘴硬心软、会修机器的老兵')}　今天还能用 {max(0, ai['left'])} 次")
    m.items(rows)
    where = "直接回复模式名就能开始，之后每一步也直接回复；" if v.get("private") else "建议私聊我来建卡，免得刷屏；"
    return m.gap().hint(f"{where}三种模式点数预算相同，模式越深越自由，不会更强。开演前随时可以重建")


def build_draft(v: dict[str, Any]) -> Msg:
    """A build draft: the character so far, then the step to answer and how.

    In a private chat the player just replies ('1', '术士', '确认'); in the group the full /团 建卡 command is shown.
    """
    private = bool(v.get("private"))

    def say(words: str) -> str:
        return words if private else "/团 建卡 " + words

    head = v.get("head") or f"{v['mode_label']}建卡"
    m = Msg().title(head, f"第 {v['position']}/{v['total']} 步" + (f" · {v['question']['label']}" if v.get("question") else " · 可以确认了"))
    m.as_segment("build").with_data(v)
    m.gap().text("　".join(f"{'✓' if s['state'] == 'done' else '▸' if s['state'] == 'now' else '·'}{s['label']}" for s in v["steps"]))
    ai = v.get("ai") or {}
    if ai.get("understood"):
        m.gap().field("AI 的理解", safe(ai["understood"]))
    for line in ai.get("changes") or []:
        m.field("改动", safe(line))
    for note in [*(ai.get("notes") or []), *v.get("notes", [])]:
        m.field("注意", safe(note))
    if ai.get("understood") and ai.get("left") is not None:
        m.text(f"AI 修改还剩 {ai['left']} 次：{cmd(say('改 你的要求'))}；自己动手改不限次数")
    m.gap()
    who = (safe(v["archetype"]) if v["archetype"] else "未选职业") + (f"「{safe(v['name'])}」" if v["name"] else "")
    m.field("角色", who)
    if v["attributes"]:
        m.field("属性", "　".join(f"{a['name']} {a['value']}" + (f"({a['delta']:+d})" if a["delta"] else "") for a in v["attributes"])
                + f"　已挪 {v['moved']}/{v['move_limit']}")
    if v["skills"]:
        m.field("技能", "、".join(safe(s["name"]) + ("（换入）" if s["new"] else "") for s in v["skills"]))
    for label, key in (("出身", "origin"), ("装备", "kit"), ("外貌与性格", "look"), ("开局关系", "relation")):
        if v.get(key):
            m.field(label, safe(v[key]))
    for d in v.get("details") or []:
        m.field(safe(d["name"]), safe(d["value"]))
    if v.get("trait"):
        m.field("特质", trait_line(v["trait"]))
    if v["items"] and not v.get("kit"):
        m.field("多带", safe("、".join(v["items"])))
    for a in v["answers"]:
        m.field(safe(a["q"]), safe(a["a"]))
    q = v.get("question")
    if q:
        answer = q.get("answer") or str(q["example"]).removeprefix("/团 建卡 ")
        m.gap().caption(f"这一步：{q['title']}").text(q["text"])
        if q["options"]:
            m.items([f"**{i}. {safe(o['name'])}**" + ("　已有" if o.get("on") else "") + (f"　{safe(o['note'])}" if o.get("note") else "")
                     + (f"　{BT}{o['meta']}{BT}" if o.get("meta") else "") for i, o in enumerate(q["options"], 1)])
        cmds = [("回答", say(answer))] + ([("跳过", say("跳过"))] if q["skip"] else []) + [("返回", say("返回"))]
        if v["ready"]:
            cmds.append(("直接确认", say("确认")))
        how = (f"直接回复 {cmd(answer)}" + ("，序号或名字都行" if q["options"] else "")) if private else f"回复 {cmd(say(answer))}"
        m.gap().hint(how + ("，不想填就发 " + cmd(say("跳过")) if q["skip"] else "")
                     + (f"；也可以直接 {cmd(say('确认'))}，没填的按默认" if v["ready"] else ""),
                     note="私聊里不用加 /团 建卡，像聊天一样回复就行。" if private else "", cmds=cmds)
    else:
        cmds = [("确认入座", say("确认")), ("返回上一步", say("返回"))]
        if ai.get("left") is not None and ai.get("understood"):
            cmds.insert(1, (f"让 AI 改（剩 {ai['left']} 次）", say("改 你的要求")))
        attrs = v.get("attributes") or []
        edits = ([cmd(say(f"属性 {attrs[0]['name']}-1 {attrs[-1]['name']}+1"))] if len(attrs) > 1 and v.get("move_limit") else [])
        edits.append(cmd(say("名字 新名字")))
        m.gap().hint(f"都填好了：{'回复' if private else '发送'} {cmd(say('确认'))} 入座；也可以用 " + "、".join(edits) + " 再改某一项",
                     note="自己动手改不限次数。", cmds=cmds)
    return m


def roster(seated: int, cap: int, rows: list[tuple[str, str, str]]) -> Msg:
    m = Msg().title("阵容", f"{seated}/{cap} 人　{dots(seated, cap)}").gap()
    m.as_segment("room").with_data({"kind": "roster", "seated": seated, "cap": cap, "rows": [list(r) for r in rows]})
    return m.items([f"**{safe(user)}**　{safe(role)}　{state}" for user, role, state in rows] or ["还没有人入座"])


def joined(user: str, seated: int, cap: int) -> Msg:
    m = Msg().title(f"{safe(user)} 已入座", f"{seated}/{cap} 人　{dots(seated, cap)}")
    return m.gap().hint(f"下一步建卡：私聊我发送 {cmd('/团 建卡')}，选快选（挑个职业就走）、定制或精雕，"
                        f"也可以 {cmd('/团 建卡 AI 你想要的角色')} 让 AI 起草；之后每一步在私聊里直接回复序号或名字就行。"
                        f"有人设卡的话，角色名写人设的名字就会带上它（{cmd('/团 人设')} 查看）")


def next_steps_after_card(state: str, regroup_open: bool = False) -> str:
    if state == "lobby":
        return f"角色已就绪。等主持人发送 {cmd('/团 开演')}；随时可以发送 {cmd('/团 背包')} 查看技能和物品。".replace(BT, "")
    if state == "paused":
        step = "发送 /团 准备" if regroup_open else "等主持人发送 /团 恢复 打开准备大厅后发送 /团 准备"
        return f"角色已就绪。故事正在暂停：{step}，主持人开演后你会排进行动顺序末尾，AI 会把你写进故事。"
    return f"角色已就绪，已排进行动顺序。轮到你时会在群里@你；{cmd('/团 背包')} 查看技能和物品。".replace(BT, "")


def regroup_card(title: str, rows: list[tuple[str, str, str, bool]], left: list[str], minutes: int, all_ready: bool) -> Msg:
    """The preparation lobby after /团 恢复: (name, archetype, state, newcomer) per seated player."""
    ready = sum(1 for r in rows if r[2] == "已准备")
    players = sum(1 for r in rows if r[2] != "未建卡")
    m = Msg().title(safe(title), f"{ready}/{players} 人已准备").gap()
    m.items([f"**{safe(name)}**" + (f"　{safe(role)}" if role else "") + f"　{BT}{state}{BT}" + ("　新加入" if new else "")
             for name, role, state, new in rows]
            or ["还没有人在座"])
    if any(state == "未建卡" for _, _, state, _ in rows):
        m.text(f"未建卡的人私聊我发送 {cmd('/团 建卡')}（中途加入可用快选、定制或 AI 建卡），建好就能准备")
    if left:
        m.text("本次离开：" + "、".join(safe(n) for n in left))
    m.gap()
    if all_ready:
        return m.hint(f"全员已准备。主持人发送 {cmd('/团 开演')} 继续故事" + ("，AI 会先把人员变动写进故事" if left or any(r[3] for r in rows) else ""))
    note = f"{minutes} 分钟后，没准备的玩家自动准备。" if minutes else ""
    return m.hint(f"准备好后发送 {cmd('/团 准备')}；这段时间可以 {cmd('/团 加入')}、建卡或 {cmd('/团 退出')}。"
                  f"{note}主持人可以发送 {cmd('/团 主持 全员准备')}")


# ---------------------------------------------------------------- story
def act_card(world_title: str, act_number: int, act_title: str, lead: str, *, world: str = "", art: str = "",
             total: int = 0, best: str = "", recap: dict[str, Any] | None = None) -> Msg:
    """art: the banner image key, 'cover' at the opening (the scene card after it shows act:1) and act:N later.
    recap (actions, checks, crits, fumbles of the act just closed) only feeds the image card."""
    m = Msg().banner(short_title(world_title))
    m.as_segment("moment").with_data({"kind": "act", "title": short_title(world_title), "number": act_number,
                                      "act_title": act_title, "lead": lead, "total": total, "best": best, "recap": recap})
    if world:
        m.with_art(world, art or f"act:{act_number}", short_title(world_title))
    if subtitle(world_title):
        m.caption(subtitle(world_title))
    if act_title:
        m.gap().heading(f"{act_label(act_number)} · {act_title}")
        if lead:
            m.quote(lead)
    if best:
        m.gap().field("上一幕最佳", best)
    return m


def scene_card(title: str, description: str, goal: str, npcs: list[tuple[str, str]]) -> Msg:
    m = Msg().heading(title).para(description).as_segment("narration")
    m.field("目标", goal)
    if npcs:
        m.gap().people("登场", [(n, first_sentence(d)) for n, d in npcs])
    return m


def action_status(actor: str, archetype: str, round_number: int, action: str, receipt: dict[str, Any],
                  meters: list[tuple[str, int, int, int | None]], *, announce: str = "",
                  wallet: tuple[str, int] | None = None) -> Msg:
    m = Msg()
    if announce:
        m.text(announce).gap()
    m.title(actor, f"{archetype}　｜　第 {round_number} 轮" if archetype else f"第 {round_number} 轮").quote(action)
    if receipt.get("kind") == "check":
        m.gap().check(attribute=receipt["attribute"], difficulty=DIFFICULTY.get(receipt["difficulty"], receipt["difficulty"]),
                      dc=receipt["dc"], face=receipt["face"], modifier=receipt["modifier"], total=receipt["total"],
                      outcome=receipt["outcome"])
    elif receipt.get("kind") == "recover":
        m.gap().text("**安全休整**")
    if receipt.get("prepared"):
        m.field("准备", "、".join(f"{safe(p['name'])}" + (f" {p['modifier']:+d}" if p["modifier"] else "") for p in receipt["prepared"]))
    if receipt.get("aid"):
        aid = receipt["aid"]
        shared_cost = "、".join(f"{k} {v:+d}" for k, v in (aid.get("changes") or {}).items())
        m.field("援手", f"{safe(aid['name'])} {aid['bonus']:+d}" + ("　羁绊加成" if aid.get("bond") else "")
                + (f"　（一起承担：{shared_cost}）" if shared_cost else ""))
    if receipt.get("flashback"):
        flash = receipt["flashback"]
        m.field("闪回", f"{flash['bonus']:+d}　{safe(flash['text'])}")
    elif receipt.get('flashback_notice'):
        m.field('闪回', safe(receipt['flashback_notice']))
    if receipt.get("trait"):
        m.field("特质", f"{safe(receipt['trait']['name'])} {receipt['trait']['bonus']:+d}")
    if receipt.get("all_in"):
        m.field("孤注", "成功，按大成功来写" if receipt.get("success") else "失败，后果加重")
    if receipt.get("aid_unused"):
        m.field("援手未用", f"这次没有检定，{safe(receipt['aid_unused'])} 的援手没用上，本幕还能再出手")
    if receipt.get("all_in_unused"):
        m.field("孤注未用", "这次没有检定，孤注没用上，本幕还能再用")
    if meters:
        m.gap()
        for name, current, maximum, delta in meters:
            m.meter(name, current, maximum, delta)
    if receipt.get("exhausted"):
        m.text("**" + "、".join(receipt["exhausted"]) + "已耗尽**")
    if wallet:
        m.field("钱包", f"{wallet[1]} {safe(wallet[0])}")
    guessed = receipt.get("wager")
    if guessed:
        m.gap().field("竞猜", wager_line(guessed))
        m.with_data({"kind": "action", "wager": guessed})
    return m.as_segment("status")


def wager_line(guessed: dict[str, Any]) -> str:
    if "void" in guessed:
        return "这次没有掷骰，竞猜作废"
    right, wrong = guessed.get("right") or [], guessed.get("wrong") or []
    return "　".join(p for p in ("猜对 " + "、".join(safe(n) for n in right) if right else "没人猜对",
                                "猜错 " + "、".join(safe(n) for n in wrong) if wrong else "") if p)


def narration(text: str, scene_title: str = "", act_heading: str = "") -> Msg:
    m = Msg()
    if act_heading:
        m.heading(act_heading)
    if scene_title:
        m.caption(scene_title)
    return m.para(text).as_segment("narration")


def turn_prompt(actor: str, user_name: str, user_id: str, round_number: int, choices: list[dict[str, str]],
                mode: str, minutes: int | None, loadout: list[str] | None = None, upcoming: str = "",
                tips: bool = False, others: dict[str, list[dict[str, Any]]] | None = None,
                pace: tuple[str, str] | None = None) -> Msg:
    meta = f"第 {round_number} 轮" + (f"　限时 {minutes} 分钟" if minutes else "") + (f"　下一位 {safe(upcoming)}" if upcoming else "")
    m = Msg().mention(user_id, user_name).title(f"▸ 轮到 {actor}", meta)
    if choices and mode != "dialogue_only":
        m.gap().choices(choices)
        if any(c.get("closing") for c in choices):
            m.text("🏁 标着“收束”的一项会把故事引向结局：选它之后，全桌表决要不要收尾。")
    if pace:
        m.gap().field("节奏", f"**{safe(pace[0])}**　{safe(pace[1])}")
    if loadout:
        m.gap().field("可准备", "　".join(loadout[:5]) + ("　…" if len(loadout) > 5 else ""))
    if tips:    # the player's first turn at this table
        lines = (["选一项：" + cmd("/团 A") + "（或 " + cmd("/团 选 A") + "），后面可以补一句演绎"] if choices and mode != "dialogue_only" else []) \
            + (["自己写：" + cmd("/团 行动 你的做法") + "，AI 会判断要不要检定"] if mode != "choice_only" else []) \
            + ["带上技能或物品：句末加 " + cmd("[用 名称]") + "，" + cmd("/团 背包") + " 看你有什么",
               "押上这次检定：选项后加“孤注”；想起有用的准备：" + cmd("/团 闪回 回忆") + "，成立后相关检定 +2"]
        m.gap().caption("新手速查").items(lines)
    hints = []
    cmds = []
    if choices and mode != "dialogue_only":
        hints.append(cmd("/团 选 A"))
        cmds.append(("选择", "/团 选 A"))
    if mode != "choice_only":
        hints.append(cmd("/团 行动 你的做法"))
        cmds.append(("自由行动", "/团 行动 描述"))
    cmds.append(("跳过", "/团 跳过"))
    notes = (["在指令末尾加 " + cmd("[用 名称]") + " 带上技能或物品，加值计入检定"] if loadout else []) + \
        ([f"{minutes} 分钟内未行动将自动选择风险最低的一项"] if minutes else [])
    m.gap().hint("回复 " + "　或　".join(hints) + ("，句末加 " + cmd("[用 名称]") + " 带上技能或物品" if loadout else "")
                 + ("，超时将自动选择风险最低的一项" if minutes else ""), note="；".join(notes) + ("。" if notes else ""), cmds=cmds)
    _others_fields(m, others)
    return m.as_segment("choices")


OTHERS_LABELS = {"crew": "同桌队友", "crowd": "围观群友"}


def others_guide(actor: str, *, crew: bool = False, aid: str = "", seats: int = 0, heckles: bool = True,
                 bets: bool = True) -> dict[str, list[dict[str, Any]]]:
    """What the rest of the group can do while actor's turn is open.

    crew rows need another seated character; aid names whoever already helps this turn; seats counts free
    seats the gallery may still take (0 when full or locked); heckles and bets say whether those are open now.
    """
    rows: dict[str, list[dict[str, Any]]] = {"crew": [], "crowd": []}
    if crew:
        rows["crew"] += [
            {"icon": "hand", "name": "援手", "cmd": "" if aid else "/团 援手 怎么帮",
             "desc": f"{aid} 已在帮 {actor}，每轮只能一人出手" if aid else f"帮 {actor} 这次检定 +2，失败一起扛，每幕一次",
             "short": f"{aid} 已在帮忙" if aid else f"帮{actor}检定 +2"},
            {"icon": "quill", "name": "台词", "cmd": "/团 说 台词", "desc": "当众插一句，不占回合，下一段正文有人接话",
             "short": "插一句"},
            {"icon": "letter", "name": "密信", "cmd": "/团 密信 角色名 内容", "private": True,
             "desc": "私聊 bot 给同伴递纸条，群里只看到递了纸条", "short": "递纸条"}]
    if heckles:
        rows["crowd"].append({"icon": "heart", "name": "起哄", "cmd": "/团 起哄 点子",
                              "desc": "给故事出个点子，附和最多的一条写进正文", "short": "出点子"})
    if bets:
        rows["crowd"].append({"icon": "dice", "name": "竞猜", "cmd": "/团 押 成",
                              "desc": f"押 {actor} 这一掷是成是败，押失败就写“败”；同桌也能押", "short": "或 败，猜这一掷"})
    if seats:
        rows["crowd"].append({"icon": "eye", "name": "入座", "cmd": "/团 加入",
                              "desc": f"还空 {seats} 个座位，建好卡排到行动顺序末尾", "short": f"还空 {seats} 席"})
    return rows


def _others_fields(m: Msg, others: dict[str, list[dict[str, Any]]] | None) -> None:
    """Two short lines for text; the image card lays out the same rows from data."""
    if not others or not any(others.get(k) for k in OTHERS_LABELS):
        return
    m.gap()
    for key, label in OTHERS_LABELS.items():
        if others.get(key):
            m.field(label, "　".join(("私聊 " if r.get("private") else "") + (cmd(r["cmd"]) + " " if r["cmd"] else "")
                                    + r["short"] for r in others[key]))
    m.with_data({**(m.data or {}), "others": others})


def host_line(text: str) -> Msg:
    return Msg().caption("主持人").para(text)


PLAYS_INTRO = (("说", "/团 说 台词", "当众说一句，不占回合，下一段正文里有人接话"),
               ("援手", "/团 援手 怎么帮", "帮正在行动的同伴：检定 +2，失败一起扛，每幕一次"),
               ("孤注", "/团 选 A 孤注", "押上这次检定：成功按大成功写，失败必定受伤，每幕一次"),
               ("闪回", "/团 闪回 回忆", "先审查本人准备，成立后花 1 点资源，相关检定 +2，每幕一次"),
               ("羁绊", "/团 羁绊 角色名 关系", "对方同意后生效：正文记得你们的关系，互相援手 +3"),
               ("竞猜", "/团 押 成", "押别人这一掷是成是败，掷骰时揭晓，终局评出预言家"),
               ("起哄", "/团 起哄 点子", "没入座也能玩，附和最多的一条写进正文"),
               ("密信", "私聊 /团 密信 角色名 内容", "给同伴递纸条，群里只看到递了纸条，终章公开"),
               ("X 卡", "私聊 /团 X", "有内容让你不舒服时匿名举卡，故事立刻转开"))


def plays_intro() -> Msg:
    """Sent once when a story starts, while the opening is being written."""
    m = Msg().title("🎲 不轮到你时也能玩").gap().items([f"**{name}**　{cmd(command)}　{text}" for name, command, text in PLAYS_INTRO])
    m.hint(f"全部写法：{cmd('/团 帮助 互动')}")
    return m.as_segment("banter").with_data({"kind": "plays_intro", "rows": [list(r) for r in PLAYS_INTRO]})


def all_in_guide(left: str = "") -> Msg:
    m = Msg().title("孤注一掷", "押上这次检定").gap().text(
        "孤注不是单独的指令，写在选项或行动后面：成功按大成功的效果来写，失败必定受伤。只对要掷骰的行动有效，每人每幕一次。")
    if left:
        m.text(left)
    return m.gap().hint(f"写法：{cmd('/团 选 A 孤注')}，或 {cmd('/团 行动 你的做法 [孤注]')}")


# ---------------------------------------------------------------- group-chat plays
def line_said(actor: str, text: str, reply_to: str = "") -> Msg:
    m = Msg().text(f"💬 **{safe(actor)}**：“{safe(text)}”").hint("下一段正文里，在场的人会对这句话作出反应")
    return m.as_segment("banter").with_data({"kind": "line", "actor": actor, "text": text, "reply_to": reply_to})


def heckle_board(rows: list[tuple[int, str, int, str]], left: int, cap: int = 2) -> Msg:
    """rows are (index, idea, backers including the author, author name)."""
    m = Msg().title("📣 起哄板", "下一段正文采纳附和最多的一条" if left else "这一幕的起哄名额已经用完")
    if rows:
        m.gap().items([f"**{i}.** {safe(text)}　＋{votes}" for i, text, votes, *_ in rows])
    else:
        m.gap().text("还没有人起哄。")
    if left:
        m.hint(f"发送 {cmd('/团 起哄 点子')} 提一个，{cmd('/团 起哄 +1 序号')} 附和；没入座也能玩",
               note=f"每人每段各一次，这一幕还能采纳 {left} 条。")
    else:
        m.hint("换幕后名额恢复，再来起哄。")
    return m.as_segment("banter").with_data({"kind": "heckles", "left": left, "cap": cap, "rows": [
        {"index": r[0], "text": r[1], "votes": r[2], "by": r[3] if len(r) > 3 else ""} for r in rows]})


def heckle_adopted(text: str, votes: int) -> Msg:
    m = Msg().text(f"🎭 本段采纳了围观群众的起哄：“{safe(text)}”（{votes} 人附和）")
    return m.as_segment("banter").with_data({"kind": "heckle_adopted", "text": text, "votes": votes})


def aid_offered(helper: str, target: str, text: str, bonus: int, bond: str = "") -> Msg:
    m = Msg().title(f"🤝 {safe(helper)} 出手相助", f"帮 {safe(target)}")
    if text:
        m.quote(text)
    if bond:
        m.field("羁绊", f"{safe(bond)}（援手 +{bonus}）")
    m.hint(f"{safe(target)} 这次行动若要检定，修正 +{bonus}；失败时 {safe(helper)} 一起承担后果。每人每幕一次")
    return m.as_segment("banter").with_data({"kind": "aid", "helper": helper, "target": target, "text": text, "bonus": bonus,
                                              "bond": bond})


def letter_passed(sender: str, target: str, *, delivered: bool = True, user_id: str = "", user_name: str = "") -> Msg:
    """The group's view of a note; when it could not be forwarded, the receiver is told where to read it."""
    m = Msg()
    if not delivered and user_id:
        m.mention(user_id, user_name or target)
    m.text(f"📜 {safe(sender)} 悄悄给 {safe(target)} 递了一张纸条。")
    if not delivered:
        m.hint(f"{safe(target)} 私聊我发送 {cmd('/团 密信')} 就能看到")
    return m.as_segment("ties").with_data({"kind": "letter_passed", "sender": sender, "target": target, "delivered": delivered})


def letter_received(sender: str, target: str, text: str) -> Msg:
    m = Msg().title(f"📜 {safe(sender)} 递给 {safe(target)} 的纸条").gap().quote(text).hint(
        f"回信：{cmd('/团 密信 ' + sender + ' 内容')}；所有纸条会在终章公开")
    return m.as_segment("ties").with_data({"kind": "letter", "sender": sender, "target": target, "text": text})


def letter_sent(target: str, delivered: bool) -> Msg:
    detail = "已经私聊转给对方。" if delivered else f"对方还没私聊过我，TA 私聊发送 {cmd('/团 密信')} 就能看到。"
    m = Msg().title(f"纸条已递给 {safe(target)}").gap().text(detail).hint("群里只会看到你递了纸条；所有纸条会在终章公开")
    return m.as_segment("ties").with_data({"kind": "letter_sent", "target": target, "delivered": delivered})


def letter_inbox(actor: str, rows: list[tuple[str, str, str]]) -> Msg:
    m = Msg().title(f"{safe(actor)} 的纸条")
    m.as_segment("ties").with_data({"kind": "letters", "actor": actor,
                                       "rows": [{"way": way, "who": who, "text": text} for way, who, text in rows]})
    if not rows:
        return m.gap().text("还没有收到或递出纸条。").hint(f"写法：{cmd('/团 密信 角色名 内容')}")
    return m.gap().items([f"**{way}** {safe(who)}：{safe(text)}" for way, who, text in rows])


def letters_revealed(rows: list[tuple[str, str, str]]) -> Msg:
    m = Msg().title("📜 这一局的纸条", f"共 {len(rows)} 张").gap().items(
        [f"**{safe(a)} → {safe(b)}**　{safe(text)}" for a, b, text in rows])
    return m.as_segment("moment").with_data({"kind": "letters_reveal",
                                             "rows": [{"from": a, "to": b, "text": text} for a, b, text in rows]})


XCARD_ENDING = {"finale": "终章已经在写，来不及改它；尾声和结局卡不会再追问是谁，主持人会看到这张卡。",
                "epilogue": "故事已经写完终章，后面不再有新的正文；主持人会看到这张卡，需要时可以 /团 完结 直接落幕。"}


def xcard_raised(stage: str = "") -> Msg:
    m = Msg().title("🛑 有人举了 X 卡").gap().text(
        XCARD_ENDING.get(stage) or "接下来的故事会避开刚才的内容，不再提起，也不追问是谁。")
    return m.as_segment("ties").with_data({"kind": "xcard", "stage": stage})


def xcard_ack(private: bool, seated: bool = True, stage: str = "") -> str:
    after = "已经记下。" if stage else "下一段正文会转开。"
    if private:
        return "已经匿名举卡，群里不会显示是谁。" + after
    return "已举卡，" + after + ("想完全匿名的话，下次私聊我发送 /团 X。" if seated else "")


# ---------------------------------------------------------------- flashbacks, bonds and bets
def flashback_told(actor: str, text: str, resource: str, delta: int, current: int, maximum: int, bonus: int) -> Msg:
    m = Msg().title(f"⏪ {safe(actor)} 的闪回", "每人每幕一次").gap().quote(text)
    m.gap().field("代价", f"{safe(resource)} {delta:+d}（剩 {current}/{maximum}）")
    m.hint(f"这段准备已经成立；{safe(actor)} 下一次相关检定 +{bonus}，无关检定不消耗加值")
    return m.as_segment("ties").with_data({"kind": "flashback", "actor": actor, "text": text, "resource": resource,
                                              "delta": delta, "current": current, "maximum": maximum, "bonus": bonus})


FLASHBACK_STEPS = (("审查", "先判断能否成立", "不能替他人同意或改写已知事实"), ("付出", "成立后花 1 点资源", "未成立不扣资源和次数"),
                   ("兑现", "相关检定 +2", "无关检定不消耗加值"))


def flashback_guide(left: str) -> Msg:
    m = Msg().title("闪回", "补写一段过去，让它现在派上用场").gap().text(
        "说一件你的角色合理做过的准备，比如提前藏好的钥匙、多年前学会的暗号。先审查是否成立，成立后花 1 点资源，"
        "下一次相关检定 +2。每人每幕一次；不能替他人同意、取得权限或推翻已发生的事。")
    if left:
        m.text(left)
    m.gap().hint(f"写法：{cmd('/团 闪回 我早就把备用钥匙藏在戏箱里')}；指定资源：{cmd('/团 闪回 理智 回忆内容')}")
    return m.as_segment("ties").with_data({"kind": "flashback_guide", "left": left, "steps": [list(s) for s in FLASHBACK_STEPS]})


def bond_proposed(a: str, b: str, text: str, user_id: str, user_name: str, renewing: bool = False) -> Msg:
    m = Msg().mention(user_id, user_name).title(f"🔗 {safe(a)} 想和 {safe(b)} " + ("改写羁绊" if renewing else "结下羁绊")).quote(text)
    m.hint(f"{safe(b)} 发送 {cmd('/团 羁绊 同意')} 接受，或 {cmd('/团 羁绊 拒绝')}")
    return m.as_segment("ties").with_data({"kind": "bond_proposed", "a": a, "b": b, "text": text, "renewing": renewing})


def bond_formed(a: str, b: str, text: str, bonus: int) -> Msg:
    m = Msg().title(f"🔗 {safe(a)} 与 {safe(b)} 结下羁绊").quote(text)
    m.gap().items(["两人同场时，正文会带出这层关系", f"互相援手时检定 +{bonus}（平时 +2）", "终章时画进人物关系图"])
    m.hint(f"{cmd('/团 羁绊')} 看这一桌的关系图；{cmd('/团 羁绊 解除 角色名')} 解开")
    return m.as_segment("ties").with_data({"kind": "bond", "a": a, "b": b, "text": text, "bonus": bonus})


def bond_map(cast: list[dict[str, str]], bonds: list[dict[str, Any]], pending: list[dict[str, Any]], *,
             note: str = "", finale: bool = False) -> Msg:
    """Every character and the bonds between them; finale is the ending's version."""
    m = Msg().title("🔗 " + ("这一局的人物关系" if finale else "人物关系图"), f"{len(bonds)} 条羁绊")
    if note:
        m.text(note)
    if bonds:
        m.gap().items([f"**{safe(r['a'])} ⟷ {safe(r['b'])}**　{safe(r['text'])}" for r in bonds])
    elif not pending:
        m.gap().text("还没有人结下羁绊。")
    if pending:
        m.gap().caption("等待确认").items([f"{safe(r['a'])} → {safe(r['b'])}　{safe(r['text'])}" for r in pending])
    if not finale:
        m.gap().hint(f"{cmd('/团 羁绊 角色名 关系')} 提出，对方 {cmd('/团 羁绊 同意')} 后生效；有羁绊的两人互相援手 +3")
    return m.as_segment("moment" if finale else "receipt").with_data(
        {"kind": "bonds", "finale": finale, "cast": cast, "bonds": bonds, "pending": pending, "note": note})


def wager_board(actor: str, round_number: int, rows: list[dict[str, str]], seers: list[dict[str, Any]], *,
                mine: str = "", open: bool = True, note: str = "") -> Msg:
    """This turn's bets (rows: name, pick) and the table's best guessers so far."""
    yes = [r["name"] for r in rows if r["pick"] == "success"]
    no = [r["name"] for r in rows if r["pick"] == "failure"]
    if open:
        m = Msg().title(f"🎲 竞猜 · {safe(actor)} 这一掷", f"第 {round_number} 轮　掷骰时揭晓")
        if note:
            m.text(note)
        m.gap().field("押成", f"{len(yes)} 人" + (f"　{'、'.join(safe(n) for n in yes)}" if yes else ""))
        m.field("押败", f"{len(no)} 人" + (f"　{'、'.join(safe(n) for n in no)}" if no else ""))
    else:
        m = Msg().title("🎲 竞猜", "现在没有等待掷骰的回合").gap().text("轮到下一位行动时再押。")
    if seers:
        m.gap().caption("本局预言家").items([f"{safe(s['name'])}　猜对 {s['right']}/{s['total']}" for s in seers[:5]])
    if open:
        m.gap().hint(f"{cmd('/团 押 成')} 或 {cmd('/团 押 败')}，掷骰前可以改押；没入座也能玩，行动的人自己不能押")
    return m.as_segment("banter").with_data({"kind": "wager", "actor": actor, "round": round_number, "open": open, "note": note,
                                              "rows": rows, "seers": seers[:5], "mine": mine})


# ---------------------------------------------------------------- rush rounds
def rush_prompt(round_number: int, choices: list[dict[str, str]], minutes: int | None, mode: str,
                members: list[tuple[str, str, str, bool]], others: dict[str, list[dict[str, Any]]] | None = None,
                pace: tuple[str, str] | None = None) -> Msg:
    """A rush round: everyone acts at once on shared options; members are (name, user, user id, submitted)."""
    done = sum(1 for m in members if m[3])
    msg = Msg()
    for name, user, user_id, submitted in members:
        if not submitted:
            msg.mention(user_id, user)
    meta = "　".join(x for x in (f"限时 {minutes} 分钟" if minutes else "", f"已交 {done}/{len(members)}") if x)
    msg.title(f"⚡ 快团 · 第 {round_number} 轮　全队同时行动", meta)
    if choices and mode != "dialogue_only":
        msg.gap().choices(choices)
        if any(c.get("closing") for c in choices):
            msg.text("🏁 标着“收束”的一项会把故事引向结局：有人选它，全桌就表决要不要收尾，选它的人都算同意。")
    if pace:
        msg.gap().field("节奏", f"**{safe(pace[0])}**　{safe(pace[1])}")
    pending = [safe(m[0]) for m in members if not m[3]]
    if pending:
        msg.gap().field("还没交", "、".join(pending))
    cmds = ([("选择", "/团 A")] if choices and mode != "dialogue_only" else []) + \
        ([("自由行动", "/团 行动 描述")] if mode != "choice_only" else []) + [("旁观", "/团 跳过")]
    msg.gap().hint("每人回复 " + "　或　".join(cmd(c) for _, c in cmds[:-1]) + "，句末可加 " + cmd("[用 名称]")
                   + " 或“孤注”；交了就掷骰，交齐或时间到一起写这一轮的正文",
                   note="没交的人这一轮旁观；不想行动发 " + cmd("/团 跳过") + "。", cmds=cmds)
    msg.with_data({"kind": "rush", "round": round_number, "minutes": minutes,
                   "members": [{"name": m[0], "done": m[3]} for m in members]})
    _others_fields(msg, others)
    return msg.as_segment("choices")


def rush_progress(members: list[tuple[str, bool]]) -> Msg:
    """members are (name, submitted) in seat order."""
    pending = [name for name, done in members if not done]
    m = Msg().text(f"快团已交 {len(members) - len(pending)}/{len(members)}，还等：" + "、".join(safe(n) for n in pending))
    return m.as_segment("banter").with_data({"kind": "rush_progress",
                                              "members": [{"name": n, "done": d} for n, d in members]})


def rush_reminder(missing: list[tuple[str, str, str]], members: list[tuple[str, bool]] | None = None) -> Msg:
    m = Msg()
    for _, user, user_id in missing:
        m.mention(user_id, user)
    m.title("⏳ 快团还剩 1 分钟", "还没交：" + "、".join(safe(n) for n, _, _ in missing)).hint(
        f"发送 {cmd('/团 A')} 或 {cmd('/团 行动 你的做法')}；时间到没交的人这一轮旁观")
    board = members if members is not None else [(n, False) for n, _, _ in missing]
    return m.as_segment("banter").with_data({"kind": "rush_remind", "members": [{"name": n, "done": d} for n, d in board]})


def rush_toggled(on: bool, minutes: int) -> Msg:
    if on:
        m = Msg().title("⚡ 快团开启").gap().text(
            f"从这一轮起全队同时行动：大家共用一组选项，各自交行动，交了就掷骰；全员交齐或 {minutes} 分钟一到，"
            "AI 把所有人的行动写成一段正文。没交的人这一轮旁观，援手留到普通回合再用。").hint("主持人发送 /团 主持 快团 关 回到轮流行动")
    else:
        m = Msg().title("快团关闭").gap().text("回到轮流行动，按座位顺序一人一回合。")
    return m.as_segment("moment").with_data({"kind": "rush", "on": on, "minutes": minutes})


def turn_reminder(actor: str, user_name: str, user_id: str, choices: bool) -> Msg:
    m = Msg().mention(user_id, user_name).title(f"⏳ {safe(actor)}，这一回合还剩 1 分钟")
    return m.hint(("超时会自动选择风险最低的一项。" if choices else "超时会跳过这一回合。")
                  + f"忘了选项的话，发送 {cmd('/团 回合')} 再看一遍")


def auto_away(actor: str, user_name: str, user_id: str, missed: int) -> Msg:
    m = Msg().mention(user_id, user_name).title(f"{safe(actor)} 已自动暂离", f"连续 {missed} 轮没有行动")
    return m.gap().para("轮到 TA 时会自动跳过，表决也不再等，故事先交给下一位。").hint(f"回来后发送 {cmd('/团 返回')} 回到行动队列")


def ask_back(actor: str, user_name: str, user_id: str, question: str, kind: str, *, again: bool,
             minutes: int | None, choices: bool) -> Msg:
    """The model asked back or refused a free action; tells the same player how to go on."""
    if kind == "impossible":
        title, fallback = "这样做行不通", "这个做法在眼下的局面里办不到。"
    elif again:
        title, fallback = "还是没能确定你的意图", "这个做法还不够明确。"
    else:
        title, fallback = "需要说清楚一点", "你想做的事情还不够明确。"
    meta = "　".join(x for x in (safe(actor), f"剩 {minutes} 分钟" if minutes else "") if x)
    m = Msg().mention(user_id, user_name).title(title, meta).gap().para(fallback if again else (safe(question) or fallback))
    if again:
        return m.hint("本回合不再追问：从下面的选项里选一个，或换个说法写清楚。")
    hints = [cmd("/团 行动 具体做法")] + ([cmd("/团 选 A")] if choices else [])
    cmds = [("写清楚", "/团 行动 具体做法")] + ([("用原选项", "/团 选 A")] if choices else [])
    if kind == "impossible":
        text = "换一种做法：回复 " + "　或　".join(hints)
        note = "换一种做法，或者用本轮原来的选项。" if choices else "换一种做法再试。"
    else:
        text = ("回复 " + hints[0] + " 只写一个去向或做法" + ("，或 " + hints[1] + " 用本轮原来的选项" if choices else "")
                + "。上面列了几个方向时，选其中一个就行。")
        note = "补充一次后不会再追问，会按最合理的理解结算。"
    return m.hint(text, note=note, cmds=cmds)


def adjustments_applied(lines: list[str]) -> Msg:
    return Msg().title("主持人调整生效").gap().items([safe(line) for line in lines]).as_segment("status")


# ---------------------------------------------------------------- skills and items
def loadout_card(name: str, entries: list[dict[str, Any]], resources: list[tuple[str, int, int]], *, own: bool,
                 wallet: tuple[str, int] | None = None) -> Msg:
    m = Msg().title(f"{safe(name)}的技能与物品")
    if resources:
        m.gap()
        for label, current, maximum in resources:
            m.meter(label, current, maximum)
    if wallet:
        m.gap().field("钱包", f"{wallet[1]} {safe(wallet[0])}")
    shown: list[dict[str, Any]] = []
    for kind, label in (("skill", "技能"), ("item", "物品")):
        rows = [e for e in entries if e["kind"] == kind]
        if not rows:
            continue
        m.gap().caption(label)
        lines = []
        for e in rows:
            effect = []
            if e["modifier"]:
                effect.append(f"{e['attribute_label'] or '任意'}检定 {e['modifier']:+d}")
            effect += [f"{k} -{v}" for k, v in e["cost"].items()] + [f"{k} +{v}" for k, v in e["gain"].items()]
            count = []
            if e.get("quantity") is not None:
                count.append(f"×{e['quantity']}")
            if e["remaining"] is not None:
                count.append(f"剩 {e['remaining']}/{e['uses']} 次 · {e['reset_label']}")
            if e.get("equipment", {}).get("equipped"):
                count.append("已装备")
            state = "" if e["usable"] else f"　〔{e['reason']}〕"
            note = f"　—— {safe(e['text'])}" if e.get("text") and e["text"] != " · ".join(effect) else ""
            lines.append(f"**{safe(e['name'])}**　{BT}{' · '.join(effect) or '叙事效果'}{BT}　{' · '.join(count)}{state}{note}")
            shown.append({"kind": kind, "name": e["name"], "effect": " · ".join(effect) or "叙事效果", "count": " · ".join(count),
                          "usable": bool(e["usable"]), "reason": "" if e["usable"] else str(e["reason"]),
                          "note": e["text"] if note else ""})
        m.items(lines)
    sample = next((e["name"] for e in entries if e["usable"] and e["modifier"]), None) \
        or next((e["name"] for e in entries), "名称")
    m.as_segment("sheet").with_data({"kind": "loadout", "name": name, "entries": shown,
                                     "resources": [list(r) for r in resources], "own": own, "sample": sample,
                                     "wallet": list(wallet) if wallet else None})
    if not entries:
        m.gap().text("没有技能或物品。")
    if own:
        m.gap().hint(f"检定时在行动后写 {cmd('[用 名称]')} 加成，例如 {cmd('/团 选 A [用 ' + sample + ']')}；"
                     f"不掷骰直接用：{cmd('/团 使用 名称')}")
    return m


def loadout_receipt(actor: str, verb: str, name: str, changes: dict[str, int], left: str) -> Msg:
    m = Msg().title(f"{safe(actor)} {verb}「{safe(name)}」")
    if changes:
        m.text("　".join(f"{k} **{v:+d}**" for k, v in changes.items()))
    if left:
        m.text(f"剩余：{left}")
    return m


def private_rooms(rooms: list[tuple[str, str, bool]]) -> Msg:
    m = Msg().title("你入座的团桌").gap()
    m.items([f"**{i}.** 群 {safe(g)}　{safe(short_title(t))}" + ("　〔当前〕" if cur else "") for i, (g, t, cur) in enumerate(rooms, 1)])
    return m.gap().hint(f"私聊里的指令作用于当前那一桌；发送 {cmd('/团 切换 序号')} 更换")


# ---------------------------------------------------------------- people
def attitude_scale(standing: int) -> str:
    """Seven cells from 敌对 to 盟友 with the current one filled."""
    return "".join("◆" if i == standing + 3 else "◇" for i in range(7))


def people_list(met: list[dict[str, Any]]) -> Msg:
    m = Msg().title("登场人物", "态度针对整个队伍")
    m.as_segment("receipt").with_data({"kind": "people", "met": [
        {"name": p["name"], "standing": p["standing"], "tier": p["tier"], "contributions": p["contributions"]} for p in met[:20]]})
    if not met:
        return m.gap().text("还没有遇到任何人。").gap().hint(f"剧情里出现的人物会自动记录；{cmd('/团 关系 人物 名字：做法 [属性 难度]')} 争取态度")
    rows = []
    for p in met[:20]:
        contrib = "　".join(f"{safe(k)} {v:+d}" for k, v in p["contributions"].items())
        rows.append(f"**{safe(p['name'])}**　{BT}{attitude_scale(p['standing'])}{BT} {p['tier']}" + (f"　{contrib}" if contrib else ""))
    m.gap().items(rows)
    return m.gap().hint(f"{cmd('/团 人物 名字')} 看详情；{cmd('/团 关系 人物 名字：做法 [属性 难度]')} 争取态度，成功升一档、失败降一档")


def person_card(p: dict[str, Any]) -> Msg:
    m = Msg().title(p["name"], "势力" if p["kind"] == "faction" else "人物")
    m.as_segment("receipt").with_data({"kind": "person", "name": p["name"], "faction": p["kind"] == "faction",
                                       "description": p.get("description") or "", "motivation": p.get("motivation") or "",
                                       "standing": p["standing"], "tier": p["tier"], "contributions": p["contributions"],
                                       "memories": (p.get("memories") or [])[-6:]})
    if p.get("description"):
        m.text(safe(p["description"]))
    if p.get("motivation"):
        m.field("动机", safe(p["motivation"]))
    m.gap().field("对队伍", f"{BT}{attitude_scale(p['standing'])}{BT} {p['tier']}")
    if p["contributions"]:
        m.field("各人影响", "　".join(f"{safe(k)} {v:+d}" for k, v in p["contributions"].items()))
    if p.get("memories"):
        m.gap().caption("往来").items([f"{safe(x['who'])}：{safe(x['text'])}" + (f"　{BT}{x['change']:+d}{BT}" if x["change"] else "")
                                      for x in p["memories"][-6:]])
    return m.gap().hint(f"{cmd('/团 关系 人物 ' + p['name'] + '：做法 [属性 难度]')} 争取态度；{cmd('/团 关系 记下 ' + p['name'] + '：往来')} 只记录不检定")


# ---------------------------------------------------------------- plays
def play_receipt(actor: str, summary: str, *, check: dict[str, Any] | None = None, draw: tuple[int, str] | None = None,
                 changes: list[str] | None = None, records: list[str] | None = None, note: str = "",
                 steps: list[str] | None = None) -> Msg:
    m = Msg().title(actor, summary).as_segment("receipt")
    if check:
        m.gap().check(**check)
    if draw:
        m.gap().draw(*draw)
    if changes:
        m.gap()
        for line in changes:
            m.text(line)
    if records:
        m.gap().items(records)
    if steps:
        m.gap().caption("接下来可以").items(steps[:5])
    if note:
        m.gap().hint(note)
    return m


def record_line(seq: int, kind: str, title: str, state: str, visual: str = "") -> str:
    return f"**#{seq}** {kind}「{safe(title)}」　{state}" + (f"　{visual}" if visual else "")


def records_list(lines: list[str], label: str = "") -> Msg:
    return Msg().title("玩法记录", label).gap().items(lines).gap().hint(f"{cmd('/团 查看 #编号')} 查看详情")


def record_detail(line: str, texts: list[str], rows: list[str], steps: list[str] | None = None,
                  meter: dict[str, Any] | None = None) -> Msg:
    """meter draws the record's progress on the image card: contest (ours, theirs, length), progress (done, total)
    or steps (each step's state)."""
    m = Msg().text(line)
    m.as_segment("receipt").with_data({"kind": "record", "line": line, "texts": texts, "rows": rows, "steps": steps or [],
                                       "meter": meter})
    for text in texts:
        m.gap().quote(text)
    if rows:
        m.gap().items(rows)
    if steps:
        m.gap().caption("接下来可以").items(steps)
    return m


def notice(title: str, detail: str = "", hint: str = "") -> Msg:
    """A short confirmation: one bold line, an optional detail line and what to do next."""
    m = Msg().title(title)
    if detail:
        m.text(detail)
    if hint:
        m.gap().hint(hint)
    return m


def saves_list(saves: list[tuple[str, str]]) -> Msg:
    m = Msg().title("存档", f"{len(saves)} 个").gap()
    m.items([f"**{i}. {safe(name)}**　{BT}{at}{BT}" for i, (name, at) in enumerate(saves, 1)])
    return m.gap().hint(f"主持人发送 {cmd('/团 读档 序号')} 读取，读档后故事处于暂停状态")


def next_steps(kind: str, state: str, seq: int, doc: dict[str, Any]) -> list[str]:
    """What players can do next with a play record, as commands with a short reason."""
    n = f"#{seq}"
    c = lambda text: cmd(text)  # noqa: E731
    if kind == "clue":
        return [f"{c('/团 假设 标题：推断')}　用它提出一个假设", f"{c('/团 假设 #假设 支持 ' + n)}　给已有假设补证据",
                f"{c('/团 出示 #证词 ' + n + ' 指出矛盾 [属性 难度]')}　拿它戳破证词"]
    if kind == "hypothesis" and state in ("open", "contested", "supported"):
        steps = [f"{c('/团 假设 ' + n + ' 支持 #线索')} 或 {c('反驳 #线索')}　让线索表态"]
        support, refute = len(doc.get("support") or []), len(doc.get("refute") or [])
        steps.append(f"{c('/团 结论 ' + n + ' 采纳')}　支持够了就定案" if state == "supported"
                     else f"至少两条线索支持、且支持多于反驳才能采纳（现在支持 {support}、反驳 {refute}）")
        return steps + [f"{c('/团 结论 ' + n + ' 否定')} 或 {c('/团 假设 ' + n + ' 撤回')}　放弃这个推断"]
    if kind == "testimony" and state in ("standing", "shaken"):
        return [f"{c('/团 追问 ' + n + ' 问题 [属性 难度]')}　逼问证人", f"{c('/团 出示 ' + n + ' #线索 矛盾 [属性 难度]')}　拿证据对质",
                f"{c('/团 对照 ' + n + ' #另一份证词 说明')}　比较两份说法"]
    if kind == "negotiation" and state in ("open", "bargaining"):
        terms = doc.get("terms") or []
        steps = [f"{c('/团 交涉 ' + n + ' 理由 [属性 难度]')}　争取筹码（目前 {doc.get('leverage', 0)}）",
                 f"{c('/团 条款 ' + n + ' 内容')}　提出条款"]
        if terms:
            steps.append(f"{c('/团 签署 ' + n + ' 序号')}　签署条款（共 {len(terms)} 条）")
        return steps + [f"{c('/团 交涉 ' + n + ' 达成')} 或 {c('中止')}　收尾"]
    if kind == "relation":
        name = doc.get("subject", "")
        word = "势力" if doc.get("subject_kind") == "faction" else "人物"
        return [f"{c('/团 关系 ' + word + ' ' + name + '：做法 [属性 难度]')}　成功升一档、失败降一档", f"{c('/团 人物 ' + name)}　看往来与各人影响"]
    if kind == "companion_goal" and state == "active":
        return [f"{c('/团 目标 ' + n + ' 实现')} 或 {c('放弃')}　了结这个目标"]
    if kind == "deadline" and state == "pending":
        return [f"{c('/团 期限 ' + n + ' 完成')}　按时完成", f"{c('/团 时间')}　看现在是什么时候"]
    if kind == "project" and state == "active":
        return [f"{c('/团 项目 ' + n + ' 推进 [属性 难度]')}　成功推进一格（{doc.get('progress', 0)}/{doc.get('segments')}）",
                f"{c('/团 休整')}　安全休整一个时段"]
    if kind == "contest" and state == "engaged":
        procedure = doc.get("procedure")
        if procedure == "chase":
            far = int(doc.get("distance", 3) or 3) * 2
            goal = (f"距离降到 0 就追上，拉开到 {far} 就跟丢" if doc.get("role") == "pursue"
                    else f"距离拉开到 {far} 就甩掉，降到 0 就被追上")
        elif procedure == "debate":
            done, rounds = len(doc.get("exchanges") or []), int(doc.get("rounds", 3) or 3)
            goal = f"共 {rounds} 轮（已过 {done} 轮），打完时比分高的一方获胜"
        else:
            goal = f"先拿到 {doc.get('length', 4)} 分的一方获胜"
        steps = [f"{c('/团 交锋 ' + n + ' 行动 [属性 难度]')}　出手，{goal}"]
        if procedure != "chase":
            steps.append(f"{c('/团 交锋 ' + n + ' 孤注 行动 [属性 难度]')}　孤注一掷，成败都按 2 分计")
        return steps + [f"{c('/团 冲突 ' + n + ' 加入')}　加入这场对抗", f"{c('/团 冲突 ' + n + ' 让步')}　自己退出，全员退出后对抗结束"]
    if kind == "plan" and state == "draft":
        return [f"{c('/团 计划 ' + n + ' 认领 步骤号')}　认领一步", f"{c('/团 计划 ' + n + ' 确认')}　每一步都有人认领后确认"]
    if kind == "plan" and state in ("confirmed", "underway", "compromised"):
        return [f"{c('/团 执行 ' + n + ' 步骤号 [属性 难度]')}　执行本人认领的步骤", f"{c('/团 计划 ' + n + ' 撤离')}　放弃剩下的步骤"]
    if kind == "oracle":
        return ["神谕只是建议：主持人和叙事可以采纳，也可以忽略"]
    if kind == "fortune" and state == "frozen":
        return [f"{c('/团 机运 ' + n + ' 兑现 怎么用这份运气')}　在合适的时候兑现"]
    if kind == "transformation" and state == "awaiting_target":
        return [f"被指名的角色本人：{c('/团 转变 ' + n + ' 确认')} 或 {c('拒绝')}", f"提出者：{c('/团 转变 ' + n + ' 撤回')}"]
    if kind == "branch" and state == "proposed":
        return [f"{c('/团 结局 ' + n + ' 支持')}　支持这个走向", f"全员支持后 {c('/团 结局 ' + n + ' 进入')}"]
    if kind == "ending" and state == "entered":
        return [f"{c('/团 尾声 ' + n + ' 内容')}　写下你的角色的尾声", f"全员写完后 {c('/团 结局 ' + n + ' 完结')}"]
    return []


def vote_card(title: str, premise: str, options: list[dict[str, Any]], ballots: int, voters: int, minutes: int,
              *, kind: str = "表决") -> Msg:
    m = Msg().heading(f"{kind} · {title.replace(' 提议：', '：', 1) if kind == '全队提议' else title}")
    if premise:
        m.para(premise)
    items = []
    for o in options:
        tag = "　".join(t for t in (f"风险：{o['risk']}" if o.get("risk") else "", f"代价：{o['cost']}" if o.get("cost") else "") if t)
        items.append({"label": o["key"], "text": o["label"] + (f"——{o['description']}" if o.get("description") else ""), "tag": tag})
    m.gap().choices(items)
    m.with_data({"kind": "vote_open", "ballots": ballots, "voters": voters, "minutes": minutes})
    ways = [(o["label"], f"/团 投 {o['key']}") for o in options]
    return m.gap().hint("　".join(f"{cmd(c)} {safe(label)}" for label, c in ways) + f"　已投 {ballots}/{voters}　{minutes} 分钟后截止",
                        note=f"已投 {ballots}/{voters}，{minutes} 分钟后截止；改主意可以再投一次。", cmds=ways).as_segment("choices")


def vote_result(title: str, winner: str, counts: list[tuple[str, int]], note: str = "",
                voters: dict[str, list[str]] | None = None) -> Msg:
    """Winner first, then every option's count, e.g. 结果：同意　同意 2 · 反对 1."""
    tally = " · ".join(f"{safe(label)} {n}" for label, n in counts)
    m = Msg().title("表决结果", title).text(f"结果：**{safe(winner)}**　{BT}{tally}{BT}")
    m.as_segment("moment").with_data({"kind": "vote", "title": title, "winner": winner, "counts": [list(c) for c in counts],
                                      "note": note, "voters": voters or {}})
    return m.gap().hint(note) if note else m


def status_card(title: str, state: str, act: tuple[int, int, str] | None, round_number: int | None, clock: str,
                scene: str, goal: str, me: dict[str, Any] | None, table: list[str], world: str = "",
                party: list[dict[str, Any]] | None = None, npcs: list[dict[str, Any]] | None = None) -> Msg:
    """party (name, role, player, resources, acting: the turn's state for whoever holds it, away) and npcs (name,
    standing, tier) only feed the image card."""
    m = Msg().title(short_title(title), state).as_segment("room")
    m.with_data({"title": short_title(title), "state": state, "act": list(act) if act else None, "round": round_number,
                 "clock": clock, "scene": scene, "goal": goal, "me": me, "table": table, "party": party or [], "npcs": npcs or []})
    if world:
        m.with_art(world, "cover", "团桌状态")
    if act:
        number, total, act_title = act
        m.text(f"{act_label(number)} · {act_title}　{BT}{dots(number, total, '■', '□')}{BT}" if total else f"{act_label(number)} · {act_title}")
    meta = "　".join(x for x in (f"第 {round_number} 轮" if round_number else "", clock) if x)
    if meta:
        m.text(meta)
    if scene:
        m.gap().field("场景", scene)
    if goal:
        m.field("目标", goal)
    if me:
        m.gap().title(me["name"], me.get("archetype", ""))
        for name, current, maximum in me["resources"]:
            m.meter(name, current, maximum)
    if table:
        m.gap().items(table)
    return m


def ending_card(world_title: str, ending: str, epilogues: list[tuple[str, str]], stats: str, *, world: str = "",
                art: str = "", report: dict[str, Any] | None = None) -> Msg:
    """report is the battle report's data (acts, cast, outcomes); the image card draws the journey from it."""
    m = Msg().banner("终章" + (f" · {ending}" if ending else "")).caption(short_title(world_title))
    m.as_segment("moment").with_data({"kind": "ending", "title": short_title(world_title), "ending": ending,
                                      "epilogues": [list(e) for e in epilogues], "stats": stats, "report": report})
    if world:
        m.with_art(world, art or "cover", "终章")
    if epilogues:
        m.gap().items([f"**{safe(name)}**　{safe(text)}" for name, text in epilogues])
    seer = (report or {}).get("seer")
    if seer:
        m.gap().field("本局预言家", f"{safe(seer['name'])}　竞猜猜对 {seer['right']}/{seer['total']}")
    return m.gap().hint(stats + f"　{cmd('/团 战报')} 看这一局的回顾，{cmd('/团 金句 那句话里的几个字')} 把喜欢的句子收进金句榜；"
                        f"主持人发送 {cmd('/团 关闭')} 收桌")


# ---------------------------------------------------------------- today's roll
def daily_roll(name: str, day: str, face: int, fortune: str, tier: str, yi: list[list[str]], ji: list[list[str]],
               *, again: bool = False, crit: str = "") -> Msg:
    """One player's d20 of the day with two 宜 and two 忌; again marks a repeat ask (same result)."""
    m = Msg().title("今日一掷", day).as_segment("daily")
    m.with_data({"kind": "roll", "name": name, "day": day, "face": face, "fortune": fortune, "tier": tier,
                 "yi": [list(s) for s in yi], "ji": [list(s) for s in ji], "again": again, "crit": crit})
    m.text(f"{safe(name)}　**{face} · {fortune}**")
    if again:
        m.caption("今天已经掷过，结果不会改变")
    if crit:
        m.gap().text(crit)
    for label, signs in (("宜", yi), ("忌", ji)):
        m.gap().field(label, " · ".join(term for term, _ in signs)).text("；".join(gloss for _, gloss in signs) + "。")
    return m.gap().caption("每日一次，不改变故事里的检定")


def daily_board(day: str, rows: list[dict[str, Any]]) -> Msg:
    """This group's rolls today, highest first."""
    m = Msg().title("今日一掷 · 本群", f"{day}　{len(rows)} 人已掷").as_segment("daily")
    m.with_data({"kind": "board", "day": day, "rows": [dict(r) for r in rows[:30]]})
    if not rows:
        return m.gap().text("今天还没有人掷。").gap().hint(f"发送 {cmd('/团 一掷')} 掷出你的今日一掷")
    m.gap().items([f"**{r['face']} · {r['fortune']}**　{safe(r['name'])}" for r in rows[:30]])
    if len(rows) > 30:
        m.caption(f"另有 {len(rows) - 30} 人未列出")
    return m.gap().hint(f"发送 {cmd('/团 一掷')} 掷出你的今日一掷")



# ---------------------------------------------------------------- group pastimes
def dice_roll(name: str, expr: str, reason: str, terms: list[dict[str, Any]], total: int, *, hidden: bool = False) -> Msg:
    """A free roll; dropped dice (kh/kl) are shown in parentheses."""
    m = Msg().title("暗骰" if hidden else "掷骰", safe(reason)).as_segment("daily")
    dice = [t for t in terms if "faces" in t]
    natural = dice[0]["faces"][0] if len(dice) == 1 and dice[0]["sides"] == 20 and len(dice[0]["faces"]) == 1 else None
    m.with_data({"kind": "dice", "name": name, "expr": expr, "reason": reason, "terms": terms, "total": total,
                 "hidden": hidden, "natural": natural if natural in (1, 20) else None})
    parts = []
    for t in terms:
        if "faces" in t:
            faces = ", ".join(str(f) if k else f"({f})" for f, k in zip(t["faces"], t["kept"]))
            parts.append(f"{t['label']} [{faces}]")
        else:
            parts.append(t["label"])
    m.text(f"{safe(name)} 掷 {cmd(expr)}").text(" ".join(parts) + f" ＝ **{total}**")
    if natural in (1, 20):
        m.caption(f"天然 {natural}")
    if hidden:
        m.caption("暗骰：只有你能看到")
    return m


def duel_challenge(name: str, target: str | None, reason: str, minutes: int) -> Msg:
    m = Msg().title("骰子对决", safe(reason))
    if target:
        m.mention(target, "对手")
    m.text(f"{safe(name)} 发起了一场骰子对决，双方各掷一次 d20，点大者胜。")
    return m.gap().hint(f"{'被点名的人' if target else '谁都可以'}发送 {cmd('/团 应战')} 接下，{minutes} 分钟内有效")


def duel_result(a: str, b: str, rounds: list[tuple[int, int]], winner: str, reason: str) -> Msg:
    x, y = rounds[-1]
    m = Msg().title("骰子对决", safe(reason)).as_segment("daily")
    m.with_data({"kind": "duel", "a": a, "b": b, "rounds": [list(r) for r in rounds], "winner": winner, "reason": reason})
    m.text(f"{safe(a)}　**{x}** ： **{y}**　{safe(b)}")
    if len(rounds) > 1:
        m.caption(f"平局重掷 {len(rounds) - 1} 次")
    return m.text(f"胜者：**{safe(winner)}**" if winner else "连掷十次都是平局，握手言和。")


def battle_report(d: dict[str, Any], art: str = "cover") -> Msg:
    m = Msg().banner(f"战报 · {d['title']}").as_segment("moment").with_data({"kind": "report", **d})
    if d.get("world"):
        m.with_art(d["world"], art, "战报")
    if d.get("sub"):
        m.caption(d["sub"])
    acts = d.get("acts") or []
    now_act = next((a for a in acts if a["number"] == d["act"]), None)
    progress = act_label(d["act"]) + (f" · {now_act['title']}" if now_act and now_act["title"] else "")
    progress += f"（共 {d['total']} 幕）" if d.get("total") else ""
    m.gap().field("进度", f"{d['state']}　{progress}" + (f"　结局：{safe(d['ending'])}" if d.get("ending") else ""))
    if d.get("cast"):
        m.field("阵容", "、".join(f"{safe(c['name'])}（{safe(c['role'])}）" if c.get("role") else safe(c["name"]) for c in d["cast"]))
    m.field("统计", f"{d['rounds']} 轮 · {d['checks']} 次检定 · 大成功 {d['crits']} · 大失败 {d['fumbles']}")
    if d.get("best"):
        m.field("全场最佳", safe(d["best"]))
    if d.get("seer"):
        m.field("本局预言家", f"{safe(d['seer']['name'])}　竞猜猜对 {d['seer']['right']}/{d['seer']['total']}")
    bests = [f"{act_label(a['number'])}{(' · ' + safe(a['title'])) if a['title'] else ''}　{safe(a['best'])}" for a in acts if a.get("best")]
    if bests:
        m.gap().caption("每幕最佳").items(bests)
    if d.get("quote"):
        m.gap().quote(d["quote"])
    return m


def schedule_board(title: str, options: list[dict[str, Any]], declined: list[str], *, decided: bool) -> Msg:
    m = Msg().title("约团", short_title(title)).as_segment("room")
    m.with_data({"kind": "schedule", "title": short_title(title), "options": options, "declined": declined, "decided": decided})
    rows = []
    for i, o in enumerate(options, 1):
        names = "、".join(safe(n) for n in o["names"])
        rows.append(f"**{i}.** {o['label']}　{len(o['names'])} 人" + (f"　{names}" if names else "") + ("　**已定档**" if o["decided"] else ""))
    m.gap().items(rows)
    if declined:
        m.field("都不行", "、".join(safe(n) for n in declined))
    if decided:
        return m.gap().hint("开始前 30 分钟会在群里提醒勾选了这个时间的人")
    return m.gap().hint(f"{cmd('/团 约 1 3')} 勾选合适的时间，都不行就发 {cmd('/团 约 都不行')}；主持人 {cmd('/团 定档 序号')} 定下")


def schedule_notice(title: str, when: str, who: list[tuple[str, str]], kind: str) -> Msg:
    m = Msg().title("已定档" if kind == "定档" else "约团提醒", short_title(title))
    for user_id, name in who:
        m.mention(user_id, name)
    m.text(f"开团时间：**{when}**")
    return m.text("还有 30 分钟开始，准备上桌。" if kind == "提醒" else "开始前 30 分钟会再提醒一次。")


def relay_progress(lines: list[dict[str, str]], total: int, *, intro: bool = False) -> Msg:
    if intro:
        return Msg().title("故事接龙").text(f"还没有人起头。发送 {cmd('/团 接龙 第一句')} 开始，满 {total} 句由 AI 写结尾。")
    m = Msg().title("故事接龙", f"{len(lines)}/{total} 句").gap()
    m.items([f"{safe(line['text'])}　—— {safe(line['name'])}" for line in lines])
    return m.gap().hint(f"{cmd('/团 接龙 你的句子')} 接下去；起头的人可以 {cmd('/团 接龙 收尾')} 提前请 AI 收尾")


def sentence(text: str) -> str:
    """A relay line with its closing punctuation, so the lines read as one passage."""
    return text if text[-1:] in "。！？…!?」”』）)～~" else text + "。"


def relay_story(title: str, lines: list[dict[str, str]], ending: str) -> Msg:
    m = Msg().title("故事接龙", safe(title) or "未完").as_segment("daily")
    m.with_data({"kind": "relay", "title": title, "lines": [dict(line) for line in lines], "ending": ending})
    m.para("".join(sentence(safe(line["text"])) for line in lines))
    if ending:
        m.para(safe(ending))
    names = list(dict.fromkeys(line["name"] for line in lines))
    return m.caption("执笔：" + "、".join(safe(n) for n in names) + ("　·　AI 收尾" if ending else ""))


# ---------------------------------------------------------------- luck, quotes, turtle soup
def _bar(value: int, peak: int, width: int = 12) -> str:
    return "▇" * max(1 if value else 0, round(value / peak * width)) if peak else ""


def luck_card(name: str, period: str, s: dict[str, Any], total: int) -> Msg:
    """One member's d20s in this group: average, tier, 20s and 1s, and the spread of faces."""
    m = Msg().title("骰运", f"{safe(name)}　{period}").as_segment("daily")
    m.with_data({"kind": "luck", "name": name, "period": period, "total": total, **s})
    if not s["count"]:
        return m.gap().text(f"这段时间还没掷过 d20，全部记录共 {total} 次。").gap().hint(f"发送 {cmd('/团 骰运 全部')} 看全部记录")
    m.gap().text(f"平均 **{s['average']:.2f}** · {s['tier']}　共 {s['count']} 次")
    m.field("大成功", f"{s['crits']} 次").field("大失败", f"{s['fumbles']} 次").field("过半", f"{s['high']}%（掷出 11 以上）")
    if s["sources"]:
        m.field("来源", "　".join(f"{label} {n}" for label, n in s["sources"]))
    peak = max(s["faces"])
    m.gap().caption("点数分布").items([f"{face:>2}　{_bar(n, peak)} {n}" for face, n in
                                    ((20, s["faces"][19]), (15, sum(s["faces"][14:19])), (10, sum(s["faces"][9:14])),
                                     (5, sum(s["faces"][4:9])), (2, sum(s["faces"][1:4])), (1, s["faces"][0]))])
    return m.gap().hint(f"{cmd('/团 骰运 榜')} 看本群本月的欧皇与非酋")


def luck_board(month: str, ranked: list[dict[str, Any]], rows: list[dict[str, Any]], minimum: int) -> Msg:
    m = Msg().title("骰运榜", f"本群 · {month}").as_segment("daily")
    crit = max(rows, key=lambda r: (r["crits"], -r["count"]), default=None)
    fumble = max(rows, key=lambda r: (r["fumbles"], -r["count"]), default=None)
    m.with_data({"kind": "luck_board", "month": month, "ranked": ranked[:20], "minimum": minimum, "players": len(rows),
                 "rolls": sum(r["count"] for r in rows),
                 "crit": {"name": crit["name"], "n": crit["crits"]} if crit and crit["crits"] else None,
                 "fumble": {"name": fumble["name"], "n": fumble["fumbles"]} if fumble and fumble["fumbles"] else None})
    if not ranked:
        m.gap().text(f"这个月还没有人掷满 {minimum} 次 d20。")
    else:
        top, bottom = ranked[:3], [r for r in ranked[::-1][:3] if r not in ranked[:3]]
        m.gap().caption("欧皇").items([f"**{r['average']:.2f}**　{safe(r['name'])}　{r['count']} 次" for r in top])
        if bottom:
            m.gap().caption("非酋").items([f"**{r['average']:.2f}**　{safe(r['name'])}　{r['count']} 次" for r in bottom])
    if crit and crit["crits"]:
        m.gap().field("大成功最多", f"{safe(crit['name'])} {crit['crits']} 次")
    if fumble and fumble["fumbles"]:
        m.field("大失败最多", f"{safe(fumble['name'])} {fumble['fumbles']} 次")
    return m.gap().caption(f"掷满 {minimum} 次 d20 才上榜；检定、一掷、掷骰和对决都算")


QUOTE_HEADS = {"saved": "已收入金句", "marked": "已收藏金句", "random": "金句重温"}


def quote_card(text: str, source: str, number: int, marks: int, saved_name: str, kind: str) -> Msg:
    m = Msg().title(QUOTE_HEADS.get(kind, "金句"), f"No.{number}").as_segment("daily")
    m.with_data({"kind": "quote", "head": QUOTE_HEADS.get(kind, "金句"), "text": text, "source": source, "no": number,
                 "marks": marks, "saved_name": saved_name, "mode": kind})
    m.gap().quote(text)
    if source:
        m.caption(f"—— {safe(source)}")
    m.gap().caption(f"{marks} 人收藏 · {safe(saved_name)} 最先收录")
    if kind == "random":
        return m.hint(f"喜欢这句就发送 {cmd(f'/团 金句 +{number}')} 一起收藏")
    return m.hint(f"{cmd('/团 金句')} 随机重温，{cmd('/团 金句 榜')} 看收藏最多的句子")


def quote_board(rows: list[dict[str, Any]], total: int) -> Msg:
    m = Msg().title("金句榜", f"本群共 {total} 句").as_segment("daily")
    m.with_data({"kind": "quote_board", "total": total,
                 "rows": [{k: r[k] for k in ("id", "text", "source", "marks", "saved_name")} for r in rows]})
    if not rows:
        return m.gap().text("本群还没有金句。").gap().hint(f"回复故事消息发送 {cmd('/团 金句')}，或 {cmd('/团 金句 那句话里的几个字')}")
    m.gap().items([f"**{r['marks']}** 人　{safe(r['text'])}　—— {safe(r['source'])}（No.{r['id']}）" for r in rows])
    return m.gap().hint(f"发送 {cmd('/团 金句 +编号')} 收藏榜上的句子")


SOUP_TONES = {"是": "yes", "否": "no", "无关": "skip", "是也不是": "half"}


def soup_board(soup: dict[str, Any], *, fresh: bool = False) -> Msg:
    """The surface, the unlocked key points and the latest questions of the group's turtle soup."""
    found = sum(k["by"] is not None for k in soup["keys"])
    m = Msg().title(f"海龟汤 · {soup['flavor']}", safe(soup["title"])).as_segment("daily")
    m.with_data({"kind": "soup", "fresh": fresh, "title": soup["title"], "flavor": soup["flavor"], "surface": soup["surface"],
                 "server": soup["name"], "count": soup["count"], "guesses": soup["guesses"],
                 "keys": [{"text": k["text"] if k["by"] else "", "by": k["by"] or ""} for k in soup["keys"]],
                 "asked": soup["asked"][-8:]})
    m.gap().quote(soup["surface"])
    m.gap().field("关键线索", f"{found}/{len(soup['keys'])} {dots(found, len(soup['keys']))}")
    for k in soup["keys"]:
        if k["by"]:
            m.text(f"✦ {safe(k['text'])}（{safe(k['by'])}）")
    if soup["asked"]:
        m.gap().caption(f"已问 {soup['count']} 个问题").items(
            [f"{safe(a['name'])}：{safe(a['q'])} → **{a['a']}**" for a in soup["asked"][-5:]])
    return m.gap().hint(f"{cmd('/团 问 是非题')} 提问，{cmd('/团 猜 你的推理')} 揭开汤底",
                        note=f"{safe(soup['name'])} 端上了这碗汤" if fresh else "")


def _soup_notes(m: Msg, notes: list[str]) -> Msg:
    for line in notes:
        m.text(line)
    return m


def soup_answer(number: int, name: str, question: str, answer: str, notes: list[str]) -> Msg:
    """One answered question, plain lines in every mode; notes are the key points it unlocked."""
    return _soup_notes(Msg().text(f"第 {number} 问 · {safe(name)}：{safe(question)}").text(f"→ **{answer}**"), notes)


def soup_guess(name: str, guess: str, verdict: str, comment: str, notes: list[str]) -> Msg:
    head = "**接近了**" if verdict == "close" else "**不对**"
    m = Msg().text(f"{safe(name)} 猜：{safe(guess)}").text(f"→ {head}" + (f"：{safe(comment)}" if comment else ""))
    return _soup_notes(m, notes)


def soup_reveal(soup: dict[str, Any], solver: str, guess: str, minutes: int) -> Msg:
    m = Msg().title("汤底揭晓", safe(soup["title"])).as_segment("daily")
    finders = [k["by"] for k in soup["keys"] if k["by"]]
    m.with_data({"kind": "soup_end", "title": soup["title"], "flavor": soup["flavor"], "surface": soup["surface"],
                 "truth": soup["truth"], "keys": [dict(k) for k in soup["keys"]], "solver": solver, "guess": guess,
                 "count": soup["count"], "guesses": soup["guesses"], "minutes": minutes,
                 "top": max(finders, key=finders.count) if finders else ""})      # ties: whoever found one first
    m.gap().text(f"**{safe(solver)} 猜中了！**" if solver else "这碗汤没人喝透，直接揭晓。")
    if guess:
        m.caption(f"推理：{safe(guess)}")
    m.gap().field("汤面", safe(soup["surface"])).gap().field("汤底", safe(soup["truth"]))
    m.gap().caption("关键线索").items([f"{'✦' if k['by'] else '○'} {safe(k['text'])}" + (f"（{safe(k['by'])}）" if k["by"] else "")
                                   for k in soup["keys"]])
    return m.gap().caption(f"问了 {soup['count']} 个问题 · 猜了 {soup['guesses']} 次 · 用时 {minutes} 分钟")


# ---------------------------------------------------------------- one-minute adventure
def _adventure_roll(m: Msg, r: dict[str, Any]) -> Msg:
    verdict = "大成功" if r["crit"] else "大失败" if r["fumble"] else "成功" if r["ok"] else "失败"
    m.text(f"第 {r['step']} 步 · {r['label']} {safe(r['text'])}　{BT}d20 {r['face']}{BT} {r['modifier']:+d} ＝ **{r['total']}**"
           f"（{r['attr']}·{r['difficulty']} {r['dc']}）**【{verdict}】**")
    return m.text(safe(r["outcome"]))


def adventure_stage(v: dict[str, Any], *, fresh: bool = False) -> Msg:
    """One step of a one-minute adventure: how the last step went, then the next scene and its options."""
    m = Msg().title(f"🧭 一分钟冒险 · {safe(v['title'])}", f"{safe(v['world'])}　第 {v['step'] + 1}/{v['total']} 步")
    m.as_segment("daily").with_data({"kind": "adventure", "fresh": fresh, **v}).with_art(v["world_id"], "cover", "一分钟冒险")
    m.text(f"你是 **{safe(v['role'])}** {safe(v['hero'])}")
    if fresh:
        m.gap().para(v["hook"])
    if v["results"]:
        _adventure_roll(m.gap(), v["results"][-1])
    m.gap().quote(v["scene"]).gap().choices(v["options"])
    return m.gap().hint(f"发送 {cmd('/团 冒险 A')} 选一项，掷 d20 定成败；不玩了发送 {cmd('/团 冒险 放弃')}")


def adventure_end(v: dict[str, Any]) -> Msg:
    m = Msg().title(f"🧭 冒险结束 · {safe(v['title'])}", f"{safe(v['world'])}　{v['wins']}/{v['total']} 步成功")
    m.as_segment("daily").with_data({"kind": "adventure_end", **v}).with_art(v["world_id"], "cover", "一分钟冒险")
    m.text(f"{safe(v['role'])} {safe(v['hero'])}：**{v['tier']}**")
    for r in v["results"]:
        _adventure_roll(m.gap(), r)
    m.gap().para(v["ending"])
    return m.hint(f"每人每天一次，明天再来；{cmd('/团 一掷')} 看看今天的运势")


# ---------------------------------------------------------------- economy
OUTFIT_CMDS = [("看货", "/团 商店"), ("买", "/团 买 物品 数量"), ("卖", "/团 卖 物品"), ("好了", "/团 整备 好了")]


def shop_card(shops: list[dict[str, Any]], unit: str, wallet: int | None, *, place: str, outfit: bool, sell: int,
              single: bool) -> Msg:
    """Shops with their wares; 'open' marks the ones at the current place."""
    here = [s for s in shops if s["open"]]
    m = Msg().title(f"🏪 {safe(shops[0]['name'])}" if single else "🏪 商店", f"钱包 {wallet} {unit}" if wallet is not None else unit)
    if not single:
        m.text(f"所在地：{safe(place) or '未知'}；能进的店：" + ("、".join(safe(s["name"]) for s in here) or "这里没有店"))
    for s in shops:
        where = "" if s["open"] else f"（在{safe(s['place'])}，到那里才能买）" if s["place"] else ""
        m.gap().caption(safe(s["name"]) + (f" · {safe(s['kind'])}" if s["kind"] else "") + where)
        if s["text"]:
            m.text(safe(s["text"]))
        m.items([f"**{safe(w['name'])}**　{w['price']} {safe(unit)}" + (f"　回收 {w['sell']}" if sell and w["sell"] else "")
                 + (f"　已有 ×{w['owned']}" if w["owned"] else "") for w in s["wares"]])
    m.as_segment("economy").with_data({"kind": "shops", "shops": shops, "unit": unit, "wallet": wallet, "place": place,
                                       "outfit": outfit, "sell": sell, "single": single})
    if outfit:
        return m.gap().hint(f"整备中：{cmd('/团 买 物品 数量')} 买下，{cmd('/团 卖 物品')} 卖给店里，买好了发送 {cmd('/团 整备 好了')}",
                            note="只能在当前地点的店里买；同伴之间可以 /团 给 名字 物品", cmds=OUTFIT_CMDS[1:])
    return m.gap().hint(f"买卖在整备时进行：主持人发送 {cmd('/团 主持 整备')} 开启后，私聊我采买。转交随时可以：{cmd('/团 给 名字 物品')}",
                        note="整备时才开门；钱包余额也在 /团 背包 里", cmds=[("转交", "/团 给 名字 物品"), ("背包", "/团 背包")])


def outfit_card(title: str, place: str, shops: list[str], members: list[dict[str, Any]], minutes: int, unit: str) -> Msg:
    done = sum(1 for x in members if x["done"])
    m = Msg().title(f"🛒 {safe(title)}", f"{done}/{len(members)} 人好了 · 剩 {minutes} 分钟")
    m.text("回合暂停，计时停住。" + (f"这里能进的店：{'、'.join(safe(s) for s in shops)}。" if shops
                                     else "这里没有店，可以互相转交、换装备。"))
    m.items([f"**{safe(x['name'])}**　{BT}{'好了' if x['done'] else '采买中'}{BT}" for x in members])
    m.as_segment("economy").with_data({"kind": "outfit", "title": title, "place": place, "shops": shops, "members": members,
                                       "minutes": minutes, "unit": unit})
    return m.gap().hint(f"私聊我发送 {cmd('/团 商店')} 看货，{cmd('/团 买 物品 数量')} 买下，好了发送 {cmd('/团 整备 好了')}。"
                        f"全员好了或时间到就结束，主持人也可以 {cmd('/团 主持 整备 收起')}",
                        note="私聊采买，群里只显示谁好了；结束时公开汇总，写进下一段正文", cmds=OUTFIT_CMDS)


def outfit_summary(rows: list[dict[str, Any]], unit: str, place: str, why: str, gifts: list[str]) -> Msg:
    m = Msg().title("🧾 整备汇总", safe(why))
    lines = []
    for r in rows:
        did = []
        if r["bought"]:
            did.append("买 " + "、".join(safe(x) for x in r["bought"]))
        if r["sold"]:
            did.append("卖 " + "、".join(safe(x) for x in r["sold"]))
        money = "　".join(x for x in (f"花 {r['spent']}" if r["spent"] else "", f"进 {r['earned']}" if r["earned"] else "") if x)
        lines.append(f"**{safe(r['name'])}**　" + ("；".join(did) if did else "没有买卖")
                     + (f"　{BT}{money}{BT}" if money else "") + f"　现有 {r['after']} {safe(unit)}")
    m.items(lines or ["没有人在座"])
    if gifts:
        m.gap().field("转交", "；".join(safe(g) for g in gifts))
    m.as_segment("economy").with_data({"kind": "outfit_summary", "rows": rows, "unit": unit, "place": place, "why": why,
                                       "gifts": gifts})
    return m.gap().hint("这些采买会写进下一段正文；回合从暂停处继续")


def trade_card(kind: str, who: str, shop: str, item: str, count: int, delta: int, after: int, unit: str, *, held: int) -> Msg:
    buy = kind == "buy"
    m = Msg().title(f"{'🛒' if buy else '💰'} {safe(who)} 在{safe(shop)}{'买下' if buy else '卖掉'}「{safe(item)}」×{count}")
    m.text(f"{safe(unit)} **{delta:+d}**　现有 **{after}** {safe(unit)}　背包里 {safe(item)} ×{held}")
    m.as_segment("economy").with_data({"kind": "trade", "trade": kind, "who": who, "shop": shop, "item": item, "count": count,
                                       "delta": delta, "after": after, "unit": unit, "held": held})
    return m.gap().hint(f"接着挑：{cmd('/团 商店')}；买好了发送 {cmd('/团 整备 好了')}", cmds=[("看货", "/团 商店"), ("好了", "/团 整备 好了")])


def gift_card(sender: str, target: str, what: str, after: int | None, unit: str) -> Msg:
    m = Msg().title(f"🎁 {safe(sender)} 交给 {safe(target)}：{safe(what)}")
    if after is not None:
        m.text(f"{safe(sender)} 现有 {after} {safe(unit)}")
    m.as_segment("economy").with_data({"kind": "gift", "from": sender, "to": target, "what": what, "after": after, "unit": unit})
    return m.gap().hint(f"{safe(target)} 发送 {cmd('/团 背包')} 就能看到", cmds=[("背包", "/团 背包")])


def ledger_card(entries: list[dict[str, Any]], unit: str) -> Msg:
    """The money and items the story itself moved this round."""
    m = Msg().title("📜 故事里的得失")
    m.items([f"**{safe(x['who'])}**　{BT}{safe(x['name'])} {x['delta']:+d}{BT}　{safe(x['reason'])}　"
             + (f"（现有 {x['after']} {safe(unit)}）" if x["kind"] == "money" else f"（现有 ×{x['after']}）") for x in entries])
    m.as_segment("economy").with_data({"kind": "ledger", "entries": entries, "unit": unit})
    return m.gap().hint(f"钱包和物品都在 {cmd('/团 背包')} 里")


def ledger_draft(lines: list[str], removed: str = "") -> Msg:
    m = Msg().title("📜 草稿里的钱物变化", f"{len(lines)} 笔")
    if removed:
        m.text(f"已撤回：{safe(removed)}")
    m.gap().items([f"**{i}.** {safe(line)}" for i, line in enumerate(lines, 1)] or ["没有钱物变化"])
    m.as_segment("economy").with_data({"kind": "ledger_draft", "lines": lines, "removed": removed})
    return m.gap().hint(f"撤回一笔发送 {cmd('/团 主持 记账 撤回 序号')}；确认正文后发送 {cmd('/团 主持 发布')}",
                        cmds=[("撤回", "/团 主持 记账 撤回 序号"), ("发布", "/团 主持 发布")])


def shops_nearby(shops: list[str], place: str) -> Msg:
    """The story walked into a place with shops; the host decides whether to stop for 整备."""
    m = Msg().title("🏪 这里有店", safe(place))
    m.items([f"**{safe(s)}**" for s in shops])
    m.as_segment("economy").with_data({"kind": "shops_nearby", "shops": shops, "place": place})
    return m.gap().hint(f"主持人发送 {cmd('/团 主持 整备')}，让大家私聊采买；不停也行，故事照常继续",
                        note="整备期间回合暂停；玩家私聊 /团 商店 看货", cmds=[("整备", "/团 主持 整备"), ("看货", "/团 商店")])


def wage_card(amount: int, unit: str, rows: list[dict[str, Any]]) -> Msg:
    """Each character's pay at a new act."""
    m = Msg().title(f"💰 新的一幕：每人领到 {amount} {safe(unit)}")
    m.items([f"**{safe(r['name'])}**　现有 {r['after']} {safe(unit)}" for r in rows])
    m.as_segment("economy").with_data({"kind": "wage", "amount": amount, "unit": unit, "rows": rows})
    return m.gap().hint(f"钱包在 {cmd('/团 背包')} 里；遇到有店的地点，主持人可以开整备采买", cmds=[("背包", "/团 背包")])


# ---------------------------------------------------------------- pacing (plays/pacing.py)
def _track_line(label: str, done: int, limit: int, unit: str = "轮") -> str:
    return f"**{label}**　{done}/{limit} {unit}" if limit else f"**{label}**　{done} {unit} · 不催"


def pace_card(v: dict[str, Any], host: bool = False, said: str = "") -> Msg:
    """/团 节奏: how far the scene, the act and the story have run, and what comes next."""
    scene, act, story = v["scene"], v["act"], v["story"]
    m = Msg().title("⏳ 本桌节奏", said or f"{v['source']} · {v['preset']}档" + ("　自动推进已关闭" if v["off"] else ""))
    rows = [_track_line("场景" + (f" · {safe(scene['title'])}" if scene["title"] else ""), scene["done"], scene["limit"]),
            _track_line(act_label(act["number"]) + (f" · {safe(act['title'])}" if act["title"] else ""), act["done"], act["limit"]),
            (f"**全程**　{story['done']}/{story['target']} 轮" + (f"（上限 {story['hard']}）" if story["hard"] else "")
             if story["target"] else f"**全程**　{story['done']} 轮 · 不设篇幅")]
    m.gap().items(rows)
    if v.get("state"):
        m.gap().field(v["state"]["label"], safe(v["state"]["detail"]))
    m.as_segment("pacing").with_data({"kind": "pacing", **v, "host": host, "said": said})
    note = (f"场景满 {scene['limit']} 轮起正文会让局面变化，再过 {v['grace']} 轮世界自己推进；" if scene["limit"] else "") \
        + (f"一幕满 {act['limit']} 轮提议换幕，{v['grace']} 轮后自动进入" if act["limit"] else "")
    if host:
        return m.gap().hint(f"调整：{cmd('/团 主持 节奏 长')}、{cmd('/团 主持 节奏 场景 6')}、{cmd('/团 主持 节奏 延后')}；"
                            f"直接收尾 {cmd('/团 主持 收尾 结局名')}", note=note,
                            cmds=[("放长", "/团 主持 节奏 长"), ("延后", "/团 主持 节奏 延后"), ("收尾", "/团 主持 收尾")])
    stage = v.get("stage") or ""
    if stage == "offer":
        return m.gap().hint(f"正在表决要不要收尾：发送 {cmd('/团 收尾 同意')} 或 {cmd('/团 收尾 再玩')}", note=note,
                            cmds=[("同意", "/团 收尾 同意"), ("再玩", "/团 收尾 再玩")])
    if stage == "epilogue":
        return m.gap().hint(f"终章已经写完：发送 {cmd('/团 尾声 一句话')} 写下你的角色最后的去向", note=note,
                            cmds=[("写尾声", "/团 尾声 一句话")])
    if stage in ("closing", "finale"):
        return m.gap().hint("故事正在收尾：照常行动，把还想交代的事趁这几轮做完", note=note, cmds=[("看回合", "/团 回合")])
    left = story["target"] - story["done"] if story["target"] else 0
    return m.gap().hint("选项里出现“收束”时选它，全桌就会表决要不要收尾"
                        + (f"；再走 {left} 轮到预定篇幅" if left > 0 else ""), note=note, cmds=[("看回合", "/团 回合")])


def act_offer(number: int, title: str, lead: str, grace: int, done: int, core: bool) -> Msg:
    """An act has run its rounds: the next one opens in 'grace' rounds unless the host moves first."""
    head = f"{act_label(number)}" + (f" · {safe(title)}" if title else "")
    m = Msg().title("🎬 本幕将尽", f"这一幕已经走了 {done} 轮，{grace} 轮后进入{head if title or not core else '新的一幕'}")
    if lead:
        m.quote(lead)
    m.text("接下来的正文会把局面慢慢引向下一幕；还有想在这一幕做完的事，抓紧这几轮。")
    m.as_segment("pacing").with_data({"kind": "act_offer", "number": number, "title": title, "lead": lead, "grace": grace,
                                       "done": done, "core": core})
    if core and not title:
        return m.gap().hint(f"主持人发送 {cmd('/团 主持 换幕 标题：引子')} 给新的一幕起名并现在进入；不起名的话 {grace} 轮后由故事自己接下去，"
                            f"{cmd('/团 主持 节奏 延后')} 再留 {grace} 轮",
                            cmds=[("起名换幕", "/团 主持 换幕 标题：引子"), ("延后", "/团 主持 节奏 延后")])
    return m.gap().hint(f"主持人发送 {cmd('/团 主持 换幕')} 现在就进入，{cmd('/团 主持 节奏 延后')} 再留 {grace} 轮",
                        cmds=[("现在换幕", "/团 主持 换幕"), ("延后", "/团 主持 节奏 延后")])


def closing_offer(title: str, reason: str, source: str, yes: list[str], no: list[str], waiting: list[str], need: int,
                  left: int = 3) -> Msg:
    """Whether to wind the story down: a majority of the seated players decides."""
    name = f"「{safe(title)}」" if title else "这个故事"
    m = Msg().title(f"🏁 要给{name}收尾吗", reason)
    m.text("同意过半就进入收尾：再走两轮把线索收拢，然后写终章，每人留一句尾声。再玩过半就继续冒险。"
           f"{left} 轮内没过半，也按继续冒险算。")
    m.gap().field("同意", "、".join(safe(n) for n in yes) or "—").field("再玩", "、".join(safe(n) for n in no) or "—")
    if waiting:
        m.field("还没表态", "、".join(safe(n) for n in waiting))
    m.as_segment("pacing").with_data({"kind": "closing_offer", "title": title, "reason": reason, "source": source, "yes": yes,
                                       "no": no, "waiting": waiting, "need": need, "left": left})
    return m.gap().hint(f"在座的人发送 {cmd('/团 收尾 同意')} 或 {cmd('/团 收尾 再玩')}，{need} 人同意即可；表决期间照常行动",
                        note=f"{need} 人同意就收尾；主持人可以 /团 主持 收尾 直接开始，或 /团 主持 收尾 取消",
                        cmds=[("同意", "/团 收尾 同意"), ("再玩", "/团 收尾 再玩")])


def closing_kept(title: str, voters: list[str], expired: bool = False) -> Msg:
    why = "收尾表决到期，同意的人没过半" if expired else \
        "过半的人想再玩一会儿" + (f"：{'、'.join(safe(v) for v in voters)}" if voters else "")
    m = Msg().title("🧭 继续冒险", why)
    m.text(f"{'「' + safe(title) + '」' if title else '收尾'}先放一放，故事照常继续；过几轮还会再问一次。")
    m.as_segment("pacing").with_data({"kind": "closing_kept", "title": title, "voters": voters, "expired": expired})
    return m.gap().hint(f"想收尾时，主持人可以随时发送 {cmd('/团 主持 收尾')}", cmds=[("节奏", "/团 节奏")])


def closing_start(title: str, rounds: int, forced: bool, reason: str = "") -> Msg:
    m = Msg().title("🌅 进入收尾", (f"结局方向：{safe(title)}" if title else "结局由接下来的故事决定")
                    + (f"　{safe(reason)}" if reason else ""))
    m.items([f"再走 **{rounds} 轮**：不开新的支线，把伏笔、人物关系和未了的事交代清楚",
             "然后 AI 写终章，按已经发生的事给出结局",
             "终章后每人发送 " + cmd("/团 尾声 一句话") + "，写下自己角色的去向"])
    m.as_segment("pacing").with_data({"kind": "closing_start", "title": title, "rounds": rounds, "forced": forced, "reason": reason})
    return m.gap().hint(f"主持人可以 {cmd('/团 主持 收尾 终章')} 立刻写终章，或 {cmd('/团 主持 收尾 取消')} 回到冒险",
                        cmds=[("立刻终章", "/团 主持 收尾 终章"), ("取消", "/团 主持 收尾 取消")])


def world_push(rounds: int, scene: str, actor: str, rush: bool = False) -> Msg:
    m = Msg().title("🌪️ 世界动了一步", f"{safe(scene) + ' · ' if scene else ''}这个场景已经停留 {rounds} 轮")
    m.text("局势不会一直等人：这一轮快团的正文会写进世界自己的变化，大家照常同时行动。" if rush else
           f"局势不会一直等人：AI 正在写一段世界自己的变化，写完后轮到 {safe(actor)} 行动。")
    m.as_segment("pacing").with_data({"kind": "world_push", "rounds": rounds, "scene": scene, "actor": actor, "rush": rush})
    return m.gap().hint(f"主持人想多留几轮，可以发送 {cmd('/团 主持 节奏 长')} 或 {cmd('/团 主持 节奏 场景 6')}",
                        cmds=[("看节奏", "/团 节奏")])


def epilogue_call(title: str, written: list[tuple[str, str]], waiting: list[str], minutes: int, note: str = "") -> Msg:
    m = Msg().title("🕯️ 写下尾声", (f"结局：{safe(title)}　" if title else "") + f"{minutes} 分钟内")
    if note:
        m.quote(note)
    m.text("终章已经写完。每位玩家用一句话写下自己角色最后的去向，全员写完或时间一到，故事落幕。")
    if written:
        m.gap().items([f"**{safe(n)}**　{safe(t)}" for n, t in written])
    if waiting:
        m.gap().field("还在等", "、".join(safe(n) for n in waiting))
    m.as_segment("pacing").with_data({"kind": "epilogue", "title": title, "written": [list(x) for x in written],
                                       "waiting": waiting, "minutes": minutes, "note": note})
    return m.gap().hint(f"发送 {cmd('/团 尾声 一句话')}，例如 {cmd('/团 尾声 她把契约烧了，回到了地表')}；"
                        f"主持人可以 {cmd('/团 完结')} 直接落幕",
                        cmds=[("写尾声", "/团 尾声 一句话"), ("直接落幕", "/团 完结")])
