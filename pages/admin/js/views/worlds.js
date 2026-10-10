import { NARRATION, acts, busy, cover, dcScale, dot, empty, esc, figure, hero, icon, meter, narrationExtensions, narrationHint, notch, paintArt, radar, roundIcon, section, shortTitle, subTitle, tier, veiled,
  when } from "../ui.js";
import * as editor from "./world_editor.js";
import * as tavern from "./tavern.js";

const size = (n) => (n / 1048576).toFixed(n >= 10485760 ? 0 : 1) + " MB";
const host = (url) => { try { return new URL(url).host; } catch { return String(url || ""); } };
// Same name as the plugin's export (market.package_file): <id>-<C1|P2>.zip.
const packageName = (id, label) => String(id).replace(/:/g, "_") + "-" + label + ".zip";

function tabs(current) {
  return '<nav class="tabs" aria-label="世界分区">' + [["", "世界库", "book"], ["market", "世界市场", "globe"]].map(([key, label, ic]) =>
    '<a href="#/worlds' + (key ? "/" + key : "") + '"' + (key === current ? ' aria-current="page"' : "") + ">" + icon(ic, 15) + label + "</a>").join("") + "</nav>";
}

export async function render(root, ctx) {
  const [first, second] = ctx.route.rest;
  if (first === "market" && !second) return market(root, ctx);
  if (first === "import") return importer(root, ctx);
  if (first === "tavern") return tavern.render(root, ctx);
  if (first === "new") return editor.render(root, ctx, { from: ctx.route.params.from, tavern: ctx.route.params.tavern === "1" });
  if (first && second === "edit") return editor.render(root, ctx, { id: first });
  if (first) return detail(root, ctx, first);
  const data = await ctx.api.get("worlds");
  const list = data.worlds;
  const custom = list.filter((w) => w.source === "custom");
  const installed = list.filter((w) => w.source === "market");
  const presets = list.filter((w) => w.source === "builtin");
  const group = (title, items, opts) => items.length ? '<section class="sec">' + section(title, { count: items.length, ...opts }) + '<div class="cards">' + items.map(card).join("") + "</div></section>" : "";
  root.innerHTML = hero({
    eyebrow: "世界 · WORLDS", title: "世界",
    lead: "插件自带灰冠之下：祖约的进阶版（P1），装好就能开团；其余世界以核心版（C1）放在世界市场，一键安装，也能安装别人发布的世界。想写自己的世界，就用“新建世界”从空白开始；停用的世界不会出现在 /团 开启 的列表里。",
    figures: '<div class="figures">' + figure(list.filter((w) => w.enabled).length + "/" + list.length, "可开的世界") + figure(installed.length, "市场安装", "plain") + figure(custom.length, "自定义", "plain") + "</div>",
    actions: '<a class="btn" href="#/worlds/import">' + icon("upload", 15) + '导入世界文件</a><a class="btn primary" href="#/worlds/import?start=1">' + icon("plus", 15) + "新建世界</a>",
  }) + tabs("") +
    group("我的世界", custom, { meta: "自定义世界可以随时编辑、复制、导出" }) +
    group("市场世界", installed, { meta: "从世界市场安装 · 只读；在世界市场里更新或卸载" }) +
    group("自带世界", presets, { meta: "随插件安装的进阶版 · 只读", link: ["#/worlds/market", "去世界市场"] });
  root.querySelectorAll("[data-toggle]").forEach((input) => input.addEventListener("change", async () => {
    input.disabled = true;
    try {
      await ctx.api.post("worlds/toggle", { id: input.dataset.toggle, enabled: input.checked });
      input.closest(".world-card").classList.toggle("off", !input.checked);
      input.closest("label").querySelector("[data-state]").textContent = input.checked ? "已启用" : "已停用";
      ctx.toast((input.checked ? "已启用 " : "已停用 ") + input.dataset.name);
    } catch (error) {
      input.checked = !input.checked;
      ctx.toast(error.message, "error");
    } finally {
      input.disabled = false;
    }
  }));
  paintArt(root, ctx.api);
}

// Archetypes by attributes; the cell shade is the value's place in that attribute's range.
function matrix(archetypes, attrs) {
  return '<div class="matrix" style="grid-template-columns:minmax(72px,auto) repeat(' + attrs.length + ',1fr)"><span></span>' + attrs.map((a) => "<b>" + esc(a.name) + "</b>").join("") +
    archetypes.map((a) => '<span class="m-name" title="' + esc(a.name) + '">' + esc(a.name) + "</span>" + attrs.map((at) => {
      const v = a.attributes[at.id] ?? at.min, share = at.max > at.min ? (v - at.min) / (at.max - at.min) : 0;
      return '<span class="m-cell" style="--s:' + share.toFixed(2) + '">' + v + "</span>";
    }).join("")).join("") + "</div>";
}

