import { acts, avatar, brief, busy, cells, dot, empty, esc, figure, fmt, hero, icon, meter, ring, roomDot, roundIcon, section, seats, shortTitle, stamps, subTitle, tug, until, veiled, when } from "../ui.js";
import { tableCard } from "./overview.js";

const FILTERS = [["open", "进行中", ["lobby", "running", "paused", "ended"]], ["running", "正在演", ["running"]], ["lobby", "筹备中", ["lobby"]],
  ["paused", "已暂停", ["paused"]], ["ended", "已完结", ["ended"]], ["closed", "已收桌", ["closed"]], ["", "全部", null]];
const EVENT_KIND = { narration: "叙事", action: "行动", check: "检定", play: "玩法", vote: "表决", system: "系统", host: "主持" };
const EVENT_ICON = { narration: "feather", action: "user", check: "dice", play: "layers", vote: "vote", system: "sparkle", host: "wand" };
const TITLE_KEYS = ["title", "topic", "subject", "question", "stake", "speaker", "counterpart", "opponent", "quarry", "companion"];
const RECORD_ICON = { clue: "search", hypothesis: "sparkle", testimony: "quote", negotiation: "scroll", relation: "users", companion_goal: "flag", deadline: "clock",
  project: "grid", contest: "bolt", joint: "shield", plan: "map", oracle: "eye", transformation: "wand", fortune: "dice", branch: "flag", ending: "book" };

// [command, label, icon, input placeholder or "", input required, confirm text]
const HOST = [
  ["叙事", [["主持 直述", "直述剧情", "feather", "要公开叙述的剧情，2–1000 字", true], ["主持 指引", "私下指引", "eyeOff", "给叙事模型的指引；写“清除”清空", true],
    ["主持 选项", "改写选项", "list", "选项一｜选项二｜选项三", true], ["主持 篇幅", "正文篇幅", "scroll", "简洁（100–300 字）｜均衡（300–600 字）｜长篇（600–1000 字）｜默认", true],
    ["主持 文风", "正文文风", "pen", "多对白｜偏对白｜均衡｜偏描写｜多描写，后面可接风格描述；写“默认”恢复", true],
    ["主持 审稿", "审稿模式", "eye", "写“开”或“关”；开启后正文先私发主持人", true],
    ["主持 发布", "发布草稿", "send"], ["主持 重写", "重写草稿", "refresh", "重写意见（可不填）", false]]],
  ["节奏", [["主持 推进", "推进剧情", "wand", "推进说明（可不填）", false], ["主持 跳过", "跳过回合", "skip"], ["主持 重试", "重试正文", "refresh"],
    ["主持 回退", "回退一步", "hourglass", "", false, "撤回最近一步行动？骰子、资源、正文和玩法记录都会回到行动前。"],
    ["主持 换幕", "换幕", "book", "幕号（不填则下一幕）", false], ["主持 限时", "回合限时", "clock", "每回合分钟数；0 为不限时；写“默认”跟随全局设置", true],
    ["主持 检定", "要求检定", "dice", "角色 属性 难度 [受伤] [理由]，例如：林晓 观察 困难 听见楼上的脚步", true],
    ["主持 集体事件", "集体事件", "sparkle"], ["主持 结束表决", "结束表决", "vote"], ["主持 表决时限", "表决时限", "hourglass", "分钟数（1–30）；写“默认”恢复 2 分钟", true]]],
  ["桌务", [["暂停", "暂停", "pause"], ["恢复", "恢复", "play"], ["存档", "存档", "save", "存档名（可不填）", false], ["读档", "读档", "folder", "存档序号或名称", true],
    ["人数", "席位上限", "users", "人数", true], ["主持 顺序", "行动顺序", "list", "按新顺序写角色名，用空格隔开；没写到的人排在后面", true],
    ["主持 入座", "入座开关", "door", "写“关”暂停新玩家入座，写“开”恢复", true], ["主持 放行", "放行玩家", "key", "被请离玩家的昵称", true],
    ["完结", "完结故事", "flag", "结局名（可不填）", false, "确定直接完结这个故事吗？"],
    ["关闭", "收桌", "door", "", false, "确定收桌吗？收桌后这一桌不再接受指令。"]]],
];
// Per-seat host actions on the seat cards: [command, label, confirm text]
const SEAT_ACTIONS = [["主持 轮到", "轮到他"], ["主持 暂离", "设为暂离"], ["主持 返回", "回到队列"], ["主持 退回", "退回重建", "收回这个角色，请玩家重新建卡？"],
  ["主持 交棒", "交棒给他", "把主持人交给这位玩家？后台操作会立即生效。"], ["主持 移出", "请离", "请这位玩家离开这一桌？之后需要放行才能再入座。"]];

