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
from services.tag_schema import build_tag_prompt

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
        tags = _parse_json_result(result_text)
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

    except Exception as e:
        logger.exception("分析失败")
        return ApiResult.error(500, f"分析失败: {e}")


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
