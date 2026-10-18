# One entry point for the monorepo. Run `just` to list recipes.
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# --- shared infrastructure -------------------------------------------------
# Start PostgreSQL + pgvector
db-up:
    docker compose up -d --wait

db-down:
    docker compose down

# --- apps/api (Python, uv) ------------------------------------------------
# Install Python dependencies
api-install:
    cd apps/api && uv sync

# Run the API with reload on http://127.0.0.1:8000
api-dev:
    cd apps/api && uv run fastapi dev app/main.py

# Apply database migrations and load reference data
migrate:
    cd apps/api && uv run alembic upgrade head && uv run python -m scripts.seed_reference

# Load sample users (development only)
seed:
    cd apps/api && uv run python -m scripts.seed

# Tests (need `just db-up`); extra args go to pytest
api-test *args:
    cd apps/api && uv run pytest {{args}}

# Static type check (must report 0 errors)
api-check:
    cd apps/api && uv run pyright

# Build the production image
api-image:
    docker build -t learn-assistant:dev apps/api

# --- everything ---------------------------------------------------------------
# What CI runs for the API
check: api-check api-test
