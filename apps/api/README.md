# Exam-Generator API

This is the Python/FastAPI service of the monorepo (see the [root README](../../README.md)). All commands below run from `apps/api`; from the repo root, `just` recipes wrap them. `docs/`, `infra/terraform/`, `compose.yaml` and the CI workflow live at the repo root.

A REST API that turns a teacher's PDFs into exam questions.

A teacher uploads PDFs. The API generates multiple-choice and true/false questions from them, each with the correct answer, an explanation and **citations to the source file, page and line**. Every question is checked automatically before it is stored: its citations must match the cited lines, and a second, blind model call must pick the same answer. The teacher selects questions into a **question set**, saves it for later reuse, and downloads a **printable PDF** for students (plus an answer key). This is a proof of concept: the API is the product, there is no frontend.

It also keeps an earlier module: timed AWS SAA-C03 practice exams for students, served from a small fixture question bank.

The POC demonstrates:

1. **Grounded generation with verification:** citations are checked against the extracted page lines, and questions pass a blind-answer check.
2. **JWT authentication** with short-lived access tokens and rotating refresh tokens.
3. **Layered authorization:** roles, per-teacher ownership and time rules as composable FastAPI dependencies.
4. **A deployable AWS setup:** container image, Terraform for ECS Fargate, RDS PostgreSQL with pgvector, S3 and Secrets Manager.

Requirements: [`docs/PRD-exam-generator.md`](../../docs/PRD-exam-generator.md) (current) and [`docs/PRD-aws-saa-study-assistant.md`](../../docs/PRD-aws-saa-study-assistant.md) (student module). Deployment: [`docs/DEPLOY.md`](../../docs/DEPLOY.md).

## Status

| Area | State |
|---|---|
| Foundation, auth, roles, ownership dependencies | Done |
| Teacher flow: PDF upload, extraction with page/line numbers, embeddings | Done |
| Question generation (multiple choice, true/false) with verified citations and blind validation | Done; tested with a fake model, not yet run against the real API |
| Question sets (save, reuse) and printable student / teacher PDFs | Done |
| AWS deployment (Dockerfile, Terraform, CI) | Provided; Terraform validated, not applied |
| Student module (timed SAA-C03 exams, stats) | Done, fixture questions only |
| Durable job queue (SQS) and a separate worker app | Done (`apps/worker`) |
| Question editing, assigning sets to students | Not started |

## Technologies

