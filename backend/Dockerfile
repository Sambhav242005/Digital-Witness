# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# ffmpeg is required by app/media.py for preparation and frame extraction.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Layer-cache dependencies separately from source.
# No [build-system] in pyproject.toml, so this installs deps only.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache

COPY . .

# Render assigns $PORT at runtime.
EXPOSE 10000
CMD ["sh", "-c", "exec uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-10000}\""]
