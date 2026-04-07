"""
UI Builder 微服务：接收 UI 示意图 → Gemini 分析 → 清洗映射 → 返回 Unity 预制体数据
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
    settings.http_client = httpx.AsyncClient(timeout=settings.timeout)
    logger.info(
        "UI Builder started | port=%s | model=%s | llm_base=%s",
        settings.port, settings.model, settings.api_url,
    )
    if not (settings.api_key or "").strip():
        logger.warning(
            "LLM 密钥未设置：/analyze 将返回 500，请在 settings.yaml 或环境变量 LLM_API_KEY 中配置"
        )
    yield
    if settings.http_client is not None:
        await settings.http_client.aclose()
        settings.http_client = None
    logger.info("UI Builder shutting down")


app = FastAPI(
    title="UI Builder",
    description="UI 示意图分析微服务：上传图片 → Gemini 分析 → Unity 预制体数据",
    lifespan=lifespan,
)

app.include_router(analyze.router)
app.include_router(health.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
