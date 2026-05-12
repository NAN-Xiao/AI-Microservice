"""
健康检查路由。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings
from app.models.response import ApiResult

router = APIRouter(prefix="/api/ai-rembg", tags=["健康检查"])

_ready = False


def set_ready(ready: bool) -> None:
    global _ready
    _ready = ready


@router.get("/health", response_model=ApiResult)
async def health():
    comfyui_configured = bool((settings.comfyui_base_url or "").strip())

    return ApiResult.ok(
        {
            "service": settings.service_name,
            "status": "UP" if _ready else "STARTING",
            "ready": _ready,
            "comfyui_configured": comfyui_configured,
            "comfyui_base_url": settings.comfyui_base_url,
            "workflow_path": settings.workflow_path,
            "workflow_save_node_id": settings.workflow_save_node_id,
        }
    )


@router.get("/health/live")
async def liveness():
    return JSONResponse({"status": "UP"})


@router.get("/health/ready")
async def readiness():
    if _ready:
        return JSONResponse({"status": "READY"})
    return JSONResponse({"status": "NOT_READY"}, status_code=503)
