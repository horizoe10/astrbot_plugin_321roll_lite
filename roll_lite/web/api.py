"""Register the WebUI routes with AstrBot (see web/service.py for the handlers)."""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..version import PLUGIN_NAME
from . import service

if TYPE_CHECKING:
    from ..app import LiteApp

logger = logging.getLogger("astrbot_plugin_321roll_lite")


def _handler(app: "LiteApp", fn: Any, method: str):
    async def view(**_: Any):
        from astrbot.api.web import error_response, json_response, request
        try:
            if method == "GET":
                payload = {key: request.query.get(key) for key in request.query.keys()}
            else:
                payload = await request.json(default={})
                if not isinstance(payload, dict):
                    return error_response("请求体必须是 JSON 对象")
            username = str(getattr(request, "username", "") or "admin")
            return json_response({"status": "ok", "data": await fn(app, payload, username)})
        except service.WebError as exc:
            return error_response(str(exc))
        except Exception:
            logger.exception("321Roll Lite web route failed")
            return error_response("服务器内部错误，已写入日志", status_code=500)
    return view


def install(app: "LiteApp") -> None:
    register = getattr(app.context, "register_web_api", None)
    if register is None:
        return
    for path, fn in service.GET_ROUTES.items():
        register(f"/{PLUGIN_NAME}/{path}", _handler(app, fn, "GET"), ["GET"], f"321Roll Lite {path}")
    for path, fn in service.POST_ROUTES.items():
        register(f"/{PLUGIN_NAME}/{path}", _handler(app, fn, "POST"), ["POST"], f"321Roll Lite {path}")

    async def export_view(**_: Any):
        from astrbot.api.web import file_response
        folder = Path(tempfile.mkdtemp(prefix="roll-lite-backup-"))
        target = folder / "321roll-lite-backup.json"
        target.write_text(json.dumps(service.export_backup(app), ensure_ascii=False), encoding="utf-8")
        return file_response(target, filename=target.name, content_type="application/json")

    register(f"/{PLUGIN_NAME}/backup/export", export_view, ["GET"], "321Roll Lite backup export")
