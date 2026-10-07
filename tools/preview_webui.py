"""Serve the admin WebUI locally against a seeded in-memory app (scripted model, no AstrBot).

Usage: python -X utf8 tools/preview_webui.py [--port 8765]
Open http://127.0.0.1:8765/ (add ?theme=dark for the black-gold theme).
Data shown is produced by real commands against a scripted model; it is a preview fixture.
When dist/worlds exists (python tools/pack_worlds.py), it is served as a local world market
at /__market/index.json and two of its packages are installed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from support import Player, make_app  # noqa: E402
from roll_lite.web import service  # noqa: E402
from roll_lite.worlds import market  # noqa: E402

PAGES = ROOT / "pages" / "admin"
MARKET = ROOT / "dist" / "worlds"
BRIDGE = """
(function () {
  const dark = new URLSearchParams(location.search).get('theme') === 'dark';
  const context = { isDark: dark, locale: 'zh-CN' };
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  async function call(method, endpoint, payload) {
    const url = '/__api/' + endpoint + (method === 'GET' ? '?' + new URLSearchParams(payload || {}) : '');
    const res = await fetch(url, method === 'GET' ? {} : { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload || {}) });
    const body = await res.json();
    if (body.status === 'error') throw new Error(body.message);
    return body.data;
  }
  window.AstrBotPluginPage = {
    ready: async () => context, getContext: () => context, onContext: (h) => { h(context); return () => {}; },
    apiGet: (e, p) => call('GET', e, p), apiPost: (e, b) => call('POST', e, b),
    download: async (e, p, name) => {
        const res = await fetch('/__api/' + e + '?' + new URLSearchParams(p || {}));
        if (!res.ok || (res.headers.get('content-type') || '').includes('json') && !name.endsWith('.json')) throw new Error('下载失败');
      const a = document.createElement('a'); a.href = URL.createObjectURL(await res.blob()); a.download = name; a.click();
        return { filename: name };
      },
      upload: async (e, file) => {
        const res = await fetch('/__upload/' + e + '?name=' + encodeURIComponent(file.name), { method: 'POST', body: file });
        const body = await res.json();
        if (body.status === 'error') throw new Error(body.message);
        return body.data;
    },
  };
})();
"""


async def seed(port: int):
    app = make_app({"turn_timeout_seconds": 600})
    host, bob, cat, dan = (Player(app, "admin", "阿主"), Player(app, "bob", "小明"), Player(app, "cat", "猫猫"),
                           Player(app, "dan", "老丹", group="g2"))
    await host.say("/团 开启 第七个不思议")
    for player, arch, name in ((host, 1, "林晓"), (bob, 2, "陈默"), (cat, 3, "苏晴")):
        await player.say("/团 加入")
        await player.say(f"/团 选职业 {arch} {name}")
    await host.say("/团 开演")
    await host.say("/团 选 A 小心翼翼地")
    await bob.say("/团 线索 亲见 怀表停在三点：表盘内侧刻着一个名字")
    await cat.say("/团 假设 名字的主人：怀表属于三十年前失踪的林小满")
    await host.say("/团 冲突 钟楼守夜人：让他交出钥匙 4")
    await host.say("/团 存档 第一幕开头")
    await bob.say("/团 行动 我去检查闪烁的灯")
    await host.say("/团 主持 集体事件")
    await host.say("/团 投 A")
    await host.say("/团 主持 指引 第二幕前不要揭示林小满的身份")
    await bob.say("/团 关系 记下 值班老师：帮他找回了丢失的钥匙")
    await cat.say("/团 关系 记下 势力 学生会：拒绝了会长的邀请")
    await bob.say("/团 使用 薄荷糖")
    await cat.say("/团 计划 夜探钟楼：找到第七个不思议｜引开值班老师｜撬开钟楼门")
    await Player(app, "admin", "阿主", group=None).say("/团 帮助")
    await host.say("/团 主持 文风 偏对白 冷峻克制")
    await host.say("/团 主持 入座 关")
    await host.say("/团 主持 审稿 开")
    await host.say("/团 主持 推进 钟楼又响了一次")
    from roll_lite import adjust
    with app.store.tx() as c:
        room = c.execute("SELECT * FROM rooms WHERE state='running'").fetchone()
        actor = c.execute("SELECT * FROM actors WHERE room_id=? ORDER BY order_index", (room["id"],)).fetchone()
        adjust.queue(c, room, [{"kind": "attitude", "subject": "值班老师", "standing": 1},
                               {"kind": "item", "actor": actor["id"], "ref": "mint", "delta": 1}], "webui:preview", "")
    other = Player(app, "admin", "阿主", group="g2")
    await other.say("/团 开启 狩火")
    await dan.say("/团 加入")
    with app.store.tx() as c:
        c.execute("INSERT INTO outbox(umo,text,state,attempts,last_error,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                  ("fake:GroupMessage:g1", "苏晴 超时，自动选择 B。\n苏晴：检查闪烁的灯", "pending", 2, "platform refused the message",
                   "2026-10-07T09:12:00+00:00", "2026-10-07T09:13:00+00:00"))
    if (MARKET / "index.json").is_file():
        index = f"http://127.0.0.1:{port}/__market/index.json"
        market.save_settings(app, {"sources": [index], "route": "direct"}, "preview")
        for name in ("final-curtain-r1.zip", "neon-pawnshop-r1.zip"):
            await market.install_bytes(app, (MARKET / "packs" / name).read_bytes(), username="preview",
                                       origin={"source": index, "file": index.rsplit("/", 1)[0] + "/packs/" + name})
    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    app = asyncio.run_coroutine_threadsafe(seed(args.port), loop).result()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            pass

        def _json(self, payload: object, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _api(self, endpoint: str, payload: dict) -> None:
            if endpoint in service.FILE_ROUTES and self.command == "GET":
                try:
                    name, kind, data = asyncio.run_coroutine_threadsafe(service.FILE_ROUTES[endpoint](app, payload, "preview"), loop).result()
                except service.WebError as exc:
                    return self._json({"status": "error", "message": str(exc)})
                self.send_response(200)
                self.send_header("content-type", kind)
                self.send_header("content-disposition", f'attachment; filename="{name}"')
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            table = service.GET_ROUTES if self.command == "GET" else service.POST_ROUTES
            fn = table.get(endpoint)
            if fn is None:
                return self._json({"status": "error", "message": "未找到该路由"}, 404)
            try:
                result = asyncio.run_coroutine_threadsafe(fn(app, payload, "preview"), loop).result()
                self._json({"status": "ok", "data": result})
            except service.WebError as exc:
                self._json({"status": "error", "message": str(exc)})

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path.startswith("/__api/"):
                return self._api(url.path[len("/__api/"):], {k: v[0] for k, v in parse_qs(url.query).items()})
            if url.path == "/__bridge.js":
                data = BRIDGE.encode()
                self.send_response(200)
                self.send_header("content-type", "text/javascript")
                self.end_headers()
                return self.wfile.write(data)
            if url.path.startswith("/__market/"):
                path = (MARKET / url.path[len("/__market/"):]).resolve()
                if not str(path).startswith(str(MARKET.resolve())) or not path.is_file():
                    self.send_response(404)
                    return self.end_headers()
                data = path.read_bytes()
                self.send_response(200)
                self.send_header("content-type", {".json": "application/json", ".webp": "image/webp"}.get(path.suffix, "application/zip"))
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            path = (PAGES / (url.path.lstrip("/") or "index.html")).resolve()
            if not str(path).startswith(str(PAGES)) or not path.is_file():
                self.send_response(404)
                return self.end_headers()
            data = path.read_bytes()
            if path.name == "index.html":
                data = data.replace(b"<head>", b'<head><script src="/__bridge.js"></script>', 1)
            types = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".png": "image/png"}
            self.send_response(200)
            self.send_header("content-type", types.get(path.suffix, "application/octet-stream"))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            url = urlparse(self.path)
            length = int(self.headers.get("content-length") or 0)
            if url.path.startswith("/__upload/"):
                fn = service.UPLOAD_ROUTES.get(url.path[len("/__upload/"):])
                name = parse_qs(url.query).get("name", ["upload.zip"])[0]
                try:
                    result = asyncio.run_coroutine_threadsafe(fn(app, self.rfile.read(length), name, "preview"), loop).result()
                    return self._json({"status": "ok", "data": result})
                except service.WebError as exc:
                    return self._json({"status": "error", "message": str(exc)})
            body = json.loads(self.rfile.read(length) or b"{}")
            return self._api(url.path[len("/__api/"):], body)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"preview on http://127.0.0.1:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
