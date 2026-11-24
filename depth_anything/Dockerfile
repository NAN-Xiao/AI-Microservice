FROM python:3.11-slim

LABEL maintainer="AI-Microservice"
LABEL service="depth_anything"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV HOST=0.0.0.0 \
    PORT=9006 \
    DEBUG=false \
    LOG_TO_FILE=false

EXPOSE 9006

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9006/api/depth-anything/health/live')" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9006", "--log-level", "warning"]
