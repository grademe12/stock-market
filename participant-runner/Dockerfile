FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend

# The runner reuses only the framework-independent participant and order types.
COPY backend/exchange /app/backend/exchange
COPY participant-runner/participant_runner /app/participant_runner

ENTRYPOINT ["python", "-m", "participant_runner"]
