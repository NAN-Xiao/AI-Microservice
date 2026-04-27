"""
See Through 接口测试脚本。

用法：
  python test_api.py D:\path\to\image.png
  python test_api.py D:\path\to\image.png http://127.0.0.1:9004
  python test_api.py D:\path\to\image.png http://127.0.0.1:9004 your-token
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:9004"
DEFAULT_TIMEOUT = 600


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python test_api.py <image_path> [base_url] [token]")
        return 1

    image_path = Path(sys.argv[1]).expanduser()
    base_url = sys.argv[2] if len(sys.argv) >= 3 else DEFAULT_BASE_URL
    token = sys.argv[3] if len(sys.argv) >= 4 else ""

    if not image_path.is_file():
        print(f"[ERROR] 图片不存在: {image_path}")
        return 1

    url = base_url.rstrip("/") + "/api/see-through/convert"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    suffix = image_path.suffix.lower() or ".png"
    output_path = image_path.with_name(f"{image_path.stem}_out.psd")

    print(f"[INFO] 请求地址: {url}")
    print(f"[INFO] 输入图片: {image_path}")
    print(f"[INFO] 输出文件: {output_path}")
    print("[INFO] 开始上传并等待 PSD 返回...")

    with image_path.open("rb") as f, httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        files = {
            "image": (image_path.name, f, _guess_content_type(suffix)),
        }
        response = client.post(url, files=files, headers=headers)

    if response.status_code != 200:
        print(f"[ERROR] HTTP {response.status_code}")
        print(response.text[:1000])
        return 1

    content_type = response.headers.get("Content-Type", "")
    if "application/octet-stream" not in content_type and "application/vnd.adobe.photoshop" not in content_type:
        print("[ERROR] 返回内容不是 PSD 文件")
        print(response.text[:1000])
        return 1

    output_path.write_bytes(response.content)
    print(f"[OK] PSD 已保存: {output_path}")
    print("[INFO] 这个脚本本身不需要轮询；接口内部已经在轮询 ComfyUI 执行结果。")
    return 0


def _guess_content_type(suffix: str) -> str:
    mapping = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    return mapping.get(suffix, "application/octet-stream")


if __name__ == "__main__":
    raise SystemExit(main())
