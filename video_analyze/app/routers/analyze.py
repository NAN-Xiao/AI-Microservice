"""
视频标签分析路由。
支持同步分析与异步任务（轮询）两种模式。
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
from app.services.tag_schema import build_tag_prompt, sanitize_tags, get_tag_schema, update_tag_schema, validate_tag_schema
from app.services.task_store import task_store, TaskStatus
from app.utils.llm_utils import get_llm_semaphore, parse_json_result
from app.utils.logger import log_request, step_start, step_done, step_fail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/video-analyze", tags=["视频分析"])

# 持有后台任务引用，防止被 GC 回收
_background_tasks: set[asyncio.Task] = set()


# ─── 请求模型 ──────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    video_url: str
    tags: dict | None = None      # 可选：调用方自定义标签体系，不传则使用服务端默认
    prompt: str | None = None     # 可选：用户额外提示词，会追加到系统 prompt 末尾

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

@router.post("/analyze", response_model=ApiResult)
async def analyze(req: AnalyzeRequest):
    """
    同步分析：传入视频 URL → 等待 LLM 处理 → 返回标签 JSON。
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

    # 如果调用方传了自定义标签体系，先校验格式
    if req.tags is not None:
        errors = validate_tag_schema(req.tags)
        if errors:
            return ApiResult.error(400, f"tags 格式错误: {'; '.join(errors)}", request_id=request_id)

    step_start(request_id, "同步分析")
    try:
        prompt = build_tag_prompt(override_tags=req.tags, extra_prompt=req.prompt or "")
        async with get_llm_semaphore():
            result_text = await llm_service.analyze(req.video_url, prompt)
        raw_tags = parse_json_result(result_text)

        if "raw_content" in raw_tags:
            step_done(request_id, "同步分析(raw)")
            log_request(request_id, {
                "mode": "sync", "video_url": req.video_url,
                "status": "completed", "raw": True, "result": raw_tags,
            })
            return ApiResult.ok(raw_tags, request_id=request_id)

        tags, removed = sanitize_tags(raw_tags, override_tags=req.tags)
        if removed:
            logger.warning("[%s] 清洗掉 %d 个非法标签: %s", request_id, len(removed), removed)

        step_done(request_id, "同步分析")
        log_request(request_id, {
            "mode": "sync", "video_url": req.video_url,
            "status": "completed", "result": tags, "removed_tags": removed,
        })
        return ApiResult.ok(tags, request_id=request_id)

    except httpx.TimeoutException:
        msg = "分析超时，LLM 服务响应过慢"
        step_fail(request_id, "同步分析", msg)
        log_request(request_id, {
            "mode": "sync", "video_url": req.video_url,
            "status": "failed", "error": msg,
        })
        return ApiResult.error(504, msg, request_id=request_id)

    except httpx.HTTPStatusError as e:
        msg = f"LLM 服务错误: HTTP {e.response.status_code}"
        step_fail(request_id, "同步分析", msg)
        log_request(request_id, {
            "mode": "sync", "video_url": req.video_url,
            "status": "failed", "error": msg,
        })
        return ApiResult.error(502, msg, request_id=request_id)

    except httpx.ConnectError:
        msg = "无法连接 LLM 服务，请检查网络或 API 地址"
        step_fail(request_id, "同步分析", msg)
        log_request(request_id, {
            "mode": "sync", "video_url": req.video_url,
            "status": "failed", "error": msg,
        })
        return ApiResult.error(503, msg, request_id=request_id)

    except ValueError as e:
        # 上游返回结构异常/不可解析时，按上游错误处理，避免误报 500
        msg = f"LLM 响应格式异常: {e}"
        step_fail(request_id, "同步分析", msg)
        log_request(request_id, {
            "mode": "sync", "video_url": req.video_url,
            "status": "failed", "error": msg,
        })
        return ApiResult.error(502, msg, request_id=request_id)

    except Exception as exc:
        logger.exception("[%s] 分析失败", request_id)
        msg = f"分析失败: {type(exc).__name__}: {exc}"
        step_fail(request_id, "同步分析", msg)
        log_request(request_id, {
            "mode": "sync", "video_url": req.video_url,
            "status": "failed", "error": msg,
        })
        return ApiResult.error(500, "分析失败，请稍后重试", request_id=request_id)


# ─── 异步任务：提交 ────────────────────────────────────

@router.post("/tasks", response_model=ApiResult)
async def submit_task(req: AnalyzeRequest):
    """
    异步提交分析任务，立即返回 task_id。
    调用方通过 GET /tasks/{task_id} 轮询结果。
    """
    if not (settings.api_key or "").strip():
        return ApiResult.error(
            500,
            "服务未配置 LLM 密钥",
        )

    # 如果调用方传了自定义标签体系，先校验格式
    if req.tags is not None:
        errors = validate_tag_schema(req.tags)
        if errors:
            return ApiResult.error(400, f"tags 格式错误: {'; '.join(errors)}")

    task = await task_store.create(req.video_url, custom_tags=req.tags)

    # 后台执行分析 —— 持有引用防 GC，完成后自动移除
    bg = asyncio.create_task(_run_analysis(task.task_id, req.video_url, custom_tags=req.tags, custom_prompt=req.prompt))
    _background_tasks.add(bg)
    bg.add_done_callback(_background_tasks.discard)

    return ApiResult.ok({
        "task_id": task.task_id,
        "status": task.status.value,
        "message": "任务已提交，请通过 GET /api/video-analyze/tasks/{task_id} 轮询结果",
    })


