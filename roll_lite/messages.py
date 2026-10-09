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
NUMERALS = "一二三四五六七八九十"


def act_label(number: int) -> str:
    return f"第{NUMERALS[number - 1]}幕" if 1 <= number <= 10 else f"第 {number} 幕"


def short_title(title: str) -> str:
    return title.split(" · ")[0]


def subtitle(title: str) -> str:
    return title.split(" · ", 1)[1] if " · " in title else ""


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
def world_list(entries: list[dict[str, Any]]) -> Msg:
    m = Msg().title("可开的世界").gap()
    m.items([f"**{i}. {safe(short_title(e['title']))}**　{safe(subtitle(e['title']))}　{BT}{e['players']} 人{BT}"
             for i, e in enumerate(entries, 1)])
    return m.gap().hint(f"管理员发送 {cmd('/团 开启 序号')} 开一桌；更多世界可以在后台“世界 → 世界市场”安装")


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
    return m.hint(f"{cmd('/团 加入')} 入座，然后私聊我 {cmd('/团 职业')}、{cmd('/团 选职业 1 名字')} 建卡（群里发也可以）　{cmd('/团 世界观')} 读设定")


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
    return m


def roster(seated: int, cap: int, rows: list[tuple[str, str, str]]) -> Msg:
    m = Msg().title("阵容", f"{seated}/{cap} 人　{dots(seated, cap)}").gap()
    m.as_segment("room").with_data({"kind": "roster", "seated": seated, "cap": cap, "rows": [list(r) for r in rows]})
    return m.items([f"**{safe(user)}**　{safe(role)}　{state}" for user, role, state in rows] or ["还没有人入座"])


def joined(user: str, seated: int, cap: int) -> Msg:
    m = Msg().title(f"{safe(user)} 已入座", f"{seated}/{cap} 人　{dots(seated, cap)}")
    return m.gap().hint(f"下一步建卡：私聊我发送 {cmd('/团 职业')} 看职业，再发 {cmd('/团 选职业 序号 角色名')}；在群里发也可以。"
                        f"有人设卡的话，角色名写人设的名字就会带上它（{cmd('/团 人设')} 查看）")


def next_steps_after_card(state: str) -> str:
    if state == "lobby":
        return f"角色已就绪。等主持人发送 {cmd('/团 开演')}；随时可以发送 {cmd('/团 背包')} 查看技能和物品。".replace(BT, "")
    return f"角色已就绪，已排进行动顺序。轮到你时会在群里@你；{cmd('/团 背包')} 查看技能和物品。".replace(BT, "")


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
                  meters: list[tuple[str, int, int, int | None]], *, announce: str = "") -> Msg:
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
    if meters:
        m.gap()
        for name, current, maximum, delta in meters:
            m.meter(name, current, maximum, delta)
    if receipt.get("exhausted"):
        m.text("**" + "、".join(receipt["exhausted"]) + "已耗尽**")
    return m.as_segment("status")


def narration(text: str, scene_title: str = "", act_heading: str = "") -> Msg:
    m = Msg()
    if act_heading:
        m.heading(act_heading)
    if scene_title:
        m.caption(scene_title)
    return m.para(text).as_segment("narration")


def turn_prompt(actor: str, user_name: str, user_id: str, round_number: int, choices: list[dict[str, str]],
                mode: str, minutes: int | None, loadout: list[str] | None = None) -> Msg:
    meta = f"第 {round_number} 轮" + (f"　限时 {minutes} 分钟" if minutes else "")
    m = Msg().mention(user_id, user_name).title(f"▸ 轮到 {actor}", meta)
    if choices and mode != "dialogue_only":
        m.gap().choices(choices)
    if loadout:
        m.gap().field("可准备", "　".join(loadout[:5]) + ("　…" if len(loadout) > 5 else ""))
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
    return m.as_segment("choices")


def host_line(text: str) -> Msg:
    return Msg().caption("主持人").para(text)


