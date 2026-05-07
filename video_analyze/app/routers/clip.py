"""
视频切片分析路由。
支持同步分析与异步任务（轮询）两种模式。
输出格式参考 resources/video_clip.md。
"""

import asyncio
import logging
import uuid
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Query
from pydantic import BaseModel, field_validator

from app.config import settings
from app.models.response import ApiResult
from app.services import llm_service
from app.services.clip_service import build_clip_prompt, sanitize_clip_result
from app.services.task_store import task_store, TaskStatus
from app.utils.llm_utils import get_llm_semaphore, parse_json_result
from app.utils.logger import log_request, step_start, step_done, step_fail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/video-analyze/clip", tags=["视频切片分析"])

# 持有后台任务引用，防止被 GC 回收
_background_tasks: set[asyncio.Task] = set()


# ─── 请求模型 ──────────────────────────────────────────

class ClipRequest(BaseModel):
    video_url: str
    prompt: str | None = None  # 可选：用户额外提示词

    @field_validator("video_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("video_url 不能为空")
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("video_url 必须是 http/https 地址")
        return v


# ─── 同步分析 ──────────────────────────────────────────

@router.post("", response_model=ApiResult)
async def clip_analyze(req: ClipRequest):
    """
    同步切片分析：传入视频 URL → 等待 LLM 处理 → 返回切片 JSON。
    适合对延迟不敏感或调用方自行管理超时的场景。
    """
    request_id = uuid.uuid4().hex[:12]

    if not (settings.api_key or "").strip():
        return ApiResult.error(
            500,
            "服务未配置 LLM 密钥：请在 video_analyze/settings.yaml 的 llm.api_key 填写，"
            "或设置环境变量 LLM_API_KEY",
            request_id=request_id,
        )

    step_start(request_id, "同步切片分析")
    try:
        prompt = build_clip_prompt(extra_prompt=req.prompt or "")
        async with get_llm_semaphore():
            result_text = await llm_service.analyze(req.video_url, prompt)
        raw = parse_json_result(result_text)

        if "raw_content" in raw:
            step_done(request_id, "同步切片分析(raw)")
            log_request(request_id, {
                "mode": "clip_sync", "video_url": req.video_url,
                "status": "completed", "raw": True, "result": raw,
            })
            return ApiResult.ok(raw, request_id=request_id)

        cleaned, removed = sanitize_clip_result(raw)
        if removed:
            logger.warning("[%s] 清洗掉 %d 个非法片段: %s", request_id, len(removed), removed)

        step_done(request_id, "同步切片分析")
        log_request(request_id, {
            "mode": "clip_sync", "video_url": req.video_url,
            "status": "completed", "result": cleaned, "removed": removed,
        })
        return ApiResult.ok(cleaned, request_id=request_id)

    except httpx.TimeoutException:
        msg = "切片分析超时，LLM 服务响应过慢"
        step_fail(request_id, "同步切片分析", msg)
        log_request(request_id, {
            "mode": "clip_sync", "video_url": req.video_url,
            "status": "failed", "error": msg,
        })
        return ApiResult.error(504, msg, request_id=request_id)

    except httpx.HTTPStatusError as e:
        msg = f"LLM 服务错误: HTTP {e.response.status_code}"
        step_fail(request_id, "同步切片分析", msg)
        log_request(request_id, {
            "mode": "clip_sync", "video_url": req.video_url,
            "status": "failed", "error": msg,
        })
        return ApiResult.error(502, msg, request_id=request_id)

    except httpx.ConnectError:
        msg = "无法连接 LLM 服务，请检查网络或 API 地址"
        step_fail(request_id, "同步切片分析", msg)
        log_request(request_id, {
            "mode": "clip_sync", "video_url": req.video_url,
            "status": "failed", "error": msg,
        })
        return ApiResult.error(503, msg, request_id=request_id)

    except ValueError as e:
        msg = f"LLM 响应格式异常: {e}"
        step_fail(request_id, "同步切片分析", msg)
        log_request(request_id, {
            "mode": "clip_sync", "video_url": req.video_url,
            "status": "failed", "error": msg,
        })
        return ApiResult.error(502, msg, request_id=request_id)

    except Exception as exc:
        logger.exception("[%s] 切片分析失败", request_id)
        msg = f"切片分析失败: {type(exc).__name__}: {exc}"
        step_fail(request_id, "同步切片分析", msg)
        log_request(request_id, {
            "mode": "clip_sync", "video_url": req.video_url,
            "status": "failed", "error": msg,
        })
        return ApiResult.error(500, "切片分析失败，请稍后重试", request_id=request_id)


# ─── 异步任务：提交 ────────────────────────────────────

@router.post("/tasks", response_model=ApiResult)
async def submit_clip_task(req: ClipRequest):
    """
    异步提交切片分析任务，立即返回 task_id。
    调用方通过 GET /api/video-analyze/clip/tasks/{task_id} 轮询结果。
    """
    if not (settings.api_key or "").strip():
        return ApiResult.error(
            500,
            "服务未配置 LLM 密钥",
        )

    task = await task_store.create(req.video_url, task_type="clip")

    bg = asyncio.create_task(_run_clip_analysis(task.task_id, req.video_url, custom_prompt=req.prompt))
    _background_tasks.add(bg)
    bg.add_done_callback(_background_tasks.discard)

    return ApiResult.ok({
        "task_id": task.task_id,
        "status": task.status.value,
        "message": "切片任务已提交，请通过 GET /api/video-analyze/clip/tasks/{task_id} 轮询结果",
    })


# ─── 异步任务：查询状态（轮询） ──────────────────────────

@router.get("/tasks/{task_id}", response_model=ApiResult)
async def get_clip_task(task_id: str):
    """
    查询切片任务状态与结果。
    - pending: 排队中
    - processing: 分析中
    - completed: 完成（result 字段包含切片结果）
    - failed: 失败（error 字段包含原因）
    """
    task = await task_store.get(task_id)
    if task is None or task.task_type != "clip":
        return ApiResult.error(404, f"任务不存在或已过期: {task_id}")
    return ApiResult.ok(task.to_dict())


# ─── 异步任务：列表 ─────────────────────────────────────

@router.get("/tasks", response_model=ApiResult)
async def list_clip_tasks(
    status: str = Query(default=None, description="按状态筛选: pending/processing/completed/failed"),
    limit: int = Query(default=50, ge=1, le=200, description="返回数量上限"),
):
    """列出所有切片任务（支持按状态筛选）。"""
    all_tasks = await task_store.list_all()
    # 只过滤出 clip 类型
    all_tasks = [t for t in all_tasks if t.get("task_type") == "clip"]
    if status:
        all_tasks = [t for t in all_tasks if t["status"] == status]
    all_tasks.sort(key=lambda t: t["created_at"], reverse=True)
    return ApiResult.ok(all_tasks[:limit])


# ─── 内部实现 ──────────────────────────────────────────

async def _run_clip_analysis(task_id: str, video_url: str, *, custom_prompt: str | None = None) -> None:
    """后台执行切片分析任务。"""
    step_start(task_id, "异步切片分析")
    await task_store.set_processing(task_id)

    try:
        prompt = build_clip_prompt(extra_prompt=custom_prompt or "")
        async with get_llm_semaphore():
            result_text = await llm_service.analyze(video_url, prompt)
        raw = parse_json_result(result_text)

        if "raw_content" in raw:
            await task_store.set_completed(task_id, raw)
            step_done(task_id, "异步切片分析(raw)")
            log_request(task_id, {
                "mode": "clip_async", "video_url": video_url,
                "status": "completed", "raw": True, "result": raw,
            })
            return

        cleaned, removed = sanitize_clip_result(raw)
        if removed:
            logger.warning("[%s] 清洗掉 %d 个非法片段: %s", task_id[:8], len(removed), removed)

        await task_store.set_completed(task_id, cleaned)
        step_done(task_id, "异步切片分析")
        log_request(task_id, {
            "mode": "clip_async", "video_url": video_url,
            "status": "completed", "result": cleaned, "removed": removed,
        })

    except httpx.TimeoutException:
        msg = "切片分析超时，LLM 服务响应过慢"
        await task_store.set_failed(task_id, msg, 504)
        step_fail(task_id, "异步切片分析", msg)
        log_request(task_id, {
            "mode": "clip_async", "video_url": video_url, "status": "failed", "error": msg,
        })

    except httpx.HTTPStatusError as e:
        msg = f"LLM 服务错误: HTTP {e.response.status_code}"
        await task_store.set_failed(task_id, msg, 502)
        step_fail(task_id, "异步切片分析", msg)
        log_request(task_id, {
            "mode": "clip_async", "video_url": video_url, "status": "failed", "error": msg,
        })

    except httpx.ConnectError:
        msg = "无法连接 LLM 服务，请检查网络或 API 地址"
        await task_store.set_failed(task_id, msg, 503)
        step_fail(task_id, "异步切片分析", msg)
        log_request(task_id, {
            "mode": "clip_async", "video_url": video_url, "status": "failed", "error": msg,
        })

    except ValueError as e:
        msg = f"LLM 响应格式异常: {e}"
        await task_store.set_failed(task_id, msg, 502)
        step_fail(task_id, "异步切片分析", msg)
        log_request(task_id, {
            "mode": "clip_async", "video_url": video_url, "status": "failed", "error": msg,
        })

    except Exception as exc:
        logger.exception("[%s] 异步切片分析失败", task_id[:8])
        msg = f"切片分析失败: {type(exc).__name__}: {exc}"
        await task_store.set_failed(task_id, msg, 500)
        step_fail(task_id, "异步切片分析", msg)
        log_request(task_id, {
            "mode": "clip_async", "video_url": video_url, "status": "failed", "error": msg,
        })
