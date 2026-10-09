"""Engine plays: intake, platform dice and commits for the custom-play catalog.

The engine (story_engine.custom_plays) validates an action against the room's
records and proposes record operations per outcome branch; Lite rolls the
dice, picks the branch and commits it under revision checks.  Only the actions
listed in ALLOWED are accepted.
"""
from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING, Any

from .. import messages, shared
from ..commands import Caller, Reply, UserError, parse_check, parse_refs, split_title
from ..dice import d20, roll_check
from ..engine.gateway import CustomPlayError
from ..features import BY_KEY
from ..fun import luck
from ..render import BT, Msg, dots
from ..storage import dumps, loads, new_id, now
from . import hosted

if TYPE_CHECKING:
    from ..app import LiteApp

ALLOWED: dict[str, frozenset[str]] = {
    "playInvestigation": frozenset({"note_clue", "search", "propose_hypothesis", "weigh", "conclude", "cite_fact", "withdraw_hypothesis"}),
    "playTestimony": frozenset({"record_testimony", "press", "present", "compare_statement"}),
    "playNegotiation": frozenset({"open_talks", "argue_terms", "propose_term", "sign_term", "settle_talks", "walk_away"}),
    "playRelations": frozenset({"appeal", "remember", "set_goal", "resolve_goal"}),
    "playCalendar": frozenset({"spend_time", "set_deadline", "meet_deadline"}),
    "playProjects": frozenset({"start_project", "work_project", "rest"}),
    "playConflict": frozenset({"open_conflict", "exchange", "concede", "join_contest", "maneuver",
                               }),
    "playChase": frozenset({"open_chase", "exchange", "concede", "join_contest"}),
    "playDebate": frozenset({"open_debate", "exchange", "concede", "join_contest", "maneuver"}),
    "playPlans": frozenset({"draft_plan", "claim_step", "confirm_plan", "execute_step", "evacuate"}),
    "playOracle": frozenset({"ask_oracle"}),
    "playTransformation": frozenset({"propose_change", "confirm_change", "decline_change", "withdraw_change"}),
    "playFortune": frozenset({"draw_fortune", "settle_fortune"}),
    "playBranchEndings": frozenset({"propose_branch", "vote_branch", "enter_ending", "write_epilogue", "conclude_ending"}),
}
HOST_ACTIONS: frozenset[tuple[str, str]] = frozenset()
# A closed play still lets records already under way finish (from 321Roll WIND_DOWN).
WIND_DOWN = {
    "playNegotiation": {"walk_away", "settle_talks"}, "playCalendar": {"meet_deadline"},
    "playConflict": {"concede"}, "playChase": {"concede"}, "playDebate": {"concede"},
    "playPlans": {"evacuate"}, "playTransformation": {"confirm_change", "decline_change", "withdraw_change"},
    "playFortune": {"settle_fortune"}, "playBranchEndings": {"write_epilogue", "conclude_ending"},
}
LITE_OPS = frozenset({"create", "update", "resources", "harm", "complete_room"})
CONTEST_PLAYS = {"conflict": "playConflict", "chase": "playChase", "debate": "playDebate"}

KIND_LABELS = {"clue": "线索", "hypothesis": "假设", "testimony": "证词", "negotiation": "交涉", "relation": "关系",
               "companion_goal": "同伴目标", "calendar": "日历", "deadline": "期限", "project": "项目", "contest": "对抗",
               "joint": "险关", "plan": "计划", "oracle": "神谕", "oracle_table": "神谕表", "transformation": "转变",
               "fortune": "机运", "branch": "结局分支", "ending": "结局", "source_fact": "公开设定"}
STATE_LABELS = {"open": "未定", "contested": "有争议", "supported": "有支持", "refuted": "被反驳", "accepted": "已采纳",
                "rejected": "已否定", "withdrawn": "已撤回", "engaged": "进行中", "won": "胜", "lost": "败", "drawn": "平局",
                "conceded": "已收尾", "forming": "集结中", "holding": "坚守中", "cleared": "已过关", "overrun": "失守",
                "bargaining": "交涉中", "agreed": "已达成", "walked_away": "已中止", "active": "进行中", "complete": "已完成",
                "pending": "未到期", "met": "已完成", "expired": "已过期", "running": "运行中", "drafted": "拟定中",
                "confirmed": "已确认", "underway": "执行中", "partial": "部分完成", "completed": "已完成",
                "compromised": "受挫", "evacuated": "已撤离", "suggestion": "建议", "frozen": "待兑现", "settled": "已兑现",
                "proposed": "待支持", "chosen": "已选定", "set_aside": "搁置", "entered": "已进入", "concluded": "已完结",
                "awaiting_target": "待本人确认", "awaiting_heir": "待继承者确认", "declined": "已拒绝", "fulfilled": "已实现",
                "abandoned": "已放弃", "recorded": "已记录"}
STATE_LABELS.update({"draft": "拟定中", "standing": "站得住", "contradicted": "被推翻", "broken_off": "已中止", "choosing": "选择中",
                     "cancelled": "已取消", "closed": "已关闭", "failed": "失败", "established": "已确立", "spent": "已用",
                     "shaken": "已动摇"})
REASONS = {
    "input_invalid": "填写内容不完整或超出范围。", "attribute_invalid": "属性不属于本世界。", "difficulty_invalid": "难度无效。",
    "actor_invalid": "所选角色不在当前在场成员中。", "record_missing": "所选记录不存在。", "state_invalid": "所选记录当前阶段不支持这项操作。",
    "already_linked": "这条线索已经关联到该假设。", "evidence_required": "出示需要搜查所得的证据或亲眼所见的线索。",
    "limit_reached": "数量已达上限。", "already_signed": "你已经做过这一步了。", "leverage_insufficient": "筹码不足，暂不能达成协议。",
    "terms_unsigned": "还没有已签署的条款。", "time_past": "所选时间已经过去。", "rest_unavailable": "本世界没有安全休整。",
    "procedure_mismatch": "所选记录不属于这个玩法。", "already_claimed": "该步骤已有人认领。", "steps_unclaimed": "全部步骤认领后才能确认计划。",
    "step_not_yours": "只能执行本人认领的步骤。", "heir_required": "传承需要另一名在场角色作为继承者。",
    "confirmation_not_yours": "只有被指名的角色本人可以确认或拒绝。", "not_proposer": "只有提出者本人可以撤回。",
    "not_member": "你不在这项记录的成员里。", "not_owner": "只有抽到这份机运的人可以兑现。", "ending_entered": "结局已经进入，不再接受新的分支。",
    "already_voted": "你已经支持了这个分支。", "votes_incomplete": "全体在场角色支持同一分支后才能进入结局。",
    "already_written": "你已经写下尾声。", "epilogues_incomplete": "全体成员写下尾声后才能完结。",
    "joint_active": "桌上已有一道险关还没收尾。", "harm_unavailable": "本世界没有失败伤势，不能立险关。",
    "cost_required": "险关失守必须设下伤势。", "already_joined": "你已经守着一路了。", "joint_full": "这道险关的人数已满。",
    "front_needed": "剩下的位子要留给还没有人守的那一路。", "not_joined": "只有认领了一路的人才能为它掷骰。",
    "already_rolled": "你已经为这道险关掷过骰了。", "front_empty": "两路都至少要有一人认领，才能开始掷骰。",
    "attribute_off_front": "这一路只能用发起时列出的属性。", "not_initiator": "只有发起人可以收尾。",
    "preparation_required": "“稳妥”出手要先取得有利位置，Lite 没有开放这一步。直接写 /团 交锋 #编号 行动，或者用“孤注”。",
    "progress_insufficient": "至少完成一半进度后才能提前结算。", "action_unknown": "这个玩法没有这项操作。",
    "rules_invalid": "房间规则无法用于该玩法。", "request_invalid": "提交内容不符合玩法合同。",
}