- **Python 3.14**, managed with [uv](https://docs.astral.sh/uv/)
- **FastAPI** for the API, with OpenAPI docs generated automatically
- **PostgreSQL + pgvector** (single database for relational data and embeddings), run locally with Docker Compose
- **SQLAlchemy 2** (typed models) and **Alembic** migrations, via psycopg 3
- **PyJWT** for access tokens and **pwdlib (argon2)** for password hashing
- **pydantic-settings** for configuration from environment variables
- **pytest** for tests and **pyright** for static type checking
- **ReportLab** to write the printable PDFs
- **boto3**: S3 for PDF storage on AWS (a local folder in development) and SQS to hand work to the worker
- The heavy libraries are in [`apps/worker`](../worker): fastembed (ONNX, `BAAI/bge-small-en-v1.5`, 384 dimensions), pdfminer.six, the Anthropic API client, httpx2 and BeautifulSoup
- **Docker** and **Terraform** for AWS

## Getting started

### Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Docker with Compose
- [just](https://github.com/casey/just) (optional; the recipes wrap the commands below)

### Setup

```bash
# 1. Install dependencies for the whole workspace (creates .venv at the repository root)
uv sync --all-packages

# 2. Configure the environment (from apps/api)
cp .env.example .env
#    then set JWT_SECRET_KEY, e.g.:
#    python -c "import secrets; print(secrets.token_urlsafe(48))"
#    To generate questions, set ANTHROPIC_API_KEY in apps/worker/.env (the worker calls the model,
#    not the API). Edit it yourself and use a key with a spend limit.

# 3. Start PostgreSQL with pgvector and the local queue (ElasticMQ)
docker compose -f ../../compose.yaml up -d --wait

# 4. Create the schema (the migrations live in packages/core; `just migrate` does steps 4 and 5)
(cd ../../packages/core && uv run alembic upgrade head)

# 5. Load exam reference data (domains, task statements) and the fixture question bank
uv run python -m scripts.seed_reference

# 6. (Development only) Load sample users
uv run python -m scripts.seed

# 7. Start the worker in another terminal, so uploads and generation jobs get processed
cd ../worker && cp .env.example .env && uv run python -m worker
```

The sample users are:

| Username | Password | Role |
|---|---|---|
| `alice` | `wonderland` | admin |
| `bob` | `builder` | student |
| `carol` | `christmas` | student |
| `dave` | `teacher-pass` | teacher |

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

### As a teacher

The worker must be running (`just worker-dev`) for uploads to become `ready` and for generation to run. Generation also needs `ANTHROPIC_API_KEY` in `apps/worker/.env`; without it the job fails with "Question generation is not configured". Uploading, listing and exporting need no key.

```bash
API=http://127.0.0.1:8000/api/v1
TOKEN=$(curl -s -X POST $API/auth/login -d 'username=dave&password=teacher-pass' | jq -r .access_token)
AUTH="Authorization: Bearer $TOKEN"

# Upload a PDF (it needs a text layer; scanned PDFs are rejected) and wait for status "ready"
DOC=$(curl -s -X POST $API/documents -H "$AUTH" -F file=@lesson.pdf | jq -r .id)
curl -s $API/documents/$DOC -H "$AUTH" | jq '{status, page_count, chunk_count, error}'

# Generate 5 multiple-choice and 3 true/false questions (optionally add "focus": "photosynthesis")
JOB=$(curl -s -X POST $API/generations -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"document_ids\": [$DOC], \"mcq_count\": 5, \"true_false_count\": 3}" | jq -r .id)
curl -s $API/generations/$JOB -H "$AUTH" | jq '{status, requested_count, produced_count, question_ids}'

# Review the questions: answer, explanation and where in the PDF it comes from
curl -s $API/questions -H "$AUTH" | jq '.[] | {id, type, stem, correct_option, citations}'

# Save a selection as a reusable set, then download the PDFs
SET=$(curl -s -X POST $API/question-sets -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"title": "Unit 1 quiz", "question_ids": [1, 2, 3]}' | jq -r .id)
curl -s "$API/question-sets/$SET/pdf" -H "$AUTH" -o quiz-students.pdf                      # no answers
curl -s "$API/question-sets/$SET/pdf?version=teacher" -H "$AUTH" -o quiz-answer-key.pdf    # answers + sources
```

A citation looks like `{"document": "lesson.pdf", "page": 3, "line_start": 12, "line_end": 14, "quote": "..."}`. Lines are the non-empty text lines of the page, numbered from 1 in reading order. Questions that fail the checks are discarded, so a job can produce fewer questions than requested (`produced_count`).

#### Download the built-in exam and run a timed session

A fixed, built-in exam (6 questions) lets you try the whole classroom flow without generating anything. In the web app: **Exam** in the menu.

```bash
curl -s "$API/sample-exam/pdf" -H "$AUTH" -o exam-students.pdf                       # questions only
curl -s "$API/sample-exam/pdf?version=teacher" -H "$AUTH" -o exam-answer-key.pdf     # questions, answers, explanations

# Open the exam to students for 30 minutes (the clock starts now); share the join_url
curl -s -X POST $API/exam-sessions -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"exam_id": "sample", "duration_minutes": 30}' | jq '{id, join_url, ends_at}'

# Live dashboard: who joined, who submitted, scores, average, per-question results
curl -s $API/exam-sessions/1 -H "$AUTH" | jq '{participants, average_score}'
curl -s -X POST $API/exam-sessions/1/close -H "$AUTH"     # end early (optional)
```

Students need no account. They open the `join_url` (`/join/<token>` in the web app), type a name and answer; each answer is saved on the server as they go. **Submit** shows the score, the correct answers and the explanations immediately, and the teacher's dashboard (it refreshes every 5 seconds) shows the result. The time limit is enforced on the server clock: answers after `ends_at` are rejected, and students who never pressed Submit are scored on what they saved. The same flow over the API, as a student would do it:

```bash
J=<token from the join_url>
P=$(curl -s -X POST $API/join/$J/participants -H 'Content-Type: application/json' -d '{"name": "Ana"}' | jq -r .participant_token)
curl -s $API/join/$J/me -H "X-Participant-Token: $P" | jq '.questions'                    # no answers inside
curl -s -X PUT $API/join/$J/answers/q1 -H "X-Participant-Token: $P" -H 'Content-Type: application/json' -d '{"selected_option": "B"}'
curl -s -X POST $API/join/$J/submit -H "X-Participant-Token: $P" | jq '{score, total}'
```

The join link is the credential: anyone who has it can join until the session ends (names must be unique within a session, at most `SESSION_MAX_PARTICIPANTS`), so share it only with the class. There is no rate limiting on these public endpoints yet.

### As a student (legacy module)

A short practice session using `curl` and `jq`:

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
| Anyone | `GET /health`, `POST /auth/login`, `POST /auth/refresh`, and `/join/{token}/...` (exam-session students; the secret link and a per-student token are the credentials) |
| Any signed-in user | `POST /auth/logout`, `GET /sources`, `GET /me/stats` |
| `teacher` | `/documents`, `/generations`, `/questions`, `/question-sets`, `/sample-exam`, `/exam-sessions` (you can only see your own) |
| `student` | Everything under `/exams` (you can only see your own exams) |
| `admin` | `POST /users` (including teachers), `POST`/`DELETE /sources`, `POST /samples` |

Access tokens last 15 minutes. Refresh them with `POST /auth/refresh`, which also rotates the refresh token. Browsers also receive it as an httpOnly cookie, and `/auth/refresh` and `/auth/logout` fall back to that cookie when no body is sent. `POST /auth/logout` revokes the current access token immediately.

### Add documentation to the student module's knowledge base

Admins ingest documentation pages. Only `https://docs.aws.amazon.com` and `https://aws.amazon.com` URLs are accepted.

```bash
ADMIN=$(curl -s -X POST $API/auth/login -d 'username=alice&password=wonderland' | jq -r .access_token)
curl -s -X POST $API/sources -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' \
  -d '{"url": "https://docs.aws.amazon.com/AmazonS3/latest/userguide/storage-class-intro.html"}'
curl -s $API/sources -H "Authorization: Bearer $ADMIN" | jq   # status: pending -> ingesting -> ready
```

Ingestion runs in the worker: the page is fetched, split into overlapping chunks at its headings, embedded, and stored in PostgreSQL with pgvector. The first ingestion downloads the embedding model (about 130 MB, cached in `.cache/fastembed` at the repository root).

## Errors and logging

Every error response is `application/problem+json` (RFC 9457) with the same body, and carries an `X-Request-ID` header (an incoming one is kept if it is up to 128 chars of `A-Za-z0-9._-`, else a new one is made):

```json
{
  "type": "about:blank",
  "title": "Conflict",
  "status": 409,
  "code": "NAME_TAKEN",
  "detail": "Someone already joined with that name; add your surname or a number",
  "instance": "/api/v1/join/.../participants",
  "request_id": "5b0f0c0e8f3a4c1c9a41a0d3b7e2c6aa",
  "errors": []
}
```

Branch on `code`, show `detail`. Validation errors (422, `VALIDATION_ERROR`) fill `errors[]` with `{field, message, type}`. Unexpected errors are 500 `INTERNAL_ERROR` with a generic message; the cause is only in the logs, under the same `request_id`.

Code raises `exam_core.errors` exceptions (`NotFound`, `Conflict`, `InvalidInput`, ...), never `HTTPException`; `app/errors.py` holds the handlers.

| Status | When |
|---|---|
| 401 | Missing, invalid or expired credentials or tokens (`WWW-Authenticate: Bearer`) |
| 403 | Signed in with the wrong role |
| 404 | Unknown or not-owned resource (never 403 for foreign ids) |
| 409 | State conflicts and duplicates |
| 413 | Upload over the size cap |
| 429 | Too many failed logins (`Retry-After` header) |
| 422 | Invalid request or semantically invalid input |
| 503 | Queue or storage down or not configured |
| 500 / 501 | Unexpected / placeholder |

Codes: `UNAUTHENTICATED`, `INVALID_CREDENTIALS`, `INVALID_TOKEN`, `INVALID_REFRESH_TOKEN`, `TOO_MANY_REQUESTS`, `FORBIDDEN`, `NOT_FOUND`, `METHOD_NOT_ALLOWED`, `DOCUMENT_NOT_FOUND`, `QUESTION_NOT_FOUND`, `QUESTION_SET_NOT_FOUND`, `GENERATION_NOT_FOUND`, `SOURCE_NOT_FOUND`, `EXAM_NOT_FOUND`, `EXAM_SESSION_NOT_FOUND`, `PARTICIPANT_NOT_FOUND`, `USERNAME_TAKEN`, `DOCUMENT_DUPLICATE`, `SOURCE_DUPLICATE`, `DOCUMENT_NOT_READY`, `JOB_IN_PROGRESS`, `QUESTION_SET_EMPTY`, `EXAM_NOT_STARTED`, `EXAM_WINDOW_CLOSED`, `EXAM_NOT_AVAILABLE`, `EXAM_ALREADY_STARTED`, `RESULTS_LOCKED`, `SESSION_ENDED`, `SESSION_FULL`, `NAME_TAKEN`, `ALREADY_SUBMITTED`, `FILE_TOO_LARGE`, `NOT_A_PDF`, `VALIDATION_ERROR`, `INVALID_OPTION`, `DURATION_TOO_LONG`, `UNKNOWN_DOMAIN`, `UNKNOWN_TASK_STATEMENT`, `TASK_DOMAIN_MISMATCH`, `QUEUE_NOT_CONFIGURED`, `QUEUE_UNAVAILABLE`, `STORAGE_UNAVAILABLE`, `NOT_IMPLEMENTED`, `INTERNAL_ERROR`.

Logs are one JSON object per line on stderr (`timestamp`, `level`, `logger`, `message`, `exc_info`, plus context such as `request_id`), shared with the worker through `exam_core.logging`. The API writes one access line per request (`method`, `path` without the query string, `status`, `duration_ms`). Set `LOG_LEVEL` and `LOG_FORMAT=text` for readable local output. Tokens, passwords, join tokens and Authorization/cookie headers are never logged.

## Tests and checks

The tests need PostgreSQL running (`docker compose -f ../../compose.yaml up -d --wait`). They create and reset their own `learn_assistant_test` database, so your development data is never touched. The worker's tests use `learn_assistant_worker_test`.

```bash
uv run pytest                        # this app's tests (from apps/api)
(cd ../worker && uv run pytest)      # the worker's tests
uv run pyright                       # static type check of the whole workspace (0 errors)
```

The tests never download the embedding model or touch the network, SQS or S3. The API tests replace the queue with an in-memory recorder (`exam_core.testing.MemoryQueue`) and check the messages it was given; the worker tests run each job function against a deterministic fake embedder, fetcher, storage and LLM. An autouse fixture disables the real LLM even if a key is configured.

The API suite covers authentication and token handling, ownership of every teacher resource, queueing (including the queue being down), question sets and PDF export, role-based access for every endpoint, exam time rules (using an injectable clock), results locking, statistics, and pgvector similarity search. The worker suite covers PDF line extraction, citation verification, generation (retries, rejections, failures), redelivery of messages, the receive loop, and SQS calls.

## Project layout

```
app/
  main.py            FastAPI app and router wiring
  config.py          API settings (JWT, cookies, exam rules) on top of exam_core's shared settings
  security.py        JWT, refresh tokens, password hashing
  dependencies.py    Authentication and role dependencies
  auth.py            /auth routes
  users.py           /users routes
  exams.py           /exams routes
  exam_deps.py       Ownership, active-window and results-unlocked dependencies
  exam_service.py    Exam creation, question selection, scoring
  stats.py           /me/stats
  documents.py       /documents (teacher uploads)
  queueing.py        Sends background work to the queue (the worker does it)
  generations.py     /generations (jobs)
  questions.py       /questions (the teacher's bank)
  question_sets.py   /question-sets and PDF download
  exam_sessions.py   Built-in exam PDFs, timed sessions, the student /join routes and the dashboard
  sample_exam.py     The built-in exam (questions as code)
  pdf_export.py      Printable student sheet and teacher answer key
  sources.py         /sources and /samples (student module)
  retrieval.py       Similarity search over chunks
  clock.py           Injectable server clock
scripts/             Seed and admin-bootstrap scripts, fixture questions
tests/               pytest suite
Dockerfile           Production image (build context: the repository root)
```

Shared code is in [`packages/core`](../../packages/core) (`exam_core`: settings, database engine and models, storage, queue messages, SSRF URL guard) and the queue consumer in [`apps/worker`](../worker). The Alembic migrations (`alembic.ini`, `migrations/`) are there too, next to the models they describe, because the schema belongs to neither service. The API image carries them and runs them in the one-off migrate task.

To add a migration after changing models, from `packages/core`: `uv run alembic revision --autogenerate -m "describe change"`, review the generated file, then `uv run alembic upgrade head` (or `just migrate`). Alembic reads the same settings as the apps (`DATABASE_URL` or `DB_*` in the environment; the local default needs nothing).

## Configuration

Settings come from environment variables or a `.env` file (see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `JWT_SECRET_KEY` | required | Signs access tokens. Keep it secret. |
| `REFRESH_COOKIE_SECURE` | `true` | `Secure` flag of the refresh cookie. Set `false` only for plain-HTTP deployments (a localhost dev server works with `true`). |
| `SQS_QUEUE_URL` | unset | Job queue. Without it, uploads and generations answer 503 `QUEUE_NOT_CONFIGURED`. Locally: `http://localhost:9324/000000000000/exam-generator-jobs` |
| `SQS_ENDPOINT_URL` / `SQS_REGION` | unset / `us-east-1` | Endpoint override for a local emulator; region of the queue |
| `ANTHROPIC_API_KEY`, `LLM_GENERATION_MODEL`, `LLM_VALIDATION_MODEL`, `PDF_MAX_PAGES`, `EMBEDDING_MODEL`, chunk settings | worker only | See [`apps/worker`](../worker); the API never reads them |
| `DATABASE_URL` | local compose database | SQLAlchemy URL for PostgreSQL |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | unset | Used instead of `DATABASE_URL` when `DB_HOST` is set (AWS) |
| `STORAGE_BACKEND` | `local` | `local` (folder `LOCAL_STORAGE_DIR`, default `../../.data/documents`, shared with the worker) or `s3` (needs `S3_BUCKET`) |
| `UPLOAD_MAX_BYTES` | 25 MB | Upload size limit |
| `GENERATION_MAX_QUESTIONS` | 50 | Per request |
| `JOB_STALE_MINUTES` | `30` | A job or document still running after this long is reported as failed |
| `LOGIN_MAX_FAILURES_PER_USERNAME` / `LOGIN_MAX_FAILURES_PER_IP` | `5` / `20` | Failed logins allowed per username / client IP within the window; beyond that `/auth/login` answers 429 `TOO_MANY_REQUESTS` with `Retry-After` (seconds). A successful login clears the username's failures |
| `LOGIN_WINDOW_SECONDS` | `900` | Sliding window of the login limiter |
| `TRUSTED_PROXY_HOPS` | `0` | Proxies in front of the API (ALB = `1`). When > 0 the client IP is the `X-Forwarded-For` entry that many hops from the right; when 0 the header is ignored |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |
| `EXAM_MINUTES_PER_QUESTION` | `2` | Exam-mode time limit per question |
| `WEB_BASE_URL` | `http://localhost:5173` | Origin of the web app, used to build the session `join_url` (no trailing slash). Set it to the public URL in production |
| `SESSION_MAX_MINUTES` / `SESSION_MAX_PARTICIPANTS` | `480` / `300` | Longest session a teacher can start; students per session |
| `INGESTION_ALLOWED_HOSTS` | AWS docs hosts | Hosts that sources may come from (JSON list) |

## Deploying to AWS

See [`docs/DEPLOY.md`](../../docs/DEPLOY.md): build the API and worker images, `terraform apply` in `infra/terraform/`, store the Anthropic key in Secrets Manager, run the migration task, start the API and the worker.
