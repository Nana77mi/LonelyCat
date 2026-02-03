# Build from repo root (context: .). Worker needs core-api app (app.db) and agent-worker.
FROM python:3.11-slim

WORKDIR /app

COPY packages/memory /app/packages/memory
COPY apps/core-api /app/apps/core-api
COPY apps/agent-worker /app/apps/agent-worker

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -e /app/packages/memory && \
    pip install --no-cache-dir -e /app/apps/core-api && \
    pip install --no-cache-dir -e /app/apps/agent-worker

# Worker imports app.db from core-api
ENV PYTHONPATH=/app/packages:/app/apps/core-api

WORKDIR /app/apps/agent-worker
CMD ["python", "-m", "worker.main"]
