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
from app.services.video_preprocess import VideoPreprocessError, preprocess_video
from app.utils.logger import log_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/depth-anything", tags=["Depth Anything"])

MAX_VIDEO_SIZE = 200 * 1024 * 1024
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
_comfy_semaphore: asyncio.Semaphore | None = None
_preprocess_semaphore: asyncio.Semaphore | None = None
_in_flight_requests = 0


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


def _get_preprocess_semaphore() -> asyncio.Semaphore | None:
    global _preprocess_semaphore
    if settings.video_preprocess_concurrency <= 0:
        return None
    if _preprocess_semaphore is None:
        _preprocess_semaphore = asyncio.Semaphore(settings.video_preprocess_concurrency)
    return _preprocess_semaphore


def _max_in_flight() -> int:
    if settings.comfyui_concurrency <= 0 or settings.comfyui_max_queue_size <= 0:
        return 0
    return settings.comfyui_concurrency + settings.comfyui_max_queue_size


@asynccontextmanager
async def _request_admission(request_id: str, filename: str):
    global _in_flight_requests
    limit = _max_in_flight()
    if limit > 0 and _in_flight_requests >= limit:
        logger.warning(
            "[%s] 排队已满，拒绝新请求: in_flight=%d limit=%d file=%s",
            request_id,
            _in_flight_requests,
            limit,
            filename,
        )
        raise ComfyQueueFullError(f"排队已满（最多允许 {limit} 个在途任务），请稍后重试")

    _in_flight_requests += 1
    try:
        yield
    finally:
        _in_flight_requests = max(0, _in_flight_requests - 1)


@asynccontextmanager
async def _preprocess_slot(request_id: str, filename: str):
    semaphore = _get_preprocess_semaphore()
    if semaphore is None:
        yield
        return

    if semaphore.locked():
        logger.info("[%s] 视频预处理繁忙，等待空闲槽位: %s", request_id, filename)
    async with semaphore:
        yield


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

    filename = video.filename or "input.mp4"

    try:
        async with _request_admission(request_id, filename):
            video_bytes = await video.read()
            if not video_bytes:
                log_request(
                    request_id,
                    {
                        "mode": "video_depth",
                        "status": "failed",
                        "filename": filename,
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
                        "filename": filename,
                        "content_type": video.content_type,
                        "size_bytes": len(video_bytes),
                        "error": f"视频过大，最大 {MAX_VIDEO_SIZE // (1024 * 1024)} MB",
                    },
                )
                return _api_error(400, f"视频过大，最大 {MAX_VIDEO_SIZE // (1024 * 1024)} MB")

            original_size = len(video_bytes)

            try:
                async with _preprocess_slot(request_id, filename):
                    prepared = await preprocess_video(video_bytes, filename)
            except VideoPreprocessError as exc:
                logger.warning("[%s] 视频预处理失败: %s", request_id, exc)
                log_request(
                    request_id,
                    {
                        "mode": "video_depth",
                        "status": "failed",
                        "filename": filename,
                        "content_type": video.content_type,
                        "size_bytes": original_size,
                        "error": str(exc),
                    },
                )
                return _api_error(400, str(exc))
            finally:
                video_bytes = b""

            queue_wait_ms = 0.0

            try:
                async with _comfy_slot(request_id, filename) as queue_wait_ms:
                    output_bytes, output_name, cleanup_token = await generate_video_depth(
                        prepared.video_bytes,
                        prepared.filename,
                        "video/mp4",
                        target_duration=prepared.target_duration,
                        target_fps=prepared.fps,
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
                        "size_bytes": original_size,
                        "processed_size_bytes": prepared.processed_size_bytes,
                        "original_duration": prepared.original_duration,
                        "target_duration": prepared.target_duration,
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
                        "size_bytes": original_size,
                        "processed_size_bytes": prepared.processed_size_bytes,
                        "original_duration": prepared.original_duration,
                        "target_duration": prepared.target_duration,
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
                        "size_bytes": original_size,
                        "processed_size_bytes": prepared.processed_size_bytes,
                        "original_duration": prepared.original_duration,
                        "target_duration": prepared.target_duration,
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
                        "size_bytes": original_size,
                        "processed_size_bytes": prepared.processed_size_bytes,
                        "original_duration": prepared.original_duration,
                        "target_duration": prepared.target_duration,
                        "queue_wait_ms": round(queue_wait_ms, 1),
                        "error": "生成深度视频失败，请稍后重试",
                    },
                )
                return _api_error(500, "生成深度视频失败，请稍后重试")
    except ComfyQueueFullError as exc:
        log_request(
            request_id,
            {
                "mode": "video_depth",
                "status": "failed",
                "filename": filename,
                "content_type": video.content_type,
                "error": str(exc),
            },
        )
        return _api_error(429, str(exc))

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
            "size_bytes": original_size,
            "processed_size_bytes": prepared.processed_size_bytes,
            "original_duration": prepared.original_duration,
            "target_duration": prepared.target_duration,
            "processed_fps": prepared.fps,
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
            "X-Original-Duration": str(prepared.original_duration or ""),
            "X-Processed-Duration": str(prepared.target_duration),
            "X-Processed-Size": str(prepared.processed_size_bytes),
        },
    )
