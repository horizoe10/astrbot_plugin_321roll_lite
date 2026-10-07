"""Seat governance for the host: handing over, removing and re-admitting players, presence on a
player's behalf, the seating lock, character resets, turn order and adjustments queued from chat.

Every command needs the host or an admin.  Seat changes take effect at once; numbers, items and
attitudes go through adjust.queue and apply after the next narration, like the WebUI adjustments.
"""
from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING, Any

from .. import adjust, loadout, messages, shared
from ..commands import Caller, Reply, UserError
from ..render import Msg
from ..storage import loads, now
from . import lifecycle

if TYPE_CHECKING:
    from ..app import LiteApp

LIVE = ("lobby", "running", "paused")
_NUMBER = re.compile(r"^[+＋\-−－]?\d{1,4}$")


def _host_room(app: "LiteApp", caller: Caller, *states: str) -> sqlite3.Row:
    room = shared.require_room(app, caller, *(states or LIVE))
    shared.require_host(app, caller, room)
    return room


def _number(text: str) -> int:
    return int(text.replace("＋", "+").replace("−", "-").replace("－", "-"))


def _host_label(c: sqlite3.Connection, room: sqlite3.Row) -> str:
    actor = c.execute("SELECT * FROM actors WHERE room_id=? AND user_id=?", (room["id"], room["host_user_id"])).fetchone()
    return shared.actor_label(actor) if actor is not None else room["host_user_id"]


def _transfer(app: "LiteApp", c: sqlite3.Connection, room: sqlite3.Row, target: sqlite3.Row, by: str) -> None:
    c.execute("UPDATE rooms SET host_user_id=? WHERE id=?", (target["user_id"], room["id"]))
    shared.set_table_data(c, room["id"], handover=None)
    app.store.add_event(c, room["id"], "system", f"主持人改为 {target['user_name']}", actor_id=target["id"])
    app.store.audit(c, by, "room.host_transfer", room["id"], {"from": room["host_user_id"], "to": target["user_id"]})
    app.store.bump_room(c, room["id"])


def _new_host_card(target: sqlite3.Row) -> Msg:
    return (Msg().mention(target["user_id"], target["user_name"]).title(f"{target['user_name']} 接任主持人")
            .text("开演、暂停、换幕、存读档和所有 /团 主持 指令都由新的主持人负责。")
            .gap().hint("发送 /团 帮助 主持 查看主持指令"))


# ---------------------------------------------------------------- host seat
async def handover(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller, *LIVE, "ended")
    offer = shared.table_data(room).get("handover")
    if args.strip() == "取消":
        if not offer:
            raise UserError("现在没有待接受的交棒。")
        with app.store.tx() as c:
            shared.set_table_data(c, room["id"], handover=None)
            app.store.add_event(c, room["id"], "system", f"取消了交给 {offer['name']} 的主持人邀请")
        return Reply().say(messages.notice("已取消交棒", f"{offer['name']} 不会接任主持人。"))
    token, _ = shared.split_target(args, caller)
    if not token and not caller.mentions:
        with app.store.read() as c:
            current = _host_label(c, room)
        detail = f"现任主持人：{current}。" + (f"正在等 {offer['name']} 回应。" if offer else "")
        return Reply().say(messages.notice("交棒", detail, "发送 /团 主持 交棒 角色名（或 @对方），对方发送 /团 接棒 后生效；/团 主持 交棒 取消 撤回"))
    with app.store.tx() as c:
        target = shared.find_actor(c, room["id"], token, caller.mentions)
        if target["user_id"] == room["host_user_id"]:
            raise UserError(f"{target['user_name']} 已经是主持人。")
        if caller.is_admin:
            _transfer(app, c, room, target, caller.user_id)
        else:
            shared.set_table_data(c, room["id"], handover={"to": target["user_id"], "name": target["user_name"],
                                                          "by": caller.user_id, "at": now()})
            app.store.add_event(c, room["id"], "system", f"{caller.user_name} 邀请 {target['user_name']} 接任主持人")
    if caller.is_admin:
        return Reply().say(_new_host_card(target))
    return Reply().say(Msg().mention(target["user_id"], target["user_name"])
                       .title(f"{caller.user_name} 想把主持人交给 {target['user_name']}")
                       .text("接任后由你负责开演、暂停、换幕、存读档和所有主持指令。")
                       .gap().hint("发送 /团 接棒 接任，或 /团 拒绝接棒 婉拒"))