let lastLog = null;
const remaining = (deadline) => (deadline ? Math.max(0, (new Date(deadline).getTime() - Date.now()) / 1000) : null);
const limitText = (s) => (!s ? "不限时" : s % 60 ? s + " 秒" : s / 60 + " 分钟");

export async function render(root, ctx) {
  if (ctx.route.rest[0]) return detail(root, ctx, ctx.route.rest[0]);
  const state = ctx.route.params.state ?? "open";
  const q = ctx.route.params.q || "";
  const data = await ctx.api.get("rooms", { state, q });
  const n = data.counts || {};
  const count = (states) => (states ? states.reduce((s, k) => s + (n[k] || 0), 0) : Object.values(n).reduce((s, v) => s + v, 0));
  root.innerHTML = hero({
    eyebrow: "团桌 · TABLES", title: "团桌",
    lead: "每个群同一时间只有一桌。点进团桌可以看进度、读最近的故事，或代替主持人操作。",
    figures: '<div class="figures">' + figure(n.running || 0, "正在演") + figure(n.lobby || 0, "筹备中", "plain") + figure(n.paused || 0, "已暂停", "plain") + figure((n.ended || 0) + (n.closed || 0), "完结与收桌", "plain") + "</div>",
  }) +
    '<div class="row between wrap" style="border-bottom:1px solid var(--line);margin-bottom:28px;align-items:flex-end"><nav class="tabs" style="border:0;margin:0">' +
    FILTERS.map(([key, label, states]) => '<button data-state="' + key + '" aria-pressed="' + (key === state) + '">' + label + '<span class="count">' + count(states) + "</span></button>").join("") + "</nav>" +
    '<form class="search" data-search style="width:260px;margin-bottom:10px">' + icon("search", 15) + '<input class="input" name="q" placeholder="搜索标题或群号" value="' + esc(q) + '" /></form></div>' +
    (data.rooms.length ? '<div class="cards">' + data.rooms.map(tableCard).join("") + "</div>" : empty("没有符合条件的团桌", "管理员在群里发送 /团 开启 开一桌"));
  const nav = (s, query) => ctx.go("rooms?" + new URLSearchParams({ state: s, ...(query ? { q: query } : {}) }));
  root.querySelectorAll("[data-state]").forEach((b) => b.addEventListener("click", () => nav(b.dataset.state, q)));
  root.querySelector("[data-search]").addEventListener("submit", (e) => { e.preventDefault(); nav(state, e.target.q.value.trim()); });
}

function recordTitle(doc) {
  for (const key of TITLE_KEYS) if (typeof doc[key] === "string" && doc[key].trim()) return doc[key].trim().slice(0, 40);
  return "";
}

function recordVisual(r, members) {
  const d = r.document;
  if (r.kind === "contest") return tug(d.ours || 0, d.theirs || 0, d.length || 4);
  if (r.kind === "project") return cells(d.progress || 0, d.segments || 0) + ' <span class="num muted">' + (d.progress || 0) + "/" + d.segments + "</span>";
  if (r.kind === "joint") return stamps((d.roster || []).length, d.size || 0);
  if (r.kind === "branch") return seats((d.votes || []).length, members);
  if (r.kind === "hypothesis") return '<span class="muted">支持 ' + (d.support || []).length + " · 反驳 " + (d.refute || []).length + "</span>";
  return "";
}

async function detail(root, ctx, id) {
  const r = await ctx.api.get("room", { id });
  const present = r.actors.filter((a) => a.presence !== "left");
  const away = present.filter((a) => a.presence === "away").length;
  const [actLine, ...leadLines] = String(r.act_heading || "").split("\n");
  const live = ["lobby", "running", "paused"].includes(r.state);
  const story = r.events.find((e) => e.kind === "narration");
  const host = present.find((a) => a.user_id === r.host_user_id);
  const reached = r.state === "lobby" ? 0 : r.act;

  root.innerHTML = '<a class="crumb" href="#/rooms">' + icon("arrow", 14, "flip") + "团桌</a>" +
    '<header class="band tone-' + esc(r.cover.tone) + '" data-mark="' + esc(r.cover.mark) + '"><div class="band-top"><div style="min-width:0">' +
      '<div class="eyebrow">' + esc(r.state_label) + " · 群 " + esc(r.group_id || "—") + " · " + esc(r.platform) + "</div><h1>" + esc(shortTitle(r.title)) + '</h1><div class="sub">' + esc(subTitle(r.title)) + "</div>" +
      '<div class="band-meta">' + (r.clock ? "<span>" + icon("clock", 13) + " " + esc(r.clock) + "</span>" : "") + (r.round ? "<span>第 " + r.round + " 轮</span>" : "") +
      (host ? "<span>主持 " + esc(host.user_name) + "</span>" : "") + "<span>" + icon("activity", 13) + " 模型 " + fmt(r.usage.calls) + " 次 · " + fmt(r.usage.tokens) + " tokens</span></div></div>" +
      '<div style="text-align:right;flex:none"><span class="avatars">' + present.map((a) => avatar(a.name || a.user_name, a.presence === "away" ? "away big" : "big")).join("") + "</span>" +
      '<div class="band-meta" style="justify-content:flex-end;margin-top:10px">' + seats(present.length, r.seat_cap, away) + "<span>" + present.length + "/" + r.seat_cap + " 席</span></div></div></div>" +
      (r.acts.length ? '<div class="band-acts">' + acts(veiled(r.acts, reached), reached) + "</div>" : "") + "</header>" +
    '<div class="grid cols-2"><div class="stack" style="gap:52px">' + nowSection(r, actLine, leadLines) + storySection(story) + recordsSection(r, present.length) + timelineSection(r) + "</div>" +
    '<div class="stack" style="gap:52px">' + (live ? hostSection(r) + adjustSection(r) : "") + peopleSection(r) + sceneSection(r) + "</div></div>" +
    '<div class="sec">' + seatsSection(r, present) + "</div>";

  if (r.turn?.deadline_at) {
    ctx.every(1000, () => {
      const slot = root.querySelector("[data-ring]");
      if (slot) slot.innerHTML = ring(remaining(r.turn.deadline_at), r.turn_timeout_seconds, "剩余");
    });
  }
  if (live) { bindHost(root, ctx, r); bindAdjust(root, ctx, r); }
}

