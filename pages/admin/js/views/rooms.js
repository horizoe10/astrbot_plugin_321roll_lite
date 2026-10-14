import { NARRATION, acts, avatar, brief, busy, cells, clock, d20, dot, empty, esc, figure, fmt, hero, icon, meter, narrationHint, narrationLabel, notch, outcomeBar, outcomeLabel, ring, roomDot,
  paintArt, roomArt, roundIcon, section, seats, shortTitle, stamps, standing, subTitle, tug, until, veiled, when } from "../ui.js";
import { tableCard } from "./overview.js";

const FILTERS = [["open", "进行中", ["lobby", "running", "paused", "ended"]], ["running", "正在演", ["running"]], ["lobby", "筹备中", ["lobby"]],
  ["paused", "已暂停", ["paused"]], ["shelved", "已暂存", ["shelved"]], ["ended", "已完结", ["ended"]], ["closed", "已收桌", ["closed"]], ["", "全部", null]];
const EVENT_KIND = { narration: "叙事", action: "行动", check: "检定", play: "玩法", vote: "表决", system: "系统", host: "主持" };
const EVENT_ICON = { narration: "feather", action: "user", check: "dice", play: "layers", vote: "vote", system: "sparkle", host: "wand" };
const NUMERALS = "一二三四五六七八九十";
const actName = (n) => "第" + (NUMERALS[n - 1] || n) + "幕";
const signed = (v) => (v > 0 ? "+" : "") + v;
const STEP_STATE = { done: "已完成", failed: "失败", open: "待执行" };
const TITLE_KEYS = ["title", "topic", "subject", "question", "stake", "speaker", "counterpart", "opponent", "quarry", "companion"];
const RECORD_ICON = { clue: "search", hypothesis: "sparkle", testimony: "quote", negotiation: "scroll", relation: "users", companion_goal: "flag", deadline: "clock",
  project: "grid", contest: "bolt", joint: "shield", plan: "map", oracle: "eye", transformation: "wand", fortune: "dice", branch: "flag", ending: "book" };

// Per-seat host actions on the seat cards: [command, label, confirm text]
const SEAT_ACTIONS = [["主持 轮到", "轮到他"], ["主持 暂离", "设为暂离"], ["主持 返回", "回到队列"], ["主持 退回", "退回重建", "收回这个角色，请玩家重新建卡？"],
  ["主持 人设 清除", "清除人设", "清除这位玩家带的人设？从下一段正文起 AI 只按职业来写这个角色。"],
  ["主持 交棒", "交棒给他", "把主持人交给这位玩家？后台操作会立即生效。"], ["主持 移出", "请离", "请这位玩家离开这一桌？之后需要放行才能再入座。"]];

// One receipt per table survives ctx.refresh; nothing is persisted outside this page session.
const roomLogs = new Map();
const renderOwners = new WeakMap();
const readLog = (id) => roomLogs.get(id);
function saveLog(log) {
  roomLogs.delete(log.id);
  roomLogs.set(log.id, log);
  while (roomLogs.size > 12) roomLogs.delete(roomLogs.keys().next().value);
}
function resultBody(log) {
  if (!log) return "";
  const status = log.status;
  const title = { success: "操作已完成", rejected: "操作未获通过", error: "操作返回错误", unknown: "未收到操作结果", legacy: "已收到操作回复" }[status] || "已收到操作回复";
  const delivery = { sent: "群聊通知已发送", pending: "群聊通知待补发；请勿因此重复提交操作", none: "本次无群聊通知" }[log.delivery] || "群聊通知状态未提供";
  return '<div class="result-head"><h2>' + esc(title) + '</h2><span>' + esc(log.command) + '</span><button type="button" class="btn text" data-result-refresh>刷新核对状态</button></div>' +
    '<div class="result-messages">' + esc((log.messages || []).join("\n\n")) + '</div>' +
    (log.progress ? '<p class="result-progress">' + esc(log.progress) + '</p>' : '') +
    '<p class="result-delivery' + (log.delivery === "pending" ? ' pending' : '') + '">' + esc(delivery) + '</p>';
}
function resultSection(id) {
  const log = readLog(id), alert = log && ["rejected", "error", "unknown"].includes(log.status);
  return '<section class="room-result" data-room-result data-status="' + esc(log?.status || "") + '" role="' + (alert ? 'alert' : 'status') + '" aria-atomic="true"' + (log ? '' : ' hidden') + '>' + resultBody(log) + '</section>';
}
function showResult(ctx, log) {
  saveLog(log);
  if (!ctx.isCurrent()) return;
  const slot = ctx.root.querySelector('[data-room-result]');
  if (!slot) return;
  slot.hidden = false;
  slot.dataset.status = log.status;
  slot.setAttribute('role', ["rejected", "error", "unknown"].includes(log.status) ? 'alert' : 'status');
  slot.innerHTML = resultBody(log);
  bindResult(ctx);
  // A rejected form can be far below the page header; reveal its receipt without rebuilding the form.
  if (log.status !== 'success') slot.scrollIntoView?.({ block: 'nearest', behavior: 'auto' });
}
function bindResult(ctx) {
  ctx.root.querySelector('[data-result-refresh]')?.addEventListener('click', () => { if (ctx.isCurrent()) ctx.refresh(); });
}
function responseLog(r, label, result) {
  const status = ["success", "rejected", "error"].includes(result?.status) ? result.status : "legacy";
  const messages = (Array.isArray(result?.messages) ? result.messages : []).map(String);
  const reason = result?.reason || result?.error || result?.message;
  if (reason && !messages.includes(String(reason))) messages.unshift(String(reason));
  if (!messages.length) messages.push(status === "success" ? label : status === "legacy" ? "回复未提供明确执行状态，请刷新核对后再决定是否重试。" : "未提供具体原因，请核对当前桌状态后再试。");
  return { id: r.id, command: label, status, delivery: result?.delivery, messages };
}
async function requestResult(ctx, r, endpoint, payload, label) {
  try { return responseLog(r, label, await ctx.api.post(endpoint, { id: r.id, ...payload })); }
  catch (error) {
    return { id: r.id, command: label, status: "unknown", messages: ["未收到操作结果，操作可能已执行。请先核对当前桌状态，不要直接重复提交。", String(error.message || error)] };
  }
}
function finishResult(ctx, log, { closeTool = false, done = "" } = {}) {
  showResult(ctx, log);
  if (!ctx.isCurrent()) return;
  if (log.status === "success") {
    if (closeTool && consoleView.id === log.id) consoleView.tool = null;
    ctx.toast(done || "已完成：" + log.command);
    ctx.refresh();
  } else if (log.status === "legacy") ctx.toast("已收到操作回复");
}
async function roomPost(ctx, r, button, endpoint, payload, label, options = {}) {
  const log = await busy(button, () => requestResult(ctx, r, endpoint, payload, label));
  finishResult(ctx, log, options);
  return log;
}
const remaining = (deadline) => (deadline ? Math.max(0, (new Date(deadline).getTime() - Date.now()) / 1000) : null);
const WORLD_KINDS = { pace_push: "世界推进", world_pulse: "世界脉冲", host_advance: "主持人推进" };
const limitText = (s) => (!s ? "不限时" : s % 60 ? s + " 秒" : s / 60 + " 分钟");

export async function render(root, ctx) {
  const owner = Symbol(), hash = window.location.hash;
  renderOwners.set(root, owner);
  ctx = { ...ctx, root, isCurrent: () => renderOwners.get(root) === owner && window.location.hash === hash };
  if (ctx.route.rest[0]) return detail(root, ctx, ctx.route.rest[0]);
  const state = ctx.route.params.state ?? "open";
  const q = ctx.route.params.q || "";
  const data = await ctx.api.get("rooms", { state, q }).catch((error) => { if (ctx.isCurrent()) throw error; });
  if (!ctx.isCurrent()) return;
  const n = data.counts || {};
  const count = (states) => (states ? states.reduce((s, k) => s + (n[k] || 0), 0) : Object.values(n).reduce((s, v) => s + v, 0));
  root.innerHTML = hero({
    eyebrow: "团桌 · TABLES", title: "团桌",
    lead: "每个群同时启用一桌。想换个世界，可以先暂存整桌进度，以后取回继续。暂存的故事在「已暂存」里。",
    figures: '<div class="figures">' + figure(n.running || 0, "正在演") + figure(n.lobby || 0, "筹备中", "plain") + figure(n.paused || 0, "已暂停", "plain") + figure((n.ended || 0) + (n.closed || 0), "完结与收桌", "plain") + "</div>",
  }) +
    '<div class="row between wrap" style="border-bottom:1px solid var(--line);margin-bottom:28px;align-items:flex-end"><nav class="tabs" style="border:0;margin:0">' +
    FILTERS.map(([key, label, states]) => '<button data-state="' + key + '" aria-pressed="' + (key === state) + '">' + label + '<span class="count">' + count(states) + "</span></button>").join("") + "</nav>" +
    '<form class="search" data-search style="width:260px;margin-bottom:10px">' + icon("search", 15) + '<input class="input" name="q" placeholder="搜索标题或群号" value="' + esc(q) + '" /></form></div>' +
    (data.rooms.length ? '<div class="cards">' + data.rooms.map(tableCard).join("") + "</div>" : empty("没有符合条件的团桌", "管理员在群里发送 /团 开启 开一桌"));
  const nav = (s, query) => ctx.go("rooms?" + new URLSearchParams({ state: s, ...(query ? { q: query } : {}) }));
  root.querySelectorAll("[data-state]").forEach((b) => b.addEventListener("click", () => nav(b.dataset.state, q)));
  root.querySelector("[data-search]").addEventListener("submit", (e) => { e.preventDefault(); nav(state, e.target.q.value.trim()); });
  paintArt(root, ctx.api);
}

function recordTitle(doc) {
  for (const key of TITLE_KEYS) if (typeof doc[key] === "string" && doc[key].trim()) return doc[key].trim().slice(0, 40);
  return "";
}

// The progress drawn on a record row; ctx carries {members, seq: record id → #, names: actor id → name}.
function recordVisual(r, ctx) {
  const d = r.document;
  if (r.kind === "contest") {
    return '<div class="contest">' + tug(d.ours || 0, d.theirs || 0, d.length || 4) + '<div class="tug-cap"><span>我方</span><span>先到 ' + (d.length || 4) +
      (d.procedure === "chase" && (d.gap ?? d.distance) != null ? " · 距离 " + esc(d.gap ?? d.distance) : "") + "</span><span>" + esc(d.opponent || "对方") + "</span></div></div>";
  }
  if (r.kind === "project") return cells(d.progress || 0, d.segments || 0) + ' <span class="num muted">' + (d.progress || 0) + "/" + d.segments + "</span>";
  if (r.kind === "joint") return stamps((d.roster || []).length, d.size || 0);
  if (r.kind === "branch") return seats((d.votes || []).length, ctx.members);
  if (r.kind === "hypothesis") return versus(d, ctx.seq);
  if (r.kind === "plan" && (d.steps || []).length) return chain(d.steps, ctx.names, true);
  if (r.kind === "negotiation" && (d.terms || []).length) {
    const signedTerms = d.terms.filter((t) => (t.signatures || []).length).length;
    return cells(signedTerms, d.terms.length) + ' <span class="num muted">' + signedTerms + "/" + d.terms.length + " 条已签</span>";
  }
  return "";
}

/** Hypothesis: clues for on the left, against on the right, each side filling out from the centre. */
function versus(d, seq) {
  const refs = (list) => (list || []).map((i) => seq[i.clue_ref]).filter(Boolean);
  const pro = refs(d.support), con = refs(d.refute), most = Math.max(3, pro.length, con.length);
  const tags = (list, cls) => list.length ? list.map((n) => '<b class="' + cls + '">#' + n + "</b>").join("") : '<span class="faint">无</span>';
  return '<div class="versus"><span class="vs-side">' + tags(pro, "pro") + '</span><div class="vs-bar"><i><span style="width:' + ((pro.length / most) * 100).toFixed(0) +
    '%"></span></i><i><span style="width:' + ((con.length / most) * 100).toFixed(0) + '%"></span></i></div><span class="vs-side">' + tags(con, "con") + "</span>" +
    '<span class="vs-cap">支持 ' + pro.length + "</span><span></span><span class=\"vs-cap\">反驳 " + con.length + "</span></div>";
}

