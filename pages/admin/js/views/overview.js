import { acts, avatar, avatars, brief, cover, dot, empty, esc, facts, figure, fmt, hero, icon, meter, ring, roomDot, roundIcon, section, shortTitle, subTitle, until, when } from "../ui.js";

const KIND_ICON = { narration: "feather", action: "user", check: "dice", play: "layers", vote: "vote", system: "sparkle" };
const KIND_LABEL = { narration: "叙事", action: "行动", check: "检定", play: "玩法", vote: "表决", system: "系统" };

function greeting(date) {
  const h = date.getHours();
  if (h < 5 || h >= 23) return ["夜深", "夜深了"];
  if (h < 9) return ["清晨", "早上好"];
  if (h < 12) return ["上午", "上午好"];
  if (h < 17) return ["午后", "午后好"];
  if (h < 19) return ["傍晚", "傍晚好"];
  return ["夜晚", "晚上好"];
}

const timeoutText = (deadline) => (new Date(deadline).getTime() <= Date.now() ? "已超时" : until(deadline) + "超时");
const remaining = (deadline) => (deadline ? Math.max(0, (new Date(deadline).getTime() - Date.now()) / 1000) : null);

/** Table card used by the overview shelf and the tables page. */
export function tableCard(r) {
  const actList = Array.from({ length: r.acts_total || 0 }, (_, i) => i + 1);
  const turn = r.turn;
  return '<a class="tcard" href="#/rooms/' + encodeURIComponent(r.id) + '">' + '<div class="cover band tone-' + esc(r.cover.tone) + '"><span class="mark">' + esc(r.cover.mark) + "</span></div>" +
    '<div class="tcard-body"><div class="tcard-eyebrow"><span>群 ' + esc(r.group_id || "—") + " · " + esc(r.platform) + "</span>" + roomDot(r.state, r.state_label) + "</div>" +
    "<h3>" + esc(shortTitle(r.title)) + "</h3>" +
    '<div class="tcard-act">' + (r.state === "lobby" ? "<span>筹备中，等人入座</span>" : (actList.length ? acts(actList, r.act, true) : "") +
      "<span>" + esc(r.act_heading || "") + (r.round ? "　第 " + r.round + " 轮" : "") + "</span>") + "</div>" +
    (r.excerpt ? '<div class="excerpt">' + esc(r.excerpt) + "</div>" : '<div class="excerpt">' + esc(subTitle(r.title)) + "</div>") +
    '<div class="tcard-foot">' + (turn ? icon("feather", 14) + '<span class="turnline">轮到 <b>' + esc(turn.actor) + "</b>" + (turn.deadline_at ? " · " + esc(timeoutText(turn.deadline_at)) : "") + "</span>" : "<span>" + esc(when(r.updated_at)) + "更新</span>") +
    (turn ? "" : '<span class="spacer"></span>') + avatars(r.names, 4) + '<span class="num">' + r.players + "/" + r.seat_cap + "</span></div></div></a>";
}

