# Build from repo root (context: .) so packages and apps are available.
# core-api depends on packages/memory and imports agent_worker.memory_client.
FROM python:3.11-slim

WORKDIR /app

# Copy monorepo packages and apps needed for core-api
COPY packages/memory /app/packages/memory
COPY apps/agent-worker /app/apps/agent-worker
COPY apps/core-api /app/apps/core-api

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -e /app/packages/memory && \
    pip install --no-cache-dir -e /app/apps/agent-worker && \
    pip install --no-cache-dir -e /app/apps/core-api

ENV PYTHONPATH=/app/packages

EXPOSE 5173

# Run from repo root so --app-dir resolves; SQLite DB defaults to CWD (use volume for persistence)
WORKDIR /app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5173", "--app-dir", "apps/core-api"]
