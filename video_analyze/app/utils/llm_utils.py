"""
LLM 通用工具：并发控制、JSON 结果解析。
供 analyze 和 clip 等模块复用。
"""

import asyncio
import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)

_llm_semaphore: asyncio.Semaphore | None = None


def get_llm_semaphore() -> asyncio.Semaphore:
    """懒初始化 LLM 并发信号量（限制同时对 LLM 的请求数）。"""
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(settings.llm_concurrency)
    return _llm_semaphore


def parse_json_result(text: str) -> dict:
    """
    剥离 markdown 代码围栏并解析 JSON。
    如果解析失败或结果不是 dict，返回 {"raw_content": text}。
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
        logger.warning("LLM 返回 JSON 但不是对象: %s", type(parsed).__name__)
        return {"raw_content": text}
    except json.JSONDecodeError:
        logger.warning("LLM 返回非 JSON，原样返回")
        return {"raw_content": text}
