# Exam-Generator

Monorepo: `apps/api` (Python/FastAPI: HTTP, auth, queueing; commands below run from there unless stated), `apps/worker` (queue consumer: PDF text, embeddings, generation), `packages/core` (`exam_core`, Python code shared by both: settings, DB models, storage, queue messages), `infra/terraform` (AWS), `docs/` (PRDs, DEPLOY.md), `compose.yaml` (Postgres + local SQS). The Python side is one uv workspace (one `uv.lock`, one `.venv` at the root; `uv sync --all-packages`). `apps/web` is the React + TypeScript app for all roles (teacher, student, admin screens) (Vite, React Router, TanStack Query, Vitest) and `packages/api-client` the OpenAPI schema + generated client; JS tooling is pnpm workspaces, not Nx. Run Python commands from `apps/api` (the `.env` file is read from the working directory); from the repo root, `just` recipes wrap them (`just check`, `just api-dev`, `just db-up`, ...). Docker: build context is the repo root (`docker build -f apps/api/Dockerfile .`). After changing an endpoint or Pydantic model run `just gen-client` and commit `packages/api-client` (CI fails on drift); name response models uniquely (the client types use the class names). Web rules: the access token lives only in memory, the refresh token is the httpOnly cookie (never read it from JS), the UI only hides screens by role (`src/roles.ts`; the API enforces), tests stub `fetch` (`apps/web/src/test-utils.ts`) and never hit the network.

FastAPI REST API: teachers upload PDFs, the app generates validated multiple-choice/true-false questions that cite file, page and line, teachers save question sets and download printable PDFs. A legacy student module (timed AWS SAA-C03 exams from a fixture bank) is kept.
Requirements (not auto-loaded; read the relevant section first): `docs/PRD-exam-generator.md` (current), `docs/PRD-aws-saa-study-assistant.md` (student module spec). AWS deployment: `docs/DEPLOY.md`, Terraform in `infra/terraform/`.

## Stack
- Python 3.14, FastAPI, managed with `uv`
- PostgreSQL + pgvector (single DB for relational data and vectors), image `pgvector/pgvector:pg17`
- SQLAlchemy 2 + Alembic (psycopg 3); migrations in `migrations/`
- Auth: PyJWT + pwdlib (argon2), settings via pydantic-settings
- Embeddings: local `fastembed` (ONNX) with `BAAI/bge-small-en-v1.5`, 384 dims, in the worker (`worker/embedder.py`; the `Embedder` protocol and `EMBEDDING_DIM` are in `exam_core/embeddings.py`)
- Ingestion (worker): httpx2 fetch + BeautifulSoup + heading-aware chunking (`worker/fetching.py`, `worker/chunking.py`, `worker/source_ingestion.py`); the SSRF URL guard is `exam_core/urls.py`
- Teacher PDFs: pdfminer.six in the worker (numbered lines, `worker/pdf_text.py`), storage in S3 or a local dir (`exam_core/storage.py`), ReportLab export in the API (`app/pdf_export.py`)
- LLM: Anthropic API behind the `Llm` protocol (`worker/llm.py`, forced tool call -> Pydantic); generation pipeline in `worker/question_gen.py`. Only the worker has the Anthropic key
- Queue: SQS (ElasticMQ locally). The API sends messages (`exam_core/queue.py`, `app/queueing.py`); the worker consumes them (`worker/consumer.py`, `worker/handlers.py`)
- Deploy: `apps/api/Dockerfile` and `apps/worker/Dockerfile` (build context: repo root), Terraform (ECS Fargate for both, SQS + DLQ, RDS pg17, S3, Secrets Manager, ALB), CI in `.github/workflows/ci.yml`

## Commands
- DB and local queue: `just db-up` (or `docker compose up -d --wait` from the repo root)
- Migrate: `uv run alembic upgrade head` (new: `uv run alembic revision --autogenerate -m "..."`)
- Seed exam reference data + fixture questions: `uv run python -m scripts.seed_reference` (required after migrating)
- Seed sample users: `uv run python -m scripts.seed` (alice=admin, bob/carol=students, dave=teacher)
- Bootstrap an admin: `uv run python -m scripts.create_admin <username>` (prompts, or set `ADMIN_PASSWORD`)
- Run: `uv run fastapi dev app/main.py`
- Type check: `uv run pyright` (whole workspace; standard mode; must stay at 0 errors)
- Test: `uv run pytest` in `apps/api` (own `learn_assistant_test` database) and in `apps/worker` (`learn_assistant_worker_test`); both need the DB up
- Worker: `just worker-dev` (reads `apps/worker/.env`). Without it uploads stay `pending`
- Config: copy `.env.example` to `.env` in `apps/api` and in `apps/worker`. Set `ANTHROPIC_API_KEY` yourself in `apps/worker/.env` (never paste it into chat); without it generation jobs end `failed` with "Question generation is not configured".
- Docker images: `just api-image`, `just worker-image`; Terraform check (repo root): `docker run --rm -v "$PWD/infra/terraform:/tf" -w /tf hashicorp/terraform:1.9 validate`

