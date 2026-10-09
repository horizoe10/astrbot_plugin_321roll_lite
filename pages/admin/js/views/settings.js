import { busy, dot, esc, figure, hero, icon, roundIcon, section } from "../ui.js";

export async function render(root, ctx) {
  const [d, about] = await Promise.all([ctx.api.get("settings"), ctx.api.get("about")]);
  const c = d.config;
  // [icon, name, value, state]: ok is ready, tip is a suggestion, warn needs setting.
  const rows = [
    ["key", "插件管理员", c.admin_ids.length ? c.admin_ids.join("、") : "未设置，只有 AstrBot 管理员可以开团", c.admin_ids.length ? "ok" : "warn"],
    ["shield", "群白名单", c.group_whitelist_enabled ? (c.allowed_groups.join("、") || "已启用，但名单为空") : "未启用，所有群都能用",
      c.group_whitelist_enabled ? (c.allowed_groups.length ? "ok" : "warn") : "tip"],
    ["sparkle", "叙事模型", c.chat_provider_id || "跟随会话使用的模型", "ok"],
    ["refresh", "备用叙事模型", c.fallback_provider_id ? c.fallback_provider_id + "，叙事模型连不上或报错时改用它" : "未设置，叙事模型出错时直接报告失败", c.fallback_provider_id ? "ok" : "tip"],
    ["hourglass", "模型超时", c.model_timeout_seconds + " 秒，失败最多重试 " + c.model_attempts + " 次", "ok"],
    ["clock", "回合限时", (c.turn_timeout_seconds ? Math.round(c.turn_timeout_seconds / 60) + " 分钟，超时自动选择风险最低的一项" : "不限时") + "；各桌可在团桌页或用 /团 主持 限时 单独调整", "ok"],
    ["users", "席位", "默认 " + c.default_seat_cap + " 人，最多 " + c.max_seat_cap + " 人", "ok"],
  ];
  const STATE = { ok: ["ok", "就绪", ""], tip: ["gold", "建议", "tip"], warn: ["warn", "待设置", "warn"] };
  const counts = { ok: 0, tip: 0, warn: 0 };
  rows.forEach((x) => { counts[x[3]] += 1; });
  const axis = (every) => '<div class="round-axis">' + Array.from({ length: 12 }, (_, i) => {
    const n = i + 1, hit = every > 0 && n % every === 0;
    return '<span class="' + (hit ? "hit" : "") + '"><i>' + (hit ? icon("sparkle", 11) : "") + "</i>" + n + "</span>";
  }).join("") + '<em>' + (every > 0 ? "第 " + every + "、" + every * 2 + "、" + every * 3 + " 轮…触发" : "已关闭") + "</em></div>";
  // Against the cap when there is one, otherwise against the busiest group.
  const most = Math.max(1, ...d.rounds_today.map((g) => g.rounds));
  const usage = (limit) => d.rounds_today.length ? '<div class="quota-rows">' + d.rounds_today.slice(0, 6).map((g) => {
    const share = Math.min(1, g.rounds / (limit || most));
    return '<div class="quota-row"><span title="' + esc(g.umo) + '">群 ' + esc(g.group_id) + '<small>' + esc(String(g.title || "").split(" · ")[0]) + '</small></span><i class="' + (limit && g.rounds >= limit ? "full" : "") +
      '"><span style="width:' + (share * 100).toFixed(0) + '%"></span></i><b class="num">' + g.rounds + (limit ? "/" + limit : " 轮") + "</b></div>";
  }).join("") + "</div>" : '<p class="hint" style="margin:10px 0 0">今天还没有群进行 AI 叙事。</p>';
  root.innerHTML = hero({
    eyebrow: "设置 · SETTINGS", title: "设置",
    lead: "基础配置在 AstrBot 的插件配置里修改，这里显示当前生效的值；集体事件间隔只在这里设置。",
    figures: '<div class="figures">' + figure(c.admin_ids.length, "管理员", "plain") + figure(d.collective_every || "关", "轮一次集体事件", "plain") + "</div>",
  }) +
    '<div class="grid cols-2"><section>' + section("插件配置", { meta: "AstrBot › 插件 › 321Roll Lite › 配置" }) +
      '<div class="readiness"><span class="r-ok"><b>' + counts.ok + "</b>项就绪</span>" + (counts.tip ? '<span class="r-tip"><b>' + counts.tip + "</b>项建议调整</span>" : "") +
      (counts.warn ? '<span class="r-warn"><b>' + counts.warn + "</b>项待设置</span>" : "") + '<div class="readiness-bar">' + rows.map((x) => '<i class="' + STATE[x[3]][2] + '" title="' + esc(x[1]) + '"></i>').join("") + "</div></div>" +
      '<div class="rows">' + rows.map(([ic, k, v, state]) =>
      '<div class="ri' + (state === "ok" ? "" : " cfg-" + state) + '">' + roundIcon(ic, state === "warn" ? "warn" : state === "tip" ? "" : "mute") + '<div style="min-width:0"><div class="ri-title">' + esc(k) + '</div><div class="ri-meta">' + esc(v) + "</div></div>" +
      dot(STATE[state][0], STATE[state][1]) + "</div>").join("") + "</div></section>" +
    '<div class="stack" style="gap:52px"><section>' + section("集体事件", { meta: "模型生成一个突发情况，全队投票决定走向" }) +
      '<div class="card"><div class="field"><label for="every">每隔多少轮触发一次（0 为关闭）</label><div class="row"><input class="input num" id="every" type="number" min="0" max="20" value="' + d.collective_every +
      '" style="width:120px" /><button class="btn primary" data-save>' + icon("check", 15) + '保存</button></div></div><div data-axis>' + axis(d.collective_every) + '</div><p class="hint" style="margin:0">主持人也可以随时用 /团 主持 集体事件 手动发起。</p></div></section>' +
    "<section>" + section("每日叙事上限", { meta: "控制模型费用，按北京时间每天零点重置" }) +
      '<div class="card"><div class="field"><label for="round-limit">每个群每天最多 AI 叙事几轮（0 为不限）</label><div class="row"><input class="input num" id="round-limit" type="number" min="0" max="' + d.round_limit_max + '" value="' + d.round_limit +
      '" style="width:120px" /><button class="btn primary" data-save-limit>' + icon("check", 15) + '保存</button></div></div><div class="label" style="margin:4px 0 8px">今天各群已用</div><div data-quota>' + usage(d.round_limit) + "</div>" +
      '<p class="hint" style="margin:12px 0 0">玩家每完成一次行动算一轮；开场、集体事件和主持人重试不计。用完后群里会提示明天再继续。</p></div></section>' +
    "<section>" + section("关于") + '<div class="about-brand"><span class="about-logo" aria-hidden="true"></span><div><b>321Roll Lite</b><span>群聊文字跑团 · 321Roll 世界引擎</span></div></div><dl class="kv"><dt>插件</dt><dd class="num">' + esc(about.version) + '</dd><dt>世界引擎</dt><dd class="num">' + esc(about.engine_version) +
      '</dd><dt>数据库</dt><dd class="num">schema ' + esc(about.database_schema) + '</dd><dt>世界格式</dt><dd class="num">' + esc(about.world_format) + "</dd><dt>指令</dt><dd>" + about.commands +
      ' 个，群里发送 /团 帮助 查看</dd><dt>数据目录</dt><dd class="num">' + esc(about.data_dir) + "</dd></dl></section></div></div>";
  root.querySelector("#every").addEventListener("input", (e) => { root.querySelector("[data-axis]").innerHTML = axis(Math.max(0, Number(e.target.value) || 0)); });
  root.querySelector("#round-limit").addEventListener("input", (e) => { root.querySelector("[data-quota]").innerHTML = usage(Math.max(0, Number(e.target.value) || 0)); });
  root.querySelector("[data-save]").addEventListener("click", async (e) => {
    try {
      await busy(e.currentTarget, () => ctx.api.post("settings/set", { collective_every: Number(root.querySelector("#every").value) }));
      ctx.toast("已保存");
    } catch (error) { ctx.toast(error.message, "error"); }
  });
  root.querySelector("[data-save-limit]").addEventListener("click", async (e) => {
    try {
      await busy(e.currentTarget, () => ctx.api.post("settings/set", { round_limit: Number(root.querySelector("#round-limit").value) }));
      ctx.toast("已保存");
    } catch (error) { ctx.toast(error.message, "error"); }
  });
}

