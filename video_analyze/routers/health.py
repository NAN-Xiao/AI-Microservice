from fastapi import APIRouter
from config import settings
from models.response import ApiResult
from services.task_store import task_store

router = APIRouter(prefix="/api/video-analyze", tags=["健康检查"])


@router.get("/health", response_model=ApiResult)
async def health():
    all_tasks = await task_store.list_all()
    task_stats = {}
    for t in all_tasks:
        s = t["status"]
        task_stats[s] = task_stats.get(s, 0) + 1

    return ApiResult.ok({
        "service": settings.service_name,
        "status": "UP",
        "model": settings.model,
        "tasks": {
            "total": len(all_tasks),
            **task_stats,
        },
    })