function storyCard(f) {
  if (!f) {
    return '<div class="story"><div class="story-band brand tone-slate"><div><div class="story-chips"><span>' + icon("sparkle", 13) + "还没有开演的团桌</span></div>" +
      '<h2 class="story-title">等第一桌开张</h2><div class="story-sub">管理员在群里发送 /团 开启，选一个世界就能开一桌</div>' +
      '<div class="story-label">开 团 三 步</div><div class="story-text">/团 开启　选世界开桌\n/团 加入　玩家入座\n/团 开演　主持人开始第一幕</div></div><div></div></div></div>';
  }
  const [actLine] = String(f.act_heading || "").split("\n");
  const turn = f.turn;
  const turnActor = turn ? f.actors.find((a) => (a.name || a.user_name) === turn.actor) : null;
  const recent = f.recent.length ? f.recent.map((e) => "<li>" + icon(KIND_ICON[e.kind] || "sparkle", 13) + "<span>" + esc(brief(e.text, 46)) + "</span></li>").join("") : "<li><span>还没有行动</span></li>";
  return '<div class="story"><div class="story-band tone-' + esc(f.cover.tone) + '" data-mark="' + esc(f.cover.mark) + '"><div style="min-width:0">' +
    '<div class="story-chips"><span>' + (f.state === "paused" ? icon("pause", 12) : icon("play", 12)) + esc(f.state_label) + "</span>" + (actLine ? "<span>" + esc(actLine) + "</span>" : "") +
      (f.clock ? "<span>" + icon("clock", 12) + esc(f.clock) + "</span>" : "") + "</div>" +
    '<h2 class="story-title">' + esc(shortTitle(f.title)) + '</h2><div class="story-sub">' + esc(subTitle(f.title)) + "</div>" +
    '<div class="story-label">最 近 的 一 段 故 事</div><div class="story-text">' + esc(brief(f.story || (f.scene && f.scene.description) || "故事刚刚开始。")) + "</div></div>" +
    '<div class="story-glass"><div class="story-label">上 回</div><ul>' + recent + "</ul>" +
      (f.goal ? '<div class="goal"><div class="story-label">此 刻 的 目 标</div>' + esc(f.goal) + "</div>" : "") + "</div></div>" +
    '<div class="story-bar">' + (turn ? ring(remaining(turn.deadline_at), f.turn_timeout_seconds, "", 54) : "") +
      '<div class="who"><b>' + (turn ? "第 " + turn.round + " 轮 · 轮到 " + esc(turn.actor) : "没有进行中的回合") + "</b><span>" +
      (turn ? (turn.deadline_at ? esc(timeoutText(turn.deadline_at)) + "，自动选风险最低的一项" : "不限时") : esc(f.state_label)) + "</span>" +
      (turnActor ? '<div class="meters">' + turnActor.resources.slice(0, 2).map((x, i) => meter(x.name, x.current, x.max, i === 1)).join("") + "</div>" : "") + "</div>" + '<span class="avatars">' + f.actors.map((a) => avatar(a.name || a.user_name, (a.name || a.user_name) === (turn && turn.actor) ? "now" : a.presence === "away" ? "away" : "")).join("") + "</span>" +
      '<a class="link" href="#/rooms/' + encodeURIComponent(f.id) + '">进入团桌' + icon("arrow", 14) + "</a></div></div>";
}