/** Plan steps as a chain of beads: done gold, failed red, claimed outlined, unclaimed dashed. */
function chain(steps, names, compact = false) {
  const state = (s) => (s.status === "done" ? "done" : s.status === "failed" ? "failed" : s.actor_ref ? "claimed" : "open");
  if (compact) return '<span class="chain">' + steps.map((s, i) => (i ? "<i></i>" : "") + '<b class="' + state(s) + '" title="第 ' + (i + 1) + " 步：" + esc(s.text || "") + '">' + (i + 1) + "</b>").join("") + "</span>";
  return '<ol class="chain-list">' + steps.map((s, i) => '<li class="' + state(s) + '"><b>' + (i + 1) + '</b><div><div>' + esc(s.text || "") + '</div><div class="hint">' +
    esc((s.actor_ref ? (names[s.actor_ref] || "已认领") : "无人认领") + " · " + (STEP_STATE[s.status] || s.status || "待执行")) + "</div></div></li>").join("") + "</ol>";
}

async function detail(root, ctx, id) {
  const r = await ctx.api.get("room", { id }).catch((error) => { if (ctx.isCurrent()) throw error; });
  if (!ctx.isCurrent()) return;
  const present = r.actors.filter((a) => a.presence !== "left");
  const away = present.filter((a) => a.presence === "away").length;
  const [actLine, ...leadLines] = String(r.act_heading || "").split("\n");
  const live = ["lobby", "running", "paused"].includes(r.state);
  const story = r.events.find((e) => e.kind === "narration");
  const host = present.find((a) => a.user_id === r.host_user_id);
  const reached = r.state === "lobby" ? 0 : r.act;
  // Acts already played carry how many rounds and checks they took.
  const noted = r.acts.map((a) => {
    const s = (r.stats?.acts || []).find((x) => x.number === a.number);
    return s && (s.rounds || s.checks) ? { ...a, note: s.rounds + " 轮" + (s.checks ? " · " + s.checks + " 次检定" : "") } : a;
  });

  root.innerHTML = '<a class="crumb" href="#/rooms">' + icon("arrow", 14, "flip") + "团桌</a>" +
    '<header class="band tone-' + esc(r.cover.tone) + '" data-mark="' + esc(r.cover.mark) + '"' + roomArt(r) + '><div class="band-top"><div style="min-width:0">' +
      '<div class="eyebrow">' + esc(r.state_label) + " · 群 " + esc(r.group_id || "—") + " · " + esc(r.platform) + "</div><h1>" + esc(shortTitle(r.title)) + '</h1><div class="sub">' + esc(subTitle(r.title)) + "</div>" +
      '<div class="band-meta">' + (r.clock ? "<span>" + icon("clock", 13) + " " + esc(r.clock) + "</span>" : "") + (r.round ? "<span>第 " + r.round + " 轮</span>" : "") +
      (host ? "<span>主持 " + esc(host.user_name) + "</span>" : "") + "<span>" + icon("activity", 13) + " 模型 " + fmt(r.usage.calls) + " 次" + (r.usage.tokens ? " · " + fmt(r.usage.tokens) + " tokens" : "") + "</span></div></div>" +
      '<div style="text-align:right;flex:none"><span class="avatars">' + present.map((a) => avatar(a.name || a.user_name, a.presence === "away" ? "away big" : "big")).join("") + "</span>" +
      '<div class="band-meta" style="justify-content:flex-end;margin-top:10px">' + seats(present.length, r.seat_cap, away) + "<span>" + present.length + "/" + r.seat_cap + " 席</span></div></div></div>" +
      (r.acts.length ? '<div class="band-acts">' + acts(veiled(noted, reached), reached) + "</div>" : "") + "</header>" +
    shelfSection(r) + endedSection(r) + resultSection(r.id) + statsSection(r) +
    '<div class="grid cols-2"><div class="stack" style="gap:52px">' + nowSection(r, actLine, leadLines) + storySection(story) + recordsSection(r, present.length) + timelineSection(r) + "</div>" +
    '<div class="stack" style="gap:52px">' + (live ? consoleSection(r) : "") + peopleSection(r) + sceneSection(r) + "</div></div>" +
    '<div class="sec">' + seatsSection(r, present) + "</div>";

  root.querySelector("[data-export-story]")?.addEventListener("click", async (e) => {
    try {
      await busy(e.currentTarget, () => ctx.api.download("room/story", { id: r.id }, shortTitle(r.title) + ".md"));
      ctx.toast("已导出整本故事");
    } catch (error) { ctx.toast(error.message, "error"); }
  });

  if (r.turn?.deadline_at) {
    ctx.every(1000, () => {
      const slot = root.querySelector("[data-ring]");
      if (slot) slot.innerHTML = ring(remaining(r.turn.deadline_at), r.turn_timeout_seconds, "剩余");
    });
  }
  bindResult(ctx);
  paintArt(root, ctx.api);
  if (live) bindConsole(root, ctx, r);
  root.querySelector('[data-ended-close]')?.addEventListener('click', (e) => {
    if (window.confirm('确定收起这张已完结的桌吗？收桌后本群可以开新桌或取回暂存桌，这桌不再接受指令。')) hostRun(ctx, r, e.currentTarget, '关闭', { label: '收桌' });
  });
  root.querySelector('[data-retrieve]')?.addEventListener('click', (e) => hostRun(ctx, r, e.currentTarget, '取回', { label: '取回团桌' }));
}

function endedSection(r) {
  if (r.state !== 'ended') return '';
  return '<section class="ended-close"><div><h2>故事已完结，桌位仍保留</h2><p>收桌后，本群就能开新桌或取回暂存的故事；这桌的故事仍可查看。</p></div>' +
    '<button type="button" class="btn" data-ended-close>' + icon('door', 16) + '收桌并腾出桌位</button></section>';
}

function shelfSection(r) {
  if (r.state !== 'shelved') return '';
  const active = r.active_table;
  return '<section class="card shelf-panel"><div>' + '<span class="tag">已暂存</span><h2>' + esc(r.shelf?.name || shortTitle(r.title)) +
    '</h2><p>角色、背包、剧情与存档都在这里。取回后进入准备阶段，大家准备好再开演。</p>' +
    (active ? '<p>本群桌位仍由 <a href="#/rooms/' + esc(encodeURIComponent(active.id)) + '">《' + esc(shortTitle(active.title)) + '》</a>占用。' +
      (active.state === 'ended' ? '这桌已完结，请先前往当前桌收桌，再回来取回。' : '请先前往当前桌暂存或收桌，再回来取回。') + '这里不会自动收起其他桌。</p>' : '<p>本群桌位空闲，可以取回这段故事。</p>') +
    '</div><button type="button" class="btn primary" data-retrieve' + (active ? ' disabled' : '') + '>' + icon('folder', 16) + '取回团桌</button></section>';
}

/** A small ring for a share, with the figure in the middle. */
function gauge(share, text, caption) {
  const r = 26, length = 2 * Math.PI * r;
  return '<div class="gauge"><svg viewBox="0 0 64 64"><circle class="track" cx="32" cy="32" r="' + r + '"/><circle class="arc" cx="32" cy="32" r="' + r + '" stroke-dasharray="' +
    length.toFixed(1) + '" stroke-dashoffset="' + (length * (1 - Math.max(0, Math.min(1, share)))).toFixed(1) + '"/></svg><b>' + esc(text) + "</b><span>" + esc(caption) + "</span></div>";
}

/** The table at a glance: rounds, checks and how they went, and the favourite so far. */
function statsSection(r) {
  const s = r.stats;
  if (!s || r.state === "lobby") return "";
  const wins = (s.outcomes.critical || 0) + (s.outcomes.success || 0);
  const cell = (value, label, cls = "") => '<div class="ts-fig ' + cls + '"><b>' + esc(value) + "</b><span>" + esc(label) + "</span></div>";
  return '<section class="tstats">' + '<div class="ts-figs">' + cell(s.rounds, "已进行轮数") + cell(s.checks, "次检定") +
    gauge(s.checks ? wins / s.checks : 0, s.checks ? Math.round((wins / s.checks) * 100) + "%" : "—", "成功率") +
    cell(s.outcomes.critical || 0, "大成功", "o-critical") + cell(s.outcomes.fumble || 0, "大失败", "o-fumble") + cell(fmt(r.usage.calls), "次模型调用", "plain") + "</div>" +
    '<div class="ts-dist"><div class="label">检定结果</div>' + outcomeBar(s.outcomes) +
    (s.best ? '<div class="ts-best">' + icon("heart", 13) + "全场最佳　<b>" + esc(s.best) + "</b></div>" : "") + "</div></section>";
}

