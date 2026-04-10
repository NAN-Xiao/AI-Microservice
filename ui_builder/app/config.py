"""
ui_builder 专用配置（与 video_analyze 完全独立，无共享模块或配置文件）。

加载顺序：
1. settings.example.yaml（仓库内默认，勿写真实密钥）
2. settings.yaml（本地覆盖；路径可用 UI_BUILDER_CONFIG 指定）
3. 环境变量覆盖：HOST、PORT、DEBUG、LLM_API_URL、LLM_API_KEY、LLM_MODEL、LLM_TIMEOUT
"""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

# 项目根目录 = ui_builder/（app/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

_EXAMPLE_PATH = PROJECT_ROOT / "settings.example.yaml"
_LOCAL_PATH = Path(os.environ.get("UI_BUILDER_CONFIG", str(PROJECT_ROOT / "settings.yaml")))


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


def _from_env(key: str, file_val: Any, cast=str) -> Any:
    """环境变量存在则优先（含空字符串），否则用配置文件中的值。"""
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

    host = _from_env("HOST", _server_get(c, "host", "127.0.0.1"))
    port = _from_env("PORT", _server_get(c, "port", 9002), int)
    debug_env = os.environ.get("DEBUG")
    if debug_env is not None:
        debug = debug_env.lower() in ("1", "true", "yes")
    else:
        debug = bool(_server_get(c, "debug", False))

    api_url = str(_from_env("LLM_API_URL", _llm_get(c, "api_url", ""))).rstrip("/")
    api_key = str(_from_env("LLM_API_KEY", _llm_get(c, "api_key", "")))
    model = str(_from_env("LLM_MODEL", _llm_get(c, "model", "")))
    timeout = _from_env("LLM_TIMEOUT", _llm_get(c, "timeout_seconds", 300), int)
    service_name = str(_service_get(c, "name", "ui-builder"))

    # SSL 证书路径（相对于项目根目录）
    ssl_certfile = _server_get(c, "ssl_certfile", "")
    ssl_keyfile = _server_get(c, "ssl_keyfile", "")
    if ssl_certfile:
        ssl_certfile = str(PROJECT_ROOT / ssl_certfile)
    if ssl_keyfile:
        ssl_keyfile = str(PROJECT_ROOT / ssl_keyfile)

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
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
        log_to_file=log_to_file,
        http_client=None,
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
    ssl_certfile: str
    ssl_keyfile: str
    log_to_file: bool
    http_client: Optional[httpx.AsyncClient]


settings = _build_settings()
