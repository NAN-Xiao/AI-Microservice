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
