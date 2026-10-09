import { busy, esc, figure, hero, icon, md, plain } from "../ui.js";

const IMAGE_ROWS = [["image_status", "个人状态", "检定、骰点与资源变化"], ["image_narration", "故事正文", "模型生成的剧情段落"],
  ["image_choices", "行动选项", "轮到谁、可选行动与表决"], ["image_moment", "大场面", "开团招募、换幕、表决结果、终章与战报"],
  ["image_sheet", "角色卡", "角色卡与 /团 背包 的技能和物品"], ["image_receipt", "玩法回执", "玩法结果、记录详情与人物态度"],
  ["image_room", "团桌状态", "/团 状态、/团 阵容 与约团"], ["image_daily", "日常", "今日一掷、掷骰、对决、骰运、金句、接龙与海龟汤"]];
const SEG_INDEX = { status: "1", narration: "2", choices: "3", moment: "4", sheet: "5", receipt: "6", room: "7", daily: "8" };
const GROUPS = { 0: "一轮行动", 3: "大场面", 4: "查询与回执", 7: "日常" };
const PLATFORMS = [["qq_official", "QQ 官方机器人"], ["aiocqhttp", "OneBot（aiocqhttp）"]];
const THEMES = [["light", "白金"], ["dark", "黑金"]];
const IMAGE_KEYS = IMAGE_ROWS.map(([key]) => key);
const PREF_FIELDS = ["format", ...IMAGE_KEYS, "card_theme", "interval", "merge"];