function nowSection(r, actLine, leadLines) {
  const t = r.turn, v = r.vote;
  const states = { awaiting: "等待行动", resolving: "结算中", narration_failed: "正文待重试", review: "正文待主持人审阅" };
  let html = '<section>' + section("此刻", { meta: [r.scene?.title ? icon("map", 13) + " " + esc(r.scene.title) : "", r.goal ? icon("flag", 13) + " " + esc(r.goal) : ""].filter(Boolean).join('<i class="sep">·</i>') || esc(actLine || "") });
  if (!t) {
    html += '<div class="card">' + empty(r.state === "lobby" ? "还没开演" : "没有进行中的回合", r.state === "lobby" ? "主持人发送 /团 开演 后开始第一轮" : "") + "</div>";
  } else {
    html += '<div class="card"><div class="turn"><div data-ring>' + ring(remaining(t.deadline_at), r.turn_timeout_seconds, t.deadline_at ? "剩余" : "不限时") + "</div>" +
      '<div><div class="label">第 ' + t.round + ' 轮 · 轮到</div><div class="turn-who">' + esc(t.actor) + "</div>" + dot(t.state === "awaiting" ? "gold" : t.state === "narration_failed" ? "err" : "warn", states[t.state] || t.state) +
      '<div class="hint" style="margin:8px 0 0">回合限时 ' + limitText(r.turn_timeout_seconds) + (r.turn_timeout_own ? "（本桌设置）" : "（跟随全局）") + "</div></div></div>" +
      (t.choices.length ? '<div class="choices">' + t.choices.map((c) => '<div class="choice"><b>' + esc(c.label) + "</b><span>" + esc(c.text) + "</span>" + (c.tag ? '<span class="tag">' + esc(c.tag) + "</span>" : "") + "</div>").join("") + "</div>" : "") + "</div>";
    if (t.draft) {
      html += '<div class="card draft" style="margin-top:16px"><div class="panel-head"><h3 class="panel-title">' + icon("eye", 16) + ' 正文草稿 · 待审阅</h3><span class="hint">玩家还看不到这段</span></div>' +
        '<div class="prose serif">' + t.draft.paragraphs.map((p) => "<p>" + esc(p) + "</p>").join("") + "</div>" +
        (t.draft.suggestions.length ? '<div class="choices">' + t.draft.suggestions.map((s, i) => '<div class="choice"><b>' + "ABCD"[i] + "</b><span>" + esc(s) + "</span></div>").join("") + "</div>" : "") +
        '<div class="row" style="margin-top:14px"><button class="btn primary" type="button" data-cmd="主持 发布">' + icon("send", 14) + '发布到群里</button>' +
        '<button class="btn" type="button" data-cmd="主持 重写">' + icon("refresh", 14) + "按意见重写</button></div></div>";
    }
  }
  if (v) {
    const members = r.actors.filter((a) => a.presence === "present").length;
    html += '<div class="card" style="margin-top:16px"><div class="panel-head"><h3 class="panel-title">' + icon("vote", 16) + " 表决 · " + esc(v.title) + '</h3><span class="row" style="gap:8px;font-size:12px;color:var(--muted)">' + seats(v.ballots, members) +
      "已投 " + v.ballots + "/" + members + (v.deadline_at ? " · " + esc(until(v.deadline_at)) + "截止" : "") + "</span></div>" +
      v.options.map((o) => '<div class="vote-opt"><b>' + esc(o.key) + "</b><div><div>" + esc(o.label) + '</div><div class="hint">' + esc([o.description, o.risk && "风险：" + o.risk, o.cost && "代价：" + o.cost].filter(Boolean).join("　")) + "</div></div></div>").join("") + "</div>";
  }
  if (leadLines.join("").trim()) html += '<p class="quote">' + esc(actLine) + "　" + esc(leadLines.join(" ")) + "</p>";
  return html + "</section>";
}

