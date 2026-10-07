import { acts, busy, cover, dot, empty, esc, figure, hero, icon, radar, roundIcon, section, shortTitle, subTitle } from "../ui.js";
import * as editor from "./world_editor.js";

export async function render(root, ctx) {
  const [first, second] = ctx.route.rest;
  if (first === "import") return importer(root, ctx);
  if (first === "new") return editor.render(root, ctx, { from: ctx.route.params.from });
  if (first && second === "edit") return editor.render(root, ctx, { id: first });
  if (first) return detail(root, ctx, first);
  const data = await ctx.api.get("worlds");
  const list = data.worlds;
  const custom = list.filter((w) => w.source === "custom");
  const presets = list.filter((w) => w.source !== "custom");
  root.innerHTML = hero({
    eyebrow: "世界 · WORLDS", title: "世界",
    lead: "随插件附带六个预设世界；复制一份就能改出自己的版本，改好可以导出成文件保存或分享。停用的世界不会出现在 /团 世界 里。",
    figures: '<div class="figures">' + figure(list.filter((w) => w.enabled).length + "/" + list.length, "可开的世界") + figure(custom.length, "自定义", "plain") + "</div>",
    actions: '<a class="btn" href="#/worlds/import">' + icon("upload", 15) + '导入世界文件</a><a class="btn primary" href="#/worlds/import?start=1">' + icon("plus", 15) + "新建世界</a>",
  }) +
    (custom.length ? '<section class="sec">' + section("我的世界", { count: custom.length, meta: "自定义世界可以随时编辑、导出" }) + '<div class="cards">' + custom.map(card).join("") + "</div></section>" : "") +
    '<section class="sec">' + section("预设世界", { count: presets.length, meta: "只读 · 复制后可以改成自己的版本" }) + '<div class="cards">' + presets.map(card).join("") + "</div></section>";
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
}

function card(w) {
  const link = "#/worlds/" + encodeURIComponent(w.id);
  const s = w.shape;
  return '<article class="world-card' + (w.enabled ? "" : " off") + '"><a href="' + link + '">' + cover(w.cover, "poster", w.title) + "</a>" +
    '<div class="body"><div class="style">' + esc(w.style) + "</div>" +
    '<div class="stat-row">' + radar(s.labels, s.archetypes.map((v) => ({ values: v })), s.min, s.max, 96, false) +
      '<div class="figures">' + figure(w.attributes.length, "项属性", "small plain") + figure(w.archetypes.length, "个职业", "small plain") + figure(w.skills + w.items, "技能物品", "small plain") + figure(w.entries, "条设定", "small plain") + "</div></div>" +
    '<div class="row" style="gap:14px;font-size:12.5px;color:var(--muted)">' + acts(w.acts.map((_, i) => i + 1), 0, true) + "<span>" + w.acts.length + " 幕 · " + w.endings.length + " 个结局</span><span class=\"spacer\"></span>" +
      icon("users", 14) + "<span>" + esc(w.players) + " 人</span>" + (w.source === "custom" ? '<span class="tag gold">第 ' + w.revision + " 版</span>" : "") + "</div>" +
    '<div class="foot"><span class="row" style="gap:18px"><a class="link" href="' + link + '">查看' + icon("arrow", 14) + "</a>" +
      (w.source === "custom" ? '<a class="link" href="' + link + '/edit">' + icon("pen", 14) + "编辑</a>" : '<a class="link" href="#/worlds/new?from=' + encodeURIComponent(w.id) + '">' + icon("copy", 14) + "复制</a>") + "</span>" +
      '<label class="row" style="gap:10px;font-size:12.5px;color:var(--muted)"><span data-state>' + (w.enabled ? "已启用" : "已停用") + "</span>" +
      '<span class="switch"><input type="checkbox" data-toggle="' + esc(w.id) + '" data-name="' + esc(shortTitle(w.title)) + '" ' + (w.enabled ? "checked" : "") +
      ' aria-label="启用 ' + esc(shortTitle(w.title)) + '" /><span></span></span></label></div></div></article>';
}

