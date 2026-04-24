"""
UI 分析 API（异步）  
POST /submit  — 提交图片，返回 taskId  
GET  /task/{task_id} — 查询进度与结果  
POST /analyze — 旧版同步接口（兼容）
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime

import httpx
from fastapi import APIRouter, UploadFile, File, Form

from app.utils import console_log as log
from app.utils.image_util import get_image_size, compress_for_llm
from app.config import settings, PROJECT_ROOT
from app.models.response import ApiResult
from app.services import llm_client
from app.services import task_store
from app.services.prompt_builder import build_system_prompt, build_user_prompt
from app.services.unity_mapper import map_to_unity
from app.utils.logger import log_request

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _save_json_log(tag: str, data: dict):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = LOG_DIR / f"{ts}_{tag}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("已保存 %s → %s", tag, path)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ui-builder", tags=["UI 分析"])

MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB

# LLM 并发信号量：限制同时调用上游 LLM 的请求数
_llm_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(settings.llm_concurrency)
    return _llm_semaphore

# 异步分析接口

@router.post("/submit", response_model=ApiResult)
async def submit(
    image: UploadFile = File(..., description="UI 示意图（png/jpg/webp）"),
    extra_prompt: str = Form("", description="额外提示词"),
    resolution: str = Form("1920x1080", description="目标分辨率，如 1920x1080"),
):
    """提交图片，返回 taskId，由后台异步分析"""
    if not image.content_type or not image.content_type.startswith("image/"):
        return ApiResult.error(400, f"仅支持图片文件，当前类型: {image.content_type}")

    if not (settings.api_key or "").strip():
        return ApiResult.error(
            500,
            "服务未配置 LLM 密钥：请在 ui_builder/settings.yaml 的 llm.api_key 填写。",
        )

    image_bytes = await image.read()
    if len(image_bytes) > MAX_IMAGE_SIZE:
        return ApiResult.error(400, f"图片过大，最大 {MAX_IMAGE_SIZE // (1024*1024)} MB")

    filename = image.filename or "image.png"
    target_w, target_h = _parse_resolution(resolution)
    task_id = uuid.uuid4().hex
    task_store.create(task_id)

    asyncio.create_task(
        _run_analysis(task_id, image_bytes, filename, extra_prompt,
                      target_w, target_h)
    )

    return ApiResult.ok({"taskId": task_id})


@router.get("/task/{task_id}", response_model=ApiResult)
async def get_task(task_id: str):
    """查询任务进度"""
    task_store.cleanup_old()
    task = task_store.get(task_id)
    if task is None:
        return ApiResult.error(404, "任务不存在或已过期")
    return ApiResult.ok(task_store.to_dict(task))


@router.post("/cancel/{task_id}", response_model=ApiResult)
async def cancel_task(task_id: str):
    """取消正在进行的分析任务"""
    ok = task_store.cancel(task_id)
    if not ok:
        task = task_store.get(task_id)
        if task is None:
            return ApiResult.error(404, "任务不存在或已过期")
        return ApiResult.error(400, f"任务状态为 {task.status}，无法取消")
    logger.info("任务 %s 已被用户取消", task_id)
    return ApiResult.ok({"taskId": task_id, "status": "cancelled", "step": "已取消"})


async def _run_analysis(task_id: str, image_bytes: bytes, filename: str,
                        extra_prompt: str, target_w: int, target_h: int):
    """异步执行完整分析流程，更新进度。支持通过 task_store.cancel() 中断。"""
    rid = task_id
    log.request_start(rid, filename, len(image_bytes) // 1024, extra_prompt)

    task = task_store.get(task_id)
    cancel_event = task.cancel_event if task else None

    img_size = get_image_size(image_bytes)
    img_w = img_size[0] if img_size else target_w
    img_h = img_size[1] if img_size else target_h

    try:
        if task_store.is_cancelled(task_id):
            log.request_fail(rid, "任务在启动前已取消")
            return

        task_store.update_step(task_id, "思考中")
        log.step(rid, "构建 Prompt", f"图片 {img_w}x{img_h} → 目标 {target_w}x{target_h}")

        # 压缩图片再送入 LLM
        orig_kb = len(image_bytes) / 1024
        image_bytes, filename = compress_for_llm(
            image_bytes,
            max_long_side=settings.image_max_long_side,
            quality=settings.image_quality,
        )
        comp_kb = len(image_bytes) / 1024
        log.step(rid, "图片压缩", f"{orig_kb:.0f}KB → {comp_kb:.0f}KB (max_side={settings.image_max_long_side})")

        system_prompt = build_system_prompt(img_w, img_h)
        user_prompt = build_user_prompt(extra_prompt)
        log.step_done(rid, "构建 Prompt")

        if task_store.is_cancelled(task_id):
            log.request_fail(rid, "任务在调用 LLM 前被取消")
            return

        task_store.update_step(task_id, "AI分析中")
        log.step(rid, "调用 LLM", f"model={settings.model}")

        async with _get_semaphore():
            result_text = await llm_client.analyze_image(
                image_bytes, filename,
                system_prompt, user_prompt,
                cancel_event=cancel_event,
            )
        log.step_done(rid, "调用 LLM", f"返回 {len(result_text)} 字符")

        if task_store.is_cancelled(task_id):
            log.request_fail(rid, "任务在 LLM 返回后被取消")
            return

        task_store.update_step(task_id, "解析结果")
        log.step(rid, "解析 JSON")
        raw_json = _parse_json_result(result_text)
        if "raw_content" in raw_json:
            log.request_fail(rid, "LLM 返回非 JSON")
            task_store.fail(task_id, 502, "LLM 返回非 JSON 数据，请重试")
            return
        log.step_done(rid, "解析 JSON")
        _save_json_log("figma", raw_json)

        if task_store.is_cancelled(task_id):
            log.request_fail(rid, "任务在映射前被取消")
            return

        task_store.update_step(task_id, "构建结构")
        log.step(rid, "Figma → Unity 映射", f"缩放 {img_w}x{img_h} → {target_w}x{target_h}")
        unity_data = map_to_unity(raw_json, img_w, img_h, target_w, target_h)
        node_count = _count_nodes(unity_data)
        log.step_done(rid, "Figma → Unity 映射", f"{node_count} 个节点")
        _save_json_log("unity", unity_data)

        task_store.complete(task_id, unity_data)
        log.request_ok(rid, f"节点数 {node_count}")

    except llm_client.CancelledError:
        logger.info("任务 %s 已被用户取消（LLM 请求中断）", task_id)
        log.request_fail(rid, "用户取消")

    except httpx.TimeoutException:
        logger.error("LLM 请求超时")
        log.request_fail(rid, f"LLM 超时（timeout={settings.timeout}s）")
        task_store.fail(task_id, 504, "分析超时，LLM 服务响应过慢")

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        detail = _llm_error_body_preview(e.response)
        logger.error("LLM 返回错误: HTTP %s detail=%s", status, detail or "(empty)")
        log.request_fail(rid, f"LLM HTTP {status}: {detail or '(无详情)'}")
        task_store.fail(task_id, 502, f"LLM 上游错误 HTTP {status}" + (f"：{detail}" if detail else ""))

    except httpx.ConnectError:
        logger.error("无法连接 LLM 服务")
        log.request_fail(rid, f"无法连接 LLM: {settings.api_url}")
        task_store.fail(task_id, 503, "无法连接 LLM 服务，请检查网络或 API 地址")

    except Exception:
        logger.exception("分析失败")
        log.request_fail(rid, "未知异常，详见上方 traceback")
        task_store.fail(task_id, 500, "分析失败，请稍后重试")


# 兼容旧同步API

@router.post("/analyze", response_model=ApiResult)
async def analyze(
    image: UploadFile = File(..., description="UI 示意图（png/jpg/webp）"),
    extra_prompt: str = Form("", description="额外提示词"),
    resolution: str = Form("1920x1080", description="目标分辨率，如 1920x1080"),
):
    """同步分析，直接返回结果（兼容旧接口）"""
    rid = uuid.uuid4().hex

    if not image.content_type or not image.content_type.startswith("image/"):
        log.request_fail(rid, f"文件类型不合法: {image.content_type}")
        return ApiResult.error(400, f"仅支持图片文件，当前类型: {image.content_type}")

    if not (settings.api_key or "").strip():
        log.request_fail(rid, "LLM 密钥未配置")
        return ApiResult.error(
            500,
            "服务未配置 LLM 密钥：请在 ui_builder/settings.yaml 的 llm.api_key 填写。",
        )

    try:
        image_bytes = await image.read()
        filename = image.filename or "image.png"
        target_w, target_h = _parse_resolution(resolution)
        img_size = get_image_size(image_bytes)
        img_w = img_size[0] if img_size else target_w
        img_h = img_size[1] if img_size else target_h
        log.request_start(rid, filename, len(image_bytes) // 1024, extra_prompt)

        if len(image_bytes) > MAX_IMAGE_SIZE:
            log.request_fail(rid, f"图片过大: {len(image_bytes) // (1024*1024)} MB")
            return ApiResult.error(400, f"图片过大，最大 {MAX_IMAGE_SIZE // (1024*1024)} MB")

        log.step(rid, "构建 Prompt")

        # 压缩图片再送入 LLM
        orig_kb = len(image_bytes) / 1024
        image_bytes, filename = compress_for_llm(
            image_bytes,
            max_long_side=settings.image_max_long_side,
            quality=settings.image_quality,
        )
        comp_kb = len(image_bytes) / 1024
        log.step(rid, "图片压缩", f"{orig_kb:.0f}KB → {comp_kb:.0f}KB (max_side={settings.image_max_long_side})")

        system_prompt = build_system_prompt(img_w, img_h)
        user_prompt = build_user_prompt(extra_prompt)
        log.step_done(rid, "构建 Prompt")

        log.step(rid, "调用 LLM", f"model={settings.model} img={img_w}x{img_h} target={target_w}x{target_h}")
        async with _get_semaphore():
            result_text = await llm_client.analyze_image(
                image_bytes, filename,
                system_prompt, user_prompt,
            )
        log.step_done(rid, "调用 LLM", f"返回 {len(result_text)} 字符")

        log.step(rid, "解析 JSON")
        raw_json = _parse_json_result(result_text)
        if "raw_content" in raw_json:
            log.request_fail(rid, "LLM 返回非 JSON")
            return ApiResult.error(502, "LLM 返回了非 JSON 数据，请重试")
        log.step_done(rid, "解析 JSON")

        log.step(rid, "Figma → Unity 映射")
        unity_data = map_to_unity(raw_json, img_w, img_h, target_w, target_h)
        node_count = _count_nodes(unity_data)
        log.step_done(rid, "Figma → Unity 映射", f"{node_count} 个节点")

        log.request_ok(rid, f"节点数 {node_count}")
        return ApiResult.ok(unity_data)

    except httpx.TimeoutException:
        logger.error("LLM 请求超时")
        log.request_fail(rid, f"LLM 超时（timeout={settings.timeout}s）")
        return ApiResult.error(504, "分析超时，LLM 服务响应过慢")

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        detail = _llm_error_body_preview(e.response)
        logger.error("LLM 返回错误: HTTP %s detail=%s", status, detail or "(empty)")
        log.request_fail(rid, f"LLM HTTP {status}: {detail or '(无详情)'}")
        msg = f"LLM 上游错误 HTTP {status}" + (f"：{detail}" if detail else "")
        return ApiResult.error(502, msg)

    except httpx.ConnectError:
        logger.error("无法连接 LLM 服务")
        log.request_fail(rid, f"无法连接 LLM: {settings.api_url}")
        return ApiResult.error(503, "无法连接 LLM 服务，请检查网络或 API 地址")

    except Exception:
        logger.exception("分析失败")
        log.request_fail(rid, "未知异常，详见上方 traceback")
        return ApiResult.error(500, "分析失败，请稍后重试")


# 工具方法

def _parse_resolution(raw: str) -> tuple[int, int]:
    """解析 '1920x1080' 文本分辨率，出错时用默认值"""
    try:
        parts = raw.lower().split("x")
        w, h = int(parts[0]), int(parts[1])
        if w > 0 and h > 0:
            return w, h
    except (ValueError, IndexError):
        pass
    return 1920, 1080


def _llm_error_body_preview(response: httpx.Response) -> str:
    try:
        data = response.json()
        err = data.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or err.get("code")
            if msg:
                return str(msg).strip()[:400]
        if isinstance(err, str) and err.strip():
            return err.strip()[:400]
    except Exception:
        pass
    text = (response.text or "").strip()
    return text[:400] if text else ""


def _count_nodes(node: dict) -> int:
    return 1 + sum(_count_nodes(c) for c in node.get("children", []) if isinstance(c, dict))


def _parse_json_result(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("LLM 返回非 JSON，原样返回")
        return {"raw_content": text}
