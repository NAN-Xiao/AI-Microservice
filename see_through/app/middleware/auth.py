"""
API Token 鉴权中间件。
"""

import asyncio
import logging
import os
import threading
from typing import Optional

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

_raw = os.environ.get("AUTH_TOKENS", "").strip()
_ENV_TOKENS: frozenset[str] = (
    frozenset(t.strip() for t in _raw.split(",") if t.strip()) if _raw else frozenset()
)

_nacos_lock = threading.Lock()
_nacos_tokens: set[str] = set()
_ALLOWED_TOKENS: set[str] = set(_ENV_TOKENS)


def _parse_tokens(raw: str) -> set[str]:
    return {t.strip() for t in raw.split(",") if t.strip()} if raw.strip() else set()


def _refresh_allowed():
    global _ALLOWED_TOKENS
    with _nacos_lock:
        _ALLOWED_TOKENS = set(_ENV_TOKENS) | set(_nacos_tokens)


def update_tokens_from_nacos(raw: str):
    global _nacos_tokens
    new_tokens = _parse_tokens(raw)
    with _nacos_lock:
        if new_tokens != _nacos_tokens:
            _nacos_tokens = new_tokens
            logger.info("Nacos token 热更新: %d 个 token 生效", len(new_tokens))
    _refresh_allowed()


_NACOS_ADDR = os.environ.get("NACOS_ADDR", "").strip()
_NACOS_POLL_INTERVAL = 30
_nacos_poll_task: Optional[asyncio.Task] = None


async def _fetch_nacos_config(service_name: str) -> Optional[str]:
    if not _NACOS_ADDR:
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"http://{_NACOS_ADDR}/nacos/v1/cs/configs",
                params={"dataId": service_name, "group": "AI_MICROSERVICE"},
            )
            if resp.status_code == 200:
                return resp.text
    except Exception as exc:
        logger.debug("Nacos 配置拉取失败: %s", exc)
    return None


def _extract_auth_tokens(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("auth_tokens:"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    return content.strip()


async def _nacos_poll_loop(service_name: str):
    logger.info("Nacos 配置监听已启动 (dataId=%s, 间隔=%ds)", service_name, _NACOS_POLL_INTERVAL)
    while True:
        try:
            await asyncio.sleep(_NACOS_POLL_INTERVAL)
            content = await _fetch_nacos_config(service_name)
            if content is not None:
                raw_tokens = _extract_auth_tokens(content)
                update_tokens_from_nacos(raw_tokens)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.debug("Nacos token 轮询异常: %s", exc)


async def start_nacos_token_watcher(service_name: str):
    global _nacos_poll_task
    if not _NACOS_ADDR:
        return

    content = await _fetch_nacos_config(service_name)
    if content is not None:
        update_tokens_from_nacos(_extract_auth_tokens(content))
        logger.info("首次从 Nacos 加载 token 完成")
    else:
        logger.info("Nacos 无 %s 配置或不可达，仅使用环境变量 token", service_name)

    _nacos_poll_task = asyncio.create_task(_nacos_poll_loop(service_name))


async def stop_nacos_token_watcher():
    global _nacos_poll_task
    if _nacos_poll_task and not _nacos_poll_task.done():
        _nacos_poll_task.cancel()
        try:
            await _nacos_poll_task
        except asyncio.CancelledError:
            pass
        _nacos_poll_task = None


_PUBLIC_KEYWORDS = ("/health", "/docs", "/openapi.json", "/ui")


class TokenAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not _ALLOWED_TOKENS:
            return await call_next(request)

        path = request.url.path
        if any(kw in path for kw in _PUBLIC_KEYWORDS):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""

        if token not in _ALLOWED_TOKENS:
            logger.warning("鉴权失败: %s %s (token=%s...)", request.method, path, token[:8])
            return JSONResponse(
                status_code=401,
                content={"code": 401, "message": "Unauthorized: invalid or missing token"},
            )

        return await call_next(request)
