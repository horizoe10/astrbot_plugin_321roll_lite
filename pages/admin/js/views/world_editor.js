// World editor: a seven-step flow over a draft {pack, presentation}.
// Inputs bind to draft paths (data-bind); structural edits are data-act buttons that re-render the step.
// Every change re-checks the draft, so the stepper always shows which step still has problems.
import { acts as actTrack, busy, cover, esc, shortTitle, subTitle } from "../ui.js";

const STEPS = [
  ["basics", "基本信息", "封面、标题、世界观与开场"],
  ["rules", "规则", "属性、资源、难度与人数"],
  ["kit", "技能与物品", "职业可选的技能、开局物品"],
  ["archetypes", "职业", "属性分配与技能"],
  ["entries", "设定条目", "地点、人物、线索与起点"],
  ["acts", "幕与结局", "故事节奏与结局条件"],
  ["review", "检查与保存", "校验、保存或导出"],
];
const KINDS = [["region", "地区"], ["place", "地点"], ["faction", "势力"], ["npc", "人物"], ["goal", "目标"], ["clue", "线索"]];
const DIFF = ["简单", "标准", "困难", "极难"];
const MODES = [["hybrid", "选项与自由行动"], ["choice_only", "只用选项"], ["dialogue_only", "只用自由行动"]];
const RESETS = [["scene", "每幕"], ["rest", "休整后"], ["never", "不恢复"]];
const TONES = [["ink", "墨蓝"], ["ember", "余烬"], ["neon", "霓紫"], ["jade", "青玉"], ["wine", "酒红"], ["slate", "石灰"]];
const ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,100}$/;
const LIMITS = { title: 100, worldview: 6000, seed: 3000, style: 300, boundaries: 1000, guidance: 2000 };
const clone = (v) => JSON.parse(JSON.stringify(v));
const isInt = (v) => Number.isInteger(v);
// Starting point for a world made from scratch: common rules and one placeholder archetype; the steps flag what is still empty.
const ATTRS = [["strength", "力量"], ["dexterity", "灵巧"], ["perception", "感知"], ["knowledge", "学识"], ["charisma", "魅力"]];
const BLANK = {
  pack: {
    format: "321roll.world-template/1", id: "my-world", revision: 1, title: "", worldview: "", seed: "", style: "", boundaries: "", guidance: "",
    attributes: ATTRS.map(([id, name]) => ({ id, name, min: 6, max: 16 })), budget: 55, modifier: { baseline: 10, divisor: 2 },
    resources: [{ id: "vitality", name: "体力", min: 0, max: 10, initial: 10 }],
    rules: { dcMin: 5, dcMax: 25, dc: 12, difficulties: [8, 12, 15, 18], seats: 16, minPlayers: 1, recommendedMin: 2, recommendedMax: 4, mode: "hybrid",
      expectedResults: true, skillSlots: 2, failureCost: 1, failureResource: "vitality", restCost: 0, restCostResource: "", restGain: 3, restGainResource: "vitality" },
    skills: [], items: [],
    archetypes: [{ id: "adventurer", name: "冒险者", text: "", attributes: Object.fromEntries(ATTRS.map(([id]) => [id, 11])), skills: [] }],
    entries: [], initial: { place: "", time: "", state: "", links: [] },
  },
  presentation: { acts: [], places: [], endings: [] },
  cover: { mark: "新", tone: "ink" },
  bundle_format: "321roll-lite.world-bundle/1",
};