# ---------------------------------------------------------------- records
def record_title(document: dict[str, Any]) -> str:
    for key in ("title", "topic", "subject", "question", "stake", "speaker", "counterpart", "opponent", "quarry", "companion"):
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:40]
    return ""


def record_seqs(app: "LiteApp", room_id: str) -> dict[str, int]:
    """Record id → sequence number, so lines can name the records they point at."""
    with app.store.read() as c:
        return {r["id"]: r["seq"] for r in c.execute("SELECT id, seq FROM records WHERE room_id=?", (room_id,))}


def record_line(row: sqlite3.Row | dict[str, Any], seqs: dict[str, int] | None = None) -> str:
    """One record as template text (bold sequence number, inline progress). seqs lets a hypothesis name its clues."""
    document = loads(row["document_json"]) if "document_json" in row.keys() else row["document"]  # type: ignore[union-attr]
    kind = row["kind"]
    visual = ""
    if kind == "contest":
        visual = f"我方 **{document.get('ours', 0)}** : **{document.get('theirs', 0)}** 对方"
        if document.get("procedure") == "chase":
            visual += f"　距离 {document.get('gap', document.get('distance'))}"
    elif kind == "project":
        progress, segments = int(document.get("progress", 0) or 0), int(document.get("segments", 0) or 0)
        visual = f"{BT}{dots(progress, segments, '■', '□')}{BT} {progress}/{segments}"
    elif kind == "relation":
        visual = str(document.get("tier", ""))
    elif kind in ("oracle", "fortune"):
        visual = str(document.get("answer_label") or document.get("tier_label") or "")
    elif kind == "joint":
        joined, size = len(document.get("roster", [])), int(document.get("size", 0) or 0)
        visual = f"{BT}{dots(joined, size)}{BT} {joined}/{size} 人"
    elif kind == "branch":
        visual = f"{len(document.get('votes', []))} 人支持"
    elif kind == "hypothesis" and seqs:
        links = [label + " " + " ".join(f"**#{seqs[i['clue_ref']]}**" for i in items if i.get("clue_ref") in seqs)
                 for label, items in (("支持", document.get("support") or []), ("反驳", document.get("refute") or []))]
        visual = " · ".join(link for link in links if "#" in link)
    return messages.record_line(row["seq"], KIND_LABELS.get(kind, kind), record_title(document),
                                STATE_LABELS.get(row["state"], row["state"]), visual)


def lite_summary(action: str, value: dict[str, Any], current: dict[str, dict[str, Any]], proposal: dict[str, Any]) -> str:
    """Receipt line for actions whose engine summary states a rule instead of what happened."""
    def title(key: str) -> str:
        record = current.get(value.get(key, ""))
        return record_title(record["document"]) if record else ""
    lines = {
        "withdraw_hypothesis": lambda: f"撤回假设「{title('hypothesis_ref')}」",
        "compare_statement": lambda: f"对照「{title('testimony_ref')}」和「{title('other_testimony_ref')}」的证词：{value.get('text', '')}",
        "propose_term": lambda: f"提出条款：{value.get('text', '')}",
        "sign_term": lambda: f"签署第 {value.get('term_id')} 条条款",
        "resolve_goal": lambda: ("实现了" if value.get("result") == "fulfilled" else "放弃了") + f"{title('goal_ref')}的同伴目标",
        "join_contest": lambda: f"加入对抗「{title('contest_ref')}」",
        "concede": lambda: f"退出对抗「{title('contest_ref')}」",
        "maneuver": lambda: ("孤注一掷" if value.get("position") == "desperate" else "冒险出手") + f"：{value.get('text', '')}",
        "exchange": lambda: f"在「{title('contest_ref')}」中出手：{value.get('text', '')}",
        "evacuate": lambda: f"退出计划「{title('plan_ref')}」",
        "execute_step": lambda: f"执行计划「{title('plan_ref')}」第 {value.get('step')} 步",
        "settle_fortune": lambda: f"兑现机运「{title('fortune_ref')}」：{value.get('use', '')}",
        "confirm_change": lambda: f"接受转变「{title('transformation_ref')}」",
        "decline_change": lambda: f"拒绝转变「{title('transformation_ref')}」",
        "withdraw_change": lambda: f"撤回转变「{title('transformation_ref')}」",
        "write_epilogue": lambda: f"写下尾声：{value.get('text', '')}",
    }
    return lines[action]() if action in lines else proposal["summary"]


LABELS = {"maneuver": "出手", "exchange": "出手"}


def waiting_on(c: sqlite3.Connection, row: sqlite3.Row, members: list[str]) -> str:
    """'还没表态：…' for a proposed branch, '还没写尾声：…' for an entered ending."""
    document = loads(row["document_json"])
    if row["kind"] == "branch" and row["state"] == "proposed":
        voted = {item["actor_ref"] for item in document.get("votes", [])}
        missing, lead = [m for m in members if m not in voted], "还没表态"
    elif row["kind"] == "ending" and row["state"] == "entered":
        done = {e["actor_ref"] for e in document.get("epilogues", [])}
        missing, lead = [m for m in document.get("members", []) if m not in done], "还没写尾声"
    else:
        return ""
    names = [shared.actor_label(a) for a in c.execute(
        f"SELECT * FROM actors WHERE id IN ({','.join('?' * len(missing))})", missing)] if missing else []
    return f"{lead}：{'、'.join(names)}" if names else ""


def record_steps(row: sqlite3.Row) -> list[str]:
    return messages.next_steps(row["kind"], row["state"], row["seq"], loads(row["document_json"]))


def world_facts(room: sqlite3.Row) -> list[dict[str, Any]]:
    pack = shared.world(room)["pack"]
    return [{"ref": f"world-fact.{e['id']}", "kind": "source_fact", "revision": 1, "state": "confirmed",
             "document": {"title": e["name"], "text": e["summary"], "source_kind": "author_world", "entry_ref": e["id"]}}
            for e in pack["entries"] if e.get("public") and e.get("summary", "").strip()]


def load_records(c: sqlite3.Connection, room: sqlite3.Row, kinds: set[str]) -> list[dict[str, Any]]:
    rows = c.execute(f"SELECT * FROM records WHERE room_id=? AND kind IN ({','.join('?' * len(kinds))}) ORDER BY seq",
                     (room["id"], *sorted(kinds))).fetchall() if kinds else []
    records = [{"ref": r["id"], "kind": r["kind"], "revision": r["revision"], "state": r["state"],
                "document": loads(r["document_json"]), "seq": r["seq"]} for r in rows]
    if "source_fact" in kinds:
        records += world_facts(room)
    return records


