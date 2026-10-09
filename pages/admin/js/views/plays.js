import { PLAY_GROUPS, dot, esc, figure, hero, icon, roundIcon, section, shares } from "../ui.js";

const ICONS = { playActions: "feather", playCollaboration: "vote", playInvestigation: "search", playTestimony: "quote", playNegotiation: "scroll", playRelations: "users",
  playCalendar: "clock", playProjects: "grid", playConflict: "bolt", playChase: "activity", playDebate: "message", playPlans: "map", playOracle: "eye",
  playFortune: "dice", playTransformation: "wand", playBranchEndings: "flag",
  funDaily: "sun", funDice: "dice", funReport: "heart", funSchedule: "hourglass", funRelay: "pen", funLuck: "activity", funQuotes: "quote", funSoup: "message" };
const NOTE = { deferred: "本期不开放", removed: "由世界物品与资源承担" };

export async function render(root, ctx) {
  const umo = ctx.route.params.umo || "";
  const data = await ctx.api.get("features", umo ? { umo } : {});
  const by = Object.fromEntries(data.plays.map((p) => [p.key, p]));
  const active = data.plays.filter((p) => p.status === "active" && p.kind !== "fun");
  const other = data.plays.filter((p) => p.status !== "active");
  const on = active.filter((p) => p.effective).length;
  const used = active.reduce((s, p) => s + p.count, 0);
  const scope = data.groups.find((g) => g.umo === umo);
  const peak = Math.max(1, ...data.plays.map((p) => p.count));
  const valueOf = (p) => (umo ? (p.override ?? p.global) : p.global);
  const row = (p, tone) => {
    const value = valueOf(p);
    const meta = [p.depends.length ? "依赖 " + p.depends.map((d) => by[d].label).join("、") : "", umo ? (p.override === null ? "跟随全局" : "本群单独设置") : ""].filter(Boolean);
    return '<div class="ri play-row' + (p.effective ? "" : " is-off") + '">' + roundIcon(ICONS[p.key] || "layers", p.effective ? "" : "mute") + '<div style="min-width:0"><div class="ri-title">' + esc(p.label) +
      '</div><div class="ri-meta"><span>' + esc(p.note) + '</span><span class="kbd">' + esc(p.usage) + "</span>" + meta.map((m) => "<span>" + esc(m) + "</span>").join("") + "</div></div>" +
      '<div class="ri-side"><span class="use-mini' + (p.count ? "" : " zero") + '" title="近 30 天 ' + p.count + ' 次"><i class="' + tone + '"><span style="width:' + ((p.count / peak) * 100).toFixed(0) +
        '%"></span></i><b class="num">' + (p.count || "未用") + "</b></span>" +
      (p.key === "funRelay" && !umo ? '<label class="row" style="gap:8px;font-size:12.5px;color:var(--muted)">每群每天 AI 收尾' +
        '<input class="input num" type="number" min="0" max="' + data.relay_max + '" value="' + data.relay_limit + '" data-relay-limit style="width:64px;height:30px;padding:0 8px" />次</label>' : "") +
      (p.key === "funSoup" && !umo ? '<label class="row" style="gap:8px;font-size:12.5px;color:var(--muted)">每群每天' +
        '<input class="input num" type="number" min="0" max="' + data.soup_max + '" value="' + data.soup_limit + '" data-soup-limit style="width:64px;height:30px;padding:0 8px" />碗</label>' : "") +
      (umo && p.override !== null ? '<button class="btn text small" data-reset="' + esc(p.key) + '">恢复跟随</button>' : "") +
      (p.effective === value ? "" : dot("warn", "依赖未开")) +
      '<span class="switch"><input type="checkbox" data-key="' + esc(p.key) + '" ' + (value ? "checked" : "") + ' aria-label="' + esc(p.label) + '" /><span></span></span></div></div>';
  };
  root.innerHTML = hero({
    eyebrow: "玩法 · PLAYS", title: "玩法",
    lead: "关闭一项玩法只停止新的受理，已经开始的记录按原阶段收尾。单群设置优先于全局默认。",
    figures: '<div class="figures">' + figure(on + "/" + active.length, scope ? "本群生效" : "已开启") + figure(used, "近 30 天使用", "plain") + "</div>",
  }) +
    '<div class="play-dist"><div class="label">近 30 天各类玩法的使用占比</div>' +
      shares(PLAY_GROUPS.map(([label, , keys, tone]) => ({ label, tone, value: keys.reduce((s, k) => s + (by[k]?.count || 0), 0) }))) + "</div>" +
    '<div class="row wrap" style="gap:14px;margin-bottom:8px"><span class="label">设置范围</span><select class="select" id="scope" style="width:320px;border-radius:999px">' +
    '<option value="">全局默认</option>' + data.groups.map((g) => '<option value="' + esc(g.umo) + '"' + (g.umo === umo ? " selected" : "") + ">群 " + esc(g.group_id) + " · " +
    esc(g.title.split(" · ")[0]) + "</option>").join("") + "</select>" + (scope ? '<span class="hint">正在设置群 ' + esc(scope.group_id) + " 的单独开关</span>" : "") + "</div>" +
    PLAY_GROUPS.map(([title, meta, keys, tone]) => '<section class="sec">' + section(title, { count: keys.filter((k) => by[k]?.effective).length + "/" + keys.length, meta }) +
      '<div class="rows">' + keys.filter((k) => by[k]).map((k) => row(by[k], tone)).join("") + "</div></section>").join("") +
    (other.length ? '<section class="sec">' + section("暂缓与删除", { meta: "Lite 本期不提供，开关不可用" }) + '<div class="rows">' + other.map((p) =>
      '<div class="ri">' + roundIcon("eyeOff", "mute") + '<div><div class="ri-title muted">' + esc(p.label) + '</div><div class="ri-meta">' + esc(NOTE[p.status] || "") + "</div></div>" + dot("off", "不可开启") + "</div>").join("") + "</div></section>" : "");
  root.querySelector("#scope").addEventListener("change", (e) => ctx.go("plays" + (e.target.value ? "?umo=" + encodeURIComponent(e.target.value) : "")));
  root.querySelectorAll("[data-key]").forEach((input) => input.addEventListener("change", async () => {
    // Plays that lean on this one stop with it; say so before turning it off.
    const leaning = input.checked ? [] : data.plays.filter((p) => p.depends.includes(input.dataset.key) && valueOf(p));
    if (leaning.length && !window.confirm("关闭「" + by[input.dataset.key].label + "」后，依赖它的 " + leaning.map((p) => "「" + p.label + "」").join("") + " 也会一起停用。继续吗？")) {
      input.checked = true;
      return;
    }
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
  const limit = root.querySelector("[data-relay-limit]");
  if (limit) limit.addEventListener("change", async () => {
    try {
      await ctx.api.post("features/set", { relay_limit: Number(limit.value) });
      ctx.toast(Number(limit.value) ? "接龙每群每天最多 AI 收尾 " + Number(limit.value) + " 次" : "已关闭接龙的 AI 收尾");
    } catch (error) {
      limit.value = data.relay_limit;
      ctx.toast(error.message, "error");
    }
  });
  const soupLimit = root.querySelector("[data-soup-limit]");
  if (soupLimit) soupLimit.addEventListener("change", async () => {
    try {
      await ctx.api.post("features/set", { soup_limit: Number(soupLimit.value) });
      ctx.toast(Number(soupLimit.value) ? "海龟汤每群每天最多 " + Number(soupLimit.value) + " 碗" : "已关闭海龟汤的 AI 出题");
    } catch (error) {
      soupLimit.value = data.soup_limit;
      ctx.toast(error.message, "error");
    }
  });
}

