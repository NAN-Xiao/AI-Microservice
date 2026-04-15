import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.config import PROJECT_ROOT, settings

_LOG_DIR = PROJECT_ROOT / "logs"


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if settings.debug else logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
    root.addHandler(console)

    if settings.log_to_file:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = TimedRotatingFileHandler(
            filename=str(_LOG_DIR / "image2psd.log"),
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
        root.addHandler(fh)
