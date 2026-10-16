# learn-assistant

A REST API that helps people study for the **AWS Certified Solutions Architect – Associate (SAA-C03)** exam.

The end goal is to generate exam-style practice questions with Retrieval-Augmented Generation (RAG) over AWS documentation, validate each question automatically, and serve them in timed exams or untimed practice sessions. This is a proof of concept: the API is the product, there is no frontend.

The POC is meant to demonstrate:

1. **RAG with grounding and validation:** questions cite their source chunks and must pass a blind-answer check.
2. **JWT authentication** with short-lived access tokens and rotating refresh tokens.
3. **Layered authorization:** roles, resource ownership and time rules as composable FastAPI dependencies.
4. **Server-enforced time windows** for exams, with results that unlock by mode and time.

The full requirements are in [`docs/PRD-aws-saa-study-assistant.md`](docs/PRD-aws-saa-study-assistant.md).

## Status

| Milestone | State |
|---|---|
| M1 Foundation (Docker Compose, Postgres + pgvector, Alembic, settings, health check) | Done |
| M2 Auth (users, login, refresh, logout, role and ownership dependencies, admin bootstrap) | Done |
| M3 Ingestion (sources, chunking, embeddings, samples) | Not started. Endpoints exist as `501` stubs with role checks |
| M4 Exams (lifecycle, time rules, answers, results, stats) | Done, using a small bank of hand-written fixture questions |
| M5 Question generation (retrieval, LLM generation, blind validation) | Not started |
| M6 Adaptive weighting from stats | Not started |

Until M5 lands, exams are built from 20 fixture questions rather than generated ones.

## Technologies

- **Python 3.14**, managed with [uv](https://docs.astral.sh/uv/)
- **FastAPI** for the API, with OpenAPI docs generated automatically
- **PostgreSQL + pgvector** (single database for relational data and, later, embeddings), run locally with Docker Compose
- **SQLAlchemy 2** (typed models) and **Alembic** migrations, via psycopg 3
- **PyJWT** for access tokens and **pwdlib (argon2)** for password hashing
- **pydantic-settings** for configuration from environment variables
- **pytest** for tests and **pyright** for static type checking
- Planned: the Anthropic API for generation and validation, and a local sentence-transformers model for embeddings

## Getting started

### Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Docker with Compose

### Setup

```bash
# 1. Install dependencies (creates .venv)
uv sync

# 2. Configure the environment
cp .env.example .env
#    then set JWT_SECRET_KEY, e.g.:
#    python -c "import secrets; print(secrets.token_urlsafe(48))"

# 3. Start PostgreSQL with pgvector
docker compose up -d --wait

# 4. Create the schema
uv run alembic upgrade head

# 5. Load exam reference data (domains, task statements) and the fixture question bank
uv run python -m scripts.seed_reference

# 6. (Development only) Load sample users
uv run python -m scripts.seed
```

The sample users are:

| Username | Password | Role |
|---|---|---|
| `alice` | `wonderland` | admin |
| `bob` | `builder` | student |
| `carol` | `christmas` | student |

These are for local development only. To create a real admin instead, run `uv run python -m scripts.create_admin <username>` (it prompts for the password, or reads `ADMIN_PASSWORD`).

### Run the app

```bash
uv run fastapi dev app/main.py
```

The API is served at http://127.0.0.1:8000 and reloads on code changes.

- Interactive docs: http://127.0.0.1:8000/docs (use **Authorize** with a username and password)
- OpenAPI schema: http://127.0.0.1:8000/openapi.json
- Health check: `GET /health`

All other endpoints live under `/api/v1`.

## Try it

A short practice session as a student, using `curl` and `jq`:

```bash
API=http://127.0.0.1:8000/api/v1

# Log in
TOKEN=$(curl -s -X POST $API/auth/login -d 'username=bob&password=builder' | jq -r .access_token)
AUTH="Authorization: Bearer $TOKEN"

# Create a practice exam with 3 questions
EXAM=$(curl -s -X POST $API/exams -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"mode": "practice", "question_count": 3}' | jq -r .id)

# Start it and read the questions (they are hidden until the exam starts)
curl -s -X POST $API/exams/$EXAM/start -H "$AUTH" | jq '.questions[] | {id, stem, options}'

# Answer a question. Practice mode returns immediate feedback.
QID=$(curl -s $API/exams/$EXAM -H "$AUTH" | jq '.questions[0].id')
curl -s -X PUT $API/exams/$EXAM/answers/$QID -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"selected_option": "B"}' | jq

# See results and your accuracy per domain
curl -s $API/exams/$EXAM/results -H "$AUTH" | jq '{correct, answered, total}'
curl -s $API/me/stats -H "$AUTH" | jq '.domains[] | {name, attempted, accuracy}'
```

Using `"mode": "exam"` instead gives a timed exam: 2 minutes per question (130 minutes for 65), enforced on the server clock. Answers are rejected after the deadline, and results stay locked until you submit (`POST /exams/$EXAM/submit`) or time runs out.

### Who can call what

| Role | Access |
|---|---|
| Anyone | `GET /health`, `POST /auth/login`, `POST /auth/refresh` |
| Any signed-in user | `POST /auth/logout`, `GET /sources`, `GET /me/stats` |
| `student` | Everything under `/exams` (you can only see your own exams) |
| `admin` | `POST /users`, and `POST`/`DELETE /sources`, `POST /samples` (not yet implemented) |

Access tokens last 15 minutes. Refresh them with `POST /auth/refresh`, which also rotates the refresh token. `POST /auth/logout` revokes the current access token immediately.

## Tests and checks

The tests need PostgreSQL running (`docker compose up -d --wait`). They create and reset their own `learn_assistant_test` database, so your development data is never touched.

```bash
uv run pytest        # run the test suite
uv run pyright       # static type check (must report 0 errors)
```

The suite covers authentication and token handling, role-based access for every endpoint, exam time rules (using an injectable clock), results locking and statistics.

## Project layout

```
app/
  main.py            FastAPI app and router wiring
  config.py          Settings from environment variables
  db.py, models.py   SQLAlchemy engine and models
  security.py        JWT, refresh tokens, password hashing
  dependencies.py    Authentication and role dependencies
  auth.py            /auth routes
  users.py           /users routes
  exams.py           /exams routes
  exam_deps.py       Ownership, active-window and results-unlocked dependencies
  exam_service.py    Exam creation, question selection, scoring
  stats.py           /me/stats
  sources.py         /sources and /samples (stubs)
  clock.py           Injectable server clock
migrations/          Alembic migrations
scripts/             Seed and admin-bootstrap scripts, fixture questions
tests/               pytest suite
docs/                Product requirements document
compose.yaml         PostgreSQL + pgvector for local development
```

To add a migration after changing models: `uv run alembic revision --autogenerate -m "describe change"`, review the generated file, then `uv run alembic upgrade head`.

## Configuration

Settings come from environment variables or a `.env` file (see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `JWT_SECRET_KEY` | required | Signs access tokens. Keep it secret. |
| `DATABASE_URL` | local compose database | SQLAlchemy URL for PostgreSQL |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |
| `EXAM_MINUTES_PER_QUESTION` | `2` | Exam-mode time limit per question |
