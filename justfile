# One entry point for the monorepo. Run `just` to list recipes.
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# --- shared infrastructure -------------------------------------------------
# Start PostgreSQL + pgvector and the local SQS stand-in (ElasticMQ)
db-up:
    docker compose up -d --wait

db-down:
    docker compose down

# --- Python workspace (uv): apps/api, apps/worker, packages/core -----------------
# Install Python dependencies for all three
api-install:
    uv sync --all-packages

# Run the API with reload on http://127.0.0.1:8000
api-dev:
    cd apps/api && uv run fastapi dev app/main.py

# Apply database migrations and load reference data
migrate:
    cd packages/core && uv run alembic upgrade head && cd ../../apps/api && uv run python -m scripts.seed_reference

# Load sample users (development only)
seed:
    cd apps/api && uv run python -m scripts.seed

# Tests (need `just db-up`); extra args go to pytest
api-test *args:
    cd apps/api && uv run pytest {{args}}

# Static type check of the whole Python workspace (must report 0 errors)
api-check:
    uv run pyright

# Production images (the build context is the repository root)
api-image:
    docker build -f apps/api/Dockerfile -t exam-generator-api:dev .

worker-image:
    docker build -f apps/worker/Dockerfile -t exam-generator-worker:dev .

# --- apps/worker (queue consumer: PDFs, embeddings, question generation) ------------
# Run the worker (needs `just db-up`; reads apps/worker/.env)
worker-dev:
    cd apps/worker && uv run python -m worker

# Worker tests (need `just db-up`); extra args go to pytest
worker-test *args:
    cd apps/worker && uv run pytest {{args}}

# --- everything ---------------------------------------------------------------
# What CI runs for the Python and JS code
check: api-check api-test worker-test js-check

# --- JavaScript workspace (pnpm) ----------------------------------------------
# Install JS dependencies
js-install:
    pnpm install

# Export the API's OpenAPI schema and regenerate the TypeScript client types
gen-client:
    cd apps/api && uv run python -m scripts.export_openapi
    pnpm --filter @exam-generator/api-client generate

# Type-check all JS packages and run the web tests
js-check:
    pnpm typecheck
    pnpm --filter web test

# Run the web app on http://localhost:5173 (proxies /api to the API on :8000)
web-dev:
    pnpm --filter web dev

# Production build of the web app (apps/web/dist)
web-build:
    pnpm --filter web build
