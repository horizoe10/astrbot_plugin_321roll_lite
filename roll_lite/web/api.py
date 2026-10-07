"""Register the WebUI routes with AstrBot (see web/service.py for the handlers)."""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..version import PLUGIN_NAME
from ..worlds.package import MAX_PACKAGE
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


def _file_handler(app: "LiteApp", fn: Any):
    async def view(**_: Any):
        from astrbot.api.web import error_response, file_response, request
        try:
            payload = {key: request.query.get(key) for key in request.query.keys()}
            name, content_type, data = await fn(app, payload, str(getattr(request, "username", "") or "admin"))
        except service.WebError as exc:
            return error_response(str(exc))
        except Exception:
            logger.exception("321Roll Lite file route failed")
            return error_response("服务器内部错误，已写入日志", status_code=500)
        target = Path(tempfile.mkdtemp(prefix="roll-lite-file-")) / name
        target.write_bytes(data)
        return file_response(target, filename=name, content_type=content_type)
    return view


def _upload_handler(app: "LiteApp", fn: Any):
    async def view(**_: Any):
        from astrbot.api.web import error_response, json_response, request
        try:
            from astrbot.api.web import PluginUploadFile
        except ImportError:
            return error_response("当前 AstrBot 版本不支持插件页上传，请升级 AstrBot，或改用“从网址安装”")
        folder = Path(tempfile.mkdtemp(prefix="roll-lite-upload-"))
        try:
            upload = (await request.files()).get("file")
            if not isinstance(upload, PluginUploadFile):
                return error_response("没有收到文件")
            target = folder / "upload.bin"
            await upload.save(target)
            if target.stat().st_size > MAX_PACKAGE:
                return error_response(f"文件超过 {MAX_PACKAGE // (1024 * 1024)}MB 上限")
            username = str(getattr(request, "username", "") or "admin")
            return json_response({"status": "ok", "data": await fn(app, target.read_bytes(), upload.filename or "", username)})
        except service.WebError as exc:
            return error_response(str(exc))
        except Exception:
            logger.exception("321Roll Lite upload route failed")
            return error_response("服务器内部错误，已写入日志", status_code=500)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    return view


def install(app: "LiteApp") -> None:
    register = getattr(app.context, "register_web_api", None)
    if register is None:
        return
    for path, fn in service.GET_ROUTES.items():
        register(f"/{PLUGIN_NAME}/{path}", _handler(app, fn, "GET"), ["GET"], f"321Roll Lite {path}")
    for path, fn in service.POST_ROUTES.items():
        register(f"/{PLUGIN_NAME}/{path}", _handler(app, fn, "POST"), ["POST"], f"321Roll Lite {path}")
    for path, fn in service.FILE_ROUTES.items():
        register(f"/{PLUGIN_NAME}/{path}", _file_handler(app, fn), ["GET"], f"321Roll Lite {path}")
    for path, fn in service.UPLOAD_ROUTES.items():
        register(f"/{PLUGIN_NAME}/{path}", _upload_handler(app, fn), ["POST"], f"321Roll Lite {path}")
