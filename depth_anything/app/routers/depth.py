from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, BackgroundTasks, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from app.config import settings
from app.models.response import ApiResult
from app.services.comfy_client import ComfyError, ComfyQueueFullError, generate_video_depth
from app.services.result_store import cleanup_by_token
from app.utils.logger import log_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/depth-anything", tags=["Depth Anything"])

MAX_VIDEO_SIZE = 200 * 1024 * 1024
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
_comfy_semaphore: asyncio.Semaphore | None = None


def _api_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ApiResult.error(status_code, message).model_dump(),
    )


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


def _is_valid_video(video: UploadFile) -> bool:
    if video.content_type and video.content_type.startswith("video/"):
        return True
    suffix = Path(video.filename or "").suffix.lower()
    return suffix in ALLOWED_VIDEO_EXTENSIONS


@router.post("/video-depth")
async def video_depth_api(
    request: Request,
    background_tasks: BackgroundTasks,
    video: UploadFile = File(..., description="输入视频（mp4/mov/webm/mkv/avi）"),
):
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])

    if not _is_valid_video(video):
        log_request(
            request_id,
            {
                "mode": "video_depth",
                "status": "failed",
                "filename": video.filename or "",
                "content_type": video.content_type,
                "error": f"仅支持视频文件，当前类型: {video.content_type}",
            },
        )
        return _api_error(400, f"仅支持视频文件，当前类型: {video.content_type}")

    video_bytes = await video.read()
    if not video_bytes:
        log_request(
            request_id,
            {
                "mode": "video_depth",
                "status": "failed",
                "filename": video.filename or "",
                "content_type": video.content_type,
                "error": "视频内容为空",
            },
        )
        return _api_error(400, "视频内容为空")

    if len(video_bytes) > MAX_VIDEO_SIZE:
        log_request(
            request_id,
            {
                "mode": "video_depth",
                "status": "failed",
                "filename": video.filename or "",
                "content_type": video.content_type,
                "size_bytes": len(video_bytes),
                "error": f"视频过大，最大 {MAX_VIDEO_SIZE // (1024 * 1024)} MB",
            },
        )
        return _api_error(400, f"视频过大，最大 {MAX_VIDEO_SIZE // (1024 * 1024)} MB")

    filename = video.filename or "input.mp4"
    queue_wait_ms = 0.0

    try:
        async with _comfy_slot(request_id, filename) as queue_wait_ms:
            output_bytes, output_name, cleanup_token = await generate_video_depth(
                video_bytes,
                filename,
                video.content_type,
            )
    except ComfyQueueFullError as exc:
        logger.warning("Depth Anything 队列已满: %s", exc)
        log_request(
            request_id,
            {
                "mode": "video_depth",
                "status": "failed",
                "filename": filename,
                "content_type": video.content_type,
                "size_bytes": len(video_bytes),
                "queue_wait_ms": round(queue_wait_ms, 1),
                "error": str(exc),
            },
        )
        return _api_error(429, str(exc))
    except ComfyError as exc:
        logger.warning("生成深度视频失败: %s", exc)
        log_request(
            request_id,
            {
                "mode": "video_depth",
                "status": "failed",
                "filename": filename,
                "content_type": video.content_type,
                "size_bytes": len(video_bytes),
                "queue_wait_ms": round(queue_wait_ms, 1),
                "error": str(exc),
            },
        )
        return _api_error(502, str(exc))
    except httpx.HTTPError as exc:
        logger.warning("ComfyUI HTTP 错误: %s", exc)
        log_request(
            request_id,
            {
                "mode": "video_depth",
                "status": "failed",
                "filename": filename,
                "content_type": video.content_type,
                "size_bytes": len(video_bytes),
                "queue_wait_ms": round(queue_wait_ms, 1),
                "error": "network error",
            },
        )
        return _api_error(502, "network error")
    except Exception:
        logger.exception("生成深度视频异常")
        log_request(
            request_id,
            {
                "mode": "video_depth",
                "status": "failed",
                "filename": filename,
                "content_type": video.content_type,
                "size_bytes": len(video_bytes),
                "queue_wait_ms": round(queue_wait_ms, 1),
                "error": "生成深度视频失败，请稍后重试",
            },
        )
        return _api_error(500, "生成深度视频失败，请稍后重试")

    safe_name = Path(output_name).name
    if not safe_name.lower().endswith(".mp4"):
        safe_name = f"{Path(filename).stem}_depth.mp4"
    encoded_name = quote(safe_name, safe="")
    fallback_name = safe_name if safe_name.isascii() else "depth.mp4"
    content_disposition = (
        f'attachment; filename="{fallback_name}"; '
        f"filename*=UTF-8''{encoded_name}"
    )

    log_request(
        request_id,
        {
            "mode": "video_depth",
            "status": "completed",
            "filename": filename,
            "content_type": video.content_type,
            "size_bytes": len(video_bytes),
            "queue_wait_ms": round(queue_wait_ms, 1),
            "output_name": safe_name,
            "output_size_bytes": len(output_bytes),
        },
    )

    background_tasks.add_task(cleanup_by_token, cleanup_token)

    return Response(
        content=output_bytes,
        media_type="video/mp4",
        headers={
            "Content-Disposition": content_disposition,
            "X-Cleanup-Token": cleanup_token,
        },
    )