async def accept_host(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, *LIVE, "ended")
    offer = shared.table_data(room).get("handover")
    if not offer or offer["to"] != caller.user_id:
        raise UserError("没有交给你的主持人邀请。")
    with app.store.tx() as c:
        target = c.execute("SELECT * FROM actors WHERE room_id=? AND user_id=? AND presence<>'left'",
                           (room["id"], caller.user_id)).fetchone()
        if target is None:
            shared.set_table_data(c, room["id"], handover=None)
            raise UserError("你已经不在这一桌，邀请作废。")
        _transfer(app, c, room, target, caller.user_id)
    return Reply().say(_new_host_card(target))


async def decline_host(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = shared.require_room(app, caller, *LIVE, "ended")
    offer = shared.table_data(room).get("handover")
    if not offer or offer["to"] != caller.user_id:
        raise UserError("没有交给你的主持人邀请。")
    with app.store.tx() as c:
        shared.set_table_data(c, room["id"], handover=None)
        app.store.add_event(c, room["id"], "system", f"{caller.user_name} 婉拒了主持人邀请")
    return Reply().say(messages.notice(f"{caller.user_name} 婉拒了接任主持人", "主持人不变。"))


# ---------------------------------------------------------------- seats
async def remove(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller)
    token, reason = shared.split_target(args, caller)
    with app.store.tx() as c:
        target = shared.find_actor(c, room["id"], token, caller.mentions)
        if target["user_id"] == room["host_user_id"]:
            raise UserError("不能移出主持人。先用 /团 主持 交棒 把主持人交给别人。")
        label = shared.actor_label(target)
        c.execute("UPDATE actors SET presence='left',revision=revision+1,updated_at=? WHERE id=?", (now(), target["id"]))
        removed = [e for e in shared.table_data(room).get("removed", []) if e["user_id"] != target["user_id"]]
        removed.append({"user_id": target["user_id"], "name": target["user_name"], "label": label, "at": now()})
        shared.set_table_data(c, room["id"], removed=removed[-50:])
        app.store.add_event(c, room["id"], "system", f"主持人请 {label} 离开了这一桌" + (f"：{reason[:100]}" if reason else ""),
                            actor_id=target["id"])
        app.store.audit(c, caller.user_id, "room.remove_player", room["id"], {"user": target["user_id"], "reason": reason[:100]})
        app.store.bump_room(c, room["id"])
    reply = Reply().say(messages.notice(f"{label}（{target['user_name']}）已被请离这一桌",
                                         (f"原因：{reason[:100]}。" if reason else "") + "角色和记录保留在这一桌。",
                                         "需要让对方回来时，主持人发送 /团 主持 放行 " + target["user_name"]))
    if room["state"] in ("running", "paused"):
        reply.extend(await app.hooks.emit("roster_changed", room_id=room["id"], actor_id=target["id"], change="left"))
    return reply


async def readmit(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller)
    removed = shared.table_data(room).get("removed", [])
    token = args.strip().lstrip("@＠")
    if not token and not caller.mentions:
        if not removed:
            return Reply().say(messages.notice("没有被请离的玩家"))
        return Reply().say(Msg().title("被请离的玩家", f"{len(removed)} 位").gap()
                           .items([f"**{e['name']}**　{e['label']}" for e in removed])
                           .gap().hint("发送 /团 主持 放行 昵称 让对方可以再次 /团 加入"))
    entry = next((e for e in removed if e["user_id"] in caller.mentions or token in (e["user_id"], e["name"], e["label"])), None)
    if entry is None:
        raise UserError("被请离的名单里没有这位。发送 /团 主持 放行 查看名单。")
    with app.store.tx() as c:
        shared.set_table_data(c, room["id"], removed=[e for e in removed if e["user_id"] != entry["user_id"]])
        app.store.add_event(c, room["id"], "system", f"主持人放行了 {entry['name']}")
    return Reply().say(messages.notice(f"已放行 {entry['name']}", "对方可以再次入座。", f"{entry['name']} 发送 /团 加入 回到这一桌"))


async def _presence(app: "LiteApp", caller: Caller, args: str, presence: str) -> Reply:
    room = _host_room(app, caller)
    token, _ = shared.split_target(args, caller)
    with app.store.read() as c:
        target = shared.find_actor(c, room["id"], token, caller.mentions)
    return await lifecycle.change_presence(app, room, target, presence, by=caller.user_name)


async def host_away(app: "LiteApp", caller: Caller, args: str) -> Reply:
    return await _presence(app, caller, args, "away")


async def host_back(app: "LiteApp", caller: Caller, args: str) -> Reply:
    return await _presence(app, caller, args, "present")


async def seating(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller)
    text = args.strip()
    locked = bool(shared.table_data(room).get("seating_locked"))
    if not text:
        return Reply().say(messages.notice("入座：" + ("已关闭" if locked else "开放中"),
                                           "关闭后新玩家不能 /团 加入，已入座的人不受影响。",
                                           "发送 /团 主持 入座 关 或 /团 主持 入座 开"))
    if text not in ("关", "关闭", "开", "开放", "打开"):
        raise UserError("写法：/团 主持 入座 关 或 /团 主持 入座 开")
    lock = text in ("关", "关闭")
    with app.store.tx() as c:
        shared.set_table_data(c, room["id"], seating_locked=lock)
        app.store.add_event(c, room["id"], "system", f"主持人{'关闭' if lock else '开放'}了入座")
    return Reply().say(messages.notice("入座已关闭" if lock else "入座已开放",
                                       "新玩家暂时不能加入，已入座的人照常游玩。" if lock else "其他人可以发送 /团 加入 入座。"))


async def rebuild(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller)
    token, reason = shared.split_target(args, caller)
    with app.store.tx() as c:
        target = shared.find_actor(c, room["id"], token, caller.mentions)
        if not target["archetype_id"]:
            raise UserError(f"{target['user_name']} 还没有建卡。")
        label = shared.actor_label(target)
        c.execute("UPDATE actors SET name='',archetype_id='',attributes_json='{}',resources_json='{}',items_json='{}',"
                  "skills_json='{}',traits_json='[]',ready=0,revision=revision+1,updated_at=? WHERE id=?", (now(), target["id"]))
        app.store.add_event(c, room["id"], "system", f"主持人请 {target['user_name']} 重新建卡（原角色「{label}」）"
                            + (f"：{reason[:100]}" if reason else ""), actor_id=target["id"])
        app.store.bump_room(c, room["id"])
    card = (Msg().mention(target["user_id"], target["user_name"]).title(f"主持人请 {target['user_name']} 重新建卡")
            .text(f"原角色「{label}」已收回。" + (f"原因：{reason[:100]}。" if reason else "")))
    card.gap().hint("私聊我发送 /团 职业 查看职业，再发 /团 选职业 序号 角色名" +
                    ("；建好后会排回行动顺序" if room["state"] != "lobby" else ""))
    reply = Reply().say(card)
    if room["state"] in ("running", "paused"):
        reply.extend(await app.hooks.emit("roster_changed", room_id=room["id"], actor_id=target["id"], change="rebuild"))
    return reply


async def reorder(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller)
    tokens = args.split()
    with app.store.tx() as c:
        rows = c.execute("SELECT * FROM actors WHERE room_id=? AND presence<>'left' ORDER BY order_index,created_at",
                         (room["id"],)).fetchall()
        if tokens or caller.mentions:
            chosen: list[sqlite3.Row] = []
            for found in [shared.find_actor(c, room["id"], "", (user,)) for user in caller.mentions] + \
                         [shared.find_actor(c, room["id"], token) for token in tokens]:
                if found["id"] not in {a["id"] for a in chosen}:
                    chosen.append(found)
            rows = chosen + [a for a in rows if a["id"] not in {x["id"] for x in chosen}]
            for index, actor in enumerate(rows, 1):
                c.execute("UPDATE actors SET order_index=?,updated_at=? WHERE id=?", (index, now(), actor["id"]))
            app.store.add_event(c, room["id"], "system", "主持人调整了行动顺序：" + " → ".join(shared.actor_label(a) for a in rows))
            app.store.bump_room(c, room["id"])
    title = "行动顺序已调整" if tokens or caller.mentions else "行动顺序"
    lines = [f"**{i}. {shared.actor_label(a)}**　{a['user_name']}" + ("　暂离" if a["presence"] == "away" else "")
             + ("" if a["archetype_id"] else "　未建卡") for i, a in enumerate(rows, 1)]
    hint = ("当前回合不变，之后按新顺序轮流。" if tokens or caller.mentions else
            "发送 /团 主持 顺序 角色一 角色二 …… 调整；没写到的人按原顺序排在后面")
    return Reply().say(Msg().title(title).gap().items(lines).gap().hint(hint))


# ---------------------------------------------------------------- adjustments from chat
def _by_name(definitions: dict[str, Any], name: str, kind: str) -> str:
    for ref, value in definitions.items():
        if name in (ref, value if isinstance(value, str) else value["name"]):
            return ref
    raise UserError(f"这个世界里没有{kind}“{name}”。")


def _parse_adjust(c: sqlite3.Connection, room: sqlite3.Row, caller: Caller, args: str) -> dict[str, Any]:
    words = args.split()
    usage = ("写法：/团 主持 调整 角色 资源名 ±数量｜角色 物品 名称 ±数量｜角色 技能 名称 习得/失去｜"
             "角色 次数 名称 剩余次数｜态度 人物 档位（" + "/".join(adjust.STANDING) + " 或 -3…3）")
    if words and words[0] == "态度":
        if len(words) < 3:
            raise UserError(usage)
        subject, level = " ".join(words[1:-1]), words[-1]
        standing = adjust.STANDING.index(level) - 3 if level in adjust.STANDING else (_number(level) if _NUMBER.match(level) else None)
        if standing is None or not -3 <= standing <= 3:
            raise UserError(usage)
        kinds = {loads(r["document_json"])["subject"]: loads(r["document_json"])["subject_kind"]
                 for r in c.execute("SELECT document_json FROM records WHERE room_id=? AND kind='relation'", (room["id"],))}
        return {"kind": "attitude", "subject": subject, "subject_kind": kinds.get(subject, "npc"), "standing": standing}
    token, rest = shared.split_target(args, caller)
    target = shared.find_actor(c, room["id"], token, caller.mentions)
    words = rest.split()
    skills, items, resources, _ = loadout.definitions(room)
    if len(words) == 3 and words[0] == "物品" and _NUMBER.match(words[2]):
        return {"kind": "item", "actor": target["id"], "ref": _by_name(items, words[1], "物品"), "delta": _number(words[2])}
    if len(words) == 3 and words[0] == "技能" and words[2] in ("习得", "获得", "失去", "收回"):
        return {"kind": "skill", "actor": target["id"], "ref": _by_name(skills, words[1], "技能"), "grant": words[2] in ("习得", "获得")}
    if len(words) == 3 and words[0] == "次数" and words[2].isdigit():
        entry = "skill" if any(words[1] in (r, d["name"]) for r, d in skills.items()) else "item"
        ref = _by_name(skills if entry == "skill" else items, words[1], "技能或物品")
        return {"kind": "uses", "actor": target["id"], "entry": entry, "ref": ref, "value": int(words[2])}
    if len(words) == 2 and _NUMBER.match(words[1]):
        return {"kind": "resource", "actor": target["id"], "ref": _by_name(resources, words[0], "资源"), "delta": _number(words[1])}
    raise UserError(usage)


async def queue_adjustment(app: "LiteApp", caller: Caller, args: str) -> Reply:
    room = _host_room(app, caller)
    text = args.strip()
    with app.store.read() as c:
        names = {a["id"]: shared.actor_label(a) for a in c.execute("SELECT * FROM actors WHERE room_id=?", (room["id"],))}
    waiting = adjust.pending(room)
    if not text:
        if not waiting:
            return Reply().say(messages.notice("没有待生效的调整", "调整会在下一回合正文写完后生效并在群里公布。",
                                               "发送 /团 主持 调整 林晓 体力 -2 之类的写法加入；私聊我发也可以，不会剧透"))
        lines = [f"**{i}.** " + "；".join(adjust.describe(room, ch, names) for ch in a["changes"]) for i, a in enumerate(waiting, 1)]
        return Reply().say(Msg().title("待生效的调整", f"{len(waiting)} 项").gap().items(lines)
                           .gap().hint("下一回合正文写完后生效；发送 /团 主持 调整 撤销 序号 取消一项"))
    if text.split()[0] == "撤销":
        rest = text.split()[1:]
        if not waiting:
            raise UserError("没有可以撤销的调整。")
        index = int(rest[0]) if rest and rest[0].isdigit() else len(waiting)
        if not 1 <= index <= len(waiting):
            raise UserError(f"序号写 1–{len(waiting)}。")
        item = waiting[index - 1]
        with app.store.tx() as c:
            adjust.cancel(c, c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone(), item["id"])
            app.store.audit(c, caller.user_id, "room.adjust_cancel", room["id"], {"adjustment": item["id"]})
        return Reply().say(messages.notice("已撤销调整", "；".join(adjust.describe(room, ch, names) for ch in item["changes"])))
    try:
        with app.store.tx() as c:
            change = _parse_adjust(c, room, caller, text)
            item = adjust.queue(c, c.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone(), [change], caller.user_id)
            app.store.audit(c, caller.user_id, "room.adjust", room["id"], {"changes": item["changes"]})
    except adjust.AdjustInvalid as exc:
        raise UserError(str(exc)) from exc
    return Reply().say(messages.notice("已加入待生效：" + adjust.describe(room, item["changes"][0], names),
                                       "下一回合正文写完后生效，并在群里公布。",
                                       "发送 /团 主持 调整 查看待生效的调整，/团 主持 调整 撤销 取消最近一项"))


def install(app: "LiteApp") -> None:
    r = app.router
    r.register("主持 交棒", handover, summary="把主持人交给同桌的另一位", usage="/团 主持 交棒 <角色|@对方|取消>", topic="主持")
    r.register("接棒", accept_host, summary="接受主持人邀请", topic="主持", private="room")
    r.register("拒绝接棒", decline_host, summary="婉拒主持人邀请", topic="主持", private="room")
    r.register("主持 移出", remove, summary="请一位玩家离开这一桌", usage="/团 主持 移出 <角色|@对方> [原因]", topic="主持")
    r.register("主持 放行", readmit, summary="允许被请离的玩家再次入座", usage="/团 主持 放行 [昵称]", topic="主持")
    r.register("主持 暂离", host_away, summary="让挂机的玩家暂离", usage="/团 主持 暂离 <角色|@对方>", topic="主持")
    r.register("主持 返回", host_back, summary="让暂离的玩家回到队列", usage="/团 主持 返回 <角色|@对方>", topic="主持")
    r.register("主持 入座", seating, summary="关闭或开放入座", usage="/团 主持 入座 [关|开]", topic="主持")
    r.register("主持 退回", rebuild, summary="请一位玩家重新建卡", usage="/团 主持 退回 <角色|@对方> [原因]", topic="主持")
    r.register("主持 顺序", reorder, summary="查看或调整行动顺序", usage="/团 主持 顺序 [角色一 角色二 …]", topic="主持")
    r.register("主持 调整", queue_adjustment, summary="调整资源、物品、技能、次数或人物态度（下一回合生效）",
               usage="/团 主持 调整 <角色> <资源> <±n>｜撤销 [序号]", topic="主持", private="self")
