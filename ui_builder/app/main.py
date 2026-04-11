"""
UI Builder 微服务：上传 UI 示意图，分析并生成 Unity 预制体数据。

部署架构：Docker → Nacos 注册 → Nginx 反向代理 → FastAPI Token 鉴权。
"""

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.middleware.auth import (
    TokenAuthMiddleware,
    start_nacos_token_watcher,
    stop_nacos_token_watcher,
)
from app.routers import analyze, health
from app.routers.health import set_ready
from app.utils.logger import setup_logging

# 初始化日志系统（文件 + 控制台）
setup_logging()
logger = logging.getLogger(__name__)

_NACOS_ADDR = os.environ.get("NACOS_ADDR", "").strip()


# ─── Nacos 服务注册 / 注销 ──────────────────────────────

async def _register_to_nacos():
    """启动时向 Nacos 注册当前服务实例"""
    if not _NACOS_ADDR:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"http://{_NACOS_ADDR}/nacos/v1/ns/instance",
                params={
                    "serviceName": settings.service_name,
                    "ip": settings.host,
                    "port": settings.port,
                    "healthy": "true",
                    "weight": "1.0",
                    "groupName": "AI_MICROSERVICE",
                },
            )
        logger.info("已注册到 Nacos: %s (服务名=%s)", _NACOS_ADDR, settings.service_name)
    except Exception as e:
        logger.warning("Nacos 注册失败（不影响服务运行）: %s", e)


async def _deregister_from_nacos():
    """关闭时从 Nacos 注销"""
    if not _NACOS_ADDR:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.delete(
                f"http://{_NACOS_ADDR}/nacos/v1/ns/instance",
                params={
                    "serviceName": settings.service_name,
                    "ip": settings.host,
                    "port": settings.port,
                    "groupName": "AI_MICROSERVICE",
                },
            )
        logger.info("已从 Nacos 注销")
    except Exception:
        pass


# ─── Lifespan ───────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.http_client = httpx.AsyncClient(timeout=settings.timeout)
    logger.info(
        "UI Builder started | host=%s | port=%s | model=%s",
        settings.host, settings.port, settings.model,
    )
    logger.info(
        "日志模式: %s",
        "文件+控制台" if settings.log_to_file else "仅控制台(stdout)",
    )
    if not (settings.api_key or "").strip():
        logger.warning(
            "LLM 密钥未设置：/analyze 将返回 500，请在 settings.yaml 或 LLM_API_KEY 中配置"
        )

    # ⚠ 任务存储为内存模式，多实例部署时各实例的任务状态不共享
    logger.info("任务存储: 内存模式（单实例）")

    # Nacos 注册 + Token 配置监听
    await _register_to_nacos()
    await start_nacos_token_watcher(settings.service_name)

    # 标记就绪 —— Nginx/Nacos/K8s 探针开始放行流量
    set_ready(True)
    logger.info("服务就绪，开始接受请求")

    yield

    # ─── 优雅停机 ───────────────────────────────────────
    logger.info("收到停机信号，开始优雅停机...")
    set_ready(False)

    await stop_nacos_token_watcher()
    await _deregister_from_nacos()

    if settings.http_client is not None:
        await settings.http_client.aclose()
        settings.http_client = None
    logger.info("UI Builder shutdown complete")


app = FastAPI(
    title="UI Builder",
    description="上传图片，AI 分析生成 Unity 预制体数据",
    lifespan=lifespan,
)

# ─── 鉴权中间件（AUTH_TOKENS 为空时自动跳过）─────────────
app.add_middleware(TokenAuthMiddleware)


# ─── 全局请求日志中间件 ─────────────────────────────────

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
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


app.include_router(analyze.router)
app.include_router(health.router)
