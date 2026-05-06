import asyncio
from contextlib import asynccontextmanager
import logging
import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, File, Request, UploadFile
from fastapi.responses import Response

from app.config import settings
from app.models.response import ApiResult
from app.services.comfy_client import ComfyError, convert_image_to_psd
from app.services.result_store import cleanup_by_token
from app.utils.logger import log_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/see-through", tags=["See Through"])

MAX_IMAGE_SIZE = 30 * 1024 * 1024
_comfy_semaphore: asyncio.Semaphore | None = None


def _get_comfy_semaphore() -> asyncio.Semaphore | None:
    global _comfy_semaphore
    if settings.comfyui_concurrency <= 0:
        return None
    if _comfy_semaphore is None:
        _comfy_semaphore = asyncio.Semaphore(settings.comfyui_concurrency)
    return _comfy_semaphore


@asynccontextmanager
async def _comfy_slot(request_id: str, filename: str):
    semaphore = _get_comfy_semaphore()
    if semaphore is None:
        yield 0.0
        return

    wait_started = time.monotonic()
    if semaphore.locked():
        logger.info("[%s] ComfyUI 忙碌，当前请求进入排队: %s", request_id, filename)

    async with semaphore:
        queue_wait_ms = (time.monotonic() - wait_started) * 1000
        logger.info("[%s] 获得 ComfyUI 执行槽位，排队耗时 %.1fms: %s", request_id, queue_wait_ms, filename)
        yield queue_wait_ms


@router.post("/convert")
async def convert_to_psd(
    request: Request,
    background_tasks: BackgroundTasks,
    image: UploadFile = File(..., description="输入图片（png/jpg/webp）"),
):
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])

    if not image.content_type or not image.content_type.startswith("image/"):
        log_request(request_id, {
            "mode": "convert",
            "status": "failed",
            "filename": image.filename or "",
            "content_type": image.content_type,
            "error": f"仅支持图片文件，当前类型: {image.content_type}",
        })
        return ApiResult.error(400, f"仅支持图片文件，当前类型: {image.content_type}")

    image_bytes = await image.read()
    if not image_bytes:
        log_request(request_id, {
            "mode": "convert",
            "status": "failed",
            "filename": image.filename or "",
            "content_type": image.content_type,
            "error": "图片内容为空",
        })
        return ApiResult.error(400, "图片内容为空")

    if len(image_bytes) > MAX_IMAGE_SIZE:
        log_request(request_id, {
            "mode": "convert",
            "status": "failed",
            "filename": image.filename or "",
            "content_type": image.content_type,
            "size_bytes": len(image_bytes),
            "error": f"图片过大，最大 {MAX_IMAGE_SIZE // (1024 * 1024)} MB",
        })
        return ApiResult.error(400, f"图片过大，最大 {MAX_IMAGE_SIZE // (1024 * 1024)} MB")

    filename = image.filename or "input.png"
    queue_wait_ms = 0.0

    try:
        async with _comfy_slot(request_id, filename) as queue_wait_ms:
            psd_bytes, psd_name, cleanup_token = await convert_image_to_psd(image_bytes, filename, image.content_type)
    except ComfyError as exc:
        logger.warning("转换失败: %s", exc)
        log_request(request_id, {
            "mode": "convert",
            "status": "failed",
            "filename": filename,
            "content_type": image.content_type,
            "size_bytes": len(image_bytes),
            "queue_wait_ms": round(queue_wait_ms, 1),
            "error": str(exc),
        })
        return ApiResult.error(502, str(exc))
    except httpx.HTTPError as exc:
        logger.warning("ComfyUI HTTP 错误: %s", exc)
        log_request(request_id, {
            "mode": "convert",
            "status": "failed",
            "filename": filename,
            "content_type": image.content_type,
            "size_bytes": len(image_bytes),
            "queue_wait_ms": round(queue_wait_ms, 1),
            "error": "调用 ComfyUI 失败",
        })
        return ApiResult.error(502, "调用 ComfyUI 失败")
    except Exception:
        logger.exception("转换异常")
        log_request(request_id, {
            "mode": "convert",
            "status": "failed",
            "filename": filename,
            "content_type": image.content_type,
            "size_bytes": len(image_bytes),
            "queue_wait_ms": round(queue_wait_ms, 1),
            "error": "转换失败，请稍后重试",
        })
        return ApiResult.error(500, "转换失败，请稍后重试")

    safe_name = Path(psd_name).name
    if not safe_name.lower().endswith(".psd"):
        safe_name = f"{Path(filename).stem}.psd"

    log_request(request_id, {
        "mode": "convert",
        "status": "completed",
        "filename": filename,
        "content_type": image.content_type,
        "size_bytes": len(image_bytes),
        "queue_wait_ms": round(queue_wait_ms, 1),
        "output_name": safe_name,
        "output_size_bytes": len(psd_bytes),
    })

    background_tasks.add_task(cleanup_by_token, cleanup_token)

    return Response(
        content=psd_bytes,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "X-Cleanup-Token": cleanup_token,
        },
    )