## Rules that always apply
- Code is fully type-annotated and must pass pyright; runtime validation is Pydantic (requests, settings, LLM JSON).
- Server clock (UTC) is the only source of time; never trust client time.
- All authorization lives in FastAPI dependencies, not in route handlers.
- Non-owned resources return 404, not 403.
- Never return `correct_option` or `explanation` before results are unlocked.
- Generated questions must have citations whose quote is verified in the cited page/lines and must pass blind validation.
- Teacher resources (documents, jobs, questions, sets) are owner-scoped: foreign ids return 404.
- Tests never call the real LLM, S3, SQS or the network. API tests override `get_queue`/`get_storage` (`tests/conftest.py`, doubles in `exam_core/testing.py`) and assert on the queued messages; worker tests call the job functions with fakes (`apps/worker/tests`); an autouse fixture disables the real LLM.
- The API must not import worker-only libraries (fastembed, pdfminer, anthropic, bs4, httpx2); CI checks the API image for them. Shared code goes in `packages/core`.
- Worker jobs are idempotent against redelivery: claim the row by status first, record the outcome on the row, never raise.
- Ingestion URLs must match the allowlist (SSRF).
- No secrets in the repo.

## Status
Teacher exam generator implemented (documents, generations, bank questions, question sets, PDF export) with a queue-driven worker, plus AWS deployment files. Legacy student module (M1-M4 of the SAA PRD) kept and tested.
Not done: question editing, assigning sets to students, live quality eval with a real key, worker autoscaling on queue depth.
Teacher decisions: roles `teacher`/`admin`/`student`; question types `mcq` and `true_false` (options A=True, B=False); citations `{document, chunk_id, page, line_start, line_end, quote}` as snapshots (survive document deletion); a "line" is a non-empty extracted text line numbered per page; chunks are 40 lines with 5 overlap; one running generation per teacher; jobs/documents stuck longer than `JOB_STALE_MINUTES` are reported failed; SQS messages name the work only (`ingest_document`, `run_generation`, `ingest_source`, `embed_samples`), a message is deleted only after the job finished, 3 failed receives go to the DLQ; sample question embeddings are filled in by the worker (nullable column); DB URL is built from `DB_*` parts when `DB_HOST` is set (AWS); a blank `ANTHROPIC_API_KEY` counts as unset.
Decisions beyond the PRD text (student module):
- Routes live under `/api/v1`; `/health` stays unversioned.
- Access token 15 min; refresh tokens are opaque, hashed, single-use (rotated), 7 days, deleted (not flagged) on use/logout.
- Browsers get the refresh token as an httpOnly `Secure` `SameSite=Strict` cookie (path `/api/v1/auth`, `REFRESH_COOKIE_SECURE=false` only for plain-HTTP deployments); `/auth/refresh` and `/auth/logout` read the body first, then the cookie.
- Logout also denylists the access token JTI (`revoked_tokens`, purged after expiry).
- Password change must call `revoke_all_refresh_tokens` (no password-change endpoint yet).
- Exam mode time limit = 2 min per question (65 questions -> 130 min), set at `/start` on the server clock.
- Requesting more questions than the bank holds serves what exists (`requested_question_count` vs `question_count`); 0 available -> `failed`.
- `GET /exams/{id}` returns questions only after start and never `correct_option`/`explanation`; practice answers return feedback in the `PUT` response.
- `GET /exams` lists the student's own exams; `GET /api/v1/health` mirrors `/health` for the web app (the proxy only forwards `/api`).
- Exam endpoints are student-only; admins get 403 (PRD open question).
- Domain ids 1-4 follow the exam guide; `POST /exams` takes `domains: [ids]`.
- `/me/stats` counts practice answers and answers from finished exams only.
- Time is injectable via the `get_clock` dependency; tests override it.
- Error responses for exam rules use `detail: {code, message}` (e.g. `EXAM_WINDOW_CLOSED`, `RESULTS_LOCKED`).
- Embeddings use `fastembed` instead of sentence-transformers (same open models, no PyTorch/CUDA install). Changing the model or its dimension needs a migration (`EMBEDDING_DIM`).
- Source ingestion runs in the worker; a source goes `pending -> ingesting -> ready|failed`, and a source left `ingesting` by a dead worker is picked up again on redelivery.
- URLs are validated against the allowlist (exact https host match, no userinfo/port) at the endpoint AND on every redirect hop; fetches have size/time/redirect caps.
- Chunks: ~1200 chars, 150 overlap, split at headings, heading prefixed to content. Only `error` text is hidden from students; the source list is visible to any user.
- Retrieval helper `similar_chunks` (cosine, optional `source_ids`) is ready for M5. HNSW indexes exist on `chunks` and `sample_questions`.
- Tests never download the model or hit the network: worker tests pass `FakeEmbedder`/`FakeFetcher` (`exam_core/testing.py`, `apps/worker/tests/helpers.py`).
