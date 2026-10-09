// 从酒馆导入: a SillyTavern lorebook or scenario card becomes a Core-edition world card in four steps,
// then opens in the seven-step editor.  Nothing is saved until the editor saves; the wizard keeps its
// state in sessionStorage so a reload or a detour does not lose the sorting work.
import { busy, cover, dot, empty, esc, figure, hero, icon, section } from "../ui.js";

const KEY = "roll-lite-tavern-wizard";
export const HANDOFF = "roll-lite-tavern-draft";
const STEPS = [["read", "读取", "上传或粘贴酒馆文件"], ["sort", "整理条目", "分类、公开与字数"], ["rules", "规则与开场", "模板、职业与第一幕"], ["preview", "预览", "检查后交给编辑器"]];
const ENTRY = ["region", "place", "faction", "npc", "goal", "clue"];
const PUBLIC_HINT = "玩家一开始就知道的条目；不公开的条目只给主持 AI 看";

const load = () => { try { return JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch { return null; } };
const keep = (w) => { try { sessionStorage.setItem(KEY, JSON.stringify(w)); } catch { /* storage full or unavailable */ } };
const len = (s) => String(s || "").length;

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("文件读取失败"));
    reader.readAsDataURL(file);
  });
}

// A budget bar: used against the limit, with an optional advised tick.
function budget(label, used, limit, { advised = 0, note = "" } = {}) {
  const top = Math.max(limit, used);
  const state = used > limit ? "over" : advised && used > advised ? "warn" : "ok";
  return '<div class="tbudget ' + state + '"><div class="tbudget-head"><b>' + esc(label) + '</b><span class="num">' + used.toLocaleString("zh-CN") + " / " + limit.toLocaleString("zh-CN") + " 字</span></div>" +
    '<div class="tbudget-bar"><span style="width:' + (Math.min(1, used / top) * 100).toFixed(1) + '%"></span>' + (advised ? '<i style="left:' + (advised / top * 100).toFixed(1) + '%" title="建议 ' + advised + ' 字以内"></i>' : "") +
    "</div>" + (note ? '<small>' + note + "</small>" : "") + "</div>";
}

