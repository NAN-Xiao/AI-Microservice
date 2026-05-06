from __future__ import annotations

import logging
import os
import shutil
from typing import Final

from aiohttp import web

import folder_paths
from server import PromptServer

logger = logging.getLogger(__name__)

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

_ALLOWED_TYPES: Final[set[str]] = {"input", "output", "temp"}
routes = PromptServer.instance.routes


def _get_base_dir(dir_type: str) -> str | None:
    if dir_type == "input":
        return folder_paths.get_input_directory()
    if dir_type == "output":
        return folder_paths.get_output_directory()
    if dir_type == "temp":
        return folder_paths.get_temp_directory()
    return None


def _safe_join_base(base_dir: str, *parts: str) -> str | None:
    base_abs = os.path.abspath(base_dir)
    target_path = os.path.abspath(os.path.join(base_abs, *parts))
    try:
        if os.path.commonpath((base_abs, target_path)) != base_abs:
            return None
    except ValueError:
        return None
    return target_path


def _is_allowed_cleanup_subfolder(subfolder: str) -> bool:
    normalized = subfolder.replace("\\", "/").strip("/")
    return normalized.startswith("seethrough/requests/")


@routes.post("/delete")
async def delete_generated_file(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"deleted": False, "error": "invalid_json"}, status=400)

    filename = str(data.get("filename") or "").strip()
    subfolder = str(data.get("subfolder") or "").strip()
    dir_type = str(data.get("type") or "").strip()

    if not filename:
        return web.json_response({"deleted": False, "error": "missing_filename"}, status=400)
    if dir_type not in _ALLOWED_TYPES:
        return web.json_response({"deleted": False, "error": "invalid_type"}, status=400)

    base_dir = _get_base_dir(dir_type)
    if not base_dir:
        return web.json_response({"deleted": False, "error": "invalid_base_dir"}, status=400)

    target_dir = _safe_join_base(base_dir, os.path.normpath(subfolder))
    target_path = _safe_join_base(base_dir, os.path.normpath(subfolder), filename)
    if target_dir is None:
        return web.json_response({"deleted": False, "error": "invalid_subfolder"}, status=403)
    if target_path is None:
        return web.json_response({"deleted": False, "error": "invalid_target"}, status=403)

    if os.path.isdir(target_path):
        return web.json_response({"deleted": False, "error": "target_is_directory"}, status=400)
    if not os.path.exists(target_path):
        return web.json_response({"deleted": False, "missing": True}, status=200)

    try:
        os.remove(target_path)
    except Exception as exc:
        logger.warning("Delete file failed: %s", exc)
        return web.json_response({"deleted": False, "error": "delete_failed"}, status=500)

    logger.info("Deleted ComfyUI file: type=%s subfolder=%s filename=%s", dir_type, subfolder, filename)
    return web.json_response(
        {
            "deleted": True,
            "filename": filename,
            "subfolder": subfolder,
            "type": dir_type,
        }
    )


@routes.post("/delete-directory")
async def delete_generated_directory(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"deleted": False, "error": "invalid_json"}, status=400)

    subfolder = str(data.get("subfolder") or "").strip().replace("\\", "/").strip("/")
    dir_type = str(data.get("type") or "").strip()

    if not subfolder:
        return web.json_response({"deleted": False, "error": "missing_subfolder"}, status=400)
    if not _is_allowed_cleanup_subfolder(subfolder):
        return web.json_response({"deleted": False, "error": "unsupported_subfolder"}, status=403)
    if dir_type not in _ALLOWED_TYPES:
        return web.json_response({"deleted": False, "error": "invalid_type"}, status=400)

    base_dir = _get_base_dir(dir_type)
    if not base_dir:
        return web.json_response({"deleted": False, "error": "invalid_base_dir"}, status=400)

    target_dir = _safe_join_base(base_dir, os.path.normpath(subfolder))
    if target_dir is None:
        return web.json_response({"deleted": False, "error": "invalid_subfolder"}, status=403)
    if os.path.abspath(target_dir) == os.path.abspath(base_dir):
        return web.json_response({"deleted": False, "error": "refuse_base_dir"}, status=403)
    if not os.path.exists(target_dir):
        return web.json_response({"deleted": False, "missing": True}, status=200)
    if not os.path.isdir(target_dir):
        return web.json_response({"deleted": False, "error": "target_is_not_directory"}, status=400)

    try:
        shutil.rmtree(target_dir)
    except Exception as exc:
        logger.warning("Delete directory failed: %s", exc)
        return web.json_response({"deleted": False, "error": "delete_failed"}, status=500)

    logger.info("Deleted ComfyUI directory: type=%s subfolder=%s", dir_type, subfolder)
    return web.json_response(
        {
            "deleted": True,
            "subfolder": subfolder,
            "type": dir_type,
        }
    )


__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
