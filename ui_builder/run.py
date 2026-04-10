"""
启动入口。
用法：
  python run.py
  uvicorn app.main:app --host 0.0.0.0 --port 9002
"""

from app.config import settings

if __name__ == "__main__":
    import uvicorn

    ssl_kwargs = {}
    if settings.ssl_certfile and settings.ssl_keyfile:
        ssl_kwargs["ssl_certfile"] = settings.ssl_certfile
        ssl_kwargs["ssl_keyfile"] = settings.ssl_keyfile

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        **ssl_kwargs,
    )