function nowSection(r, actLine, leadLines) {
  if (r.state === 'shelved') return '';
  const t = r.turn, v = r.vote;
  const states = { awaiting: "等待行动", resolving: "结算中", narration_failed: "正文待重试", review: "正文待主持人审阅" };
  let html = '<section>' + section("此刻", { meta: [r.scene?.title ? icon("map", 13) + " " + esc(r.scene.title) : "", r.goal ? icon("flag", 13) + " " + esc(r.goal) : ""].filter(Boolean).join('<i class="sep">·</i>') || esc(actLine || "") });
  const s = r.stage;
  if (!t && s && (s.key === "epilogue" || s.key === "finale")) {
    const epi = s.key === "epilogue";
    const face = epi && s.deadline_at ? ring(remaining(s.deadline_at), 300, "剩余")
      : '<div class="turn-face">' + avatar(epi ? "尾" : "终", "huge now") + "<small>" + icon(epi ? "pause" : "feather", 12) + (epi ? "暂停中" : "生成中") + "</small></div>";
    html += '<div class="card"><div class="turn">' + face + '<div><div class="label">' + (epi ? "终章之后" : "故事收束") + '</div><div class="turn-who">' + esc(epi ? "征集尾声" : s.label) + "</div>" +
      dot(epi ? "gold" : "warn", s.detail) + '<div class="hint" style="margin:8px 0 0">' + (epi ? "玩家发送 /团 尾声 一句话；全员写完或时间一到，故事自动落幕" : "写完后自动开始征集尾声") + "</div></div></div>" +
      (epi ? '<div class="row" style="margin-top:14px"><button class="btn small" type="button" data-pace-cmd="完结" data-confirm="不等尾声，直接落幕？">' + icon("flag", 14) + "直接落幕</button></div>" : "") + "</div>";
  } else if (!t) {
    html += '<div class="card">' + empty(r.state === "lobby" ? "还没开演" : "没有进行中的回合", r.state === "lobby" ? "主持人发送 /团 开演 后开始第一轮" : "") + "</div>";
  } else {
    const face = t.deadline_at ? '<div data-ring>' + ring(remaining(t.deadline_at), r.turn_timeout_seconds, "剩余") + "</div>"
      : '<div class="turn-face">' + avatar(t.actor, "huge now") + "<small>" + icon("hourglass", 12) + "不限时</small></div>";
    html += '<div class="card"><div class="turn">' + face +
      '<div><div class="label">第 ' + t.round + ' 轮 · 轮到</div><div class="turn-who">' + esc(t.actor) + "</div>" + dot(t.state === "awaiting" ? "gold" : t.state === "narration_failed" ? "err" : "warn", states[t.state] || t.state) +
      '<div class="hint" style="margin:8px 0 0">回合限时 ' + limitText(r.turn_timeout_seconds) + (r.turn_timeout_own ? "（本桌设置）" : "（跟随全局）") + "</div></div></div>" +
      (t.state === "narration_failed" ? '<div class="pace-stage"><b>' + icon("alert", 15) + (t.kind === "finale" ? "终章没写出来" : WORLD_KINDS[t.kind] ? WORLD_KINDS[t.kind] + "没写出来" : "正文没写出来") + "</b><span>" +
        (t.kind === "finale" ? "重试终章，或跳过终章直接征集尾声" : WORLD_KINDS[t.kind] ? "重试，或跳过这段、直接轮到 " + esc(t.actor) : "重试，或跳过、直接轮到下一位") + "</span></div>" +
        '<div class="row"><button class="btn small primary" type="button" data-pace-cmd="主持 重试">' + icon("refresh", 14) + "重试</button>" +
        '<button class="btn small" type="button" data-pace-cmd="主持 跳过" data-confirm="' + (t.kind === "finale" ? "不写终章，直接征集尾声？" : "跳过这一段？") + '">跳过</button></div>' : "") +
      (t.choices.length ? '<div class="choices">' + t.choices.map((c) => '<div class="choice"><b>' + esc(c.label) + "</b><span>" + esc(c.text) + "</span>" + (c.tag ? '<span class="tag">' + esc(c.tag) + "</span>" : "") + "</div>").join("") + "</div>" : "") + "</div>";
    if (t.draft) {
      html += '<div class="card draft" style="margin-top:16px"><div class="panel-head"><h3 class="panel-title">' + icon("eye", 16) + ' 正文草稿 · 待审阅</h3><span class="hint">玩家还看不到这段</span></div>' +
        '<div class="prose serif">' + t.draft.paragraphs.map((p) => "<p>" + esc(p) + "</p>").join("") + "</div>" +
        (t.draft.suggestions.length ? '<div class="choices">' + t.draft.suggestions.map((s, i) => '<div class="choice"><b>' + "ABCD"[i] + "</b><span>" + esc(s) + "</span></div>").join("") + "</div>" : "") +
        '<form class="narr-style" data-rewrite style="margin-top:14px"><button class="btn primary" type="button" data-publish>' + icon("send", 14) + "发布到群里</button>" +
        '<input class="input" name="note" maxlength="300" placeholder="不满意？写下重写意见（可不填）" /><button class="btn" type="submit">' + icon("refresh", 14) + "重写</button></form></div>";
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
  const exportButton = story ? '<button class="btn small" type="button" data-export-story title="按幕整理成 Markdown，含每轮行动、检定、正文和结局">' + icon("download", 14) + "导出整本故事</button>" : "";
  return '<section>' + section("最近的故事", { meta: story ? esc(when(story.created_at)) + " · 模型写下的最新一段" : "", extra: exportButton }) +
    (story ? '<div class="prose initial">' + esc(brief(story.text)) + "</div>" : empty("还没有正文", "第一位玩家行动后会出现在这里")) + "</section>";
}

function recordsSection(r, members) {
  const ctx = { members, seq: Object.fromEntries(r.records.map((x) => [x.id, x.seq])), names: Object.fromEntries(r.actors.map((a) => [a.id, a.name || a.user_name])) };
  const groups = r.play_groups.map((g) => ({ ...g, records: r.records.filter((x) => g.kinds.includes(x.kind)) })).filter((g) => g.records.length);
  const row = (x) => '<details class="record-d"><summary class="record"><span class="seq">#' + x.seq + '</span><div style="min-width:0"><div class="title">' + icon(RECORD_ICON[x.kind] || "layers", 14) + " " +
    esc(x.kind_label) + "「" + esc(recordTitle(x.document)) + '」</div><div class="meta">' + esc(x.state_label) + " · " + esc(when(x.updated_at)) + '</div></div><div class="record-vis">' + recordVisual(x, ctx) + "</div></summary>" +
    '<div class="record-body">' + recordBody(x, ctx) + (x.steps.length ? '<div class="label" style="margin-top:10px">接下来可以</div><ul class="steps">' + x.steps.map((s) => "<li>" + esc(s) + "</li>").join("") + "</ul>" : "") + "</div></details>";
  return '<section>' + section("玩法记录", { count: r.records.length, meta: "按玩法分组；点开一条看完整内容和群里的下一步" }) +
    (groups.length ? groups.map((g) => '<div class="rgroup"><div class="rgroup-title">' + esc(g.label) + '<span class="num muted">' + g.records.length + "</span></div>" + g.records.slice(0, 20).map(row).join("") + "</div>").join("")
      : empty("还没有玩法记录", "线索、交涉、对抗、计划等玩法会出现在这里")) + "</section>";
}

function recordBody(x, ctx) {
  const d = x.document, lines = [];
  for (const key of ["text", "goal", "description", "change", "stakes", "stance", "topic", "premise", "argument", "question", "answer_label", "use"]) {
    if (typeof d[key] === "string" && d[key].trim()) lines.push('<p class="quote" style="margin:6px 0">' + esc(d[key]) + "</p>");
  }
  if (Array.isArray(d.terms) && d.terms.length) lines.push('<div class="label">条款</div><ul class="steps">' + d.terms.map((t, i) => "<li>" + (i + 1) + ". " + esc(t.text) + "（" + (t.signatures || []).length + " 人签署）</li>").join("") + "</ul>");
  if (Array.isArray(d.steps) && d.steps.length) lines.push('<div class="label">步骤</div>' + chain(d.steps, ctx.names));
  if (Array.isArray(d.memories) && d.memories.length) lines.push('<div class="label">往来</div><ul class="steps">' + d.memories.map((m) => "<li>" + esc(m.text) + (m.change ? "（" + (m.change > 0 ? "+" : "") + m.change + "）" : "") + "</li>").join("") + "</ul>");
  return lines.join("") || '<div class="hint">' + esc(x.line) + "</div>";
}

function adjustSection(r) {
  const actors = r.actors.filter((a) => a.presence !== "left" && a.archetype);
  const o = r.adjust_options;
  const pending = r.adjustments.filter((a) => a.state === "pending"), done = r.adjustments.filter((a) => a.state !== "pending").slice(0, 5);
  const opts = (list) => list.map((x) => '<option value="' + esc(x.id) + '">' + esc(x.name) + "</option>").join("");
  return '<div class="pane-block">' + paneHead("主持调整", { meta: "提交后不会立刻生效，要等模型写完下一回合的正文后才生效，并在群里公布" }) + '<div class="card">' +
    '<form data-adjust class="adjust-form"><div class="grid" style="grid-template-columns:1fr 1fr;gap:10px">' +
    '<label class="field"><span class="label">调整什么</span><select class="select" name="kind"><option value="resource">资源</option><option value="item">物品数量</option>' + (o.money ? '<option value="money">钱（' + esc(r.economy.currency) + '）</option>' : "") +
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
    "</div></div>";
}

// Narration settings: each one follows the world value copied when the table opened, or is set for this table.

// Pacing (roll_lite/plays/pacing.py): rounds in this scene, act and story; the same commands as /团 主持 节奏 and /团 主持 收尾.
function paceTrack(label, sub, done, limit, extra, note, end = 0) {
  if (!limit) return '<div class="pace-track off"><div class="pace-head"><b>' + esc(label) + "</b><span>" + esc(sub) + '</span><em class="num">' + done + " 轮 · 不催</em></div><div class=\"pace-bar\"></div></div>";
  const last = end || limit + extra, top = Math.max(last, done, 1);
  const cls = done >= last ? " over" : done >= limit ? " due" : "";
  return '<div class="pace-track' + cls + '"><div class="pace-head"><b>' + esc(label) + "</b><span>" + esc(sub) + '</span><em class="num">' + done + "<small>/" + limit + " 轮</small></em></div>" +
    '<div class="pace-bar"><i style="width:' + Math.min(100, (done / top) * 100).toFixed(1) + '%"></i><s style="left:' + ((limit / top) * 100).toFixed(1) + '%"></s></div>' +
    '<div class="pace-note">' + esc(note) + "</div></div>";
}

function pacingSection(r) {
  const p = r.pacing;
  if (!p) return "";
  const sc = p.scene, ac = p.act, st = p.story, g = p.grace;
  const tracks = paceTrack("场景", sc.title, sc.done, sc.limit, g, "满 " + sc.limit + " 轮起正文让局面变化，" + (sc.limit + g) + " 轮世界自己推进") +
    paceTrack("第 " + ac.number + " 幕", ac.title, ac.done, ac.limit, g, ac.last ? "最后一幕：满 " + ac.limit + " 轮提议收尾" : "满 " + ac.limit + " 轮提议换幕，" + (ac.limit + g) + " 轮自动进入") +
    paceTrack("全程", "", st.done, st.target, 0, "满 " + st.target + " 轮提议收尾" + (st.hard ? "，" + st.hard + " 轮必定收尾" : ""), st.hard);
  const presets = [["短", "短"], ["标准", "标准"], ["长", "长"]];
  const at = presets.findIndex(([v]) => v === p.preset);
  const notchHtml = '<div class="notch" style="--n:3;--from:0;--to:' + Math.max(0, at) + '"><div class="notch-track"><i class="notch-fill"></i>' +
    presets.map(([v, l], i) => '<button type="button" class="' + (i === at ? "on" : i < at ? "past" : "") + '" data-pace-cmd="主持 节奏 ' + v + '" title="' + l + '"><span></span></button>').join("") +
    '</div><div class="notch-labels">' + presets.map(([, l], i) => '<span class="' + (i === at ? "on" : "") + '">' + l + "</span>").join("") + "</div></div>";
  const num = (name, label, value, top) => '<label class="field"><span class="label">' + label + '</span><input class="input num" type="number" min="0" max="' + top + '" name="' + name + '" value="' + value + '" /></label>';
  const pending = p.state && (p.state.label === "本幕将尽" || (p.state.label === "局势在酝酿" && sc.limit && sc.done >= sc.limit));
  let closing;
  if (p.epilogue) {
    closing = '<div class="pace-stage"><b>' + icon("feather", 15) + "征集尾声</b><span>" + (p.epilogue.title ? "结局「" + esc(p.epilogue.title) + "」 · " : "") + "已写 " + p.epilogue.written + " 人，到点自动落幕</span></div>" +
      '<div class="row"><button class="btn small" type="button" data-pace-cmd="完结" data-confirm="不等尾声，直接落幕？">' + icon("flag", 14) + "直接落幕</button></div>";
  } else if (p.closing) {
    closing = '<div class="pace-stage"><b>' + icon("flag", 15) + "收尾阶段</b><span>" + (p.closing.title ? "结局「" + esc(p.closing.title) + "」 · " : "") + "第 " + p.closing.until + " 轮写终章</span></div>" +
      '<div class="row"><button class="btn small primary" type="button" data-pace-cmd="主持 收尾 终章" data-confirm="现在就写终章？">立刻写终章</button><button class="btn small" type="button" data-pace-cmd="主持 收尾 取消">取消收尾</button></div>';
  } else {
    closing = (p.offer ? '<div class="pace-stage"><b>' + icon("vote", 15) + "收尾提议</b><span>" + (p.offer.title ? "「" + esc(p.offer.title) + "」 · " : "") + esc(p.offer.source) + " · 同意 " + p.offer.yes + " · 再玩 " + p.offer.no + "</span></div>" : "") +
      '<form class="narr-style" data-pace-close><input class="input" maxlength="24" name="ending" value="' + esc(p.offer?.title || "") + '" placeholder="结局名（可不填，由故事决定）" /><button class="btn primary" type="submit">开始收尾</button>' +
      (p.offer ? '<button class="btn" type="button" data-pace-cmd="主持 收尾 取消">驳回提议</button>' : "") + "</form>";
  }
  return '<div class="pane-block">' + paneHead("节奏与收尾", { meta: "按轮计：在座的人各行动一次算一轮；结果发往群聊" }) + '<div class="card narr">' +
    '<div class="pace-tracks">' + tracks + "</div>" +
    (p.state ? '<div class="pace-stage soft"><b>' + icon("hourglass", 15) + esc(p.state.label) + "</b><span>" + esc(p.state.detail) + "</span></div>" : "") +
    '<div class="narr-row"><div class="narr-head"><b>整体节奏</b><span class="now">' + esc(p.preset) + "档" + (p.off ? " · 自动推进已关闭" : "") + '</span><span class="spacer"></span><span class="narr-src">' + esc(p.source) + "</span></div>" + notchHtml +
    '<p class="narr-hint">短档各层轮数约为四分之三，长档放长一半；主持人可以调长，也可以调短。</p></div>' +
    '<div class="narr-row"><div class="narr-head"><b>各层轮数</b><span class="spacer"></span></div><form class="pace-nums" data-pace-nums>' +
    num("场景", "场景", sc.limit, 100) + num("每幕", "每幕", ac.limit, 100) + num("全程", "全程", st.target, 1000) + num("上限", "上限", st.hard, 1000) +
    '<button class="btn" type="submit">应用</button></form><p class="narr-hint">0 表示这一层不催。上限到了会直接进入收尾。</p>' +
    '<div class="row" style="gap:8px;margin-top:10px">' + (pending ? '<button class="btn small" type="button" data-pace-cmd="主持 节奏 延后">' + icon("clock", 14) + "延后 " + g + " 轮</button>" : "") +
    '<button class="btn small" type="button" data-pace-cmd="主持 节奏 ' + (p.off ? "开" : "关") + '">' + (p.off ? "开启自动推进" : "关闭自动推进") + "</button>" +
    (p.source === "主持人调整" ? '<button class="btn small" type="button" data-pace-cmd="主持 节奏 默认">' + icon("refresh", 14) + "恢复世界设置</button>" : "") + "</div></div>" +
    '<div class="narr-row"><div class="narr-head"><b>收尾</b><span class="spacer"></span><span class="narr-src">' + (p.ending ? "收尾提议开启" : "世界关闭了自动收尾提议") + "</span></div>" + closing + "</div>" +
    "</div></div>";
}

function bindPacing(root, ctx, r) {
  if (!r.pacing) return;
  const run = (button, command, done) => hostRun(ctx, r, button, command, { done });
  root.querySelectorAll("[data-pace-cmd]").forEach((b) => b.addEventListener("click", () => {
    if (b.classList.contains("on")) return;
    if (b.dataset.confirm && !window.confirm(b.dataset.confirm)) return;
    run(b, b.dataset.paceCmd);
  }));
  const nums = root.querySelector("[data-pace-nums]");
  nums?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const now = { 场景: r.pacing.scene.limit, 每幕: r.pacing.act.limit, 全程: r.pacing.story.target, 上限: r.pacing.story.hard };
    const field = (k) => nums.elements.namedItem(k);
    const changed = Object.keys(now).filter((k) => field(k).value !== "" && Number(field(k).value) !== now[k]);
    if (!changed.length) return ctx.toast("轮数没有变化");
    const button = nums.querySelector("[type=submit]");
    const edits = changed.map((k) => ({ key: k, value: Number(field(k).value) }));
    const completed = [], replies = [];
    const log = await busy(button, async () => {
      for (const edit of edits) {
        const label = edit.key + ' ' + edit.value + ' 轮';
        const reply = await requestResult(ctx, r, 'room/command', { command: '主持 节奏 ' + edit.key + ' ' + edit.value }, label);
        replies.push(reply);
        if (reply.status !== 'success') return { ...reply, command: '批量调整节奏', progress: '已确认完成：' + (completed.join('、') || '无') + '。已停止；本项「' + label + '」未确认完成，其余 ' + (edits.length - replies.length) + ' 项未提交。' };
        completed.push(label);
        // Prevent a retry after a partial result from re-applying an already confirmed edit.
        now[edit.key] = edit.value;
        const targets = { 场景: [r.pacing.scene, 'limit'], 每幕: [r.pacing.act, 'limit'], 全程: [r.pacing.story, 'target'], 上限: [r.pacing.story, 'hard'] };
        targets[edit.key][0][targets[edit.key][1]] = edit.value;
      }
      return { id: r.id, command: '批量调整节奏', status: 'success', messages: replies.flatMap((reply) => reply.messages),
        delivery: replies.some((reply) => reply.delivery === 'pending') ? 'pending' : replies.every((reply) => ['sent', 'none'].includes(reply.delivery)) ? (replies.some((reply) => reply.delivery === 'sent') ? 'sent' : 'none') : undefined,
        progress: '已确认完成：' + completed.join('、') };
    });
    if (log.status !== 'success' && replies.slice(0, -1).some((reply) => reply.delivery === 'pending')) log.progress += ' 已完成项目中有群聊通知待补发。';
    finishResult(ctx, log, { done: '已调整：' + completed.join('、') });
  });
  const close = root.querySelector("[data-pace-close]");
  close?.addEventListener("submit", (e) => {
    e.preventDefault();
    run(close.querySelector("[type=submit]"), ("主持 收尾 " + close.elements.ending.value.trim()).trim(), "已开始收尾");
  });
}

