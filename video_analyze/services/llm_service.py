"""
LLM 服务：调用 Qwen（OpenAI 兼容 API）分析视频。
"""

import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)


async def analyze(video_url: str, prompt: str) -> str:
    """传入视频 URL + 提示词 → 调用 LLM → 返回结果文本。"""
    payload = {
        "model": settings.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "video_url", "video_url": {"url": video_url}},
                ],
            }
        ],
    }

    logger.info("调用 LLM: model=%s, video_url=%s", settings.model, video_url)

    async with httpx.AsyncClient(timeout=settings.timeout) as client:
        resp = await client.post(
            f"{settings.api_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {settings.api_key}"},
        )
        resp.raise_for_status()
        result = resp.json()

    return result["choices"][0]["message"]["content"]