function storySection(story) {
  return '<section>' + section("最近的故事", { meta: story ? esc(when(story.created_at)) + " · 模型写下的最新一段" : "" }) +
    (story ? '<div class="prose initial">' + esc(brief(story.text)) + "</div>" : empty("还没有正文", "第一位玩家行动后会出现在这里")) + "</section>";
}

function recordsSection(r, members) {
  const groups = r.play_groups.map((g) => ({ ...g, records: r.records.filter((x) => g.kinds.includes(x.kind)) })).filter((g) => g.records.length);
  const row = (x) => '<details class="record-d"><summary class="record"><span class="seq">#' + x.seq + '</span><div style="min-width:0"><div class="title">' + icon(RECORD_ICON[x.kind] || "layers", 14) + " " +
    esc(x.kind_label) + "「" + esc(recordTitle(x.document)) + '」</div><div class="meta">' + esc(x.state_label) + " · " + esc(when(x.updated_at)) + "</div></div><div>" + recordVisual(x, members) + "</div></summary>" +
    '<div class="record-body">' + recordBody(x) + (x.steps.length ? '<div class="label" style="margin-top:10px">接下来可以</div><ul class="steps">' + x.steps.map((s) => "<li>" + esc(s) + "</li>").join("") + "</ul>" : "") + "</div></details>";
  return '<section>' + section("玩法记录", { count: r.records.length, meta: "按玩法分组；点开一条看完整内容和群里的下一步" }) +
    (groups.length ? groups.map((g) => '<div class="rgroup"><div class="rgroup-title">' + esc(g.label) + '<span class="num muted">' + g.records.length + "</span></div>" + g.records.slice(0, 20).map(row).join("") + "</div>").join("")
      : empty("还没有玩法记录", "线索、交涉、对抗、计划等玩法会出现在这里")) + "</section>";
}

function recordBody(x) {
  const d = x.document, lines = [];
  for (const key of ["text", "goal", "description", "change", "stakes", "stance", "topic", "premise", "argument", "question", "answer_label", "use"]) {
    if (typeof d[key] === "string" && d[key].trim()) lines.push('<p class="quote" style="margin:6px 0">' + esc(d[key]) + "</p>");
  }
  if (Array.isArray(d.terms) && d.terms.length) lines.push('<div class="label">条款</div><ul class="steps">' + d.terms.map((t, i) => "<li>" + (i + 1) + ". " + esc(t.text) + "（" + (t.signatures || []).length + " 人签署）</li>").join("") + "</ul>");
  if (Array.isArray(d.steps) && d.steps.length) lines.push('<div class="label">步骤</div><ul class="steps">' + d.steps.map((t, i) => "<li>" + (i + 1) + ". " + esc(t.text) + "（" + esc(t.status || "") + "）</li>").join("") + "</ul>");
  if (Array.isArray(d.memories) && d.memories.length) lines.push('<div class="label">往来</div><ul class="steps">' + d.memories.map((m) => "<li>" + esc(m.text) + (m.change ? "（" + (m.change > 0 ? "+" : "") + m.change + "）" : "") + "</li>").join("") + "</ul>");
  return lines.join("") || '<div class="hint">' + esc(x.line) + "</div>";
}

