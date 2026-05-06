from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_STORE: dict[str, dict[str, Any]] = {}
_TTL_SECONDS = 1800


def put_cleanup_data(data: dict[str, Any]) -> str:
    token = secrets.token_urlsafe(24)
    payload = dict(data)
    payload["created_at"] = time.time()
    _STORE[token] = payload
    _cleanup_expired()
    return token


def pop_cleanup_data(token: str) -> dict[str, Any] | None:
    _cleanup_expired()
    return _STORE.pop(token, None)


async def cleanup_by_token(token: str) -> bool:
    data = pop_cleanup_data(token)
    if data is None:
        return False

    await cleanup_remote_resources(data)
    return True


def _cleanup_expired() -> None:
    cutoff = time.time() - _TTL_SECONDS
    expired = [k for k, v in _STORE.items() if float(v.get("created_at", 0)) < cutoff]
    for key in expired:
        _STORE.pop(key, None)


async def cleanup_remote_resources(data: dict[str, Any]) -> None:
    base_url = settings.comfyui_base_url.rstrip("/")
    if not base_url:
        return

    prompt_id = str(data.get("prompt_id") or "").strip()
    directories = data.get("directories")
    files = data.get("files")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            if isinstance(directories, list):
                for item in directories:
                    if not isinstance(item, dict):
                        continue
                    await _delete_remote_directory(client, base_url, item)

            if isinstance(files, list):
                for item in files:
                    if not isinstance(item, dict):
                        continue
                    await _delete_remote_file(client, base_url, item)

            if isinstance(directories, list):
                for item in directories:
                    if not isinstance(item, dict):
                        continue
                    await _delete_remote_directory(client, base_url, item)

            if prompt_id:
                await client.post(
                    f"{base_url}/history",
                    json={"delete": [prompt_id]},
                )
    except Exception as exc:
        # 清理失败不影响用户下载结果
        logger.warning("清理 ComfyUI 远端资源失败: %s", exc)

    await asyncio.sleep(0)


async def _delete_remote_file(client: httpx.AsyncClient, base_url: str, item: dict[str, Any]) -> None:
    filename = str(item.get("filename") or "").strip()
    file_type = str(item.get("type") or "").strip()
    subfolder = str(item.get("subfolder") or "")
    if not filename or _invalid_file_type(file_type):
        return

    payload = {
        "filename": filename,
        "subfolder": subfolder,
        "type": file_type,
    }

    for path in ("/delete", "/api/delete"):
        try:
            response = await client.post(f"{base_url}{path}", json=payload)
            if response.status_code in (404, 405):
                continue
            if response.status_code >= 400:
                logger.warning("删除 ComfyUI 文件失败: path=%s status=%s body=%s payload=%s", path, response.status_code, response.text[:500], payload)
            return
        except Exception as exc:
            logger.warning("调用 ComfyUI 文件删除接口失败: path=%s payload=%s error=%s", path, payload, exc)
            return
    logger.warning("ComfyUI 文件删除接口不可用: payload=%s", payload)


async def _delete_remote_directory(client: httpx.AsyncClient, base_url: str, item: dict[str, Any]) -> None:
    subfolder = str(item.get("subfolder") or "").strip().replace("\\", "/").strip("/")
    dir_type = str(item.get("type") or "").strip()
    if not subfolder or _invalid_file_type(dir_type):
        return

    payload = {
        "subfolder": subfolder,
        "type": dir_type,
    }

    for path in ("/seethrough/delete-directory", "/api/seethrough/delete-directory", "/delete-directory", "/api/delete-directory"):
        try:
            response = await client.post(f"{base_url}{path}", json=payload)
            if response.status_code in (404, 405):
                continue
            if response.status_code >= 400:
                logger.warning("删除 ComfyUI 目录失败: path=%s status=%s body=%s payload=%s", path, response.status_code, response.text[:500], payload)
            return
        except Exception as exc:
            logger.warning("调用 ComfyUI 目录删除接口失败: path=%s payload=%s error=%s", path, payload, exc)
            return
    logger.warning("ComfyUI 目录删除接口不可用，请确认 cleanup delete route 已更新并重启 ComfyUI: payload=%s", payload)


def _invalid_file_type(file_type: str) -> bool:
    return file_type not in {"input", "output", "temp"}
