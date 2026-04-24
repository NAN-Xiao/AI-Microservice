"""
ui_builder 专用配置（与 video_analyze 完全独立，无共享模块或配置文件）。

加载来源：
1. settings.yaml（唯一配置来源，写真实密钥）

说明：
- 本服务只读取配置文件，不读取任何环境变量。
- settings.example.yaml 仅作为模板，不参与运行时加载。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

# 项目根目录 = ui_builder/（app/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

_LOCAL_PATH = PROJECT_ROOT / "settings.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def _load_file_config() -> dict[str, Any]:
    return _load_yaml(_LOCAL_PATH)


def _server_get(cfg: dict[str, Any], key: str, default: Any) -> Any:
    s = cfg.get("server") or {}
    return s.get(key, default) if isinstance(s, dict) else default


def _llm_get(cfg: dict[str, Any], key: str, default: Any) -> Any:
    s = cfg.get("llm") or {}
    return s.get(key, default) if isinstance(s, dict) else default


def _service_get(cfg: dict[str, Any], key: str, default: Any) -> Any:
    s = cfg.get("service") or {}
    return s.get(key, default) if isinstance(s, dict) else default


def _auth_get(cfg: dict[str, Any], key: str, default: Any) -> Any:
    s = cfg.get("auth") or {}
    return s.get(key, default) if isinstance(s, dict) else default


def _nacos_get(cfg: dict[str, Any], key: str, default: Any) -> Any:
    s = cfg.get("nacos") or {}
    return s.get(key, default) if isinstance(s, dict) else default


def _to_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
    return default


def _build_settings() -> "Settings":
    c = _load_file_config()

    host = str(_server_get(c, "host", "127.0.0.1"))
    port = _to_int(_server_get(c, "port", 9002), 9002)
    debug = _to_bool(_server_get(c, "debug", False), False)

    api_url = str(_llm_get(c, "api_url", "")).rstrip("/")
    api_key = str(_llm_get(c, "api_key", ""))
    model = str(_llm_get(c, "model", ""))
    timeout = _to_int(_llm_get(c, "timeout_seconds", 300), 300)
    llm_concurrency = _to_int(_llm_get(c, "concurrency", 5), 5)
    image_max_long_side = _to_int(_llm_get(c, "image_max_long_side", 1024), 1024)
    image_quality = _to_int(_llm_get(c, "image_quality", 80), 80)
    service_name = str(_service_get(c, "name", "ui-builder"))

    # SSL 证书路径（相对于项目根目录）
    ssl_certfile = _server_get(c, "ssl_certfile", "")
    ssl_keyfile = _server_get(c, "ssl_keyfile", "")
    if ssl_certfile:
        ssl_certfile = str(PROJECT_ROOT / ssl_certfile)
    if ssl_keyfile:
        ssl_keyfile = str(PROJECT_ROOT / ssl_keyfile)

    log_to_file = _to_bool(_server_get(c, "log_to_file", True), True)
    auth_tokens = str(_auth_get(c, "tokens", ""))

    return Settings(
        host=host,
        port=port,
        debug=debug,
        api_url=api_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
        llm_concurrency=llm_concurrency,
        image_max_long_side=image_max_long_side,
        image_quality=image_quality,
        service_name=service_name,
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
        log_to_file=log_to_file,
        auth_tokens=auth_tokens,
        http_client=None,
        # -------- Nacos 服务注册配置 --------
        nacos_enabled=_to_bool(_nacos_get(c, "enabled", True), True),
        nacos_server_addr=str(_nacos_get(c, "server_addr", "127.0.0.1:8848")),
        nacos_service_name=str(_nacos_get(c, "service_name", "ui-builder-service")),
        nacos_namespace=str(_nacos_get(c, "namespace", "")),
        nacos_group=str(_nacos_get(c, "group", "DEFAULT_GROUP")),
        nacos_username=str(_nacos_get(c, "username", "nacos")),
        nacos_password=str(_nacos_get(c, "password", "nacos")),
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
    llm_concurrency: int
    image_max_long_side: int
    image_quality: int
    service_name: str
    ssl_certfile: str
    ssl_keyfile: str
    log_to_file: bool
    auth_tokens: str
    http_client: Optional[httpx.AsyncClient]
    # -------- Nacos 服务注册配置 --------
    nacos_enabled: bool
    nacos_server_addr: str
    nacos_service_name: str
    nacos_namespace: str
    nacos_group: str
    nacos_username: str
    nacos_password: str


settings = _build_settings()
