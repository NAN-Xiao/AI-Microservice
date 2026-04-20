"""
Image2Psd 微服务：上传图片，调用远程 ComfyUI 工作流，返回 PSD 文件。
"""

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.middleware.auth import (
    TokenAuthMiddleware,
    start_nacos_token_watcher,
    stop_nacos_token_watcher,
)
from app.routers import convert, health
from app.routers.health import set_ready
from app.utils.logger import setup_logging, start_log_cleanup, stop_log_cleanup

setup_logging()
logger = logging.getLogger(__name__)

_NACOS_ADDR = os.environ.get("NACOS_ADDR", "").strip()
_nacos_server = _NACOS_ADDR if _NACOS_ADDR else settings.nacos_server_addr
_nacos_enabled = bool(_NACOS_ADDR) or settings.nacos_enabled.lower() in ("1", "true", "yes")

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
from nacos_registry import NacosRegistry

nacos = NacosRegistry(
    service_name=settings.nacos_service_name,
    service_port=settings.port,
    server_addr=_nacos_server,
    namespace=settings.nacos_namespace,
    group=settings.nacos_group,
    username=settings.nacos_username,
    password=settings.nacos_password,
    enabled=_nacos_enabled,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Image2Psd started | host=%s | port=%s | comfyui=%s",
        settings.host,
        settings.port,
        settings.comfyui_base_url,
    )
    logger.info(
        "日志模式: %s",
        "文件+控制台" if settings.log_to_file else "仅控制台(stdout)",
    )
    if not (settings.comfyui_base_url or "").strip():
        logger.warning("ComfyUI 地址未设置：/convert 将调用失败，请在配置文件或 COMFYUI_BASE_URL 中配置")

    await nacos.register()
    await start_nacos_token_watcher(settings.service_name)
    start_log_cleanup()
    set_ready(True)
    logger.info("服务就绪，开始接受请求")

    yield

    logger.info("收到停机信号，开始优雅停机...")
    set_ready(False)
    stop_log_cleanup()
    await stop_nacos_token_watcher()
    await nacos.deregister()
    logger.info("Image2Psd shutdown complete")


app = FastAPI(
    title="Image2Psd",
    description="上传图片，调用 ComfyUI 工作流并返回 PSD 文件",
    lifespan=lifespan,
)

app.add_middleware(TokenAuthMiddleware)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
    request.state.request_id = request_id
    start = time.time()
    logger.info(
        "→ %s %s [%s]",
        request.method, request.url.path, request_id,
    )
    try:
        response = await call_next(request)
        elapsed = time.time() - start
        logger.info(
            "← %s %s [%s] %d (%.1fms)",
            request.method, request.url.path, request_id,
            response.status_code, elapsed * 1000,
        )
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        elapsed = time.time() - start
        logger.exception(
            "← %s %s [%s] 500 (%.1fms) UNHANDLED",
            request.method, request.url.path, request_id, elapsed * 1000,
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": 500,
                "message": "服务内部错误",
                "request_id": request_id,
            },
        )


app.include_router(convert.router)
app.include_router(health.router)
