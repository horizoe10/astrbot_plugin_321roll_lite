import { busy, columns, dot, empty, esc, figure, fmt, hero, icon, roundIcon, section, shares, when } from "../ui.js";

const TABS = [["usage", "模型用量", "activity"], ["outbox", "待重发", "send"], ["audit", "操作记录", "list"], ["backup", "备份", "save"]];
const CONTRACTS = [["brief-start", "开场"], ["intent", "理解行动"], ["narrative", "叙事正文"], ["risk", "风险排序"], ["collective-event", "集体事件"]];
const contractName = (id) => (CONTRACTS.find(([key]) => String(id).includes(key)) || [null, id])[1];
const CONTRACT_TONES = ["c1", "c2", "c3", "c4", "c5", "c6"];
const TABLES = { rooms: "团桌", actors: "角色", records: "玩法记录", turns: "回合", events: "时间线", facts: "事实", npcs: "人物", votes: "表决",
  saves: "存档", worlds: "自定义世界", settings: "设置", outbox: "待发消息", audit: "操作记录" };
const ACTIONS = { "web.room_command": ["后台主持", "wand"], "web.world_toggle": ["启停世界", "globe"], "web.world_save": ["保存世界", "save"], "web.world_delete": ["删除世界", "trash"],
  "web.feature_set": ["玩法开关", "layers"], "web.settings_set": ["设置", "sliders"], "web.settings_message": ["消息样式", "message"], "web.backup_import": ["恢复备份", "upload"] };

export async function render(root, ctx) {
  const tab = TABS.some(([k]) => k === ctx.route.rest[0]) ? ctx.route.rest[0] : "usage";
  const body = document.createElement("div");
  root.innerHTML = hero({ eyebrow: "运行 · OPERATIONS", title: "运行", lead: "模型调用、消息送达、后台操作与数据备份。" }) +
    '<nav class="tabs">' + TABS.map(([k, l, ic]) => '<a href="#/ops/' + k + '"' + (k === tab ? ' aria-current="page"' : "") + ">" + icon(ic, 15) + l + "</a>").join("") + "</nav>";
  root.appendChild(body);
  await { usage, outbox, audit, backup }[tab](body, ctx);
}

