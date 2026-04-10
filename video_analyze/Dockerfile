FROM python:3.12-slim

LABEL maintainer="AI-Microservice"
LABEL service="video-analyze"

WORKDIR /app

# 依赖先装，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制业务代码
COPY . .

# 运行时环境变量（可被 docker-compose / Nacos 覆盖）
ENV HOST=0.0.0.0 \
    PORT=9001 \
    DEBUG=false \
    LOG_TO_FILE=false

EXPOSE 9001

# 健康检查 —— Docker 和 Nacos 都能用
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9001/api/video-analyze/health/live')" || exit 1

# 用 uvicorn 启动，单 worker（LLM 调用是 IO 密集，asyncio 够用）
# 多实例扩容交给 Docker/K8s，不用 gunicorn 多 worker
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9001", "--log-level", "warning"]
