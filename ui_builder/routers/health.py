from fastapi import APIRouter
from config import settings
from models.response import ApiResult

router = APIRouter(prefix="/api/ui-builder", tags=["健康检查"])


@router.get("/health", response_model=ApiResult)
async def health():
    return ApiResult.ok({
        "service": "ui-builder",
        "status": "UP",
        "model": settings.model,
        "api_url": settings.api_url,
    })