def adjustments_applied(lines: list[str]) -> Msg:
    return Msg().title("主持人调整生效").gap().items([safe(line) for line in lines]).as_segment("status")


# ---------------------------------------------------------------- skills and items
def loadout_card(name: str, entries: list[dict[str, Any]], resources: list[tuple[str, int, int]], *, own: bool) -> Msg:
    m = Msg().title(f"{safe(name)}的技能与物品")
    if resources:
        m.gap()
        for label, current, maximum in resources:
            m.meter(label, current, maximum)
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
    m.as_segment("sheet").with_data({"kind": "loadout", "name": name, "entries": shown,
                                     "resources": [list(r) for r in resources], "own": own})
    if not entries:
        m.gap().text("没有技能或物品。")
    if own:
        m.gap().hint(f"检定时在行动后写 {cmd('[用 名称]')} 加成，例如 {cmd('/团 选 A [用 手电筒]')}；"
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
    m = Msg().heading(f"{kind} · {title}")
    if premise:
        m.para(premise)
    items = []
    for o in options:
        tag = "　".join(t for t in (f"风险：{o['risk']}" if o.get("risk") else "", f"代价：{o['cost']}" if o.get("cost") else "") if t)
        items.append({"label": o["key"], "text": o["label"] + (f"——{o['description']}" if o.get("description") else ""), "tag": tag})
    m.gap().choices(items)
    m.with_data({"kind": "vote_open", "ballots": ballots, "voters": voters, "minutes": minutes})
    return m.gap().hint(f"{cmd('/团 投 A')}　已投 {ballots}/{voters}　{minutes} 分钟后截止",
                        note=f"已投 {ballots}/{voters}，{minutes} 分钟后截止。", cmds=[("投票", "/团 投 A")]).as_segment("choices")


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
    return m.gap().hint(stats + f"　主持人发送 {cmd('/团 关闭')} 收桌")


def help_index(topics: list[str]) -> Msg:
    m = Msg().title("321Roll Lite", "群聊文字跑团").gap()
    m.caption("一局怎么玩")
    m.items([f"在群里发送 {cmd('/团 加入')} 入座",
             f"私聊我发送 {cmd('/团 职业')} 看职业，{cmd('/团 选职业 序号 角色名')} 建卡（群里发也可以）",
             f"主持人发送 {cmd('/团 开演')}；轮到你时选 {cmd('/团 选 A')} 或写 {cmd('/团 行动 你的做法')}",
             f"检定时在句末写 {cmd('[用 名称]')} 带上技能或物品；{cmd('/团 背包')} 看持有的技能和物品",
             f"线索、交涉、对抗、计划等玩法随时可用，回执里会写下一步怎么做"])
    m.gap().caption("私聊里也能用")
    m.text(f"建卡、{cmd('/团 角色')}、{cmd('/团 背包')}、{cmd('/团 使用')}、{cmd('/团 人物')}、{cmd('/团 状态')}、{cmd('/团 回顾')}、"
           f"{cmd('/团 记录')}；在私聊里行动或使用玩法，结果会发到群里")
    m.gap().caption("带上自己的角色")
    m.text(f"私聊我 {cmd('/团 人设 导入')} 导入酒馆角色卡，或 {cmd('/团 人设 新建 名字')} 手写；建卡时 {cmd('/团 选职业 序号 人设名')} 带上，"
           f"{cmd('/团 人设 融入')} 让 AI 写出你在这个世界里的身份")
    m.gap().caption("每天一次")
    m.text(f"{cmd('/团 一掷')} 掷出今天的 d20 和宜忌，{cmd('/团 一掷 全群')} 看本群今日榜")
    return m.gap().hint(f"{cmd('/团 帮助 分类')} 查看详细指令，分类：" + "、".join(topics))


def help_topic(topic: str, rows: list[tuple[str, str]]) -> Msg:
    return Msg().title("帮助", topic).gap().items([f"{BT}{usage}{BT}　{summary}" for usage, summary in rows])


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
