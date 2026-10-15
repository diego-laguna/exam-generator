# learn-assistant

FastAPI REST API that generates and validates AWS SAA-C03 practice questions with RAG, plus timed exams.
Full requirements: `docs/PRD-aws-saa-study-assistant.md` (not auto-loaded). Read the relevant section before implementing a milestone.

## Stack
- Python 3.14, FastAPI, managed with `uv`
- PostgreSQL + pgvector (single DB for relational data and vectors), image `pgvector/pgvector:pg17`
- SQLAlchemy 2 + Alembic (psycopg 3); migrations in `migrations/`
- Auth: PyJWT + pwdlib (argon2), settings via pydantic-settings
- Planned: Anthropic API (generation/validation), local sentence-transformers embeddings

## Commands
- DB: `docker compose up -d --wait`
- Migrate: `uv run alembic upgrade head` (new: `uv run alembic revision --autogenerate -m "..."`)
- Seed sample users: `uv run python -m scripts.seed`
- Run: `uv run fastapi dev app/main.py`
- Test: `uv run pytest` (needs the DB up; uses its own `learn_assistant_test` database)
- Config: copy `.env.example` to `.env`

## Rules that always apply
- Server clock (UTC) is the only source of time; never trust client time.
- All authorization lives in FastAPI dependencies, not in route handlers.
- Non-owned resources return 404, not 403.
- Never return `correct_option` or `explanation` before results are unlocked.
- Generated questions must cite existing chunk IDs and pass blind validation.
- Ingestion URLs must match the allowlist (SSRF).
- No secrets in the repo.

## Status
PRD milestones: M1 (foundation) and M2 (auth) are done except `POST /users` and the admin seed.
Deviations from the PRD, decided:
- Routes live under `/api/v1`; `/health` stays unversioned.
- Access token 15 min; refresh tokens are opaque, hashed, single-use (rotated), 7 days.
- Logout deletes the given refresh token and denylists the access token JTI (`revoked_tokens`, purged after expiry).
- Password change must call `revoke_all_refresh_tokens` (no password-change endpoint yet).
- Refresh tokens are deleted rather than flagged `revoked_at`.
- Postgres is pg17 (PRD updated).
