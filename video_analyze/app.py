"""
Video Analyze 微服务：接收视频地址并调用 LLM 输出标签结果
"""

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from config import settings
from routers import analyze, health

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
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
    description="视频分析微服务：输入视频地址并输出标签结果",
    lifespan=lifespan,
)

app.include_router(analyze.router)
app.include_router(health.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