def by_seq(app: "LiteApp", room: sqlite3.Row, seq: int, *kinds: str) -> sqlite3.Row:
    with app.store.read() as c:
        row = c.execute("SELECT * FROM records WHERE room_id=? AND seq=?", (room["id"], seq)).fetchone()
    if row is None:
        raise UserError(f"没有 #{seq} 这条记录。发送 /团 记录 查看。")
    if kinds and row["kind"] not in kinds:
        raise UserError(f"#{seq} 是{KIND_LABELS.get(row['kind'], row['kind'])}，这里需要" + "或".join(KIND_LABELS.get(k, k) for k in kinds) + "。")
    return row


def actor_by_name(app: "LiteApp", room: sqlite3.Row, name: str) -> sqlite3.Row:
    name = name.strip().lstrip("@")
    with app.store.read() as c:
        for actor in hosted.eligible_actors(c, room["id"]):
            if name in (actor["name"], actor["user_name"], actor["user_id"]):
                return actor
    raise UserError(f"在场角色里没有“{name}”。")


# ---------------------------------------------------------------- intake
def _turn_bound(proposal: dict[str, Any], current: dict[str, dict[str, Any]]) -> bool:
    ops = [op for branch in proposal["outcomes"].values() for op in branch]
    calendar = any(op.get("kind") == "calendar" or (op["op"] == "update" and current[op["ref"]]["kind"] == "calendar")
                   for op in ops if op["op"] in ("create", "update"))
    joint = any(op["op"] == "harm" or (op["op"] == "update" and current[op["ref"]]["kind"] == "joint"
                                       and op["state"] in ("cleared", "overrun")) for op in ops)
    return bool(proposal.get("check") or proposal.get("draw") or calendar or joint or any(op["op"] == "resources" for op in ops))


def _check_ops(proposal: dict[str, Any], current: dict[str, dict[str, Any]]) -> None:
    for branch in proposal["outcomes"].values():
        for op in branch:
            if op["op"] not in LITE_OPS:
                raise UserError("这个操作在 Lite 中未开放。")
            if op["op"] == "update" and (op["ref"] not in current or current[op["ref"]]["revision"] != op["revision"]):
                raise UserError("记录刚刚发生了变化，请再试一次。")


async def perform(app: "LiteApp", caller: Caller, play: str, action: str, value: dict[str, Any]) -> Reply:
    room = shared.require_room(app, caller, "running")
    if action not in ALLOWED.get(play, ()):
        raise UserError("这个操作在 Lite 中未开放。")
    if not app.features.enabled(caller.umo, play) and action not in WIND_DOWN.get(play, ()):
        raise UserError(f"本群未开放“{BY_KEY[play].label}”玩法。")
    actor = shared.require_actor(app, caller, room)
    if not actor["archetype_id"] or actor["presence"] != "present":
        raise UserError("需要在场并选好职业的角色才能这样做。")
    if (play, action) in HOST_ACTIONS:
        shared.require_host(app, caller, room)
    catalog = await app.engine.catalog()
    reads = set(catalog["plays"][play]["reads"])
    lock = app.lock(room["id"] + ":plays")
    async with lock:
        with app.store.read() as c:
            records = load_records(c, room, reads)
            members = [a["id"] for a in hosted.eligible_actors(c, room["id"])]
            turn = hosted.current_turn(c, room["id"])
        payload = {"play": play, "action": action, "input": value, "actor_ref": actor["id"], "member_refs": members,
                   "rules": shared.rules(room),
                   "records": [{k: r[k] for k in ("ref", "kind", "revision", "state", "document")} for r in records]}
        try:
            proposal = await app.engine.evaluate_custom_play(payload)
        except CustomPlayError as exc:
            code = str(exc).removeprefix("custom_play.")
            raise UserError(REASONS.get(code, f"引擎拒绝了这个操作（{code}）。")) from exc
        current = {r["ref"]: r for r in records}
        _check_ops(proposal, current)
        bound = _turn_bound(proposal, current)
        if bound and turn is not None and turn["state"] == "awaiting" and turn["actor_id"] != actor["id"]:
            with app.store.read() as c:
                holder = c.execute("SELECT * FROM actors WHERE id=?", (turn["actor_id"],)).fetchone()
            raise UserError(f"这个操作会用掉一次行动，现在轮到 {shared.actor_label(holder)}。")
        if bound and turn is not None and turn["state"] != "awaiting":
            raise UserError("上一个行动还在结算，请稍候。")
        dice_line, branch, check_block, draw_block = "", "always", None, None
        if proposal.get("check"):
            check = proposal["check"]
            rules = shared.rules(room)
            score = loads(actor["attributes_json"], {}).get(check["attribute_ref"], rules["modifier"]["baseline"])
            mod = (score - rules["modifier"]["baseline"]) // rules["modifier"]["divisor"]
            roll = roll_check(mod, rules["difficulties"][check["difficulty"]])
            branch = "success" if roll.success else "failure"
            outcome = "大成功" if roll.critical else "大失败" if roll.fumble else "成功" if roll.success else "失败"
            dice_line = (f"【检定】{rules['attributes'][check['attribute_ref']]}·"
                         f"{hosted.DIFFICULTY_LABELS.get(check['difficulty'], check['difficulty'])}："
                         f"d20={roll.face} {mod:+d} = {roll.total}，对抗 {roll.dc} → {outcome}")
            check_block = {"attribute": rules["attributes"][check["attribute_ref"]],
                           "difficulty": messages.DIFFICULTY.get(check["difficulty"], check["difficulty"]),
                           "dc": roll.dc, "face": roll.face, "modifier": mod, "total": roll.total,
                           "outcome": "critical" if roll.critical else "fumble" if roll.fumble
                           else "success" if roll.success else "failure"}
        elif proposal.get("draw"):
            face = d20()
            band = next(b for b in proposal["draw"]["bands"] if b["low"] <= face <= b["high"])
            branch = band["key"]
            dice_line = f"【d20={face}】{band['label']}"
            draw_block = (face, band["label"])
        chosen = proposal["outcomes"][branch]
        written, completes, extra_lines = commit(app, room, actor, play, action, proposal, chosen, current, dice_line, value)
        rolled = check_block["face"] if check_block else draw_block[0] if draw_block else None
        if rolled:
            with app.store.tx() as c:
                luck.record(c, room["umo"], actor["user_id"], actor["user_name"], "check", [rolled])
    if check_block and branch == "failure" and not written:
        extra_lines.append("这次没有收获。")
    steps = [s for row in written[:2] for s in record_steps(row)]
    with app.store.read() as c:
        steps += [line for row in written[:2] if (line := waiting_on(c, row, members))]
    seqs = record_seqs(app, room["id"])
    reply = Reply().say(messages.play_receipt(shared.actor_label(actor), lite_summary(action, value, current, proposal),
                                              check=check_block, draw=draw_block, changes=extra_lines,
                                              records=[record_line(row, seqs) for row in written], steps=steps))
    if completes:
        from ..rooms import lifecycle
        ending = next((loads(r["document_json"]) for r in written if r["kind"] == "ending"), None)
        reply.extend(await lifecycle.complete_story(app, room["id"], {"title": ending["title"]} if ending else None, by=caller.user_id))
    elif bound and turn is not None:
        with app.store.read() as c:
            fresh = hosted.current_turn(c, room["id"])
        if fresh is not None and fresh["id"] == turn["id"] and fresh["state"] == "awaiting":
            reply.extend(hosted.pass_turn(app, room, fresh, f"{shared.actor_label(actor)} 用这一回合完成了{LABELS.get(action, proposal['label'])}。"))
    return reply


