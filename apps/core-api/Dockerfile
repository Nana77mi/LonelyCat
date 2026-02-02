FROM python:3.11-slim

WORKDIR /app

COPY apps/core-api/pyproject.toml ./

RUN pip install --no-cache-dir \
    "fastapi>=0.110" \
    "pydantic>=2.6" \
    "uvicorn>=0.27"

COPY apps/core-api/app ./app

EXPOSE 5173

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5173"]