/** The world's rules drawn: difficulty ruler, resources at the start, each attribute's range, and party size. */
function rulesBlock(p, attrs) {
  const r = p.rules, lo = Math.min(...attrs.map((a) => a.min)), hi = Math.max(...attrs.map((a) => a.max)), span = Math.max(1, hi - lo);
  const seatsRow = Array.from({ length: 8 }, (_, i) => {
    const n = i + 1, cls = n < r.minPlayers ? "" : n >= r.recommendedMin && n <= r.recommendedMax ? "rec" : "ok";
    return '<span class="' + cls + '"><i></i>' + n + "</span>";
  }).join("");
  return '<div class="rule-block"><div class="label">难度 <span class="faint">· 刻度下的百分比是属性加值为 0 时的成功率</span></div>' + dcScale(r) + "</div>" +
    '<div class="rule-block"><div class="label">资源 <span class="faint">· 开局 / 上限</span></div><div class="meters">' + p.resources.map((x, i) => meter(x.name, x.initial, x.max, i)).join("") + "</div></div>" +
    '<div class="rule-block"><div class="label">属性范围</div>' + (attrs.every((a) => a.min === lo && a.max === hi)
      ? '<p class="hint" style="margin:0">' + attrs.map((a) => esc(a.name)).join("、") + " 都在 <b class=\"num\">" + lo + "–" + hi + "</b> 之间</p>"
      : '<div class="ranges">' + attrs.map((a) => '<div class="range-row"><span>' + esc(a.name) + '</span><div class="range-track"><i style="left:' +
        (((a.min - lo) / span) * 100).toFixed(1) + "%;right:" + (((hi - a.max) / span) * 100).toFixed(1) + '%"></i></div><b class="num">' + a.min + "–" + a.max + "</b></div>").join("") + "</div>") + "</div>" +
    '<div class="rule-block"><div class="label">人数 <span class="faint">· 实心为推荐，空心可开但不推荐</span></div><div class="seat-scale">' + seatsRow + "</div></div>" +
    '<dl class="kv"><dt>设定条目</dt><dd>' + p.entries.length + " 条（公开 " + p.entries.filter((e) => e.public).length + "）</dd></dl>";
}

function card(w) {
  const link = "#/worlds/" + encodeURIComponent(w.id);
  return '<article class="world-card' + (w.enabled ? "" : " off") + '"><a href="' + link + '">' +
    cover(w.cover, "poster", w.title, w.art ? 'data-art="' + esc(w.id) + '" data-rev="' + esc(w.market?.sha256 || "") + '"' : "") + "</a>" +
    '<div class="body"><div class="style">' + esc(w.style) + "</div>" +
    '<div class="stat-row">' +
      '<div class="figures">' + figure(w.attributes.length, "项属性", "small plain") + figure(w.archetypes.length, "个职业", "small plain") + figure(w.skills + w.items, "技能物品", "small plain") + figure(w.entries, "条设定", "small plain") + "</div></div>" +
    '<div class="wc-tags"><span class="wc-tag">' + icon("book", 12) + (w.edition === "core" ? "核心版 · 第一幕后即兴" : w.acts.length + " 幕 · " + w.endings.length + " 个结局") + "</span>" +
      ["improv", "dialogue"].map((f) => w.narration?.[f] ? '<span class="wc-tag" title="' + esc(NARRATION[f].title) + '">' + esc(NARRATION[f].title.slice(0, 2)) + " <b>" + esc(w.narration[f].label) + "</b></span>" : "").join("") + "</div>" +
    '<div class="row" style="gap:14px;font-size:12.5px;color:var(--muted)"><span class="wc-played' + (w.played.rooms ? "" : " none") + '">' + icon("dice", 13) +
      (w.played.rooms ? "近 30 天 <b>" + w.played.month + "</b> 桌 · 最近开桌 " + esc(when(w.played.last_at)) : "还没开过桌") + '</span><span class="spacer"></span>' +
      icon("users", 14) + "<span>" + esc(w.players) + " 人</span>" + (w.source === "custom" ? '<span class="tag gold">' + esc(w.label) + "</span>" : w.source === "market" ? '<span class="tag gold">' + (w.art ? "图文 · " : "") + esc(w.label) + "</span>" : "") + "</div>" +
    '<div class="foot"><span class="row" style="gap:18px"><a class="link" href="' + link + '">查看' + icon("arrow", 14) + "</a>" +
      (w.source === "custom" ? '<a class="link" href="' + link + '/edit">' + icon("pen", 14) + "编辑</a>" : "") + "</span>" +
      '<label class="row" style="gap:10px;font-size:12.5px;color:var(--muted)"><span data-state>' + (w.enabled ? "已启用" : "已停用") + "</span>" +
      '<span class="switch"><input type="checkbox" data-toggle="' + esc(w.id) + '" data-name="' + esc(shortTitle(w.title)) + '" ' + (w.enabled ? "checked" : "") +
      ' aria-label="启用 ' + esc(shortTitle(w.title)) + '" /><span></span></span></label></div></div></article>';
}