def commit(app: "LiteApp", room: sqlite3.Row, actor: sqlite3.Row, play: str, action: str, proposal: dict[str, Any],
           chosen: list[dict[str, Any]], current: dict[str, dict[str, Any]], dice_line: str, value: dict[str, Any]
           ) -> tuple[list[sqlite3.Row], bool, list[str]]:
    pack = shared.world(room)["pack"]
    resource_names = {r["id"]: r["name"] for r in pack["resources"]}
    extra: list[str] = []
    written_ids: list[str] = []
    completes = False
    with app.store.tx() as c:
        for ref, record in current.items():
            if record["kind"] == "source_fact":
                continue
            row = c.execute("SELECT revision FROM records WHERE id=?", (ref,)).fetchone()
            if row is None or row["revision"] != record["revision"]:
                raise UserError("记录刚刚发生了变化，请再试一次。")
        for op in chosen:
            if op["op"] == "create":
                record_id = new_id("rec")
                c.execute("INSERT INTO records(id,room_id,seq,play,kind,state,audience,members_json,document_json,created_by,"
                          "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                          (record_id, room["id"], app.store.next_seq(c, room["id"]), play, op["kind"], op["state"],
                           op.get("audience", "room"), dumps(op.get("members", [])), dumps(op["document"]), actor["id"], now(), now()))
                written_ids.append(record_id)
            elif op["op"] == "update":
                if c.execute("UPDATE records SET state=?,document_json=?,revision=revision+1,updated_at=? WHERE id=? AND revision=?",
                             (op["state"], dumps(op["document"]), now(), op["ref"], op["revision"])).rowcount != 1:
                    raise UserError("记录刚刚发生了变化，请再试一次。")
                written_ids.append(op["ref"])
                if current[op["ref"]]["kind"] == "transformation" and op["state"] == "confirmed":
                    _add_traits(c, op["ref"], op["document"])
            elif op["op"] == "resources":
                fresh = c.execute("SELECT * FROM actors WHERE id=?", (actor["id"],)).fetchone()
                resources = loads(fresh["resources_json"], {})
                rest = shared.rules(room).get("recovery", {}).get("rest", {})
                for ref, amount in rest.get("cost", {}).items():
                    if ref in resources and resources[ref]["current"] + amount < resources[ref].get("min", 0):
                        raise UserError(f"{resource_names.get(ref, ref)}不足，不能休整。")
                applied = hosted.apply_deltas(resources, op["deltas"])
                c.execute("UPDATE actors SET resources_json=?,revision=revision+1,updated_at=? WHERE id=?",
                          (dumps(resources), now(), actor["id"]))
                if applied:
                    extra.append("　".join(f"{resource_names.get(k, k)} {v:+d}" for k, v in applied.items()))
            elif op["op"] == "harm":
                for ref in op["actor_refs"]:
                    target = c.execute("SELECT * FROM actors WHERE id=?", (ref,)).fetchone()
                    if target is None:
                        continue
                    resources = loads(target["resources_json"], {})
                    applied = hosted.apply_deltas(resources, {op["resource_ref"]: -op["amount"]})
                    c.execute("UPDATE actors SET resources_json=?,revision=revision+1,updated_at=? WHERE id=?",
                              (dumps(resources), now(), ref))
                    if applied:
                        extra.append(f"{shared.actor_label(target)} {resource_names.get(op['resource_ref'], op['resource_ref'])} "
                                     f"{applied[op['resource_ref']]:+d}")
            elif op["op"] == "complete_room":
                completes = True
        for record_id in written_ids:
            row = c.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
            if row["kind"] == "calendar":
                document = loads(row["document_json"])
                c.execute("UPDATE rooms SET clock_json=? WHERE id=?",
                          (dumps({"day": document["day"], "slot": document["slot"]}), room["id"]))
        summary = f"{shared.actor_label(actor)}：{lite_summary(action, value, current, proposal)}" \
            + (f"（{dice_line}）" if dice_line else "")
        app.store.add_event(c, room["id"], "play", summary, actor_id=actor["id"], data={"play": play, "action": action})
        app.store.bump_room(c, room["id"])
        rows = [c.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone() for rid in dict.fromkeys(written_ids)]
    return [r for r in rows if r["kind"] != "calendar"], completes, extra


def _add_traits(c: sqlite3.Connection, record_id: str, change: dict[str, Any]) -> None:
    targets = [change["target_actor_ref"]] + ([change["heir_actor_ref"]] if change.get("change_kind") == "legacy" else [])
    for ref in targets:
        row = c.execute("SELECT traits_json FROM actors WHERE id=?", (ref,)).fetchone()
        if row is None:
            continue
        traits = loads(row["traits_json"], [])
        if not any(t.get("source") == record_id for t in traits):
            traits.append({"source": record_id, "title": change["title"], "text": change["change"]})
            c.execute("UPDATE actors SET traits_json=?,revision=revision+1 WHERE id=?", (dumps(traits[-64:]), ref))


# ---------------------------------------------------------------- parsing helpers
def _check(app: "LiteApp", room: sqlite3.Row, args: str, *, required: bool = True) -> tuple[str, dict[str, str]]:
    rules = shared.rules(room)
    text, check = parse_check(args, rules["attributes"], hosted.DIFFICULTY_LABELS)
    if check is None and required:
        raise UserError("这个操作需要检定，请在句末写 [属性 难度]，例如 [" + next(iter(rules["attributes"].values())) + " 标准]。"
                        "属性：" + "、".join(rules["attributes"].values()))
    return text, check or {}


def _one_ref(args: str, what: str) -> tuple[int, str]:
    refs, rest = parse_refs(args)
    if not refs:
        raise UserError(f"请用 #编号 指明{what}。发送 /团 记录 查看编号。")
    return refs[0], rest


def _need(text: str, usage: str, limit: int = 1000) -> str:
    text = text.strip()
    if not text or len(text) > limit:
        raise UserError("写法：" + usage)
    return text


# ---------------------------------------------------------------- commands
def _room(app: "LiteApp", caller: Caller) -> sqlite3.Row:
    return shared.require_room(app, caller, "running")


async def cmd_clue(app, caller, args):
    room = _room(app, caller)
    source = "observed"
    words = args.split(maxsplit=1)
    if words and words[0] in ("亲见", "亲眼", "听说", "他人"):
        source = "observed" if words[0].startswith("亲") else "speaker_claim"
        args = words[1] if len(words) > 1 else ""
    title, text = split_title(_need(args, "/团 线索 [亲见|听说] 标题：内容"))
    return await perform(app, caller, "playInvestigation", "note_clue", {"title": title[:120], "text": text[:1000], "source_kind": source})