// Values are read when a narration starts, so a change lands from the next one.
const FALLBACK = { improv: "均衡", dialogue: "dialogue_soft", length: "free" };
function narrationSection(r) {
  const n = r.settings.narration;
  const row = (field) => {
    const d = n[field];
    const hint = d.own ? narrationHint(field, d.value) : d.inherited ? "沿用开桌时的世界默认。" + narrationHint(field, d.value) : "这一桌开桌时世界没有设置，模型按自己的习惯写。";
    return '<div class="narr-row"><div class="narr-head"><b>' + NARRATION[field].title + '</b><span class="now">' + esc(d.value ? narrationLabel(field, d.value) : "未设置") + "</span>" +
      '<span class="spacer"></span><span class="narr-src">' + (d.own ? "本桌设置" : "世界默认") + "</span>" +
      '<label class="narr-own" title="打开后可以单独调整这一桌"><span class="switch"><input type="checkbox" data-own="' + field + '"' + (d.own ? " checked" : "") + " /><span></span></span>自定义</label></div>" +
      notch(field, d.value, { disabled: !d.own }) + '<p class="narr-hint">' + esc(hint) + "</p></div>";
  };
  const world = r.settings.world_style;
  return '<div class="pane-block">' + paneHead("叙事设置", { meta: "改动从下一段正文开始生效" }) + '<div class="card narr">' + ["improv", "dialogue", "length"].map(row).join("") +
    '<div class="narr-row"><div class="narr-head"><b>文笔与基调</b><span class="spacer"></span><span class="narr-src">' + (n.style ? "本桌有补充" : "世界默认") + "</span></div>" +
    (world ? '<div class="narr-sub">世界设定</div><div class="narr-text">' + esc(world) + "</div>" : "") +
    '<div class="narr-sub">本桌补充</div><form class="narr-style" data-style-form><input class="input" data-style-words maxlength="300" value="' + esc(n.style) +
    '" placeholder="例如：多写环境声，少用比喻；留空保存即清除" /><button class="btn primary" type="submit">保存</button></form></div></div></div>';
}

function bindNarration(root, ctx, r) {
  const post = (button, changes, done) => roomPost(ctx, r, button, 'room/narration', { changes }, '叙事设置', { done: done + '，从下一段正文开始生效' });
  root.querySelectorAll("[data-own]").forEach((box) => box.addEventListener("change", () => {
    const field = box.dataset.own, d = r.settings.narration[field];
    post(box, { [field]: box.checked ? d.value || FALLBACK[field] : null }, box.checked ? NARRATION[field].title + "改为本桌设置" : NARRATION[field].title + "恢复世界默认");
  }));
  root.querySelectorAll(".narr .notch [data-field]").forEach((b) => b.addEventListener("click", () => {
    if (!b.classList.contains("on")) post(b, { [b.dataset.field]: b.dataset.value }, NARRATION[b.dataset.field].title + "改为“" + b.title + "”");
  }));
  const form = root.querySelector("[data-style-form]");
  form?.addEventListener("submit", (e) => {
    e.preventDefault();
    const words = form.querySelector("[data-style-words]").value.trim();
    post(form.querySelector("button"), { style: words }, words ? "已保存文笔补充" : "已清除文笔补充");
  });
}

// Build limits: the host may lower the world's limits for this table (same as /团 主持 建卡 …), never raise them.
let reachPick = 0;
function ladder(kind, options, index) {
  const n = options.length;
  return '<div class="notch" style="--n:' + n + ";--from:0;--to:" + Math.max(0, index) + '"><div class="notch-track"><i class="notch-fill"></i>' +
    options.map(([v, l], i) => '<button type="button" class="' + (i === index ? "on" : i < index ? "past" : "") + '" data-create="' + kind + '" data-value="' + esc(v) + '" title="' + esc(l) + '"><span></span></button>').join("") +
    '</div><div class="notch-labels">' + options.map(([, l], i) => '<span class="' + (i === index ? "on" : "") + '">' + esc(l) + "</span>").join("") + "</div></div>";
}

// How far each attribute of one archetype can go when the move limit is used in full (shared with the world editor's look).
function reachHtml(archetypes, move) {
  const arch = archetypes[Math.min(reachPick, archetypes.length - 1)];
  if (!arch) return "";
  return '<div class="chips reach-pick">' + archetypes.map((a, i) => '<button type="button" class="chip small' + (a === arch ? " on" : "") + '" data-reach="' + i + '">' + esc(a.name) + "</button>").join("") + "</div>" +
    '<div class="reach">' + arch.attrs.map((at) => {
      const lo = Math.max(at.min, at.value - move), hi = Math.min(at.max, at.value + move), span = Math.max(1, at.max - at.min);
      const pos = (v) => ((v - at.min) / span) * 100;
      return '<div class="reach-row"><span>' + esc(at.name) + '</span><span class="reach-track"><i style="left:' + pos(lo) + "%;right:" + (100 - pos(hi)) + '%"></i><b style="left:' + pos(at.value) + '%"></b></span>' +
        '<span class="num">' + (lo === hi ? at.value : lo + "–" + hi) + '</span><span class="faint num">' + at.min + "–" + at.max + "</span></div>";
    }).join("") + "</div>";
}

function creationSection(r) {
  const c = r.settings.creation;
  const deepest = c.cap || c.modes[c.modes.length - 1].key;
  const modeIndex = c.modes.findIndex((m) => m.key === deepest);
  const counts = (top, unit) => Array.from({ length: top + 1 }, (_, i) => [String(i), i === top ? i + " " + unit + " · 上限" : String(i)]);
  const src = (own) => '<span class="narr-src">' + (own ? "本桌调低" : "世界设置") + "</span>";
  const row = (title, now, own, body, hint) => '<div class="narr-row"><div class="narr-head"><b>' + title + '</b><span class="now">' + esc(now) + '</span><span class="spacer"></span>' + src(own) + "</div>" +
    body + '<p class="narr-hint">' + esc(hint) + "</p></div>";
  const reach = '<div data-reach-box>' + reachHtml(c.archetypes, c.move) + "</div>";
  const own = Boolean(c.cap) || c.move_own || c.swap_own;
  const forgeNote = c.modes.some((m) => m.key === "forge") && !c.open.includes("forge") && c.cap !== "quick" && c.cap !== "custom" ? "故事已经开始，精雕暂时关闭。" : "";
  return '<div class="pane-block">' + paneHead("建卡设置", { meta: "只能在世界上限内调低；只影响之后建卡或重建的人，结果会发到群里" }) + '<div class="card narr">' +
    row("模式最深", (c.modes.find((m) => m.key === deepest) || {}).label + (c.cap ? "" : "（不限）"), Boolean(c.cap), ladder("mode", c.modes.map((m) => [m.key, m.label]), modeIndex),
      "这个世界开放 " + c.modes.map((m) => m.label).join("、") + "。" + forgeNote) +
    (c.world_move ? row("属性最多挪", c.move + " 点", c.move_own, ladder("move", counts(c.world_move, "点"), c.move) + (c.move ? reach : ""),
      c.move ? "定制和精雕可以在职业属性上加减各 " + c.move + " 点，每项仍不超出属性范围。上面是挪满时各属性能到的范围，圆点是职业原值。" : "调到 0 时不能挪属性，定制和精雕跳过“调整属性”这一步。")
      : row("属性最多挪", "0 点", false, "", "这个世界不允许挪属性。")) +
    (c.world_swap ? row("定制最多换技能", c.swap + " 项", c.swap_own, ladder("swap", counts(c.world_swap, "项"), c.swap),
      c.swap ? "定制可以把职业自带的技能换成技能池里的另一项；精雕不受这项限制。" : "调到 0 时定制跳过“换技能”这一步；精雕仍可从技能池任选。")
      : row("定制最多换技能", "0 项", false, "", "这个世界不允许定制换技能。")) +
    (own ? '<div class="row" style="padding-top:16px"><button class="btn small" type="button" data-create="reset">' + icon("refresh", 14) + "恢复世界设置</button></div>" : "") +
    "</div></div>";
}