async function usage(root, ctx) {
  const d = await ctx.api.get("usage");
  const byDay = Object.fromEntries(d.days.map((x) => [x.day, x]));
  const days = Array.from({ length: 14 }, (_, i) => {
    const day = new Date(Date.now() - (13 - i) * 86400000).toISOString().slice(0, 10);
    return byDay[day] || { day, calls: 0, failures: 0, input_tokens: 0, output_tokens: 0 };
  });
  const total = days.reduce((s, x) => s + x.calls, 0);
  const tokens = days.reduce((s, x) => s + (x.input_tokens || 0) + (x.output_tokens || 0), 0);
  const failed = days.reduce((s, x) => s + (x.failures || 0), 0);
  const lat = d.latency;
  // Two or fewer busy days read better by the hour.
  let mode = days.filter((x) => x.calls).length <= 2 ? "hours" : "days";
  const today = new Date().toISOString().slice(0, 10);
  const chart = () => columns(mode === "hours"
    ? d.hours.map((x, i) => { const h = new Date(x.hour + ":00:00Z").getHours(); return { label: h % 3 === 0 ? String(h).padStart(2, "0") : "", ok: x.calls - x.failures, fail: x.failures,
        now: i === d.hours.length - 1, title: h + ":00 · " + x.calls + " 次" + (x.failures ? "，失败 " + x.failures : "") }; })
    : days.map((x) => ({ label: x.day.slice(5).replace("-", "/"), ok: x.calls - (x.failures || 0), fail: x.failures || 0, now: x.day === today,
        title: x.day + " · " + x.calls + " 次" + (x.failures ? "，失败 " + x.failures : "") })), 240);
  const callsAll = d.contracts.reduce((s, c) => s + c.calls, 0);
  const busiest = days.reduce((a, b) => (b.calls > a.calls ? b : a), days[0]);
  const active = days.filter((x) => x.calls).length;
  const chartNote = () => '<div class="chart-note"><span>有调用的日子 <b>' + active + "</b> / 14 天</span><span>日均 <b>" + (active ? (total / active).toFixed(1) : 0) + "</b> 次</span>" +
    (busiest.calls ? "<span>最忙 <b>" + busiest.day.slice(5).replace("-", "/") + "</b> · " + busiest.calls + " 次</span>" : "") + "<span>失败 <b" + (failed ? ' class="err-text"' : "") + ">" + failed + "</b> 次</span></div>";
  const contracts = d.contracts.map((c, i) => ({ ...c, tone: CONTRACT_TONES[i % CONTRACT_TONES.length] }));
  const slowest = Math.max(1, ...contracts.map((c) => c.latency?.p50 || 0));
  root.innerHTML = '<div class="figures" style="margin-bottom:40px;gap:56px">' + figure(fmt(total), "近 14 天调用") +
    figure(failed ? ((failed / total) * 100).toFixed(1) + "%" : "0%", "失败率 · " + failed + " 次", failed ? "err" : "plain") +
    figure(lat ? lat.p50 + "″" : "—", "中位耗时", "plain") + figure(lat ? lat.p95 + "″" : "—", "95% 在此之内", "plain") +
    (tokens ? figure(fmt(tokens), "tokens", "plain") : "") + figure(d.config.provider || "跟随会话", "叙事模型", "small plain") +
    (d.config.fallback ? figure(d.config.fallback, "备用模型", "small plain") : "") + "</div>" +
    '<div class="grid cols-2"><section>' + section("调用量", { meta: "金色为成功，红色为失败；今天以深色标出",
      extra: '<div class="seg mini" role="group" aria-label="时间范围">' + [["hours", "24 小时"], ["days", "14 天"]].map(([k, l]) => '<button data-mode="' + k + '" aria-pressed="' + (mode === k) + '">' + l + "</button>").join("") + "</div>" }) +
      '<div data-chart>' + chart() + "</div>" + chartNote() + "</section>" +
    "<section>" + section("按用途", { meta: "共 " + fmt(callsAll) + " 次" }) + (contracts.length ? shares(contracts.map((c) => ({ label: contractName(c.contract), value: c.calls, tone: c.tone })), { legend: false }) +
      '<div class="use-rows"><div class="use-row head"><span>用途</span><span>调用</span><span>失败</span><span>中位耗时</span></div>' +
      contracts.map((c) => '<div class="use-row" title="' + esc(c.contract) + '"><span class="use-name"><i class="cat-dot ' + c.tone + '"></i>' + esc(contractName(c.contract)) + "</span>" +
        '<span class="num">' + fmt(c.calls) + '<small> 次</small></span><span class="num' + (c.failures ? " err-text" : " faint") + '">' + (c.failures ? "失败 " + c.failures : "无失败") + "</span>" +
        '<span class="use-lat"><i><span style="width:' + (((c.latency?.p50 || 0) / slowest) * 100).toFixed(0) + '%"></span></i><b class="num">' + (c.latency ? c.latency.p50 + "″" : "—") + "</b></span></div>").join("") +
      "</div>" : empty("暂无")) +
      '<dl class="kv" style="margin-top:22px"><dt>超时</dt><dd>' + d.config.timeout + " 秒</dd><dt>重试</dt><dd>最多 " + d.config.attempts + " 次</dd>" +
      (lat ? "<dt>最慢一次</dt><dd>" + lat.max + " 秒</dd>" : "") +
      "<dt>格式修正</dt><dd>" + fmt(d.repaired || 0) + ' 次<span class="muted">（模型漏写 null 或多写字段时自动修正）</span></dd></dl></section></div>' +
    '<section class="sec">' + section("最近失败", { count: d.failures.length }) + (d.failures.length ? '<div class="rows">' + d.failures.map((f) => '<div class="ri">' + roundIcon("alert", "err") +
      '<div style="min-width:0"><div class="ri-title">' + esc(contractName(f.contract)) + " · " + esc((f.title || "—").split(" · ")[0]) + '</div><div class="ri-meta">' + esc(f.error || f.status) +
      (f.note ? "　已自动修正：" + esc(f.note) : "") + "</div></div>" +
      '<span class="ri-side"><time>' + esc(when(f.started_at)) + "</time></span></div>").join("") + "</div>" : '<div class="rows"><div class="ri">' + roundIcon("check", "ok") + '<div class="ri-title">没有失败记录</div><span></span></div></div>') + "</section>";
  root.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
    mode = b.dataset.mode;
    root.querySelectorAll("[data-mode]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    root.querySelector("[data-chart]").innerHTML = chart();
  }));
}