async def cmd_search(app, caller, args):
    room = _room(app, caller)
    text, check = _check(app, room, args)
    title, method = split_title(_need(text, "/团 搜查 目标：方式 [属性 难度]"))
    return await perform(app, caller, "playInvestigation", "search", {"title": title[:120], "text": method[:1000], **check})


async def cmd_hypothesis(app, caller, args):
    room = _room(app, caller)
    refs, rest = parse_refs(args)
    if not refs:
        title, text = split_title(_need(args, "/团 假设 标题：推断"))
        return await perform(app, caller, "playInvestigation", "propose_hypothesis", {"title": title[:120], "text": text[:1000]})
    hypothesis = by_seq(app, room, refs[0], "hypothesis")
    if "撤回" in rest:
        return await perform(app, caller, "playInvestigation", "withdraw_hypothesis", {"hypothesis_ref": hypothesis["id"]})
    if len(refs) < 2 or not any(w in rest for w in ("支持", "反驳")):
        raise UserError("写法：/团 假设 #假设 支持|反驳 #线索，或 /团 假设 #假设 撤回")
    clue = by_seq(app, room, refs[1], "clue")
    return await perform(app, caller, "playInvestigation", "weigh", {"hypothesis_ref": hypothesis["id"], "clue_ref": clue["id"],
                                                                     "stance": "support" if "支持" in rest else "refute"})


async def cmd_conclude(app, caller, args):
    room = _room(app, caller)
    seq, rest = _one_ref(args, "假设")
    if not any(w in rest for w in ("采纳", "否定")):
        raise UserError("写法：/团 结论 #假设 采纳|否定")
    record = by_seq(app, room, seq, "hypothesis")
    document, accept = loads(record["document_json"]), "采纳" in rest
    need = "supported" if accept else "refuted"
    if record["state"] in ("open", "contested", "supported", "refuted") and record["state"] != need:
        support, refute = len(document.get("support") or []), len(document.get("refute") or [])
        side, counts = ("支持", f"现在支持 {support}、反驳 {refute}") if accept else ("反驳", f"现在反驳 {refute}、支持 {support}")
        raise UserError(f"{'采纳' if accept else '否定'}需要至少两条线索{side}，且{side}多于另一方（{counts}）。"
                        f"用 /团 假设 #{seq} {side} #线索 补证据。")
    return await perform(app, caller, "playInvestigation", "conclude",
                         {"hypothesis_ref": by_seq(app, room, seq, "hypothesis")["id"], "verdict": "accept" if "采纳" in rest else "reject"})


async def cmd_cite(app, caller, args):
    room = _room(app, caller)
    name = _need(args, "/团 引用 <公开条目名>")
    fact = next((f for f in world_facts(room) if name in (f["document"]["title"], f["document"]["entry_ref"])), None)
    if fact is None:
        names = "、".join(f["document"]["title"] for f in world_facts(room))
        raise UserError("没有这个公开条目。可引用：" + names)
    return await perform(app, caller, "playInvestigation", "cite_fact", {"fact_ref": fact["ref"]})


async def cmd_testimony(app, caller, args):
    speaker, text = split_title(_need(args, "/团 证词 证人：证词"))
    return await perform(app, caller, "playTestimony", "record_testimony", {"speaker": speaker[:80], "text": text[:1000]})


async def cmd_press(app, caller, args):
    room = _room(app, caller)
    text, check = _check(app, room, args)
    seq, question = _one_ref(text, "证词")
    return await perform(app, caller, "playTestimony", "press", {"testimony_ref": by_seq(app, room, seq, "testimony")["id"],
                                                                 "question": _need(question, "/团 追问 #证词 问题 [属性 难度]", 600), **check})


async def cmd_present(app, caller, args):
    room = _room(app, caller)
    text, check = _check(app, room, args)
    refs, claim = parse_refs(text)
    if len(refs) < 2:
        raise UserError("写法：/团 出示 #证词 #线索 指出矛盾 [属性 难度]")
    return await perform(app, caller, "playTestimony", "present", {
        "testimony_ref": by_seq(app, room, refs[0], "testimony")["id"], "clue_ref": by_seq(app, room, refs[1], "clue")["id"],
        "claim": _need(claim, "/团 出示 #证词 #线索 指出矛盾 [属性 难度]", 600), **check})


async def cmd_compare(app, caller, args):
    room = _room(app, caller)
    refs, text = parse_refs(args)
    if len(refs) < 2:
        raise UserError("写法：/团 对照 #证词 #证词 说明")
    return await perform(app, caller, "playTestimony", "compare_statement", {
        "testimony_ref": by_seq(app, room, refs[0], "testimony")["id"],
        "other_testimony_ref": by_seq(app, room, refs[1], "testimony")["id"], "text": _need(text, "/团 对照 #证词 #证词 说明", 600)})


async def cmd_talks(app, caller, args):
    room = _room(app, caller)
    refs, rest = parse_refs(args)
    if not refs:
        counterpart, topic = split_title(_need(args, "/团 交涉 对象：议题"))
        return await perform(app, caller, "playNegotiation", "open_talks", {"counterpart": counterpart[:80], "topic": topic[:300]})
    talks = by_seq(app, room, refs[0], "negotiation")["id"]
    word = rest.strip()
    if word.startswith("达成"):
        return await perform(app, caller, "playNegotiation", "settle_talks", {"negotiation_ref": talks})
    if word.startswith("中止"):
        return await perform(app, caller, "playNegotiation", "walk_away", {"negotiation_ref": talks})
    text, check = _check(app, room, rest)
    return await perform(app, caller, "playNegotiation", "argue_terms", {"negotiation_ref": talks,
                                                                          "argument": _need(text, "/团 交涉 #交涉 理由 [属性 难度]", 600), **check})


async def cmd_term(app, caller, args):
    room = _room(app, caller)
    seq, text = _one_ref(args, "交涉")
    return await perform(app, caller, "playNegotiation", "propose_term", {"negotiation_ref": by_seq(app, room, seq, "negotiation")["id"],
                                                                          "text": _need(text, "/团 条款 #交涉 条款内容", 400)})


async def cmd_sign(app, caller, args):
    room = _room(app, caller)
    seq, rest = _one_ref(args, "交涉")
    if not rest.strip().isdigit():
        raise UserError("写法：/团 签署 #交涉 条款序号")
    return await perform(app, caller, "playNegotiation", "sign_term", {"negotiation_ref": by_seq(app, room, seq, "negotiation")["id"],
                                                                       "term_id": int(rest.strip())})


async def cmd_relation(app, caller, args):
    room = _room(app, caller)
    words = args.split(maxsplit=1)
    if not words:
        reply = await list_records(app, caller, "关系")
        reply.private_only = True
        return reply
    kind = {"人物": "npc", "势力": "faction"}
    if words[0] == "记下":
        rest = words[1] if len(words) > 1 else ""
        subject_kind = "npc"
        parts = rest.split(maxsplit=1)
        if parts and parts[0] in kind:
            subject_kind, rest = kind[parts[0]], parts[1] if len(parts) > 1 else ""
        subject, text = split_title(_need(rest, "/团 关系 记下 [人物|势力] 对象：往来"))
        return await perform(app, caller, "playRelations", "remember", {"subject": subject[:80], "subject_kind": subject_kind, "text": text[:600]})
    if words[0] not in kind:
        raise UserError("写法：/团 关系 人物|势力 对象：方式 [属性 难度]，或 /团 关系 记下 对象：往来")
    text, check = _check(app, room, words[1] if len(words) > 1 else "")
    subject, approach = split_title(_need(text, "/团 关系 人物 对象：方式 [属性 难度]"))
    return await perform(app, caller, "playRelations", "appeal", {"subject": subject[:80], "subject_kind": kind[words[0]],
                                                                 "approach": approach[:600], **check})


