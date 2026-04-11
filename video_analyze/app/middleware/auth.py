"""
API Token 鉴权中间件。

调用方式与 OpenAI / 通义千问等 LLM API 一致：
  请求头: Authorization: Bearer <your-api-token>

Token 来源（优先级从高到低，合并取并集）：
1. Nacos 配置中心 —— 在 Nacos 控制台修改后 ~30s 自动热加载，不用重启
   Data ID = <service.name>  Group = AI_MICROSERVICE
   配置内容: auth_tokens: token-a,token-b
2. 环境变量 AUTH_TOKENS（作为兜底 / 本地开发用）

规则：
- 两处都为空 → 鉴权关闭，所有请求放行（本地开发）
- 含 /health 的路径始终放行（Docker 健康检查 / Nginx 探针）
- 含 /docs 或 /openapi.json 的路径始终放行（Swagger 文档）
"""

import asyncio
import logging
import os
import threading

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# ─── Token 存储（线程安全） ──────────────────────────────

# 环境变量 token（启动时加载，不变）
_raw = os.environ.get("AUTH_TOKENS", "").strip()
_ENV_TOKENS: frozenset[str] = (
    frozenset(t.strip() for t in _raw.split(",") if t.strip()) if _raw else frozenset()
)

# Nacos 推送的 token（热更新）
_nacos_lock = threading.Lock()
_nacos_tokens: set[str] = set()

# 对外暴露的合并视图
_ALLOWED_TOKENS: set[str] = set(_ENV_TOKENS)


def _parse_tokens(raw: str) -> set[str]:
    """从逗号分隔字符串解析 token 集合。"""
    return {t.strip() for t in raw.split(",") if t.strip()} if raw.strip() else set()


def _refresh_allowed():
    """合并环境变量 + Nacos token，更新公共集合。"""
    global _ALLOWED_TOKENS
    with _nacos_lock:
        _ALLOWED_TOKENS = set(_ENV_TOKENS) | set(_nacos_tokens)


def update_tokens_from_nacos(raw: str):
    """被 Nacos 配置监听回调调用，更新 token 集合（线程安全）。"""
    global _nacos_tokens
    new_tokens = _parse_tokens(raw)
    with _nacos_lock:
        if new_tokens != _nacos_tokens:
            _nacos_tokens = new_tokens
            logger.info("Nacos token 热更新: %d 个 token 生效", len(new_tokens))
    _refresh_allowed()


# ─── Nacos 配置监听 ─────────────────────────────────────

_NACOS_ADDR = os.environ.get("NACOS_ADDR", "").strip()
_NACOS_POLL_INTERVAL = 30  # 秒
_nacos_poll_task: asyncio.Task | None = None


async def _fetch_nacos_config(service_name: str) -> str | None:
    """从 Nacos HTTP API 拉取配置内容。"""
    if not _NACOS_ADDR:
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"http://{_NACOS_ADDR}/nacos/v1/cs/configs",
                params={
                    "dataId": service_name,
                    "group": "AI_MICROSERVICE",
                },
            )
            if resp.status_code == 200:
                return resp.text
    except Exception as e:
        logger.debug("Nacos 配置拉取失败: %s", e)
    return None


def _extract_auth_tokens(content: str) -> str:
    """从 Nacos 配置内容中提取 auth_tokens 值。
    支持 YAML 格式（auth_tokens: xxx）和纯文本格式（直接逗号分隔 token）。
    """
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("auth_tokens:"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    # 没有 auth_tokens: 前缀，当作纯逗号分隔 token 处理
    return content.strip()


async def _nacos_poll_loop(service_name: str):
    """后台轮询 Nacos 配置，发现变更时更新 token。"""
    logger.info("Nacos 配置监听已启动 (dataId=%s, 间隔=%ds)", service_name, _NACOS_POLL_INTERVAL)
    while True:
        try:
            await asyncio.sleep(_NACOS_POLL_INTERVAL)
            content = await _fetch_nacos_config(service_name)
            if content is not None:
                raw_tokens = _extract_auth_tokens(content)
                update_tokens_from_nacos(raw_tokens)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug("Nacos 配置轮询异常: %s", e)


async def start_nacos_token_watcher(service_name: str):
    """启动 Nacos 配置监听（在 lifespan 中调用）。首次拉取 + 后台定时轮询。"""
    global _nacos_poll_task
    if not _NACOS_ADDR:
        return
    # 首次拉取
    content = await _fetch_nacos_config(service_name)
    if content is not None:
        raw_tokens = _extract_auth_tokens(content)
        update_tokens_from_nacos(raw_tokens)
        logger.info("首次从 Nacos 加载 token 完成")
    else:
        logger.info("Nacos 无 %s 配置或不可达，仅使用环境变量 token", service_name)
    # 后台轮询
    _nacos_poll_task = asyncio.create_task(_nacos_poll_loop(service_name))


async def stop_nacos_token_watcher():
    """停止 Nacos 配置监听。"""
    global _nacos_poll_task
    if _nacos_poll_task and not _nacos_poll_task.done():
        _nacos_poll_task.cancel()
        try:
            await _nacos_poll_task
        except asyncio.CancelledError:
            pass
        _nacos_poll_task = None


# ─── 不需要鉴权的路径关键词 ─────────────────────────────

_PUBLIC_KEYWORDS = ("/health", "/docs", "/openapi.json")


# ─── 中间件 ─────────────────────────────────────────────

class TokenAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 鉴权未启用 → 直接放行
        if not _ALLOWED_TOKENS:
            return await call_next(request)

        # 公开路径放行（健康检查、Swagger 文档）
        path = request.url.path
        if any(kw in path for kw in _PUBLIC_KEYWORDS):
            return await call_next(request)

        # 提取 Bearer token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        else:
            token = ""

        if token not in _ALLOWED_TOKENS:
            logger.warning("鉴权失败: %s %s (token=%s...)", request.method, path, token[:8])
            return JSONResponse(
                status_code=401,
                content={"code": 401, "message": "Unauthorized: invalid or missing token"},
            )

        return await call_next(request)
