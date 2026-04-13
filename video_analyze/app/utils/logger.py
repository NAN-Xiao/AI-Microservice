"""
video_analyze 日志系统。
- 控制台彩色输出（开发调试用）
- 按日期滚动的文件日志（持久化）
- 每次分析请求生成独立 JSON 日志文件（可审计追溯）
- 自动清理超过 7 天的请求日志文件
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.config import settings, PROJECT_ROOT

_LOG_DIR = PROJECT_ROOT / "logs"
_REQUEST_LOG_DIR = _LOG_DIR / "requests"

# ANSI 颜色
_CYAN = "\033[96m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_MAGENTA = "\033[95m"
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"


class _ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: _DIM,
        logging.INFO: _GREEN,
        logging.WARNING: _YELLOW,
        logging.ERROR: _RED,
        logging.CRITICAL: _BOLD + _RED,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        level = f"{color}{record.levelname:<7}{_RESET}"
        name = f"{_CYAN}{record.name}{_RESET}"
        msg = super().format(record)  # 会处理 exc_info
        # super().format 已经包含了完整消息，直接拼接前缀
        return f"{_DIM}{ts}{_RESET} {level} {name} - {record.getMessage()}" + (
            "\n" + self.formatException(record.exc_info) if record.exc_info else ""
        )


def setup_logging() -> None:
    """初始化日志系统，应在应用启动时调用一次。"""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)

    # 清除默认 handler（避免 uvicorn 重复输出）
    root.handlers.clear()

    # 控制台 handler（Docker 中这是主要输出，docker logs 能直接看到）
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    console.setFormatter(_ColorFormatter())
    root.addHandler(console)

    # 文件 handler —— 按天滚动，保留 30 天（Docker 中可关闭，靠 stdout 收集）
    if settings.log_to_file:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        _REQUEST_LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            filename=str(_LOG_DIR / "video_analyze.log"),
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
        )
        root.addHandler(file_handler)


def log_request(task_id: str, data: dict) -> None:
    """将单次分析请求的完整信息写入独立 JSON 文件（仅 log_to_file 开启时）。"""
    if not settings.log_to_file:
        return
    _REQUEST_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = _REQUEST_LOG_DIR / f"{ts}_{task_id}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── 控制台进度打印 ────────────────────────────────────

_STEP_START: dict[str, float] = {}


def step_start(task_id: str, step: str) -> None:
    key = f"{task_id}:{step}"
    _STEP_START[key] = time.time()
    print(f"  {_MAGENTA}▶{_RESET} [{task_id[:8]}] {step}")


def step_done(task_id: str, step: str) -> None:
    key = f"{task_id}:{step}"
    start = _STEP_START.pop(key, None)
    elapsed = _fmt_elapsed(time.time() - start) if start else "?"
    print(f"  {_GREEN}✔{_RESET} [{task_id[:8]}] {step} {_DIM}({elapsed}){_RESET}")


def step_fail(task_id: str, step: str, error: str) -> None:
    key = f"{task_id}:{step}"
    start = _STEP_START.pop(key, None)
    elapsed = _fmt_elapsed(time.time() - start) if start else "?"
    print(f"  {_RED}✘{_RESET} [{task_id[:8]}] {step} {_DIM}({elapsed}){_RESET} — {_RED}{error}{_RESET}")


def _fmt_elapsed(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{seconds / 60:.1f}min"


# ─── 请求日志自动清理 ──────────────────────────────────

_LOG_RETENTION_DAYS = 7
_LOG_CLEANUP_INTERVAL = 3600  # 每小时清理一次
_cleanup_handle: asyncio.TimerHandle | None = None


def _cleanup_old_request_logs() -> None:
    """删除超过保留天数的请求日志文件。"""
    if not _REQUEST_LOG_DIR.is_dir():
        return
    cutoff = time.time() - _LOG_RETENTION_DAYS * 86400
    removed = 0
    for f in _REQUEST_LOG_DIR.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    if removed:
        logging.getLogger(__name__).debug("清理过期请求日志: %d 个", removed)


def start_log_cleanup() -> None:
    """启动定期日志清理（在 lifespan 中调用）。"""
    global _cleanup_handle

    def _schedule():
        global _cleanup_handle
        _cleanup_old_request_logs()
        _cleanup_handle = asyncio.get_event_loop().call_later(_LOG_CLEANUP_INTERVAL, _schedule)

    _cleanup_old_request_logs()  # 启动时立即清理一次
    _cleanup_handle = asyncio.get_event_loop().call_later(_LOG_CLEANUP_INTERVAL, _schedule)


def stop_log_cleanup() -> None:
    global _cleanup_handle
    if _cleanup_handle:
        _cleanup_handle.cancel()
        _cleanup_handle = None