# ─── 异步任务：查询状态（轮询） ──────────────────────────

@router.get("/tasks/{task_id}", response_model=ApiResult)
async def get_task(task_id: str):
    """
    查询任务状态与结果。
    - pending: 排队中
    - processing: 分析中
    - completed: 完成（result 字段包含标签）
    - failed: 失败（error 字段包含原因）
    """
    task = await task_store.get(task_id)
    if task is None or task.task_type != "analyze":
        return ApiResult.error(404, f"任务不存在或已过期: {task_id}")
    return ApiResult.ok(task.to_dict())


# ─── 异步任务：列表 ─────────────────────────────────────

@router.get("/tasks", response_model=ApiResult)
async def list_tasks(
    status: str = Query(default=None, description="按状态筛选: pending/processing/completed/failed"),
    limit: int = Query(default=50, ge=1, le=200, description="返回数量上限"),
):
    """列出所有标签分析任务（支持按状态筛选）。"""
    all_tasks = await task_store.list_all()
    # 只保留 analyze 类型（排除 clip）
    all_tasks = [t for t in all_tasks if t.get("task_type") == "analyze"]
    if status:
        all_tasks = [t for t in all_tasks if t["status"] == status]
    # 按创建时间倒序
    all_tasks.sort(key=lambda t: t["created_at"], reverse=True)
    return ApiResult.ok(all_tasks[:limit])


# ─── 标签模板管理 ──────────────────────────────────────

@router.get("/tags", response_model=ApiResult)
async def get_tags():
    """获取当前标签模板。"""
    try:
        return ApiResult.ok(get_tag_schema())
    except Exception:
        logger.exception("获取标签模板失败")
        return ApiResult.error(500, "获取标签模板失败")


@router.put("/tags", response_model=ApiResult)
async def put_tags(new_tags: dict):
    """
    上传/替换标签模板。
    请求体就是完整的标签 JSON，格式与 video_tags.json 相同。
    上传后立即生效，后续 /analyze 请求会使用新模板。
    """
    try:
        stats = update_tag_schema(new_tags)
        return ApiResult.ok(stats)
    except ValueError as e:
        return ApiResult.error(400, str(e))
    except Exception:
        logger.exception("更新标签模板失败")
        return ApiResult.error(500, "更新标签模板失败")


# ─── 内部实现 ──────────────────────────────────────────

async def _run_analysis(task_id: str, video_url: str, *, custom_tags: dict | None = None, custom_prompt: str | None = None) -> None:
    """后台执行分析任务。"""
    step_start(task_id, "异步分析")
    await task_store.set_processing(task_id)

    try:
        prompt = build_tag_prompt(override_tags=custom_tags, extra_prompt=custom_prompt or "")
        async with get_llm_semaphore():
            result_text = await llm_service.analyze(video_url, prompt)
        raw_tags = parse_json_result(result_text)

        if "raw_content" in raw_tags:
            await task_store.set_completed(task_id, raw_tags)
            step_done(task_id, "异步分析(raw)")
            log_request(task_id, {
                "mode": "async", "video_url": video_url,
                "status": "completed", "raw": True, "result": raw_tags,
            })
            return

        tags, removed = sanitize_tags(raw_tags, override_tags=custom_tags)
        if removed:
            logger.warning("[%s] 清洗掉 %d 个非法标签: %s", task_id[:8], len(removed), removed)

        await task_store.set_completed(task_id, tags)
        step_done(task_id, "异步分析")
        log_request(task_id, {
            "mode": "async", "video_url": video_url,
            "status": "completed", "result": tags, "removed_tags": removed,
        })

    except httpx.TimeoutException:
        msg = "分析超时，LLM 服务响应过慢"
        await task_store.set_failed(task_id, msg, 504)
        step_fail(task_id, "异步分析", msg)
        log_request(task_id, {
            "mode": "async", "video_url": video_url, "status": "failed", "error": msg,
        })

    except httpx.HTTPStatusError as e:
        msg = f"LLM 服务错误: HTTP {e.response.status_code}"
        await task_store.set_failed(task_id, msg, 502)
        step_fail(task_id, "异步分析", msg)
        log_request(task_id, {
            "mode": "async", "video_url": video_url, "status": "failed", "error": msg,
        })

    except httpx.ConnectError:
        msg = "无法连接 LLM 服务，请检查网络或 API 地址"
        await task_store.set_failed(task_id, msg, 503)
        step_fail(task_id, "异步分析", msg)
        log_request(task_id, {
            "mode": "async", "video_url": video_url, "status": "failed", "error": msg,
        })

    except ValueError as e:
        # 上游返回结构异常/不可解析时，按上游错误处理，避免误报 500
        msg = f"LLM 响应格式异常: {e}"
        await task_store.set_failed(task_id, msg, 502)
        step_fail(task_id, "异步分析", msg)
        log_request(task_id, {
            "mode": "async", "video_url": video_url, "status": "failed", "error": msg,
        })

    except Exception as exc:
        logger.exception("[%s] 异步分析失败", task_id[:8])
        msg = f"分析失败: {type(exc).__name__}: {exc}"
        await task_store.set_failed(task_id, msg, 500)
        step_fail(task_id, "异步分析", msg)
        log_request(task_id, {
            "mode": "async", "video_url": video_url, "status": "failed", "error": msg,
        })
