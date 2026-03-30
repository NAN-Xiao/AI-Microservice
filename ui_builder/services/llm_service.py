"""
LLM 服务：调用 Gemini API 分析 UI 图片。
使用 system + user 双消息结构。
"""

import base64
import logging
import mimetypes

import httpx

from config import settings

logger = logging.getLogger(__name__)


async def analyze_image(image_bytes: bytes, filename: str,
                        system_prompt: str, user_prompt: str) -> str:
    """图片 + system/user prompt → 调用 Gemini → 返回结果文本。"""
    client = settings.http_client
    if client is None:
        raise RuntimeError("HTTP client is not initialized")

    b64 = base64.b64encode(image_bytes).decode()
    mime = mimetypes.guess_type(filename)[0] or "image/png"
    data_uri = f"data:{mime};base64,{b64}"

    payload = {
        "model": settings.model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            },
        ],
    }

    logger.info("调用 LLM: model=%s, image=%s (%d bytes)", settings.model, filename, len(image_bytes))

    resp = await client.post(
        f"{settings.api_url}/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {settings.api_key}"},
    )
    resp.raise_for_status()
    result = resp.json()

    return result["choices"][0]["message"]["content"]