export async function render(root, ctx) {
  const data = await ctx.api.get("messages/preview");
  const saved = { ...data.prefs };
  const form = { ...data.prefs };
  let platform = "qq_official";

  const images = IMAGE_KEYS.filter((k) => saved[k]).length;
  root.innerHTML = hero({
    eyebrow: "消息 · MESSAGES", title: "消息样式",
    lead: "所有团桌共用一套推送设置。不支持 Markdown 的平台会自动改用纯文本；QQ 官方机器人需要开通原生 Markdown 权限，被拒收一次后该平台会自动降级。",
    figures: '<div class="figures">' + figure(saved.format === "markdown" ? "MD" : "纯", saved.format === "markdown" ? "Markdown 推送" : "纯文本推送") +
      figure(images + "/" + IMAGE_KEYS.length, "类转为图片", "plain") + figure(saved.merge ? "合并" : Number(saved.interval).toFixed(1) + "″", saved.merge ? "一条发完" : "分段间隔", "plain") + "</div>",
  }) +
    '<div class="msg-layout"><section class="card" data-form></section><div class="stack" data-preview></div></div>';
  const formEl = root.querySelector("[data-form]");
  const previewEl = root.querySelector("[data-preview]");

  const dirty = () => PREF_FIELDS.some((k) => form[k] !== saved[k]);

  function drawForm() {
    formEl.innerHTML = '<div class="panel-head"><h2 class="panel-title">推送设置</h2><span class="panel-sub">' + (dirty() ? '<span class="gold">有未保存的修改</span>' : "已保存") + "</span></div>" +
      '<div class="label" style="margin-bottom:8px">推送格式</div><div class="seg" role="group" aria-label="推送格式">' +
      [["markdown", "Markdown"], ["plain", "纯文本"]].map(([k, l]) => '<button data-format="' + k + '" aria-pressed="' + (form.format === k) + '">' + l + "</button>").join("") + "</div>" +
      '<p class="hint" style="margin:8px 0 0">支持 Markdown 的平台：' + esc(data.markdown_platforms.join("、")) + "。其余平台一律纯文本。</p>" +
      '<hr class="rule" /><div class="label">转为图片</div><p class="hint" style="margin:4px 0 4px">按插件自带的卡片版式，经 AstrBot 的渲染服务出图。开场、换幕和换场景时正文卡顶部会放世界横幅。渲染失败时先改用 AstrBot 默认文转图，再失败就发文字。</p>' +
      IMAGE_ROWS.map(([key, label, note], i) => (GROUPS[i] ? '<div class="label" style="margin:' + (i ? 12 : 10) + 'px 0 2px">' + GROUPS[i] + "</div>" : "") +
        '<label class="opt"><span class="opt-num">' + SEG_INDEX[key.replace("image_", "")] + '</span><span class="opt-text"><b>' + label + "</b><span>" + note +
        '</span></span><span class="switch"><input type="checkbox" data-image="' + key + '" ' + (form[key] ? "checked" : "") + ' aria-label="' + label + '转为图片" /><span></span></span></label>').join("") +
      '<div class="label" style="margin:14px 0 8px">卡片配色</div><div class="seg" role="group" aria-label="卡片配色">' +
      THEMES.map(([k, l]) => '<button data-card-theme="' + k + '" aria-pressed="' + (form.card_theme === k) + '">' + l + "</button>").join("") + "</div>" +
      '<hr class="rule" /><div class="label">发送节奏</div>' +
      '<label class="opt"><span class="opt-text"><b>合并为一条消息</b><span>状态、正文和选项拼成一条；转图片的段落仍单独发送</span></span><span class="switch"><input type="checkbox" data-merge ' +
        (form.merge ? "checked" : "") + ' aria-label="合并为一条消息" /><span></span></span></label>' +
      '<div class="field" style="margin-top:6px"><label for="interval">分段间隔 <span class="num gold" data-interval-text>' + Number(form.interval).toFixed(1) + " 秒</span></label>" +
        '<input id="interval" type="range" min="0" max="3" step="0.5" value="' + form.interval + '" style="--fill:' + (form.interval / 3) * 100 + '%" ' + (form.merge ? "disabled" : "") + " /></div>" +
      (saved.blocked.length ? '<hr class="rule" /><div class="label">已自动降级为纯文本的平台</div><div class="chips" style="margin:8px 0 10px">' +
        saved.blocked.map((b) => '<span class="tag">' + esc(b) + "</span>").join("") + '</div><button class="btn small" data-unblock>重新尝试 Markdown</button>' : "") +
      '<div class="btns" style="margin-top:22px"><button class="btn primary" data-save ' + (dirty() ? "" : "disabled") + '>保存设置</button>' +
        (dirty() ? '<button class="btn text" data-revert>撤销修改</button>' : "") + "</div>";
    formEl.querySelectorAll("[data-format]").forEach((b) => b.addEventListener("click", () => { form.format = b.dataset.format; update(); }));
    formEl.querySelectorAll("[data-card-theme]").forEach((b) => b.addEventListener("click", () => { form.card_theme = b.dataset.cardTheme; update(); }));
    formEl.querySelectorAll("[data-image]").forEach((i) => i.addEventListener("change", () => { form[i.dataset.image] = i.checked; update(); }));
    formEl.querySelector("[data-merge]").addEventListener("change", (e) => { form.merge = e.target.checked; update(); });
    formEl.querySelector("#interval").addEventListener("input", (e) => {
      form.interval = Number(e.target.value);
      e.target.style.setProperty("--fill", (form.interval / 3) * 100 + "%");
      formEl.querySelector("[data-interval-text]").textContent = form.interval.toFixed(1) + " 秒";
      drawPreview();
      formEl.querySelector("[data-save]").disabled = !dirty();
    });
    formEl.querySelector("#interval").addEventListener("change", update);
    formEl.querySelector("[data-revert]")?.addEventListener("click", () => { Object.assign(form, saved); update(); });
    formEl.querySelector("[data-save]").addEventListener("click", (e) => save(e.target, {}));
    formEl.querySelector("[data-unblock]")?.addEventListener("click", (e) => save(e.target, { reset_blocked: true }));
  }

  async function save(button, extra) {
    try {
      const result = await busy(button, () => ctx.api.post("settings/message", { ...form, ...extra }));
      Object.assign(saved, result.message);
      Object.assign(form, result.message);
      ctx.toast("消息设置已保存");
      update();
    } catch (error) { ctx.toast(error.message, "error"); }
  }

  const useMarkdown = () => form.format === "markdown" && platform === "qq_official" && !saved.blocked.some((b) => b.startsWith("qq_official"));
  const imageOn = (segment) => Boolean(segment && form["image_" + segment]);
  const mention = (names) => names.map((n) => "@" + n + " ").join("");

  function bubble(entry, asMarkdown) {
    const source = mention(entry.mentions) + (asMarkdown ? entry.markdown : entry.plain);
    if (imageOn(entry.segment) && entry.card) {
      return '<div class="bubble image">' + (entry.mentions.length ? '<div style="padding:4px 8px 6px"><span class="at">' + esc(mention(entry.mentions)) + "</span></div>" : "") +
        '<iframe class="card-frame" title="' + esc(entry.label) + '图片卡" srcdoc="' + esc(entry.card[form.card_theme] || entry.card.light) + '"></iframe>' +
        '<div class="shot-tag">图片 · ' + (form.card_theme === "dark" ? "黑金" : "白金") + '卡片<button type="button" class="zoom" data-zoom="' + esc(entry.label) + '">' + icon("search", 12) + "放大</button></div></div>";
    }
    return asMarkdown ? '<div class="bubble md">' + md(source) + "</div>" : '<div class="bubble plain">' + plain(source) + "</div>";
  }

  function sequence(entries, asMarkdown) {
    // Mirrors delivery.prepare(): images stand alone, merge joins consecutive text items.
    const out = [];
    for (const entry of entries) {
      const last = out[out.length - 1];
      if (form.merge && !imageOn(entry.segment) && last && !last.image && !(entry.mentions.length && last.mentions.length)) {
        const sep = asMarkdown ? "\n\n---\n\n" : "\n\n┄┄┄┄┄┄┄┄┄┄\n\n";
        last.labels.push(entry.label);
        last.entry = { ...last.entry, markdown: last.entry.markdown + sep + entry.markdown, plain: last.entry.plain + sep + entry.plain,
          mentions: last.entry.mentions.length ? last.entry.mentions : entry.mentions, segment: "" };
        last.mentions = last.entry.mentions;
        continue;
      }
      out.push({ entry, labels: [entry.label], image: imageOn(entry.segment), mentions: entry.mentions, segment: entry.segment });
    }
    return out;
  }

  function chat(entries, asMarkdown, numbered) {
    const items = sequence(entries, asMarkdown);
    return items.map((item, i) => (i && !form.merge && form.interval ? '<div class="gap-note">间隔 ' + Number(form.interval).toFixed(1) + " 秒</div>" : "") +
      (numbered ? '<div class="seg-label">' + item.labels.map((l) => (SEG_INDEX[entries.find((e) => e.label === l)?.segment] || "") + "　" + l).join("　+　") + (item.image ? "　·　图片" : "") + "</div>" : "") +
      '<div class="chat-row"><span class="avatar bot" aria-hidden="true"></span><div><div class="sender">321Roll Lite</div>' + bubble(item.entry, asMarkdown) + "</div></div>").join("");
  }

  function drawPreview() {
    const asMarkdown = useMarkdown();
    const formatNote = asMarkdown ? "按 Markdown 发送" : form.format === "markdown" ? "该平台不支持 Markdown，自动降级为纯文本" : "按纯文本发送";
    previewEl.innerHTML = '<section class="chat"><div class="chat-top"><div><div class="panel-title">一轮行动的推送</div><div class="hint">' + esc(formatNote) + "</div></div>" +
      '<div class="seg" role="group" aria-label="预览平台">' + PLATFORMS.map(([k, l]) => '<button data-platform="' + k + '" aria-pressed="' + (platform === k) + '">' + l + "</button>").join("") + "</div></div>" +
      chat(data.turn, asMarkdown, true) + "</section>" +
      '<div class="ornament">其他消息</div><div class="grid cols-even">' + data.others.map((e) => '<section class="chat" style="padding:18px"><div class="label" style="margin-bottom:10px">' +
        esc(e.label) + (imageOn(e.segment) ? " · 图片" : "") + "</div>" + bubble(e, asMarkdown) + "</section>").join("") + "</div>";
    previewEl.querySelectorAll("[data-platform]").forEach((b) => b.addEventListener("click", () => { platform = b.dataset.platform; drawPreview(); }));
    previewEl.querySelectorAll("[data-zoom]").forEach((b) => b.addEventListener("click", () => {
      const entry = [...data.turn, ...data.others].find((x) => x.label === b.dataset.zoom);
      const box = document.createElement("div");
      box.className = "lightbox";
      box.innerHTML = '<div class="lightbox-card"><div class="lightbox-head"><b>' + esc(entry.label) + '</b><span class="hint">按卡片实际宽度显示</span><button type="button" class="btn text small" data-close>' +
        icon("x", 14) + "关闭</button></div><iframe title=\"" + esc(entry.label) + "\" srcdoc=\"" + esc(entry.card[form.card_theme] || entry.card.light) + '"></iframe></div>';
      const close = () => { box.remove(); document.removeEventListener("keydown", onKey); };
      const onKey = (e) => { if (e.key === "Escape") close(); };
      box.addEventListener("click", (e) => { if (e.target === box || e.target.closest("[data-close]")) close(); });
      document.addEventListener("keydown", onKey);
      document.body.appendChild(box);
    }));
    previewEl.querySelectorAll(".card-frame").forEach((frame) => {
      // The card stretches to its viewport (min-height 100vh), so measure the natural height of its content plus the footer.
      let width = 0;
      const fit = () => {
        const doc = frame.contentDocument;
        const content = doc?.querySelector(".content");
        if (!content || frame.clientWidth === width) return;
        width = frame.clientWidth;
        const last = content.lastElementChild;
        const view = doc.defaultView;
        const bottom = last ? last.getBoundingClientRect().bottom + parseFloat(view.getComputedStyle(last).marginBottom) : 0;
        frame.style.height = Math.ceil(bottom + parseFloat(view.getComputedStyle(content).paddingBottom) + doc.querySelector(".foot").offsetHeight) + "px";
      };
      frame.addEventListener("load", () => { width = 0; fit(); });
      new ResizeObserver(fit).observe(frame);
    });
  }

  function update() {
    drawForm();
    drawPreview();
  }
  update();
}

