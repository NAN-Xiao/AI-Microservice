"""
LLM 客户端：调用 OpenAI 兼容 API 分析 UI 图片。
使用 system + user 双消息结构，支持取消。
"""

import asyncio
import base64
import logging
import mimetypes

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class CancelledError(Exception):
    """任务被用户取消。"""


async def analyze_image(image_bytes: bytes, filename: str,
                        system_prompt: str, user_prompt: str,
                        cancel_event: asyncio.Event | None = None) -> str:
    """图片 + system/user prompt → 调用 LLM → 返回结果文本。

    cancel_event: 若被 set()，请求将被中断并抛出 CancelledError。
    """
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

    if cancel_event is None:
        resp = await client.post(
            f"{settings.api_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {settings.api_key}"},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def _do_request():
        return await client.post(
            f"{settings.api_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {settings.api_key}"},
        )

    async def _wait_cancel():
        await cancel_event.wait()

    request_task = asyncio.create_task(_do_request())
    cancel_task = asyncio.create_task(_wait_cancel())

    done, pending = await asyncio.wait(
        {request_task, cancel_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    for t in pending:
        t.cancel()

    if cancel_task in done:
        request_task.cancel()
        raise CancelledError("用户取消了分析任务")

    resp = request_task.result()
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
