from __future__ import annotations

from fastapi import APIRouter

from app.models.response import ApiResult
from app.services.result_store import cleanup_by_token

router = APIRouter(prefix="/api/see-through", tags=["清理"])


@router.post("/cleanup", response_model=ApiResult)
async def cleanup(payload: dict):
    token = str(payload.get("token") or "").strip()
    if not token:
        return ApiResult.error(400, "缺少 cleanup token")

    cleaned = await cleanup_by_token(token)
    if not cleaned:
        return ApiResult.ok({"cleaned": False, "reason": "not_found"})

    return ApiResult.ok({"cleaned": True})
