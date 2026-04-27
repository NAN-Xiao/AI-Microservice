"""
See Through 配置。
加载顺序：
1. settings.example.yaml
2. settings.yaml（可通过 SEE_THROUGH_CONFIG 指定）
3. 环境变量覆盖
"""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_EXAMPLE_PATH = PROJECT_ROOT / "settings.example.yaml"
_LOCAL_PATH = Path(os.environ.get("SEE_THROUGH_CONFIG", str(PROJECT_ROOT / "settings.yaml")))


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


def _section_get(cfg: dict[str, Any], section: str, key: str, default: Any) -> Any:
    sec = cfg.get(section) or {}
    return sec.get(key, default) if isinstance(sec, dict) else default


def _from_env(key: str, file_val: Any, cast=str) -> Any:
    if key not in os.environ:
        if cast is int:
            return int(file_val)
        if cast is float:
            return float(file_val)
        if file_val is None:
            return ""
        return str(file_val)
    raw = os.environ[key]
    if cast is int:
        return int(raw)
    if cast is float:
        return float(raw)
    return raw


def _build_settings() -> "Settings":
    c = _load_file_config()

    host = _from_env("HOST", _section_get(c, "server", "host", "127.0.0.1"))
    port = _from_env("PORT", _section_get(c, "server", "port", 9004), int)

    debug_env = os.environ.get("DEBUG")
    if debug_env is not None:
        debug = debug_env.lower() in ("1", "true", "yes")
    else:
        debug = bool(_section_get(c, "server", "debug", False))

    log_to_file_env = os.environ.get("LOG_TO_FILE")
    if log_to_file_env is not None:
        log_to_file = log_to_file_env.lower() in ("1", "true", "yes")
    else:
        log_to_file = bool(_section_get(c, "server", "log_to_file", True))

    service_name = str(_section_get(c, "service", "name", "see_through"))

    comfyui_base_url = str(_from_env("COMFYUI_BASE_URL", _section_get(c, "comfyui", "base_url", ""))).rstrip("/")
    comfyui_timeout = _from_env("COMFYUI_TIMEOUT", _section_get(c, "comfyui", "timeout_seconds", 300), int)
    comfyui_poll_interval = _from_env("COMFYUI_POLL_INTERVAL", _section_get(c, "comfyui", "poll_interval_seconds", 1), float)
    comfyui_concurrency = _from_env("COMFYUI_CONCURRENCY", _section_get(c, "comfyui", "concurrency", 0), int)
    workflow_path = str(_from_env("COMFYUI_WORKFLOW_PATH", _section_get(c, "comfyui", "workflow_path", "resources/workflow.json")))
    workflow_input_node_id = str(_from_env("COMFYUI_WORKFLOW_INPUT_NODE_ID", _section_get(c, "comfyui", "workflow_input_node_id", "27")))
    workflow_input_field = str(_from_env("COMFYUI_WORKFLOW_INPUT_FIELD", _section_get(c, "comfyui", "workflow_input_field", "image")))
    comfyui_client_id = str(_from_env("COMFYUI_CLIENT_ID", _section_get(c, "comfyui", "client_id", "")))

    return Settings(
        host=host,
        port=port,
        debug=debug,
        log_to_file=log_to_file,
        service_name=service_name,
        comfyui_base_url=comfyui_base_url,
        comfyui_timeout=comfyui_timeout,
        comfyui_poll_interval=comfyui_poll_interval,
        comfyui_concurrency=comfyui_concurrency,
        workflow_path=workflow_path,
        workflow_input_node_id=workflow_input_node_id,
        workflow_input_field=workflow_input_field,
        comfyui_client_id=comfyui_client_id,
        nacos_enabled=_from_env("NACOS_ENABLED", _section_get(c, "nacos", "enabled", "true")),
        nacos_server_addr=_from_env("NACOS_SERVER_ADDR", _section_get(c, "nacos", "server_addr", "127.0.0.1:8848")),
        nacos_service_name=_from_env("NACOS_SERVICE_NAME", _section_get(c, "nacos", "service_name", "see-through-service")),
        nacos_namespace=_from_env("NACOS_NAMESPACE", _section_get(c, "nacos", "namespace", "")),
        nacos_group=_from_env("NACOS_GROUP", _section_get(c, "nacos", "group", "DEFAULT_GROUP")),
        nacos_username=_from_env("NACOS_USERNAME", _section_get(c, "nacos", "username", "nacos")),
        nacos_password=_from_env("NACOS_PASSWORD", _section_get(c, "nacos", "password", "nacos")),
    )


@dataclass
class Settings:
    host: str
    port: int
    debug: bool
    log_to_file: bool
    service_name: str

    comfyui_base_url: str
    comfyui_timeout: int
    comfyui_poll_interval: float
    comfyui_concurrency: int
    workflow_path: str
    workflow_input_node_id: str
    workflow_input_field: str
    comfyui_client_id: str

    nacos_enabled: str
    nacos_server_addr: str
    nacos_service_name: str
    nacos_namespace: str
    nacos_group: str
    nacos_username: str
    nacos_password: str


settings = _build_settings()
