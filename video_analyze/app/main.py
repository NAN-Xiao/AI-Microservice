"""
Video Analyze 微服务：接收视频地址并调用 LLM 输出标签结果。
支持同步分析与异步任务（轮询）两种模式。

部署架构：Docker → Nacos 注册 → Nginx/Gateway 反向代理。
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import analyze, health
from app.routers.health import set_ready
from app.utils.logger import setup_logging

# 初始化日志系统（文件 + 控制台）
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.http_client = httpx.AsyncClient(timeout=settings.timeout)
    logger.info(
        "Video Analyze started | host=%s | port=%s | model=%s",
        settings.host, settings.port, settings.model,
    )
    logger.info(
        "日志模式: %s",
        "文件+控制台" if settings.log_to_file else "仅控制台(stdout)",
    )
    if not (settings.api_key or "").strip():
        logger.warning(
            "LLM 密钥未设置：/analyze 将调用失败，请在 settings.yaml 或 LLM_API_KEY 中配置"
        )

    # ⚠ 任务存储为内存模式，多实例部署时各实例的任务状态不共享
    # 如需跨实例共享，请将 task_store 替换为 Redis 实现
    logger.info("任务存储: 内存模式（单实例）")

    # 标记就绪 —— Nginx/Nacos/K8s 探针开始放行流量
    set_ready(True)
    logger.info("服务就绪，开始接受请求")

    yield

    # ─── 优雅停机 ───────────────────────────────────────
    logger.info("收到停机信号，开始优雅停机...")
    set_ready(False)  # 先标记未就绪，探针返回 503，Nginx/Nacos 摘流

    if settings.http_client is not None:
        await settings.http_client.aclose()
        settings.http_client = None
    logger.info("Video Analyze shutdown complete")


app = FastAPI(
    title="Video Analyze Agent",
    description="视频分析微服务：输入视频地址并输出标签结果。支持同步分析和异步任务轮询。",
    lifespan=lifespan,
)


# ─── 全局请求日志中间件 ─────────────────────────────────

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    # 支持上游（Nginx/Gateway）传递的请求追踪 ID
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
