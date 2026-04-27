"""
see_through 日志系统。
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from app.config import PROJECT_ROOT, settings

_LOG_DIR = PROJECT_ROOT / "logs"
_REQUEST_LOG_DIR = _LOG_DIR / "requests"

_CYAN = "\033[96m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
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
        return f"{_DIM}{ts}{_RESET} {level} {name} - {record.getMessage()}" + (
            "\n" + self.formatException(record.exc_info) if record.exc_info else ""
        )


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    console.setFormatter(_ColorFormatter())
    root.addHandler(console)

    if settings.log_to_file:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        _REQUEST_LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            filename=str(_LOG_DIR / "see_through.log"),
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
    if not settings.log_to_file:
        return
    _REQUEST_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = _REQUEST_LOG_DIR / f"{ts}_{task_id}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


_LOG_RETENTION_DAYS = 7
_LOG_CLEANUP_INTERVAL = 3600
_cleanup_handle: asyncio.TimerHandle | None = None


def _cleanup_old_request_logs() -> None:
    if not _REQUEST_LOG_DIR.is_dir():
        return
    cutoff = time.time() - _LOG_RETENTION_DAYS * 86400
    removed = 0
    for file_path in _REQUEST_LOG_DIR.iterdir():
        if file_path.is_file() and file_path.stat().st_mtime < cutoff:
            file_path.unlink(missing_ok=True)
            removed += 1
    if removed:
        logging.getLogger(__name__).debug("清理过期请求日志: %d 个", removed)


def start_log_cleanup() -> None:
    global _cleanup_handle

    def _schedule() -> None:
        global _cleanup_handle
        _cleanup_old_request_logs()
        _cleanup_handle = asyncio.get_event_loop().call_later(_LOG_CLEANUP_INTERVAL, _schedule)

    _cleanup_old_request_logs()
    _cleanup_handle = asyncio.get_event_loop().call_later(_LOG_CLEANUP_INTERVAL, _schedule)


def stop_log_cleanup() -> None:
    global _cleanup_handle
    if _cleanup_handle:
        _cleanup_handle.cancel()
        _cleanup_handle = None