function adjustSection(r) {
  const actors = r.actors.filter((a) => a.presence !== "left" && a.archetype);
  const o = r.adjust_options;
  const pending = r.adjustments.filter((a) => a.state === "pending"), done = r.adjustments.filter((a) => a.state !== "pending").slice(0, 5);
  const opts = (list) => list.map((x) => '<option value="' + esc(x.id) + '">' + esc(x.name) + "</option>").join("");
  return '<section>' + section("主持调整", { meta: "提交后不会立刻生效，要等模型写完下一回合的正文后才生效，并在群里公布" }) + '<div class="card">' +
    '<form data-adjust class="adjust-form"><div class="grid" style="grid-template-columns:1fr 1fr;gap:10px">' +
    '<label class="field"><span class="label">调整什么</span><select class="select" name="kind"><option value="resource">资源</option><option value="item">物品数量</option>' +
      '<option value="skill">技能（习得/失去）</option><option value="uses">剩余次数</option><option value="attitude">人物态度</option></select></label>' +
    '<label class="field" data-for="actor"><span class="label">角色</span><select class="select" name="actor">' + actors.map((a) => '<option value="' + esc(a.id) + '">' + esc(a.name || a.user_name) + "</option>").join("") + "</select></label>" +
    '<label class="field" data-for="resource"><span class="label">资源</span><select class="select" name="resource">' + opts(o.resources) + "</select></label>" +
    '<label class="field" data-for="item"><span class="label">物品</span><select class="select" name="item">' + opts(o.items) + "</select></label>" +
    '<label class="field" data-for="skill"><span class="label">技能</span><select class="select" name="skill">' + opts(o.skills) + "</select></label>" +
    '<label class="field" data-for="uses"><span class="label">条目</span><select class="select" name="entry">' + o.skills.map((x) => '<option value="skill:' + esc(x.id) + '">技能 · ' + esc(x.name) + "</option>").join("") +
      o.items.map((x) => '<option value="item:' + esc(x.id) + '">物品 · ' + esc(x.name) + "</option>").join("") + "</select></label>" +
    '<label class="field" data-for="delta"><span class="label">变化量（可为负）</span><input class="input num" name="delta" type="number" value="1" /></label>' +
    '<label class="field" data-for="grant"><span class="label">方式</span><select class="select" name="grant"><option value="1">习得</option><option value="0">失去</option></select></label>' +
    '<label class="field" data-for="value"><span class="label">剩余次数设为</span><input class="input num" name="value" type="number" min="0" value="1" /></label>' +
    '<label class="field" data-for="subject"><span class="label">人物或势力</span><input class="input" name="subject" list="people-names" placeholder="名字" /><datalist id="people-names">' +
      r.people.map((p) => '<option value="' + esc(p.name) + '"></option>').join("") + "</datalist></label>" +
    '<label class="field" data-for="standing"><span class="label">态度设为</span><select class="select" name="standing">' + o.standing.map((s, i) => '<option value="' + (i - 3) + '"' + (i === 3 ? " selected" : "") + ">" + s + "</option>").join("") + "</select></label>" +
    '</div><div class="row"><button class="btn primary" type="submit">' + icon("clock", 14) + "加入待生效</button></div></form>" +
    (pending.length ? '<div class="label" style="margin-top:18px">待生效 ' + pending.length + "</div>" + pending.map((a) => '<div class="ri" style="padding:10px 0">' + roundIcon("hourglass", "warn") + '<div style="min-width:0"><div class="ri-title" style="white-space:normal;font-weight:500">' +
      esc(a.lines.join("；")) + '</div><div class="ri-meta">' + esc(when(a.created_at)) + " 提交 · 下一回合正文写完后生效</div></div>" + '<button class="btn text small" data-cancel-adjust="' + esc(a.id) + '">撤销</button></div>').join("") : "") +
    (done.length ? '<details style="margin-top:12px"><summary>已处理 ' + done.length + " 条</summary>" + done.map((a) => '<div class="hint" style="margin-top:6px">' + (a.state === "applied" ? "已生效" : "已撤销") + "：" + esc(a.lines.join("；")) + "</div>").join("") + "</details>" : "") +
    "</div></section>";
}

function bindAdjust(root, ctx, r) {
  const form = root.querySelector("[data-adjust]");
  if (!form) return;
  const fields = { resource: ["actor", "resource", "delta"], item: ["actor", "item", "delta"], skill: ["actor", "skill", "grant"], uses: ["actor", "uses", "value"], attitude: ["subject", "standing"] };
  const sync = () => form.querySelectorAll("[data-for]").forEach((el) => { el.hidden = !fields[form.kind.value].includes(el.dataset.for); });
  form.kind.addEventListener("change", sync);
  sync();
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const k = form.kind.value;
    const change = { kind: k };
    if (k !== "attitude") change.actor = form.actor.value;
    if (k === "resource") Object.assign(change, { ref: form.resource.value, delta: Number(form.delta.value) });
    if (k === "item") Object.assign(change, { ref: form.item.value, delta: Number(form.delta.value) });
    if (k === "skill") Object.assign(change, { ref: form.skill.value, grant: form.grant.value === "1" });
    if (k === "uses") { const [entry, ref] = form.entry.value.split(":"); Object.assign(change, { entry, ref, value: Number(form.value.value) }); }
    if (k === "attitude") Object.assign(change, { subject: form.subject.value.trim(), standing: Number(form.standing.value) });
    try {
      await busy(form.querySelector("[type=submit]"), () => ctx.api.post("room/adjust", { id: r.id, changes: [change] }));
      ctx.toast("已加入待生效，下一回合正文写完后生效");
      ctx.refresh();
    } catch (error) { ctx.toast(error.message, "error"); }
  });
  root.querySelectorAll("[data-cancel-adjust]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await ctx.api.post("room/adjust/cancel", { id: r.id, adjustment: b.dataset.cancelAdjust });
      ctx.toast("已撤销");
      ctx.refresh();
    } catch (error) { ctx.toast(error.message, "error"); }
  }));
}


