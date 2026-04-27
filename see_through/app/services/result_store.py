from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any

import httpx

from app.config import settings

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
    files = data.get("files")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            if isinstance(files, list):
                for item in files:
                    if not isinstance(item, dict):
                        continue
                    await _delete_remote_file(client, base_url, item)

            if prompt_id:
                await client.post(
                    f"{base_url}/history",
                    json={"delete": [prompt_id]},
                )
    except Exception:
        # 清理失败不影响用户下载结果
        pass

    await asyncio.sleep(0)


async def _delete_remote_file(client: httpx.AsyncClient, base_url: str, item: dict[str, Any]) -> None:
    filename = str(item.get("filename") or "").strip()
    file_type = str(item.get("type") or "").strip()
    subfolder = str(item.get("subfolder") or "")
    if not filename or file_type not in {"input", "output", "temp"}:
        return

    payload = {
        "filename": filename,
        "subfolder": subfolder,
        "type": file_type,
    }

    for path in ("/delete", "/api/delete"):
        try:
            response = await client.post(f"{base_url}{path}", json=payload)
            if response.status_code == 404:
                continue
            return
        except Exception:
            return