export function download(w, pack, presentation, notify) {
  const blob = new Blob([JSON.stringify({ format: w.bundle_format, pack, presentation }, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = pack.id + ".world.json";
  a.click();
  notify?.("已导出 " + a.download);
}

async function detail(root, ctx, id) {
  const w = await ctx.api.get("world", { id });
  const p = w.pack, pres = w.presentation || {};
  const custom = w.source === "custom";
  const attrs = p.attributes;
  const lo = Math.min(...attrs.map((a) => a.min)), hi = Math.max(...attrs.map((a) => a.max));
  const actions = custom
    ? '<a class="btn primary" href="#/worlds/' + encodeURIComponent(id) + '/edit">' + icon("pen", 15) + '编辑</a><a class="btn" href="#/worlds/new?from=' + encodeURIComponent(id) + '">' + icon("copy", 15) +
      '复制</a><button class="btn" data-export>' + icon("download", 15) + '导出</button><button class="btn text danger" data-delete>' + icon("trash", 15) + "删除</button>"
    : '<a class="btn primary" href="#/worlds/new?from=' + encodeURIComponent(id) + '">' + icon("copy", 15) + '复制为自定义世界</a><button class="btn" data-export>' + icon("download", 15) + "导出</button>";
  root.innerHTML = '<a class="crumb" href="#/worlds">' + icon("arrow", 14, "flip") + "世界</a>" +
    '<header class="band tone-' + esc(w.cover.tone) + '" data-mark="' + esc(w.cover.mark) + '"><div class="band-top"><div style="min-width:0">' +
      '<div class="eyebrow">' + (custom ? "自定义世界 · 第 " + p.revision + " 版" : "预设世界 · 只读") + " · " + esc(p.id) + "</div><h1>" + esc(shortTitle(p.title)) + '</h1><div class="sub">' + esc(subTitle(p.title)) + "</div>" +
      '<div class="band-meta">' + dot(w.enabled ? "ok" : "off", w.enabled ? "已启用" : "已停用") + "<span>" + icon("users", 13) + " " + p.rules.recommendedMin + "–" + p.rules.recommendedMax + " 人</span><span>" +
      (pres.acts || []).length + " 幕 · " + (pres.endings || []).length + " 个结局</span><span>" + p.entries.length + " 条设定</span></div></div>" +
      '<div class="btns" style="flex:none">' + actions + "</div></div>" +
      ((pres.acts || []).length ? '<div class="band-acts">' + acts(pres.acts, 0) + "</div>" : "") + "</header>" +
    '<div class="grid cols-2"><div class="stack" style="gap:52px">' +
      "<section>" + section("世界观", { meta: esc(p.style || "") }) + '<div class="prose initial">' + esc(p.worldview) + "</div>" + (p.seed ? '<p class="quote">' + esc(p.seed) + "</p>" : "") + "</section>" +
      ((pres.acts || []).length ? "<section>" + section("幕", { count: pres.acts.length, meta: "故事的大段落，主持人用 /团 主持 换幕 推进" }) + '<div class="rows">' +
        pres.acts.map((a) => '<div class="ri"><span class="opt-num">' + a.number + '</span><div style="min-width:0"><div class="ri-title">' + esc(a.title) + '</div><div class="ri-meta">' + esc(a.lead || "") + "</div></div><span></span></div>").join("") + "</div></section>" : "") +
      "<section>" + section("职业", { count: p.archetypes.length, meta: "玩家用 /团 选职业 建角" }) + '<div class="rows">' +
        p.archetypes.map((a) => '<div class="ri">' + roundIcon("user") + '<div style="min-width:0"><div class="ri-title">' + esc(a.name) + "　<span class=\"muted\" style=\"font-weight:400\">" + esc(a.text || "") +
          '</span></div><div class="ri-meta">' + attrs.map((at) => esc(at.name) + " " + a.attributes[at.id]).join(" · ") + "</div></div>" +
          radar(attrs.map((at) => at.name), [{ values: attrs.map((at) => a.attributes[at.id]), strong: true }], lo, hi, 56, false) + "</div>").join("") + "</div></section>" +
    '</div><div class="stack" style="gap:52px">' +
      "<section>" + section("职业属性", { meta: "所有职业叠在一起看侧重" }) + '<div style="display:grid;place-items:center">' +
        radar(attrs.map((a) => a.name), p.archetypes.map((a) => ({ values: attrs.map((at) => a.attributes[at.id]) })), lo, hi, 240) + "</div>" +
        '<div class="figures" style="justify-content:space-between;margin-top:18px">' + figure(attrs.length, "项属性", "small") + figure(p.resources.length, "种资源", "small") + figure(p.skills.length, "项技能", "small") + figure(p.items.length, "件物品", "small") + "</div></section>" +
      "<section>" + section("规则") + '<dl class="kv"><dt>属性</dt><dd>' + attrs.map((a) => esc(a.name) + " " + a.min + "–" + a.max).join("、") + "</dd>" +
        "<dt>资源</dt><dd>" + p.resources.map((r) => esc(r.name) + " " + r.initial + "/" + r.max).join("、") + "</dd>" +
        "<dt>难度</dt><dd>简单 " + p.rules.difficulties.join(" · ").replace(/^(\d+) · (\d+) · (\d+) · (\d+)$/, "$1 · 标准 $2 · 困难 $3 · 极难 $4") + "</dd>" +
        "<dt>人数</dt><dd>最少 " + p.rules.minPlayers + " 人，推荐 " + p.rules.recommendedMin + "–" + p.rules.recommendedMax + " 人</dd>" +
        "<dt>设定条目</dt><dd>" + p.entries.length + " 条（公开 " + p.entries.filter((e) => e.public).length + "）</dd></dl></section>" +
      ((pres.endings || []).length ? "<section>" + section("结局", { count: pres.endings.length }) + '<div class="rows">' + pres.endings.map((e, i) => '<div class="ri"><span class="opt-num">' +
        String.fromCharCode(65 + i) + '</span><div style="min-width:0"><div class="ri-title">' + esc(e.name) + '</div><div class="ri-meta">' + esc(e.rule) + "</div></div><span></span></div>").join("") + "</div></section>" : "") +
    "</div></div>";
  root.querySelector("[data-export]").addEventListener("click", () => download(w, p, pres, ctx.toast));
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
  const presets = data.worlds.filter((w) => w.source !== "custom");
  root.innerHTML = hero({
    eyebrow: "世界 · NEW WORLD", title: "新建或导入世界", crumb: ["#/worlds", "世界"],
    lead: "从预设世界复制一份再改是最快的方式；也可以导入别人分享的 .world.json，或 321Roll 的 pack.json。",
  }) +
    '<section class="sec" id="start">' + section("从预设世界开始", { meta: "复制后进入编辑器，保存前不会影响任何东西" }) + '<div class="preset-grid">' +
      presets.map((w) => '<a class="preset" href="#/worlds/new?from=' + encodeURIComponent(w.id) + '">' + cover(w.cover, "tile") +
        "<span><b>" + esc(shortTitle(w.title)) + "</b><small>" + esc(w.players) + " 人 · " + w.archetypes.length + " 职业 · " + w.acts.length + " 幕</small></span></a>").join("") + "</div></section>" +
    '<section class="sec grid cols-2"><div>' + section("导入文件", { meta: "导出的 .world.json 可以原样导回" }) +
      '<label class="drop">' + icon("upload", 22) + '<input type="file" accept=".json,application/json" data-file="pack" /><b>选择世界文件</b><span>.world.json（Lite 导出的文件）或 pack.json</span></label>' +
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
      saveBtn.disabled = !r.ok || r.existing === "builtin";
      saveBtn.lastChild.textContent = r.existing === "custom" ? "覆盖导入" : "导入";
      out.innerHTML = r.ok
        ? (r.existing === "builtin" ? dot("err", "编号与预设世界相同，不能导入") : r.existing === "custom" ? dot("warn", "将覆盖已有的同编号世界，版本号自动递增") : dot("ok", "可以导入")) +
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
      ctx.toast("已导入，第 " + r.revision + " 版");
      ctx.go("worlds/" + encodeURIComponent(r.id));
    } catch (error) { ctx.toast(error.message, "error"); }
  });
}