export function download(w, pack, presentation, notify) {
  // Chosen narration defaults travel in the file's extensions, as in the plugin's own export.
  const chosen = Object.fromEntries(Object.entries(w.narration || {}).filter(([, d]) => d.source !== "fallback").map(([f, d]) => [f, d.value]));
  const extensions = narrationExtensions(chosen);
  const blob = new Blob([JSON.stringify({ format: w.bundle_format, pack, presentation, ...(Object.keys(extensions).length ? { extensions } : {}) }, null, 2)],
    { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = pack.id + ".world.json";
  a.click();
  notify?.("已导出 " + a.download);
}

// A world's narration defaults: what new tables start with.  Preset and market worlds keep their package as is;
// a change here is this machine's adjustment and can be undone back to the package's value.
function narrationSection(w) {
  const custom = w.source === "custom";
  const row = (field) => {
    const d = w.narration[field];
    const reset = d.source === "local" ? '<button class="btn text small" data-narr-reset="' + field + '">恢复为' + esc(d.packaged_label) + "</button>" : "";
    return '<div class="narr-row"><div class="narr-head"><b>' + NARRATION[field].title + '</b><span class="now">' + esc(d.label) + '</span><span class="spacer"></span>' +
      '<span class="narr-src">' + esc(d.source_label) + "</span>" + reset + "</div>" + notch(field, d.value) + '<p class="narr-hint">' + esc(narrationHint(field, d.value)) + "</p></div>";
  };
  return "<section>" + section("叙事默认", { meta: "新开的团桌沿用这些设置，已开的桌不受影响" }) + '<div class="narr">' + ["improv", "dialogue", "length"].map(row).join("") +
    '<div class="narr-row"><div class="narr-head"><b>文笔与基调</b><span class="spacer"></span><span class="narr-src">' + (custom ? "在编辑器的“基本信息”里修改" : "世界包") + "</span></div>" +
    '<div class="narr-text">' + esc(w.pack.style || "未填写，模型会贴合这个世界的基调与氛围。") + "</div></div></div></section>";
}

// Scene images, act titles and endings give the story away, so the detail page folds them until asked.
// The folded content sits in a <template>, so its images are not even requested before that.
const SPOILERS = {
  scenes: "场景图会提前展示后面的幕、地点和结局。确定要看吗？",
  acts: "幕的标题和引言会透露故事走向。确定要看吗？",
  endings: "结局的名字和达成条件会透露故事走向。确定要看吗？",
};
const spoiler = (kind, summary, body) => '<div class="spoiler" data-spoiler="' + kind + '"><div class="spoiler-veil">' + icon("eyeOff", 18) +
  "<p>" + esc(summary) + '</p><button class="btn small" data-reveal="' + kind + '">' + icon("eye", 14) + "查看剧透内容</button></div>" +
  '<div class="spoiler-bar"><span>' + icon("eye", 14) + '剧透内容已展开</span><button class="btn text small" data-fold>' + icon("eyeOff", 14) + "收起</button></div>" +
  '<div class="spoiler-body"></div><template>' + body + "</template></div>";

async function detail(root, ctx, id) {
  const w = await ctx.api.get("world", { id });
  const p = w.pack, pres = w.presentation || {};
  const actList = pres.acts || [], endings = pres.endings || [];
  const later = w.scenes.filter((s) => s.key !== "cover").length;
  const custom = w.source === "custom";
  const fromMarket = w.source === "market";
  const m = w.market;
  // Core editions (world cards, C1, C2…) preset the first act only and no endings; the table improvises the rest.
  const core = w.edition === "core";
  const attrs = p.attributes;
  const lo = Math.min(...attrs.map((a) => a.min)), hi = Math.max(...attrs.map((a) => a.max));
  // Only custom worlds can be edited, copied or exported as JSON; preset and market worlds stay read-only
  // and leave only as their install package, which installs read-only again elsewhere.
  const exportPackage = (cls) => '<button class="btn' + cls + '" data-package title="zip 安装包，可在另一台 AstrBot 的世界市场里上传安装">' + icon("download", 15) + "导出安装包</button>";
  const actions = custom
    ? '<a class="btn primary" href="#/worlds/' + encodeURIComponent(id) + '/edit">' + icon("pen", 15) + '编辑</a><a class="btn" href="#/worlds/new?from=' + encodeURIComponent(id) + '">' + icon("copy", 15) +
      "复制</a>" + exportPackage("") + '<button class="btn text" data-export title="可在编辑器或“导入世界文件”里打开的 JSON">JSON</button>' +
      '<button class="btn text danger" data-delete>' + icon("trash", 15) + "删除</button>"
    : exportPackage(" primary") + (fromMarket ? '<button class="btn text danger" data-uninstall>' + icon("trash", 15) + "卸载</button>" : "");
  const origin = !m ? "" : m.source === "upload" ? "上传的安装包" : m.source === "url" ? "网址安装 · " + host(m.file) : host(m.source) + " 索引";
  root.innerHTML = '<a class="crumb" href="#/worlds">' + icon("arrow", 14, "flip") + "世界</a>" +
    '<header class="band tone-' + esc(w.cover.tone) + '" data-mark="' + esc(w.cover.mark) + '"' + (w.art ? ' data-art="' + esc(id) + '" data-rev="' + esc(m.sha256) + '"' : "") + '><div class="band-top"><div style="min-width:0">' +
      '<div class="eyebrow">' + (custom ? "自定义世界 · " + esc(w.label) : fromMarket ? "市场世界 · " + esc(w.label) + (w.art ? " · 图文" : "") : "自带世界 · 进阶版 " + esc(w.label)) + " · " + esc(p.id) + "</div><h1>" + esc(shortTitle(p.title)) + '</h1><div class="sub">' + esc(subTitle(p.title)) + "</div>" +
      '<div class="band-meta">' + dot(w.enabled ? "ok" : "off", w.enabled ? "已启用" : "已停用") + "<span>" + icon("users", 13) + " " + p.rules.recommendedMin + "–" + p.rules.recommendedMax + " 人</span><span>" +
      (core ? "核心版 · 预设 1 幕 · 结局即兴" : (pres.acts || []).length + " 幕 · " + (pres.endings || []).length + " 个结局") + "</span><span>" + p.entries.length + " 条设定</span></div></div>" +
      '<div class="btns" style="flex:none">' + actions + "</div></div>" +
      (actList.length ? '<div class="band-acts">' + acts(veiled(actList, 0), 0) + "</div>" : "") + "</header>" +
    (core ? '<div class="note-box" style="margin:0 0 48px">' + icon("sparkle", 16) + "<div><b>核心版（世界卡）</b><span>预设剧情只写到第一幕，没有预设结局。开团后由 AI 即兴续写，即兴程度默认“奔放”，主持人可以用 " +
      '<span class="kbd">/团 主持 即兴</span> 调整；想开新的一幕时发送 <span class="kbd">/团 主持 换幕 标题：引子</span>，收尾时发送 <span class="kbd">/团 完结 结局名</span>。</span></div></div>' : "") +
    (later ? '<section style="margin:0 0 56px">' + section("场景图", { count: w.scenes.length, meta: "随安装包附带 · 保存在插件数据目录" }) +
      spoiler("scenes", "封面之外另有 " + later + " 张场景图，开团后随剧情出现。", '<div class="scene-grid">' +
        w.scenes.map((s) => '<figure class="scene"><div class="scene-frame" data-art="' + esc(id) + '" data-key="' + esc(s.key) + '" data-rev="' + esc(m.sha256) + '"></div><figcaption title="' + esc(s.label) + '">' +
          esc(s.label) + "</figcaption></figure>").join("") + "</div>") + "</section>" : "") +
    '<div class="grid cols-2"><div class="stack" style="gap:52px">' +
      "<section>" + section("世界观") + '<div class="prose initial">' + esc(p.worldview) + "</div>" + (p.seed ? '<p class="quote">' + esc(p.seed) + "</p>" : "") + "</section>" +
      (actList.length ? "<section>" + section("幕", { count: actList.length, meta: "故事的大段落，主持人用 /团 主持 换幕 推进" }) +
        spoiler("acts", "共 " + actList.length + " 幕。每一幕的标题和引言会在团桌推进到那一幕时揭晓。", '<div class="rows">' +
          actList.map((a) => '<div class="ri"><span class="opt-num">' + a.number + '</span><div style="min-width:0"><div class="ri-title">' + esc(a.title) + '</div><div class="ri-meta">' + esc(a.lead || "") + "</div></div><span></span></div>").join("") + "</div>") + "</section>" : "") +
      "<section>" + section("职业", { count: p.archetypes.length, meta: "玩家用 /团 选职业 建角" }) + '<div class="rows">' +
        p.archetypes.map((a) => '<div class="ri">' + roundIcon("user") + '<div style="min-width:0"><div class="ri-title">' + esc(a.name) + "　<span class=\"muted\" style=\"font-weight:400\">" + esc(a.text || "") +
          '</span></div><div class="ri-meta">' + attrs.map((at) => esc(at.name) + " " + a.attributes[at.id]).join(" · ") + "</div></div>" +
          radar(attrs.map((at) => at.name), [{ values: attrs.map((at) => a.attributes[at.id]), strong: true }], lo, hi, 56, false) + "</div>").join("") + "</div></section>" +
    '</div><div class="stack" style="gap:52px">' +
      narrationSection(w) +
      "<section>" + section("职业属性", { meta: "每列一项属性，颜色越深数值越高" }) + matrix(p.archetypes, attrs) +
        '<div class="figures" style="justify-content:space-between;margin-top:18px">' + figure(attrs.length, "项属性", "small") + figure(p.resources.length, "种资源", "small") + figure(p.skills.length, "项技能", "small") + figure(p.items.length, "件物品", "small") + "</div></section>" +
      (m ? "<section>" + section("安装信息", { meta: "在世界市场里更新或卸载" }) + '<dl class="kv"><dt>来源</dt><dd>' + esc(origin) + "</dd>" +
        "<dt>安装包</dt><dd>" + esc(m.label) + " · " + size(m.size) + " · " + m.images + " 张场景图</dd>" +
        '<dt>sha256</dt><dd class="mono" title="' + esc(m.sha256) + '">' + esc(String(m.sha256).slice(0, 16)) + "…</dd>" +
        "<dt>安装时间</dt><dd>" + esc(when(m.installed_at)) + "</dd>" +
        (w.builtin_revision ? "<dt>插件自带</dt><dd>" + esc(w.builtin_label) + "，卸载后恢复</dd>" : "") + "</dl></section>" : "") +
      "<section>" + section("规则") + rulesBlock(p, attrs) + "</section>" +
      (endings.length ? "<section>" + section("结局", { count: endings.length }) +
        spoiler("endings", "共 " + endings.length + " 个结局。结局的名字和达成条件只在故事走到那里时出现。", '<div class="rows">' + endings.map((e, i) => '<div class="ri"><span class="opt-num">' +
          String.fromCharCode(65 + i) + '</span><div style="min-width:0"><div class="ri-title">' + esc(e.name) + '</div><div class="ri-meta">' + esc(e.rule) + "</div></div><span></span></div>").join("") + "</div>") + "</section>" : "") +
    "</div></div>";
  // Revealing copies the folded content out of its <template>; folding drops the copy again.
  root.querySelectorAll("[data-spoiler]").forEach((box) => {
    const kind = box.dataset.spoiler, body = box.querySelector(".spoiler-body");
    const show = (open) => {
      body.innerHTML = open ? box.querySelector("template").innerHTML : "";
      box.classList.toggle("open", open);
      if (kind === "acts") root.querySelector(".band-acts").innerHTML = acts(open ? actList : veiled(actList, 0), 0);
      if (open) paintArt(body, ctx.api);
    };
    box.querySelector("[data-reveal]").addEventListener("click", () => { if (window.confirm(SPOILERS[kind])) show(true); });
    box.querySelector("[data-fold]").addEventListener("click", () => {
      show(false);
      if (box.getBoundingClientRect().top < 0) box.scrollIntoView({ block: "center" });
    });
  });
  root.querySelector("[data-export]")?.addEventListener("click", () => download(w, p, pres, ctx.toast));
  const setNarration = async (button, field, value) => {
    try {
      await busy(button, () => ctx.api.post("worlds/narration", { id, changes: { [field]: value } }));
      ctx.toast(value === null ? "已恢复" + NARRATION[field].title : NARRATION[field].title + "已设为“" + button.title + "”，之后新开的团桌使用");
      ctx.refresh();
    } catch (error) { ctx.toast(error.message, "error"); }
  };
  root.querySelectorAll(".narr [data-field]").forEach((b) => b.addEventListener("click", () => {
    if (!b.classList.contains("on")) setNarration(b, b.dataset.field, b.dataset.value);
  }));
  root.querySelectorAll("[data-narr-reset]").forEach((b) => b.addEventListener("click", () => setNarration(b, b.dataset.narrReset, null)));
  root.querySelector("[data-package]").addEventListener("click", async (e) => {
    try {
      const name = packageName(id, w.label);
      await busy(e.currentTarget, () => ctx.api.download("worlds/package", { id }, name));
      ctx.toast("已导出 " + name);
    } catch (error) { ctx.toast(error.message, "error"); }
  });
  root.querySelector("[data-uninstall]")?.addEventListener("click", async (e) => {
    const after = w.builtin_revision ? "卸载后恢复插件自带的版本。" : "卸载后这个世界会从列表里移除。";
    if (!window.confirm("确定卸载「" + shortTitle(p.title) + "」吗？" + after + "已开的团桌不受影响。")) return;
    try {
      await busy(e.currentTarget, () => ctx.api.post("market/uninstall", { id }));
      ctx.toast("已卸载 " + shortTitle(p.title));
      ctx.go("worlds");
    } catch (error) { ctx.toast(error.message, "error"); }
  });
  paintArt(root, ctx.api);
  root.querySelector("[data-delete]")?.addEventListener("click", async (e) => {
    if (!window.confirm("确定删除这个自定义世界吗？已开的团桌不受影响。建议先导出一份。")) return;
    try {
      await busy(e.currentTarget, () => ctx.api.post("worlds/delete", { id }));
      ctx.toast("已删除");
      ctx.go("worlds");
    } catch (error) { ctx.toast(error.message, "error"); }
  });
}

async function importer(root, ctx) {
  const data = await ctx.api.get("worlds");
  const mine = data.worlds.filter((w) => w.source === "custom");
  root.innerHTML = hero({
    eyebrow: "世界 · NEW WORLD", title: "新建世界", crumb: ["#/worlds", "世界"],
    lead: "在七步可视化编辑器里从空白写起，或复制一个自己写的世界再改；也可以把 SillyTavern 的世界书整理成世界卡，或导入别人分享的 .world.json、321Roll 的 pack.json。",
  }) +
    '<section class="sec" id="start">' + section("用编辑器新建", { meta: "七个步骤逐项提示还缺什么，保存前不会影响任何东西" }) + '<div class="start-grid' + (mine.length ? "" : " solo") + '">' +
      '<div class="start-pair"><a class="start-blank" href="#/worlds/new">' + icon("plus", 22) + "<b>从空白开始</b><span>预置五项通用属性、一种资源和常用难度，按步骤填写标题、世界观、职业、设定、幕与结局。</span><em>打开编辑器" + icon("arrow", 14) + "</em></a>" +
      '<a class="start-blank alt" href="#/worlds/tavern">' + icon("book", 22) + "<b>从酒馆导入</b><span>把 SillyTavern 的世界书或带世界书的角色卡整理成核心版世界卡：分类条目、选规则模板，可让 AI 补全职业和开场。</span><em>打开导入向导" + icon("arrow", 14) + "</em></a></div>" +
      (mine.length ? '<div><div class="label" style="margin-bottom:10px">或复制一个自己写的世界再改</div><div class="preset-grid">' +
        mine.map((w) => '<a class="preset" href="#/worlds/new?from=' + encodeURIComponent(w.id) + '">' + cover(w.cover, "tile") +
          "<span><b>" + esc(shortTitle(w.title)) + "</b><small>" + esc(w.players) + " 人 · " + w.archetypes.length + " 职业 · " + w.acts.length + " 幕</small></span></a>").join("") + "</div></div>" : "") + "</div></section>" +
    '<section class="sec grid cols-2"><div>' + section("导入文件", { meta: "导出的 .world.json 可以原样导回" }) +
      '<label class="drop">' + icon("upload", 22) + '<input type="file" accept=".json,application/json" data-file="pack" /><b>选择世界文件</b><span>.world.json（Lite 导出的文件）或 pack.json；zip 安装包请在世界市场上传</span></label>' +
      '<div class="field" style="margin-top:18px"><label for="pack">文件内容</label><textarea class="textarea" id="pack" spellcheck="false" placeholder="也可以直接粘贴 JSON"></textarea></div>' +
      '<details class="ed-more"><summary>另附 presentation.json（只在导入 321Roll 的 pack.json 时需要）</summary><div class="field" style="margin-top:12px">' +
      '<textarea class="textarea" id="presentation" spellcheck="false" style="min-height:110px"></textarea><input type="file" accept=".json,application/json" data-file="presentation" class="hint" /></div></details>' +
      '<div class="btns" style="margin-top:18px"><button class="btn" data-validate>' + icon("check", 15) + '校验</button><button class="btn primary" data-save disabled>' + icon("download", 15) + "导入</button></div></div>" +
    "<div>" + section("校验结果") + '<div data-result class="card">' + empty("还没有校验", "选择文件或粘贴内容后点“校验”") + "</div></div></section>";
  const body = () => ({ pack: root.querySelector("#pack").value, presentation: root.querySelector("#presentation").value });
  const out = root.querySelector("[data-result]");
  const saveBtn = root.querySelector("[data-save]");
  let checked = null;
  root.querySelector("#pack").addEventListener("input", () => { checked = null; saveBtn.disabled = true; });
  root.querySelectorAll("[data-file]").forEach((input) => input.addEventListener("change", async () => {
    if (!input.files[0]) return;
    root.querySelector("#" + input.dataset.file).value = await input.files[0].text();
    checked = null;
    saveBtn.disabled = true;
    root.querySelector("[data-validate]").click();
  }));
  root.querySelector("[data-validate]").addEventListener("click", async (e) => {
    try {
      const r = await busy(e.currentTarget, () => ctx.api.post("worlds/validate", body()));
      checked = r.ok ? r : null;
      saveBtn.disabled = !r.ok || r.existing === "builtin" || r.existing === "market";
      saveBtn.lastChild.textContent = r.existing === "custom" ? "覆盖导入" : "导入";
      out.innerHTML = r.ok
        ? (r.existing === "builtin" ? dot("err", "编号与自带世界相同，不能导入") : r.existing === "market" ? dot("err", "编号与市场安装的世界相同，不能导入") : r.existing === "custom" ? dot("warn", "将覆盖已有的同编号世界，版本号自动递增") : dot("ok", "可以导入")) +
          '<div class="serif" style="font-size:20px;font-weight:600;margin:16px 0 4px">' + esc(shortTitle(r.summary.title)) + '</div><div class="hint num">' + esc(r.summary.id) + "</div>" +
          '<div class="figures" style="margin-top:18px;gap:24px">' + figure(r.summary.attributes, "项属性", "small") + figure(r.summary.archetypes, "个职业", "small") + figure(r.summary.entries, "条设定", "small") +
          figure(r.summary.acts, "幕", "small") + figure(r.summary.endings, "个结局", "small") + "</div>"
        : dot("err", "不能导入") + '<div class="notice err" style="margin-top:12px">' + esc(r.error) + "</div>";
    } catch (error) { out.innerHTML = '<div class="notice err">' + esc(error.message) + "</div>"; }
  });
  saveBtn.addEventListener("click", async (e) => {
    if (!checked) return;
    if (checked.existing === "custom" && !window.confirm("确定用这个文件覆盖已有的「" + shortTitle(checked.summary.title) + "」吗？")) return;
    try {
      const r = await busy(e.currentTarget, () => ctx.api.post("worlds/save", body()));
      ctx.toast("已导入，" + (r.label || tier(null, r.revision)));
      ctx.go("worlds/" + encodeURIComponent(r.id));
    } catch (error) { ctx.toast(error.message, "error"); }
  });
}

// ---------------------------------------------------------------- world market
const STATES = {
  available: { action: "安装" },
  upgrade: { label: "插件已自带", action: "安装市场版" },
  installed: { label: "已安装", gold: true, note: () => "已是最新版本" },
  update: { label: "可更新", gold: true, action: (w) => "更新到 " + w.label, note: (w) => "已安装 " + w.installed_label },
  // Same revision, other file (e.g. an old r1 install against the index's P1): offer to replace it.
  changed: { label: "内容不同", gold: true, action: "替换安装", note: (w) => "已安装的 " + w.installed_label + " 与索引里的 " + w.label + " 内容不同" },
  older: { label: "版本较旧", note: (w) => "插件自带的 " + w.builtin_label + " 更新", warn: true },
  conflict: { label: "编号冲突", note: () => "已有同 id 的自定义世界", warn: true },
  plugin: { label: "需更新插件", note: (w) => "需要插件 " + w.min_plugin + " 或更新", warn: true },
  // Lite installs Core and Pro only: Max (the world module) needs the full 321Roll, an unknown tier a newer plugin.
  full: { label: "需要全量版", note: () => "旗舰版（世界模组），需要 321Roll 全量版", warn: true },
  tier: { label: "需更新插件", note: () => "这个版本档需要更新插件", warn: true },
};
const ROUTE_NOTES = {
  jsdelivr: "GitHub 上的文件改走 jsDelivr 镜像，失败再直连。国内网络建议用这个。",
  direct: "直接访问 GitHub。服务器在海外时用这个。",
  prefix: "在地址前加上代理前缀（例如 https://ghfast.top/），失败再直连。",
};

// Indexes can take a while to load; only the newest request may redraw the page.
let marketSeq = 0;
async function market(root, ctx, refresh = false) {
  const mine = ++marketSeq;
  const data = await ctx.api.get("market", refresh ? { refresh: "1" } : {});
  if (mine === marketSeq) draw(root, ctx, data);
}

function marketCard(w, source) {
  const st = STATES[w.status] || STATES.available;
  const pick = (v) => (typeof v === "function" ? v(w) : v || "");
  const action = pick(st.action);
  const installed = Boolean(w.installed_revision);
  const art = w.previews.length ? "data-srcs='" + esc(JSON.stringify(w.previews)) + "'" : "";
  // A Core edition's title ends in （核心版）; the poster keeps the world's name and the facts row says which edition it is.
  const core = w.edition === "core";
  const title = core ? String(w.title).replace("（核心版）", "") : w.title;
  return '<article class="world-card market-card"><div class="poster-wrap">' +
    cover(w.cover || { mark: shortTitle(title).slice(0, 1), tone: "ink" }, "poster", title, art) +
    (st.label ? '<span class="tag state' + (st.gold ? " gold" : "") + '">' + esc(st.label) + "</span>" : "") +
    // Pro packs may carry weather, ambience and other effects of the full version that Lite skips.
    (w.full_effects ? '<span class="tag extra" title="天气、氛围音等效果只在 321Roll 全量版显示">含进阶版效果（Lite 中不显示）</span>' : "") + "</div>" +
    '<div class="body"><div class="style">' + esc(w.summary || "") + "</div>" +
    '<div class="facts"><span class="num" title="版本档与修订号：C 为核心版（世界卡），P 为进阶版（世界包），M 为旗舰版（世界模组）">' + esc(w.label) + "</span>" +
      (core ? '<span class="tag gold" title="预设剧情只写到第一幕，之后由 AI 即兴续写">核心版 · 第一幕后即兴</span>' : "") + "<span>" +
      (w.images ? '<span class="num">' + w.images + "</span> 张场景图" : "纯文本") + '</span><span class="num">' + size(w.size) + "</span></div>" +
    '<div class="foot"><span class="note' + (st.warn ? " warn" : "") + '">' + esc(pick(st.note)) + '</span><span class="row" style="gap:14px">' +
      (installed ? '<a class="link" href="#/worlds/' + encodeURIComponent(w.id) + '">查看' + icon("arrow", 14) + "</a>" +
        '<button class="btn text small danger" data-uninstall="' + esc(w.id) + '" data-title="' + esc(shortTitle(w.title)) + '" data-builtin="' + (w.builtin_revision ? "1" : "") + '">卸载</button>' : "") +
      (action ? '<button class="btn primary small" data-install="' + esc(w.id) + '" data-source="' + esc(source) + '">' + icon("download", 14) + esc(action) + "</button>" : "") +
    "</span></div></div></article>";
}

function sourceBlock(s) {
  const meta = '<span class="mono">' + esc(host(s.url)) + "</span>" +
    (s.ok ? "<span>读取于 " + esc(when(s.fetched_at)) + "</span>" + (s.skipped ? "<span>" + s.skipped + " 条无法识别，已跳过</span>" : "") : "");
  const head = section(s.name || host(s.url), { count: s.ok ? s.worlds.length : null, meta });
  if (!s.ok) {
    return "<section>" + head + '<div class="source-empty">' + icon("alert", 20) + "<div><b>读取索引失败</b><p>" + esc(s.error) + "</p>" +
      "<p>索引所在的 GitHub 仓库需要公开；国内网络可以在右侧换成 jsDelivr 或代理前缀。也可以先下载安装包，再从右侧上传。</p></div></div></section>";
  }
  if (!s.worlds.length) return "<section>" + head + empty("这个索引里还没有世界") + "</section>";
  return "<section>" + head + '<div class="cards">' + s.worlds.map((w) => marketCard(w, s.url)).join("") + "</div></section>";
}

function side(data) {
  const cfg = data.settings;
  const routes = Object.entries(cfg.routes);
  const short = { jsdelivr: "jsDelivr", direct: "直连", prefix: "代理前缀" };
  return '<aside class="market-side">' +
    '<section class="panel"><div class="panel-head"><h3 class="panel-title">下载线路</h3><span class="panel-sub">' + esc(cfg.routes[cfg.route]) + "</span></div>" +
      '<div class="seg" role="group" aria-label="下载线路">' + routes.map(([key]) => '<button type="button" data-route="' + key + '" aria-pressed="' + (cfg.route === key) + '">' + short[key] + "</button>").join("") + "</div>" +
      '<p class="side-note" data-route-note>' + esc(ROUTE_NOTES[cfg.route]) + "</p>" +
      '<div class="field" data-prefix style="margin:14px 0 0' + (cfg.route === "prefix" ? "" : ";display:none") + '"><label for="mk-prefix">代理前缀</label>' +
        '<div class="row" style="gap:8px"><input class="input" id="mk-prefix" placeholder="https://ghfast.top/" value="' + esc(cfg.prefix) + '" /><button class="btn small" data-save-prefix>保存</button></div></div></section>' +
    '<section class="panel"><div class="panel-head"><h3 class="panel-title">索引地址</h3><span class="panel-sub">每行一个，最多 10 个</span></div>' +
      '<textarea class="textarea" id="mk-sources" spellcheck="false">' + esc(cfg.sources.join("\n")) + "</textarea>" +
      '<div class="btns" style="margin-top:12px"><button class="btn small" data-save-sources>' + icon("check", 14) + '保存</button><button class="btn text small" data-official>恢复官方索引</button></div>' +
      '<p class="side-note">官方索引在插件仓库的 worlds 分支。也可以填别人发布的 index.json。</p></section>' +
    '<section class="panel"><div class="panel-head"><h3 class="panel-title">离线安装</h3><span class="panel-sub">最大 ' + data.max_package_mb + " MB</span></div>" +
      '<label class="drop">' + icon("upload", 22) + '<input type="file" accept=".zip,application/zip" data-upload /><b data-upload-label>上传安装包</b><span>从别处下载或导出的 .zip</span></label>' +
      '<div class="field" style="margin:16px 0 8px"><label for="mk-url">从网址安装</label><input class="input" id="mk-url" placeholder="https://…/world-r1.zip" /></div>' +
      '<input class="input" id="mk-sha" placeholder="sha256（可选，填了就核对）" style="font:12px var(--mono)" />' +
      '<div class="btns" style="margin-top:12px"><button class="btn small" data-install-url>' + icon("download", 14) + "安装</button></div>" +
      '<p class="side-note">安装包只含 JSON 和图片，安装前会逐个核对文件，再交给世界引擎编译。</p></section></aside>';
}

function draw(root, ctx, data) {
  const all = data.sources.flatMap((s) => s.worlds);
  const count = (...states) => all.filter((w) => states.includes(w.status)).length;
  const updates = count("update");
  root.innerHTML = hero({
    eyebrow: "世界 · MARKET", title: "世界市场",
    lead: "从 GitHub 上的世界包索引安装带场景图的世界。下载后先核对每个文件的大小和 sha256，再交给世界引擎编译，全部通过才会出现在世界库里。",
    figures: '<div class="figures">' + figure(count("available", "upgrade"), "可安装") + figure(count("installed", "update", "changed"), "已安装", "plain") +
      figure(updates, "可更新", updates ? "" : "plain") + "</div>",
    actions: '<button class="btn" data-refresh>' + icon("refresh", 15) + "刷新索引</button>",
  }) + tabs("market") +
    '<div class="market-layout"><div class="stack" style="gap:56px">' +
      (data.sources.length ? data.sources.map(sourceBlock).join("")
        : '<div class="source-empty">' + icon("alert", 20) + "<div><b>还没有索引地址</b><p>在右侧填入 index.json 的地址，或点“恢复官方索引”。</p></div></div>") +
    "</div>" + side(data) + "</div>";
  const cfg = data.settings;
  // Saving is instant; the index list then shows a loading state while it is read again over the new settings.
  const again = async (refresh = false) => {
    const list = root.querySelector(".market-layout > .stack");
    if (list) list.innerHTML = '<div aria-busy="true"><div class="source-loading">' + icon("refresh", 16) + "<span>正在通过" + esc(cfg.routes[cfg.route]) +
      "读取索引，网络慢时最多等半分钟…</span></div>" + [72, 90, 64].map((w) => '<div class="skeleton" style="width:' + w + '%"></div>').join("") + "</div>";
    await market(root, ctx, refresh);
  };
  const showRoute = (route) => {
    root.querySelectorAll("[data-route]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.route === route)));
    root.querySelector("[data-route-note]").textContent = ROUTE_NOTES[route];
    root.querySelector(".market-side .panel-sub").textContent = cfg.routes[route];
    root.querySelector("[data-prefix]").style.display = route === "prefix" ? "" : "none";
  };
  const saveSettings = async (patch) => {
    const { settings: next } = await ctx.api.post("market/settings", { sources: cfg.sources, route: cfg.route, prefix: cfg.prefix, ...patch });
    Object.assign(cfg, next);
    showRoute(cfg.route);
  };
  const act = (selector, handler) => root.querySelectorAll(selector).forEach((el) => el.addEventListener("click", async (e) => {
    try { await handler(e.currentTarget); } catch (error) { ctx.toast(error.message, "error"); }
  }));
  act("[data-refresh]", async (btn) => { await busy(btn, () => again(true)); });
  act("[data-install]", async (btn) => {
    const r = await busy(btn, () => ctx.api.post("market/install", { source: btn.dataset.source, id: btn.dataset.install }));
    ctx.toast("已安装「" + shortTitle(r.title) + "」" + r.label + (r.previous ? "（原 " + r.previous_label + "）" : ""));
    await again();
  });
  act("[data-uninstall]", async (btn) => {
    const after = btn.dataset.builtin ? "卸载后恢复插件自带的版本。" : "卸载后这个世界会从列表里移除。";
    if (!window.confirm("确定卸载「" + btn.dataset.title + "」吗？" + after + "已开的团桌不受影响。")) return;
    await busy(btn, () => ctx.api.post("market/uninstall", { id: btn.dataset.uninstall }));
    ctx.toast("已卸载 " + btn.dataset.title);
    await again();
  });
  act("[data-route]", async (btn) => {
    const route = btn.dataset.route;
    showRoute(route);
    if (route === cfg.route) return;
    if (route === "prefix" && !cfg.prefix) {          // ask for the prefix first; saving it switches the route
      root.querySelector("#mk-prefix").focus();
      return;
    }
    try {
      await saveSettings({ route });
    } catch (error) {
      showRoute(cfg.route);
      throw error;
    }
    ctx.toast("下载线路：" + cfg.routes[route]);
    await again();
  });
  act("[data-save-prefix]", async (btn) => {
    await busy(btn, () => saveSettings({ route: "prefix", prefix: root.querySelector("#mk-prefix").value }));
    ctx.toast("已保存代理前缀");
    await again();
  });
  act("[data-save-sources]", async (btn) => {
    await busy(btn, () => saveSettings({ sources: root.querySelector("#mk-sources").value }));
    ctx.toast("已保存索引地址");
    await again();
  });
  act("[data-official]", async (btn) => {
    await busy(btn, () => saveSettings({ sources: [cfg.official] }));
    ctx.toast("已恢复官方索引");
    await again();
  });
  act("[data-install-url]", async (btn) => {
    const r = await busy(btn, () => ctx.api.post("market/install-url", { url: root.querySelector("#mk-url").value, sha256: root.querySelector("#mk-sha").value }));
    ctx.toast("已安装「" + shortTitle(r.title) + "」" + r.label);
    await again();
  });
  root.querySelector("[data-upload]").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const label = root.querySelector("[data-upload-label]");
    label.textContent = "正在安装 " + file.name + "…";
    try {
      const r = await ctx.api.upload("market/upload", file);
      ctx.toast("已安装「" + shortTitle(r.title) + "」" + r.label);
      await again();
    } catch (error) {
      label.textContent = "上传安装包";
      e.target.value = "";
      ctx.toast(error.message, "error");
    }
  });
  paintArt(root, ctx.api);
}
