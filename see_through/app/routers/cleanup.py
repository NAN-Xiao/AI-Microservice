from __future__ import annotations

from fastapi import APIRouter

from app.models.response import ApiResult
from app.services.result_store import cleanup_remote_resources, pop_cleanup_data

router = APIRouter(prefix="/api/see-through", tags=["清理"])


@router.post("/cleanup", response_model=ApiResult)
async def cleanup(payload: dict):
    token = str(payload.get("token") or "").strip()
    if not token:
        return ApiResult.error(400, "缺少 cleanup token")

    data = pop_cleanup_data(token)
    if data is None:
        return ApiResult.ok({"cleaned": False, "reason": "not_found"})

    await cleanup_remote_resources(data)
    return ApiResult.ok({"cleaned": True})
