FROM python:3.11-slim

LABEL maintainer="AI-Microservice"
LABEL service="image2psd"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV HOST=0.0.0.0 \
    PORT=9003 \
    DEBUG=false \
    LOG_TO_FILE=false

EXPOSE 9003

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9003/api/image2psd/health/live')" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9003", "--log-level", "warning"]
