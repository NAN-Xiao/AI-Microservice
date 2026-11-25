"""
视频预处理服务：在提交 ComfyUI Depth Anything 模型前，对用户上传的视频进行探测、裁剪（最长 30s）与压缩。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
import re
import shutil
import tempfile

from app.config import settings

logger = logging.getLogger(__name__)

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO_STREAM_RE = re.compile(r"Stream\s+#\d+:\d+.*?Video:.*")
_RESOLUTION_RE = re.compile(r",\s*(\d{2,5})x(\d{2,5})(?:\s|\[|,|$)")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:fps|tbr)")


class VideoPreprocessError(Exception):
    pass


@dataclass
class VideoInfo:
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None


@dataclass
class PreprocessedVideo:
    video_bytes: bytes
    filename: str
    original_size_bytes: int
    processed_size_bytes: int
    original_duration: float | None
    target_duration: float
    width: int | None
    height: int | None
    fps: float


def _resolve_ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe:
            return exe
    except Exception:
        pass

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    raise VideoPreprocessError("未找到可用的 ffmpeg，请安装 imageio-ffmpeg 或系统 ffmpeg")


def _parse_ffmpeg_info(stderr_text: str) -> VideoInfo:
    info = VideoInfo()

    dur_match = _DURATION_RE.search(stderr_text)
    if dur_match:
        hours, minutes, seconds = dur_match.groups()
        total = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        if total > 0:
            info.duration = total

    stream_match = _VIDEO_STREAM_RE.search(stderr_text)
    if stream_match:
        line = stream_match.group(0)
        res_match = _RESOLUTION_RE.search(line)
        if res_match:
            info.width = int(res_match.group(1))
            info.height = int(res_match.group(2))
        fps_match = _FPS_RE.search(line)
        if fps_match:
            fps_val = float(fps_match.group(1))
            if 1.0 <= fps_val <= 240.0:
                info.fps = fps_val

    return info


def _compute_target_resolution(
    width: int | None,
    height: int | None,
    max_dimension: int,
) -> tuple[int | None, int | None]:
    if not width or not height or width <= 0 or height <= 0:
        return None, None

    scale = 1.0
    if max_dimension > 0 and max(width, height) > max_dimension:
        scale = max_dimension / float(max(width, height))

    target_w = max(2, int(round(width * scale)) // 2 * 2)
    target_h = max(2, int(round(height * scale)) // 2 * 2)
    return target_w, target_h


async def _run_ffmpeg(args: list[str], timeout: int) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.communicate()
        raise VideoPreprocessError(f"视频预处理超时（>{timeout}s）") from exc
    return proc.returncode or 0, stderr.decode("utf-8", errors="ignore")


async def _probe_video(ffmpeg_exe: str, input_path: Path) -> VideoInfo:
    _, stderr_text = await _run_ffmpeg([ffmpeg_exe, "-hide_banner", "-i", str(input_path)], timeout=30)
    return _parse_ffmpeg_info(stderr_text)


async def preprocess_video(video_bytes: bytes, original_filename: str) -> PreprocessedVideo:
    ffmpeg_exe = _resolve_ffmpeg_exe()
    max_duration = max(1.0, float(settings.video_max_duration))
    max_dimension = int(settings.video_max_dimension)
    max_fps = max(1.0, float(settings.video_max_fps))
    crf = int(settings.video_crf)
    preset = str(settings.video_preset or "veryfast").strip()
    timeout = max(30, int(settings.video_preprocess_timeout))

    suffix = Path(original_filename or "input.mp4").suffix.lower()
    if not suffix or len(suffix) > 10 or any(ch not in ".abcdefghijklmnopqrstuvwxyz0123456789" for ch in suffix):
        suffix = ".mp4"

    with tempfile.TemporaryDirectory(prefix="depth_anything_prep_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        in_file = tmp_path / f"input{suffix}"
        out_file = tmp_path / "processed.mp4"
        in_file.write_bytes(video_bytes)

        info = await _probe_video(ffmpeg_exe, in_file)

        if info.duration is not None and info.duration > 0:
            target_duration = round(min(info.duration, max_duration), 3)
        else:
            target_duration = round(max_duration, 3)

        target_w, target_h = _compute_target_resolution(info.width, info.height, max_dimension)

        if info.fps is not None and info.fps > 0:
            target_fps = round(min(info.fps, max_fps), 3)
        else:
            target_fps = round(max_fps, 3)

        cmd = [
            ffmpeg_exe,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(in_file),
            "-t",
            f"{target_duration:.3f}",
            "-an",
        ]

        if target_w and target_h:
            cmd.extend(["-vf", f"scale={target_w}:{target_h}"])
        else:
            cmd.extend(["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"])

        if info.fps is None or info.fps > max_fps:
            cmd.extend(["-r", f"{target_fps:.3f}"])

        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(out_file),
            ]
        )

        rc, stderr_text = await _run_ffmpeg(cmd, timeout=timeout)
        if rc != 0 or not out_file.is_file() or out_file.stat().st_size == 0:
            detail = stderr_text.strip().splitlines()[-1] if stderr_text.strip() else f"exit={rc}"
            raise VideoPreprocessError(f"视频裁剪压缩失败: {detail}")

        out_info = await _probe_video(ffmpeg_exe, out_file)
        if out_info.duration is not None and out_info.duration > 0:
            target_duration = round(min(out_info.duration, max_duration), 3)
        if out_info.fps is not None and out_info.fps > 0:
            target_fps = round(min(out_info.fps, max_fps), 3)

        processed_bytes = out_file.read_bytes()
        processed_name = f"{Path(original_filename or 'input.mp4').stem or 'input'}.mp4"

        logger.info(
            "视频预处理完成: file=%s | size=%.2fMB->%.2fMB | duration=%ss->%.2fs | res=%sx%s->%sx%s | fps=%.2f",
            original_filename,
            len(video_bytes) / (1024 * 1024),
            len(processed_bytes) / (1024 * 1024),
            f"{info.duration:.2f}" if info.duration is not None else "unknown",
            target_duration,
            info.width or "?",
            info.height or "?",
            out_info.width or target_w or "?",
            out_info.height or target_h or "?",
            target_fps,
        )

        return PreprocessedVideo(
            video_bytes=processed_bytes,
            filename=processed_name,
            original_size_bytes=len(video_bytes),
            processed_size_bytes=len(processed_bytes),
            original_duration=round(info.duration, 3) if info.duration is not None else None,
            target_duration=target_duration,
            width=out_info.width or target_w,
            height=out_info.height or target_h,
            fps=target_fps,
        )
