from __future__ import annotations

import os

from aiohttp import web

import folder_paths
from server import PromptServer


routes = PromptServer.instance.routes


def _get_base_dir(dir_type: str) -> str | None:
    if dir_type == "input":
        return folder_paths.get_input_directory()
    if dir_type == "output":
        return folder_paths.get_output_directory()
    if dir_type == "temp":
        return folder_paths.get_temp_directory()
    return None


@routes.post("/delete")
async def delete_generated_file(request: web.Request) -> web.Response:
    data = await request.json()

    filename = str(data.get("filename") or "").strip()
    subfolder = str(data.get("subfolder") or "").strip()
    dir_type = str(data.get("type") or "").strip()

    if not filename:
        return web.json_response({"deleted": False, "error": "missing_filename"}, status=400)
    if dir_type not in {"input", "output", "temp"}:
        return web.json_response({"deleted": False, "error": "invalid_type"}, status=400)

    base_dir = _get_base_dir(dir_type)
    if not base_dir:
        return web.json_response({"deleted": False, "error": "invalid_base_dir"}, status=400)

    target_dir = os.path.abspath(os.path.join(base_dir, os.path.normpath(subfolder)))
    target_path = os.path.abspath(os.path.join(target_dir, filename))

    if os.path.commonpath((base_dir, target_dir)) != base_dir:
        return web.json_response({"deleted": False, "error": "invalid_subfolder"}, status=403)
    if os.path.commonpath((base_dir, target_path)) != base_dir:
        return web.json_response({"deleted": False, "error": "invalid_target"}, status=403)
    if os.path.isdir(target_path):
        return web.json_response({"deleted": False, "error": "target_is_directory"}, status=400)
    if not os.path.exists(target_path):
        return web.json_response({"deleted": False, "missing": True}, status=200)

    os.remove(target_path)
    return web.json_response({"deleted": True, "filename": filename, "type": dir_type})