async def cmd_goal(app, caller, args):
    room = _room(app, caller)
    refs, rest = parse_refs(args)
    if refs:
        if not any(w in rest for w in ("实现", "放弃")):
            raise UserError("写法：/团 目标 #目标 实现|放弃")
        return await perform(app, caller, "playRelations", "resolve_goal", {"goal_ref": by_seq(app, room, refs[0], "companion_goal")["id"],
                                                                            "result": "fulfilled" if "实现" in rest else "abandoned"})
    companion, goal = split_title(_need(args, "/团 目标 同伴：目标"))
    return await perform(app, caller, "playRelations", "set_goal", {"companion": companion[:80], "goal": goal[:400]})


def _int_suffix(text: str, low: int, high: int, default: int) -> tuple[str, int]:
    match = re.search(r"(\d+)\s*$", text)
    if match and low <= int(match.group(1)) <= high:
        return text[:match.start()].strip(), int(match.group(1))
    return text.strip(), default


async def cmd_conflict(app, caller, args):
    room = _room(app, caller)
    refs, rest = parse_refs(args)
    if refs:
        contest = by_seq(app, room, refs[0], "contest")
        play = CONTEST_PLAYS[loads(contest["document_json"])["procedure"]]
        if "加入" in rest:
            return await perform(app, caller, play, "join_contest", {"contest_ref": contest["id"]})
        if any(w in rest for w in ("让步", "放弃", "认输")):
            return await perform(app, caller, play, "concede", {"contest_ref": contest["id"]})
        raise UserError("写法：/团 冲突 #冲突 加入|让步；交锋请用 /团 交锋 #冲突 行动 [属性 难度]")
    words = args.split(maxsplit=2)
    if words and words[0] == "追逐":
        if len(words) < 3 or words[1] not in ("追赶", "逃离"):
            raise UserError("写法：/团 冲突 追逐 追赶|逃离 对象 [距离2-4]")
        quarry, distance = _int_suffix(words[2], 2, 4, 3)
        return await perform(app, caller, "playChase", "open_chase", {"quarry": _need(quarry, "/团 冲突 追逐 追赶 对象", 80),
                                                                      "role": "pursue" if words[1] == "追赶" else "flee",
                                                                      "distance": distance})
    text, length = _int_suffix(args, 3, 6, 4)
    opponent, stakes = split_title(_need(text, "/团 冲突 对手：赌注 [轨道长度3-6]"))
    return await perform(app, caller, "playConflict", "open_conflict", {"opponent": opponent[:80], "stakes": stakes[:300], "length": length})


async def cmd_debate(app, caller, args):
    text, rounds = _int_suffix(args, 3, 6, 3)
    topic, stance = split_title(_need(text, "/团 辩论 辩题：立场 [回合数3-6]"))
    return await perform(app, caller, "playDebate", "open_debate", {"topic": topic[:200], "stance": stance[:300], "rounds": rounds})


async def cmd_exchange(app, caller, args):
    room = _room(app, caller)
    text, check = _check(app, room, args)
    seq, rest = _one_ref(text, "对抗")
    contest = by_seq(app, room, seq, "contest")
    play = CONTEST_PLAYS[loads(contest["document_json"])["procedure"]]
    words = rest.split(maxsplit=1)
    positions = {"冒险": "risky", "孤注": "desperate", "稳妥": "controlled"}
    if words and words[0] in positions and play != "playChase":
        return await perform(app, caller, play, "maneuver", {"contest_ref": contest["id"], "position": positions[words[0]],
                                                             "text": _need(words[1] if len(words) > 1 else "", "/团 交锋 #对抗 冒险 行动 [属性 难度]", 600),
                                                             **check})
    return await perform(app, caller, play, "exchange", {"contest_ref": contest["id"],
                                                         "text": _need(rest, "/团 交锋 #对抗 行动 [属性 难度]", 600), **check})


async def cmd_plan(app, caller, args):
    room = _room(app, caller)
    refs, rest = parse_refs(args)
    if refs:
        plan = by_seq(app, room, refs[0], "plan")["id"]
        words = rest.split()
        if words and words[0] == "认领" and len(words) > 1 and words[1].isdigit():
            return await perform(app, caller, "playPlans", "claim_step", {"plan_ref": plan, "step": int(words[1])})
        if words and words[0] == "确认":
            return await perform(app, caller, "playPlans", "confirm_plan", {"plan_ref": plan})
        if words and words[0] == "撤离":
            return await perform(app, caller, "playPlans", "evacuate", {"plan_ref": plan})
        raise UserError("写法：/团 计划 #计划 认领 <步骤>|确认|撤离")
    parts = [p.strip() for p in args.replace("|", "｜").split("｜") if p.strip()]
    if len(parts) < 2:
        raise UserError("写法：/团 计划 标题：目标｜步骤一｜步骤二（最多 6 步）")
    title, goal = split_title(parts[0])
    return await perform(app, caller, "playPlans", "draft_plan", {"title": title[:120], "goal": goal[:400],
                                                                  "steps": [p[:300] for p in parts[1:7]]})


async def cmd_execute(app, caller, args):
    room = _room(app, caller)
    text, check = _check(app, room, args)
    seq, rest = _one_ref(text, "计划")
    if not rest.strip().isdigit():
        raise UserError("写法：/团 执行 #计划 步骤序号 [属性 难度]")
    return await perform(app, caller, "playPlans", "execute_step", {"plan_ref": by_seq(app, room, seq, "plan")["id"],
                                                                    "step": int(rest.strip()), **check})


SLOT_NAMES = {"清晨": 0, "白天": 1, "傍晚": 2, "夜晚": 3}


async def cmd_time(app, caller, args):
    room = _room(app, caller)
    words = args.split(maxsplit=2)
    if not words:
        from ..rooms import lifecycle
        reply = Reply().say("现在是 " + (lifecycle.clock_text(room) or "第 1 日 · 清晨") + "。")
        reply.private_only = True
        return reply
    if words[0] == "花费" and len(words) == 3 and words[1].isdigit() and 1 <= int(words[1]) <= 4:
        return await perform(app, caller, "playCalendar", "spend_time", {"activity": words[2][:200], "slots": int(words[1])})
    raise UserError("写法：/团 时间 花费 <1-4 个时段> <活动>")


async def cmd_deadline(app, caller, args):
    room = _room(app, caller)
    refs, rest = parse_refs(args)
    if refs:
        return await perform(app, caller, "playCalendar", "meet_deadline", {"deadline_ref": by_seq(app, room, refs[0], "deadline")["id"]})
    match = re.match(r"^(.+?)\s*第\s*(\d{1,3})\s*[日天]\s*(清晨|白天|傍晚|夜晚)\s*$", args.strip())
    if not match:
        raise UserError("写法：/团 期限 事项 第N日 清晨|白天|傍晚|夜晚，完成时 /团 期限 #期限 完成")
    return await perform(app, caller, "playCalendar", "set_deadline", {"title": match.group(1)[:120], "day": int(match.group(2)),
                                                                       "slot": SLOT_NAMES[match.group(3)]})


