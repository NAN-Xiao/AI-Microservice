"""
API Token 鉴权中间件。
"""

from __future__ import annotations

import logging
import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

_raw = os.environ.get("AUTH_TOKENS", "").strip()
_ALLOWED_TOKENS: frozenset[str] = (
    frozenset(t.strip() for t in _raw.split(",") if t.strip()) if _raw else frozenset()
)
_PUBLIC_KEYWORDS = ("/health", "/docs", "/openapi.json")


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

