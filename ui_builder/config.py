import os
from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass
class Settings:
    host: str = os.environ.get("HOST", "127.0.0.1")
    port: int = int(os.environ.get("PORT", "9002"))
    debug: bool = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")

    # Gemini API (OpenAI-compatible endpoint)
    api_url: str = os.environ.get("LLM_API_URL", "https://aikey.elex-tech.com/v1")
    api_key: str = os.environ.get("LLM_API_KEY", "apg_c2a9f12cb04b6db44c905952402619ba39a4eb446185653c")
    model: str = os.environ.get("LLM_MODEL", "gemini-2.5-pro")
    timeout: int = int(os.environ.get("LLM_TIMEOUT", "300"))
    service_name: str = "ui-builder"
    http_client: Optional[httpx.AsyncClient] = None


settings = Settings()
