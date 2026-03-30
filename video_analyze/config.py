import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass
class Settings:
    host: str = os.environ.get("HOST", "127.0.0.1")
    port: int = int(os.environ.get("PORT", "9001"))
    debug: bool = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")
    upload_dir: Path = Path(__file__).parent / "tmp_uploads"

    # Qwen / OpenAI 兼容 API
    api_url: str = os.environ.get("LLM_API_URL", "https://aikey.elex-tech.com/v1")
    api_key: str = os.environ.get("LLM_API_KEY", "apg_c2a9f12cb04b6db44c905952402619ba39a4eb446185653c")
    model: str = os.environ.get("LLM_MODEL", "qwen3.5-plus")
    timeout: int = int(os.environ.get("LLM_TIMEOUT", "300"))
    service_name: str = "video-analyze"
    http_client: Optional[httpx.AsyncClient] = None


settings = Settings()
