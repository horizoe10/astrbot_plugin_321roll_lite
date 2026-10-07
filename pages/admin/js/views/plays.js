import { dot, esc, figure, hero, icon, roundIcon, section } from "../ui.js";

const GROUPS = [
  ["回合与协作", "每桌都会用到的基础玩法", ["playActions", "playCollaboration"]],
  ["调查与社交", "找线索、对证词、谈条件、拉关系", ["playInvestigation", "playTestimony", "playNegotiation", "playRelations"]],
  ["时间与经营", "让世界时间流动，推进长期目标", ["playCalendar", "playProjects"]],
  ["对抗", "一对一或多人的较量", ["playConflict", "playChase", "playDebate"]],
  ["计划与命运", "规划、求签、问神谕，改变角色与结局", ["playPlans", "playOracle", "playFortune", "playTransformation", "playBranchEndings"]],
];
const ICONS = { playActions: "feather", playCollaboration: "vote", playInvestigation: "search", playTestimony: "quote", playNegotiation: "scroll", playRelations: "users",
  playCalendar: "clock", playProjects: "grid", playConflict: "bolt", playChase: "activity", playDebate: "message", playPlans: "map", playOracle: "eye",
  playFortune: "dice", playTransformation: "wand", playBranchEndings: "flag" };
const NOTE = { deferred: "本期不开放", removed: "由世界物品与资源承担" };

export async function render(root, ctx) {
  const umo = ctx.route.params.umo || "";
  const data = await ctx.api.get("features", umo ? { umo } : {});
  const by = Object.fromEntries(data.plays.map((p) => [p.key, p]));
  const active = data.plays.filter((p) => p.status === "active");
  const other = data.plays.filter((p) => p.status !== "active");
  const on = active.filter((p) => p.effective).length;
  const used = active.reduce((s, p) => s + p.count, 0);
  const scope = data.groups.find((g) => g.umo === umo);
  const row = (p) => {
    const value = umo ? (p.override ?? p.global) : p.global;
    const meta = [p.depends.length ? "依赖 " + p.depends.map((d) => by[d].label).join("、") : "", umo ? (p.override === null ? "跟随全局" : "本群单独设置") : ""].filter(Boolean);
    return '<div class="ri">' + roundIcon(ICONS[p.key] || "layers", p.effective ? "" : "mute") + '<div style="min-width:0"><div class="ri-title">' + esc(p.label) +
      (p.count ? '　<span class="gold serif" style="font-weight:400">' + p.count + '</span><span class="faint" style="font-weight:400;font-size:12px"> 次 · 近 30 天</span>' : "") +
      '</div><div class="ri-meta"><span>' + esc(p.note) + '</span><span class="kbd">' + esc(p.usage) + "</span>" + meta.map((m) => "<span>" + esc(m) + "</span>").join("") + "</div></div>" +
      '<div class="ri-side">' + (umo && p.override !== null ? '<button class="btn text small" data-reset="' + esc(p.key) + '">恢复跟随</button>' : "") +
      (p.effective === value ? "" : dot("warn", "依赖未开")) +
      '<span class="switch"><input type="checkbox" data-key="' + esc(p.key) + '" ' + (value ? "checked" : "") + ' aria-label="' + esc(p.label) + '" /><span></span></span></div></div>';
  };
  root.innerHTML = hero({
    eyebrow: "玩法 · PLAYS", title: "玩法",
    lead: "关闭一项玩法只停止新的受理，已经开始的记录按原阶段收尾。单群设置优先于全局默认。",
    figures: '<div class="figures">' + figure(on + "/" + active.length, scope ? "本群生效" : "已开启") + figure(used, "近 30 天使用", "plain") + "</div>",
  }) +
    '<div class="row wrap" style="gap:14px;margin-bottom:8px"><span class="label">设置范围</span><select class="select" id="scope" style="width:320px;border-radius:999px">' +
    '<option value="">全局默认</option>' + data.groups.map((g) => '<option value="' + esc(g.umo) + '"' + (g.umo === umo ? " selected" : "") + ">群 " + esc(g.group_id) + " · " +
    esc(g.title.split(" · ")[0]) + "</option>").join("") + "</select>" + (scope ? '<span class="hint">正在设置群 ' + esc(scope.group_id) + " 的单独开关</span>" : "") + "</div>" +
    GROUPS.map(([title, meta, keys]) => '<section class="sec">' + section(title, { count: keys.filter((k) => by[k]?.effective).length + "/" + keys.length, meta }) +
      '<div class="rows">' + keys.filter((k) => by[k]).map((k) => row(by[k])).join("") + "</div></section>").join("") +
    (other.length ? '<section class="sec">' + section("暂缓与删除", { meta: "Lite 本期不提供，开关不可用" }) + '<div class="rows">' + other.map((p) =>
      '<div class="ri">' + roundIcon("eyeOff", "mute") + '<div><div class="ri-title muted">' + esc(p.label) + '</div><div class="ri-meta">' + esc(NOTE[p.status] || "") + "</div></div>" + dot("off", "不可开启") + "</div>").join("") + "</div></section>" : "");
  root.querySelector("#scope").addEventListener("change", (e) => ctx.go("plays" + (e.target.value ? "?umo=" + encodeURIComponent(e.target.value) : "")));
  root.querySelectorAll("[data-key]").forEach((input) => input.addEventListener("change", async () => {
    input.disabled = true;
    try {
      await ctx.api.post("features/set", { key: input.dataset.key, umo, value: input.checked });
      ctx.toast((input.checked ? "已开启 " : "已关闭 ") + by[input.dataset.key].label);
      ctx.refresh();
    } catch (error) {
      input.checked = !input.checked;
      input.disabled = false;
      ctx.toast(error.message, "error");
    }
  }));
  root.querySelectorAll("[data-reset]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await ctx.api.post("features/set", { key: b.dataset.reset, umo, value: null });
      ctx.refresh();
    } catch (error) { ctx.toast(error.message, "error"); }
  }));
}

