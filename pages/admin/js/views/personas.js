// 人设卡: players' own characters (words only), grouped by owner; the right panel views, edits or imports one.
import { avatar, busy, empty, esc, figure, hero, icon, section, when } from "../ui.js";

const FLOW = [
  ["upload", "建卡", "玩家私聊 <code>/团 人设 导入</code> 发送酒馆角色卡，或 <code>/团 人设 新建 名字</code> 按模板手写；后台也能代建"],
  ["sparkle", "摘要", "设定超过 300 字时，AI 整理成一段摘要，主持故事的 AI 每轮只读这段"],
  ["users", "入座", "选职业时写人设名 <code>/团 选职业 序号 名字</code>，或 <code>/团 人设 使用 名字</code>"],
  ["globe", "融入", "<code>/团 人设 融入</code> 让 AI 写一句这个人在本世界里的身份"],
];
const SOURCES = { card: "酒馆角色卡", manual: "群里手写", webui: "后台创建" };
const STATE = { lobby: "等人", running: "进行中", paused: "暂停" };

const pic = (p, size = "big") => p.avatar
  ? '<span class="avatar ' + size + ' photo"><img src="' + esc(p.avatar) + '" alt="" /></span>'
  : avatar(p.name, size);
const ownerKey = (o) => o.platform + "\u0001" + o.user_id;

function summaryState(p, limit) {
  if (p.data.summary) return p.data.summary_by === "ai" ? ["gold", "AI 摘要"] : ["", "手写摘要"];
  return p.long ? ["warn", "待整理 · 只读前 " + limit + " 字"] : ["", "短卡 · 全文交给 AI"];
}

// Length of the card against the summary limit: the tick marks where the hosting model stops reading.
function lengthBar(chars, limit) {
  const top = Math.max(limit * 4, chars);
  const share = Math.min(1, chars / top), mark = limit / top;
  return '<div class="plen' + (chars > limit ? " over" : "") + '" title="设定共 ' + chars + " 字，AI 每轮读 " + limit + ' 字以内"><div class="plen-bar"><span style="width:' + (share * 100).toFixed(1) +
    '%"></span><i style="left:' + (mark * 100).toFixed(1) + '%"></i></div><small class="num">' + chars + " 字</small></div>";
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("文件读取失败"));
    reader.readAsDataURL(file);
  });
}

