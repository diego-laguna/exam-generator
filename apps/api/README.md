# learn-assistant API

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
| Durable job queue (SQS), question editing, assigning sets to students | Not started |

## Technologies

- **Python 3.14**, managed with [uv](https://docs.astral.sh/uv/)
- **FastAPI** for the API, with OpenAPI docs generated automatically
- **PostgreSQL + pgvector** (single database for relational data and embeddings), run locally with Docker Compose
- **SQLAlchemy 2** (typed models) and **Alembic** migrations, via psycopg 3
- **PyJWT** for access tokens and **pwdlib (argon2)** for password hashing
- **pydantic-settings** for configuration from environment variables
- **pytest** for tests and **pyright** for static type checking
- **fastembed** (ONNX, `BAAI/bge-small-en-v1.5`, 384 dimensions) for local embeddings
- **pdfminer.six** to read PDFs line by line, **ReportLab** to write the printable PDFs
- **Anthropic API** for generation and validation (the key is optional for everything else)
- **boto3 / S3** for PDF storage on AWS (a local folder in development)
- **httpx2** and **BeautifulSoup** for the student module's documentation ingestion
- **Docker** and **Terraform** for AWS

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
#    and, to generate questions, ANTHROPIC_API_KEY (edit .env yourself; use a key with a spend limit)

# 3. Start PostgreSQL with pgvector
docker compose -f ../../compose.yaml up -d --wait

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

The teacher flow needs `ANTHROPIC_API_KEY` in `.env` for the generation step. Uploading, listing and exporting work without it.

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
| Anyone | `GET /health`, `POST /auth/login`, `POST /auth/refresh` |
| Any signed-in user | `POST /auth/logout`, `GET /sources`, `GET /me/stats` |
| `teacher` | `/documents`, `/generations`, `/questions`, `/question-sets` (you can only see your own) |
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

Ingestion runs in the background: the page is fetched, split into overlapping chunks at its headings, embedded, and stored in PostgreSQL with pgvector. The first ingestion downloads the embedding model (about 130 MB, cached in `.cache/fastembed`).

## Tests and checks

The tests need PostgreSQL running (`docker compose -f ../../compose.yaml up -d --wait`). They create and reset their own `learn_assistant_test` database, so your development data is never touched.

```bash
uv run pytest        # run the test suite
uv run pyright       # static type check (must report 0 errors)
```

The tests never download the embedding model or touch the network; they use a deterministic fake embedder and fetcher.

The suite also stands in for the model, storage and embedder (`tests/helpers_teacher.py`), so it never calls the Anthropic API or S3, and an autouse fixture disables the real LLM even if your `.env` has a key.

The suite covers authentication and token handling, PDF line extraction, citation verification, generation (retries, rejections, failures), ownership of every teacher resource, question sets and PDF export, role-based access for every endpoint, exam time rules (using an injectable clock), results locking statistics, URL allowlisting (including SSRF bypass attempts), chunking, and pgvector similarity search.

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
  documents.py       /documents (teacher uploads)
  document_ingestion.py  Background job: PDF -> numbered lines -> chunks -> embeddings
  pdf_text.py        PDF line extraction, chunking, citation quote check
  storage.py         PDF storage: local folder or S3
  llm.py             Anthropic client behind a small protocol
  question_gen.py    Generation pipeline: draft, verify citations, blind validation
  generations.py     /generations (jobs)
  questions.py       /questions (the teacher's bank)
  question_sets.py   /question-sets and PDF download
  pdf_export.py      Printable student sheet and teacher answer key
  sources.py         /sources and /samples (student module)
  fetching.py        Allowlisted, size-capped page fetching (SSRF guard)
  chunking.py        HTML -> heading-aware chunks
  embeddings.py      Local embedding model
  ingestion.py       Background ingestion job
  retrieval.py       Similarity search over chunks
  clock.py           Injectable server clock
migrations/          Alembic migrations
scripts/             Seed and admin-bootstrap scripts, fixture questions
tests/               pytest suite
Dockerfile           Production image (build context: this folder)
```

To add a migration after changing models: `uv run alembic revision --autogenerate -m "describe change"`, review the generated file, then `uv run alembic upgrade head`.

## Configuration

Settings come from environment variables or a `.env` file (see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `JWT_SECRET_KEY` | required | Signs access tokens. Keep it secret. |
| `REFRESH_COOKIE_SECURE` | `true` | `Secure` flag of the refresh cookie. Set `false` only for plain-HTTP deployments (a localhost dev server works with `true`). |
| `ANTHROPIC_API_KEY` | unset | Enables generation. Blank counts as unset. Never commit it. |
| `LLM_GENERATION_MODEL` / `LLM_VALIDATION_MODEL` | `claude-sonnet-5-5` | Models for drafting and for blind validation |
| `DATABASE_URL` | local compose database | SQLAlchemy URL for PostgreSQL |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | unset | Used instead of `DATABASE_URL` when `DB_HOST` is set (AWS) |
| `STORAGE_BACKEND` | `local` | `local` (folder `LOCAL_STORAGE_DIR`, default `.data/documents`) or `s3` (needs `S3_BUCKET`) |
| `UPLOAD_MAX_BYTES` / `PDF_MAX_PAGES` | 25 MB / 400 | Upload limits |
| `GENERATION_MAX_QUESTIONS` / `GENERATION_ATTEMPTS_PER_SLOT` | 50 / 3 | Per request and per question |
| `JOB_STALE_MINUTES` | `30` | A job or document still running after this long is reported as failed |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |
| `EXAM_MINUTES_PER_QUESTION` | `2` | Exam-mode time limit per question |
| `INGESTION_ALLOWED_HOSTS` | AWS docs hosts | Hosts that sources may come from (JSON list) |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Must output 384 dimensions |
| `CHUNK_MAX_CHARS` / `CHUNK_OVERLAP_CHARS` | `1200` / `150` | Chunking |

## Deploying to AWS

See [`docs/DEPLOY.md`](../../docs/DEPLOY.md): build the image, `terraform apply` in `infra/terraform/`, store the Anthropic key in Secrets Manager, run the migration task, start the service.
