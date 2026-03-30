FROM python:3.11-slim

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install curl for remote_exec commands
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock* ./

# Install dependencies
RUN uv sync --no-dev --no-editable

# Copy application code
COPY src/ src/
COPY apps/ apps/
COPY scripts/ scripts/
COPY migrations/ migrations/
COPY alembic.ini ./

# Default command (overridden by docker-compose per service)
CMD ["uv", "run", "uvicorn", "apps.gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