async def cmd_project(app, caller, args):
    room = _room(app, caller)
    refs, rest = parse_refs(args)
    if refs:
        text, check = _check(app, room, rest)
        if "推进" not in text:
            raise UserError("写法：/团 项目 #项目 推进 [属性 难度]")
        return await perform(app, caller, "playProjects", "work_project", {"project_ref": by_seq(app, room, refs[0], "project")["id"], **check})
    title, segments = _int_suffix(args, 3, 8, 4)
    return await perform(app, caller, "playProjects", "start_project", {"title": _need(title, "/团 项目 标题 [进度格3-8]", 120),
                                                                        "project_kind": "project", "segments": segments})


async def cmd_rest(app, caller, args):
    reply = await perform(app, caller, "playProjects", "rest", {})
    from .. import loadout
    room = shared.require_room(app, caller)
    actor = shared.require_actor(app, caller, room)
    with app.store.tx() as c:
        if loadout.refill(c, room, "rest", [actor["id"]]):
            reply.messages.insert(1, "按“休整后恢复”的技能与物品次数已恢复。")
    return reply


async def cmd_fortune(app, caller, args):
    room = _room(app, caller)
    refs, rest = parse_refs(args)
    if refs:
        use = rest.strip().removeprefix("兑现").strip()
        return await perform(app, caller, "playFortune", "settle_fortune", {"fortune_ref": by_seq(app, room, refs[0], "fortune")["id"],
                                                                            "use": _need(use, "/团 机运 #机运 兑现 如何兑现", 400)})
    return await perform(app, caller, "playFortune", "draw_fortune", {"stake": _need(args, "/团 机运 所求之事", 300)})


ORACLE_LIKELIHOOD = {"很可能": "likely", "五五开": "even", "不太可能": "unlikely"}


async def cmd_oracle(app, caller, args):
    if args.split(maxsplit=1)[:1] == ["抽"]:
        raise UserError("Lite 没有灵感表，神谕只回答是非问题：/团 神谕 [很可能|五五开|不太可能] 问题")
    words = args.split(maxsplit=2)
    likelihood = "even"
    if words and words[0] in ORACLE_LIKELIHOOD:
        likelihood = ORACLE_LIKELIHOOD[words[0]]
        args = args.split(maxsplit=1)[1] if len(words) > 1 else ""
    return await perform(app, caller, "playOracle", "ask_oracle", {"question": _need(args, "/团 神谕 [很可能|五五开|不太可能] 是非问题", 300),
                                                                   "likelihood": likelihood})


async def cmd_change(app, caller, args):
    room = _room(app, caller)
    refs, rest = parse_refs(args)
    if refs:
        record = by_seq(app, room, refs[0], "transformation")["id"]
        action = {"确认": "confirm_change", "拒绝": "decline_change", "撤回": "withdraw_change"}.get(rest.strip()[:2])
        if action is None:
            raise UserError("写法：/团 转变 #转变 确认|拒绝|撤回")
        return await perform(app, caller, "playTransformation", action, {"transformation_ref": record})
    words = args.split(maxsplit=2)
    if len(words) >= 1 and words[0] == "转变":
        words = args.split(maxsplit=3)[1:]
    if len(words) < 2:
        raise UserError("写法：/团 转变 <角色名> 名称：变化，被指名的角色本人用 /团 转变 #编号 确认")
    target = actor_by_name(app, room, words[0])
    text = " ".join(words[1:])
    title, change = split_title(_need(text, "/团 转变 转变 角色名 名称：变化"))
    value = {"title": title[:120], "change": change[:800], "change_kind": "transformation", "target_actor_ref": target["id"]}
    return await perform(app, caller, "playTransformation", "propose_change", value)


async def cmd_ending(app, caller, args):
    room = _room(app, caller)
    refs, rest = parse_refs(args)
    if not refs:
        words = args.split(maxsplit=1)
        if words and words[0] == "提出":
            title, description = split_title(_need(words[1] if len(words) > 1 else "", "/团 结局 提出 标题：走向"))
            return await perform(app, caller, "playBranchEndings", "propose_branch", {"title": title[:120], "description": description[:800]})
        reply = await list_records(app, caller, "结局")
        endings = shared.world(room).get("presentation", {}).get("endings") or []
        if endings:
            # Ending conditions name hidden truths; like 321Roll, only the host sees them.
            host = shared.is_host(app, caller, room)
            items = [f"**{e['name']}**　{e['rule']}" if host else f"**{e['name']}**" for e in endings]
            reply.say(Msg().title("本世界预设的结局").gap().items(items)
                      .gap().hint(f"用 {messages.cmd('/团 结局 提出 结局名：走向')} 提出分支"
                                  + ("" if host else "，结局名请用上面的名称；达成条件只有主持人能看到")))
        reply.private_only = True
        return reply
    record = by_seq(app, room, refs[0], "branch", "ending")
    word = rest.strip()[:2]
    if record["kind"] == "branch" and word == "支持":
        return await perform(app, caller, "playBranchEndings", "vote_branch", {"branch_ref": record["id"]})
    if record["kind"] == "branch" and word == "进入":
        return await perform(app, caller, "playBranchEndings", "enter_ending", {"branch_ref": record["id"]})
    if record["kind"] == "ending" and word == "完结":
        return await perform(app, caller, "playBranchEndings", "conclude_ending", {"ending_ref": record["id"]})
    raise UserError("写法：/团 结局 #分支 支持|进入，或 /团 结局 #结局 完结")


async def cmd_epilogue(app, caller, args):
    room = _room(app, caller)
    seq, text = _one_ref(args, "结局")
    return await perform(app, caller, "playBranchEndings", "write_epilogue", {"ending_ref": by_seq(app, room, seq, "ending")["id"],
                                                                              "text": _need(text, "/团 尾声 #结局 内容", 800)})


LIST_FILTERS = {"线索": ("clue", "hypothesis", "testimony"), "证词": ("testimony",), "交涉": ("negotiation",),
                "关系": ("relation", "companion_goal"), "冲突": ("contest",), "计划": ("plan",),
                "项目": ("project", "deadline"), "神谕": ("oracle",), "机运": ("fortune",), "转变": ("transformation",),
                "结局": ("branch", "ending")}
CLOSED_STATES = ("withdrawn", "rejected", "conceded", "won", "lost", "drawn", "cleared", "overrun", "walked_away", "complete",
                 "met", "expired", "completed", "evacuated", "settled", "set_aside", "concluded", "declined", "fulfilled", "abandoned")


async def list_records(app, caller, args):
    room = shared.require_room(app, caller)
    word = args.strip()
    kinds = LIST_FILTERS.get(word)
    show_all = word == "全部"
    with app.store.read() as c:
        rows = c.execute("SELECT * FROM records WHERE room_id=? AND kind NOT IN ('calendar','oracle_table') ORDER BY seq", (room["id"],)).fetchall()
    rows = [r for r in rows if (kinds is None or r["kind"] in kinds) and (show_all or kinds is not None or r["state"] not in CLOSED_STATES)]
    if not rows:
        return Reply().say("还没有" + (word or "进行中的") + "记录。")
    label = word if kinds is not None else ("全部" if show_all else "进行中")
    seqs = record_seqs(app, room["id"])
    return Reply().say(messages.records_list([record_line(r, seqs) for r in rows[-30:]], label))