function bindCreation(root, ctx, r) {
  const c = r.settings.creation;
  const deepest = c.modes[c.modes.length - 1].key;
  const arg = (kind, value) => kind === "reset" ? "默认" : kind === "mode" ? (value === deepest ? "不限" : c.modes.find((m) => m.key === value).label)
    : (kind === "move" ? "挪点 " : "换技能 ") + value;
  root.querySelectorAll("[data-create]").forEach((b) => b.addEventListener("click", async () => {
    if (b.classList.contains("on")) return;
    hostRun(ctx, r, b, '主持 建卡 ' + arg(b.dataset.create, b.dataset.value), {
      label: '建卡设置', done: b.dataset.create === 'reset' ? '已恢复世界的建卡设置' : '建卡设置已更新，之后建卡的人生效',
    });
  }));
  const box = root.querySelector("[data-reach-box]");
  box?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-reach]");
    if (!b) return;
    reachPick = Number(b.dataset.reach);
    box.innerHTML = reachHtml(c.archetypes, c.move);
  });
}

function bindAdjust(root, ctx, r) {
  const form = root.querySelector("[data-adjust]");
  if (!form) return;
  const fields = { resource: ["actor", "resource", "delta"], item: ["actor", "item", "delta"], money: ["actor", "delta"], skill: ["actor", "skill", "grant"], uses: ["actor", "uses", "value"], attitude: ["subject", "standing"] };
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
    if (k === "money") change.delta = Number(form.delta.value);
    if (k === "skill") Object.assign(change, { ref: form.skill.value, grant: form.grant.value === "1" });
    if (k === "uses") { const [entry, ref] = form.entry.value.split(":"); Object.assign(change, { entry, ref, value: Number(form.value.value) }); }
    if (k === "attitude") Object.assign(change, { subject: form.subject.value.trim(), standing: Number(form.standing.value) });
    roomPost(ctx, r, form.querySelector('[type=submit]'), 'room/adjust', { changes: [change] }, '提交待生效调整（下一回合正文写完后生效）', { done: '已加入待生效，下一回合正文写完后生效' });
  });
  root.querySelectorAll('[data-cancel-adjust]').forEach((b) => b.addEventListener('click', () =>
    roomPost(ctx, r, b, 'room/adjust/cancel', { adjustment: b.dataset.cancelAdjust }, '撤销待生效调整')));
}


function timelineSection(r) {
  // Events arrive newest first with their act and round; consecutive ones of the same round form a group.
  const groups = [];
  for (const e of r.events) {
    const key = e.act == null ? "lobby" : e.act + ":" + e.round;
    if (!groups.length || groups[groups.length - 1].key !== key) groups.push({ key, act: e.act, round: e.round, items: [] });
    groups[groups.length - 1].items.push(e);
  }
  const title = (g) => (g.act == null ? "筹备" : actName(g.act) + " · " + (g.round === 0 ? "开场" : "第 " + g.round + " 轮"));
  const line = (e) => {
    if (e.kind === "chapter") return '<div class="tl-item k-chapter"><i class="tl-dot"></i><div class="tl-chapter">' + icon("book", 13) + esc(e.text.replace("——", "　")) + "</div></div>";
    const c = e.check;
    const who = c ? e.text.split(" ")[0] : "";
    const what = c ? (/【(主持)?检定】([^：]+)：/.exec(e.text) || []) : [];
    return '<div class="tl-item k-' + esc(e.kind) + (c ? " has-check" : "") + '"><i class="tl-dot"></i><div class="tl-body"><span class="tl-kind">' + esc(EVENT_KIND[e.kind] || e.kind) +
      '</span><span class="tl-text' + (e.kind === "narration" ? " serif" : "") + '">' +
      (c ? esc(who) + '<span class="muted"> · ' + esc(what[2] || c.attribute || "") + (what[1] ? " · 主持人要求" : "") + "</span>" : esc(brief(e.text, 220))) + "</span></div>" +
      '<div class="tl-side">' + (c ? d20(c.face, c.outcome) + '<span class="num">' + esc(signed(c.modifier || 0)) + " = <b>" + esc(c.total) + "</b> / " + esc(c.dc) +
        '</span><span class="otag o-' + esc(c.outcome) + '">' + esc(outcomeLabel(c.outcome)) + "</span>" : "") + "<time>" + esc(clock(e.created_at)) + "</time></div></div>";
  };
  const CAP = 6;
  const group = (g) => '<div class="tl-group' + (g.act == null ? " lobby" : "") + '"><div class="tl-head"><b>' + esc(title(g)) + "</b><span>" + g.items.length + ' 条</span><span class="spacer"></span><time>' +
    esc(when(g.items[0].created_at)) + '</time></div><div class="tl-items">' + g.items.slice(0, CAP).map(line).join("") + "</div>" +
    (g.items.length > CAP ? '<details class="tl-rest"><summary>这一轮还有 ' + (g.items.length - CAP) + ' 条</summary><div class="tl-items">' + g.items.slice(CAP).map(line).join("") + "</div></details>" : "") + "</div>";
  const shown = groups.slice(0, 4), rest = groups.slice(4);
  return '<section>' + section("时间线", { count: r.events.length, meta: "按幕与轮次分组，最新的在上" }) +
    (groups.length ? '<div class="timeline">' + shown.map(group).join("") + "</div>" +
      (rest.length ? '<details class="tl-more"><summary>更早的 ' + rest.length + ' 组</summary><div class="timeline">' + rest.map(group).join("") + "</div></details>" : "")
      : empty("暂无事件")) + "</section>";
}

// ---------------------------------------------------------------- host console
// Five panes; the open pane and tool survive the refresh that follows each command on the same table.
const CONSOLE_TABS = [["play", "进行", "play"], ["pace", "节奏", "hourglass"], ["table", "桌务", "users"], ["config", "设置", "sliders"], ["adjust", "调整", "wand"]];
let consoleView = { id: null, tab: "play", tool: null };
// Story tools open a form under the tiles; [key, label, icon]
const PLAY_TOOLS = [["advance", "推进剧情", "wand"], ["narrate", "直述剧情", "feather"], ["check", "要求检定", "dice"],
  ["choices", "改写选项", "list"], ["directive", "私下指引", "eyeOff"], ["act", "换幕", "book"]];
// Turn commands run on a click; [command, label, icon, confirm text]
const PLAY_DIRECT = [["主持 跳过", "跳过回合", "skip"], ["主持 重试", "重试正文", "refresh"],
  ["主持 回退", "回退一步", "hourglass", "撤回最近一步行动？骰子、资源、正文和玩法记录都会回到行动前。"], ["主持 集体事件", "集体事件", "sparkle"], ["主持 结束表决", "结束表决", "vote"]];
const TURN_LIMITS = [["默认", "跟随全局"], ["0", "不限时"], ["2", "2 分"], ["5", "5 分"], ["10", "10 分"], ["30", "30 分"]];
const VOTE_LIMITS = [1, 2, 3, 5, 10];

function paneHead(title, { meta = "", extra = "" } = {}) {
  return '<div class="pane-head"><h3>' + esc(title) + "</h3>" + (meta ? "<span>" + meta + "</span>" : "") + extra + "</div>";
}

function consoleSection(r) {
  if (consoleView.id !== r.id) consoleView = { id: r.id, tab: "play", tool: null };
  const s = r.settings, tab = consoleView.tab;
  const notes = [["eye", "审稿 " + (s.review ? "开启" : "关闭")], ["door", "入座 " + (s.seating_locked ? "已关闭" : "开放")], ["clock", "回合 " + limitText(r.turn_timeout_seconds)],
    ["hourglass", "表决 " + s.vote_minutes + " 分钟"], ["refresh", "可回退 " + s.rewinds + " 步"], ["user", "人设卡 " + (s.personas_off ? "已关闭" : "开放")]]
    .concat(s.rush ? [["bolt", "快团 开启"]] : []).concat(s.xcards ? [["shield", "X 卡 " + s.xcards + " 次"]] : [])
    .concat(s.handover ? [["key", "等待 " + s.handover + " 接棒"]] : []).concat(s.removed.length ? [["user", "已请离 " + s.removed.join("、")]] : []);
  const pane = (key, html) => '<div class="console-pane" data-pane="' + key + '"' + (key === tab ? "" : " hidden") + ">" + html + "</div>";
  return '<section class="console">' + section("主持台", { meta: "以管理员身份执行，结果发往群聊" }) +
    '<div class="host-notes console-notes">' + notes.map(([ic, text]) => "<span>" + icon(ic, 13) + esc(text) + "</span>").join("") + "</div>" +
    '<nav class="tabs console-tabs">' + CONSOLE_TABS.map(([key, label, ic]) => '<button type="button" data-tab="' + key + '" aria-pressed="' + (key === tab) + '">' + icon(ic, 14) + label +
      (key === "adjust" && r.adjustments.some((a) => a.state === "pending") ? '<i class="tab-dot"></i>' : "") + "</button>").join("") + "</nav>" +
    pane("play", playPane(r)) +
    pane("pace", pacingSection(r) || '<div class="card">' + empty("还没开演", "开演后这里显示场景、幕和全程的轮数，以及收尾") + "</div>") +
    pane("table", tablePane(r)) + pane("config", configPane(r) + narrationSection(r) + creationSection(r)) + pane("adjust", adjustSection(r)) +
    "</section>";
}

async function hostRun(ctx, r, button, command, { actors = null, label = "", done = "" } = {}) {
  return roomPost(ctx, r, button, 'room/command', { command, ...(actors ? { actors } : {}) },
    label || command.split(' ').slice(0, 2).join(' '), { closeTool: true, done });
}

// ---- 进行
function playPane(r) {
  const running = r.state === "running", tool = consoleView.tool;
  const usable = (key) => key === "directive" || running;
  const tile = (attrs, ic, label, on, off, mark) => "<button type=\"button\" " + attrs + ' aria-pressed="' + on + '"' + (off ? " disabled" : "") + ">" + icon(ic, 18) + esc(label) +
    (mark ? '<i class="tile-dot" title="' + esc(mark) + '"></i>' : "") + "</button>";
  const tools = PLAY_TOOLS.map(([key, label, ic]) => tile('data-tool="' + key + '"', ic, label, tool === key, !usable(key), key === "directive" && r.directive ? "已有指引" : "")).join("");
  const direct = PLAY_DIRECT.filter(([cmd]) => cmd !== "主持 结束表决" || r.vote).map(([cmd, label, ic, confirm]) =>
    tile('data-run="' + esc(cmd) + '"' + (confirm ? ' data-confirm="' + esc(confirm) + '"' : ""), ic, label + (cmd === "主持 回退" && r.settings.rewinds ? " · " + r.settings.rewinds : ""), false,
      !running || (cmd === "主持 回退" && !r.settings.rewinds), "")).join("");
  return '<div class="pane-block">' + paneHead("一轮之中", { meta: running ? "需要填写的操作会在下方展开" : "开演后才能推进、检定和换幕；私下指引随时可写" }) +
    '<div class="card"><div class="host-group">剧情</div><div class="host-actions">' + tools + '</div><div class="host-group">回合</div><div class="host-actions">' + direct + "</div>" +
    (tool && usable(tool) ? '<div class="tool-pane">' + TOOL_FORMS[tool](r) + "</div>" : "") + "</div></div>";
}

