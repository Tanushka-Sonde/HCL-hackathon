FROM python:3.11-slim AS base

WORKDIR /app

# System deps for asyncpg (libpq) and building wheels
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.in .
RUN pip install --no-cache-dir -r requirements.in

COPY . .

# Default: API server
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
