"""
image2psd 日志系统。
- 控制台彩色输出（开发调试用）
- 按日期滚动的文件日志（持久化）
- 每次转换请求生成独立 JSON 日志文件（可审计追溯）
"""

import json
import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from app.config import PROJECT_ROOT, settings

_LOG_DIR = PROJECT_ROOT / "logs"
_REQUEST_LOG_DIR = _LOG_DIR / "requests"

# ANSI 颜色
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
    """初始化日志系统，应在应用启动时调用一次。"""
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
            filename=str(_LOG_DIR / "image2psd.log"),
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
    """将单次转换请求的完整信息写入独立 JSON 文件（仅 log_to_file 开启时）。"""
    if not settings.log_to_file:
        return
    _REQUEST_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = _REQUEST_LOG_DIR / f"{ts}_{task_id}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