async def show_record(app, caller, args):
    room = shared.require_room(app, caller)
    seq, _ = _one_ref(args, "记录")
    row = by_seq(app, room, seq)
    document = loads(row["document_json"])
    texts, rows = [], []
    for key in ("text", "goal", "description", "change", "stakes", "stance", "premise", "argument"):
        if isinstance(document.get(key), str) and document[key].strip():
            texts.append(document[key])
    for key, label in (("terms", "条款"), ("steps", "步骤")):
        for index, item in enumerate(document.get(key) or [], 1):
            state = (f"{len(item.get('signatures', []))} 人签署" if key == "terms"
                     else STATE_LABELS.get(item.get("status"), item.get("status", "")))
            rows.append(f"**{label}{item.get('term_id', index)}**　{messages.safe(item.get('text', ''))}　{BT}{state}{BT}")
    if document.get("answer_label"):
        rows.append(f"神谕 **{document['answer_label']}**（仅为建议，不直接成为事实）")
    return Reply().say(messages.record_detail(record_line(row, record_seqs(app, room["id"])), texts, rows, record_steps(row),
                                              record_meter(row["kind"], document)))


def record_meter(kind: str, document: dict[str, Any]) -> dict[str, Any] | None:
    if kind == "contest" and document.get("length"):
        return {"kind": "contest", "ours": int(document.get("ours") or 0), "theirs": int(document.get("theirs") or 0),
                "length": int(document["length"]), "opponent": str(document.get("opponent") or "")}
    if kind == "project" and document.get("segments"):
        return {"kind": "progress", "done": int(document.get("progress") or 0), "total": int(document["segments"])}
    if kind == "joint" and document.get("size"):
        return {"kind": "progress", "done": len(document.get("roster") or []), "total": int(document["size"]), "unit": "人"}
    if kind == "plan" and document.get("steps"):
        return {"kind": "steps", "steps": [str(s.get("status") or "open") for s in document["steps"]]}
    return None


def install(app: "LiteApp") -> None:
    r = app.router
    t = "玩法"
    r.register("记录", list_records, summary="查看玩法记录", usage="/团 记录 [线索|冲突|结局|全部…]", topic=t, private="self")
    r.register("查看", show_record, summary="查看一条记录的详情", usage="/团 查看 #编号", topic=t, private="self")
    r.register("线索", cmd_clue, summary="记录线索", usage="/团 线索 [亲见|听说] 标题：内容", topic="调查", private="room")
    r.register("搜查", cmd_search, summary="搜查证据（检定）", usage="/团 搜查 目标：方式 [属性 难度]", topic="调查", private="room")
    r.register("假设", cmd_hypothesis, summary="提出、支持/反驳或撤回假设", usage="/团 假设 标题：推断 | /团 假设 #假设 支持 #线索", topic="调查", private="room")
    r.register("结论", cmd_conclude, summary="采纳或否定假设", usage="/团 结论 #假设 采纳|否定", topic="调查", private="room")
    r.register("引用", cmd_cite, summary="引用公开世界设定", usage="/团 引用 <条目名>", topic="调查", private="room")
    r.register("证词", cmd_testimony, summary="记录证词", usage="/团 证词 证人：证词", topic="调查", private="room")
    r.register("追问", cmd_press, summary="追问证词（检定）", usage="/团 追问 #证词 问题 [属性 难度]", topic="调查", private="room")
    r.register("出示", cmd_present, summary="出示证据（检定）", usage="/团 出示 #证词 #线索 矛盾 [属性 难度]", topic="调查", private="room")
    r.register("对照", cmd_compare, summary="对照两份证词", usage="/团 对照 #证词 #证词 说明", topic="调查", private="room")
    r.register("交涉", cmd_talks, summary="开启、陈述、达成或中止交涉", usage="/团 交涉 对象：议题 | /团 交涉 #交涉 理由 [属性 难度]", topic="交涉", private="room")
    r.register("条款", cmd_term, summary="提出条款", usage="/团 条款 #交涉 内容", topic="交涉", private="room")
    r.register("签署", cmd_sign, summary="本人签署条款", usage="/团 签署 #交涉 条款序号", topic="交涉", private="room")
    r.register("关系", cmd_relation, summary="争取态度或记下往来", usage="/团 关系 人物|势力 对象：方式 [属性 难度]", topic="交涉", private="room")
    r.register("目标", cmd_goal, summary="确立或了结同伴目标", usage="/团 目标 同伴：目标 | /团 目标 #目标 实现|放弃", topic="交涉", private="room")
    r.register("冲突", cmd_conflict, summary="开启冲突或追逐、加入、让步", usage="/团 冲突 对手：赌注 | /团 冲突 追逐 追赶 对象", topic="对抗", private="room")
    r.register("辩论", cmd_debate, summary="开启辩论", usage="/团 辩论 辩题：立场 [回合数]", topic="对抗", private="room")
    r.register("交锋", cmd_exchange, summary="在对抗中出手（检定）", usage="/团 交锋 #对抗 [冒险|孤注] 行动 [属性 难度]", topic="对抗", private="room")
    r.register("计划", cmd_plan, summary="拟定、认领、确认计划或撤离", usage="/团 计划 标题：目标｜步骤一｜步骤二", topic="计划", private="room")
    r.register("执行", cmd_execute, summary="执行计划步骤（检定）", usage="/团 执行 #计划 步骤 [属性 难度]", topic="计划", private="room")
    r.register("时间", cmd_time, summary="查看时间或花费时段", usage="/团 时间 [花费 n 活动]", topic="计划", private="room")
    r.register("期限", cmd_deadline, summary="设定或完成期限", usage="/团 期限 事项 第N日 时段", topic="计划", private="room")
    r.register("项目", cmd_project, summary="开始或推进项目", usage="/团 项目 标题 [进度格] | /团 项目 #项目 推进 [属性 难度]", topic="计划", private="room")
    r.register("休整", cmd_rest, summary="安全休整一个时段", topic="计划", private="room")
    r.register("机运", cmd_fortune, summary="判定或兑现机运", usage="/团 机运 所求之事 | /团 机运 #机运 兑现 用法", topic="叙事", private="room")
    r.register("神谕", cmd_oracle, summary="向神谕问一个是非问题", usage="/团 神谕 [很可能|五五开|不太可能] 问题", topic="叙事", private="room")
    r.register("转变", cmd_change, summary="提出或确认角色转变", usage="/团 转变 角色名 名称：变化 | /团 转变 #转变 确认", topic="叙事", private="room")
    r.register("结局", cmd_ending, summary="查看、提出、支持、进入或完结结局", usage="/团 结局 提出 标题：走向 | /团 结局 #分支 支持", topic="叙事", private="room")
    r.register("尾声", cmd_epilogue, summary="写下本人尾声", usage="/团 尾声 #结局 内容", topic="叙事", private="room")
