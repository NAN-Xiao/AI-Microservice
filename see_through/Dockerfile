FROM python:3.11-slim

LABEL maintainer="AI-Microservice"
LABEL service="see_through"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV HOST=0.0.0.0 \
    PORT=9004 \
    DEBUG=false \
    LOG_TO_FILE=false

EXPOSE 9004

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9004/api/see-through/health/live')" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9004", "--log-level", "warning"]