export async function render(root, ctx) {
  const d = await ctx.api.get("overview");
  const now = new Date();
  const [slot, greet] = greeting(now);
  const live = (d.rooms.running || 0) + (d.rooms.paused || 0);
  const week = ["日", "一", "二", "三", "四", "五", "六"][now.getDay()];
  const m = d.model_24h;
  const peak = Math.max(1, ...d.model_week.map((x) => x.calls));
  const playPeak = Math.max(1, ...d.plays.map((p) => p.count));
  const msg = d.message;
  const urgent = d.attention.filter((a) => a.tone === "err").length;

  const shelf = d.active_rooms.length ? '<div class="rows">' + d.active_rooms.slice(0, 6).map((r) =>
    '<a class="ri shelf" href="#/rooms/' + encodeURIComponent(r.id) + '">' + cover(r.cover) + '<div style="min-width:0"><div class="ri-title">' + esc(shortTitle(r.title)) + "</div>" +
    '<div class="ri-meta">' + (r.state === "lobby" ? "<span>筹备中 · " + r.players + "/" + r.seat_cap + " 人</span>" : "<span>" + esc(r.act_heading || "第 " + r.act + " 幕") + "</span>" + (r.round ? "<span>第 " + r.round + " 轮</span>" : "")) + "</div></div>" +
    '<div class="ri-side" style="flex-direction:column;align-items:flex-end;gap:2px">' + roomDot(r.state, r.state_label) + (r.turn ? '<span class="faint">轮到 ' + esc(r.turn.actor) + "</span>" : '<span class="faint">' + esc(when(r.updated_at)) + "</span>") + "</div></a>").join("") + "</div>"
    : empty("还没有团桌", "在群里发送 /团 开启");

  const attention = d.attention.length ? '<div class="rows two">' + d.attention.map((a) => '<a class="ri" href="#/' + esc(a.link) + '">' + roundIcon(a.icon, a.tone) +
    '<div style="min-width:0"><div class="ri-title">' + esc(a.title) + '</div><div class="ri-meta"><span>' + esc(a.detail) + "</span>" + (a.deadline_at ? "<span>" + (new Date(a.deadline_at).getTime() <= Date.now() ? "已到截止时间" : esc(until(a.deadline_at)) + "截止") + "</span>" : "") + "</div></div>" +
    '<span class="link">' + esc(a.action) + icon("arrow", 14) + "</span></a>").join("") + "</div>"
    : '<div class="rows"><div class="ri">' + roundIcon("check", "ok") + '<div><div class="ri-title">一切顺利</div><div class="ri-meta">没有失败的正文、待重发的消息或进行中的表决</div></div><span></span></div></div>';

  const imageSegs = [["image_status", "状态"], ["image_narration", "正文"], ["image_choices", "选项"]];
  const ready = [
    [d.ready.admins > 0, "插件管理员", d.ready.admins ? d.ready.admins + " 位" : "未设置"],
    [true, "群白名单", d.ready.whitelist ? "已启用 · " + d.ready.allowed_groups + " 个群" : "未启用，所有群可用"],
    [true, "叙事模型", d.ready.provider],
    [true, "回合限时", d.ready.turn_timeout ? Math.round(d.ready.turn_timeout / 60) + " 分钟" : "不限时"],
    [true, "集体事件", d.ready.collective_every ? "每 " + d.ready.collective_every + " 轮" : "已关闭"],
    [d.plays_enabled > 0, "玩法", d.plays_enabled + "/" + d.plays_total + " 已开启"],
  ];

  root.innerHTML = hero({
    eyebrow: "酒馆账房 · 周" + week + " · " + slot + " " + now.toTimeString().slice(0, 5),
    title: esc(greet) + "，" + (live ? "<em>" + live + " 桌</em>故事正在进行。" : "酒馆里还很安静。"),
    lead: facts([["users", d.seated, "位玩家在桌边"], ["dice", d.rooms.lobby || 0, "桌筹备中"], ["feather", d.rounds_24h, "轮 · 近 24 小时"],
      ["activity", m.calls, "次模型调用"], ["globe", d.worlds.enabled + "/" + d.worlds.total, "个世界可开"]]),
    figures: '<div class="figures">' + figure(live, "进行中") + figure(d.attention.length, "待处理", urgent ? "err" : "") + figure(d.outbox_pending, "待重发", "plain") + "</div>",
  }) +
  '<section class="sec grid cols-2"><div>' + storyCard(d.feature) + "</div>" +
    "<div>" + section("团桌一览", { count: d.active_rooms.length, meta: "进行中优先 · 含筹备与已完结", link: ["#/rooms", "全部团桌"] }) + shelf + "</div></section>" +
  '<section class="sec">' + section("等你处理", { count: d.attention.length, meta: (urgent ? urgent + " 项需要尽快处理 · " : "") + "来自团桌、消息与模型" }) + attention + "</section>" +
  '<section class="sec">' + section("运行概况", { meta: "近 7 天模型调用、消息推送与基础配置" }) + '<div class="grid cols-3">' +
    '<div><h3 class="sub-title">模型调用</h3><div class="figures" style="gap:26px;margin-bottom:18px">' + figure(fmt(m.calls), "24 小时调用", "small") + figure(fmt(m.input_tokens + m.output_tokens), "tokens", "small plain") +
      figure(m.failures, "失败", m.failures ? "small err" : "small plain") + '</div><div class="bars" style="height:96px">' + d.model_week.map((x) => '<div class="col" title="' + esc(x.day) + "：" + x.calls + " 次" + '"><div class="stack-bar">' +
      (x.failures ? '<i class="fail" style="height:' + ((x.failures / peak) * 100).toFixed(0) + '%"></i>' : "") + '<i style="height:' + (((x.calls - x.failures) / peak) * 100).toFixed(0) + '%"></i></div><span>' + esc(x.day.slice(8)) + "</span></div>").join("") +
      '</div><div style="margin-top:14px"><a class="link" href="#/ops/usage">模型用量' + icon("arrow", 14) + "</a></div></div>" +
    '<div><h3 class="sub-title">消息推送</h3><dl class="kv"><dt>格式</dt><dd>' + (msg.format === "markdown" ? "Markdown（不支持的平台自动纯文本）" : "纯文本") + "</dd>" +
      "<dt>转为图片</dt><dd>" + imageSegs.map(([k, l]) => dot(msg[k] ? "gold" : "off", l)).join("　") + "</dd>" +
      "<dt>分段</dt><dd>" + (msg.merge ? "合并为一条" : "间隔 " + Number(msg.interval).toFixed(1) + " 秒") + "</dd>" +
      "<dt>降级平台</dt><dd>" + (msg.blocked.length ? esc(msg.blocked.join("、")) : "无") + "</dd><dt>待重发</dt><dd>" + d.outbox_pending + " 条</dd></dl>" +
      '<div style="margin-top:18px"><a class="link" href="#/messages">消息样式' + icon("arrow", 14) + "</a></div></div>" +
    '<div><h3 class="sub-title">就绪检查</h3><div style="display:grid;gap:9px">' + ready.map(([ok, k, v]) => '<div class="row between"><span class="dot ' + (ok ? "ok" : "warn") + '">' + esc(k) + '</span><span class="muted" style="font-size:12.5px">' + esc(v) + "</span></div>").join("") +
      '</div><div style="margin-top:18px"><a class="link" href="#/settings">设置' + icon("arrow", 14) + "</a></div></div></div></section>" +
  '<section class="sec grid cols-2"><div>' + section("此刻酒馆里", { meta: "所有团桌最近的动态", link: ["#/rooms", "团桌"] }) +
    (d.recent.length ? '<div class="rows feed">' + d.recent.slice(0, 8).map((e) => '<a class="ri ' + esc(e.kind) + '" href="#/rooms/' + encodeURIComponent(e.room_id) + '">' + roundIcon(KIND_ICON[e.kind] || "sparkle", e.kind === "narration" ? "" : "mute") +
      '<div style="min-width:0"><div class="ri-title">' + esc(brief(e.text, 120)) + '</div><div class="ri-meta"><span>' + esc(KIND_LABEL[e.kind] || e.kind) + "</span><span>" + esc(shortTitle(e.title)) + "</span></div></div>" +
      '<span class="ri-side"><time>' + esc(when(e.created_at)) + "</time></span></a>").join("") + "</div>" : empty("暂无动态")) + "</div>" +
    "<div>" + section("玩法热度", { meta: "近 30 天 · 已开启 " + d.plays_enabled + "/" + d.plays_total, link: ["#/plays", "玩法"] }) +
      (d.plays.length ? d.plays.slice(0, 8).map((p) => '<div class="hbar"><span>' + esc(p.label) + '</span><i><span style="width:' + ((p.count / playPeak) * 100).toFixed(0) + '%"></span></i><span class="num">' + p.count + "</span></div>").join("") : empty("近 30 天还没有玩法记录")) +
      '<div class="sec" style="margin-top:40px">' + section("世界", { meta: "按开桌次数 · 自定义 " + d.custom_worlds + " 个", link: ["#/worlds", "全部世界"] }) +
      (d.world_usage.length ? '<div class="rows">' + d.world_usage.map((w) => '<a class="ri shelf" href="#/worlds/' + encodeURIComponent(w.id) + '">' + cover(w.cover) + '<div style="min-width:0"><div class="ri-title">' + esc(shortTitle(w.title)) +
        '</div><div class="ri-meta">' + esc(subTitle(w.title)) + '</div></div><span class="ri-side"><span class="serif gold" style="font-size:20px">' + w.rooms + "</span>桌</span></a>").join("") + "</div>" : empty("还没有开过桌")) + "</div></div></section>" +
  '<div class="footer-note"><div class="sign" aria-hidden="true"></div>321，开团！故事从此刻发生……<div class="mono" style="margin-top:8px;letter-spacing:0">Lite ' + esc(d.version) + " · 世界引擎 " + esc(d.engine_version) + "</div></div>";

  const ringEl = root.querySelector(".story-bar .ring");
  if (ringEl && d.feature?.turn?.deadline_at) {
    ctx.every(1000, () => {
      const slotEl = root.querySelector(".story-bar .ring");
      if (slotEl) slotEl.outerHTML = ring(remaining(d.feature.turn.deadline_at), d.feature.turn_timeout_seconds, "", 54);
    });
  }
}

