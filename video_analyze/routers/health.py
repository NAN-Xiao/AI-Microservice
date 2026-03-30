from fastapi import APIRouter
from config import settings
from models.response import ApiResult

router = APIRouter(prefix="/api/video-analyze", tags=["健康检查"])


@router.get("/health", response_model=ApiResult)
async def health():
    return ApiResult.ok({
        "service": "video-analyze",
        "status": "UP",
        "model": settings.model,
        "api_url": settings.api_url,
    })