function toolForm(key, body, submit, ic, hint) {
  return '<form class="tool-form" data-tool-form="' + key + '">' + body + '<div class="tool-foot"><span class="hint">' + esc(hint) + '</span><span class="spacer"></span>' +
    '<button class="btn text small" type="button" data-tool-close>收起</button><button class="btn primary" type="submit">' + icon(ic, 14) + esc(submit) + "</button></div></form>";
}
const toolNote = (text) => '<p class="tool-note">' + esc(text) + '</p><div class="tool-foot"><span class="spacer"></span><button class="btn text small" type="button" data-tool-close>收起</button></div>';

const TOOL_FORMS = {
  advance: () => toolForm("advance", '<label class="field"><span class="label">推进说明（可不填）</span><textarea class="input" name="text" rows="2" maxlength="300" placeholder="想让局势往哪里走，例如：巡逻队提前换岗"></textarea></label>',
    "推进剧情", "wand", "以主持人的名义写一段正文，写完回到原来的行动者。"),
  narrate: () => toolForm("narrate", '<label class="field"><span class="label">公开剧情<span class="count"><b data-count>0</b>/1000</span></span><textarea class="input" name="text" rows="4" maxlength="1000" data-counted placeholder="会原样发到群里，并记成剧情事实"></textarea></label>',
    "公开发出", "send", "2–1000 字，之后的正文都以它为准。"),
  directive: (r) => (r.directive ? '<div class="tool-current"><div><span class="label">当前指引</span><p>' + esc(r.directive) + '</p></div><button type="button" class="btn small" data-clear-directive>' + icon("x", 13) + "清除</button></div>" : "") +
    toolForm("directive", '<label class="field"><span class="label">' + (r.directive ? "替换为" : "给叙事模型的指引") + '</span><textarea class="input" name="text" rows="3" maxlength="600" placeholder="只有叙事模型看得到，例如：让管家显得心虚，但先别揭穿"></textarea></label>',
      r.directive ? "替换指引" : "保存指引", "eyeOff", "不会发到群里；一桌只保留一条指引。"),
  choices: (r) => {
    const t = r.turn;
    if (!t || t.state !== "awaiting") return toolNote("现在没有等待行动的回合，轮到下一位时再改选项。");
    return toolForm("choices", '<div class="opt-list">' + [0, 1, 2, 3].map((i) => '<label class="opt-row"><b>' + "ABCD"[i] + '</b><input class="input" name="opt' + i + '" maxlength="80" value="' +
      esc(t.choices[i]?.text || "") + '" placeholder="' + (i ? "可留空" : "至少写一项") + '" /></label>').join("") + "</div>", "替换选项", "list", "给 " + t.actor + " 的新选项，留空的不出现。");
  },
  check: (r) => {
    const o = r.check_options, actors = r.actors.filter((a) => a.presence !== "left" && a.archetype);
    if (!actors.length) return toolNote("还没有建好卡的角色。");
    const mid = Math.floor((o.difficulties.length - 1) / 2);
    const now = actors.find((a) => (a.name || a.user_name) === r.turn?.actor);
    return toolForm("check", '<div class="tool-grid"><label class="field"><span class="label">角色</span><select class="select" name="actor">' + actors.map((a) => '<option value="' + esc(a.id) + '"' +
      (a === now ? " selected" : "") + ">" + esc(a.name || a.user_name) + "</option>").join("") + "</select></label>" +
      '<label class="field"><span class="label">属性</span><select class="select" name="attr">' + o.attributes.map((a) => '<option value="' + esc(a.ref) + '">' + esc(a.name) + "</option>").join("") + "</select></label></div>" +
      '<div class="field"><span class="label">难度</span><div class="seg diff-seg" data-diff>' + o.difficulties.map((d, i) => '<button type="button" data-value="' + esc(d.key) + '" aria-pressed="' + (i === mid) + '">' +
        esc(d.label) + '<small class="num">' + d.dc + "</small></button>").join("") + "</div></div>" +
      (o.harm ? '<label class="tool-switch"><span class="switch small"><input type="checkbox" name="harm" /><span></span></span>失败要付代价：按世界规则扣资源，下一段正文后生效</label>' : "") +
      '<label class="field"><span class="label">理由（可不填）</span><input class="input" name="reason" maxlength="200" placeholder="例如：听见楼上的脚步" /></label>',
    "掷骰", "dice", "结果立刻公布并记入剧情，下一段正文据此叙述。");
  },
  act: (r) => {
    const later = r.acts.filter((a) => a.number > r.act);
    const next = Math.max(r.act, ...r.acts.map((a) => a.number)) + 1;
    const opts = later.length ? later.map((a) => [a.number, actName(a.number) + "　" + a.title]) : [[next, actName(next) + "（即兴续写）"]];
    return toolForm("act", '<label class="field"><span class="label">进入</span><select class="select" name="target">' + opts.map(([n, l]) => '<option value="' + n + '">' + esc(l) + "</option>").join("") + "</select></label>" +
      (later.length ? "" : '<label class="field"><span class="label">幕名与引子（可不填）</span><input class="input" name="named" maxlength="120" placeholder="例如：潮落：守夜人交出了钥匙" /></label>'),
    "换幕", "book", later.length ? "发出新一幕的开场，节奏从新一幕重新计算。" : "预设的幕已经演完。核心版可以即兴续写下一幕；想结束请到“节奏”开始收尾。");
  },
};

function toolCommand(key, form) {
  const text = (name) => (form.elements.namedItem(name)?.value || "").trim();
  if (key === "advance") return { command: ("主持 推进 " + text("text")).trim(), label: "推进剧情" };
  if (key === "narrate") {
    if (text("text").length < 2) throw new Error("公开剧情至少写 2 个字");
    return { command: "主持 直述 " + text("text"), label: "直述剧情" };
  }
  if (key === "directive") {
    if (!text("text")) throw new Error("请先写指引内容");
    return { command: "主持 指引 " + text("text"), label: "私下指引" };
  }
  if (key === "choices") {
    const list = [0, 1, 2, 3].map((i) => text("opt" + i).replace(/[|｜]/g, "/")).filter(Boolean);
    if (!list.length) throw new Error("至少写一个选项");
    return { command: "主持 选项 " + list.join("｜"), label: "改写选项" };
  }
  if (key === "check") {
    const diff = form.querySelector("[data-diff] [aria-pressed=true]").dataset.value;
    const harm = form.elements.namedItem("harm")?.checked;
    const reason = text("reason").replace(/^(受伤|伤害)(\s|$)/, "$1：$2");
    return { command: ["主持 检定", form.attr.value, diff, harm ? "受伤" : "", reason].filter(Boolean).join(" "), actors: [form.actor.value], label: "要求检定" };
  }
  if (key === "act") return { command: ("主持 换幕 " + form.target.value + " " + text("named")).trim(), label: "换幕" };
}

function bindPlay(root, ctx, r) {
  const pane = root.querySelector('[data-pane="play"]');
  const redraw = () => { pane.innerHTML = playPane(r); bindPlay(root, ctx, r); };
  pane.querySelectorAll("[data-tool]").forEach((b) => b.addEventListener("click", () => {
    consoleView.tool = consoleView.tool === b.dataset.tool ? null : b.dataset.tool;
    redraw();
    pane.querySelector(".tool-form textarea, .tool-form input:not([type=checkbox])")?.focus();
  }));
  pane.querySelectorAll("[data-tool-close]").forEach((b) => b.addEventListener("click", () => { consoleView.tool = null; redraw(); }));
  pane.querySelectorAll("[data-run]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.confirm && !window.confirm(b.dataset.confirm)) return;
    hostRun(ctx, r, b, b.dataset.run);
  }));
  pane.querySelector("[data-clear-directive]")?.addEventListener("click", (e) => hostRun(ctx, r, e.currentTarget, "主持 指引 清除", { label: "清除指引" }));
  pane.querySelectorAll("[data-diff] button").forEach((b) => b.addEventListener("click", () =>
    b.parentElement.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)))));
  const counted = pane.querySelector("[data-counted]");
  counted?.addEventListener("input", () => {
    const n = counted.value.trim().length, out = pane.querySelector("[data-count]");
    out.textContent = n;
    out.className = n && n < 2 ? "over" : "";
  });
  const form = pane.querySelector("[data-tool-form]");
  form?.addEventListener("submit", (e) => {
    e.preventDefault();
    let spec;
    try { spec = toolCommand(form.dataset.toolForm, form); } catch (error) { return ctx.toast(error.message, "error"); }
    hostRun(ctx, r, form.querySelector("[type=submit]"), spec.command, spec);
  });
}

// ---- 桌务
function tablePane(r) {
  const s = r.settings, st = r.state;
  const present = r.actors.filter((a) => a.presence !== "left");
  const flow = [["暂停", "暂停", "pause", st === "running", "故事停在这一轮，玩家的行动指令暂不受理"], ["恢复", "打开准备大厅", "users", st === "paused", "让大家重新准备，可以调整人员和角色"],
    ["主持 全员准备", "全员准备", "check", st === "paused", "替还没准备的人点准备"], ["开演", st === "lobby" ? "开演" : "开演继续", "play", st === "lobby" || st === "paused", st === "lobby" ? "从第一幕开场" : "从暂停的地方继续"]]
    .filter((f) => f[3]);
  const endings = (r.endings || []).map((e) => e.name).filter(Boolean);
  const order = present.map((a, i) => '<li data-actor="' + esc(a.id) + '"><span class="order-no num">' + (i + 1) + "</span>" + avatar(a.name || a.user_name, a.presence === "away" ? "away" : "") +
    '<span class="order-name"><b>' + esc(a.name || a.user_name) + "</b>" + (a.name && a.name !== a.user_name ? '<span class="hint">' + esc(a.user_name) + "</span>" : "") +
    (a.presence === "away" ? '<span class="tag">暂离</span>' : "") + '</span><button type="button" class="btn text small" data-move="-1" title="上移">' + icon("chevron", 15, "flip-y") +
    '</button><button type="button" class="btn text small" data-move="1" title="下移">' + icon("chevron", 15) + "</button></li>").join("");
  const low = Math.max(1, present.length);
  return '<div class="pane-block">' + paneHead("桌面状态", { meta: "现在：" + esc(r.state_label) }) + '<div class="card">' +
    (flow.length ? '<div class="flow-list">' + flow.map(([cmd, label, ic, , note]) => '<button type="button" class="flow-btn" data-run-table="' + esc(cmd) + '">' + icon(ic, 18) +
      "<span><b>" + esc(label) + "</b><small>" + esc(note) + "</small></span></button>").join("") + "</div>" : "") +
    '<div class="rule-row"><div><b>暂存这桌，换个世界</b><p>保留角色、背包、剧情和存档，腾出本群位置；以后从「已暂存」取回</p></div></div>' +
    '<form class="narr-style" data-shelve><input class="input" name="name" maxlength="40" aria-label="暂存名称" placeholder="暂存名称（默认世界名）" /><button class="btn primary" type="submit">' + icon('folder', 14) + '暂存团桌</button></form>' +
    '<div class="rule-row tight"><div><b>完结故事</b><p>直接写下结局，跳过收尾和尾声</p></div></div>' +
    '<form class="narr-style" data-finish><input class="input" name="ending" maxlength="40" list="ending-names" placeholder="结局名（可不填，可选世界里的结局）" />' +
    '<datalist id="ending-names">' + endings.map((n) => '<option value="' + esc(n) + '"></option>').join("") + '</datalist><button class="btn" type="submit">' + icon("flag", 14) + "完结</button></form>" +
    '<div class="rule-row danger-row"><div><b>收桌</b><p>收桌后这一桌不再接受指令，群里可以重新开一桌</p></div><button type="button" class="btn small danger" data-close-table>' + icon("door", 14) + "收桌</button></div>" +
    "</div></div>" +

    '<div class="pane-block">' + paneHead("存档", { meta: "读档后故事回到存档时的位置，并处于暂停" }) + '<div class="card">' +
    '<form class="narr-style" data-save><input class="input" name="name" maxlength="40" placeholder="存档名（可不填）" /><button class="btn primary" type="submit">' + icon("save", 14) + "存档</button></form>" +
    (r.saves.length ? '<div class="save-list">' + r.saves.map((x, i) => '<div class="save-row"><span class="order-no num">' + (i + 1) + '</span><span class="order-name"><b>' + esc(x.name) + '</b><span class="hint">' +
      esc(when(x.created_at)) + '</span></span><button type="button" class="btn small" data-load="' + (i + 1) + '" data-name="' + esc(x.name) + '">' + icon("folder", 14) + "读档</button></div>").reverse().join("") + "</div>"
      : '<p class="tool-note">还没有手动存档。</p>') + "</div></div>" +

    '<div class="pane-block">' + paneHead("席位与顺序", { meta: present.length + " 人在座 · 上限 " + r.seat_cap }) + '<div class="card">' +
    '<div class="rule-row"><div><b>席位上限</b><p>' + (low >= r.seat_limit ? "已经坐满可设的上限" : "最少 " + low + "（已入座人数），最多 " + r.seat_limit) + '</p></div>' +
    '<div class="num-step" data-cap data-low="' + low + '" data-high="' + r.seat_limit + '" data-now="' + r.seat_cap + '"><button type="button" data-step="-1" aria-label="减少">−</button><b class="num">' + r.seat_cap +
    '</b><button type="button" data-step="1" aria-label="增加">+</button></div><button type="button" class="btn small" data-cap-apply disabled>应用</button></div>' +
    (present.length > 1 ? '<div class="rule-row" style="border-bottom:0;padding-bottom:6px"><div><b>行动顺序</b><p>上下移动后应用，从下一次轮转开始生效</p></div><button type="button" class="btn small primary" data-order-apply disabled>应用顺序</button></div>' +
      '<ol class="order-list" data-order>' + order + "</ol>" : "") +
    (s.removed.length ? '<div class="rule-row" style="border-bottom:0"><div><b>已请离</b><p>放行后可以重新入座</p></div><div class="chips">' +
      s.removed.map((n) => '<button type="button" class="chip" data-release="' + esc(n) + '">' + esc(n) + " · 放行</button>").join("") + "</div></div>" : "") +
    "</div></div>";
}

