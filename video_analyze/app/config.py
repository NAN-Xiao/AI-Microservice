"""
video_analyze 专用配置（与 ui_builder 完全独立，无共享模块）。

加载顺序：
1. settings.example.yaml（仓库内默认，勿写真实密钥）
2. settings.yaml（本地覆盖；路径可用 VIDEO_ANALYZE_CONFIG 指定）
3. 环境变量覆盖：HOST、PORT、DEBUG、LLM_*、LLM_CONCURRENCY
"""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

# 项目根目录 = video_analyze/（app/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

_EXAMPLE_PATH = PROJECT_ROOT / "settings.example.yaml"
_LOCAL_PATH = Path(os.environ.get("VIDEO_ANALYZE_CONFIG", str(PROJECT_ROOT / "settings.yaml")))


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def _load_file_config() -> dict[str, Any]:
    example = _load_yaml(_EXAMPLE_PATH)
    local = _load_yaml(_LOCAL_PATH)
    if not example and not local:
        return {}
    return _deep_merge(example, local)


def _server_get(cfg: dict[str, Any], key: str, default: Any) -> Any:
    s = cfg.get("server") or {}
    return s.get(key, default) if isinstance(s, dict) else default


def _llm_get(cfg: dict[str, Any], key: str, default: Any) -> Any:
    s = cfg.get("llm") or {}
    return s.get(key, default) if isinstance(s, dict) else default


def _service_get(cfg: dict[str, Any], key: str, default: Any) -> Any:
    s = cfg.get("service") or {}
    return s.get(key, default) if isinstance(s, dict) else default


def _nacos_get(cfg: dict[str, Any], key: str, default: Any) -> Any:
    s = cfg.get("nacos") or {}
    return s.get(key, default) if isinstance(s, dict) else default



def _from_env(key: str, file_val: Any, cast=str) -> Any:
    if key not in os.environ:
        if cast is int:
            return int(file_val)
        if file_val is None:
            return ""
        return str(file_val)
    raw = os.environ[key]
    if cast is int:
        return int(raw)
    return raw


def _build_settings() -> "Settings":
    c = _load_file_config()

    host = _from_env("HOST", _server_get(c, "host", "0.0.0.0"))
    port = _from_env("PORT", _server_get(c, "port", 9001), int)
    debug_env = os.environ.get("DEBUG")
    if debug_env is not None:
        debug = debug_env.lower() in ("1", "true", "yes")
    else:
        debug = bool(_server_get(c, "debug", False))

    api_url = str(_from_env("LLM_API_URL", _llm_get(c, "api_url", ""))).rstrip("/")
    api_key = str(_from_env("LLM_API_KEY", _llm_get(c, "api_key", "")))
    model = str(_from_env("LLM_MODEL", _llm_get(c, "model", "")))
    timeout = _from_env("LLM_TIMEOUT", _llm_get(c, "timeout_seconds", 300), int)
    service_name = str(_service_get(c, "name", "video-analyze"))
    llm_concurrency = _from_env(
        "LLM_CONCURRENCY", _llm_get(c, "concurrency", 5), int
    )

    log_to_file_env = os.environ.get("LOG_TO_FILE")
    if log_to_file_env is not None:
        log_to_file = log_to_file_env.lower() in ("1", "true", "yes")
    else:
        log_to_file = bool(_server_get(c, "log_to_file", True))

    return Settings(
        host=host,
        port=port,
        debug=debug,
        api_url=api_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
        service_name=service_name,
        llm_concurrency=llm_concurrency,
        log_to_file=log_to_file,
        http_client=None,
        # -------- Nacos 服务注册配置 --------
        nacos_enabled=_from_env("NACOS_ENABLED", _nacos_get(c, "enabled", "true")),
        nacos_server_addr=_from_env("NACOS_SERVER_ADDR", _nacos_get(c, "server_addr", "127.0.0.1:8848")),
        nacos_service_name=_from_env("NACOS_SERVICE_NAME", _nacos_get(c, "service_name", "video-analyze-service")),
        nacos_namespace=_from_env("NACOS_NAMESPACE", _nacos_get(c, "namespace", "")),
        nacos_group=_from_env("NACOS_GROUP", _nacos_get(c, "group", "DEFAULT_GROUP")),
        nacos_username=_from_env("NACOS_USERNAME", _nacos_get(c, "username", "nacos")),
        nacos_password=_from_env("NACOS_PASSWORD", _nacos_get(c, "password", "nacos")),
    )


@dataclass
class Settings:
    host: str
    port: int
    debug: bool
    api_url: str
    api_key: str
    model: str
    timeout: int
    service_name: str
    llm_concurrency: int
    log_to_file: bool
    http_client: Optional[httpx.AsyncClient]
    # -------- Nacos 服务注册配置 --------
    nacos_enabled: str
    nacos_server_addr: str
    nacos_service_name: str
    nacos_namespace: str
    nacos_group: str
    nacos_username: str
    nacos_password: str


settings = _build_settings()
