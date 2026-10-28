// World editor: a seven-step flow over a draft {pack, presentation}.
// Inputs bind to draft paths (data-bind); structural edits are data-act buttons that re-render the step.
// Every change re-checks the draft, so the stepper always shows which step still has problems.
import { DIFFICULTY as DIFF, NARRATION, acts as actTrack, busy, cover, dcScale, esc, meter, narrationExtensions, narrationHint, notch, shortTitle, subTitle, tier } from "../ui.js";
import { HANDOFF } from "./tavern.js";

const STEPS = [
  ["basics", "基本信息", "封面、标题、世界观与开场"],
  ["rules", "规则", "属性、资源、难度与人数"],
  ["kit", "技能与物品", "职业可选的技能、开局物品"],
  ["archetypes", "职业", "属性分配与技能"],
  ["creation", "建卡", "模式、挪点、出身、人物细节、特质、背景问题与装备包"],
  ["economy", "经济", "货币、价格、商店与工钱"],
  ["entries", "设定条目", "地点、人物、线索与起点"],
  ["acts", "幕与结局", "幕的标题引子与结局条件"],
  ["pacing", "节奏", "场景与每幕轮数、篇幅与收尾提议"],
  ["review", "检查与保存", "校验、保存或导出"],
];
const KINDS = [["region", "地区"], ["place", "地点"], ["faction", "势力"], ["npc", "人物"], ["goal", "目标"], ["clue", "线索"]];
const MODES = [["hybrid", "选项与自由行动"], ["choice_only", "只用选项"], ["dialogue_only", "只用自由行动"]];
const RESETS = [["scene", "每幕"], ["rest", "休整后"], ["never", "不恢复"]];
const TONES = [["ink", "墨蓝"], ["ember", "余烬"], ["neon", "霓紫"], ["jade", "青玉"], ["wine", "酒红"], ["slate", "石灰"]];
// Build modes (roll_lite/rooms/build.py): 快选 is always open; a world may close 定制 or 精雕 and tune the limits.
const CREATE_MODES = [["quick", "快选", "挑职业、起名字就上桌", "2 步 · 30 秒"], ["custom", "定制", "挪点、换技能、出身、多带一件东西、答一问", "2–3 分钟"],
  ["forge", "精雕", "任选技能、装备包、写背景，可定开局关系", "5–10 分钟"]];
const CREATE_DEFAULTS = { move: 4, swap: 1 };
// Trait conditions (roll_lite/worlds/creation.py TRAIT_WHEN): [key, picker label, prefix before "<属性>检定"].
const TRAIT_WHEN = [["any", "任何时候", ""], ["hard", "困难及以上", "困难及以上的"], ["easy", "普通及以下", "普通及以下的"], ["hurt", "带伤时", "带伤时的"],
  ["alone", "没人援手时", "没人援手时的"], ["helped", "有人援手时", "有人援手时的"], ["allIn", "孤注一掷时", "孤注一掷时的"]];
const DETAIL_MODES = [["custom", "定制"], ["forge", "精雕"]];
// '困难及以上的胆量检定 +2' / '所有检定 −1', the same words the player sees.
export function traitEffect(effect, attributes, sign) {
  const when = TRAIT_WHEN.find(([k]) => k === (effect.when || "any")) || TRAIT_WHEN[0];
  const attr = (attributes.find((a) => a.id === effect.attribute) || {}).name || "";
  const target = when[0] !== "any" || attr ? when[2] + attr + "检定" : "所有检定";
  return target + " " + (sign > 0 ? "+" : "−") + (effect.value || 1);
}
const ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,100}$/;
const LIMITS = { title: 100, worldview: 6000, seed: 3000, style: 300, boundaries: 1000, guidance: 2000 };
// What new tables on a world start with when it sets nothing (roll_lite/narration.py FALLBACK).
const NARRATION_DEFAULTS = { improv: "均衡", dialogue: "dialogue_soft", length: "free" };
const withNarration = (d, given) => ({ ...d, narration: { ...NARRATION_DEFAULTS, ...(d.narration || {}), ...(given || {}) } });
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

// A world card made by the tavern import wizard (views/tavern.js), handed over through sessionStorage.
function tavernSource() {
  let handed = null;
  try { handed = JSON.parse(sessionStorage.getItem(HANDOFF) || "null"); } catch { /* storage unavailable */ }
  if (!handed?.pack) throw new Error("没有找到酒馆导入的草稿，请回到“新建世界 → 从酒馆导入”重新生成预览。");
  return { pack: handed.pack, presentation: handed.presentation, cover: handed.presentation?.cover,
    narration: Object.fromEntries(Object.entries(handed.narration || {}).map(([f, v]) => [f, { value: v }])), bundle_format: BLANK.bundle_format, title: handed.title };
}