export async function render(root, ctx, { id, from }) {
  const list = await ctx.api.get("worlds");
  const taken = new Set(list.worlds.map((w) => w.id));
  // No id and no from: a blank world.
  const blank = !id && !from;
  const source = blank ? clone(BLANK) : await ctx.api.get("world", { id: id || from });
  const isNew = !id;
  if (!isNew && source.source !== "custom") throw new Error("预设世界不能直接修改，请在详情页先“复制为自定义世界”。");

  let draft = { pack: clone(source.pack), presentation: clone(source.presentation || {}) };
  draft.presentation.acts = draft.presentation.acts || [];
  draft.presentation.endings = draft.presentation.endings || [];
  draft.presentation.places = draft.presentation.places || [];
  if (isNew) {
    const stem = blank ? "my-world" : (from + "-custom").slice(0, 90);
    let next = stem;
    for (let n = 2; taken.has(next); n++) next = stem + "-" + n;
    draft.pack.id = next;
    draft.pack.revision = 1;
    if (!blank) {
      const [main, ...rest] = draft.pack.title.split(" · ");
      draft.pack.title = [main + "（自定义）", ...rest].join(" · ");
    }
  }
  draft.presentation.cover = draft.presentation.cover || { ...source.cover };

  const key = "roll-lite-world-draft:" + (isNew ? "new:" + (from || "blank") : id);
  let saved = JSON.stringify(draft);
  let step = Math.max(0, STEPS.findIndex(([k]) => k === ctx.route.params.step));
  let serverCheck = null;
  let pendingDraft = null;
  try {
    const stored = JSON.parse(localStorage.getItem(key) || "null");
    if (stored && JSON.stringify(stored.draft) !== saved) pendingDraft = stored;
  } catch { /* storage unavailable */ }

  let persisted = !isNew;
  const dirty = () => JSON.stringify(draft) !== saved;
  ctx.guard((silent) => !dirty() || (!silent && window.confirm("世界包还有未保存的修改，离开后只保留在本机草稿里。确定离开吗？")));

  root.innerHTML = '<div class="ed-root"><a class="crumb" href="#/worlds' + (blank ? "/import" : "/" + encodeURIComponent(isNew ? from : id)) + '">← ' + (blank ? "返回新建世界" : isNew ? "返回原世界" : "返回世界详情") + "</a>" +
    '<header class="ed-head"><div data-live="cover-mini"></div><div class="ed-title"><div class="eyebrow">' + (blank ? "新建世界 · 从空白开始" : isNew ? "新建世界 · 复制自 " + esc(shortTitle(source.pack.title)) : "编辑世界 · 第 " + source.pack.revision + " 版") +
    '</div><h1 class="page-title" data-live="title"></h1><div class="ed-meta" data-live="meta"></div></div>' +
    '<div class="btns"><button class="btn" data-act="export">导出 JSON</button><button class="btn primary" data-act="save">' + (isNew ? "保存为新世界" : "保存修改") + "</button></div></header>" +
    '<div data-live="draft-notice"></div>' +
    '<div class="ed-layout"><nav class="stepper" data-live="stepper" aria-label="编辑步骤"></nav><section class="ed-main"><div data-step></div>' +
    '<div class="ed-foot" data-live="foot"></div></section></div></div>';
  // Listeners live on this view's own element: #page is shared and would keep handlers of earlier visits.
  root = root.firstElementChild;
  const stepEl = root.querySelector("[data-step]");

  // ------------------------------------------------------------ draft access
  const get = (path) => path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), draft);
  function set(path, value) {
    const keys = path.split(".");
    const last = keys.pop();
    keys.reduce((o, k) => o[k], draft)[last] = value;
  }
  const pack = () => draft.pack;

  // ------------------------------------------------------------ validation (mirrors catalog.validate_world)
  function issues() {
    const p = draft.pack, r = p.rules, out = Object.fromEntries(STEPS.map(([k]) => [k, []]));
    const add = (k, m) => out[k].push(m);
    const [main] = p.title.split(" · ");
    if (!main.trim()) add("basics", "主标题不能为空");
    for (const [field, limit] of Object.entries(LIMITS)) if ((p[field] || "").length > limit) add("basics", fieldName(field) + "超过 " + limit + " 字");
    if (!p.worldview.trim()) add("basics", "世界观不能为空");
    if (!p.seed.trim()) add("basics", "开场不能为空");
    if (!ID_RE.test(p.id)) add("basics", "编号只能用字母、数字和 - _ . :，并以字母或数字开头");
    else if (isNew && taken.has(p.id)) add("basics", "编号 " + p.id + " 已被占用");
    const cv = draft.presentation.cover || {};
    if (!cv.mark || cv.mark.trim().length < 1 || cv.mark.trim().length > 2) add("basics", "封面字需要 1–2 个字");

    if (p.attributes.length < 3 || p.attributes.length > 12) add("rules", "属性需要 3–12 项");
    p.attributes.forEach((a) => {
      if (!a.name.trim()) add("rules", "有属性没有名字");
      if (!isInt(a.min) || !isInt(a.max) || a.min > a.max || a.min < -100 || a.max > 100) add("rules", "属性「" + (a.name || a.id) + "」的范围无效");
    });
    const lo = p.attributes.reduce((s, a) => s + (a.min || 0), 0), hi = p.attributes.reduce((s, a) => s + (a.max || 0), 0);
    if (!isInt(p.budget) || p.budget < lo || p.budget > hi) add("rules", "点数预算要在 " + lo + "–" + hi + " 之间");
    if (p.resources.length < 1 || p.resources.length > 8) add("rules", "资源需要 1–8 种");
    p.resources.forEach((x) => {
      if (!x.name.trim()) add("rules", "有资源没有名字");
      if (!isInt(x.min) || !isInt(x.max) || !isInt(x.initial) || x.min < 0 || x.max < Math.max(1, x.min) || x.initial < x.min || x.initial > x.max)
        add("rules", "资源「" + (x.name || x.id) + "」的数值无效（初始值要在最小与最大之间）");
    });
    if (!isInt(r.dcMin) || !isInt(r.dcMax) || r.dcMin > r.dcMax) add("rules", "难度区间无效");
    if (!r.difficulties.every((d, i) => isInt(d) && d >= r.dcMin && d <= r.dcMax && (i === 0 || d > r.difficulties[i - 1]))) add("rules", "四档难度要逐档递增，并落在 " + r.dcMin + "–" + r.dcMax + " 之间");
    if (!isInt(r.dc) || r.dc < r.dcMin || r.dc > r.dcMax) add("rules", "默认难度要在难度区间内");
    if (!(isInt(r.minPlayers) && r.minPlayers >= 1 && r.minPlayers <= r.seats && r.recommendedMin >= 1 && r.recommendedMin <= r.recommendedMax && r.recommendedMax <= r.seats)) add("rules", "人数设置无效（最少 ≤ 推荐下限 ≤ 推荐上限 ≤ 席位）");
    if (!isInt(r.skillSlots) || r.skillSlots < 0 || r.skillSlots > 20) add("rules", "技能栏位要在 0–20 之间");
    for (const [cost, ref, label] of [["failureCost", "failureResource", "失败代价"], ["restCost", "restCostResource", "休整消耗"], ["restGain", "restGainResource", "休整恢复"]]) {
      if (!isInt(r[cost]) || r[cost] < 0) add("rules", label + "要是非负整数");
      else if (r[cost] > 0 && !p.resources.some((x) => x.id === r[ref])) add("rules", label + "需要选择一种资源");
    }

    for (const [kind, label] of [["skills", "技能"], ["items", "物品"]]) {
      p[kind].forEach((s) => {
        const name = s.name || s.id;
        if (!s.name.trim()) add("kit", "有" + label + "没有名字");
        if ((s.text || "").length > 2000) add("kit", label + "「" + name + "」的说明超过 2000 字");
        if (!isInt(s.modifier) || s.modifier < -20 || s.modifier > 20) add("kit", label + "「" + name + "」的加值要在 -20–20 之间");
        if (!isInt(s.uses) || s.uses < 0 || s.uses > 1000) add("kit", label + "「" + name + "」的次数无效");
        for (const [amount, ref] of [["cost", "costResource"], ["gain", "gainResource"]])
          if (!isInt(s[amount]) || s[amount] < 0 || (s[amount] > 0 && !p.resources.some((x) => x.id === s[ref]))) add("kit", label + "「" + name + "」的资源消耗或恢复需要选择资源");
        if (kind === "items" && (!isInt(s.initial) || !isInt(s.consume) || s.initial < 0 || s.consume < 0)) add("kit", "物品「" + name + "」的开局数量或消耗无效");
      });
    }

    if (!p.archetypes.length) add("archetypes", "至少需要一个职业");
    p.archetypes.forEach((a) => {
      const name = a.name || a.id;
      if (!a.name.trim()) add("archetypes", "有职业没有名字");
      const total = p.attributes.reduce((s, at) => s + (a.attributes[at.id] ?? 0), 0);
      if (p.attributes.some((at) => !isInt(a.attributes[at.id]) || a.attributes[at.id] < at.min || a.attributes[at.id] > at.max)) add("archetypes", "「" + name + "」有属性超出范围");
      if (total !== p.budget) add("archetypes", "「" + name + "」的属性合计 " + total + "，要等于预算 " + p.budget);
      if (a.skills.length > r.skillSlots) add("archetypes", "「" + name + "」的技能超过 " + r.skillSlots + " 个栏位");
    });

    p.entries.forEach((e) => {
      if (!e.name.trim()) add("entries", "有条目没有名字");
      if (e.summary.length > 4000 || e.secret.length > 4000) add("entries", "条目「" + (e.name || e.id) + "」的内容超过 4000 字");
    });
    if (!p.initial.place.trim()) add("entries", "开场地点不能为空");

    draft.presentation.acts.forEach((a, i) => { if (!a.title.trim()) add("acts", "第 " + (i + 1) + " 幕没有标题"); });
    draft.presentation.endings.forEach((e, i) => { if (!e.name.trim()) add("acts", "第 " + (i + 1) + " 个结局没有名字"); });
    out.review = Object.entries(out).filter(([k]) => k !== "review").flatMap(([, v]) => v);
    return out;
  }
  const fieldName = (f) => ({ title: "标题", worldview: "世界观", seed: "开场", style: "叙事风格", boundaries: "内容边界", guidance: "主持要点" })[f] || f;

  function summary(k) {
    const p = draft.pack, pr = draft.presentation;
    return {
      basics: (p.worldview.length + p.seed.length) + " 字",
      rules: p.attributes.length + " 属性 · " + p.resources.length + " 资源",
      kit: p.skills.length + " 技能 · " + p.items.length + " 物品",
      archetypes: p.archetypes.length + " 个职业",
      entries: p.entries.length + " 条 · " + p.entries.filter((e) => e.public).length + " 公开",
      acts: pr.acts.length + " 幕 · " + pr.endings.length + " 结局",
      review: dirty() ? "有未保存的修改" : persisted ? "已与保存版本一致" : "尚未保存",
    }[k];
  }

  // ------------------------------------------------------------ form helpers
  const opts = (list, value) => list.map(([v, l]) => '<option value="' + esc(v) + '"' + (v === value ? " selected" : "") + ">" + esc(l) + "</option>").join("");
  const resOpts = (value) => opts([["", "不选"], ...pack().resources.map((x) => [x.id, x.name || x.id])], value);
  const attrOpts = (value) => opts([["", "不加检定"], ...pack().attributes.map((x) => [x.id, x.name || x.id])], value);
  function text(path, label, { limit, area, rows = 4, hint = "", placeholder = "", rerender = false } = {}) {
    const value = get(path) ?? "";
    const counter = limit ? '<span class="count" data-live="count:' + path + ":" + limit + '"></span>' : "";
    const control = area
      ? '<textarea class="input" rows="' + rows + '" data-bind="' + path + '"' + (placeholder ? ' placeholder="' + esc(placeholder) + '"' : "") + ">" + esc(value) + "</textarea>"
      : '<input class="input" data-bind="' + path + '" value="' + esc(value) + '"' + (placeholder ? ' placeholder="' + esc(placeholder) + '"' : "") + (rerender ? " data-rerender" : "") + " />";
    return '<label class="field"><span class="label row between">' + esc(label) + counter + "</span>" + control + (hint ? '<span class="hint">' + esc(hint) + "</span>" : "") + "</label>";
  }
  const num = (path, label, attrs = "") => '<label class="field"><span class="label">' + esc(label) + '</span><input class="input num" type="number" data-type="int" data-bind="' + path + '" value="' + esc(get(path) ?? "") + '" ' + attrs + " /></label>";
  const select = (path, label, options) => '<label class="field"><span class="label">' + esc(label) + '</span><select class="select" data-bind="' + path + '" data-rerender>' + options + "</select></label>";
  const toggle = (path, label) => '<label class="row" style="gap:10px"><span class="switch"><input type="checkbox" data-type="bool" data-bind="' + path + '"' + (get(path) ? " checked" : "") + ' /><span></span></span><span class="label" style="margin:0">' + esc(label) + "</span></label>";
  const del = (act, i, label = "删除") => '<button class="btn text small danger" data-act="' + act + '" data-i="' + i + '" type="button">' + label + "</button>";
  const sectionHead = (title, sub, actions = "") => '<div class="ed-sec"><div><h3>' + esc(title) + "</h3>" + (sub ? '<p class="hint">' + esc(sub) + "</p>" : "") + "</div>" + actions + "</div>";
  const newId = (prefix, rows) => { let n = rows.length + 1; while (rows.some((r) => r.id === prefix + "-" + n)) n++; return prefix + "-" + n; };

  // ------------------------------------------------------------ steps
  const STEP_VIEWS = {
    basics() {
      const [main, ...rest] = pack().title.split(" · ");
      return sectionHead("封面与标题", "封面不用图片：选一种配色，写一两个字。群里和后台都按这个标题显示。") +
        '<div class="ed-cover"><div data-live="cover-poster"></div><div>' +
        '<label class="field"><span class="label">封面字</span><input class="input" maxlength="2" data-bind="presentation.cover.mark" value="' + esc(draft.presentation.cover.mark) + '" style="width:96px;font:600 22px var(--serif);text-align:center" /></label>' +
        '<div class="label">配色</div><div class="swatches">' + TONES.map(([t, l]) => '<button type="button" class="swatch tone-' + t + '" data-act="tone" data-v="' + t + '" aria-pressed="' + (draft.presentation.cover.tone === t) + '" title="' + l + '"><span>' + l + "</span></button>").join("") + "</div></div></div>" +
        '<div class="grid cols-even" style="gap:0 20px;margin-top:18px">' +
        '<label class="field"><span class="label">主标题</span><input class="input" data-bind="title.main" value="' + esc(main) + '" /></label>' +
        '<label class="field"><span class="label">副标题</span><input class="input" data-bind="title.sub" value="' + esc(rest.join(" · ")) + '" placeholder="一句话钩子，可不填" /></label></div>' +
        '<label class="field"><span class="label">编号（id）</span><input class="input num" data-bind="pack.id" value="' + esc(pack().id) + '"' + (isNew ? "" : " readonly") + " /><span class=\"hint\">" +
        (isNew ? "用于区分世界包，保存后不能修改。只能用字母、数字和 - _ . :" : "已保存的世界不能改编号；想换编号，请导出后改成新世界导入。") + "</span></label>" +
        '<hr class="rule" />' + sectionHead("世界与开场", "世界观和开场会交给叙事模型；开场是第一幕的起点描写。") +
        text("pack.worldview", "世界观", { limit: LIMITS.worldview, area: true, rows: 9 }) +
        text("pack.seed", "开场", { limit: LIMITS.seed, area: true, rows: 5, hint: "开团时会作为开团卡的引子发到群里。" }) +
        text("pack.style", "叙事风格", { limit: LIMITS.style, area: true, rows: 2 }) +
        '<details class="ed-more"><summary>主持要点与内容边界（不公开）</summary><div style="margin-top:14px">' +
        text("pack.guidance", "主持要点", { limit: LIMITS.guidance, area: true, rows: 5, hint: "真相、伏笔等只给模型看的内容。" }) +
        text("pack.boundaries", "内容边界", { limit: LIMITS.boundaries, area: true, rows: 3 }) + "</div></details>";
    },

    rules() {
      const p = pack(), r = p.rules;
      return sectionHead("属性", "每个职业都按这些属性分配点数。检定时加值 =（属性 − 基准）÷ 除数。", '<button class="btn small" data-act="add-attr" type="button">添加属性</button>') +
        '<div class="ed-rows">' + p.attributes.map((a, i) => '<div class="ed-row attr"><input class="input" data-bind="pack.attributes.' + i + '.name" value="' + esc(a.name) + '" placeholder="名称" />' +
          '<input class="input num" type="number" data-type="int" data-bind="pack.attributes.' + i + '.min" value="' + a.min + '" title="最小" />' +
          '<span class="faint">—</span><input class="input num" type="number" data-type="int" data-bind="pack.attributes.' + i + '.max" value="' + a.max + '" title="最大" />' +
          '<div data-live="range:' + i + '"></div>' + (p.attributes.length > 3 ? del("del-attr", i) : '<span></span>') + "</div>").join("") + "</div>" +
        '<div class="row wrap" style="gap:20px;margin-top:14px"><div style="width:180px">' + num("pack.budget", "点数预算") + '</div><div class="hint" data-live="budget-range"></div></div>' +
        '<hr class="rule" />' + sectionHead("资源", "体力、理智这类会被消耗和恢复的数值。", p.resources.length < 8 ? '<button class="btn small" data-act="add-res" type="button">添加资源</button>' : "") +
        '<div class="ed-rows">' + p.resources.map((x, i) => '<div class="ed-row res"><input class="input" data-bind="pack.resources.' + i + '.name" value="' + esc(x.name) + '" placeholder="名称" />' +
          ["min", "max", "initial"].map((f) => '<label class="ed-mini"><span>' + { min: "最小", max: "最大", initial: "初始" }[f] + '</span><input class="input num" type="number" data-type="int" data-bind="pack.resources.' + i + "." + f + '" value="' + x[f] + '" /></label>').join("") +
          '<div data-live="res:' + i + '"></div>' + (p.resources.length > 1 ? del("del-res", i) : "<span></span>") + "</div>").join("") + "</div>" +
        '<hr class="rule" />' + sectionHead("难度", "四档难度对应群里的 简单 / 标准 / 困难 / 极难。刻度上的百分比是属性加值为 0 时 d20 的成功率。") +
        '<div class="grid cols-even" style="grid-template-columns:repeat(5,1fr);gap:0 12px">' + DIFF.map((d, i) => num("pack.rules.difficulties." + i, d)).join("") + num("pack.rules.dc", "默认难度") + "</div>" +
        '<div data-live="scale"></div>' +
        '<hr class="rule" />' + sectionHead("人数与玩法", "Lite 的团桌最多 8 人，推荐人数会显示在 /团 世界 列表里。") +
        '<div class="grid cols-3" style="gap:0 16px">' + num("pack.rules.minPlayers", "最少人数", 'min="1"') + num("pack.rules.recommendedMin", "推荐下限", 'min="1"') + num("pack.rules.recommendedMax", "推荐上限", 'min="1"') + "</div>" +
        '<div data-live="players"></div>' +
        '<div class="grid cols-even" style="gap:0 16px;margin-top:14px">' + select("pack.rules.mode", "行动方式", opts(MODES, r.mode)) + num("pack.rules.skillSlots", "每个职业的技能栏位", 'min="0" max="20"') + "</div>" +
        '<hr class="rule" />' + sectionHead("代价与休整", "检定失败时扣的资源，以及“/团 休整”的消耗和恢复。") +
        '<div class="grid cols-3" style="gap:0 16px">' +
        '<div class="ed-pair">' + num("pack.rules.failureCost", "失败扣除") + select("pack.rules.failureResource", "扣哪种资源", resOpts(r.failureResource)) + "</div>" +
        '<div class="ed-pair">' + num("pack.rules.restGain", "休整恢复") + select("pack.rules.restGainResource", "恢复哪种资源", resOpts(r.restGainResource)) + "</div>" +
        '<div class="ed-pair">' + num("pack.rules.restCost", "休整消耗") + select("pack.rules.restCostResource", "消耗哪种资源", resOpts(r.restCostResource)) + "</div></div>" +
        '<details class="ed-more"><summary>高级：难度区间、席位、加值换算</summary><div class="grid cols-3" style="gap:0 16px;margin-top:14px">' +
        num("pack.rules.dcMin", "难度下限") + num("pack.rules.dcMax", "难度上限") + num("pack.rules.seats", "世界席位上限", 'min="1" max="16"') +
        num("pack.modifier.baseline", "加值基准") + num("pack.modifier.divisor", "加值除数", 'min="1"') +
        '<div style="padding-top:26px">' + toggle("pack.rules.expectedResults", "模型给出预期结果") + "</div></div></details>";
    },

    kit() {
      const p = pack();
      const users = (sid) => p.archetypes.filter((a) => a.skills.includes(sid)).map((a) => a.name);
      const card = (kind, s, i) => {
        const base = "pack." + kind + "." + i + ".";
        return '<div class="ed-card"><div class="ed-card-head"><input class="input strong" data-bind="' + base + 'name" value="' + esc(s.name) + '" placeholder="名称" />' + del("del-" + kind, i) + "</div>" +
          '<input class="input" data-bind="' + base + 'text" value="' + esc(s.text) + '" placeholder="一句话说明效果" />' +
          '<div class="ed-grid4">' + select(base + "attribute", "检定属性", attrOpts(s.attribute)) + num(base + "modifier", "加值", 'min="-20" max="20"') + num(base + "uses", "次数", 'min="0" title="0 为不限次数"') + select(base + "reset", "恢复时机", opts(RESETS, s.reset)) + "</div>" +
          '<div class="ed-grid4">' + num(base + "cost", "消耗") + select(base + "costResource", "消耗资源", resOpts(s.costResource)) + num(base + "gain", "恢复") + select(base + "gainResource", "恢复资源", resOpts(s.gainResource)) + "</div>" +
          (kind === "items" ? '<div class="ed-grid4">' + num(base + "initial", "开局数量", 'min="0"') + num(base + "consume", "每次用掉", 'min="0"') + "</div>"
            : '<div class="chips">' + (users(s.id).length ? users(s.id).map((n) => '<span class="tag gold">' + esc(n) + "</span>").join("") : '<span class="hint">还没有职业选用</span>') + "</div>") + "</div>";
      };
      return sectionHead("技能", "职业从这里挑选技能（在“职业”一步勾选）。", '<button class="btn small" data-act="add-skills" type="button">添加技能</button>') +
        '<div class="ed-cards">' + (p.skills.map((s, i) => card("skills", s, i)).join("") || '<p class="hint">还没有技能。</p>') + "</div>" +
        '<hr class="rule" />' + sectionHead("开局物品", "每位角色开局都会带上这些物品。", '<button class="btn small" data-act="add-items" type="button">添加物品</button>') +
        '<div class="ed-cards">' + (p.items.map((s, i) => card("items", s, i)).join("") || '<p class="hint">还没有物品。</p>') + "</div>";
    },

    archetypes() {
      const p = pack();
      return sectionHead("职业一览", "每格的深浅表示属性高低，一眼对比各职业的侧重。", '<button class="btn small" data-act="add-arch" type="button">添加职业</button>') +
        '<div data-live="matrix"></div><hr class="rule" />' +
        p.archetypes.map((a, i) => {
          const base = "pack.archetypes." + i + ".";
          return '<div class="ed-arch"><div class="ed-card-head"><input class="input strong" data-bind="' + base + 'name" value="' + esc(a.name) + '" placeholder="职业名" />' +
            '<button class="btn text small" data-act="dup-arch" data-i="' + i + '" type="button">复制</button>' + (p.archetypes.length > 1 ? del("del-arch", i) : "") + "</div>" +
            '<input class="input" data-bind="' + base + 'text" value="' + esc(a.text || "") + '" placeholder="定位，例如：取证与追问（专精型）" />' +
            '<div class="row between" style="margin:14px 0 8px"><span class="label">属性分配</span><span class="row" style="gap:10px"><span data-live="alloc:' + i + '"></span>' +
            '<button class="btn text small" data-act="fit-arch" data-i="' + i + '" type="button">补齐到预算</button></span></div>' +
            '<div class="ed-alloc">' + p.attributes.map((at) => '<label class="ed-alloc-row"><span>' + esc(at.name || at.id) + '</span><input type="range" min="' + at.min + '" max="' + at.max + '" step="1" data-type="int" data-bind="' + base + "attributes." + at.id + '" value="' + (a.attributes[at.id] ?? at.min) + '" />' +
              '<input class="input num" type="number" data-type="int" data-bind="' + base + "attributes." + at.id + '" value="' + (a.attributes[at.id] ?? at.min) + '" /></label>').join("") + "</div>" +
            '<div class="row between" style="margin:14px 0 8px"><span class="label">技能（最多 ' + p.rules.skillSlots + ' 个）</span><span class="hint" data-live="slots:' + i + '"></span></div>' +
            '<div class="chips">' + (p.skills.map((s) => '<button type="button" class="chip' + (a.skills.includes(s.id) ? " on" : "") + '" data-act="arch-skill" data-i="' + i + '" data-v="' + esc(s.id) + '">' + esc(s.name || s.id) + "</button>").join("") || '<span class="hint">先在“技能与物品”里添加技能</span>') + "</div></div>";
        }).join("");
    },

    entries() {
      const p = pack(), ini = p.initial;
      const publicEntries = p.entries.filter((e) => e.public);
      return sectionHead("开场起点", "故事开始的地点、时间和局面；勾选的公开条目会作为开场线索。") +
        '<div class="grid cols-even" style="gap:0 16px">' + text("pack.initial.place", "地点") + text("pack.initial.time", "时间", { placeholder: "可不填" }) + "</div>" +
        text("pack.initial.state", "局面", { area: true, rows: 2, limit: 2000 }) +
        '<div class="label" style="margin-bottom:8px">开场关联的条目</div><div class="chips">' + (publicEntries.map((e) => '<button type="button" class="chip' + (ini.links.includes(e.id) ? " on" : "") + '" data-act="init-link" data-v="' + esc(e.id) + '">' + esc(e.name || e.id) + "</button>").join("") || '<span class="hint">还没有公开条目</span>') + "</div>" +
        '<hr class="rule" />' + sectionHead("设定条目", "公开条目玩家可以在 /团 世界观 里读到；隐藏设定只交给模型，不会发到群里。", '<button class="btn small" data-act="add-entry" type="button">添加条目</button>') +
        '<div class="ed-kinds" data-live="kinds"></div>' +
        p.entries.map((e, i) => {
          const base = "pack.entries." + i + ".";
          return '<div class="ed-card"><div class="ed-card-head"><select class="select" style="width:96px" data-bind="' + base + 'kind" data-rerender>' + opts(KINDS, e.kind) + "</select>" +
            '<input class="input strong" data-bind="' + base + 'name" value="' + esc(e.name) + '" placeholder="名称" />' + toggle(base + "public", "公开") + del("del-entry", i) + "</div>" +
            '<span class="mini-label">公开描述</span><textarea class="input" rows="2" data-bind="' + base + 'summary" placeholder="玩家可以读到的内容">' + esc(e.summary) + "</textarea>" +
            '<span class="mini-label">隐藏设定 · 只给模型</span><textarea class="input secret" rows="2" data-bind="' + base + 'secret" placeholder="真相、机关、伏笔，可不填">' + esc(e.secret) + "</textarea>" +
            '<div class="chips"><span class="hint">关联：</span>' + p.entries.filter((o) => o.id !== e.id).map((o) => '<button type="button" class="chip small' + (e.links.includes(o.id) ? " on" : "") + '" data-act="entry-link" data-i="' + i + '" data-v="' + esc(o.id) + '">' + esc(o.name || o.id) + "</button>").join("") + "</div></div>";
        }).join("");
    },

    acts() {
      const pr = draft.presentation;
      return sectionHead("幕", "幕是故事的大段落，团桌页会按幕显示进度，主持人可以用 /团 主持 换幕 推进。", '<button class="btn small" data-act="add-act" type="button">添加一幕</button>') +
        '<div class="panel soft" style="margin-bottom:16px" data-live="act-track"></div>' +
        pr.acts.map((a, i) => '<div class="ed-act"><span class="opt-num">' + (i + 1) + '</span><div class="ed-act-body"><input class="input strong" data-bind="presentation.acts.' + i + '.title" value="' + esc(a.title) + '" placeholder="幕名" />' +
          '<input class="input" data-bind="presentation.acts.' + i + '.lead" value="' + esc(a.lead || "") + '" placeholder="引子：进入这一幕时的一句话" /></div><div class="ed-act-tools">' +
          '<button class="btn text small" type="button" data-act="move-act" data-i="' + i + '" data-v="-1"' + (i ? "" : " disabled") + ">上移</button>" +
          '<button class="btn text small" type="button" data-act="move-act" data-i="' + i + '" data-v="1"' + (i < pr.acts.length - 1 ? "" : " disabled") + ">下移</button>" + del("del-act", i) + "</div></div>").join("") +
        '<hr class="rule" />' + sectionHead("结局", "列出可能的结局和达成条件；模型会参考它们，玩家用 /团 结局 查看。", '<button class="btn small" data-act="add-ending" type="button">添加结局</button>') +
        pr.endings.map((e, i) => '<div class="ed-act"><span class="opt-num">' + String.fromCharCode(65 + (i % 26)) + '</span><div class="ed-act-body"><input class="input strong" data-bind="presentation.endings.' + i + '.name" value="' + esc(e.name) + '" placeholder="结局名" />' +
          '<input class="input" data-bind="presentation.endings.' + i + '.rule" value="' + esc(e.rule || "") + '" placeholder="达成条件" /></div><div class="ed-act-tools">' + del("del-ending", i) + "</div></div>").join("");
    },

    review() {
      const all = issues();
      const p = pack(), pr = draft.presentation;
      return '<div class="ed-review"><div>' + cover(draft.presentation.cover, "poster", p.title) + '<div class="chips" style="margin-top:14px"><span class="tag">' + p.rules.recommendedMin + "–" + p.rules.recommendedMax + ' 人</span><span class="tag">' +
        pr.acts.length + ' 幕</span><span class="tag">' + p.archetypes.length + ' 职业</span><span class="tag">' + pr.endings.length + " 结局</span></div>" +
        '<p class="muted serif" style="margin:14px 0 0;line-height:1.8">' + esc(p.seed.slice(0, 180)) + (p.seed.length > 180 ? "…" : "") + "</p></div>" +
        "<div>" + sectionHead("检查清单", "每一步的问题都要先解决，才能保存。") + '<div class="ed-checklist">' + STEPS.slice(0, -1).map(([k, label], i) => {
          const list = all[k];
          return '<button type="button" class="ed-check" data-act="goto" data-i="' + i + '"><span class="dot ' + (list.length ? "warn" : "ok") + '"></span><b>' + label + "</b><span>" +
            (list.length ? esc(list[0]) + (list.length > 1 ? " 等 " + list.length + " 项" : "") : esc(summary(k))) + "</span></button>";
        }).join("") + "</div>" +
        '<div class="row" style="margin-top:18px;gap:10px"><button class="btn" data-act="check" type="button">用世界引擎校验</button><span class="hint">会实际编译一次规则，结果与保存时一致。</span></div>' +
        '<div data-live="server" style="margin-top:14px"></div>' +
        '<hr class="rule" /><div class="btns"><button class="btn primary" data-act="save" type="button">' + (isNew ? "保存为新世界" : "保存修改") + '</button><button class="btn" data-act="export" type="button">导出 JSON</button></div>' +
        '<p class="hint">导出的文件可以在“导入世界”里原样导回，也可以分享给其他 Lite 管理员。保存后世界默认启用，已经开着的团桌不受影响。</p></div></div>';
    },
  };

  // ------------------------------------------------------------ live widgets
  const LIVE = {
    "cover-mini": () => cover(draft.presentation.cover, "tile"),
    "cover-poster": () => cover(draft.presentation.cover, "poster", pack().title),
    title: () => esc(shortTitle(pack().title) || "未命名世界"),
    meta: () => '<span class="num">' + esc(pack().id) + "</span><span>第 " + pack().revision + " 版" + (isNew ? "（新建）" : "") + "</span>" +
      (dirty() ? '<span class="gold">● 有未保存的修改</span>' : persisted ? "<span>已保存</span>" : '<span class="gold">● 尚未保存</span>') +
      (subTitle(pack().title) ? "<span>" + esc(subTitle(pack().title)) + "</span>" : ""),
    issues: () => {
      if (STEPS[step][0] === "review") return "";
      const list = issues()[STEPS[step][0]];
      return list.length ? '<div class="notice err ed-issues"><b>这一步还有 ' + list.length + " 个问题</b><ul>" + list.slice(0, 6).map((m) => "<li>" + esc(m) + "</li>").join("") +
        (list.length > 6 ? "<li>……</li>" : "") + "</ul></div>" : "";
    },
    stepper: () => {
      const all = issues();
      return STEPS.map(([k, label], i) => {
        const n = k === "review" ? 0 : all[k].length;
        const state = i === step ? "now" : n ? "warn" : "ok";
        return '<button type="button" class="step ' + state + '" data-act="goto" data-i="' + i + '"' + (i === step ? ' aria-current="step"' : "") + '><span class="step-no">' + (n ? "!" : i + 1) + '</span><span class="step-text"><b>' + label +
          "</b><small>" + (n ? n + " 个问题" : esc(summary(k))) + "</small></span></button>";
      }).join("");
    },
    foot: () => '<button class="btn" type="button" data-act="goto" data-i="' + (step - 1) + '"' + (step ? "" : " disabled") + '>上一步</button><span class="hint">第 ' + (step + 1) + " / " + STEPS.length + " 步 · " + STEPS[step][2] + "</span>" +
      (step < STEPS.length - 1 ? '<button class="btn primary" type="button" data-act="goto" data-i="' + (step + 1) + '">下一步：' + STEPS[step + 1][1] + "</button>" : "<span></span>"),
    "draft-notice": () => pendingDraft ? '<div class="notice row between" style="margin-bottom:18px"><span>本机还有一份 ' + esc(new Date(pendingDraft.at).toLocaleString("zh-CN")) + " 的未保存草稿。</span><span class=\"btns\"><button class=\"btn small\" data-act=\"restore\">恢复草稿</button><button class=\"btn text small\" data-act=\"discard\">丢弃</button></span></div>" : "",
    "budget-range": () => {
      const p = pack(), lo = p.attributes.reduce((s, a) => s + (a.min || 0), 0), hi = p.attributes.reduce((s, a) => s + (a.max || 0), 0);
      return "允许 " + lo + "–" + hi + "；每个职业的属性合计都要等于预算，平均每项 " + (p.attributes.length ? (p.budget / p.attributes.length).toFixed(1) : "—");
    },
    scale: () => {
      const r = pack().rules, span = Math.max(1, r.dcMax - r.dcMin);
      const pos = (v) => Math.max(0, Math.min(100, ((v - r.dcMin) / span) * 100));
      const chance = (dc) => Math.max(5, Math.min(100, (21 - dc) * 5));
      return '<div class="dc-scale"><div class="dc-line"></div>' + r.difficulties.map((d, i) => '<div class="dc-mark" style="left:' + pos(d) + '%"><i></i><b>' + DIFF[i] + " " + d + "</b><span>" + chance(d) + "%</span></div>").join("") +
        '<div class="dc-mark default" style="left:' + pos(r.dc) + '%"><i></i><b>默认</b></div><span class="dc-end" style="left:0">' + r.dcMin + '</span><span class="dc-end" style="left:100%">' + r.dcMax + "</span></div>";
    },
    players: () => {
      const r = pack().rules;
      return '<div class="seat-scale">' + Array.from({ length: 8 }, (_, i) => {
        const n = i + 1, cls = n < r.minPlayers ? "" : n <= r.recommendedMax && n >= r.recommendedMin ? "rec" : n <= r.recommendedMax || n >= r.minPlayers && n < r.recommendedMin ? "ok" : "";
        return '<span class="' + cls + '"><i></i>' + n + "</span>";
      }).join("") + '<span class="hint">实心为推荐人数，空心为可开但不推荐</span></div>';
    },
    matrix: () => {
      const p = pack();
      if (!p.archetypes.length) return "";
      return '<div class="matrix" style="grid-template-columns:120px repeat(' + p.attributes.length + ',1fr) 64px"><span></span>' + p.attributes.map((a) => "<b>" + esc(a.name || a.id) + "</b>").join("") + "<b>合计</b>" +
        p.archetypes.map((a) => {
          const total = p.attributes.reduce((s, at) => s + (a.attributes[at.id] ?? 0), 0);
          return '<span class="m-name">' + esc(a.name || a.id) + "</span>" + p.attributes.map((at) => {
            const v = a.attributes[at.id] ?? at.min, share = at.max > at.min ? (v - at.min) / (at.max - at.min) : 0;
            return '<span class="m-cell" style="--s:' + share.toFixed(2) + '">' + v + "</span>";
          }).join("") + '<span class="m-total ' + (total === p.budget ? "" : "bad") + '">' + total + "</span>";
        }).join("") + "</div>";
    },
    kinds: () => '<div class="chips">' + KINDS.map(([k, l]) => {
      const n = pack().entries.filter((e) => e.kind === k).length;
      return '<span class="tag' + (n ? " gold" : "") + '">' + l + " " + n + "</span>";
    }).join("") + "</div>",
    "act-track": () => draft.presentation.acts.length ? actTrack(draft.presentation.acts.map((a, i) => ({ number: i + 1, title: a.title || "未命名" })), 1) : '<span class="hint">还没有幕。没有幕时团桌不显示幕进度。</span>',
    server: () => {
      if (!serverCheck) return "";
      if (serverCheck.error) return '<div class="notice err">' + esc(serverCheck.error) + "</div>";
      const s = serverCheck.summary;
      return '<div class="notice"><span class="dot ok">世界引擎校验通过</span><div class="hint" style="margin-top:6px">' + esc(s.title) + " · " + s.attributes + " 属性 · " + s.archetypes + " 职业 · " + s.entries + " 条目 · " +
        s.acts + " 幕 · " + s.endings + " 结局" + (serverCheck.existing && isNew ? "　注意：编号已被占用" : "") + "</div></div>";
    },
  };
  function liveFor(name) {
    if (LIVE[name]) return LIVE[name]();
    const [kind, a, b] = name.split(":");
    const p = pack();
    if (kind === "count") { const len = String(get(a) || "").length; return '<span class="' + (len > Number(b) ? "over" : "") + '">' + len + " / " + b + "</span>"; }
    if (kind === "range") {
      const at = p.attributes[a];
      if (!at) return "";
      const lo = -2, hi = 22, pos = (v) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
      return '<div class="range-bar"><i style="left:' + pos(at.min) + "%;right:" + (100 - pos(at.max)) + '%"></i></div>';
    }
    if (kind === "res") {
      const x = p.resources[a];
      if (!x) return "";
      const share = x.max ? Math.max(0, Math.min(1, x.initial / x.max)) : 0;
      return '<div class="meter"><span>开局</span><div class="bar"><span style="width:' + (share * 100).toFixed(0) + '%"></span></div><span class="num">' + x.initial + "/" + x.max + "</span></div>";
    }
    if (kind === "alloc") {
      const arch = p.archetypes[a];
      if (!arch) return "";
      const total = p.attributes.reduce((s, at) => s + (arch.attributes[at.id] ?? 0), 0), diff = p.budget - total;
      return '<span class="alloc ' + (diff ? "bad" : "good") + '">' + total + " / " + p.budget + (diff ? (diff > 0 ? "　还差 " + diff : "　超出 " + -diff) : "　刚好") + "</span>";
    }
    if (kind === "slots") { const arch = p.archetypes[a]; return arch ? arch.skills.length + " / " + p.rules.skillSlots : ""; }
    return "";
  }
  function updateLive() {
    root.querySelectorAll("[data-live]").forEach((el) => {
      const html = liveFor(el.dataset.live);
      if (el.innerHTML !== html) el.innerHTML = html;
    });
  }

  function renderStep() {
    stepEl.innerHTML = '<div class="panel ed-panel"><div class="ed-step-head"><span class="eyebrow">第 ' + (step + 1) + " 步</span><h2>" + STEPS[step][1] + "</h2><p class=\"hint\">" + STEPS[step][2] + "</p></div>" +
      '<div data-live="issues"></div>' + STEP_VIEWS[STEPS[step][0]]() + "</div>";
    stepEl.querySelectorAll('input[type="range"]').forEach(fillRange);
    updateLive();
    const url = "#/worlds/" + (isNew ? "new?" + (from ? "from=" + encodeURIComponent(from) + "&" : "") : encodeURIComponent(id) + "/edit?") + "step=" + STEPS[step][0];
    history.replaceState(null, "", url);
  }

  let storeTimer = null;
  function changed() {
    updateLive();
    clearTimeout(storeTimer);
    storeTimer = setTimeout(() => {
      try {
        if (dirty()) localStorage.setItem(key, JSON.stringify({ at: Date.now(), draft }));
        else localStorage.removeItem(key);
      } catch { /* storage unavailable */ }
    }, 400);
  }

  // ------------------------------------------------------------ input binding
  function write(el) {
    const path = el.dataset.bind;
    let value = el.dataset.type === "bool" ? el.checked : el.value;
    if (el.dataset.type === "int") value = value === "" ? null : Number.parseInt(value, 10);
    if (path === "title.main" || path === "title.sub") {
      const [main, ...rest] = pack().title.split(" · ");
      const parts = path === "title.main" ? [value, rest.join(" · ")] : [main, value];
      pack().title = parts.filter((x, i) => i === 0 || String(x).trim()).join(" · ");
      return;
    }
    set(path, value);
    // keep a range and its number box in step
    root.querySelectorAll('[data-bind="' + path + '"]').forEach((other) => {
      if (other !== el && other.type !== "checkbox") other.value = value ?? "";
      if (other.type === "range") fillRange(other);
    });
  }
  function fillRange(el) {
    const min = Number(el.min), max = Number(el.max), v = Number(el.value);
    el.style.setProperty("--fill", (max > min ? ((v - min) / (max - min)) * 100 : 0) + "%");
  }
  root.addEventListener("input", (e) => {
    const el = e.target.closest("[data-bind]");
    if (!el || el.tagName === "SELECT") return;
    write(el);
    changed();
  });
  root.addEventListener("change", (e) => {
    const el = e.target.closest("[data-bind]");
    if (!el) return;
    write(el);
    changed();
    if (el.hasAttribute("data-rerender") || el.type === "checkbox") renderStep();
  });

  // ------------------------------------------------------------ structural actions
  const ACTIONS = {
    goto: (i) => { step = Math.max(0, Math.min(STEPS.length - 1, i)); renderStep(); window.scrollTo({ top: 0, behavior: "smooth" }); },
    tone: (_, v) => { draft.presentation.cover.tone = v; },
    "add-attr": () => {
      const p = pack(), ref = p.attributes[0] || { min: 6, max: 16 };
      const at = { id: newId("attr", p.attributes), name: "", min: ref.min, max: ref.max };
      p.attributes.push(at);
      p.archetypes.forEach((a) => { a.attributes[at.id] = at.min; });
      p.budget += at.min;
    },
    "del-attr": (i) => {
      const p = pack(), [at] = p.attributes.splice(i, 1);
      p.archetypes.forEach((a) => { delete a.attributes[at.id]; });
      for (const s of [...p.skills, ...p.items]) if (s.attribute === at.id) s.attribute = "";
    },
    "add-res": () => { pack().resources.push({ id: newId("res", pack().resources), name: "", min: 0, max: 5, initial: 5 }); },
    "del-res": (i) => {
      const p = pack(), [x] = p.resources.splice(i, 1), r = p.rules;
      for (const [cost, ref] of [["failureCost", "failureResource"], ["restCost", "restCostResource"], ["restGain", "restGainResource"]]) if (r[ref] === x.id) { r[ref] = ""; r[cost] = 0; }
      for (const s of [...p.skills, ...p.items]) for (const [amount, ref] of [["cost", "costResource"], ["gain", "gainResource"]]) if (s[ref] === x.id) { s[ref] = ""; s[amount] = 0; }
    },
    "add-skills": () => { pack().skills.push({ id: newId("skill", pack().skills), name: "", text: "", attribute: "", modifier: 2, cost: 0, costResource: "", gain: 0, gainResource: "", uses: 1, reset: "scene" }); },
    "del-skills": (i) => { const [s] = pack().skills.splice(i, 1); pack().archetypes.forEach((a) => { a.skills = a.skills.filter((x) => x !== s.id); }); },
    "add-items": () => { pack().items.push({ id: newId("item", pack().items), name: "", text: "", attribute: "", modifier: 0, cost: 0, costResource: "", gain: 0, gainResource: "", uses: 0, reset: "never", initial: 1, consume: 0 }); },
    "del-items": (i) => { pack().items.splice(i, 1); },
    "add-arch": () => {
      const p = pack(), a = { id: newId("archetype", p.archetypes), name: "", text: "", attributes: {}, skills: [] };
      p.attributes.forEach((at) => { a.attributes[at.id] = at.min; });
      fit(a);
      p.archetypes.push(a);
    },
    "dup-arch": (i) => { const p = pack(), a = clone(p.archetypes[i]); a.id = newId("archetype", p.archetypes); a.name = (a.name || "职业") + "（副本）"; p.archetypes.splice(i + 1, 0, a); },
    "del-arch": (i) => { pack().archetypes.splice(i, 1); },
    "fit-arch": (i) => { fit(pack().archetypes[i]); },
    "arch-skill": (i, v) => {
      const a = pack().archetypes[i];
      if (a.skills.includes(v)) a.skills = a.skills.filter((x) => x !== v);
      else if (a.skills.length < pack().rules.skillSlots) a.skills.push(v);
      else ctx.toast("技能栏位已满，先取消一个", "error");
    },
    "add-entry": () => { pack().entries.push({ id: newId("entry", pack().entries), name: "", kind: "place", public: true, summary: "", secret: "", links: [] }); },
    "del-entry": (i) => {
      const p = pack(), [e] = p.entries.splice(i, 1);
      p.entries.forEach((o) => { o.links = o.links.filter((x) => x !== e.id); });
      p.initial.links = p.initial.links.filter((x) => x !== e.id);
    },
    "entry-link": (i, v) => { const e = pack().entries[i]; e.links = e.links.includes(v) ? e.links.filter((x) => x !== v) : [...e.links, v]; },
    "init-link": (_, v) => { const ini = pack().initial; ini.links = ini.links.includes(v) ? ini.links.filter((x) => x !== v) : [...ini.links, v]; },
    "add-act": () => { draft.presentation.acts.push({ number: draft.presentation.acts.length + 1, title: "", lead: "" }); },
    "del-act": (i) => { draft.presentation.acts.splice(i, 1); },
    "move-act": (i, v) => { const list = draft.presentation.acts, j = i + Number(v); [list[i], list[j]] = [list[j], list[i]]; },
    "add-ending": () => { const list = draft.presentation.endings; list.push({ id: "ending-" + (list.length + 1), name: "", rule: "" }); },
    "del-ending": (i) => { draft.presentation.endings.splice(i, 1); },
    restore: () => { draft = pendingDraft.draft; pendingDraft = null; },
    discard: () => { pendingDraft = null; try { localStorage.removeItem(key); } catch { /* ignore */ } },
  };
  function fit(a) {
    // Spread the missing (or extra) points one at a time across attributes that still have room.
    const p = pack();
    let diff = p.budget - p.attributes.reduce((s, at) => s + (a.attributes[at.id] ?? at.min), 0);
    p.attributes.forEach((at) => { a.attributes[at.id] = Math.max(at.min, Math.min(at.max, a.attributes[at.id] ?? at.min)); });
    diff = p.budget - p.attributes.reduce((s, at) => s + a.attributes[at.id], 0);
    for (let guard = 0; diff !== 0 && guard < 2000; guard++) {
      const at = p.attributes[guard % p.attributes.length];
      const v = a.attributes[at.id];
      if (diff > 0 && v < at.max) { a.attributes[at.id] = v + 1; diff--; }
      else if (diff < 0 && v > at.min) { a.attributes[at.id] = v - 1; diff++; }
    }
  }
  function normalise() {
    draft.presentation.acts.forEach((a, i) => { a.number = i + 1; });
  }

  async function serverValidate(button) {
    normalise();
    const result = await busy(button, () => ctx.api.post("worlds/validate", { pack: draft.pack, presentation: draft.presentation }));
    serverCheck = result.ok ? result : { error: result.error };
    updateLive();
  }

  async function save(button) {
    normalise();
    const all = issues();
    const first = STEPS.findIndex(([k]) => k !== "review" && all[k].length);
    if (first >= 0) {
      ctx.toast("还有 " + all.review.length + " 个问题，先处理“" + STEPS[first][1] + "”", "error");
      return ACTIONS.goto(first);
    }
    try {
      const result = await busy(button, () => ctx.api.post("worlds/save", { pack: draft.pack, presentation: draft.presentation, create: isNew }));
      saved = JSON.stringify(draft);
      persisted = true;
      try { localStorage.removeItem(key); } catch { /* ignore */ }
      ctx.toast("已保存「" + shortTitle(draft.pack.title) + "」第 " + result.revision + " 版");
      ctx.go("worlds/" + encodeURIComponent(result.id));
    } catch (error) {
      serverCheck = { error: error.message };
      ctx.toast(error.message, "error");
      if (step !== STEPS.length - 1) ACTIONS.goto(STEPS.length - 1); else updateLive();
    }
  }

  function exportFile() {
    normalise();
    const blob = new Blob([JSON.stringify({ format: source.bundle_format, pack: draft.pack, presentation: draft.presentation }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = draft.pack.id + ".world.json";
    a.click();
    ctx.toast("已导出 " + a.download + (dirty() ? "（包含未保存的修改）" : ""));
  }

  root.addEventListener("click", (e) => {
    const el = e.target.closest("[data-act]");
    if (!el || el.disabled) return;
    const act = el.dataset.act;
    if (act === "save") return save(el);
    if (act === "export") return exportFile();
    if (act === "check") return serverValidate(el).catch((error) => ctx.toast(error.message, "error"));
    const fn = ACTIONS[act];
    if (!fn) return;
    fn(Number(el.dataset.i), el.dataset.v);
    if (act !== "goto") { changed(); renderStep(); }
  });

  renderStep();
}

