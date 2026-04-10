"""
纯文本调用 LLM，验证 LLM_API_URL / LLM_API_KEY / LLM_MODEL 是否可用。
在 ui_builder 目录下执行: python scripts/test_llm_connect.py
或在服务器上: cd 到 ui_builder 后同样执行。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 保证能 import config
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402


def main() -> int:
    url = f"{settings.api_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.model,
        "messages": [
            {"role": "user", "content": "只回复一个字：好"},
        ],
    }
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    print(f"POST {url}")
    print(f"model={settings.model}")
    print("---")

    resp = None
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            print(f"HTTP {resp.status_code}")
            if resp.status_code != 200:
                print(resp.text[:2000])
                return 1
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            print("LLM 回复:", text.strip()[:500])
            print("---")
            print("结论: LLM 连通正常")
            return 0
    except httpx.HTTPStatusError as e:
        print(f"HTTP 错误: {e.response.status_code}")
        print(e.response.text[:2000])
        return 1
    except httpx.RequestError as e:
        print(f"网络错误: {e}")
        return 1
    except (KeyError, json.JSONDecodeError) as e:
        print(f"响应解析失败: {e}")
        if resp is not None:
            print(resp.text[:2000])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
