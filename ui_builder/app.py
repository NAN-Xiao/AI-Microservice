"""
UI Builder 微服务：接收 UI 示意图 → Gemini 分析 → 清洗映射 → 返回 Unity 预制体数据
"""

import logging
from contextlib import asynccontextmanager

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
    logger.info(
        "UI Builder started | port=%s | model=%s",
        settings.port, settings.model,
    )
    yield
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
