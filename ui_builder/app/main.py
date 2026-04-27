"""
UI Builder 微服务：上传 UI 示意图，分析并生成 Unity 预制体数据。

部署架构：Docker → Nacos 注册 → Nginx 反向代理 → FastAPI Token 鉴权。
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.middleware.auth import (
    TokenAuthMiddleware,
    start_nacos_token_watcher,
    stop_nacos_token_watcher,
)
from app.routers import analyze, health
from app.routers.health import set_ready
from app.utils.logger import setup_logging, start_log_cleanup, stop_log_cleanup

# 初始化日志系统（文件 + 控制台）
setup_logging()
logger = logging.getLogger(__name__)

# ─── Nacos 服务注册（完整版：含心跳） ─────────────────────

_nacos_server = settings.nacos_server_addr
_nacos_enabled = settings.nacos_enabled

# 延迟导入，nacos_registry.py 位于项目根目录（ui_builder/）
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
from nacos_registry import NacosRegistry

nacos = NacosRegistry(
    service_name=settings.nacos_service_name if hasattr(settings, 'nacos_service_name') else settings.service_name,
    service_port=settings.port,
    server_addr=_nacos_server,
    namespace=settings.nacos_namespace if hasattr(settings, 'nacos_namespace') else "",
    group=settings.nacos_group if hasattr(settings, 'nacos_group') else "DEFAULT_GROUP",
    username=settings.nacos_username if hasattr(settings, 'nacos_username') else "nacos",
    password=settings.nacos_password if hasattr(settings, 'nacos_password') else "nacos",
    enabled=_nacos_enabled,
)


# ─── Lifespan ───────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.http_client = httpx.AsyncClient(timeout=settings.timeout)
    logger.info(
        "UI Builder started | host=%s | port=%s | model=%s",
        settings.host, settings.port, settings.model,
    )
    logger.info(
        "日志模式: %s",
        "文件+控制台" if settings.log_to_file else "仅控制台(stdout)",
    )
    if not (settings.api_key or "").strip():
        logger.warning(
            "LLM 密钥未设置：/analyze 将返回 500，请在 settings.yaml 的 llm.api_key 中配置"
        )

    # ⚠ 任务存储为内存模式，多实例部署时各实例的任务状态不共享
    logger.info("任务存储: 内存模式（单实例）")

    # Nacos 注册（含心跳）+ Token 配置监听
    await nacos.register()
    await start_nacos_token_watcher(settings.service_name)
    start_log_cleanup()

    # 标记就绪 —— Nginx/Nacos/K8s 探针开始放行流量
    set_ready(True)
    logger.info("服务就绪，开始接受请求")

    yield

    # ─── 优雅停机 ───────────────────────────────────────
    logger.info("收到停机信号，开始优雅停机...")
    set_ready(False)

    stop_log_cleanup()
    await stop_nacos_token_watcher()
    await nacos.deregister()

    if settings.http_client is not None:
        await settings.http_client.aclose()
        settings.http_client = None
    logger.info("UI Builder shutdown complete")


app = FastAPI(
    title="UI Builder",
    description="上传图片，AI 分析生成 Unity 预制体数据",
    lifespan=lifespan,
)

# ─── 鉴权中间件（settings.yaml 中 auth.tokens 为空时自动跳过）─────────────
app.add_middleware(TokenAuthMiddleware)


# ─── 全局请求日志中间件 ─────────────────────────────────

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
    start = time.time()
    logger.info(
        "→ %s %s [%s]",
        request.method, request.url.path, request_id,
    )
    try:
        response = await call_next(request)
        elapsed = time.time() - start
        logger.info(
            "← %s %s [%s] %d (%.1fms)",
            request.method, request.url.path, request_id,
            response.status_code, elapsed * 1000,
        )
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        elapsed = time.time() - start
        logger.exception(
            "← %s %s [%s] 500 (%.1fms) UNHANDLED",
            request.method, request.url.path, request_id, elapsed * 1000,
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": 500,
                "message": "服务内部错误",
                "request_id": request_id,
            },
        )


app.include_router(analyze.router)
app.include_router(health.router)
