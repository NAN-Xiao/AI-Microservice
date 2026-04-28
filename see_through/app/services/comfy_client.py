from __future__ import annotations

import copy
import io
import json
import logging
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from PIL import Image
from psd_tools import PSDImage
from psd_tools.api.layers import PixelLayer

from app.config import PROJECT_ROOT, settings
from app.services.result_store import put_cleanup_data

logger = logging.getLogger(__name__)


class ComfyError(Exception):
    pass


SAVE_PSD_NODE_ID = "21"


def _load_workflow_template() -> dict[str, Any]:
    workflow_file = PROJECT_ROOT / settings.workflow_path
    if not workflow_file.is_file():
        raise ComfyError(f"工作流文件不存在: {workflow_file}")

    try:
        return json.loads(workflow_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ComfyError(f"工作流 JSON 格式错误: {exc}") from exc


def _inject_uploaded_image(workflow: dict[str, Any], uploaded_name: str) -> dict[str, Any]:
    node_id = settings.workflow_input_node_id
    field = settings.workflow_input_field

    nodes = workflow.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if str(node.get("id")) != node_id:
                continue
            widgets_values = node.get("widgets_values")
            if field == "image" and isinstance(widgets_values, list) and widgets_values:
                widgets_values[0] = uploaded_name
                return workflow
            inputs = node.get("inputs")
            if isinstance(inputs, dict):
                inputs[field] = uploaded_name
                return workflow
            raise ComfyError(f"节点 {node_id} 缺少可写入字段: {field}")
        raise ComfyError(f"工作流中未找到输入节点: {node_id}")

    node = workflow.get(node_id)
    if not isinstance(node, dict):
        raise ComfyError(f"工作流中未找到输入节点: {node_id}")

    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise ComfyError(f"节点 {node_id} 缺少 inputs 字段")

    inputs[field] = uploaded_name
    return workflow


def _inject_filename_prefix(
    workflow: dict[str, Any],
    filename_prefix: str,
    node_id: str = SAVE_PSD_NODE_ID,
) -> dict[str, Any]:
    node = workflow.get(node_id)
    if not isinstance(node, dict):
        return workflow

    inputs = node.get("inputs")
    if isinstance(inputs, dict):
        inputs["filename_prefix"] = filename_prefix
    return workflow


def _normalize_output_file(
    filename: str,
    subfolder: str = "",
    file_type: str = "output",
) -> dict[str, str]:
    raw_filename = str(filename or "").strip().replace("\\", "/")
    raw_subfolder = str(subfolder or "").strip().replace("\\", "/").strip("/")

    if raw_filename and not raw_subfolder and "/" in raw_filename:
        path = PurePosixPath(raw_filename)
        parent = str(path.parent)
        if parent and parent != ".":
            raw_filename = path.name
            raw_subfolder = parent

    return {
        "filename": raw_filename,
        "subfolder": raw_subfolder,
        "type": str(file_type or "output"),
    }


def _basename_matches_prefix(filename: str, filename_prefix: str) -> bool:
    basename = PurePosixPath(str(filename or "").replace("\\", "/")).name
    return basename.startswith(filename_prefix) and basename.endswith("_layers.json")


def _extract_file_candidates(value: Any, out: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        if "filename" in value and isinstance(value["filename"], str):
            out.append(_normalize_output_file(
                value["filename"],
                str(value.get("subfolder", "")),
                str(value.get("type", "output")),
            ))
        for v in value.values():
            _extract_file_candidates(v, out)
    elif isinstance(value, str):
        lowered = value.lower()
        if lowered.endswith("_layers.json") or (lowered.endswith(".json") and "layer" in lowered):
            out.append(_normalize_output_file(value))
    elif isinstance(value, list):
        for item in value:
            _extract_file_candidates(item, out)


def _list_output_files(history_payload: dict[str, Any]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    _extract_file_candidates(history_payload, candidates)

    deduped = []
    seen = set()
    for item in candidates:
        key = (item["filename"], item["subfolder"], item["type"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    return deduped


def _pick_layers_info_output(history_payload: dict[str, Any]) -> dict[str, str] | None:
    deduped = _list_output_files(history_payload)

    for item in deduped:
        filename = item["filename"].lower()
        if filename.endswith("_layers.json"):
            return item

    for item in deduped:
        if item["filename"].lower().endswith(".json") and "layer" in item["filename"].lower():
            return item

    return None


async def convert_image_to_psd(image_bytes: bytes, filename: str, content_type: str | None) -> tuple[bytes, str, str]:
    if not settings.comfyui_base_url:
        raise ComfyError("未配置 COMFYUI_BASE_URL")

    timeout = settings.comfyui_timeout
    base_url = settings.comfyui_base_url
    filename_prefix = _make_request_prefix(filename)

    async with httpx.AsyncClient(timeout=timeout) as client:
        upload_name = await _upload_input_image(client, base_url, image_bytes, filename, content_type)
        prompt_id = await _enqueue_prompt(client, base_url, upload_name, filename_prefix)
        history = await _wait_for_history(client, base_url, prompt_id, timeout)
        history_files = _list_output_files(history)
        info_file = _pick_layers_info_output(history)
        if info_file is None:
            info_file = await _wait_for_layers_info_file(client, base_url, filename_prefix, timeout=15)
        layer_info = await _download_json(client, base_url, info_file)
        psd_bytes = await _build_psd_bytes(client, base_url, layer_info, history_files, info_file)
        output_name = _make_output_name(layer_info, filename)
        cleanup_targets = _collect_cleanup_targets(upload_name, info_file, layer_info, history_files)
        cleanup_token = put_cleanup_data(
            {
                "prompt_id": prompt_id,
                "uploaded_name": upload_name,
                "info_filename": info_file.get("filename", ""),
                "prefix": filename_prefix,
                "files": cleanup_targets,
            }
        )
        return psd_bytes, output_name, cleanup_token


async def _upload_input_image(
    client: httpx.AsyncClient,
    base_url: str,
    image_bytes: bytes,
    filename: str,
    content_type: str | None,
) -> str:
    files = {
        "image": (filename, image_bytes, content_type or "application/octet-stream"),
    }
    resp = await client.post(f"{base_url}/upload/image", files=files)
    resp.raise_for_status()

    payload = resp.json()
    if not isinstance(payload, dict) or not payload.get("name"):
        raise ComfyError(f"ComfyUI 上传返回异常: {payload}")

    return str(payload["name"])


async def _enqueue_prompt(
    client: httpx.AsyncClient,
    base_url: str,
    upload_name: str,
    filename_prefix: str,
) -> str:
    workflow = _load_workflow_template()
    workflow = _inject_uploaded_image(copy.deepcopy(workflow), upload_name)
    workflow = _inject_filename_prefix(workflow, filename_prefix)

    payload: dict[str, Any] = {"prompt": workflow}
    if settings.comfyui_client_id:
        payload["client_id"] = settings.comfyui_client_id
    else:
        payload["client_id"] = uuid.uuid4().hex

    resp = await client.post(f"{base_url}/prompt", json=payload)
    resp.raise_for_status()

    data = resp.json()
    if not isinstance(data, dict):
        raise ComfyError(f"ComfyUI /prompt 返回异常: {data}")

    if "error" in data and data["error"]:
        raise ComfyError(f"ComfyUI 工作流校验失败: {data['error']}")

    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise ComfyError(f"ComfyUI 未返回 prompt_id: {data}")

    return str(prompt_id)


async def _wait_for_history(client: httpx.AsyncClient, base_url: str, prompt_id: str, timeout: int) -> dict[str, Any]:
    start = time.monotonic()

    while True:
        elapsed = time.monotonic() - start
        if elapsed > timeout:
            raise ComfyError(f"等待 ComfyUI 执行超时（>{timeout}s）")

        resp = await client.get(f"{base_url}/history/{prompt_id}")
        resp.raise_for_status()

        data = resp.json()
        if isinstance(data, dict) and prompt_id in data and isinstance(data[prompt_id], dict):
            result = data[prompt_id]
            status = result.get("status", {})
            if isinstance(status, dict):
                status_str = status.get("status_str")
                if status_str == "error":
                    messages = status.get("messages") or []
                    raise ComfyError(f"ComfyUI 工作流执行失败: {messages}")
            return result

        await asyncio_sleep(settings.comfyui_poll_interval)


async def _download_file(client: httpx.AsyncClient, base_url: str, output_file: dict[str, str]) -> bytes:
    normalized = _normalize_output_file(
        output_file["filename"],
        output_file.get("subfolder", ""),
        output_file.get("type", "output"),
    )
    params = {
        "filename": normalized["filename"],
        "subfolder": normalized["subfolder"],
        "type": normalized["type"],
    }
    resp = await client.get(f"{base_url}/view", params=params)
    resp.raise_for_status()
    if not resp.content:
        raise ComfyError("ComfyUI 返回空文件")
    return resp.content


async def _download_json(client: httpx.AsyncClient, base_url: str, output_file: dict[str, str]) -> dict[str, Any]:
    content = await _download_file(client, base_url, output_file)
    try:
        payload = json.loads(content.decode("utf-8"))
    except Exception as exc:
        raise ComfyError(f"layers.json 解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise ComfyError("layers.json 内容格式非法")
    return payload


def _make_output_name(layer_info: dict[str, Any], original_filename: str) -> str:
    return f"{Path(original_filename).stem or 'seethrough'}.psd"


def _resolve_download_file(
    filename: str,
    history_files: list[dict[str, str]],
    fallback: dict[str, str],
) -> dict[str, str]:
    normalized_target = _normalize_output_file(filename)
    for item in history_files:
        normalized_item = _normalize_output_file(
            item["filename"],
            item.get("subfolder", ""),
            item.get("type", "output"),
        )
        if (
            normalized_item["filename"] == normalized_target["filename"]
            and normalized_item["subfolder"] == normalized_target["subfolder"]
        ):
            return item
    fallback_subfolder = fallback.get("subfolder", "")
    if normalized_target["subfolder"]:
        fallback_subfolder = normalized_target["subfolder"]
    return _normalize_output_file(
        normalized_target["filename"],
        fallback_subfolder,
        "output" if fallback.get("type") == "temp" else fallback.get("type", "output"),
    )


async def _build_psd_bytes(
    client: httpx.AsyncClient,
    base_url: str,
    layer_info: dict[str, Any],
    history_files: list[dict[str, str]],
    fallback_file: dict[str, str],
) -> bytes:
    width = int(layer_info.get("width") or 0)
    height = int(layer_info.get("height") or 0)
    layers = layer_info.get("layers")

    if width <= 0 or height <= 0:
        raise ComfyError(f"layers.json 缺少有效画布尺寸: width={width}, height={height}")
    if not isinstance(layers, list) or not layers:
        raise ComfyError("layers.json 未包含有效图层")

    psd = PSDImage.new("RGBA", (width, height), color=0)

    for entry in layers:
        if not isinstance(entry, dict):
            continue

        png_name = entry.get("filename")
        layer_name = str(entry.get("name") or "Layer")
        left = int(entry.get("left") or 0)
        top = int(entry.get("top") or 0)

        if not isinstance(png_name, str) or not png_name.strip():
            logger.warning("跳过缺少 filename 的图层: %s", layer_name)
            continue

        output_file = _resolve_download_file(png_name, history_files, fallback_file)
        image_bytes = await _download_file(client, base_url, output_file)

        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        except Exception as exc:
            raise ComfyError(f"加载图层图片失败 {png_name}: {exc}") from exc

        layer = PixelLayer.frompil(image, psd, name=layer_name, top=top, left=left)
        psd.append(layer)

    if len(psd) == 0:
        raise ComfyError("未能从 layers.json 构建任何 PSD 图层")

    output = io.BytesIO()
    psd.save(output)
    return output.getvalue()


def _make_request_prefix(original_filename: str) -> str:
    stem = Path(original_filename).stem or "seethrough"
    safe_stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)[:40]
    return f"seethrough_{safe_stem}_{uuid.uuid4().hex[:8]}"


def _collect_cleanup_targets(
    uploaded_name: str,
    info_file: dict[str, str],
    layer_info: dict[str, Any],
    history_files: list[dict[str, str]],
) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []

    def add_target(filename: str | None, file_type: str, subfolder: str = "") -> None:
        if not isinstance(filename, str) or not filename.strip():
            return
        entry = _normalize_output_file(filename.strip(), subfolder, file_type)
        if entry not in targets:
            targets.append(entry)

    add_target(uploaded_name, "input")
    add_target(info_file.get("filename"), info_file.get("type", "output"), info_file.get("subfolder", ""))

    layers = layer_info.get("layers")
    if isinstance(layers, list):
        fallback_type = "output" if info_file.get("type") == "temp" else info_file.get("type", "output")
        fallback_subfolder = info_file.get("subfolder", "")
        for entry in layers:
            if not isinstance(entry, dict):
                continue
            add_target(entry.get("filename"), fallback_type, fallback_subfolder)
            add_target(entry.get("depth_filename"), fallback_type, fallback_subfolder)

    for item in history_files:
        if not isinstance(item, dict):
            continue
        add_target(
            item.get("filename"),
            str(item.get("type") or "output"),
            str(item.get("subfolder") or ""),
        )

    return targets


async def _wait_for_layers_info_file(
    client: httpx.AsyncClient,
    base_url: str,
    filename_prefix: str,
    timeout: int = 15,
) -> dict[str, str]:
    start = time.monotonic()
    legacy_logs = [
        _normalize_output_file("seethrough_psd_info.log"),
        _normalize_output_file(f"seethrough/node_{SAVE_PSD_NODE_ID}/latest.log"),
    ]

    while True:
        if time.monotonic() - start > timeout:
            raise ComfyError("工作流执行完成，但未能定位 layers.json 输出文件")

        try:
            listed = await _list_output_directory_files(client, base_url)
            for name in listed:
                if _basename_matches_prefix(name, filename_prefix):
                    return _normalize_output_file(name)
        except Exception:
            pass

        for log_file in legacy_logs:
            try:
                content = await _download_file(client, base_url, log_file)
                info_filename = content.decode("utf-8").strip()
                if _basename_matches_prefix(info_filename, filename_prefix):
                    return _normalize_output_file(info_filename)
            except Exception:
                continue

        await asyncio_sleep(0.5)


async def asyncio_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


async def _list_output_directory_files(client: httpx.AsyncClient, base_url: str) -> list[str]:
    for path in ("/internal/files/output", "/api/internal/files/output"):
        try:
            resp = await client.get(f"{base_url}{path}")
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, list):
                continue

            names: list[str] = []
            for item in payload:
                if not isinstance(item, str):
                    continue
                if item.endswith(" [output]"):
                    names.append(item[:-9])
                else:
                    names.append(item)
            return names
        except Exception:
            continue
    return []
