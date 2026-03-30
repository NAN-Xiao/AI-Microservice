"""
UI Builder Agent - 视频分析微服务
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
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "UI Builder Agent started | port=%s | llm=%s | upload_dir=%s",
        settings.port, settings.llm.provider, settings.upload_dir,
    )
    yield
    logger.info("UI Builder Agent shutting down")


app = FastAPI(
    title="UI Builder Agent",
    description="视频分析微服务：上传视频 → AI 分析 → 返回标签/描述",
    lifespan=lifespan,
)

app.include_router(analyze.router)
app.include_router(health.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