function bindTable(root, ctx, r) {
  const pane = root.querySelector('[data-pane="table"]');
  const shelf = pane.querySelector('[data-shelve]');
  shelf.addEventListener('submit', (e) => { e.preventDefault(); hostRun(ctx, r, shelf.querySelector('[type=submit]'), ('暂存 ' + shelf.name.value.trim()).trim(), { label: '暂存团桌' }); });
  pane.querySelectorAll("[data-run-table]").forEach((b) => b.addEventListener("click", () => hostRun(ctx, r, b, b.dataset.runTable)));
  const finish = pane.querySelector("[data-finish]");
  finish.addEventListener("submit", (e) => {
    e.preventDefault();
    const name = finish.ending.value.trim();
    if (!window.confirm("确定直接完结这个故事吗？" + (name ? "结局：" + name : ""))) return;
    hostRun(ctx, r, finish.querySelector("[type=submit]"), ("完结 " + name).trim(), { label: "完结故事" });
  });
  pane.querySelector("[data-close-table]").addEventListener("click", (e) => {
    if (window.confirm("确定收桌吗？收桌后这一桌不再接受指令。")) hostRun(ctx, r, e.currentTarget, "关闭", { label: "收桌" });
  });
  const save = pane.querySelector("[data-save]");
  save.addEventListener("submit", (e) => { e.preventDefault(); hostRun(ctx, r, save.querySelector("[type=submit]"), ("存档 " + save.name.value.trim()).trim(), { label: "存档" }); });
  pane.querySelectorAll("[data-load]").forEach((b) => b.addEventListener("click", () => {
    if (window.confirm("读取存档「" + b.dataset.name + "」？之后的进度会被覆盖，故事回到存档时的位置并暂停。")) hostRun(ctx, r, b, "读档 " + b.dataset.load, { label: "读档" });
  }));
  const cap = pane.querySelector("[data-cap]"), capApply = pane.querySelector("[data-cap-apply]");
  let seats = r.seat_cap;
  cap.querySelectorAll("[data-step]").forEach((b) => b.addEventListener("click", () => {
    seats = Math.min(Number(cap.dataset.high), Math.max(Number(cap.dataset.low), seats + Number(b.dataset.step)));
    cap.querySelector("b").textContent = seats;
    capApply.disabled = seats === r.seat_cap;
  }));
  capApply.addEventListener("click", () => hostRun(ctx, r, capApply, "人数 " + seats, { label: "席位上限" }));
  const list = pane.querySelector("[data-order]"), orderApply = pane.querySelector("[data-order-apply]");
  if (list) {
    const start = [...list.children].map((li) => li.dataset.actor).join();
    list.addEventListener("click", (e) => {
      const b = e.target.closest("[data-move]");
      if (!b) return;
      const li = b.closest("li"), to = b.dataset.move === "-1" ? li.previousElementSibling : li.nextElementSibling;
      if (!to) return;
      if (b.dataset.move === "-1") list.insertBefore(li, to); else list.insertBefore(to, li);
      [...list.children].forEach((x, i) => { x.querySelector(".order-no").textContent = i + 1; });
      li.classList.remove("moved"); void li.offsetWidth; li.classList.add("moved");
      orderApply.disabled = [...list.children].map((x) => x.dataset.actor).join() === start;
    });
    orderApply.addEventListener("click", () => hostRun(ctx, r, orderApply, "主持 顺序", { actors: [...list.children].map((x) => x.dataset.actor), label: "行动顺序" }));
  }
  pane.querySelectorAll("[data-release]").forEach((b) => b.addEventListener("click", () => hostRun(ctx, r, b, "主持 放行 " + b.dataset.release, { label: "放行" })));
}

// ---- 设置
function configPane(r) {
  const s = r.settings;
  const toggle = (cmd, on, title, text) => '<div class="rule-row"><div><b>' + title + "</b><p>" + text + '</p></div><span class="switch"><input type="checkbox" data-toggle="' + cmd + '"' +
    (on ? " checked" : "") + ' aria-label="' + title + '" /><span></span></span></div>';
  const secs = r.turn_timeout_seconds, own = r.turn_timeout_own;
  const turnKey = !own ? "默认" : secs === 0 ? "0" : String(secs / 60);
  const turnCustom = own && !TURN_LIMITS.some(([k]) => k === turnKey);
  const voteCustom = !VOTE_LIMITS.includes(s.vote_minutes);
  const seg = (cmd, items, now) => '<div class="seg limit-seg">' + items.map(([k, l]) => '<button type="button" data-limit="' + cmd + '" data-value="' + k + '" aria-pressed="' + (k === now) + '">' + l + "</button>").join("") + "</div>";
  const custom = (cmd, value, top, on) => '<form class="limit-custom' + (on ? " on" : "") + '" data-limit-form="' + cmd + '"><span>自定义</span><input class="input num" type="number" min="1" max="' + top + '" name="minutes" value="' + (on ? value : "") +
    '" placeholder="1–' + top + '" /><span>分钟</span><button class="btn small" type="submit">设定</button></form>';
  return '<div class="pane-block">' + paneHead("桌面规则", { meta: "开关立即生效，结果发到群里" }) + '<div class="card">' +
    toggle("主持 审稿", s.review, "审稿模式", "正文先私发给主持人，确认后再发到群里") +
    toggle("主持 入座", !s.seating_locked, "开放入座", "关闭后新玩家不能加入，已在座的人不受影响") +
    toggle("主持 人设", !s.personas_off, "参考玩家人设", "关闭后 AI 只按职业写角色，不看玩家自带的人设卡") +
    toggle("主持 快团", s.rush, "快团", "全队同时交行动，一轮合写一段正文；关闭后按座位轮流") + "</div></div>" +
    '<div class="pane-block">' + paneHead("时限", { meta: "到时没有行动，自动选择风险最低的选项" }) + '<div class="card">' +
    '<div class="limit-row"><div class="narr-head"><b>回合限时</b><span class="now">' + esc(limitText(secs)) + '</span><span class="spacer"></span><span class="narr-src">' + (own ? "本桌设置" : "跟随全局") + "</span></div>" +
    seg("主持 限时", TURN_LIMITS, turnCustom ? "" : turnKey) + custom("主持 限时", secs / 60, 1440, turnCustom) +
    '<p class="narr-hint">全局设置是' + esc(limitText(r.turn_timeout_default)) + "。改动后，正在等待的那一回合重新计时。</p></div>" +
    '<div class="limit-row"><div class="narr-head"><b>表决时限</b><span class="now">' + s.vote_minutes + ' 分钟</span><span class="spacer"></span>' +
    '<button type="button" class="btn text small" data-limit="主持 表决时限" data-value="默认">恢复默认</button></div>' +
    seg("主持 表决时限", VOTE_LIMITS.map((m) => [String(m), m + " 分"]), voteCustom ? "" : String(s.vote_minutes)) + custom("主持 表决时限", s.vote_minutes, 30, voteCustom) +
    '<p class="narr-hint">默认 2 分钟，可设 1–30 分钟；从下一次表决开始生效。</p></div>' + "</div></div>";
}

function bindConfig(root, ctx, r) {
  const pane = root.querySelector('[data-pane="config"]');
  pane.querySelectorAll("[data-toggle]").forEach((box) => box.addEventListener("change", () =>
    hostRun(ctx, r, box, box.dataset.toggle + (box.checked ? " 开" : " 关"))));
  pane.querySelectorAll("[data-limit]").forEach((b) => b.addEventListener("click", () => {
    if (b.getAttribute("aria-pressed") === "true") return;
    hostRun(ctx, r, b, b.dataset.limit + " " + b.dataset.value);
  }));
  pane.querySelectorAll("[data-limit-form]").forEach((form) => form.addEventListener("submit", (e) => {
    e.preventDefault();
    const n = Number(form.minutes.value);
    if (!Number.isInteger(n) || n < Number(form.minutes.min) || n > Number(form.minutes.max)) return ctx.toast("请填 " + form.minutes.min + "–" + form.minutes.max + " 的整数分钟", "error");
    hostRun(ctx, r, form.querySelector("[type=submit]"), form.dataset.limitForm + " " + n);
  }));
}

