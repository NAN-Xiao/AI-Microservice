"""
启动入口。
用法：
  python run.py
  uvicorn app.main:app --host 0.0.0.0 --port 9004
"""

from app.config import settings

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
    )
