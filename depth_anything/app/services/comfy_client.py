from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from app.config import PROJECT_ROOT, settings
from app.services.result_store import cleanup_remote_resources, put_cleanup_data

logger = logging.getLogger(__name__)


class ComfyError(Exception):
    pass


class ComfyQueueFullError(ComfyError):
    pass


def _load_workflow_template() -> dict[str, Any]:
    workflow_file = PROJECT_ROOT / settings.workflow_path
    if not workflow_file.is_file():
        raise ComfyError(f"工作流文件不存在: {workflow_file}")

    try:
        return json.loads(workflow_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ComfyError(f"工作流 JSON 格式错误: {exc}") from exc


def _inject_uploaded_video(workflow: dict[str, Any], uploaded_name: str) -> dict[str, Any]:
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


def _inject_filename_prefix(
    workflow: dict[str, Any],
    filename_prefix: str,
    frame_rate: float | None = None,
) -> dict[str, Any]:
    node_id = settings.workflow_save_node_id
    node = workflow.get(node_id)
    if not isinstance(node, dict):
        raise ComfyError(f"工作流中未找到保存节点: {node_id}")

    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise ComfyError(f"节点 {node_id} 缺少 inputs 字段")

    inputs["filename_prefix"] = filename_prefix
    if frame_rate is not None and frame_rate > 0:
        inputs["frame_rate"] = round(float(frame_rate), 3)
    return workflow


def _inject_slice_duration(workflow: dict[str, Any], duration: float | None) -> dict[str, Any]:
    if duration is None or duration <= 0:
        return workflow
    node_id = settings.workflow_slice_node_id
    if not node_id:
        return workflow
    node = workflow.get(node_id)
    if not isinstance(node, dict):
        return workflow
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        return workflow
    clamped = round(min(float(duration), float(settings.video_max_duration)), 3)
    inputs["start_time"] = 0.0
    inputs["duration"] = clamped
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


def _extract_file_candidates(value: Any, out: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        if "filename" in value and isinstance(value["filename"], str):
            subfolder = str(value.get("subfolder", ""))
            file_type = str(value.get("type", "output"))
            out.append(_normalize_output_file(value["filename"], subfolder, file_type))
            workflow_img = value.get("workflow")
            if isinstance(workflow_img, str) and workflow_img.strip():
                out.append(_normalize_output_file(workflow_img, subfolder, file_type))
        for v in value.values():
            _extract_file_candidates(v, out)
    elif isinstance(value, list):
        for item in value:
            _extract_file_candidates(item, out)


def _list_output_files(history_payload: dict[str, Any]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    _extract_file_candidates(history_payload, candidates)

    deduped: list[dict[str, str]] = []
    seen = set()
    for item in candidates:
        key = (item["filename"], item["subfolder"], item["type"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    return deduped


def _pick_saved_video(history_payload: dict[str, Any], request_key: str) -> dict[str, str]:
    files = _list_output_files(history_payload)
    request_subfolder = _make_request_subfolder(request_key)

    for item in files:
        filename = item["filename"].lower()
        subfolder = item["subfolder"].strip("/")
        if item["type"] == "output" and subfolder == request_subfolder and filename.endswith(".mp4"):
            return item

    for item in files:
        joined = f"{item['subfolder'].strip('/')}/{item['filename']}".strip("/")
        if request_key in joined and item["filename"].lower().endswith(".mp4"):
            return item

    for item in files:
        if item["type"] == "output" and item["filename"].lower().endswith(".mp4"):
            return item

    raise ComfyError(f"工作流执行完成，但未找到 request_key={request_key} 的 MP4 输出")


async def generate_video_depth(
    video_bytes: bytes,
    filename: str,
    content_type: str | None,
    *,
    target_duration: float | None = None,
    target_fps: float | None = None,
) -> tuple[bytes, str, str]:
    if not settings.comfyui_base_url:
        raise ComfyError("未配置 COMFYUI_BASE_URL")

    timeout = settings.comfyui_timeout
    base_url = settings.comfyui_base_url
    request_key = _make_request_key(filename)

    upload_name = ""
    prompt_id = ""
    history: dict[str, Any] = {}
    output_file: dict[str, str] = {}
    succeeded = False

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            upload_name = await _upload_input_video(client, base_url, video_bytes, filename, content_type, request_key)
            prompt_id = await _enqueue_prompt(
                client,
                base_url,
                upload_name,
                request_key,
                target_duration=target_duration,
                target_fps=target_fps,
            )
            history = await _wait_for_history(client, base_url, prompt_id, timeout)
            output_file = _pick_saved_video(history, request_key)
            output_bytes = await _download_file(client, base_url, output_file)
            _validate_mp4(output_bytes)
            output_name = _make_output_name(filename)
            cleanup_token = put_cleanup_data(
                {
                    "prompt_id": prompt_id,
                    "uploaded_name": upload_name,
                    "prefix": request_key,
                    "directories": _collect_cleanup_directories(request_key),
                    "files": _collect_cleanup_targets(upload_name, output_file, history),
                }
            )
            succeeded = True
            return output_bytes, output_name, cleanup_token
    finally:
        if not succeeded and (upload_name or prompt_id):
            logger.info("任务未成功完成，触发 ComfyUI 远端资源兜底清理: request_key=%s", request_key)
            try:
                await cleanup_remote_resources(
                    {
                        "prompt_id": prompt_id,
                        "uploaded_name": upload_name,
                        "prefix": request_key,
                        "directories": _collect_cleanup_directories(request_key),
                        "files": _collect_cleanup_targets(upload_name, output_file, history),
                    }
                )
            except Exception as exc:
                logger.warning("失败任务兜底清理异常: request_key=%s error=%s", request_key, exc)


async def _upload_input_video(
    client: httpx.AsyncClient,
    base_url: str,
    video_bytes: bytes,
    filename: str,
    content_type: str | None,
    request_key: str,
) -> str:
    upload_filename = _make_upload_filename(filename, request_key)
    upload_subfolder = _make_request_subfolder(request_key)
    files = {
        "image": (upload_filename, video_bytes, content_type or "video/mp4"),
    }
    data = {
        "type": "input",
        "subfolder": upload_subfolder,
        "overwrite": "false",
    }
    resp = await client.post(f"{base_url}/upload/image", files=files, data=data)
    _raise_for_queue_full(resp)
    resp.raise_for_status()

    payload = resp.json()
    if not isinstance(payload, dict) or not payload.get("name"):
        raise ComfyError(f"ComfyUI 上传返回异常: {payload}")

    returned_name = str(payload["name"])
    returned_subfolder = str(payload.get("subfolder") or upload_subfolder).strip().replace("\\", "/").strip("/")
    if returned_subfolder and "/" not in returned_name.replace("\\", "/"):
        return f"{returned_subfolder}/{returned_name}"
    return returned_name


async def _enqueue_prompt(
    client: httpx.AsyncClient,
    base_url: str,
    upload_name: str,
    request_key: str,
    *,
    target_duration: float | None = None,
    target_fps: float | None = None,
) -> str:
    workflow = _load_workflow_template()
    workflow = _inject_uploaded_video(copy.deepcopy(workflow), upload_name)
    workflow = _inject_slice_duration(workflow, target_duration)
    workflow = _inject_filename_prefix(
        workflow,
        f"{_make_request_subfolder(request_key)}/result",
        frame_rate=target_fps,
    )

    payload: dict[str, Any] = {
        "prompt": workflow,
        "client_id": _make_client_id(request_key),
    }

    resp = await client.post(
        f"{base_url}/prompt",
        json=payload,
        headers={"llm_queue_request": "1"},
    )
    _raise_for_queue_full(resp)
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
        _raise_for_queue_full(resp)
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

        await asyncio.sleep(settings.comfyui_poll_interval)


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
    _raise_for_queue_full(resp)
    resp.raise_for_status()
    if not resp.content:
        raise ComfyError("ComfyUI 返回空文件")
    return resp.content


def _validate_mp4(content: bytes) -> None:
    if len(content) < 12 or b"ftyp" not in content[:32]:
        raise ComfyError("ComfyUI 返回内容不是有效的 MP4 视频文件")


def _make_output_name(original_filename: str) -> str:
    stem = Path(original_filename).stem or "depth"
    return f"{stem}_depth.mp4"


def _make_request_key(original_filename: str) -> str:
    stem = Path(original_filename).stem or "depth"
    safe_stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)[:40]
    return f"depth_anything_{safe_stem}_{uuid.uuid4().hex}"


def _make_upload_filename(original_filename: str, request_key: str) -> str:
    suffix = Path(original_filename).suffix.lower()
    if not suffix or len(suffix) > 10 or any(ch not in ".abcdefghijklmnopqrstuvwxyz0123456789" for ch in suffix):
        suffix = ".mp4"
    return f"{request_key}{suffix}"


def _make_request_subfolder(request_key: str) -> str:
    return f"depth_anything/requests/{request_key}"


def _make_client_id(request_key: str) -> str:
    configured = str(settings.comfyui_client_id or "").strip()
    if configured:
        safe_configured = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in configured).strip("._")
        if safe_configured:
            return f"{safe_configured}_{request_key}"
    return request_key


def _collect_cleanup_targets(
    uploaded_name: str,
    output_file: dict[str, str],
    history_payload: dict[str, Any],
) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []

    def add_target(filename: str | None, file_type: str, subfolder: str = "") -> None:
        if not isinstance(filename, str) or not filename.strip():
            return
        entry = _normalize_output_file(filename.strip(), subfolder, file_type)
        if entry not in targets:
            targets.append(entry)

    add_target(uploaded_name, "input")
    add_target(output_file.get("filename"), output_file.get("type", "output"), output_file.get("subfolder", ""))

    for item in _list_output_files(history_payload):
        add_target(item.get("filename"), str(item.get("type") or "output"), str(item.get("subfolder") or ""))

    return targets


def _collect_cleanup_directories(request_key: str) -> list[dict[str, str]]:
    request_subfolder = _make_request_subfolder(request_key)
    return [
        {"type": "input", "subfolder": request_subfolder},
        {"type": "output", "subfolder": request_subfolder},
    ]


def _raise_for_queue_full(resp: httpx.Response) -> None:
    if resp.status_code != 429:
        return
    try:
        payload = resp.json()
    except Exception:
        payload = {}
    message = payload.get("error") if isinstance(payload, dict) else ""
    if str(message).strip().lower() == "queue is full":
        raise ComfyQueueFullError("队列已满，请等待")
