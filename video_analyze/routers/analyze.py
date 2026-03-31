"""
视频标签分析路由。
"""

import json
import logging

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from models.response import ApiResult
from services import llm_service
from services.tag_schema import build_tag_prompt, sanitize_tags, get_tag_schema, update_tag_schema

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/video-analyze", tags=["视频分析"])


class AnalyzeRequest(BaseModel):
    video_url: str
    extra_prompt: str = ""


@router.post("/analyze", response_model=ApiResult)
async def analyze(req: AnalyzeRequest):
    """传入视频 URL → 返回标签 JSON。"""
    try:
        prompt = build_tag_prompt(req.extra_prompt)
        result_text = await llm_service.analyze(req.video_url, prompt)
        raw_tags = _parse_json_result(result_text)

        if "raw_content" in raw_tags:
            return ApiResult.ok(raw_tags)

        tags, removed = sanitize_tags(raw_tags)
        if removed:
            logger.warning("清洗掉 %d 个非法标签: %s", len(removed), removed)

        return ApiResult.ok(tags)

    except httpx.TimeoutException:
        logger.error("LLM 请求超时: %s", req.video_url)
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