export async function render(root, ctx) {
  let data = await ctx.api.get("personas");
  let selected = ctx.route.params.id || data.personas[0]?.id || null;
  let mode = data.personas.length ? "view" : "intro";
  const limit = data.limits.summary;

  root.innerHTML = '<div class="pview"><div data-head></div>' +
    '<section class="sec">' + section("人设怎样进入故事", { meta: "只带文字：名字、外貌、性格、背景和说话方式。属性、技能和物品始终由世界的职业决定，桌上得到的东西也不会带走。" }) +
    '<ol class="pflow">' + FLOW.map(([ic, t, d], i) => '<li><span class="pflow-no">' + icon(ic, 18) + '</span><div><b><em class="num">0' + (i + 1) + "</em>" + t + "</b><p>" + d + "</p></div></li>").join("") + "</ol></section>" +
    '<section class="sec"><div class="pgrid"><div data-list></div><aside class="ppanel" data-panel></aside></div></section></div>';
  // Listeners live on this view's own element: #page is shared and would keep handlers of earlier visits.
  root = root.firstElementChild;
  const headEl = root.querySelector("[data-head]"), listEl = root.querySelector("[data-list]"), panel = root.querySelector("[data-panel]");

  const find = (id) => data.personas.find((p) => p.id === id);
  function drawHead() {
    const s = data.stats;
    headEl.innerHTML = hero({
      eyebrow: "人设 · PERSONAS", title: "人设卡",
      lead: "玩家自己的角色，可以带进任何一个世界。来自 SillyTavern 角色卡、群里的模板，或在这里代建；每人最多 " + data.limits.per_user + " 张。",
      figures: '<div class="figures">' + figure(s.total, "张人设卡") + figure(s.owners, "位玩家", "plain") + figure(s.in_use, "张在桌上", "plain") +
        figure(s.long, "张待整理", s.long ? "err" : "plain") + "</div>",
      actions: '<button class="btn" data-mode="import">' + icon("upload", 15) + "导入酒馆角色卡</button>" +
        '<button class="btn primary" data-mode="new">' + icon("plus", 15) + "新建人设</button>",
    });
  }

  function drawList() {
    if (!data.personas.length) {
      listEl.innerHTML = '<div class="card">' + empty("还没有人设卡", "玩家在私聊里导入或手写后，会按人出现在这里") + "</div>";
      return;
    }
    const groups = new Map();
    data.personas.forEach((p) => {
      const k = ownerKey(p);
      if (!groups.has(k)) groups.set(k, { owner: p, items: [] });
      groups.get(k).items.push(p);
    });
    listEl.innerHTML = [...groups.values()].map(({ owner, items }) =>
      '<div class="powner"><div class="powner-head">' + avatar(owner.user_name) + "<div><b>" + esc(owner.user_name || owner.user_id) + '</b><small class="num">' +
        esc(owner.platform) + " · " + esc(owner.user_id) + '</small></div><span class="pslots" title="已用 ' + items.length + " / " + data.limits.per_user + ' 张">' +
        Array.from({ length: data.limits.per_user }, (_, i) => '<i class="' + (i < items.length ? "on" : "") + '"></i>').join("") + "</span></div>" +
      items.map((p) => {
        const [tone, label] = summaryState(p, limit);
        return '<button type="button" class="prow' + (p.id === selected && mode !== "new" && mode !== "import" ? " on" : "") + '" data-pick="' + esc(p.id) + '">' + pic(p) +
          '<span class="prow-main"><span class="prow-name"><b>' + esc(p.name) + "</b>" + (p.data.tags || []).slice(0, 3).map((t) => '<span class="tag">' + esc(t) + "</span>").join("") + "</span>" +
          '<span class="prow-text">' + esc(p.text) + "</span>" + lengthBar(p.chars, limit) + "</span>" +
          '<span class="prow-side"><span class="tag ' + tone + '">' + esc(label) + "</span>" +
          (p.usage.length ? '<span class="prow-use">' + icon("dice", 13) + p.usage.length + " 桌</span>" : '<span class="prow-use none">未入座</span>') + "</span></button>";
      }).join("") + "</div>").join("");
  }

  // ------------------------------------------------------------ panel
  const ownerOptions = (value = "") => data.players.length
    ? data.players.map((o) => '<option value="' + esc(ownerKey(o)) + '"' + (ownerKey(o) === value ? " selected" : "") + ">" + esc(o.user_name || o.user_id) + "（" + esc(o.platform) + " · " + esc(o.user_id) + "）</option>").join("")
    : "";
  const ownerField = () => data.players.length
    ? '<label class="field"><span class="label">属于哪位玩家</span><select class="select" data-owner>' + ownerOptions() + '</select><span class="hint">只列出在团桌上出现过的玩家；人设卡归玩家所有，玩家在群里能看到和使用。</span></label>'
    : '<div class="notice">还没有玩家在团桌上出现过，后台无法代建。请让玩家私聊机器人发送 <code>/团 人设 导入</code> 或 <code>/团 人设 新建 名字</code>。</div>';
  const ownerOf = () => {
    const value = panel.querySelector("[data-owner]")?.value || "";
    const o = data.players.find((x) => ownerKey(x) === value);
    if (!o) throw new Error("请先选择这张人设卡属于哪位玩家");
    return { platform: o.platform, user_id: o.user_id, user_name: o.user_name };
  };
  const counter = (name, max) => '<span class="count num" data-count="' + name + '" data-max="' + max + '"></span>';

  function viewPanel(p) {
    const [tone, label] = summaryState(p, limit);
    const modelText = p.text || "";
    const share = Math.min(1, modelText.length / limit);
    return '<div class="ppanel-head">' + pic(p, "huge") + '<div><div class="eyebrow">' + esc(SOURCES[p.data.source] || "人设卡") + (p.data.creator ? " · 作者 " + esc(p.data.creator) : "") + "</div>" +
        '<h2 class="ppanel-title">' + esc(p.name) + '</h2><div class="chips">' + (p.data.tags || []).map((t) => '<span class="tag">' + esc(t) + "</span>").join("") +
        '<span class="faint" style="font-size:12px">' + esc(p.user_name) + " · 更新于 " + esc(when(p.updated_at)) + "</span></div></div></div>" +
      '<div class="pmodel"><div class="pmodel-head"><span class="label">主持 AI 每轮读到的文字</span><span class="tag ' + tone + '">' + esc(label) + "</span></div>" +
        '<p class="serif">' + esc(modelText || "（还没有内容）") + '</p><div class="pmodel-meter"><div class="plen-bar"><span style="width:' + (share * 100).toFixed(0) + '%"></span></div><small class="num">' + modelText.length + " / " + limit + "</small></div>" +
        (!p.data.summary && p.long ? '<div class="notice warn" style="margin-top:12px">设定共 ' + p.chars + " 字，超过 " + limit + " 字的部分不会交给 AI。整理一段摘要，能让角色更完整。</div>" : "") + "</div>" +
      '<dl class="pfields">' + data.fields.map((f) => "<dt>" + esc(f.label) + "</dt><dd>" + (p.data[f.key] ? esc(p.data[f.key]) : '<span class="faint">未填写</span>') + "</dd>").join("") + "</dl>" +
      '<div class="label" style="margin-top:18px">正在使用的团桌</div>' +
      (p.usage.length ? '<div class="puse">' + p.usage.map((u) => '<a href="#/rooms/' + encodeURIComponent(u.room) + '"><b>' + esc(u.title) + '</b><span class="tag">' + esc(STATE[u.state] || u.state) + "</span>" +
        (u.off ? '<span class="tag warn">本桌已关闭人设</span>' : "") + "<small>角色 " + esc(u.actor) + (u.intro ? "　" + esc(u.intro) : "　还没有融入这个世界") + "</small></a>").join("") + "</div>"
        : '<p class="hint">还没有带进任何一桌。入座时的人设会复制到角色上，之后修改人设卡不影响已经开始的故事。</p>') +
      '<div class="btns ppanel-actions"><button class="btn primary" data-mode="edit">' + icon("pen", 15) + "编辑</button>" +
        '<button class="btn" data-digest>' + icon("sparkle", 15) + (p.data.summary_by === "ai" ? "重新整理摘要" : "AI 整理摘要") + "</button>" +
        '<label class="btn">' + icon("image", 15) + '换头像<input type="file" accept="image/*" data-avatar hidden /></label>' +
        (p.avatar ? '<button class="btn text" data-avatar-clear>移除头像</button>' : "") +
        '<span class="spacer"></span><button class="btn text" data-export>' + icon("download", 15) + "导出酒馆 JSON</button>" +
        '<button class="btn text danger" data-delete>' + icon("trash", 15) + "删除</button></div>";
  }

  function editPanel(p) {
    const d = p ? p.data : {};
    return '<div class="ppanel-head slim"><div><div class="eyebrow">' + (p ? "编辑人设 · " + esc(p.user_name) : "新建人设") + '</div><h2 class="ppanel-title">' + (p ? esc(p.name) : "新的人设卡") + "</h2></div></div>" +
      (p ? "" : ownerField()) +
      '<label class="field"><span class="label row between">名字' + counter("name", data.limits.name) + '</span><input class="input" data-f="name" value="' + esc(p?.name || "") + '" maxlength="' + data.limits.name + '" /></label>' +
      data.fields.map((f) => '<label class="field"><span class="label row between">' + esc(f.label) + counter(f.key, data.limits.field) + '</span><textarea class="input" rows="' + (f.key === "background" ? 5 : 3) + '" data-f="' + f.key + '">' + esc(d[f.key] || "") + "</textarea></label>").join("") +
      '<label class="field"><span class="label">标签</span><input class="input" data-f="tags" value="' + esc((d.tags || []).join("、")) + '" placeholder="用顿号或空格分开，最多 8 个" /></label>' +
      '<label class="field"><span class="label row between">交给 AI 的摘要' + counter("summary", limit) + '</span><textarea class="input" rows="4" data-f="summary" placeholder="可不填：设定不超过 ' + limit + ' 字时全文交给 AI；更长时建议写一段，或保存后点“AI 整理摘要”">' + esc(d.summary || "") + "</textarea></label>" +
      '<div class="btns ppanel-actions"><button class="btn primary" data-save>' + icon("check", 15) + "保存</button><button class=\"btn text\" data-mode=\"" + (p ? "view" : "intro") + '">取消</button></div>';
  }

  function importPanel() {
    return '<div class="ppanel-head slim"><div><div class="eyebrow">导入 · SillyTavern</div><h2 class="ppanel-title">导入酒馆角色卡</h2></div></div>' + ownerField() +
      '<label class="drop">' + icon("upload", 22) + '<input type="file" accept=".png,.json,image/png,application/json" data-import-file /><b>选择角色卡</b><span>PNG 角色卡或 JSON（chara_card_v2 / v3）</span></label>' +
      '<div class="field" style="margin-top:16px"><label class="label">或粘贴 JSON</label><textarea class="textarea" rows="5" data-import-text spellcheck="false"></textarea></div>' +
      '<div class="btns"><button class="btn primary" data-import>' + icon("download", 15) + "导入粘贴的 JSON</button><button class=\"btn text\" data-mode=\"intro\">取消</button></div>" +
      '<p class="hint" style="margin-top:14px">只导入名字、描述、性格和示例对白里的说话方式；卡面图片会裁成头像。群里导入时，PNG 必须以文件发送，直接发图会被压缩、丢掉角色数据。</p>';
  }

  function introPanel() {
    return '<div class="ppanel-intro">' + empty(data.personas.length ? "选一张人设卡查看" : "还没有人设卡", "人设卡由玩家自己在私聊里建，也可以在这里替玩家导入或代建。") +
      '<div class="btns" style="justify-content:center"><button class="btn" data-mode="import">' + icon("upload", 15) + "导入酒馆角色卡</button><button class=\"btn primary\" data-mode=\"new\">" + icon("plus", 15) + "新建人设</button></div></div>";
  }

  function drawPanel() {
    const p = find(selected);
    if ((mode === "view" || mode === "edit") && !p) mode = "intro";
    panel.innerHTML = mode === "view" ? viewPanel(p) : mode === "edit" ? editPanel(p) : mode === "new" ? editPanel(null) : mode === "import" ? importPanel() : introPanel();
    panel.querySelectorAll("[data-count]").forEach(updateCount);
    drawList();
  }
  function updateCount(el) {
    const input = panel.querySelector('[data-f="' + el.dataset.count + '"]');
    const n = input ? input.value.length : 0, max = Number(el.dataset.max);
    el.textContent = n + " / " + max;
    el.classList.toggle("over", n > max);
  }
  function replace(p) {
    const i = data.personas.findIndex((x) => x.id === p.id);
    if (i >= 0) data.personas[i] = p; else data.personas.push(p);
    selected = p.id;
    mode = "view";
  }
  async function reload(id = selected) {
    data = await ctx.api.get("personas");
    selected = id;
    drawHead();
    drawPanel();
  }

  root.addEventListener("input", (e) => {
    const f = e.target.dataset.f;
    if (f) { const el = panel.querySelector('[data-count="' + f + '"]'); if (el) updateCount(el); }
  });
  root.addEventListener("click", async (e) => {
    const pick = e.target.closest("[data-pick]");
    if (pick) { selected = pick.dataset.pick; mode = "view"; drawPanel(); panel.scrollIntoView({ block: "nearest", behavior: "smooth" }); return; }
    const m = e.target.closest("[data-mode]");
    if (m) { mode = m.dataset.mode; drawPanel(); return; }
    const p = find(selected);
    try {
      if (e.target.closest("[data-save]")) {
        const btn = e.target.closest("[data-save]");
        const val = (k) => panel.querySelector('[data-f="' + k + '"]').value;
        const body = { name: val("name"), data: { ...Object.fromEntries(data.fields.map((f) => [f.key, val(f.key)])), tags: val("tags"), summary: val("summary") } };
        if (mode === "edit") {
          body.id = p.id;
          if (val("summary") !== (p.data.summary || "")) body.data.summary_by = val("summary") ? "manual" : "";
        } else Object.assign(body, ownerOf());
        const saved = await busy(btn, () => ctx.api.post("personas/save", body));
        await reload(saved.id);
        mode = "view";
        drawPanel();
        ctx.toast("已保存「" + saved.name + "」");
      } else if (e.target.closest("[data-digest]")) {
        const saved = await busy(e.target.closest("[data-digest]"), () => ctx.api.post("personas/digest", { id: p.id }));
        replace(saved); drawHead(); drawPanel();
        ctx.toast("AI 整理好了「" + saved.name + "」的摘要");
      } else if (e.target.closest("[data-avatar-clear]")) {
        replace(await ctx.api.post("personas/avatar", { id: p.id, data: "" })); drawPanel();
      } else if (e.target.closest("[data-export]")) {
        await ctx.api.download("personas/export", { id: p.id }, p.name + ".json");
      } else if (e.target.closest("[data-delete]")) {
        if (!window.confirm("删除「" + p.name + "」？这张卡属于玩家 " + p.user_name + "，已经带着它入座的团桌不受影响。")) return;
        data = await ctx.api.post("personas/delete", { id: p.id });
        selected = data.personas[0]?.id || null;
        mode = selected ? "view" : "intro";
        drawHead(); drawPanel();
        ctx.toast("已删除「" + p.name + "」");
      } else if (e.target.closest("[data-import]")) {
        const text = panel.querySelector("[data-import-text]").value.trim();
        if (!text) throw new Error("先选择文件或粘贴 JSON");
        const saved = await busy(e.target.closest("[data-import]"), () => ctx.api.post("personas/import", { ...ownerOf(), text }));
        await reload(saved.id); mode = "view"; drawPanel();
        ctx.toast("已导入「" + saved.name + "」" + (saved.long ? "，设定较长，建议整理摘要" : ""));
      }
    } catch (error) { ctx.toast(error.message, "error"); }
  });
  root.addEventListener("change", async (e) => {
    try {
      if (e.target.matches("[data-import-file]") && e.target.files[0]) {
        const file = e.target.files[0];
        const owner = ownerOf();
        const saved = await ctx.api.post("personas/import", { ...owner, data: await readFile(file), filename: file.name });
        await reload(saved.id); mode = "view"; drawPanel();
        ctx.toast("已导入「" + saved.name + "」" + (saved.avatar ? "，卡面已裁成头像" : ""));
      } else if (e.target.matches("[data-avatar]") && e.target.files[0]) {
        replace(await ctx.api.post("personas/avatar", { id: selected, data: await readFile(e.target.files[0]) }));
        drawPanel();
        ctx.toast("头像已更新");
      }
    } catch (error) { ctx.toast(error.message, "error"); }
  });

  drawHead();
  drawPanel();
}

