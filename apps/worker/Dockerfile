# syntax=docker/dockerfile:1
# Build from the repository root:  docker build -f apps/worker/Dockerfile .
FROM python:3.14-slim AS model
# The embedding model is downloaded in its own stage, before any project file is copied, so it is
# fetched again only when the model or this stage changes, not on every dependency or code update.
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
RUN pip install --no-cache-dir fastembed && \
    python -c "import os; from fastembed import TextEmbedding; TextEmbedding(os.environ['EMBEDDING_MODEL'], cache_dir='/opt/fastembed')"

FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/
COPY packages/core/pyproject.toml packages/core/
RUN uv sync --frozen --no-dev --package exam-worker --no-install-workspace
COPY packages/core packages/core
COPY apps/worker apps/worker
RUN uv sync --frozen --no-dev --package exam-worker

FROM python:3.14-slim
RUN useradd --system --uid 10001 --create-home app
WORKDIR /app/apps/worker
COPY --from=build /app /app
COPY --from=model --chown=app:app /opt/fastembed /opt/fastembed
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 EMBEDDING_CACHE_DIR=/opt/fastembed
USER app
CMD ["python", "-m", "worker"]
