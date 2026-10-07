// Shared rendering helpers: text, time, icons, page and section heads, and the small game-state visuals.
export const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
export const fmt = (n) => Number(n || 0).toLocaleString("zh-CN");
export const shortTitle = (title) => String(title || "").split(" · ")[0];
export const subTitle = (title) => (String(title || "").includes(" · ") ? String(title).split(" · ").slice(1).join(" · ") : "");

export function when(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const diff = (Date.now() - date.getTime()) / 1000;
  if (diff < -60) return until(iso);
  if (diff < 60) return "刚刚";
  if (diff < 3600) return Math.floor(diff / 60) + " 分钟前";
  if (diff < 86400) return Math.floor(diff / 3600) + " 小时前";
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** Time left before a future moment, e.g. a vote deadline. */
export function until(iso) {
  const left = (new Date(iso).getTime() - Date.now()) / 1000;
  if (Number.isNaN(left)) return "";
  if (left <= 0) return "已到期";
  if (left < 3600) return Math.ceil(left / 60) + " 分钟后";
  return Math.round(left / 3600) + " 小时后";
}

/** Event text for timelines: blank lines collapse, long text is cut. */
export const brief = (text, limit = 0) => {
  const s = String(text || "").replace(/\n\s*\n+/g, "\n");
  return limit && s.length > limit ? s.slice(0, limit) + "…" : s;
};

export function toast(message, kind = "") {
  const zone = document.getElementById("toasts");
  const item = document.createElement("div");
  item.className = "toast" + (kind === "error" ? " err" : "");
  item.textContent = message;
  zone.appendChild(item);
  setTimeout(() => item.remove(), kind === "error" ? 7000 : 3600);
}

export function loading(root) {
  root.innerHTML = '<div aria-busy="true" style="max-width:720px;padding-top:24px">' + [60, 92, 70, 84].map((w) => '<div class="skeleton" style="width:' + w + '%"></div>').join("") + "</div>";
}

export const empty = (title, hint = "") => '<div class="empty"><b>' + esc(title) + "</b>" + esc(hint) + "</div>";

export function failure(root, error, retry) {
  root.innerHTML = '<div class="notice err"><span class="fail-mark" aria-hidden="true"></span><b>读取失败</b><div class="muted">' + esc(error?.message || error) +
    '</div><div class="btns" style="margin-top:12px"><button class="btn small" data-retry>重新读取</button></div></div>';
  root.querySelector("[data-retry]")?.addEventListener("click", retry);
}

export async function busy(button, task) {
  const label = button.innerHTML;
  button.disabled = true;
  button.textContent = "处理中…";
  try {
    return await task();
  } finally {
    button.disabled = false;
    button.innerHTML = label;
  }
}

// ---------------------------------------------------------------- icons (24px grid, 1.6 stroke)
const P = (d) => '<path d="' + d + '"/>';
const C = (x, y, r) => '<circle cx="' + x + '" cy="' + y + '" r="' + r + '"/>';
const ICONS = {
  home: P("M3.5 10.5 12 3.5l8.5 7V20a.5.5 0 0 1-.5.5h-5v-6h-6v6H4a.5.5 0 0 1-.5-.5z"),
  dice: P("M12 2.8 20.2 7.5v9L12 21.2 3.8 16.5v-9z") + P("M3.8 7.5 12 12.3l8.2-4.8M12 12.3v8.9"),
  compass: C(12, 12, 9) + P("m15.5 8.5-2.2 4.8-4.8 2.2 2.2-4.8z"),
  book: P("M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5zM5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3M9 7h6"),
  layers: P("M12 3.5 20.5 8 12 12.5 3.5 8zM3.5 12 12 16.5 20.5 12M3.5 16 12 20.5 20.5 16"),
  message: P("M4 5h16v11H10l-5 4v-4H4z") + P("M8 9.5h8M8 12.5h5"),
  activity: P("M3 12h4l2.5-7 5 14 2.5-7h4"),
  sliders: P("M4 6.5h9M17 6.5h3M4 12h3M11 12h9M4 17.5h11M19 17.5h1") + C(15, 6.5, 2) + C(9, 12, 2) + C(17, 17.5, 2),
  users: C(9, 8, 3.5) + P("M2.5 20c.8-3.6 3.3-5.5 6.5-5.5s5.7 1.9 6.5 5.5M15.5 4.6a3.5 3.5 0 0 1 0 6.8M17.5 14.6c2 .7 3.3 2.5 3.8 5.4"),
  user: C(12, 8, 4) + P("M4.5 20.5c1-4 4-6 7.5-6s6.5 2 7.5 6"),
  clock: C(12, 12, 9) + P("M12 7v5l3.2 2"),
  flag: P("M5.5 21V4M5.5 4.5h11.5l-2.2 4 2.2 4H5.5"),
  alert: P("M12 3.5 21.5 20h-19zM12 10v4.5M12 17.3v.2"),
  check: P("m5 12.5 4.5 4.5L19 7.5"),
  x: P("M6.5 6.5 17.5 17.5M17.5 6.5 6.5 17.5"),
  refresh: P("M19.5 11A7.5 7.5 0 1 0 17.3 16.3M19.5 4.5V11h-6.5"),
  download: P("M12 4v11M7.5 10.5 12 15l4.5-4.5M4.5 19.5h15"),
  upload: P("M12 20V9M7.5 13.5 12 9l4.5 4.5M4.5 4.5h15"),
  pen: P("M4.5 19.5h4l10.5-10.5-4-4L4.5 15.5zM13.5 6.5l4 4"),
  copy: P("M8.5 8.5h11v11h-11z") + P("M15.5 8.5V4.5h-11v11h4"),
  trash: P("M4.5 7h15M9.5 7V4h5v3M6.5 7l1 13.5h9l1-13.5M10 11v6M14 11v6"),
  plus: P("M12 5v14M5 12h14"),
  arrow: P("M5 12h14M13.5 6.5 19 12l-5.5 5.5"),
  search: C(11, 11, 6.5) + P("m20 20-4.4-4.4"),
  feather: P("M20 4c-8.5 0-13.5 5-14.5 15.5M5.5 19.5 9 16M8.5 15c6.5 0 9.5-4.5 10.5-10"),
  eye: P("M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z") + C(12, 12, 3),
  eyeOff: P("M3.5 3.5l17 17M10.4 6.1A9 9 0 0 1 12 6c6 0 9.5 6 9.5 6a16 16 0 0 1-3 3.7M6.6 7.7C4 9.5 2.5 12 2.5 12s3.5 6 9.5 6c1.4 0 2.7-.3 3.8-.8"),
  pause: P("M8.5 5v14M15.5 5v14"),
  play: P("M7 4.5v15L19.5 12z"),
  skip: P("M6 5.5 15 12l-9 6.5zM18 5.5v13"),
  save: P("M5 4.5h11l3.5 3.5v11.5H5zM8.5 4.5v4.5h7V4.5M8.5 19.5v-5.5h7v5.5"),
  folder: P("M3.5 6.5h6l2 2h9v10.5h-17z"),
  vote: P("M4 10h16v10H4zM7.5 10V4.5h9V10") + P("m9 15 2 2 4-4"),
  send: P("M20.5 3.5 3.5 10.5l7 3 3 7zM10.5 13.5l10-10"),
  key: C(8, 15.5, 4) + P("M11 12.5 20 3.5M16.5 7l3 3M14.5 9l2 2"),
  globe: C(12, 12, 9) + P("M3 12h18M12 3c3 3.4 3 14.6 0 18M12 3c-3 3.4-3 14.6 0 18"),
  sparkle: P("M12 3.5l1.9 5.6 5.6 1.9-5.6 1.9L12 18.5l-1.9-5.6L4.5 11l5.6-1.9z"),
  scroll: P("M7 4h11a2 2 0 0 1 2 2v2h-4M7 4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V8M9 9h5.5M9 12.5h5.5M9 16h3.5"),
  shield: P("M12 3.5 19.5 6.5v5.5c0 4.7-3.2 7.7-7.5 8.5-4.3-.8-7.5-3.8-7.5-8.5V6.5z"),
  map: P("M3.5 6 9 3.5l6 2.5 5.5-2.5V18L15 20.5l-6-2.5L3.5 20.5zM9 3.5V18M15 6v14.5"),
  list: P("M9 6.5h11M9 12h11M9 17.5h11M4.5 6.5h.5M4.5 12h.5M4.5 17.5h.5"),
  grid: P("M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"),
  wand: P("M4.5 19.5 15 9M14 3.5v2.5M19.5 9H22M18 5.5l1.8-1.8M12.5 6.5l5 5"),
  door: P("M5.5 20.5V3.5h10v17M15.5 6.5h3v14M3.5 20.5h17M12.5 12h.3"),
  quote: P("M5 15c0-4 1.5-6.5 4.5-7.5M5 15h4v4.5H5zM14 15c0-4 1.5-6.5 4.5-7.5M14 15h4v4.5h-4z"),
  hash: P("M9.5 3.5 7.5 20.5M16.5 3.5l-2 17M4.5 9h16M3.5 15h16"),
  link: P("M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"),
  chevron: P("m6.5 9.5 5.5 5.5 5.5-5.5"),
  sun: C(12, 12, 4) + P("M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"),
  moon: P("M19.5 14.5A8 8 0 1 1 9.5 4.5a6.5 6.5 0 0 0 10 10z"),
  image: P("M3.5 5h17v14h-17z") + C(9, 10, 1.8) + P("m4 18 5-5 3.5 3.5 2.5-2.5 5 4.5"),
  bolt: P("M13 3 5 13.5h6L10 21l8-10.5h-6z"),
  heart: P("M12 20s-7.5-4.6-7.5-10.2A4.3 4.3 0 0 1 12 7.2a4.3 4.3 0 0 1 7.5 2.6C19.5 15.4 12 20 12 20z"),
  hourglass: P("M6.5 3.5h11M6.5 20.5h11M7.5 3.5c0 5 9 5 9 8.5s-9 3.5-9 8.5M16.5 3.5c0 5-9 5-9 8.5s9 3.5 9 8.5"),
};
export function icon(name, size = 16, cls = "") {
  return '<svg class="ico ' + cls + '" width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[name] || ICONS.sparkle) + "</svg>";
}

// ---------------------------------------------------------------- page structure
/** Page head: eyebrow, serif title, one lead line, optional figures and actions on the right. */
export function hero({ eyebrow, title, lead = "", figures = "", actions = "", crumb = "" }) {
  return '<header class="hero">' + (crumb ? '<a class="crumb" href="' + crumb[0] + '">' + icon("arrow", 14, "flip") + esc(crumb[1]) + "</a>" : "") +
    '<div class="hero-row"><div class="hero-text"><div class="eyebrow">' + eyebrow + '</div><h1 class="hero-title">' + title + "</h1>" +
    (lead ? '<p class="hero-lead">' + lead + "</p>" : "") + "</div>" +
    (figures || actions ? '<div class="hero-side">' + figures + (actions ? '<div class="btns">' + actions + "</div>" : "") + "</div>" : "") + "</div></header>";
}

/** Kept for older call sites: plain head without figures. */
export const head = (eyebrow, title, lead = "", actions = "") => hero({ eyebrow: esc(eyebrow), title: esc(title), lead: esc(lead), actions });

/** Section head: serif title with an optional gold count, a meta line and a text link on the right. */
export function section(title, { count = null, meta = "", link = null, extra = "" } = {}) {
  return '<div class="sec-head"><div><h2 class="sec-title">' + esc(title) + (count !== null ? '<span class="sec-count">' + esc(count) + "</span>" : "") + "</h2>" +
    (meta ? '<div class="sec-meta">' + meta + "</div>" : "") + "</div>" + extra +
    (link ? '<a class="link" href="' + link[0] + '">' + esc(link[1]) + icon("arrow", 14) + "</a>" : "") + "</div>";
}

export const figure = (value, label, tone = "") => '<div class="figure ' + tone + '"><b>' + esc(value) + "</b><span>" + esc(label) + "</span></div>";
export const figures = (items) => '<div class="figures">' + items.map(([v, l, t]) => figure(v, l, t)).join("") + "</div>";
/** Inline facts for a lead line: [[icon, value, label], ...] */
export const facts = (items) => items.map(([ic, v, l]) => '<span class="fact">' + icon(ic, 14) + (v !== "" ? "<b>" + esc(v) + "</b>" : "") + esc(l) + "</span>").join('<i class="sep">·</i>');

const STATE_DOT = { running: "ok", paused: "warn", lobby: "gold", ended: "off", closed: "off" };
export const roomDot = (state, label) => '<span class="dot ' + (STATE_DOT[state] || "") + '">' + esc(label) + "</span>";
export const dot = (kind, label) => '<span class="dot ' + kind + '">' + esc(label) + "</span>";
export const roundIcon = (name, tone = "") => '<span class="ricon ' + tone + '">' + icon(name, 16) + "</span>";

/** World cover: colour field plus one large character; attrs (data-art / data-srcs) let paintArt lay a scene image over it. */
export function cover(c, size = "tile", title = "", attrs = "") {
  const cap = size === "poster" && title
    ? '<div class="cap"><b>' + esc(shortTitle(title)) + "</b><span>" + esc(subTitle(title)) + "</span></div>" : "";
  return '<div class="cover ' + size + " tone-" + esc(c?.tone || "ink") + '" aria-hidden="true"' + (attrs ? " " + attrs : "") + ">" + cap +
    '<span class="mark">' + esc(c?.mark || "团") + "</span></div>";
}

// Scene images: installed ones come through the API as data URLs (plugin pages cannot read the data folder),
// market previews load straight from the index host.  Either way the colour cover stays until an image arrives.
const artCache = new Map();
function placeArt(el, url, onFail) {
  const img = new Image();
  img.className = "art";
  img.alt = "";
  img.decoding = "async";
  img.onload = () => { el.prepend(img); requestAnimationFrame(() => el.classList.add("has-art")); };
  img.onerror = () => onFail?.();
  img.src = url;
}
export function paintArt(root, api) {
  root.querySelectorAll("[data-art]").forEach(async (el) => {
    const key = el.dataset.art + "|" + (el.dataset.key || "cover") + "|" + (el.dataset.rev || "");
    try {
      if (!artCache.has(key)) artCache.set(key, (await api.get("worlds/image", { id: el.dataset.art, key: el.dataset.key || "cover" })).url);
      placeArt(el, artCache.get(key));
    } catch { /* keep the colour cover */ }
  });
  root.querySelectorAll("[data-srcs]").forEach((el) => {
    const list = JSON.parse(el.dataset.srcs || "[]");
    const next = (i) => { if (i < list.length) placeArt(el, list[i], () => next(i + 1)); };
    next(0);
  });
}

/** Initial avatar for a player or character. */
export function avatar(name, tone = "", extra = "") {
  const ch = String(name || "?").trim().slice(0, 1) || "?";
  return '<span class="avatar ' + tone + '" title="' + esc(name) + '">' + esc(ch) + extra + "</span>";
}
export const avatars = (names, max = 6) => '<span class="avatars">' + names.slice(0, max).map((n) => avatar(n)).join("") +
  (names.length > max ? '<span class="avatar more">+' + (names.length - max) + "</span>" : "") + "</span>";

/** Act progress: one segment per act, past acts thin gold, the current one solid gold. */
export function acts(list, current, mini = false) {
  if (!list?.length) return "";
  return '<div class="acts' + (mini ? " mini" : "") + '" aria-label="第 ' + current + " 幕，共 " + list.length + ' 幕">' + list.map((a) => {
    const n = typeof a === "object" ? a.number : a;
    const state = n < current ? "done" : n === current ? "now" : "";
    return '<div class="act-seg ' + state + '"><i></i>' + (mini ? "" : "<span>" + esc(typeof a === "object" ? a.title : "") + "</span>") + "</div>";
  }).join("") + "</div>";
}
/** Acts with titles only up to the one reached; later ones read "第 N 幕" so the track does not spoil the story. */
export const veiled = (list, reached) => list.map((a) => a.number > reached ? { number: a.number, title: "第 " + a.number + " 幕" } : a);

export function seats(filled, total, away = 0) {
  total = Math.max(0, Math.min(Number(total) || 0, 12));
  return '<span class="seats" aria-label="' + filled + "/" + total + ' 席">' + Array.from({ length: total }, (_, i) =>
    '<i class="' + (i < filled - away ? "on" : i < filled ? "away" : "") + '"></i>').join("") + "</span>";
}

/** Countdown ring; total and remaining in seconds. */
export function ring(remaining, total, caption, size = 92) {
  const r = 40, length = 2 * Math.PI * r;
  const share = total > 0 && remaining != null ? Math.max(0, Math.min(1, remaining / total)) : 0;
  const text = remaining == null ? "—" : remaining >= 60 ? Math.ceil(remaining / 60) + "′" : Math.max(0, Math.round(remaining)) + "″";
  return '<div class="ring" style="width:' + size + "px;height:" + size + 'px"><svg viewBox="0 0 92 92"><circle class="track" cx="46" cy="46" r="' + r + '" fill="none" stroke-width="3"/>' +
    '<circle class="arc' + (share < 0.25 ? " low" : "") + '" cx="46" cy="46" r="' + r + '" fill="none" stroke-width="3" stroke-dasharray="' + length.toFixed(1) +
    '" stroke-dashoffset="' + (length * (1 - share)).toFixed(1) + '"/></svg><div class="center"><b>' + text + "</b>" + (caption ? "<small>" + esc(caption) + "</small>" : "") + "</div></div>";
}

export function meter(name, current, max, alt = false) {
  const share = max ? Math.max(0, Math.min(1, (current ?? 0) / max)) : 0;
  return '<div class="meter' + (alt ? " alt" : "") + (share <= 0.25 ? " low" : "") + '"><span>' + esc(name) + '</span><div class="bar"><span style="width:' +
    (share * 100).toFixed(0) + '%"></span></div><span class="num">' + (current ?? "—") + "/" + max + "</span></div>";
}

export const cells = (on, total) => '<span class="cells">' + Array.from({ length: Math.min(total || 0, 12) }, (_, i) => '<i class="' + (i < on ? "on" : "") + '"></i>').join("") + "</span>";
export const stamps = (on, total) => '<span class="stamps">' + Array.from({ length: Math.min(total || 0, 8) }, (_, i) => '<i class="' + (i < on ? "on" : "") + '"></i>').join("") + "</span>";

/** Contest track: ours fills leftwards from the centre, theirs rightwards, both toward the length. */
export function tug(ours, theirs, length) {
  const pct = (n) => (length ? Math.min(100, (n / length) * 100) : 0).toFixed(0);
  return '<div class="tug"><span class="num">' + ours + '</span><div class="lane"><i><span style="width:' + pct(ours) + '%"></span></i><i><span style="width:' + pct(theirs) +
    '%"></span></i></div><span class="num">' + theirs + "</span></div>";
}

/** Radar of attribute shapes; series: [{values:[...], strong?}], values scaled between min and max. */
export function radar(labels, series, min, max, size = 180, showLabels = true) {
  const n = labels.length;
  if (n < 3) return "";
  const c = size / 2, R = size / 2 - (showLabels ? 30 : 8);
  const pt = (i, f) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / n; return [c + Math.cos(a) * R * f, c + Math.sin(a) * R * f]; };
  const poly = (f) => labels.map((_, i) => pt(i, f).map((v) => v.toFixed(1)).join(",")).join(" ");
  const span = Math.max(1, max - min);
  let svg = '<svg class="radar" viewBox="0 0 ' + size + " " + size + '" width="' + size + '" height="' + size + '">';
  for (const f of [0.34, 0.67, 1]) svg += '<polygon class="grid" points="' + poly(f) + '"/>';
  labels.forEach((_, i) => { const [x, y] = pt(i, 1); svg += '<line class="grid" x1="' + c + '" y1="' + c + '" x2="' + x.toFixed(1) + '" y2="' + y.toFixed(1) + '"/>'; });
  for (const s of series) {
    const pts = s.values.map((v, i) => pt(i, 0.12 + 0.88 * Math.max(0, Math.min(1, (v - min) / span))).map((q) => q.toFixed(1)).join(",")).join(" ");
    svg += '<polygon class="shape' + (s.strong ? " strong" : "") + '" points="' + pts + '"/>';
  }
  if (showLabels) labels.forEach((l, i) => { const [x, y] = pt(i, 1.2); svg += '<text x="' + x.toFixed(1) + '" y="' + (y + 4).toFixed(1) + '" text-anchor="middle">' + esc(l) + "</text>"; });
  return svg + "</svg>";
}