function bindConsole(root, ctx, r) {
  root.querySelectorAll(".console-tabs [data-tab]").forEach((b) => b.addEventListener("click", () => {
    consoleView.tab = b.dataset.tab;
    root.querySelectorAll(".console-tabs [data-tab]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    root.querySelectorAll(".console-pane").forEach((p) => { p.hidden = p.dataset.pane !== b.dataset.tab; });
  }));
  bindPlay(root, ctx, r); bindTable(root, ctx, r); bindConfig(root, ctx, r);
  bindPacing(root, ctx, r); bindNarration(root, ctx, r); bindCreation(root, ctx, r); bindAdjust(root, ctx, r);
  // The review draft under "此刻" and the per-seat actions on the seat cards.
  root.querySelector("[data-publish]")?.addEventListener("click", (e) => hostRun(ctx, r, e.currentTarget, "主持 发布", { label: "发布草稿" }));
  const rewrite = root.querySelector("[data-rewrite]");
  rewrite?.addEventListener("submit", (e) => {
    e.preventDefault();
    hostRun(ctx, r, rewrite.querySelector("[type=submit]"), ("主持 重写 " + rewrite.note.value.trim()).trim(), { label: "重写草稿" });
  });
  root.querySelectorAll("[data-seat-cmd]").forEach((button) => button.addEventListener("click", () => {
    const spec = SEAT_ACTIONS.find(([cmd]) => cmd === button.dataset.seatCmd);
    if (spec[2] && !window.confirm(button.dataset.name + "：" + spec[2])) return;
    hostRun(ctx, r, button, spec[0] + " " + button.dataset.user, { label: spec[1] + " · " + button.dataset.name });
  }));
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
    const mine = (r.stats?.cast || []).find((c) => c.name === name);
    const live = ["lobby", "running", "paused"].includes(r.state);
    const isHost = a.user_id === r.host_user_id;
    const show = { "主持 轮到": r.state === "running" && r.turn?.state === "awaiting" && a.presence === "present" && a.archetype && name !== turnActor,
      "主持 暂离": a.presence === "present", "主持 返回": a.presence === "away", "主持 退回": Boolean(a.archetype), "主持 人设 清除": Boolean(a.persona),
      "主持 交棒": !isHost, "主持 移出": !isHost };
    const actions = live ? SEAT_ACTIONS.filter(([cmd]) => show[cmd]).map(([cmd, label]) => '<button type="button" class="btn small' + (cmd === "主持 移出" ? " danger" : "") +
      '" data-seat-cmd="' + esc(cmd) + '" data-user="' + esc(a.user_id) + '" data-name="' + esc(name) + '">' + esc(label) + "</button>").join("") : "";
    const skills = a.loadout.filter((e) => e.kind === "skill"), items = a.loadout.filter((e) => e.kind === "item");
    const ties = r.people.filter((p) => p.contributions[name]).map((p) => '<span class="tag' + (p.contributions[name] > 0 ? " gold" : "") + '">' + esc(p.name) + " " +
      (p.contributions[name] > 0 ? "+" : "") + p.contributions[name] + "</span>").join("");
    const p = a.persona;
    const persona = p ? '<div class="sheet-persona' + (r.settings.personas_off ? " off" : "") + '">' + (p.avatar ? '<span class="avatar photo"><img src="' + esc(p.avatar) + '" alt="" /></span>' : avatar(p.name)) +
      '<div><div class="sp-head"><span class="label" style="margin:0">人设</span><b>' + esc(p.name) + "</b>" + (p.tags || []).slice(0, 3).map((t) => '<span class="tag">' + esc(t) + "</span>").join("") +
      (r.settings.personas_off ? '<span class="tag warn">本桌已关闭 · AI 不参考</span>' : "") + "</div>" +
      '<p class="serif">' + (p.intro ? esc(p.intro) : '<span class="faint">还没有融入这个世界：玩家发送 /团 人设 融入</span>') + "</p></div></div>" : "";
    return '<article class="sheet">' + '<div class="sheet-head">' + avatar(name, "big" + (name === turnActor ? " now" : "") + (a.presence === "away" ? " away" : "")) +
      '<div style="min-width:0"><div class="actor-name"><b>' + esc(name) + '</b><span class="muted" style="font-size:12.5px">' + esc(a.archetype || "未建卡") + "</span></div>" +
      '<div class="hint">玩家 ' + esc(a.user_name) + (a.user_id === r.host_user_id ? " · 主持人" : "") + "</div></div>" +
      '<div class="row" style="gap:14px">' + (mine ? '<span class="sheet-stat">行动 <b>' + mine.turns + "</b></span>" + '<span class="sheet-stat">检定 <b>' + mine.wins + "</b>/" + mine.checks + "</span>" : "") +
      dot(...(presence[a.presence] || ["", a.presence])) + "</div></div>" +
      (actions ? '<div class="seat-actions">' + actions + "</div>" : "") +
      persona +
      (a.archetype ? '<div class="sheet-grid"><div><div class="label">资源</div><div class="meters">' + a.resources.map((x, i) => meter(x.name, x.current, x.max, i)).join("") + "</div>" +
        (a.money != null ? '<div class="label" style="margin-top:12px">钱包</div><div class="wallet-line">' + icon("coin", 15) + "<b>" + a.money + "</b><span>" + esc(r.economy.currency) + "</span></div>" : "") +
        '<div class="label" style="margin-top:12px">属性</div><div class="attrs">' + a.attributes.map((x, i) => {
          const range = r.attribute_ranges[i] || { min: 0, max: 20 }, share = range.max > range.min ? ((x.value ?? range.min) - range.min) / (range.max - range.min) : 0;
          return '<span style="--s:' + Math.max(0, Math.min(1, share)).toFixed(2) + '"><b>' + (x.value ?? "—") + "</b>" + esc(x.name) +
            (x.modifier != null ? '<i>' + (x.modifier >= 0 ? "+" : "") + x.modifier + "</i>" : "") + "<u></u></span>";
        }).join("") + "</div>" +
        (a.traits.length ? '<div class="label" style="margin-top:12px">经历</div><div class="chips">' + a.traits.map((t) => '<span class="tag gold">' + esc(t) + "</span>").join("") + "</div>" : "") +
        (ties ? '<div class="label" style="margin-top:12px">对人物态度的影响</div><div class="chips">' + ties + "</div>" : "") + "</div>" +
        '<div><div class="label">技能 ' + skills.length + "</div>" + (skills.map(entry).join("") || '<div class="hint">无</div>') +
        '<div class="label" style="margin-top:12px">物品 ' + items.length + "</div>" + (items.map(entry).join("") || '<div class="hint">无</div>') + "</div></div>"
        : '<div class="hint" style="margin-top:10px">还没有建卡。玩家可以私聊 bot 发送 /团 建卡，选快选、定制、精雕或 AI 起草。</div>') + "</article>";
  };
  const of = r.economy?.outfit, built = actors.filter((a) => a.archetype && a.presence !== "left").length;
  const outfit = of ? '<div class="outfit-banner">' + icon("coin", 16) + '<div><b>整备中</b><span>' + esc(of.place || "当前地点") + (of.shops.length ? " · " + esc(of.shops.join("、")) : "") +
      "</span></div><div class=\"outfit-meta\"><span>好了 <b>" + of.done + "</b>/" + built + "</span><span>" + Math.max(0, Math.ceil((new Date(of.deadline) - Date.now()) / 60000)) + " 分钟后收起</span></div></div>"
    : r.economy?.here?.length ? '<div class="outfit-banner idle">' + icon("coin", 16) + "<div><b>这里有店</b><span>" + esc(r.economy.here.join("、")) + "</span></div><div class=\"outfit-meta\"><span>主持人发送 /团 主持 整备 让大家买卖</span></div></div>" : "";
  return '<section>' + section("同桌", { count: actors.length + "/" + r.seat_cap, meta: "角色、技能和物品只在这一桌有效；检定时句末写 [用 名称] 带上技能或物品" }) + outfit +
    (actors.length ? party(r, actors) + '<div class="stack" style="gap:16px">' + actors.map(card).join("") + "</div>" : empty("还没有人入座")) + "</section>";
}

/** The party side by side: what each one has done, their resources, and every attribute on one line per attribute. */
function party(r, actors) {
  const built = actors.filter((a) => a.archetype);
  if (!built.length) return "";
  const tone = new Map(built.map((a, i) => [a.id, "pc-" + ((i % 8) + 1)]));
  const turnActor = r.turn?.actor;
  const rows = built.map((a) => {
    const name = a.name || a.user_name, s = (r.stats?.cast || []).find((c) => c.name === name) || { turns: 0, checks: 0, wins: 0 };
    const rate = s.checks ? s.wins / s.checks : 0;
    return '<div class="pm">' + avatar(name, tone.get(a.id) + (name === turnActor ? " now" : "") + (a.presence === "away" ? " away" : "")) +
      '<div style="min-width:0"><b>' + esc(name) + "</b><small>" + esc(a.archetype) + " · " + esc(a.user_name) + "</small></div>" +
      '<div class="pm-num"><b>' + s.turns + "</b><small>行动</small></div>" +
      '<div class="pm-rate"><div class="pm-rate-top"><span>检定</span><b>' + (s.checks ? Math.round(rate * 100) + "%" : "—") + '</b></div><div class="bar"><span style="width:' + (rate * 100).toFixed(0) +
        '%"></span></div><small>' + s.wins + " 成 / " + s.checks + " 次</small></div>" +
      '<div class="meters">' + a.resources.map((x, i) => meter(x.name, x.current, x.max, i)).join("") + "</div></div>";
  }).join("");
  const lanes = r.attribute_ranges.map((range, i) => {
    // Characters with the same score sit side by side around it.
    const span = Math.max(1, range.max - range.min), seen = {}, ties = {};
    built.forEach((a) => { const v = a.attributes[i]?.value; if (v != null) ties[v] = (ties[v] || 0) + 1; });
    const pins = built.map((a) => {
      const v = a.attributes[i]?.value;
      if (v == null) return "";
      const stack = (seen[v] = (seen[v] || 0) + 1) - 1 - (ties[v] - 1) / 2;
      return '<span class="pin ' + tone.get(a.id) + '" style="left:' + (((v - range.min) / span) * 100).toFixed(1) + "%;--k:" + stack + '" title="' + esc((a.name || a.user_name) + " " + v) + '">' +
        esc((a.name || a.user_name).slice(0, 1)) + "</span>";
    }).join("");
    const values = built.map((a) => a.attributes[i]?.value).filter((v) => v != null);
    return '<div class="lane"><span class="lane-name">' + esc(range.name) + '</span><div class="lane-track" title="' + esc(range.name + " " + range.min + "–" + range.max) + '"><i></i>' + pins + '</div><span class="lane-range num">' +
      (values.length ? Math.min(...values) + "–" + Math.max(...values) : "—") + "</span></div>";
  }).join("");
  return '<div class="party"><div><div class="label">队伍</div><div class="pm-list">' + rows + "</div></div>" +
    '<div><div class="label">属性对比 <span class="faint">· 刻度两端为世界规定的上下限，右侧为队内最低到最高</span></div><div class="lanes">' + lanes + "</div></div></div>";
}

function peopleSection(r) {
  const labels = r.adjust_options.standing;
  const move = (p) => {
    const last = [...p.memories].reverse().find((m) => m.change);
    return last ? '<span class="move ' + (last.change > 0 ? "up" : "down") + '" title="最近一次变化">' + (last.change > 0 ? "▲" : "▼") + " " + esc(last.who) + " " + signed(last.change) + "</span>" : "";
  };
  return '<section>' + section("人物与关系", { count: r.people.length, meta: "态度针对整个队伍；后面的数字是每位玩家带来的升降" }) +
    (r.people.length ? '<div class="people">' + r.people.map((p) => '<div class="person-card">' +
      '<div class="pc-head">' + roundIcon(p.kind === "faction" ? "flag" : "user", p.standing > 0 ? "" : p.standing < 0 ? "err" : "mute") +
      '<div style="min-width:0"><div class="ri-title">' + esc(p.name) + '　<span class="muted" style="font-weight:400;font-size:12.5px">' + esc(p.kind === "faction" ? "势力" : "人物") + (p.seq ? " · #" + p.seq : "") + "</span></div>" +
      (p.description ? '<div class="ri-meta">' + esc(p.description) + (p.motivation ? " · 动机：" + esc(p.motivation) : "") + "</div>" : "") + "</div>" +
      '<div class="pc-tier"><b class="' + (p.standing > 0 ? "pos" : p.standing < 0 ? "neg" : "") + '">' + esc(p.tier) + "</b>" + move(p) + "</div></div>" +
      standing(p.standing, labels) +
      (Object.keys(p.contributions).length ? '<div class="contribs">' + Object.entries(p.contributions).map(([who, v]) => '<span class="' + (v > 0 ? "up" : "down") + '">' + esc(who) + "<b>" + signed(v) + "</b></span>").join("") + "</div>" : "") +
      (p.memories.length ? '<div class="hint" style="margin-top:8px">' + p.memories.slice(-3).map((m) => esc(m.who + "：" + m.text) + (m.change ? "（" + signed(m.change) + "）" : "")).join("　") + "</div>" : "") +
      "</div>").join("") + "</div>"
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

