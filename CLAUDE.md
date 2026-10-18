# learn-assistant

Monorepo: `apps/api` (Python/FastAPI, everything below unless stated), `infra/terraform` (AWS), `docs/` (PRDs, DEPLOY.md), `compose.yaml` (Postgres). A React app (`apps/web`) and a generated API client (`packages/api-client`) are planned; JS tooling will be pnpm workspaces, not Nx. Run Python commands from `apps/api` (the `.env` file is read from the working directory); from the repo root, `just` recipes wrap them (`just check`, `just api-dev`, `just db-up`, ...). Docker: build context is `apps/api`.

FastAPI REST API: teachers upload PDFs, the app generates validated multiple-choice/true-false questions that cite file, page and line, teachers save question sets and download printable PDFs. A legacy student module (timed AWS SAA-C03 exams from a fixture bank) is kept.
Requirements (not auto-loaded; read the relevant section first): `docs/PRD-exam-generator.md` (current), `docs/PRD-aws-saa-study-assistant.md` (student module spec). AWS deployment: `docs/DEPLOY.md`, Terraform in `infra/terraform/`.

## Stack
- Python 3.14, FastAPI, managed with `uv`
- PostgreSQL + pgvector (single DB for relational data and vectors), image `pgvector/pgvector:pg17`
- SQLAlchemy 2 + Alembic (psycopg 3); migrations in `migrations/`
- Auth: PyJWT + pwdlib (argon2), settings via pydantic-settings
- Embeddings: local `fastembed` (ONNX) with `BAAI/bge-small-en-v1.5`, 384 dims (`app/embeddings.py`)
- Ingestion: httpx2 fetch + BeautifulSoup + heading-aware chunking (`app/fetching.py`, `app/chunking.py`, `app/ingestion.py`)
- Teacher PDFs: pdfminer.six (numbered lines, `app/pdf_text.py`), storage in S3 or a local dir (`app/storage.py`), ReportLab export (`app/pdf_export.py`)
- LLM: Anthropic API behind the `Llm` protocol (`app/llm.py`, forced tool call -> Pydantic); generation pipeline in `app/question_gen.py`
- Deploy: `apps/api/Dockerfile`, Terraform (ECS Fargate, RDS pg17, S3, Secrets Manager, ALB), CI in `.github/workflows/ci.yml`

## Commands
- DB: `just db-up` (or `docker compose up -d --wait` from the repo root)
- Migrate: `uv run alembic upgrade head` (new: `uv run alembic revision --autogenerate -m "..."`)
- Seed exam reference data + fixture questions: `uv run python -m scripts.seed_reference` (required after migrating)
- Seed sample users: `uv run python -m scripts.seed` (alice=admin, bob/carol=students, dave=teacher)
- Bootstrap an admin: `uv run python -m scripts.create_admin <username>` (prompts, or set `ADMIN_PASSWORD`)
- Run: `uv run fastapi dev app/main.py`
- Type check: `uv run pyright` (standard mode; must stay at 0 errors)
- Test: `uv run pytest` (needs the DB up; uses its own `learn_assistant_test` database)
- Config: copy `.env.example` to `.env`. Set `ANTHROPIC_API_KEY` yourself in `.env` (never paste it into chat); without it `POST /generations` returns 503.
- Docker image: `just api-image`; Terraform check (repo root): `docker run --rm -v "$PWD/infra/terraform:/tf" -w /tf hashicorp/terraform:1.9 validate`

## Rules that always apply
- Code is fully type-annotated and must pass pyright; runtime validation is Pydantic (requests, settings, LLM JSON).
- Server clock (UTC) is the only source of time; never trust client time.
- All authorization lives in FastAPI dependencies, not in route handlers.
- Non-owned resources return 404, not 403.
- Never return `correct_option` or `explanation` before results are unlocked.
- Generated questions must have citations whose quote is verified in the cited page/lines and must pass blind validation.
- Teacher resources (documents, jobs, questions, sets) are owner-scoped: foreign ids return 404.
- Tests never call the real LLM, S3 or the network: they override `get_llm`/`get_storage`/`get_embedder` (`tests/helpers_teacher.py`); an autouse fixture disables the real LLM.
- Ingestion URLs must match the allowlist (SSRF).
- No secrets in the repo.

## Status
Teacher exam generator implemented (documents, generations, bank questions, question sets, PDF export) plus AWS deployment files. Legacy student module (M1-M4 of the SAA PRD) kept and tested.
Not done: durable job queue (SQS), question editing, assigning sets to students, live quality eval with a real key.
Teacher decisions: roles `teacher`/`admin`/`student`; question types `mcq` and `true_false` (options A=True, B=False); citations `{document, chunk_id, page, line_start, line_end, quote}` as snapshots (survive document deletion); a "line" is a non-empty extracted text line numbered per page; chunks are 40 lines with 5 overlap; one running generation per teacher; jobs/documents stuck longer than `JOB_STALE_MINUTES` are reported failed; DB URL is built from `DB_*` parts when `DB_HOST` is set (AWS); a blank `ANTHROPIC_API_KEY` counts as unset.
Decisions beyond the PRD text (student module):
- Routes live under `/api/v1`; `/health` stays unversioned.
- Access token 15 min; refresh tokens are opaque, hashed, single-use (rotated), 7 days, deleted (not flagged) on use/logout.
- Browsers get the refresh token as an httpOnly `Secure` `SameSite=Strict` cookie (path `/api/v1/auth`, `REFRESH_COOKIE_SECURE=false` only for plain-HTTP deployments); `/auth/refresh` and `/auth/logout` read the body first, then the cookie.
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
- Embeddings use `fastembed` instead of sentence-transformers (same open models, no PyTorch/CUDA install). Changing the model or its dimension needs a migration (`EMBEDDING_DIM`).
- Ingestion runs as FastAPI `BackgroundTasks` (no queue); a source goes `pending -> ingesting -> ready|failed`, and a restart mid-ingestion leaves it `ingesting`.
- URLs are validated against the allowlist (exact https host match, no userinfo/port) at the endpoint AND on every redirect hop; fetches have size/time/redirect caps.
- Chunks: ~1200 chars, 150 overlap, split at headings, heading prefixed to content. Only `error` text is hidden from students; the source list is visible to any user.
- Retrieval helper `similar_chunks` (cosine, optional `source_ids`) is ready for M5. HNSW indexes exist on `chunks` and `sample_questions`.
- Tests never download the model or hit the network: they override `get_embedder`/`get_fetcher` with `tests/helpers_ingestion.py`.