async function outbox(root, ctx) {
  const d = await ctx.api.get("outbox");
  root.innerHTML = section("待重发消息", { count: d.items.length, meta: "群里暂时发不出去的消息会留在这里，群里有人再用 /团 时自动补发；也可以手动重试或放弃。" }) +
    (d.items.length ? '<div class="rows">' + d.items.map((m) => '<div class="ri" style="align-items:start">' + roundIcon("send", m.state === "pending" ? "warn" : "mute") +
      '<div style="min-width:0"><div class="ri-meta" style="margin:0 0 6px">' + dot(m.state === "pending" ? "warn" : "off", m.state === "pending" ? "待重发" : "已放弃") + '<span class="num">' + esc(m.umo) + "</span><span>" + esc(when(m.updated_at)) + " · 已尝试 " + m.attempts + " 次</span></div>" +
      '<div class="prose" style="font-size:14px;line-height:1.8">' + esc(m.text.length > 240 ? m.text.slice(0, 240) + "…" : m.text) + "</div>" + (m.last_error ? '<div class="hint" style="margin-top:6px;color:var(--danger)">' + esc(m.last_error) + "</div>" : "") + "</div>" +
      (m.state === "pending" ? '<div class="btns"><button class="btn small" data-retry="' + m.id + '">' + icon("refresh", 14) + '重试</button><button class="btn text small" data-drop="' + m.id + '">放弃</button></div>' : "<span></span>") + "</div>").join("") + "</div>"
      : '<div class="rows"><div class="ri">' + roundIcon("check", "ok") + '<div class="ri-title">全部消息都已送达</div><span></span></div></div>');
  for (const [attr, action] of [["retry", "retry"], ["drop", "drop"]]) {
    root.querySelectorAll("[data-" + attr + "]").forEach((b) => b.addEventListener("click", async () => {
      try {
        await busy(b, () => ctx.api.post("outbox/action", { id: Number(b.dataset[attr]), action }));
        ctx.toast(action === "retry" ? "已重新发送" : "已放弃");
        ctx.refresh();
      } catch (error) { ctx.toast(error.message, "error"); }
    }));
  }
}

async function audit(root, ctx) {
  const d = await ctx.api.get("audit");
  root.innerHTML = section("操作记录", { count: d.items.length, meta: "后台的每次写操作，以及开团、收桌等关键动作" }) +
    (d.items.length ? '<div class="rows">' + d.items.map((a) => {
      const [label, ic] = ACTIONS[a.action] || [a.action, "sparkle"];
      const detail = a.detail.command || Object.entries(a.detail).map(([k, v]) => k + "=" + (typeof v === "string" ? v : JSON.stringify(v))).join("　");
      return '<div class="ri">' + roundIcon(ic, "mute") + '<div style="min-width:0"><div class="ri-title">' + esc(label) + '　<span class="mono muted" style="font-weight:400">' + esc(a.target) + "</span></div>" +
        '<div class="ri-meta"><span>' + esc(a.actor.replace(/^webui:/, "后台 · ")) + "</span><span>" + esc(detail) + '</span></div></div><span class="ri-side"><time>' + esc(when(a.created_at)) + "</time></span></div>";
    }).join("") + "</div>" : empty("还没有操作记录"));
}

async function backup(root, ctx) {
  const d = await ctx.api.get("backup");
  root.innerHTML = '<div class="grid cols-even"><section>' + section("当前数据", { meta: fmt(Math.round(d.database_bytes / 1024)) + " KB · " + esc(d.path) }) +
    '<div class="figures" style="gap:24px 34px">' + Object.entries(d.counts).map(([k, v]) => figure(fmt(v), TABLES[k] || k, "small plain")).join("") + "</div>" +
    '<div class="btns" style="margin-top:28px"><button class="btn primary" data-export>' + icon("download", 15) + "导出完整备份</button></div></section>" +
    "<section>" + section("从备份恢复", { meta: "恢复会整体替换现有数据，建议先导出一份" }) + '<div class="card"><div class="field"><label for="file">备份文件</label><input class="input" id="file" type="file" accept="application/json,.json" /></div>' +
    '<div class="field"><label for="confirm">输入“覆盖”确认替换全部数据</label><input class="input" id="confirm" autocomplete="off" /></div><button class="btn danger" data-import>' + icon("upload", 15) + "恢复备份</button></div></section></div>";
  root.querySelector("[data-export]").addEventListener("click", async (e) => {
    try {
      await busy(e.currentTarget, () => ctx.api.download("backup/export", {}, "321roll-lite-backup.json"));
      ctx.toast("备份已下载");
    } catch (error) { ctx.toast(error.message, "error"); }
  });
  root.querySelector("[data-import]").addEventListener("click", async (e) => {
    const file = root.querySelector("#file").files[0];
    if (!file) return ctx.toast("请先选择备份文件", "error");
    try {
      const text = await file.text();
      await busy(e.currentTarget, () => ctx.api.post("backup/import", { data: text, confirm: root.querySelector("#confirm").value.trim() }));
      ctx.toast("已恢复备份");
      ctx.refresh();
    } catch (error) { ctx.toast(error.message, "error"); }
  });
}

