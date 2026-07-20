from fastapi.testclient import TestClient

from app.main import app
from app.services.comfy_client import ComfyQueueFullError


def test_remove_background_queue_full_returns_http_429(monkeypatch):
    async def fake_remove_background(*args, **kwargs):
        raise ComfyQueueFullError("队列已满，请等待")

    monkeypatch.setattr("app.routers.remove_bg.remove_background", fake_remove_background)

    client = TestClient(app)
    response = client.post(
        "/api/ai-rembg/remove-background",
        files={"image": ("input.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )

    assert response.status_code == 429
    assert response.json()["message"] == "队列已满，请等待"


def test_remove_background_supports_chinese_download_filename(monkeypatch):
    async def fake_remove_background(*args, **kwargs):
        return b"png-bytes", "替换红色元素-77862_removebg.png", "cleanup-token"

    monkeypatch.setattr("app.routers.remove_bg.remove_background", fake_remove_background)

    client = TestClient(app)
    response = client.post(
        "/api/ai-rembg/remove-background",
        files={"image": ("替换红色元素-77862.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )

    assert response.status_code == 200
    assert response.content == b"png-bytes"
    assert response.headers["content-disposition"] == (
        "attachment; filename=\"removebg.png\"; "
        "filename*=UTF-8''%E6%9B%BF%E6%8D%A2%E7%BA%A2%E8%89%B2%E5%85%83%E7%B4%A0-77862_removebg.png"
    )
