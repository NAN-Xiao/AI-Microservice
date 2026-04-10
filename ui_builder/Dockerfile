FROM python:3.11-slim

LABEL maintainer="AI-Microservice"
LABEL service="ui-builder"

WORKDIR /app

# 依赖先装，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制业务代码
COPY . .

# 运行时环境变量（可被 docker-compose / Nacos 覆盖）
ENV HOST=0.0.0.0 \
    PORT=9002 \
    DEBUG=false \
    LOG_TO_FILE=false

EXPOSE 9002

# 健康检查 —— Docker 和 Nacos 都能用
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9002/api/ui-builder/health/live')" || exit 1

# 用 uvicorn 启动，单 worker（LLM 调用是 IO 密集，asyncio 够用）
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9002", "--log-level", "warning"]