// ---------------------------------------------------------------- Markdown preview
// Renders the subset roll_lite/render.py produces, following CommonMark rules for line breaks.
function inlineMd(text) {
  const keep = [];
  let s = esc(text).replace(/\\([\\*_~|\x60\[\]#>+\-.])/g, (_, ch) => { keep.push(ch); return "\u0000" + (keep.length - 1) + "\u0000"; });
  s = s.replace(/\x60([^\x60]+)\x60/g, (_, code) => { keep.push("<code>" + code + "</code>"); return "\u0000" + (keep.length - 1) + "\u0000"; });
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*([^*\s][^*]*?)\*/g, "$1<em>$2</em>");
  s = s.replace(/^(?:@\S+\s)+/, (m) => '<span class="at">' + m + "</span>");
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => keep[Number(i)]);
}

export function md(source) {
  const blocks = String(source || "").split(/\n{2,}/);
  return blocks.map((block) => {
    const lines = block.split("\n");
    if (/^## /.test(block)) return "<h2>" + inlineMd(block.slice(3)) + "</h2>";
    if (/^### /.test(block)) return "<h3>" + inlineMd(block.slice(4)) + "</h3>";
    if (/^(---|\*\*\*)$/.test(block.trim())) return "<hr />";
    if (lines.every((l) => /^- /.test(l))) return "<ul>" + lines.map((l) => "<li>" + inlineMd(l.slice(2)) + "</li>").join("") + "</ul>";
    if (/^> /.test(block)) return "<blockquote>" + lines.map((l) => inlineMd(l.replace(/^> ?/, ""))).join(" ") + "</blockquote>";
    return "<p>" + lines.map((l) => (/ {2}$/.test(l) ? inlineMd(l.replace(/ +$/, "")) + "<br />" : inlineMd(l) + " ")).join("") + "</p>";
  }).join("");
}

export function plain(text) {
  return esc(text).replace(/^(?:@\S+\s)+/, (m) => '<span class="at">' + m + "</span>");
}

