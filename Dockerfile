FROM ghcr.io/astral-sh/uv:0.8.22 AS uv
FROM python:3.13-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates bash libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_LINK_MODE=copy PYTHONUNBUFFERED=1 PYTHONUTF8=1
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY . .
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 && rm -rf /var/lib/apt/lists/*
RUN uv sync --locked --no-dev && .venv/bin/python scripts/prepare_hosted_hermes.py
ENV PATH="/app/.venv/bin:${PATH}" BRANDPILOT_STORAGE_ROOT=/data/storage BRANDPILOT_SESSION_COOKIE_SECURE=true
CMD ["python", "scripts/run_hosted.py"]
