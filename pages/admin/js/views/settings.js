import { busy, dot, esc, figure, hero, icon, roundIcon, section } from "../ui.js";

export async function render(root, ctx) {
  const [d, about] = await Promise.all([ctx.api.get("settings"), ctx.api.get("about")]);
  const c = d.config;
  const rows = [
    ["key", "插件管理员", c.admin_ids.length ? c.admin_ids.join("、") : "未设置，只有 AstrBot 管理员可以开团", c.admin_ids.length > 0],
    ["shield", "群白名单", c.group_whitelist_enabled ? (c.allowed_groups.join("、") || "已启用，但名单为空") : "未启用，所有群都能用", true],
    ["sparkle", "叙事模型", c.chat_provider_id || "跟随会话使用的模型", true],
    ["hourglass", "模型超时", c.model_timeout_seconds + " 秒，失败最多重试 " + c.model_attempts + " 次", true],
    ["clock", "回合限时", (c.turn_timeout_seconds ? Math.round(c.turn_timeout_seconds / 60) + " 分钟，超时自动选择风险最低的一项" : "不限时") + "；各桌可在团桌页或用 /团 主持 限时 单独调整", true],
    ["users", "席位", "默认 " + c.default_seat_cap + " 人，最多 " + c.max_seat_cap + " 人", true],
  ];
  root.innerHTML = hero({
    eyebrow: "设置 · SETTINGS", title: "设置",
    lead: "基础配置在 AstrBot 的插件配置里修改，这里显示当前生效的值；集体事件间隔只在这里设置。",
    figures: '<div class="figures">' + figure(c.admin_ids.length, "管理员", "plain") + figure(d.collective_every || "关", "轮一次集体事件", "plain") + "</div>",
  }) +
    '<div class="grid cols-2"><section>' + section("插件配置", { meta: "AstrBot › 插件 › 321Roll Lite › 配置" }) + '<div class="rows">' + rows.map(([ic, k, v, ok]) =>
      '<div class="ri">' + roundIcon(ic, ok ? "" : "warn") + '<div style="min-width:0"><div class="ri-title">' + esc(k) + '</div><div class="ri-meta">' + esc(v) + "</div></div>" + dot(ok ? "ok" : "warn", ok ? "就绪" : "待设置") + "</div>").join("") + "</div></section>" +
    '<div class="stack" style="gap:52px"><section>' + section("集体事件", { meta: "模型生成一个突发情况，全队投票决定走向" }) +
      '<div class="card"><div class="field"><label for="every">每隔多少轮触发一次（0 为关闭）</label><div class="row"><input class="input num" id="every" type="number" min="0" max="20" value="' + d.collective_every +
      '" style="width:120px" /><button class="btn primary" data-save>' + icon("check", 15) + '保存</button></div></div><p class="hint" style="margin:0">主持人也可以随时用 /团 主持 集体事件 手动发起。</p></div></section>' +
    "<section>" + section("关于") + '<div class="about-brand"><span class="about-logo" aria-hidden="true"></span><div><b>321Roll Lite</b><span>群聊文字跑团 · 321Roll 世界引擎</span></div></div><dl class="kv"><dt>插件</dt><dd class="num">' + esc(about.version) + '</dd><dt>世界引擎</dt><dd class="num">' + esc(about.engine_version) +
      '</dd><dt>数据库</dt><dd class="num">schema ' + esc(about.database_schema) + '</dd><dt>世界格式</dt><dd class="num">' + esc(about.world_format) + "</dd><dt>指令</dt><dd>" + about.commands +
      ' 个，群里发送 /团 帮助 查看</dd><dt>数据目录</dt><dd class="num">' + esc(about.data_dir) + "</dd></dl></section></div></div>";
  root.querySelector("[data-save]").addEventListener("click", async (e) => {
    try {
      await busy(e.currentTarget, () => ctx.api.post("settings/set", { collective_every: Number(root.querySelector("#every").value) }));
      ctx.toast("已保存");
    } catch (error) { ctx.toast(error.message, "error"); }
  });
}