function timelineSection(r) {
  const line = (e) => '<div class="ri ' + esc(e.kind) + '">' + roundIcon(EVENT_ICON[e.kind] || "sparkle", e.kind === "narration" ? "" : "mute") + '<div style="min-width:0"><div class="ri-title">' + esc(brief(e.text, 200)) +
    '</div><div class="ri-meta"><span>' + esc(EVENT_KIND[e.kind] || e.kind) + '</span></div></div><span class="ri-side"><time>' + esc(when(e.created_at)) + "</time></span></div>";
  const shown = r.events.slice(0, 10), rest = r.events.slice(10, 60);
  return '<section>' + section("时间线", { count: r.events.length, meta: "这一桌发生过的每件事" }) +
    (r.events.length ? '<div class="rows feed">' + shown.map(line).join("") + "</div>" +
      (rest.length ? '<details style="margin-top:14px"><summary>更早的 ' + rest.length + ' 条</summary><div class="rows feed" style="margin-top:12px">' + rest.map(line).join("") + "</div></details>" : "")
      : empty("暂无事件")) + "</section>";
}

function hostSection(r) {
  const s = r.settings;
  const hidden = { 暂停: r.state !== "running", 恢复: r.state !== "paused", "主持 发布": true, "主持 重写": true };
  const notes = [["scroll", "篇幅 " + s.length], ["pen", "文风 " + ([s.preset, s.style].filter(Boolean).join(" · ") || "默认")],
    ["eye", "审稿 " + (s.review ? "开启" : "关闭")], ["door", "入座 " + (s.seating_locked ? "已关闭" : "开放")], ["hourglass", "表决 " + s.vote_minutes + " 分钟"],
    ["refresh", "可回退 " + s.rewinds + " 步"]].concat(s.handover ? [["key", "等待 " + s.handover + " 接棒"]] : [])
    .concat(s.removed.length ? [["user", "已请离 " + s.removed.join("、")]] : []);
  return '<section>' + section("主持操作", { meta: "以管理员身份执行，结果发往群聊" }) + '<div class="card">' +
    HOST.map(([group, items]) => '<div class="host-group">' + group + '</div><div class="host-actions">' + items.filter(([cmd]) => !hidden[cmd]).map(([cmd, label, ic]) =>
      '<button type="button" data-cmd="' + esc(cmd) + '">' + icon(ic, 18) + esc(label) + "</button>").join("") + "</div>").join("") +
    '<form data-host-form hidden style="margin-top:18px"><div class="field"><label data-host-label></label><textarea class="input" name="arg" rows="3"></textarea></div>' +
    '<div class="row"><button class="btn primary" type="submit">' + icon("send", 14) + '执行</button><button class="btn text" type="button" data-cancel>取消</button></div></form>' +
    '<div class="host-notes">' + notes.map(([ic, text]) => "<span>" + icon(ic, 13) + esc(text) + "</span>").join("") + "</div>" +
    (r.directive ? '<div class="hint" style="margin-top:16px">' + icon("eyeOff", 13) + " 当前指引：" + esc(r.directive) + "</div>" : "") +
    (r.saves.length ? '<div class="hint" style="margin-top:6px">' + icon("save", 13) + " 存档：" + r.saves.map((s, i) => (i + 1) + ". " + esc(s.name)).join("　") + "</div>" : "") +
    (lastLog && lastLog.id === r.id ? '<div class="sent-log"><div class="label" style="margin-bottom:6px">已发往群聊 · ' + esc(lastLog.command) + "</div>" + esc(lastLog.messages.join("\n\n")) + "</div>" : "") + "</div></section>";
}

function bindHost(root, ctx, r) {
  const form = root.querySelector("[data-host-form]");
  const specs = Object.fromEntries(HOST.flatMap(([, items]) => items.map((it) => [it[0], it])));
  let current = null;
  const run = async (button, command) => {
    try {
      const result = await busy(button, () => ctx.api.post("room/command", { id: r.id, command }));
      lastLog = { id: r.id, command, messages: result.messages };
      ctx.toast("已执行：" + command.split(" ").slice(0, 2).join(" "));
      ctx.refresh();
    } catch (error) {
      ctx.toast(error.message, "error");
    }
  };
  root.querySelectorAll("[data-cmd]").forEach((button) => button.addEventListener("click", () => {
    const [cmd, label, , placeholder, , confirmText] = specs[button.dataset.cmd];
    root.querySelectorAll("[data-cmd]").forEach((b) => b.setAttribute("aria-pressed", String(b === button && Boolean(placeholder))));
    if (!placeholder) {
      form.hidden = true;
      if (confirmText && !window.confirm(confirmText)) return;
      return run(button, cmd);
    }
    current = cmd;
    form.hidden = false;
    form.querySelector("[data-host-label]").textContent = label + " · " + placeholder;
    form.arg.value = "";
    form.arg.focus();
  }));
  form.querySelector("[data-cancel]").addEventListener("click", () => {
    form.hidden = true;
    root.querySelectorAll("[data-cmd]").forEach((b) => b.setAttribute("aria-pressed", "false"));
  });
  root.querySelectorAll("[data-seat-cmd]").forEach((button) => button.addEventListener("click", () => {
    const spec = SEAT_ACTIONS.find(([cmd]) => cmd === button.dataset.seatCmd);
    if (spec[2] && !window.confirm(button.dataset.name + "：" + spec[2])) return;
    run(button, spec[0] + " " + button.dataset.user);
  }));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const [cmd, , , , required, confirmText] = specs[current];
    const arg = form.arg.value.trim();
    if (required && !arg) return ctx.toast("请先填写内容", "error");
    if (confirmText && !window.confirm(confirmText)) return;
    run(form.querySelector('[type="submit"]'), (cmd + " " + arg).trim());
  });
}

