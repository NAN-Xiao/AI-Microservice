"""
Depth Anything 微服务：上传视频，调用内网 ComfyUI Depth Anything 3 工作流，返回深度视频 MP4。
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.middleware.auth import TokenAuthMiddleware
from app.routers import cleanup, depth, health, web
from app.routers.health import set_ready
from app.utils.logger import setup_logging, start_log_cleanup, stop_log_cleanup
from nacos_registry import NacosRegistry

setup_logging()
logger = logging.getLogger(__name__)

_LOG_IGNORED_PATHS = {
    "/api/depth-anything/health",
    "/api/depth-anything/health/live",
}

nacos = NacosRegistry(
    service_name=settings.nacos_service_name or settings.service_name,
    service_port=settings.port,
    server_addr=settings.nacos_server_addr,
    namespace=settings.nacos_namespace,
    group=settings.nacos_group,
    username=settings.nacos_username,
    password=settings.nacos_password,
    enabled=str(settings.nacos_enabled).lower() in ("1", "true", "yes", "on"),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Depth Anything started | host=%s | port=%s | comfyui=%s",
        settings.host,
        settings.port,
        settings.comfyui_base_url,
    )
    if settings.comfyui_concurrency > 0:
        logger.info("ComfyUI 并发限制: %s", settings.comfyui_concurrency)
    else:
        logger.info("ComfyUI 并发限制: 未启用（按上游能力并发执行）")
    logger.info("日志模式: %s", "文件+控制台" if settings.log_to_file else "仅控制台(stdout)")
    if not (settings.comfyui_base_url or "").strip():
        logger.warning("ComfyUI 地址未设置：/video-depth 将调用失败，请配置 COMFYUI_BASE_URL")

    start_log_cleanup()
    await nacos.register()
    set_ready(True)
    logger.info("服务就绪，开始接受请求")

    yield

    logger.info("收到停机信号，开始优雅停机...")
    set_ready(False)
    await nacos.deregister()
    stop_log_cleanup()
    logger.info("Depth Anything shutdown complete")


app = FastAPI(
    title="Depth Anything",
    description="上传视频，调用内网 ComfyUI Depth Anything 3 工作流并返回深度视频 MP4 文件",
    lifespan=lifespan,
)

app.add_middleware(TokenAuthMiddleware)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
    request.state.request_id = request_id
    if request.url.path in _LOG_IGNORED_PATHS:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    start = time.time()
    logger.info("→ %s %s [%s]", request.method, request.url.path, request_id)
    try:
        response = await call_next(request)
        elapsed = time.time() - start
        logger.info(
            "← %s %s [%s] %d (%.1fms)",
            request.method,
            request.url.path,
            request_id,
            response.status_code,
            elapsed * 1000,
        )
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        elapsed = time.time() - start
        logger.exception("✖ %s %s [%s] 异常 (%.1fms)", request.method, request.url.path, request_id, elapsed * 1000)
        raise


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("未捕获异常: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": "Internal Server Error", "data": None},
    )


app.include_router(health.router)
app.include_router(depth.router)
app.include_router(cleanup.router)
app.include_router(web.router)
