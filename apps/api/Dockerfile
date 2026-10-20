# syntax=docker/dockerfile:1
# Build from the repository root:  docker build -f apps/api/Dockerfile .
# The API image has no embedding model, PDF parser or LLM client: those live in the worker image.
FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/
COPY packages/core/pyproject.toml packages/core/
RUN uv sync --frozen --no-dev --package exam-api --no-install-workspace
COPY packages/core packages/core
COPY apps/api apps/api
RUN uv sync --frozen --no-dev --package exam-api

FROM python:3.14-slim
RUN useradd --system --uid 10001 --create-home app
WORKDIR /app/apps/api
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
# The ALB is the only thing that can reach the task, so trusting its forwarded headers is safe.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
