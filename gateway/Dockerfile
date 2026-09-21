FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/backend

COPY backend/exchange /app/backend/exchange
COPY gateway/gateway /app/gateway

EXPOSE 8000

ENTRYPOINT ["python", "-m", "gateway"]
