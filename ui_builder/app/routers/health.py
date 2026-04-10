"""
健康检查路由。
- /health      — 完整健康信息（Nacos 注册 / 运维面板）
- /health/live — 存活探针（Docker HEALTHCHECK / K8s livenessProbe）
- /health/ready — 就绪探针（K8s readinessProbe / Nginx upstream check）
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings
from app.models.response import ApiResult
from app.services.task_store import task_store_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ui-builder", tags=["健康检查"])

# 模块级就绪标志，由 app.main lifespan 控制
_ready = False


def set_ready(ready: bool) -> None:
    global _ready
    _ready = ready


@router.get("/health", response_model=ApiResult)
async def health():
    """完整健康信息 —— Nacos 服务注册时上报，也可用于运维面板。"""
    llm_configured = bool((settings.api_key or "").strip())

    return ApiResult.ok({
        "service": settings.service_name,
        "status": "UP" if _ready else "STARTING",
        "ready": _ready,
        "model": settings.model,
        "llm_configured": llm_configured,
        "tasks": task_store_summary(),
    })


@router.get("/health/live")
async def liveness():
    """
    存活探针 —— 仅检查进程是否存活。
    Docker HEALTHCHECK:  curl -f http://localhost:9002/api/ui-builder/health/live
    返回 200 = 活着，非 200 = 需要重启容器。
    """
    return JSONResponse({"status": "UP"})


@router.get("/health/ready")
async def readiness():
    """
    就绪探针 —— 检查服务是否可以接受流量。
    Nginx upstream_check / K8s readinessProbe 使用。
    返回 200 = 就绪，503 = 尚未就绪（别把流量打过来）。
    """
    if _ready:
        return JSONResponse({"status": "READY"})
    return JSONResponse({"status": "NOT_READY"}, status_code=503)
