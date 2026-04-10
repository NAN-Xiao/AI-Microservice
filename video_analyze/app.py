"""
Video Analyze 微服务：接收视频地址并调用 LLM 输出标签结果。
支持同步分析与异步任务（轮询）两种模式。
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import settings
from routers import analyze, health
from utils.logger import setup_logging

# 初始化日志系统（文件 + 控制台）
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.http_client = httpx.AsyncClient(timeout=settings.timeout)
    logger.info(
        "Video Analyze started | port=%s | model=%s | upload_dir=%s",
        settings.port, settings.model, settings.upload_dir,
    )
    if not (settings.api_key or "").strip():
        logger.warning(
            "LLM 密钥未设置：/analyze 将调用失败，请在 video_analyze/settings.yaml 或 LLM_API_KEY 中配置"
        )
    yield
    if settings.http_client is not None:
        await settings.http_client.aclose()
        settings.http_client = None
    logger.info("Video Analyze shutting down")


app = FastAPI(
    title="Video Analyze Agent",
    description="视频分析微服务：输入视频地址并输出标签结果。支持同步分析和异步任务轮询。",
    lifespan=lifespan,
)


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
