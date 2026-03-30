"""
UI 分析路由：上传 UI 示意图 → Gemini 分析 → 清洗映射 → 返回 Unity 预制体数据。
"""

import json
import logging

import httpx
from fastapi import APIRouter, UploadFile, File, Form

from models.response import ApiResult
from services import llm_service
from services.ui_schema import build_system_prompt, build_user_prompt
from services.unity_mapper import map_to_unity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ui-builder", tags=["UI 分析"])

MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB


@router.post("/analyze", response_model=ApiResult)
async def analyze(
    image: UploadFile = File(..., description="UI 示意图（png/jpg/webp）"),
    extra_prompt: str = Form("", description="额外提示词"),
):
    """上传 UI 示意图 → 返回 Unity 预制体 JSON。"""
    if not image.content_type or not image.content_type.startswith("image/"):
        return ApiResult.error(400, f"仅支持图片文件，当前类型: {image.content_type}")

    try:
        image_bytes = await image.read()
        if len(image_bytes) > MAX_IMAGE_SIZE:
            return ApiResult.error(400, f"图片过大，最大 {MAX_IMAGE_SIZE // (1024*1024)} MB")

        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(extra_prompt)
        result_text = await llm_service.analyze_image(
            image_bytes, image.filename or "image.png",
            system_prompt, user_prompt,
        )
        raw_json = _parse_json_result(result_text)

        if "raw_content" in raw_json:
            return ApiResult.error(502, "LLM 返回了非 JSON 数据，请重试")

        unity_data = map_to_unity(raw_json)
        return ApiResult.ok(unity_data)

    except httpx.TimeoutException:
        logger.error("LLM 请求超时")
        return ApiResult.error(504, "分析超时，LLM 服务响应过慢")

    except httpx.HTTPStatusError as e:
        logger.error("LLM 返回错误: %s", e.response.status_code)
        return ApiResult.error(502, f"LLM 服务错误: HTTP {e.response.status_code}")

    except httpx.ConnectError:
        logger.error("无法连接 LLM 服务")
        return ApiResult.error(503, "无法连接 LLM 服务，请检查网络或 API 地址")

    except Exception:
        logger.exception("分析失败")
        return ApiResult.error(500, "分析失败，请稍后重试")


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
