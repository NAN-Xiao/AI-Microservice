from __future__ import annotations

import copy
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.config import PROJECT_ROOT, settings

logger = logging.getLogger(__name__)


class ComfyError(Exception):
    pass


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

    node = workflow.get(node_id)
    if not isinstance(node, dict):
        raise ComfyError(f"工作流中未找到输入节点: {node_id}")

    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise ComfyError(f"节点 {node_id} 缺少 inputs 字段")

    inputs[field] = uploaded_name
    return workflow


def _extract_file_candidates(value: Any, out: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        if "filename" in value and isinstance(value["filename"], str):
            out.append(
                {
                    "filename": value["filename"],
                    "subfolder": str(value.get("subfolder", "")),
                    "type": str(value.get("type", "output")),
                }
            )
        for v in value.values():
            _extract_file_candidates(v, out)
    elif isinstance(value, list):
        for item in value:
            _extract_file_candidates(item, out)


def _pick_psd_output(history_payload: dict[str, Any]) -> dict[str, str]:
    candidates: list[dict[str, str]] = []
    _extract_file_candidates(history_payload, candidates)

    # 去重
    deduped = []
    seen = set()
    for item in candidates:
        key = (item["filename"], item["subfolder"], item["type"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    for item in deduped:
        if item["filename"].lower().endswith(".psd"):
            return item

    found = ", ".join(i["filename"] for i in deduped[:10])
    raise ComfyError(f"工作流执行完成，但未找到 PSD 输出文件。已发现文件: {found or '无'}")


async def convert_image_to_psd(image_bytes: bytes, filename: str, content_type: str | None) -> tuple[bytes, str]:
    if not settings.comfyui_base_url:
        raise ComfyError("未配置 COMFYUI_BASE_URL")

    timeout = settings.comfyui_timeout
    base_url = settings.comfyui_base_url

    async with httpx.AsyncClient(timeout=timeout) as client:
        upload_name = await _upload_input_image(client, base_url, image_bytes, filename, content_type)
        prompt_id = await _enqueue_prompt(client, base_url, upload_name)
        history = await _wait_for_history(client, base_url, prompt_id, timeout)

        output_file = _pick_psd_output(history)
        psd_bytes = await _download_file(client, base_url, output_file)
        output_name = Path(output_file["filename"]).name
        return psd_bytes, output_name


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


async def _enqueue_prompt(client: httpx.AsyncClient, base_url: str, upload_name: str) -> str:
    workflow = _load_workflow_template()
    workflow = _inject_uploaded_image(copy.deepcopy(workflow), upload_name)

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
    params = {
        "filename": output_file["filename"],
        "subfolder": output_file["subfolder"],
        "type": output_file["type"],
    }
    resp = await client.get(f"{base_url}/view", params=params)
    resp.raise_for_status()
    if not resp.content:
        raise ComfyError("ComfyUI 返回空文件")
    return resp.content


async def asyncio_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
