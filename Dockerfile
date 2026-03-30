FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock alembic.ini README.md ./
COPY apps ./apps
COPY src ./src
COPY migrations ./migrations
COPY scripts ./scripts

RUN uv sync --no-dev

EXPOSE 8000 8010
