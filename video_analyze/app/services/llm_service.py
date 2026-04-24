"""
LLM 服务：调用 Qwen（OpenAI 兼容 API）分析视频。
"""

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# 重试配置
_MAX_RETRIES = 2
_RETRY_BACKOFF = 1.0  # 秒，指数退避基数
_RETRYABLE_STATUS = {500, 502, 503, 429}


async def analyze(video_url: str, prompt: str) -> str:
    """传入视频 URL + 提示词 → 调用 LLM → 返回结果文本。"""
    client = settings.http_client
    if client is None:
        raise RuntimeError("HTTP client is not initialized")

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

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            if attempt > 0:
                wait = _RETRY_BACKOFF * (2 ** (attempt - 1))
                logger.info("LLM 重试 %d/%d (等待 %.1fs): video_url=%s", attempt, _MAX_RETRIES, wait, video_url)
                await asyncio.sleep(wait)

            logger.info("调用 LLM: model=%s, video_url=%s", settings.model, video_url)

            resp = await client.post(
                f"{settings.api_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {settings.api_key}"},
            )
            resp.raise_for_status()
            result = resp.json()

            # 防御性解析 LLM 响应
            choices = result.get("choices")
            if not choices or not isinstance(choices, list):
                raise ValueError(f"LLM 响应缺少 choices 字段: {list(result.keys())}")
            message = choices[0].get("message")
            if not message or "content" not in message:
                raise ValueError(f"LLM 响应缺少 message.content: {choices[0].keys()}")

            content = message["content"]
            # 兼容部分 OpenAI 兼容网关返回 content 为数组片段的情况
            if isinstance(content, list):
                text_parts: list[str] = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(str(part.get("text", "")))
                content = "\n".join(p for p in text_parts if p).strip()

            if not isinstance(content, str):
                raise ValueError(f"LLM 响应 content 类型异常: {type(content).__name__}")
            return content

        except httpx.HTTPStatusError as e:
            last_exc = e
            if e.response.status_code not in _RETRYABLE_STATUS:
                raise
            logger.warning("LLM HTTP %d，可重试", e.response.status_code)

        except (httpx.ConnectError, httpx.TimeoutException) as e:
            last_exc = e
            logger.warning("LLM 连接/超时异常: %s", type(e).__name__)

        except ValueError:
            raise  # 响应解析错误不重试

    # 所有重试耗尽
    raise last_exc  # type: ignore[misc]
