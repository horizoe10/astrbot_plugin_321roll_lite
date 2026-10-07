import * as api from "./api.js";
import { esc, failure, loading, toast } from "./ui.js";
import * as overview from "./views/overview.js";
import * as rooms from "./views/rooms.js";
import * as worlds from "./views/worlds.js";
import * as plays from "./views/plays.js";
import * as messages from "./views/messages.js";
import * as ops from "./views/ops.js";
import * as settings from "./views/settings.js";

const NAV = [["overview", "总览", overview], ["rooms", "团桌", rooms], ["worlds", "世界", worlds], ["plays", "玩法", plays],
  ["messages", "消息", messages], ["ops", "运行", ops], ["settings", "设置", settings]];
const VIEWS = Object.fromEntries(NAV.map(([key, label, view]) => [key, { label, view }]));

function parseRoute() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const [name, ...rest] = path.split("/").map(decodeURIComponent);
  return { name: VIEWS[name] ? name : "overview", rest, params: Object.fromEntries(new URLSearchParams(query)) };
}

export function go(path) {
  location.hash = "#/" + path;
}

let badges = {};
let version = "";
function renderNav(current) {
  document.getElementById("nav").innerHTML = NAV.map(([key, label]) => '<a href="#/' + key + '"' + (key === current ? ' aria-current="page"' : "") + ">" +
    label + (badges[key] ? '<span class="badge">' + badges[key] + "</span>" : "") + "</a>").join("");
  document.getElementById("meta").textContent = version ? "v" + version : "";
}

async function refreshBadges() {
  try {
    const d = await api.get("overview");
    version = d.version;
    badges = { ops: d.outbox_pending || 0, rooms: (d.rooms.running || 0) + (d.rooms.paused || 0) + (d.rooms.lobby || 0) };
    renderNav(parseRoute().name);
  } catch {
    /* the page reports its own read failures */
  }
}

let timer = null;
let guard = null;          // set by a page with unsaved edits: (silent) => may leave?
let currentHash = location.hash;
async function render() {
  const route = parseRoute();
  renderNav(route.name);
  clearInterval(timer);
  guard = null;
  const page = document.getElementById("page");
  loading(page);
  const ctx = { api, go, route, toast, refresh: render, every: (ms, fn) => { timer = setInterval(fn, ms); }, guard: (fn) => { guard = fn; } };
  try {
    await VIEWS[route.name].view.render(page, ctx);
    page.classList.remove("enter");
    void page.offsetWidth;
    page.classList.add("enter");
  } catch (error) {
    failure(page, error, render);
  }
}

async function start() {
  if (!api.available()) {
    renderNav("overview");
    document.getElementById("page").innerHTML = '<div class="notice"><b>请在 AstrBot 后台中打开本页面</b><div class="muted">插件页面需要 AstrBot 提供的桥接对象才能读取数据。</div></div>';
    return;
  }
  await api.ready();
  const applyTheme = (context) => {
    if (typeof context?.isDark === "boolean") document.documentElement.dataset.theme = context.isDark ? "dark" : "light";
  };
  applyTheme(api.context());
  api.onContext(applyTheme);
  window.addEventListener("hashchange", () => {
    if (guard && !guard(false)) {
      history.replaceState(null, "", currentHash);
      return;
    }
    currentHash = location.hash;
    render();
  });
  window.addEventListener("beforeunload", (event) => {
    if (guard && !guard(true)) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  await render();
  refreshBadges();
  setInterval(refreshBadges, 30000);
}

start().catch((error) => {
  document.getElementById("page").innerHTML = '<div class="notice err">' + esc(error.message || error) + "</div>";
});