export async function render(root, ctx) {
  const meta = await ctx.api.get("worlds/tavern/templates");
  const kindLabel = Object.fromEntries(meta.kinds.map((k) => [k.key, k.label]));
  const L = meta.limits;
  let w = load() || { step: 0, draft: null, template: "adventure", extras: null, wantOpening: true, built: null, filter: "" };

  root.innerHTML = '<div class="tview">' + hero({
    eyebrow: "世界 · 从酒馆导入", title: "从酒馆导入世界卡", crumb: ["#/worlds/import", "新建世界"],
    lead: "把 SillyTavern 的世界书或带世界书的角色卡整理成一张核心版世界卡：只预设第一幕，之后由团桌即兴推进。整理好后在七步编辑器里检查并保存。",
  }) + '<div class="ed-layout"><nav class="stepper" data-stepper aria-label="导入步骤"></nav><section class="ed-main"><div data-body></div></section></div></div>';
  root = root.firstElementChild;
  const stepper = root.querySelector("[data-stepper]"), body = root.querySelector("[data-body]");

  const save = () => keep(w);
  const entries = () => w.draft?.entries || [];
  const included = () => entries().filter((e) => e.include);
  const worldviewChars = () => len(w.draft?.worldview) + included().filter((e) => e.kind === "worldview").reduce((s, e) => s + len(e.name) + len(e.content) + 3, 0);
  const guidanceChars = () => included().filter((e) => e.kind === "guidance").reduce((s, e) => s + len(e.name) + len(e.content) + 2, 0);
  const hostChars = () => included().filter((e) => ENTRY.includes(e.kind)).reduce((s, e) => s + len(e.name) + 12 + Math.min(len(e.content), L.entry) + len(e.summary), 0) + guidanceChars();

  function drawStepper() {
    stepper.innerHTML = STEPS.map(([k, label, sub], i) => {
      const reachable = i === 0 || (w.draft && (i < 3 || w.step >= 2));
      const state = i === w.step ? "now" : i < w.step ? "ok" : "";
      const small = i === 0 && w.draft ? (w.draft.kind === "card" ? "角色卡 · " : "世界书 · ") + entries().length + " 条" :
        i === 1 && w.draft ? included().length + " 条导入" : i === 2 && w.draft ? (meta.templates.find((t) => t.id === w.template)?.name || "") + (w.extras ? " · AI 已补全" : "") : sub;
      return '<button type="button" class="step ' + state + '" data-goto="' + i + '"' + (reachable ? "" : " disabled") + (i === w.step ? ' aria-current="step"' : "") +
        '><span class="step-no">' + (i < w.step ? icon("check", 13) : i + 1) + '</span><span class="step-text"><b>' + label + "</b><small>" + esc(small) + "</small></span></button>";
    }).join("") + '<div class="tstep-reset"><button type="button" class="btn text small" data-reset>' + icon("refresh", 13) + "重新开始</button></div>";
  }

  // ------------------------------------------------------------ step 1: read
  function stepRead() {
    const d = w.draft;
    return '<div class="panel ed-panel"><div class="ed-step-head"><span class="eyebrow">第 1 步</span><h2>读取酒馆文件</h2><p class="hint">世界书 JSON、带世界书的角色卡（PNG 或 JSON）都可以。</p></div>' +
      '<div class="grid cols-2" style="gap:28px"><div><label class="drop">' + icon("upload", 22) + '<input type="file" accept=".json,.png,application/json,image/png" data-file /><b>选择文件</b><span>world_info / lorebook JSON，或 chara_card_v2 / v3 角色卡</span></label>' +
      '<div class="field" style="margin-top:16px"><label class="label" for="tv-text">或粘贴 JSON</label><textarea class="textarea" id="tv-text" rows="6" spellcheck="false"></textarea></div>' +
      '<div class="btns"><button class="btn" data-parse-text>' + icon("check", 15) + "读取粘贴的内容</button></div></div>" +
      '<div class="tmap"><div class="label">酒馆里的内容会放到哪里</div>' +
      [["世界书条目", "地区、地点、势力、人物、目标、线索，也可以并入世界观或作为主持要点"], ["角色卡的描述", "世界观"], ["开场白（first_mes）", "开场"],
        ["场景（scenario）", "开场局面"], ["角色与人设", "不导入：玩家用自己的人设卡"]].map(([a, b]) => '<div class="tmap-row"><span>' + esc(a) + "</span>" + icon("arrow", 14) + "<b>" + esc(b) + "</b></div>").join("") +
      '<p class="hint" style="margin-top:12px">属性、资源、技能和职业来自下一步选择的规则模板，也可以让 AI 按世界补全职业。</p></div></div>' +
      (d ? '<hr class="rule" /><div class="tread">' + dot("ok", "已读取") + '<div class="tread-title serif">' + esc(d.title) + '</div><div class="figures" style="gap:28px;margin-top:14px">' +
        figure(d.kind === "card" ? "角色卡" : "世界书", "文件类型", "small plain") + figure(d.entries.length, "条条目", "small") + figure(len(d.worldview), "字世界观", "small plain") +
        figure(d.seed ? "有" : "无", "开场白", "small plain") + "</div>" + (d.skipped ? '<div class="notice warn" style="margin-top:12px">条目超过 ' + L.entries + " 条，后面的 " + d.skipped + " 条没有读入。</div>" : "") +
        '<div class="btns" style="margin-top:18px"><button class="btn primary" data-goto="1">下一步：整理条目' + icon("arrow", 14) + "</button></div></div>" : "") + "</div>";
  }

  // ------------------------------------------------------------ step 2: sort
  function distribution() {
    const list = included();
    if (!list.length) return '<div class="hint">没有要导入的条目。</div>';
    const counts = meta.kinds.map((k) => [k.key, list.filter((e) => e.kind === k.key).length]).filter(([, n]) => n);
    return '<div class="tdist"><div class="tdist-bar">' + counts.map(([k, n]) => '<span class="tk-' + k + '" style="flex:' + n + '" title="' + esc(kindLabel[k]) + " " + n + ' 条"></span>').join("") + "</div>" +
      '<div class="tdist-legend">' + counts.map(([k, n]) => '<button type="button" class="tdist-key' + (w.filter === k ? " on" : "") + '" data-filter="' + k + '"><i class="tk-' + k + '"></i>' + esc(kindLabel[k]) + "<b class=\"num\">" + n + "</b></button>").join("") +
      (w.filter ? '<button type="button" class="btn text small" data-filter="">显示全部</button>' : "") + "</div></div>";
  }
  function budgets() {
    return budget("世界观（含并入的条目）", worldviewChars(), L.worldview, { advised: L.worldview_advised, note: "超过上限的部分会被截掉；建议 " + L.worldview_advised + " 字以内，太长可以让 AI 压缩" }) +
      budget("主持上下文（条目与主持要点）", hostChars(), L.host, { note: "每轮只给主持 AI 看；超出时从最后一条开始舍去，重要的条目请排在前面" });
  }
  function entryRow(e, i) {
    if (w.filter && e.kind !== w.filter) return "";
    const canPublic = ENTRY.includes(e.kind);
    return '<div class="trow' + (e.include ? "" : " off") + '" data-row="' + i + '"><label class="switch" title="导入这一条"><input type="checkbox" data-include="' + i + '"' + (e.include ? " checked" : "") + " /><span></span></label>" +
      '<div class="trow-main"><div class="trow-name"><b>' + esc(e.name || "未命名") + "</b>" + (e.constant ? '<span class="tag gold">常驻</span>' : "") +
      (e.keys?.length ? '<small>' + esc(e.keys.slice(0, 4).join("、")) + "</small>" : "") + "</div>" +
      '<details class="trow-text"><summary>' + esc(String(e.content || "").slice(0, 70)) + (len(e.content) > 70 ? "…" : "") + "</summary><textarea class=\"input\" rows=\"6\" data-content=\"" + i + "\">" + esc(e.content) + "</textarea></details>" +
      (canPublic && e.public ? '<input class="input trow-sum" data-summary="' + i + '" value="' + esc(e.summary || "") + '" placeholder="玩家能看到的表面描述（不写秘密）" />' : "") + "</div>" +
      '<select class="select tk-sel tk-' + e.kind + '" data-kind="' + i + '">' + meta.kinds.map((k) => '<option value="' + k.key + '"' + (k.key === e.kind ? " selected" : "") + ">" + esc(k.label) + "</option>").join("") + "</select>" +
      '<label class="trow-pub' + (canPublic ? "" : " na") + '" title="' + PUBLIC_HINT + '"><span class="switch small"><input type="checkbox" data-public="' + i + '"' + (e.public ? " checked" : "") + (canPublic ? "" : " disabled") + " /><span></span></span>公开</label>" +
      '<span class="trow-len num' + (len(e.content) > 600 ? " long" : "") + '">' + len(e.content) + "</span></div>";
  }
  function stepSort() {
    const d = w.draft;
    return '<div class="panel ed-panel"><div class="ed-step-head"><span class="eyebrow">第 2 步</span><h2>整理条目</h2><p class="hint">按 Lite 的设定类型归类，决定哪些公开给玩家。可以先让 AI 分类，再逐条调整。</p></div>' +
      '<div class="grid cols-even" style="gap:0 20px"><label class="field"><span class="label">世界名称</span><input class="input" data-title value="' + esc(d.title) + '" /></label>' +
      '<div class="field"><span class="label">AI 帮忙</span><div class="btns"><button class="btn" data-classify>' + icon("sparkle", 15) + "AI 分类与公开</button><button class=\"btn\" data-condense>" + icon("layers", 15) + "AI 压缩过长内容</button></div></div></div>" +
      '<label class="field"><span class="label row between">世界观<span class="count num" data-wv-count></span></span><textarea class="input" rows="6" data-worldview>' + esc(d.worldview) + "</textarea><span class=\"hint\">角色卡的描述会放在这里；世界书没有时，可以把“并入世界观”的条目合进来，也可以自己写。</span></label>" +
      '<div class="tbudgets" data-budgets>' + budgets() + "</div>" +
      '<div class="label" style="margin-top:20px">条目类型</div><div data-dist>' + distribution() + "</div>" +
      '<div class="trows-head"><span>导入</span><span>条目</span><span>类型</span><span>公开</span><span>字数</span></div><div class="trows">' + (d.entries.map(entryRow).join("") || empty("没有条目", "这个文件里没有世界书条目，可以只用世界观和开场")) + "</div>" +
      '<div class="btns" style="margin-top:20px"><button class="btn" data-goto="0">' + icon("arrow", 14, "flip") + '上一步</button><button class="btn primary" data-goto="2">下一步：规则与开场' + icon("arrow", 14) + "</button></div></div>";
  }
  function refreshSort() {
    const b = root.querySelector("[data-budgets]"); if (b) b.innerHTML = budgets();
    const dEl = root.querySelector("[data-dist]"); if (dEl) dEl.innerHTML = distribution();
    const c = root.querySelector("[data-wv-count]"); if (c) c.textContent = len(w.draft.worldview) + " 字";
    drawStepper();
  }

  // ------------------------------------------------------------ step 3: rules and opening
  function stepRules() {
    const x = w.extras;
    const tpl = (t) => '<button type="button" class="ttpl' + (t.id === w.template ? " on" : "") + '" data-template="' + t.id + '"><b>' + esc(t.name) + "</b><p>" + esc(t.text) + "</p>" +
      '<div class="chips">' + t.attributes.map((a) => '<span class="tag">' + esc(a) + "</span>").join("") + "</div>" +
      '<div class="ttpl-res">' + t.resources.map((r) => "<span>" + esc(r.name) + ' <b class="num">' + r.max + "</b></span>").join("") + "</div>" +
      '<small>' + (x && t.id === w.template ? "职业由 AI 按世界补全" : "职业：" + t.archetypes.map((a) => esc(a.name)).join("、")) + "</small></button>";
    const arche = x ? '<div class="tarch">' + x.archetypes.map((a, i) => '<div class="tarch-card"><div class="row between"><b>' + esc(a.name) + '</b><button type="button" class="btn text small danger" data-drop-arch="' + i + '">移除</button></div><p>' + esc(a.text) + "</p>" +
      a.skills.map((s) => '<div class="tarch-skill">' + icon("bolt", 12) + "<span><b>" + esc(s.name) + "</b>" + esc(s.text) + "</span></div>").join("") + "</div>").join("") + "</div>" : "";
    const val = (k) => esc(x?.[k] ?? "");
    return '<div class="panel ed-panel"><div class="ed-step-head"><span class="eyebrow">第 3 步</span><h2>规则与开场</h2><p class="hint">酒馆文件里没有数值规则，从五套模板里选一套最接近的；之后在编辑器里都能改。</p></div>' +
      '<div class="ttpls">' + meta.templates.map(tpl).join("") + "</div>" +
      '<hr class="rule" /><div class="ed-sec"><div><h3>AI 补全</h3><p class="hint">按世界设定写 3–5 个职业和技能、第一幕的标题与目标' + (w.draft.seed ? "；文件里已有开场白，可选择保留" : "，以及一段开场") + "。</p></div>" +
      '<div class="btns"><label class="row" style="gap:8px;font-size:13px"><span class="switch small"><input type="checkbox" data-want-opening' + (w.wantOpening ? " checked" : "") + ' /><span></span></span>' + (w.draft.seed ? "重写开场" : "写开场") + "</label>" +
      '<button class="btn primary" data-complete>' + icon("wand", 15) + (x ? "重新补全" : "AI 补全") + "</button>" + (x ? '<button class="btn text" data-clear-extras>不用 AI 的结果</button>' : "") + "</div></div>" +
      (x ? arche + '<div class="grid cols-even" style="gap:0 20px;margin-top:18px">' +
        '<label class="field"><span class="label">第一幕标题</span><input class="input" data-x="act.title" value="' + esc(x.act?.title || "") + '" /></label>' +
        '<label class="field"><span class="label">第一幕目标</span><input class="input" data-x="goal" value="' + val("goal") + '" /></label>' +
        '<label class="field"><span class="label">开场地点</span><input class="input" data-x="place" value="' + val("place") + '" /></label>' +
        '<label class="field"><span class="label">开场时间</span><input class="input" data-x="time" value="' + val("time") + '" /></label></div>' +
        '<label class="field"><span class="label">第一幕引言</span><input class="input" data-x="act.lead" value="' + esc(x.act?.lead || "") + '" /></label>' +
        (x.seed ? '<label class="field"><span class="label">开场</span><textarea class="input" rows="7" data-x="seed">' + val("seed") + "</textarea></label>" : "")
        : '<div class="notice" style="margin-top:6px">不用 AI 也可以：职业用模板自带的三个，开场' + (w.draft.seed ? "沿用文件里的开场白" : "和开场地点留给编辑器里填写") + "。</div>") +
      (w.draft.seed && !(x && x.seed) ? '<details class="ed-more" style="margin-top:16px"><summary>文件里的开场白（' + len(w.draft.seed) + " 字）</summary><p class=\"serif tseed\">" + esc(w.draft.seed) + "</p></details>" : "") +
      '<div class="btns" style="margin-top:20px"><button class="btn" data-goto="1">' + icon("arrow", 14, "flip") + '上一步</button><button class="btn primary" data-goto="3">生成预览' + icon("arrow", 14) + "</button></div></div>";
  }

  // ------------------------------------------------------------ step 4: preview
  function stepPreview() {
    const b = w.built;
    if (!b) return '<div class="panel ed-panel">' + empty("正在生成预览", "") + "</div>";
    const p = b.pack, r = b.report;
    return '<div class="panel ed-panel"><div class="ed-step-head"><span class="eyebrow">第 4 步</span><h2>预览</h2><p class="hint">这是一份还没保存的世界卡草稿。打开编辑器后可以逐项修改，保存后才会出现在世界库里。</p></div>' +
      '<div class="tprev"><div>' + cover(b.cover, "poster", p.title) + '<div class="chips" style="margin-top:12px"><span class="tag gold">核心版 · 世界卡</span><span class="tag">只预设第一幕</span><span class="tag">即兴：奔放</span></div></div>' +
      '<div><div class="figures" style="gap:28px">' + figure(p.attributes.length, "项属性", "small") + figure(p.archetypes.length, "个职业", "small") + figure(p.skills.length + p.items.length, "技能物品", "small") +
        figure(p.entries.length, "条设定", "small") + figure(p.entries.filter((e) => e.public).length, "条公开", "small plain") + "</div>" +
      '<div class="tbudgets" style="margin-top:20px">' + budget("世界观", Math.min(r.worldview_chars, r.worldview_limit), r.worldview_limit, { note: r.worldview_cut ? "原文 " + r.worldview_chars + " 字，已截到上限" : "" }) +
        budget("主持上下文（第一幕）", r.host_chars, r.host_limit, { note: r.entries_dropped ? "有 " + r.entries_dropped + " 条条目放不下，主持 AI 读不到；可以在编辑器里精简" : "全部条目都在主持 AI 的视野里" }) + "</div>" +
      '<div class="label" style="margin-top:18px">职业</div><div class="chips">' + p.archetypes.map((a) => '<span class="tag">' + esc(a.name) + "</span>").join("") + "</div>" +
      '<div class="label" style="margin-top:14px">开场</div><p class="serif tseed">' + esc(p.seed ? p.seed.slice(0, 220) + (p.seed.length > 220 ? "…" : "") : "（还没有开场）") + "</p>" +
      (b.issues.length ? '<div class="notice warn"><b>打开编辑器后还要处理 ' + b.issues.length + " 项</b><ul>" + b.issues.map((m) => "<li>" + esc(m) + "</li>").join("") + "</ul></div>"
        : '<div class="notice ok">' + dot("ok", "规则已通过世界引擎编译，可以直接保存") + "</div>") + "</div></div>" +
      '<div class="btns" style="margin-top:20px"><button class="btn" data-goto="2">' + icon("arrow", 14, "flip") + '上一步</button><button class="btn primary" data-open>' + icon("pen", 15) + "在编辑器中打开</button></div></div>";
  }

  async function build() {
    w.built = await ctx.api.post("worlds/tavern/build", { draft: w.draft, template: w.template, extras: w.extras || {} });
    save();
  }

  function draw() {
    drawStepper();
    body.innerHTML = [stepRead, stepSort, stepRules, stepPreview][w.step]();
    if (w.step === 1) refreshSort();
  }
  async function goto(i) {
    if (i > 0 && !w.draft) return;
    w.step = i;
    if (i === 3) { w.built = null; draw(); try { await build(); } catch (error) { ctx.toast(error.message, "error"); w.step = 2; } }
    save();
    draw();
    root.scrollIntoView({ block: "start" });
  }
  function setDraft(d) {
    w = { step: 0, draft: d, template: w.template || "adventure", extras: null, wantOpening: !d.seed, built: null, filter: "" };
    save();
    draw();
    ctx.toast("读取了「" + d.title + "」，共 " + d.entries.length + " 条");
  }
  const setPath = (obj, path, value) => { const keys = path.split("."); const last = keys.pop(); keys.reduce((o, k) => (o[k] = o[k] || {}), obj)[last] = value; };

  root.addEventListener("click", async (e) => {
    const t = e.target;
    const g = t.closest("[data-goto]");
    if (g && !g.disabled) return goto(Number(g.dataset.goto));
    try {
      if (t.closest("[data-reset]")) {
        if (w.draft && !window.confirm("清空这次导入的整理进度，重新开始？")) return;
        w = { step: 0, draft: null, template: "adventure", extras: null, wantOpening: true, built: null, filter: "" };
        save(); draw();
      } else if (t.closest("[data-parse-text]")) {
        const text = root.querySelector("#tv-text").value.trim();
        if (!text) throw new Error("先粘贴 JSON");
        setDraft(await busy(t.closest("[data-parse-text]"), () => ctx.api.post("worlds/tavern/parse", { text })));
      } else if (t.closest("[data-filter]")) {
        w.filter = t.closest("[data-filter]").dataset.filter; save(); draw();
      } else if (t.closest("[data-classify]")) {
        const res = await busy(t.closest("[data-classify]"), () => ctx.api.post("worlds/tavern/classify", { title: w.draft.title, entries: entries().map((e) => ({ name: e.name, content: e.content })) }));
        res.entries.forEach((r) => { const e = entries()[r.i]; if (!e) return; if (r.kind) e.kind = r.kind; e.public = r.public; e.summary = r.summary || ""; });
        save(); draw();
        ctx.toast("AI 整理了 " + res.entries.length + " 条，请再看一遍");
      } else if (t.closest("[data-condense]")) {
        const long = entries().map((e, i) => ({ i, name: e.name, content: e.content, e })).filter((x) => x.e.include && len(x.content) > 600);
        const res = await busy(t.closest("[data-condense]"), () => ctx.api.post("worlds/tavern/condense", { worldview: w.draft.worldview, limit: L.worldview_advised, entries: long.map(({ i, name, content }) => ({ i, name, content })) }));
        if (res.worldview) w.draft.worldview = res.worldview;
        res.entries.forEach((r) => { if (entries()[r.i]) entries()[r.i].content = r.text; });
        save(); draw();
        ctx.toast("压缩了世界观" + (res.entries.length ? "和 " + res.entries.length + " 条长条目" : ""));
      } else if (t.closest("[data-template]")) {
        w.template = t.closest("[data-template]").dataset.template;
        if (w.extras) { w.extras = null; ctx.toast("换了模板，AI 补全的职业需要重新生成"); }
        save(); draw();
      } else if (t.closest("[data-complete]")) {
        const res = await busy(t.closest("[data-complete]"), () => ctx.api.post("worlds/tavern/complete", { title: w.draft.title, worldview: w.draft.worldview,
          entries: included().map((e) => ({ name: e.name, kind: e.kind })), template: w.template, want_opening: w.wantOpening }));
        w.extras = res; save(); draw();
        ctx.toast("AI 补全了 " + res.archetypes.length + " 个职业" + (res.seed ? "和开场" : ""));
      } else if (t.closest("[data-clear-extras]")) {
        w.extras = null; save(); draw();
      } else if (t.closest("[data-drop-arch]")) {
        w.extras.archetypes.splice(Number(t.closest("[data-drop-arch]").dataset.dropArch), 1);
        if (!w.extras.archetypes.length) w.extras = null;
        save(); draw();
      } else if (t.closest("[data-open]")) {
        const b = w.built;
        sessionStorage.setItem(HANDOFF, JSON.stringify({ pack: b.pack, presentation: b.presentation, narration: b.narration, title: w.draft.title }));
        ctx.go("worlds/new?tavern=1");
      }
    } catch (error) { ctx.toast(error.message, "error"); }
  });
  root.addEventListener("change", async (e) => {
    const t = e.target, d = t.dataset;
    try {
      if (t.matches("[data-file]") && t.files[0]) {
        const file = t.files[0];
        setDraft(await ctx.api.post("worlds/tavern/parse", { data: await readFile(file), filename: file.name }));
      } else if (d.include !== undefined) {
        entries()[d.include].include = t.checked; t.closest(".trow").classList.toggle("off", !t.checked); save(); refreshSort();
      } else if (d.public !== undefined) {
        entries()[d.public].public = t.checked; save(); draw();
      } else if (d.kind !== undefined) {
        const e = entries()[d.kind]; e.kind = t.value; if (!ENTRY.includes(e.kind)) e.public = false; save(); draw();
      } else if (d.wantOpening !== undefined) {
        w.wantOpening = t.checked; save();
      }
    } catch (error) { ctx.toast(error.message, "error"); }
  });
  root.addEventListener("input", (e) => {
    const t = e.target, d = t.dataset;
    if (d.title !== undefined) w.draft.title = t.value;
    else if (d.worldview !== undefined) w.draft.worldview = t.value;
    else if (d.content !== undefined) { entries()[d.content].content = t.value; t.closest(".trow").querySelector(".trow-len").textContent = len(t.value); }
    else if (d.summary !== undefined) entries()[d.summary].summary = t.value;
    else if (d.x !== undefined) setPath(w.extras, d.x, t.value);
    else return;
    save();
    if (w.step === 1) refreshSort();
  });

  draw();
}