function seatsSection(r, actors) {
  const presence = { present: ["ok", "在场"], away: ["warn", "暂离"] };
  const turnActor = r.turn?.actor;
  const entry = (e) => '<div class="kit' + (e.usable ? "" : " off") + '"><div class="kit-head"><b>' + esc(e.name) + "</b>" +
    (e.quantity != null ? '<span class="num">×' + e.quantity + "</span>" : "") + (e.equipment?.equipped ? '<span class="tag gold">已装备</span>' : "") +
    '<span class="spacer"></span>' + (e.remaining != null ? cells(e.remaining, e.uses) : "") + "</div>" +
    '<div class="kit-meta">' + esc([e.modifier ? (e.attribute_label || "任意") + "检定 " + (e.modifier > 0 ? "+" : "") + e.modifier : "",
      ...Object.entries(e.cost).map(([k, v]) => k + " -" + v), ...Object.entries(e.gain).map(([k, v]) => k + " +" + v),
      e.remaining != null ? "剩 " + e.remaining + "/" + e.uses + " · " + e.reset_label : ""].filter(Boolean).join(" · ") || "叙事效果") +
    (e.usable ? "" : '　<span class="warn-text">' + esc(e.reason) + "</span>") + "</div>" + (e.text ? '<div class="kit-text">' + esc(e.text) + "</div>" : "") + "</div>";
  const card = (a) => {
    const name = a.name || a.user_name;
    const live = ["lobby", "running", "paused"].includes(r.state);
    const isHost = a.user_id === r.host_user_id;
    const show = { "主持 轮到": r.state === "running" && r.turn?.state === "awaiting" && a.presence === "present" && a.archetype && name !== turnActor,
      "主持 暂离": a.presence === "present", "主持 返回": a.presence === "away", "主持 退回": Boolean(a.archetype), "主持 交棒": !isHost, "主持 移出": !isHost };
    const actions = live ? SEAT_ACTIONS.filter(([cmd]) => show[cmd]).map(([cmd, label]) => '<button type="button" class="btn small' + (cmd === "主持 移出" ? " danger" : "") +
      '" data-seat-cmd="' + esc(cmd) + '" data-user="' + esc(a.user_id) + '" data-name="' + esc(name) + '">' + esc(label) + "</button>").join("") : "";
    const skills = a.loadout.filter((e) => e.kind === "skill"), items = a.loadout.filter((e) => e.kind === "item");
    const ties = r.people.filter((p) => p.contributions[name]).map((p) => '<span class="tag' + (p.contributions[name] > 0 ? " gold" : "") + '">' + esc(p.name) + " " +
      (p.contributions[name] > 0 ? "+" : "") + p.contributions[name] + "</span>").join("");
    return '<article class="sheet">' + '<div class="sheet-head">' + avatar(name, "big" + (name === turnActor ? " now" : "") + (a.presence === "away" ? " away" : "")) +
      '<div style="min-width:0"><div class="actor-name"><b>' + esc(name) + '</b><span class="muted" style="font-size:12.5px">' + esc(a.archetype || "未建卡") + "</span></div>" +
      '<div class="hint">玩家 ' + esc(a.user_name) + (a.user_id === r.host_user_id ? " · 主持人" : "") + "</div></div>" + dot(...(presence[a.presence] || ["", a.presence])) + "</div>" +
      (actions ? '<div class="seat-actions">' + actions + "</div>" : "") +
      (a.archetype ? '<div class="sheet-grid"><div><div class="label">资源</div><div class="meters">' + a.resources.map((x, i) => meter(x.name, x.current, x.max, i % 2 === 1)).join("") + "</div>" +
        '<div class="label" style="margin-top:12px">属性</div><div class="attrs">' + a.attributes.map((x) => '<span><b>' + (x.value ?? "—") + "</b>" + esc(x.name) +
          (x.modifier != null ? '<i>' + (x.modifier >= 0 ? "+" : "") + x.modifier + "</i>" : "") + "</span>").join("") + "</div>" +
        (a.traits.length ? '<div class="label" style="margin-top:12px">经历</div><div class="chips">' + a.traits.map((t) => '<span class="tag gold">' + esc(t) + "</span>").join("") + "</div>" : "") +
        (ties ? '<div class="label" style="margin-top:12px">对人物态度的影响</div><div class="chips">' + ties + "</div>" : "") + "</div>" +
        '<div><div class="label">技能 ' + skills.length + "</div>" + (skills.map(entry).join("") || '<div class="hint">无</div>') +
        '<div class="label" style="margin-top:12px">物品 ' + items.length + "</div>" + (items.map(entry).join("") || '<div class="hint">无</div>') + "</div></div>"
        : '<div class="hint" style="margin-top:10px">还没有建卡。玩家可以私聊 bot 发送 /团 职业、/团 选职业 序号 角色名。</div>') + "</article>";
  };
  return '<section>' + section("同桌", { count: actors.length + "/" + r.seat_cap, meta: "角色、技能和物品只在这一桌有效；检定时句末写 [用 名称] 带上技能或物品" }) +
    (actors.length ? '<div class="stack" style="gap:16px">' + actors.map(card).join("") + "</div>" : empty("还没有人入座")) + "</section>";
}

