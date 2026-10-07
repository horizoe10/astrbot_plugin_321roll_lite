// Thin wrapper over AstrBot's plugin page bridge (window.AstrBotPluginPage).
const bridge = () => window.AstrBotPluginPage;

export const available = () => Boolean(bridge());

export async function ready() {
  if (bridge()) await bridge().ready();
}

export function context() {
  return bridge()?.getContext?.() || {};
}

export function onContext(handler) {
  return bridge()?.onContext?.(handler) || (() => {});
}

export async function get(endpoint, params = {}) {
  return bridge().apiGet(endpoint, params);
}

export async function post(endpoint, body = {}) {
  return bridge().apiPost(endpoint, body);
}

export async function download(endpoint, params, filename) {
  return bridge().download(endpoint, params || {}, filename);
}

export async function upload(endpoint, file) {
  return bridge().upload(endpoint, file);
}
