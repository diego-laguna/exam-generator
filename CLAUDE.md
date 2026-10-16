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
- Seed exam reference data + fixture questions: `uv run python -m scripts.seed_reference` (required after migrating)
- Seed sample users: `uv run python -m scripts.seed` (alice=admin, bob/carol=students)
- Bootstrap an admin: `uv run python -m scripts.create_admin <username>` (prompts, or set `ADMIN_PASSWORD`)
- Run: `uv run fastapi dev app/main.py`
- Type check: `uv run pyright` (standard mode; must stay at 0 errors)
- Test: `uv run pytest` (needs the DB up; uses its own `learn_assistant_test` database)
- Config: copy `.env.example` to `.env`

## Rules that always apply
- Code is fully type-annotated and must pass pyright; runtime validation is Pydantic (requests, settings, LLM JSON).
- Server clock (UTC) is the only source of time; never trust client time.
- All authorization lives in FastAPI dependencies, not in route handlers.
- Non-owned resources return 404, not 403.
- Never return `correct_option` or `explanation` before results are unlocked.
- Generated questions must cite existing chunk IDs and pass blind validation.
- Ingestion URLs must match the allowlist (SSRF).
- No secrets in the repo.

## Status
PRD milestones done: M1 (foundation), M2 (auth, `POST /users`, admin bootstrap), M4 (exams with fixture questions).
Still stubs (501, role checks in place): `/sources*` and `/samples` (M3). Next: M3, then M5 (generation).
Decisions beyond the PRD text:
- Routes live under `/api/v1`; `/health` stays unversioned.
- Access token 15 min; refresh tokens are opaque, hashed, single-use (rotated), 7 days, deleted (not flagged) on use/logout.
- Logout also denylists the access token JTI (`revoked_tokens`, purged after expiry).
- Password change must call `revoke_all_refresh_tokens` (no password-change endpoint yet).
- Exam mode time limit = 2 min per question (65 questions -> 130 min), set at `/start` on the server clock.
- Requesting more questions than the bank holds serves what exists (`requested_question_count` vs `question_count`); 0 available -> `failed`.
- `GET /exams/{id}` returns questions only after start and never `correct_option`/`explanation`; practice answers return feedback in the `PUT` response.
- Exam endpoints are student-only; admins get 403 (PRD open question).
- Domain ids 1-4 follow the exam guide; `POST /exams` takes `domains: [ids]`.
- `/me/stats` counts practice answers and answers from finished exams only.
- Time is injectable via the `get_clock` dependency; tests override it.
- Error responses for exam rules use `detail: {code, message}` (e.g. `EXAM_WINDOW_CLOSED`, `RESULTS_LOCKED`).