function peopleSection(r) {
  const scale = (s) => '<span class="scale" title="' + esc(r.adjust_options.standing[s + 3]) + '">' + r.adjust_options.standing.map((label, i) =>
    '<i class="' + (i === s + 3 ? "on" : "") + (i < 3 ? " neg" : i > 3 ? " pos" : "") + '"></i>').join("") + "</span>";
  return '<section>' + section("人物与关系", { count: r.people.length, meta: "态度针对整个队伍；后面的数字是每位玩家带来的升降" }) +
    (r.people.length ? '<div class="rows">' + r.people.map((p) => '<div class="ri person" style="align-items:start">' + roundIcon(p.kind === "faction" ? "flag" : "user", p.standing > 0 ? "" : p.standing < 0 ? "err" : "mute") +
      '<div style="min-width:0"><div class="ri-title">' + esc(p.name) + '　<span class="muted" style="font-weight:400;font-size:12.5px">' + esc(p.kind === "faction" ? "势力" : "人物") + (p.seq ? " · #" + p.seq : "") + "</span></div>" +
      (p.description ? '<div class="ri-meta">' + esc(p.description) + (p.motivation ? " · 动机：" + esc(p.motivation) : "") + "</div>" : "") +
      (Object.keys(p.contributions).length ? '<div class="chips" style="margin-top:6px">' + Object.entries(p.contributions).map(([who, v]) => '<span class="tag' + (v > 0 ? " gold" : "") + '">' + esc(who) + " " + (v > 0 ? "+" : "") + v + "</span>").join("") + "</div>" : "") +
      (p.memories.length ? '<div class="hint" style="margin-top:6px">' + p.memories.slice(-3).map((m) => esc(m.who + "：" + m.text) + (m.change ? "（" + (m.change > 0 ? "+" : "") + m.change + "）" : "")).join("　") + "</div>" : "") +
      '</div><div class="ri-side" style="flex-direction:column;align-items:flex-end;gap:4px">' + scale(p.standing) + '<span class="serif" style="font-size:15px;color:var(--text)">' + esc(p.tier) + "</span></div></div>").join("") + "</div>"
      : empty("还没有遇到任何人", "剧情里出现的人物会自动记录；玩家用 /团 关系 人物 名字：做法 争取态度")) + "</section>";
}


function sceneSection(r) {
  if (!r.scene?.title && !r.npcs.length && !r.facts.length) return "";
  return '<section>' + section("场景资料", { meta: "模型记住的人物与事实" }) +
    (r.scene?.title ? '<div class="serif" style="font-size:17px;font-weight:600">' + esc(r.scene.title) + '</div><p class="muted serif" style="margin:6px 0 0;line-height:1.8">' + esc(r.scene.description || "") + "</p>" : "") +
    (r.npcs.length ? '<div class="rows" style="margin-top:18px">' + r.npcs.slice(0, 8).map((n) => '<div class="ri">' + roundIcon("user", "mute") + '<div style="min-width:0"><div class="ri-title">' + esc(n.name) +
      '</div><div class="ri-meta">' + esc(n.description) + "</div></div><span></span></div>").join("") + "</div>" : "") +
    (r.facts.length ? '<details style="margin-top:16px"><summary>已确立的事实 ' + r.facts.length + ' 条</summary><ul style="margin:10px 0 0;padding-left:18px;line-height:1.9">' +
      r.facts.map((f) => "<li>" + esc(f.text) + "</li>").join("") + "</ul></details>" : "") + "</section>";
}