export async function render(root, ctx, { id, from, tavern = false }) {
  const list = await ctx.api.get("worlds");
  const taken = new Set(list.worlds.map((w) => w.id));
  // No id, no from and no tavern draft: a blank world.
  const blank = !id && !from && !tavern;
  const source = blank ? clone(BLANK) : tavern ? tavernSource() : await ctx.api.get("world", { id: id || from });
  const isNew = !id;
  if (!blank && !tavern && source.source !== "custom") throw new Error("自带世界和市场世界是只读的，不能修改或复制。想写自己的世界，请在“新建世界”里从空白开始。");

  let draft = { pack: clone(source.pack), presentation: clone(source.presentation || {}) };
  draft = withNarration(draft, Object.fromEntries(Object.entries(source.narration || {}).map(([f, d]) => [f, d.value])));
  draft.presentation.acts = draft.presentation.acts || [];
  draft.presentation.endings = draft.presentation.endings || [];
  draft.presentation.places = draft.presentation.places || [];
  if (isNew) {
    const stem = blank ? "my-world" : tavern ? draft.pack.id : (from + "-copy").slice(0, 90);
    let next = stem;
    for (let n = 2; taken.has(next); n++) next = stem + "-" + n;
    draft.pack.id = next;
    draft.pack.revision = 1;
    if (!blank && !tavern) {
      const [main, ...rest] = draft.pack.title.split(" · ");
      draft.pack.title = [main + "（副本）", ...rest].join(" · ");
    }
  }
  draft.presentation.cover = draft.presentation.cover || { ...source.cover };

  const key = "roll-lite-world-draft:" + (isNew ? "new:" + (from || (tavern ? "tavern" : "blank")) : id);
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

  root.innerHTML = '<div class="ed-root"><a class="crumb" href="#/worlds' + (blank ? "/import" : tavern ? "/tavern" : "/" + encodeURIComponent(isNew ? from : id)) + '">← ' +
    (blank ? "返回新建世界" : tavern ? "返回酒馆导入" : isNew ? "返回原世界" : "返回世界详情") + "</a>" +
    '<header class="ed-head"><div data-live="cover-mini"></div><div class="ed-title"><div class="eyebrow">' + (blank ? "新建世界 · 从空白开始" : tavern ? "新建世界 · 从酒馆导入" : isNew ? "新建世界 · 复制自 " + esc(shortTitle(source.pack.title)) : "编辑世界 · " + tier(draft.presentation.edition, source.pack.revision)) +
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
  // The optional creation block is created on first edit, so opening the step alone leaves the draft untouched.
  const cre = () => (draft.pack.creation ||= {});
  const creOf = () => draft.pack.creation || {};
  // Optional economy block (roll_lite/worlds/economy.py); absent means the world has no money.
  const eco = () => draft.pack.economy;
  const ECO_INTS = [["initial", "开局钱数", 0, 100000], ["wage", "每幕工钱", 0, 10000], ["storyLimit", "单段正文得失上限", 1, 100000], ["sell", "回收比例 %", 0, 100], ["kitMoney", "精雕“装备包折钱”", 0, 100000]];
  // Optional pacing block (roll_lite/worlds/pacing.py): every world is paced; the block only changes the numbers.
  const paceOf = () => draft.pack.pacing || {};
  function paceView() {
    const p = paceOf(), core = draft.presentation.edition === "core", acts = draft.presentation.acts.length;
    const scene = p.sceneRounds ?? 4, act = p.actRounds ?? 8, grace = p.graceRounds ?? 2, count = core || !acts ? 3 : acts;
    const per = (n) => p.acts?.[String(n)] ?? act;
    const autoTarget = act ? Array.from({ length: count }, (_, i) => per(i + 1)).reduce((a, b) => a + b, 0) : 0;
    const target = p.targetRounds ?? autoTarget;
    const autoHard = target ? target + Math.max(2, Math.floor(target / 2)) : 0;
    return { scene, act, grace, count, per, autoTarget, target, autoHard, hard: p.hardRounds ?? autoHard, ending: p.endingPrompt !== false };
  }
  const createModes = () => creOf().modes || (draft.presentation.edition === "core" ? ["quick", "custom"] : ["quick", "custom", "forge"]);
  const createMove = () => creOf().move ?? CREATE_DEFAULTS.move;
  const createSwap = () => Math.min(creOf().swap ?? CREATE_DEFAULTS.swap, pack().rules.skillSlots);
  const fallbackOrigins = () => pack().entries.filter((e) => e.public && (e.kind === "faction" || e.kind === "region"));
  const defaultQuestions = () => ["你为什么会来到" + (shortTitle(pack().title) || "这里") + "？", "你欠谁一个人情？", "你最怕什么？"];
  let reachArch = 0;

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

    const cset = p.creation;
    if (cset) {
      const itemIds = new Set(p.items.map((x) => x.id));
      if (cset.move != null && (!isInt(cset.move) || cset.move < 0 || cset.move > 12)) add("creation", "属性挪点要在 0–12 之间");
      if (cset.swap != null && (!isInt(cset.swap) || cset.swap < 0 || cset.swap > r.skillSlots)) add("creation", "定制换技能要在 0–" + r.skillSlots + " 之间（不超过技能栏位）");
      (cset.origins || []).forEach((o, i) => {
        const name = o.name.trim() || "第 " + (i + 1) + " 个出身";
        if (!o.name.trim() || o.name.trim().length > 30) add("creation", name + "的名字要 1–30 字");
        if ((o.text || "").length > 200) add("creation", "出身「" + name + "」的说明超过 200 字");
        if (o.item && !itemIds.has(o.item)) add("creation", "出身「" + name + "」带的物品已不存在");
      });
      if ((cset.origins || []).length > 12) add("creation", "出身最多 12 个，多出的不会显示");
      if ((cset.questions || []).some((q) => q.trim() && (q.trim().length < 2 || q.trim().length > 40))) add("creation", "背景问题每个 2–40 字");
      (cset.kits || []).forEach((k, i) => {
        const name = k.name.trim() || "第 " + (i + 1) + " 个装备包";
        if (!k.name.trim() || k.name.trim().length > 20) add("creation", name + "的名字要 1–20 字");
        const entries = Object.entries(k.items || {});
        if (!entries.length) add("creation", "装备包「" + name + "」还没有物品");
        if (entries.some(([id, n]) => !itemIds.has(id) || !isInt(n) || n < 1 || n > 10)) add("creation", "装备包「" + name + "」的物品数量要在 1–10 之间");
      });
      if ((cset.kits || []).length > 8) add("creation", "装备包最多 8 个，多出的不会显示");
      const seen = new Set();
      (cset.details || []).forEach((d, i) => {
        const name = d.name.trim() || "第 " + (i + 1) + " 项人物细节";
        if (!d.name.trim() || d.name.trim().length > 8) add("creation", name + "的名字要 1–8 字");
        else if (seen.has(d.name.trim())) add("creation", "人物细节「" + name + "」重名了");
        seen.add(d.name.trim());
        if ((d.text || "").length > 60) add("creation", "人物细节「" + name + "」的提示超过 60 字");
        if ((d.options || []).some((o) => !o.name.trim() || o.name.trim().length > 20)) add("creation", "人物细节「" + name + "」有选项没写名字或超过 20 字");
        if ((d.options || []).some((o) => (o.text || "").length > 60)) add("creation", "人物细节「" + name + "」有选项说明超过 60 字");
        if (!(d.modes || ["forge"]).length) add("creation", "人物细节「" + name + "」至少要出现在定制或精雕里");
      });
      if ((cset.details || []).length > 4) add("creation", "人物细节最多 4 项");
      const traitNames = new Set(), attrIds = new Set(p.attributes.map((a) => a.id));
      (cset.traits || []).forEach((t, i) => {
        const name = t.name.trim() || "第 " + (i + 1) + " 个特质";
        if (!t.name.trim() || t.name.trim().length > 12) add("creation", name + "的名字要 1–12 字");
        else if (traitNames.has(t.name.trim())) add("creation", "特质「" + name + "」重名了");
        traitNames.add(t.name.trim());
        if ((t.text || "").length > 80) add("creation", "特质「" + name + "」的描述超过 80 字");
        if (!(t.modes || ["forge"]).length) add("creation", "特质「" + name + "」至少要出现在定制或精雕里");
        for (const k of ["up", "down"]) {
          if (![1, 2].includes(t[k]?.value)) add("creation", "特质「" + name + "」的" + (k === "up" ? "利" : "弊") + "要选 1 或 2 点");
          if (t[k]?.attribute && !attrIds.has(t[k].attribute)) add("creation", "特质「" + name + "」用到的属性已不存在");
        }
      });
      if ((cset.traits || []).length > 8) add("creation", "特质最多 8 个");
      (cset.origins || []).forEach((o, i) => { if (o.money != null && (!isInt(o.money) || Math.abs(o.money) > 100000)) add("economy", "出身「" + (o.name || i + 1) + "」带的钱要在 -100000–100000 之间"); });
    }

    p.entries.forEach((e) => {
      if (!e.name.trim()) add("entries", "有条目没有名字");
      if (e.summary.length > 4000 || e.secret.length > 4000) add("entries", "条目「" + (e.name || e.id) + "」的内容超过 4000 字");
    });
    if (!p.initial.place.trim()) add("entries", "开场地点不能为空");

    const e = p.economy;
    if (e) {
      const cur = (e.currency || "").trim();
      if (!cur || cur.length > 8) add("economy", "货币名要 1–8 字");
      for (const [k, label, lo, hi] of ECO_INTS) if (e[k] != null && (!isInt(e[k]) || e[k] < lo || e[k] > hi)) add("economy", label + "要在 " + lo + "–" + hi + " 之间");
      const priced = new Set(Object.entries(e.prices || {}).filter(([, v]) => isInt(v) && v >= 1 && v <= 100000).map(([k]) => k));
      if (Object.values(e.prices || {}).some((v) => v != null && !(isInt(v) && v >= 1 && v <= 100000))) add("economy", "价格要在 1–100000 之间");
      const entryIds = new Set(p.entries.map((x) => x.id));
      (e.shops || []).forEach((s, i) => {
        const name = "第 " + (i + 1) + " 家店" + (s.name ? "「" + s.name + "」" : "");
        if (!(s.name || "").trim() || s.name.trim().length > 20) add("economy", name + "的名字要 1–20 字");
        if ((s.kind || "").length > 8) add("economy", name + "的类别最多 8 字");
        if ((s.text || "").length > 80) add("economy", name + "的说明超过 80 字");
        if (s.place && !entryIds.has(s.place)) add("economy", name + "绑定的地点已不存在");
        if (!(s.items || []).length) add("economy", name + "还没有上架商品");
        if ((s.items || []).length > 30) add("economy", name + "最多上架 30 件");
        if ((s.items || []).some((id) => !priced.has(id))) add("economy", name + "有商品还没定价");
      });
      if ((e.shops || []).length > 12) add("economy", "商店最多 12 家");
    }
    draft.presentation.acts.forEach((a, i) => { if (!a.title.trim()) add("acts", "第 " + (i + 1) + " 幕没有标题"); });
    const pc = p.pacing;
    if (pc) {
      for (const [k, label, lo, hi] of [["sceneRounds", "场景轮数", 0, 50], ["actRounds", "每幕轮数", 0, 100], ["graceRounds", "宽限轮数", 1, 10], ["targetRounds", "全程目标", 0, 1000], ["hardRounds", "全程上限", 0, 1000]])
        if (pc[k] != null && (!isInt(pc[k]) || pc[k] < lo || pc[k] > hi)) add("pacing", label + "要在 " + lo + "–" + hi + " 之间");
      if (pc.targetRounds && pc.hardRounds && pc.hardRounds < pc.targetRounds) add("pacing", "全程上限不能小于全程目标");
      if (Object.values(pc.acts || {}).some((v) => v != null && !(isInt(v) && v >= 1 && v <= 100))) add("pacing", "每一幕的轮数要在 1–100 之间");
    }
    draft.presentation.endings.forEach((e, i) => { if (!e.name.trim()) add("acts", "第 " + (i + 1) + " 个结局没有名字"); });
    out.review = Object.entries(out).filter(([k]) => k !== "review").flatMap(([, v]) => v);
    return out;
  }
  const fieldName = (f) => ({ title: "标题", worldview: "世界观", seed: "开场", style: "文笔与基调", boundaries: "内容边界", guidance: "主持要点" })[f] || f;

  function summary(k) {
    const p = draft.pack, pr = draft.presentation;
    return {
      basics: (p.worldview.length + p.seed.length) + " 字",
      rules: p.attributes.length + " 属性 · " + p.resources.length + " 资源",
      kit: p.skills.length + " 技能 · " + p.items.length + " 物品",
      archetypes: p.archetypes.length + " 个职业",
      creation: createModes().length + " 种模式 · 挪 " + createMove() + " · 换 " + createSwap() + ((creOf().traits || []).length ? " · " + creOf().traits.length + " 个特质" : ""),
      economy: p.economy ? (p.economy.currency || "未命名货币") + " · " + (p.economy.shops || []).length + " 家店" : "未开启",
      entries: p.entries.length + " 条 · " + p.entries.filter((e) => e.public).length + " 公开",
      acts: pr.acts.length + " 幕 · " + pr.endings.length + " 结局",
      pacing: (() => { const v = paceView(); return "场景 " + (v.scene || "不催") + " · 每幕 " + (v.act || "不催") + " · 全程 " + (v.target || "不限"); })(),
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
  const val = (v) => ' value="' + esc(v || "") + '"';

  // A story detail (信仰, 外貌…): its name, the prompt, which deep modes ask it, its options and whether players may write their own.
  function detailCard(d, i) {
    const b = "pack.creation.details." + i + ".", options = d.options || [], modes = d.modes || ["forge"], free = d.free !== false || !options.length;
    const optRow = (o, j) => '<div class="cre-opt"><span class="opt-num">' + (j + 1) + '</span><input class="input" maxlength="20" data-bind="' + b + "options." + j + '.name"' + val(o.name) + ' placeholder="选项" />' +
      '<input class="input" maxlength="60" data-bind="' + b + "options." + j + '.text"' + val(o.text) + ' placeholder="一句说明（可不填）" />' +
      '<button class="btn text small danger" data-act="del-detail-opt" data-i="' + i + '" data-v="' + j + '" type="button" aria-label="删除选项">✕</button></div>';
    return '<div class="ed-card cre-detail"><div class="ed-card-head"><span class="cre-badge">细节</span><input class="input strong" maxlength="8" data-bind="' + b + 'name"' + val(d.name) + ' placeholder="细节名，例如：信仰" />' + del("del-detail", i) + "</div>" +
      '<input class="input" maxlength="60" data-bind="' + b + 'text"' + val(d.text) + ' placeholder="给玩家的提示，例如：你在这座城里信什么" />' +
      '<div class="cre-toggles chips"><span class="label">出现在</span>' + DETAIL_MODES.map(([k, l]) => '<button type="button" class="chip small' + (modes.includes(k) ? " on" : "") + '" data-act="detail-mode" data-i="' + i + '" data-v="' + k + '">' + l + "</button>").join("") +
      '<span class="cre-sep"></span><button type="button" class="chip small' + (free ? " on" : "") + '" data-act="detail-free" data-i="' + i + '"' + (options.length ? "" : " disabled") + ">允许自己写</button></div>" +
      (options.length ? '<div class="cre-opts">' + options.map(optRow).join("") + "</div>" : "") +
      '<div class="row between">' + (options.length < 8 ? '<button class="btn text small" data-act="add-detail-opt" data-i="' + i + '" type="button">＋ 添加选项</button>' : "<span></span>") +
      '<span class="hint">' + (!options.length ? "没有选项：玩家自己写一句（30 字内）" : free ? "可以挑选项，也可以自己写" : "只能从选项里挑") + "</span></div></div>";
  }

  // A trait: an upside and a downside, each a condition, an optional attribute and ±1/±2.
  function traitCard(t, i) {
    const p = pack(), b = "pack.creation.traits." + i + ".", modes = t.modes || ["forge"];
    const attrOpts = (v) => opts([["", "任何属性"], ...p.attributes.map((a) => [a.id, a.name || a.id])], v || "");
    const side = (k, sign, label) => '<div class="cre-eff ' + (sign > 0 ? "up" : "dn") + '"><span class="cre-eff-tag">' + label + "</span>" +
      '<select class="select" data-bind="' + b + k + '.when">' + opts(TRAIT_WHEN.map(([w, l]) => [w, l]), t[k].when || "any") + "</select>" +
      '<select class="select" data-bind="' + b + k + '.attribute">' + attrOpts(t[k].attribute) + "</select>" +
      '<span class="cre-seg">' + [1, 2].map((n) => '<button type="button" class="' + (t[k].value === n ? "on" : "") + '" data-act="trait-value" data-i="' + i + '" data-v="' + k + ":" + n + '">' + (sign > 0 ? "+" : "−") + n + "</button>").join("") + "</span></div>";
    return '<div class="ed-card cre-trait"><div class="ed-card-head"><span class="cre-badge">特质</span><input class="input strong" maxlength="12" data-bind="' + b + 'name"' + val(t.name) + ' placeholder="特质名，例如：临危不乱" />' + del("del-trait", i) + "</div>" +
      '<input class="input" maxlength="80" data-bind="' + b + 'text"' + val(t.text) + ' placeholder="一句话写性格，例如：越危险越冷静，平时反倒丢三落四" />' +
      '<div class="cre-toggles chips"><span class="label">出现在</span>' + DETAIL_MODES.map(([k, l]) => '<button type="button" class="chip small' + (modes.includes(k) ? " on" : "") + '" data-act="trait-mode" data-i="' + i + '" data-v="' + k + '">' + l + "</button>").join("") + "</div>" +
      side("up", 1, "利") + side("down", -1, "弊") + '<div class="cre-trait-sum" data-live="trait:' + i + '"></div></div>';
  }

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
        '<div class="field"><span class="label">版本</span><div class="seg" role="group" aria-label="世界版本">' +
          [["core", "核心版 · 世界卡"], ["pro", "进阶版 · 世界包"]].map(([v, l]) => '<button type="button" data-act="edition" data-v="' + v + '" aria-pressed="' + ((draft.presentation.edition || "pro") === v) + '">' + l + "</button>").join("") +
          '</div><span class="hint">' + ((draft.presentation.edition || "pro") === "core"
            ? "核心版只预设第一幕，没有固定结局；之后的幕由主持人用 /团 主持 换幕 标题 即兴开启。"
            : "进阶版按你写好的幕和结局推进。") + "</span></div>" +
        '<hr class="rule" />' + sectionHead("世界与开场", "世界观和开场会交给叙事模型；开场是第一幕的起点描写。") +
        text("pack.worldview", "世界观", { limit: LIMITS.worldview, area: true, rows: 9 }) +
        text("pack.seed", "开场", { limit: LIMITS.seed, area: true, rows: 5, hint: "开团时会作为开团卡的引子发到群里。" }) +
        text("pack.style", "文笔与基调", { limit: LIMITS.style, area: true, rows: 2, placeholder: "例如：冷峻克制，多用短句，带一点黑色幽默", hint: "写给叙事模型的文字要求；主持人开桌后还可以补充。" }) +
        '<details class="ed-more"><summary>主持要点与内容边界（不公开）</summary><div style="margin-top:14px">' +
        text("pack.guidance", "主持要点", { limit: LIMITS.guidance, area: true, rows: 5, hint: "真相、伏笔等只给模型看的内容。" }) +
        text("pack.boundaries", "内容边界", { limit: LIMITS.boundaries, area: true, rows: 3 }) + "</div></details>" +
        '<hr class="rule" />' + sectionHead("叙事默认", "新开的团桌沿用这些设置，主持人开桌后可以随时调整。") +
        '<div class="narr">' + ["improv", "dialogue", "length"].map((f) => '<div class="narr-row"><div class="narr-head"><b>' + NARRATION[f].title + '</b><span class="now">' +
          esc(NARRATION[f].options.find((o) => o[0] === draft.narration[f])[1]) + "</span></div>" + notch(f, draft.narration[f]) +
          '<p class="narr-hint">' + esc(narrationHint(f, draft.narration[f])) + "</p></div>").join("") + "</div>";
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
        '<hr class="rule" />' + sectionHead("难度", "四档难度对应群里的 简单 / 标准 / 困难 / 极难。刻度上的百分比是属性加值为 0 时投掷的成功率。") +
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

    creation() {
      const p = pack(), cv = creOf(), modes = createModes(), slots = p.rules.skillSlots;
      const dots = (n) => '<span class="cm-dots">' + [1, 2, 3].map((i) => "<i" + (i <= n ? ' class="on"' : "") + "></i>").join("") + "</span>";
      const fallback = fallbackOrigins();
      const itemOpts = (value) => opts([["", "不带物品"], ...p.items.map((x) => [x.id, x.name || x.id])], value || "");
      return sectionHead("开放的模式", "快选始终开放。核心版世界默认只开放快选和定制；主持人开桌后还能再往下限制，但不能超出这里。",
          creOf().modes || p.creation ? '<button class="btn text small" data-act="cre-reset" type="button">全部恢复默认</button>' : "") +
        '<div class="cm-grid">' + CREATE_MODES.map(([k, label, desc, cost], i) => {
          const on = modes.includes(k);
          return '<button type="button" class="cm-card' + (on ? " on" : "") + '" data-act="cre-mode" data-v="' + k + '"' + (k === "quick" ? " disabled" : "") + ' aria-pressed="' + on + '">' +
            '<span class="cm-head"><b>' + label + "</b>" + dots(i + 1) + '</span><span class="cm-cost">' + cost + '</span><span class="cm-desc">' + desc + '</span><span class="cm-state">' +
            (k === "quick" ? "始终开放" : on ? "✓ 开放" : "未开放") + "</span></button>";
        }).join("") + "</div>" +
        '<div data-live="cre-flow" style="margin-top:16px"></div>' +
        '<hr class="rule" />' + sectionHead("属性与技能的自由度", "定制和精雕都从职业出发；这里决定玩家能在职业基础上改多少。") +
        '<div class="ed-alloc" style="gap:14px">' +
        '<label class="ed-alloc-row cre-limit"><span>属性最多挪</span><input type="range" min="0" max="12" step="1" data-type="int" data-bind="pack.creation.move" value="' + createMove() + '" />' +
          '<input class="input num" type="number" min="0" max="12" data-type="int" data-bind="pack.creation.move" value="' + createMove() + '" /></label>' +
        '<label class="ed-alloc-row cre-limit"><span>定制换技能</span><input type="range" min="0" max="' + slots + '" step="1" data-type="int" data-bind="pack.creation.swap" value="' + createSwap() + '"' + (slots ? "" : " disabled") + " />" +
          '<input class="input num" type="number" min="0" max="' + slots + '" data-type="int" data-bind="pack.creation.swap" value="' + createSwap() + '"' + (slots ? "" : " disabled") + " /></label></div>" +
        '<p class="hint" style="margin:10px 0 0">挪点指加点合计（同时减掉同样多的点），每项属性仍在范围内；默认 4 点。换技能只对定制生效，精雕从技能池任选，不超过 ' + slots + " 个栏位。</p>" +
        '<div class="panel soft" style="margin-top:14px" data-live="cre-reach"></div>' +
        '<hr class="rule" />' + sectionHead("出身", "定制和精雕第一步之后会让玩家选出身；可以顺带一件开局物品。" + (cv.origins?.length ? "" : "不填时用世界里公开的地区和势力。"),
          (cv.origins || []).length < 12 ? '<button class="btn small" data-act="add-origin" type="button">添加出身</button>' : "") +
        ((cv.origins || []).length ? '<div class="ed-cards">' + cv.origins.map((o, i) => '<div class="ed-card"><div class="ed-card-head"><input class="input strong" maxlength="30" data-bind="pack.creation.origins.' + i + '.name" value="' + esc(o.name) + '" placeholder="出身名，例如：雾港本地人" />' + del("del-origin", i) + "</div>" +
          '<input class="input" maxlength="200" data-bind="pack.creation.origins.' + i + '.text" value="' + esc(o.text || "") + '" placeholder="一句话说明，玩家选择时能看到" />' +
          (eco() ? '<div class="ed-grid4">' + select("pack.creation.origins." + i + ".item", "顺带的物品", itemOpts(o.item)) + num("pack.creation.origins." + i + ".money", "多带的钱（" + (eco().currency || "钱") + "，可为负）", 'min="-100000" max="100000"') + "</div>"
            : select("pack.creation.origins." + i + ".item", "顺带的物品", itemOpts(o.item))) + "</div>").join("") + "</div>"
          : '<div class="chips"><span class="hint">当前会用：</span>' + (fallback.length ? fallback.map((e) => '<span class="tag">' + esc(e.name || e.id) + "</span>").join("") : '<span class="hint">没有公开的地区或势力，出身这一步会跳过</span>') + "</div>") +
        '<hr class="rule" />' + sectionHead("人物细节", "只写进故事、不影响数值的设定，比如信仰、外貌、口头禅。可以给选项让玩家挑，也可以让玩家自己写一句；AI 主持每轮都会读到。最多 4 项。",
          (cv.details || []).length < 4 ? '<button class="btn small" data-act="add-detail" type="button">添加人物细节</button>' : "") +
        ((cv.details || []).length ? '<div class="ed-cards">' + cv.details.map(detailCard).join("") + "</div>" : '<p class="hint">还没有人物细节，建卡时不会出现这类步骤。</p>') +
        '<hr class="rule" />' + sectionHead("特质", "利弊一体的性格：“利”让某些检定加值，“弊”让另一些检定减值，掷骰时插件自动算，AI 只读到结果。每个特质可以设定出现在定制还是精雕（新加的默认只在精雕），玩家最多选一个，也可以不选。最多 8 个。",
          (cv.traits || []).length < 8 ? '<button class="btn small" data-act="add-trait" type="button">添加特质</button>' : "") +
        ((cv.traits || []).length ? '<div class="ed-cards">' + cv.traits.map(traitCard).join("") + "</div>" : '<p class="hint">还没有特质，建卡时不会出现“特质”这一步。</p>') +
        '<hr class="rule" />' + sectionHead("背景问题", "定制回答第 1 个，精雕三个都回答。答案会写进角色卡，AI 主持每轮都会读到。好的问题能勾出故事，比如“你欠谁一个人情？”。") +
        '<div class="cre-qs">' + [0, 1, 2].map((i) => '<label class="cre-q"><span class="opt-num">' + (i + 1) + '</span><input class="input" maxlength="40" data-bind="pack.creation.questions.' + i + '" value="' + esc((cv.questions || [])[i] || "") +
          '" placeholder="' + esc(defaultQuestions()[i]) + '" /><span class="tag' + (i ? "" : " gold") + '">' + (i ? "精雕" : "定制 · 精雕") + "</span></label>").join("") + "</div>" +
        '<p class="hint" style="margin:8px 0 0">留空的用灰色的默认问题；三个都留空就全部用默认问题。</p>' +
        '<hr class="rule" />' + sectionHead("开局关系", "精雕的最后一步：和同桌定一层关系（对方同意才生效），或认一位公开人物作旧识。想让关系全在游玩中自然发展，就关掉这一步。") +
        '<div class="chips cre-toggles"><button type="button" class="chip' + (cv.relation === false ? "" : " on") + '" data-act="cre-relation" aria-pressed="' + (cv.relation !== false) + '">精雕包含开局关系</button>' +
          '<span class="hint">' + (cv.relation === false ? "已关闭：精雕写完背景就能确认，不会出现关系卡。" : "开启：精雕最后会出现关系卡，玩家可以跳过。") + "</span></div>" +
        '<hr class="rule" />' + sectionHead("装备包", "精雕时可以挑一个装备包代替“多带一件东西”。没有装备包时，精雕和定制一样多带一件。",
          (cv.kits || []).length < 8 ? '<button class="btn small" data-act="add-kit" type="button"' + (p.items.length ? "" : " disabled") + ">添加装备包</button>" : "") +
        ((cv.kits || []).length ? '<div class="ed-cards">' + cv.kits.map((k, i) => '<div class="ed-card"><div class="ed-card-head"><input class="input strong" maxlength="20" data-bind="pack.creation.kits.' + i + '.name" value="' + esc(k.name) + '" placeholder="装备包名，例如：守夜包" />' + del("del-kit", i) + "</div>" +
          '<input class="input" data-bind="pack.creation.kits.' + i + '.text" value="' + esc(k.text || "") + '" placeholder="一句话说明" />' +
          '<div class="chips">' + p.items.map((x) => '<button type="button" class="chip small' + (k.items[x.id] ? " on" : "") + '" data-act="kit-item" data-i="' + i + '" data-v="' + esc(x.id) + '">' + esc(x.name || x.id) + "</button>").join("") + "</div>" +
          (Object.keys(k.items).length ? '<div class="cre-kit">' + Object.entries(k.items).map(([id, n]) => '<label class="ed-mini"><span>' + esc((p.items.find((x) => x.id === id) || {}).name || id) + '</span><input class="input num" type="number" min="1" max="10" data-type="int" data-bind="kit-count" data-i="' + i + '" data-v="' + esc(id) + '" value="' + n + '" /></label>').join("") + "</div>" : "") +
          "</div>").join("") + "</div>" : '<p class="hint">' + (p.items.length ? "还没有装备包。" : "先在“技能与物品”里添加物品。") + "</p>");
    },


    economy() {
      const p = pack(), e = eco();
      const intro = "开启后每位角色有独立钱包：故事里会得钱失钱，玩家在“整备”时到当前地点的店里买卖。不开启时世界里没有钱。";
      if (!e) return sectionHead("经济", intro, '<button class="btn small primary" data-act="eco-on" type="button">开启经济</button>') +
        '<p class="hint">适合有交易、物资紧张或需要攒钱目标的世界。开启后可以设置货币、价格、商店和每幕工钱。</p>';
      const cur = e.currency || "钱", priced = (id) => isInt(e.prices?.[id]) && e.prices[id] >= 1;
      const places = [["", "随处可买"], ...p.entries.filter((x) => x.kind === "place" || x.kind === "region").map((x) => [x.id, (x.kind === "region" ? "地区 · " : "") + (x.name || x.id)])];
      const priceRow = (it, i) => '<div class="eco-price"><span class="opt-num">' + (i + 1) + '</span><span class="strong" style="flex:1">' + esc(it.name || it.id) + "</span>" +
        '<input class="input num" type="number" min="1" max="100000" data-type="int" data-bind="eco-price" data-i="' + i + '" value="' + esc(e.prices?.[it.id] ?? "") + '" placeholder="不卖" />' +
        '<span class="hint">' + esc(cur) + "</span></div>";
      const shopCard = (s, i) => {
        const b = "pack.economy.shops." + i + ".", wares = new Set(s.items || []);
        const chips = p.items.filter((it) => priced(it.id)).map((it) => '<button type="button" class="tag' + (wares.has(it.id) ? " gold" : "") + '" data-act="eco-ware" data-i="' + i + '" data-v="' + esc(it.id) + '">' +
          (wares.has(it.id) ? "✓ " : "+ ") + esc(it.name || it.id) + " · " + e.prices[it.id] + "</button>").join("");
        return '<div class="ed-card"><div class="ed-card-head"><input class="input strong" maxlength="20" data-bind="' + b + 'name"' + val(s.name) + ' placeholder="店名，例如：卡隆商行" />' + del("eco-del-shop", i) + "</div>" +
          '<div class="ed-grid4" style="grid-template-columns:130px minmax(0, 1fr)"><label class="field"><span class="label">类别</span><input class="input" maxlength="8" data-bind="' + b + 'kind"' + val(s.kind) + ' placeholder="例如：杂货、武器" /></label>' +
          select(b + "place", "开在哪里", opts(places, s.place || "")) + "</div>" +
          '<input class="input" maxlength="80" data-bind="' + b + 'text"' + val(s.text) + ' placeholder="一句话说明，玩家看货时能看到" />' +
          '<span class="label">上架商品 · ' + wares.size + " 件</span>" +
          '<div class="chips">' + (chips || '<span class="hint">先在上面给物品定价，定了价的物品才能上架。</span>') + "</div></div>";
      };
      const unpriced = p.items.length - p.items.filter((it) => priced(it.id)).length;
      return sectionHead("经济", intro, '<button class="btn text small danger" data-act="eco-off" type="button">关闭经济</button>') +
        '<div class="ed-grid4">' + text("pack.economy.currency", "货币名", { limit: 8, placeholder: "例如：铜轮" }) +
        ECO_INTS.map(([k, label, lo, hi]) => num("pack.economy." + k, label, 'min="' + lo + '" max="' + hi + '" placeholder="' + ({ sell: 50, storyLimit: 20 }[k] ?? 0) + '"')).join("") + "</div>" +
        '<p class="hint">工钱在每次换幕时发给每位角色；“单段正文得失上限”限制模型一段正文里最多给或扣多少；回收比例是玩家把东西卖回店里时按售价打几折；精雕玩家可以放弃装备包换这笔钱。出身带的钱在“建卡”一步的出身卡片里填。</p>' +
        toggle("pack.economy.autoOutfit", "进入有店的地点时自动开始整备（不勾时由主持人发起）") +
        '<hr class="rule" />' + sectionHead("价格", "留空表示这件物品不出售。已定价 " + (p.items.length - unpriced) + " / " + p.items.length + " 件。") +
        (p.items.length ? '<div class="eco-prices">' + p.items.map(priceRow).join("") + "</div>" : '<p class="hint">还没有物品，先在“技能与物品”一步添加。</p>') +
        '<hr class="rule" />' + sectionHead("商店", "玩家只能在店所在的地点买它上架的东西；不绑地点的店随处可买。最多 12 家。",
          (e.shops || []).length < 12 ? '<button class="btn small" data-act="eco-add-shop" type="button">添加商店</button>' : "") +
        ((e.shops || []).length ? '<div class="ed-cards">' + e.shops.map(shopCard).join("") + "</div>" : '<p class="hint">还没有商店。没有商店时玩家只能互相转交，钱只在故事里得失。</p>');
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
      const core = pr.edition === "core";
      return (core ? '<div class="notice" style="margin-bottom:16px">这是核心版世界卡：写好第一幕就够了，后面的幕由主持人即兴开启，结局也可以留空。</div>' : "") +
        sectionHead("幕", "幕是故事的大段落，团桌页会按幕显示进度，主持人可以用 /团 主持 换幕 推进。", '<button class="btn small" data-act="add-act" type="button">添加一幕</button>') +
        '<div class="panel soft" style="margin-bottom:16px" data-live="act-track"></div>' +
        pr.acts.map((a, i) => '<div class="ed-act"><span class="opt-num">' + (i + 1) + '</span><div class="ed-act-body"><input class="input strong" data-bind="presentation.acts.' + i + '.title" value="' + esc(a.title) + '" placeholder="幕名" />' +
          '<input class="input" data-bind="presentation.acts.' + i + '.lead" value="' + esc(a.lead || "") + '" placeholder="引子：进入这一幕时的一句话" /></div><div class="ed-act-tools">' +
          '<button class="btn text small" type="button" data-act="move-act" data-i="' + i + '" data-v="-1"' + (i ? "" : " disabled") + ">上移</button>" +
          '<button class="btn text small" type="button" data-act="move-act" data-i="' + i + '" data-v="1"' + (i < pr.acts.length - 1 ? "" : " disabled") + ">下移</button>" + del("del-act", i) + "</div></div>").join("") +
        '<hr class="rule" />' + sectionHead("结局", "列出可能的结局和达成条件；模型会参考它们，玩家用 /团 结局 查看。", '<button class="btn small" data-act="add-ending" type="button">添加结局</button>') +
        pr.endings.map((e, i) => '<div class="ed-act"><span class="opt-num">' + String.fromCharCode(65 + (i % 26)) + '</span><div class="ed-act-body"><input class="input strong" data-bind="presentation.endings.' + i + '.name" value="' + esc(e.name) + '" placeholder="结局名" />' +
          '<input class="input" data-bind="presentation.endings.' + i + '.rule" value="' + esc(e.rule || "") + '" placeholder="达成条件" /></div><div class="ed-act-tools">' + del("del-ending", i) + "</div></div>").join("");
    },

    pacing() {
      const v = paceView(), p = paceOf(), pr = draft.presentation;
      const field = (key, label, lo, hi, ph, hint) => '<label class="field"><span class="label">' + label + '</span><input class="input num" type="number" data-type="int" data-bind="pack.pacing.' + key +
        '" min="' + lo + '" max="' + hi + '" value="' + esc(p[key] ?? "") + '" placeholder="' + ph + '" /><span class="hint">' + hint + "</span></label>";
      const actRows = (pr.edition === "core" ? [] : pr.acts).map((a, i) => '<div class="eco-price"><span class="opt-num">' + (i + 1) + '</span><span class="strong" style="flex:1">' + esc(a.title || "第 " + (i + 1) + " 幕") + "</span>" +
        '<input class="input num" type="number" min="1" max="100" data-type="int" data-bind="pace-act" data-i="' + (i + 1) + '" value="' + esc(p.acts?.[String(i + 1)] ?? "") + '" placeholder="' + v.act + '" /><span class="hint">轮</span></div>').join("");
      return sectionHead("节奏", "按轮计：在座的人各行动一次算一轮。所有世界默认开启，不填就用括号里的默认值；填 0 表示这一层不催。") +
        '<div class="panel soft" style="margin-bottom:18px" data-live="pace-plan"></div>' +
        '<div class="ed-grid4">' +
        field("sceneRounds", "场景轮数", 0, 50, 4, "满了以后正文必须让局面变化") +
        field("actRounds", "每幕轮数", 0, 100, 8, "满了以后提议换幕") +
        field("graceRounds", "宽限轮数", 1, 10, 2, "提醒之后再过几轮自动推进") +
        "</div>" +
        '<div class="ed-grid4" style="margin-top:16px">' +
        field("targetRounds", "全程目标", 0, 1000, v.autoTarget, "满了以后提议收尾") +
        field("hardRounds", "全程上限", 0, 1000, v.autoHard, "到了必定进入收尾") + "</div>" +
        '<label class="row" style="gap:10px;margin:6px 0 4px"><span class="switch"><input type="checkbox" data-pace-ending' + (v.ending ? " checked" : "") + ' /><span></span></span>' +
        '<span class="label" style="margin:0">允许发起收尾提议：到目标轮数、最后一幕走满或全员倒下时，问大家要不要收尾</span></label>' +
        '<p class="hint">关掉后只在玩家选了“收束”选项、或主持人发送 /团 主持 收尾 时收尾；全程上限仍然生效。</p>' +
        (actRows ? '<hr class="rule" />' + sectionHead("每一幕单独设置", "长的一幕可以多给几轮；留空跟随“每幕轮数”。") + '<div class="eco-prices">' + actRows + "</div>"
          : '<p class="hint" style="margin-top:12px">' + (pr.edition === "core" ? "核心版只写第一幕，后面的幕由故事即兴展开，按三幕估算全程。" : "还没有幕。在“幕与结局”里添加幕后可以单独设置每一幕的轮数。") + "</p>");
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
    meta: () => '<span class="num">' + esc(pack().id) + "</span><span>" + tier(draft.presentation.edition, pack().revision) + (isNew ? "（新建）" : "") + "</span>" +
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
    scale: () => dcScale(pack().rules),
    "cre-flow": () => {
      const p = pack(), modes = createModes(), move = createMove(), swap = createSwap();
      const origins = (creOf().origins || []).length || fallbackOrigins().length, kits = (creOf().kits || []).length;
      const traits = creOf().traits || [], details = creOf().details || [];
      const flow = (mode) => ["职业", "名字", ...(move ? ["属性 ±" + move] : []), ...(mode === "forge" ? ["技能任选"] : swap ? ["换 " + swap + " 项技能"] : []),
        ...(traits.some((t) => (t.modes || ["forge"]).includes(mode)) ? ["特质"] : []), ...(origins ? ["出身"] : []), ...(mode === "forge" && kits ? ["装备包"] : p.items.length ? ["多带一件"] : []),
        ...details.filter((d) => (d.modes || ["forge"]).includes(mode)).map((d) => d.name.trim() || "人物细节"),
        ...(mode === "custom" ? ["背景 1 问"] : ["背景 " + ((creOf().questions || []).filter((q) => q.trim()).length || 3) + " 问", ...(creOf().relation === false ? [] : ["开局关系"])])];
      const rows = CREATE_MODES.filter(([k]) => k !== "quick" && modes.includes(k)).map(([k, label]) => {
        const list = flow(k);
        return '<div class="cre-flow"><b>' + label + '</b><span class="faint">' + list.length + ' 步</span><div class="cre-steps">' + list.map((s) => "<span>" + esc(s) + "</span>").join("<i>→</i>") + "</div></div>";
      });
      return rows.length ? '<div class="label" style="margin-bottom:6px">玩家会走的步骤</div>' + rows.join("") : '<p class="hint">只开放快选：玩家选职业、起名字就入座。</p>';
    },
    "cre-reach": () => {
      const p = pack(), move = createMove();
      if (!p.archetypes.length) return '<span class="hint">先添加职业。</span>';
      if (!move) return '<span class="hint">挪点为 0：属性完全按职业来，定制和精雕跳过“调整属性”这一步。</span>';
      const arch = p.archetypes[Math.min(reachArch, p.archetypes.length - 1)];
      return '<div class="row between"><span class="label" style="margin:0">挪满 ' + move + ' 点时各属性能到的范围</span><span class="hint">圆点是职业原值</span></div>' +
        '<div class="chips" style="margin:10px 0 12px">' + p.archetypes.map((a, i) => '<button type="button" class="chip small' + (a === arch ? " on" : "") + '" data-act="cre-reach" data-i="' + i + '">' + esc(a.name || "未命名") + "</button>").join("") + "</div>" +
        '<div class="reach">' + p.attributes.map((at) => {
          const v = arch.attributes[at.id] ?? at.min, lo = Math.max(at.min, v - move), hi = Math.min(at.max, v + move), span = Math.max(1, at.max - at.min);
          const pos = (x) => ((x - at.min) / span) * 100;
          return '<div class="reach-row"><span>' + esc(at.name || at.id) + '</span><span class="reach-track"><i style="left:' + pos(lo) + "%;right:" + (100 - pos(hi)) + '%"></i><b style="left:' + pos(v) + '%"></b></span>' +
            '<span class="num">' + (lo === hi ? v : lo + "–" + hi) + '</span><span class="faint num">' + at.min + "–" + at.max + "</span></div>";
        }).join("") + "</div>";
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
    "pace-plan": () => {
      const v = paceView();
      const segs = Array.from({ length: v.count }, (_, i) => ({ n: i + 1, r: v.act ? v.per(i + 1) : 0, title: (draft.presentation.acts[i] || {}).title || "" }));
      const total = Math.max(v.hard || 0, v.target || 0, segs.reduce((s, x) => s + x.r, 0), 1);
      const bar = segs.map((x) => '<span class="pace-seg" style="flex:' + Math.max(x.r, 0.0001) + '" title="' + esc(x.title) + '"><b>' + (draft.presentation.edition === "core" && x.n > 1 ? "即兴" : "第 " + x.n + " 幕") + "</b><em>" + (x.r ? x.r + " 轮" : "不催") + "</em></span>").join("") +
        (v.hard > segs.reduce((s, x) => s + x.r, 0) ? '<span class="pace-seg grace" style="flex:' + (v.hard - segs.reduce((s, x) => s + x.r, 0)) + '"><b>收尾余量</b><em>' + (v.hard - segs.reduce((s, x) => s + x.r, 0)) + " 轮</em></span>" : "");
      const mark = (at, label) => at ? '<i class="pace-mark' + (at / total > 0.8 ? " end" : "") + '" style="left:' + ((at / total) * 100).toFixed(1) + '%"><span>' + label + " " + at + "</span></i>" : "";
      return '<div class="pace-plan"><div class="pace-segs">' + bar + "</div>" + mark(v.target, "提议收尾") + mark(v.hard, "必定收尾") + "</div>" +
        '<div class="hint" style="margin-top:28px">一个场景约 ' + (v.scene || "不限") + (v.scene ? " 轮，满了以后正文让局面变化，再过 " + v.grace + " 轮世界自己推进" : "") + "；" +
        (v.target ? "全程约 " + v.target + " 轮，按每轮 4 人、每人 1 分钟算大约 " + Math.round((v.target * 4) / 60 * 10) / 10 + " 小时。" : "不设篇幅。") + "</div>";
    },
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
    if (kind === "trait") {
      const t = (creOf().traits || [])[a];
      if (!t) return "";
      return '<span class="label">玩家看到</span><b>' + esc(t.name.trim() || "未命名特质") + '</b><span class="cre-side up">利 ' + esc(traitEffect(t.up, p.attributes, 1)) +
        '</span><span class="cre-side dn">弊 ' + esc(traitEffect(t.down, p.attributes, -1)) + "</span>";
    }
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
      return meter("开局", x.initial, x.max, Number(a));
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
    const url = "#/worlds/" + (isNew ? "new?" + (from ? "from=" + encodeURIComponent(from) + "&" : tavern ? "tavern=1&" : "") : encodeURIComponent(id) + "/edit?") + "step=" + STEPS[step][0];
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
    if (path === "kit-count") { cre().kits[Number(el.dataset.i)].items[el.dataset.v] = value; return; }
    if (path === "pace-act") {
      const acts = ((draft.pack.pacing ||= {}).acts ||= {});
      if (value == null || Number.isNaN(value)) delete acts[el.dataset.i]; else acts[el.dataset.i] = value;
      return;
    }
    if (path.startsWith("pack.pacing.")) draft.pack.pacing ||= {};
    if (path === "eco-price") {
      const prices = (eco().prices ||= {}), id = pack().items[Number(el.dataset.i)].id;
      if (value == null) delete prices[id]; else prices[id] = value;
      return;
    }
    if (path.startsWith("pack.creation.")) {
      cre();
      if (path.startsWith("pack.creation.questions.")) { const q = draft.pack.creation.questions || []; draft.pack.creation.questions = [0, 1, 2].map((i) => q[i] || ""); }
    }
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
    if (e.target.matches("[data-pace-ending]")) {
      const pc = (draft.pack.pacing ||= {});
      if (e.target.checked) delete pc.endingPrompt; else pc.endingPrompt = false;
      changed();
      return renderStep();
    }
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
    edition: (_, v) => { if (v === "core") draft.presentation.edition = "core"; else delete draft.presentation.edition; },
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
      for (const t of p.creation?.traits || []) for (const k of ["up", "down"]) if (t[k].attribute === at.id) delete t[k].attribute;
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
    "del-items": (i) => {
      const [x] = pack().items.splice(i, 1), cv = pack().creation;
      if (!cv) return;
      (cv.origins || []).forEach((o) => { if (o.item === x.id) o.item = ""; });
      (cv.kits || []).forEach((k) => { delete k.items[x.id]; });
    },
    "add-arch": () => {
      const p = pack(), a = { id: newId("archetype", p.archetypes), name: "", text: "", attributes: {}, skills: [] };
      p.attributes.forEach((at) => { a.attributes[at.id] = at.min; });
      fit(a);
      p.archetypes.push(a);
    },
    "dup-arch": (i) => { const p = pack(), a = clone(p.archetypes[i]); a.id = newId("archetype", p.archetypes); a.name = (a.name || "职业") + "（副本）"; p.archetypes.splice(i + 1, 0, a); },
    "del-arch": (i) => { pack().archetypes.splice(i, 1); },
    "fit-arch": (i) => { fit(pack().archetypes[i]); },
    "cre-mode": (_, v) => {
      const on = new Set(createModes());
      if (on.has(v)) on.delete(v); else on.add(v);
      cre().modes = CREATE_MODES.map(([k]) => k).filter((k) => k === "quick" || on.has(k));
    },
    "cre-reset": () => { delete pack().creation; },
    "eco-on": () => { pack().economy = { currency: "", initial: 0, prices: {}, shops: [] }; },
    "eco-off": () => { delete pack().economy; (pack().creation?.origins || []).forEach((o) => { delete o.money; }); },
    "eco-add-shop": () => { const e = eco(); e.shops = [...(e.shops || []), { id: newId("shop", e.shops || []), name: "", kind: "", place: "", items: [], text: "" }]; },
    "eco-del-shop": (i) => { eco().shops.splice(i, 1); },
    "eco-ware": (i, v) => { const s = eco().shops[i], has = s.items.includes(v); s.items = has ? s.items.filter((x) => x !== v) : [...s.items, v]; },
    "cre-reach": (i) => { reachArch = i; },
    "cre-relation": () => { const c = cre(); if (c.relation === false) delete c.relation; else c.relation = false; },
    "add-origin": () => { cre().origins = [...(creOf().origins || []), { name: "", text: "", item: "" }]; },
    "del-origin": (i) => { cre().origins.splice(i, 1); },
    "add-kit": () => { cre().kits = [...(creOf().kits || []), { name: "", text: "", items: {} }]; },
    "del-kit": (i) => { cre().kits.splice(i, 1); },
    "kit-item": (i, v) => { const items = cre().kits[i].items; if (items[v]) delete items[v]; else items[v] = 1; },
    "add-detail": () => { cre().details = [...(creOf().details || []), { name: "", text: "", options: [], modes: ["forge"] }]; },
    "del-detail": (i) => { cre().details.splice(i, 1); },
    "detail-mode": (i, v) => {
      const d = cre().details[i], on = new Set(d.modes || ["forge"]);
      if (on.has(v)) on.delete(v); else on.add(v);
      if (!on.size) { ctx.toast("人物细节至少要出现在定制或精雕里", "error"); return; }
      d.modes = DETAIL_MODES.map(([k]) => k).filter((k) => on.has(k));
    },
    "detail-free": (i) => { const d = cre().details[i]; d.free = d.free === false; },
    "add-detail-opt": (i) => { const d = cre().details[i]; d.options = [...(d.options || []), { name: "", text: "" }]; },
    "del-detail-opt": (i, v) => { const d = cre().details[i]; d.options.splice(Number(v), 1); if (!d.options.length) delete d.free; },
    "add-trait": () => { cre().traits = [...(creOf().traits || []), { name: "", text: "", modes: ["forge"], up: { when: "hard", value: 1 }, down: { when: "easy", value: 1 } }]; },
    "del-trait": (i) => { cre().traits.splice(i, 1); },
    "trait-mode": (i, v) => {
      const t = cre().traits[i], on = new Set(t.modes || ["forge"]);
      if (on.has(v)) on.delete(v); else on.add(v);
      if (!on.size) { ctx.toast("特质至少要出现在定制或精雕里", "error"); return; }
      t.modes = DETAIL_MODES.map(([k]) => k).filter((k) => on.has(k));
    },
    "trait-value": (i, v) => { const [k, n] = v.split(":"); cre().traits[i][k].value = Number(n); },
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
    restore: () => { draft = withNarration(pendingDraft.draft); pendingDraft = null; },
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
    const pc = draft.pack.pacing;
    if (pc) {
      for (const k of ["sceneRounds", "actRounds", "graceRounds", "targetRounds", "hardRounds"]) if (pc[k] == null || Number.isNaN(pc[k])) delete pc[k];
      if (pc.endingPrompt !== false) delete pc.endingPrompt;
      const n = draft.presentation.edition === "core" ? 0 : draft.presentation.acts.length;
      pc.acts = Object.fromEntries(Object.entries(pc.acts || {}).filter(([k, v]) => v != null && !Number.isNaN(v) && Number(k) <= n));
      if (!Object.keys(pc.acts).length) delete pc.acts;
      if (!Object.keys(pc).length) delete draft.pack.pacing;
    }
    const e = draft.pack.economy;
    if (e) {
      const items = new Set(draft.pack.items.map((x) => x.id));
      e.currency = (e.currency || "").trim();
      for (const [k] of ECO_INTS) if (e[k] == null || Number.isNaN(e[k])) delete e[k];
      if (!e.autoOutfit) delete e.autoOutfit;
      e.prices = Object.fromEntries(Object.entries(e.prices || {}).filter(([k, v]) => items.has(k) && v != null));
      (e.shops || []).forEach((s) => {
        s.name = (s.name || "").trim();
        s.items = (s.items || []).filter((x) => items.has(x));
        for (const k of ["kind", "place", "text"]) if (!(s[k] || "").trim()) delete s[k];
      });
    }
    const cv = draft.pack.creation;
    if (!cv) return;
    if (cv.questions) cv.questions = cv.questions.map((q) => q.trim()).filter(Boolean);
    (cv.origins || []).forEach((o) => { o.name = o.name.trim(); if (!o.item) delete o.item; if (!o.text) delete o.text; if (o.money == null || !e) delete o.money; });
    (cv.kits || []).forEach((k) => { k.name = k.name.trim(); if (!k.text) delete k.text; });
    (cv.details || []).forEach((d) => {
      d.name = d.name.trim();
      if (!d.text) delete d.text;
      d.options = (d.options || []).filter((o) => o.name.trim() || (o.text || "").trim()).map((o) => ({ name: o.name.trim(), ...(o.text?.trim() ? { text: o.text.trim() } : {}) }));
      if (!d.options.length) { delete d.options; delete d.free; } else if (d.free !== false) delete d.free;
    });
    (cv.traits || []).forEach((t) => {
      t.name = t.name.trim();
      if (!t.text) delete t.text;
      for (const k of ["up", "down"]) { if (!t[k].attribute) delete t[k].attribute; if (!t[k].when || t[k].when === "any") delete t[k].when; }
    });
    for (const key of ["questions", "origins", "kits", "details", "traits"]) if (cv[key] && !cv[key].length) delete cv[key];
    if (!Object.keys(cv).length) delete draft.pack.creation;
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
      const result = await busy(button, () => ctx.api.post("worlds/save", { pack: draft.pack, presentation: draft.presentation, narration: draft.narration, create: isNew }));
      saved = JSON.stringify(draft);
      persisted = true;
      try { localStorage.removeItem(key); } catch { /* ignore */ }
      ctx.toast("已保存「" + shortTitle(draft.pack.title) + "」" + (result.label || tier(null, result.revision)));
      ctx.go("worlds/" + encodeURIComponent(result.id));
    } catch (error) {
      serverCheck = { error: error.message };
      ctx.toast(error.message, "error");
      if (step !== STEPS.length - 1) ACTIONS.goto(STEPS.length - 1); else updateLive();
    }
  }

  function exportFile() {
    normalise();
    const blob = new Blob([JSON.stringify({ format: source.bundle_format, pack: draft.pack, presentation: draft.presentation,
      extensions: narrationExtensions(draft.narration) }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = draft.pack.id + ".world.json";
    a.click();
    ctx.toast("已导出 " + a.download + (dirty() ? "（包含未保存的修改）" : ""));
  }

  root.addEventListener("click", (e) => {
    const pick = e.target.closest(".notch [data-field]");
    if (pick && !pick.disabled) {
      draft.narration[pick.dataset.field] = pick.dataset.value;
      changed();
      return renderStep();
    }
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

