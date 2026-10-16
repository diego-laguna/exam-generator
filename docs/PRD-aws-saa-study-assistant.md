# PRD — AWS SAA Study Assistant (POC)

**Status:** Draft v0.2. M1–M4 implemented (see section 13). Where the implementation differs from the original text, the section says so.
**Type:** Proof of concept
**Owner:** Diego Laguna

---

## 1. Summary

A REST API built with Python and FastAPI. It generates AWS Solutions Architect Associate (SAA-C03) practice questions using Retrieval-Augmented Generation (RAG) over AWS documentation, then validates each question before serving it. Users take timed exams or untimed practice sessions.

The POC demonstrates four things:

1. **RAG with grounding and validation.** Questions are generated from retrieved documentation chunks, cite their sources, and must pass an automated validation step.
2. **JWT authentication.** Short-lived access tokens are paired with refresh tokens.
3. **Layered authorization.** Role-based access, resource ownership, and time-based rules are each enforced as composable FastAPI dependencies.
4. **Time-based access.** Exam sessions enforce their time window server-side, and results unlock by mode and time.

## 2. Goals and non-goals

### Goals
- G1: Generate exam-style SAA-C03 questions that are grounded in ingested AWS documentation.
- G2: Reject ambiguous or incorrect generated questions through an automated validation pass.
- G3: Provide an exam mode that mirrors the real exam (65 questions, 130 minutes) and a practice mode.
- G4: Enforce authentication, RBAC, ownership, and time windows on the server.
- G5: Track accuracy per domain and task statement, and use it to bias future generation toward weak areas.

### Non-goals (POC)
- Frontend or UI. The API is the product, and it is exercised via OpenAPI docs or an HTTP client.
- Multi-tenancy, SSO, OAuth providers, or self-service registration.
- Production-grade scaling, high availability, or cost optimization.
- Use of third-party "exam dump" content. Only official AWS sample questions and self-authored samples are used.

## 3. Roles

| Role | Description |
|---|---|
| `admin` | Manages users, documentation sources, and sample questions. |
| `student` | Creates and takes exams, and views their own results and stats. |

Admins create users. There is no public registration.

## 4. Content model

The system uses three distinct inputs, each with a separate purpose.

| Input | Purpose | Usage |
|---|---|---|
| **AWS documentation** (service FAQs, user guides, Well-Architected pillars) | Knowledge source | Chunked and embedded. Top-k chunks are retrieved per generation target. |
| **Sample questions** (official AWS exam-guide samples plus self-authored ones; around 20–30 total) | Style exemplars | Embedded. 2–3 from the same domain are used as few-shot examples. Never used as a fact source. |
| **SAA-C03 exam guide taxonomy** (domains and task statements) | Generation targets and coverage tracking | Seeded as reference data. |

### Exam domains (SAA-C03 weights)
| Domain | Weight |
|---|---|
| Design Secure Architectures | 30% |
| Design Resilient Architectures | 26% |
| Design High-Performing Architectures | 24% |
| Design Cost-Optimized Architectures | 20% |

Each domain contains task statements from the official exam guide, seeded via migration or fixture.

## 5. Question generation pipeline

Generation runs asynchronously as a background job.

1. **Select target.** Choose a domain and task statement. The weighting comes from the exam domain percentages, adjusted by the user's weak areas (see FR-STATS).
2. **Retrieve facts.** Take the top-k documentation chunks by similarity to the task statement, optionally restricted to the `source_ids` requested.
3. **Retrieve style.** Take 2–3 sample questions from the same domain, found by vector similarity.
4. **Generate.** The LLM produces a stem, 4 options, the correct option, and an explanation that cites chunk IDs. The output is structured JSON validated with Pydantic.
5. **Validate.** A second LLM call receives only the cited chunks and the question, without the answer, and answers blind. The question is discarded if:
   - the blind answer differs from the generated correct answer, or
   - the validator flags more than one defensible option, or
   - the cited chunk IDs do not exist or were not part of the retrieved set.
6. **Store.** Save the question with its domain, task statement, source chunk IDs, validation result, and model metadata.

If validation discards a question, the pipeline retries up to N times per slot (configurable, default 3). Then it marks the exam `ready` with fewer questions, or `failed` if it falls below a minimum threshold.

**Known risk:** Validation is the step that needs the most iteration. Distractors must be plausible but clearly wrong according to the docs.

## 6. Modes and time-based rules

| Rule | Exam mode | Practice mode |
|---|---|---|
| Question count | 65 (configurable) | User-defined |
| Time limit | 2 minutes per question from `start` (130 minutes for 65 questions) | None |
| Answers after `ends_at` | Rejected (server clock) | N/A |
| Explanations and correct answers | Locked until submitted or expired | Available after each answer |

Additional rules:
- **Implemented:** the exam duration is `question_count × 2` minutes (configurable), so an exam with fewer questions gets a proportionally shorter window.
- `ends_at = started_at + duration`. Both are set server-side at `POST /exams/{id}/start`, and the client clock is never trusted.
- An exam whose `ends_at` has passed is treated as expired and auto-finalized on next access.
- **Optional:** a daily quota of exam generations per user, enforced on `POST /exams`. It also caps LLM spend.

## 7. API

All endpoints are under `/api/v1`. Exam generation returns `202 Accepted`, and the client polls for status.

| Method & path | Purpose | Auth |
|---|---|---|
| `POST /auth/login` | Username + password → access token + refresh token | Public |
| `POST /auth/refresh` | Issue a new access token and a rotated refresh token (the old one is single-use) | Refresh token |
| `POST /auth/logout` | Revoke the given refresh token (optional body) and the current access token | JWT |
| `POST /users` | Create a user and assign a role | JWT + admin |
| `POST /sources` | Ingest a documentation page (async chunk + embed) | JWT + admin |
| `GET /sources` | List sources and ingestion status | JWT (any role) |
| `DELETE /sources/{id}` | Remove a source and its chunks | JWT + admin |
| `POST /samples` | Add up to 50 sample (few-shot) questions, each with a `task_statement` code or `domain_id`; all-or-nothing | JWT + admin |
| `POST /exams` | Create an exam. Body: `mode`, `domains` (ids 1–4), `question_count` → 202 + id. `source_ids` arrives with generation (M5) | JWT + student (+ quota) |
| `GET /exams/{id}` | Status (`generating` / `ready` / `in_progress` / `finished` / `failed`) and questions (only once started), never correct answers | JWT + owner |
| `POST /exams/{id}/start` | Start the timer and set `started_at` / `ends_at` | JWT + owner |
| `PUT /exams/{id}/answers/{question_id}` | Save or overwrite an answer | JWT + owner + active window |
| `POST /exams/{id}/submit` | Finalize the exam | JWT + owner + active window |
| `GET /exams/{id}/results` | Score, correct answers, explanations with citations | JWT + owner + unlocked |
| `GET /me/stats` | Accuracy per domain and task statement | JWT |

### Source ingestion constraints
- URLs are restricted to an allowlist (default: `docs.aws.amazon.com`, `aws.amazon.com`) to prevent SSRF.
- Ingestion is admin-only. Students reference ingested sources by ID or by domain.
- **Implemented:** only exact `https` host matches are accepted (no credentials or custom ports), redirects are re-validated on every hop, and fetches are capped in size, time and redirect count. Source errors are visible to admins only.

## 8. Authentication and authorization

### Authentication
- Passwords are hashed with bcrypt or argon2.
- Access tokens are JWTs that expire after about 15 minutes. Claims: `sub`, `role`, `exp`, `iat`, `jti`.
- Refresh tokens are long-lived, stored as a hash in the database, revocable, and rotated on use.
- **Decision:** refresh tokens are deleted (not flagged) on use, on logout, and on password change. Logout also denylists the current access token's `jti` until it expires, so logout takes effect immediately.

### Authorization layers (composable FastAPI dependencies)
1. `get_current_user`: validates the JWT and loads the user.
2. `require_role(role)`: RBAC check.
3. `get_owned_exam(exam_id)`: checks that `exam.user_id == current_user.id`. Returns 404 rather than 403, to avoid leaking whether an exam exists.
4. `require_active_window(exam)`: checks `started_at <= now < ends_at` against the server clock.
5. `require_results_unlocked(exam)`: allows practice mode always, and exam mode only when finished or expired.

Route handlers should contain little beyond calls to services. All authorization lives in dependencies.

## 9. Data model

As implemented (columns added or changed from the original draft are marked):

- `users`: id, username (unique), password_hash, role, is_active *(added)*, created_at
- `refresh_tokens`: id, user_id, token_hash, expires_at, created_at. Rows are deleted rather than flagged, so there is no `revoked_at` *(changed)*
- `revoked_tokens` *(added)*: jti, expires_at. Access tokens revoked by logout, purged after expiry
- `domains`: id, name, weight
- `task_statements`: id, domain_id, code, description
- `sources`: id, url (unique), title, status (`pending` / `ingesting` / `ready` / `failed`), error *(added)*, created_at
- `chunks`: id, source_id, position *(added)*, content, embedding `vector(384)`, metadata (jsonb)
- `sample_questions`: id, domain_id, task_statement_id (nullable), stem, options (jsonb), correct_option, embedding `vector(384)`, created_at
- `questions`: id, domain_id, task_statement_id, stem, options (jsonb), correct_option, explanation, cited_chunk_ids (int[]), validation (jsonb), model, created_at. Fixture questions have `model = 'fixture'` until generation exists
- `exams`: id, user_id, mode, status, question_count, requested_question_count *(added)*, duration_minutes *(added)*, started_at, ends_at, submitted_at, score (number of correct answers), created_at
- `exam_questions`: exam_id, question_id, position
- `answers`: exam_id, question_id, selected_option, answered_at, is_correct
- `generation_quota` (optional, not implemented): user_id, date, count

The embedding dimension (384) is fixed by the embedding model; changing the model needs a migration.

## 10. Tech stack

| Concern | Decision |
|---|---|
| Language / framework | Python, FastAPI |
| Database | **PostgreSQL + pgvector** (single database for relational data and vectors). Local image: `pgvector/pgvector:pg17` |
| ORM / migrations | SQLAlchemy + Alembic. The first migration runs `CREATE EXTENSION vector;` |
| Vector index | HNSW (cosine) on `chunks` and `sample_questions` |
| JWT | PyJWT |
| LLM (generation + validation) | Anthropic API |
| Embeddings | Local `fastembed` (ONNX) running `BAAI/bge-small-en-v1.5`, 384 dimensions (no API key, no PyTorch) |
| Background jobs | FastAPI `BackgroundTasks` for the POC (see open questions) |
| Local environment | Docker Compose runs Postgres; the API runs on the host with `uv` (containerizing it is not done) |

**Rationale for a single Postgres database:** Retrieval can filter by source or domain and rank by similarity in one SQL query, with transactions across all data and no second store to keep in sync. It also deploys directly to RDS or Aurora PostgreSQL, which support pgvector. A dedicated vector database adds no value at POC scale.

## 11. Functional requirements and acceptance criteria

- **FR-AUTH-1:** Login with valid credentials returns an access token and a refresh token. Invalid credentials return 401.
- **FR-AUTH-2:** An expired or invalid access token returns 401 on every protected endpoint.
- **FR-AUTH-3:** A refresh token rotates on use. A reused or revoked refresh token returns 401.
- **FR-RBAC-1:** A student calling admin endpoints receives 403.
- **FR-OWN-1:** A student accessing another user's exam receives 404.
- **FR-TIME-1:** Answering or submitting after `ends_at` returns 409 or 403 with an explicit error code (`EXAM_WINDOW_CLOSED`).
- **FR-TIME-2:** Exam-mode results before finish or expiry return 403 (`RESULTS_LOCKED`). Practice-mode results are always available.
- **FR-TIME-3:** Expired exams are finalized and scored on next access.
- **FR-GEN-1:** `POST /exams` returns 202, and the exam reaches `ready` or `failed`.
- **FR-GEN-2:** Every served question cites at least one chunk ID that exists in `chunks`.
- **FR-GEN-3:** No served question has a failed validation record.
- **FR-GEN-4:** `GET /exams/{id}` never includes `correct_option` or `explanation` before results are unlocked.
- **FR-INGEST-1:** Non-allowlisted URLs are rejected with 422.
- **FR-STATS-1:** `/me/stats` returns accuracy per domain and task statement, and generation weighting uses it.

## 12. Non-functional requirements

- All time comparisons use the server clock in UTC.
- Configuration comes from environment variables (pydantic-settings), and no secrets are kept in the repo.
- OpenAPI docs are generated automatically and serve as the API contract.
- Code is type-annotated and statically checked with pyright (standard mode, zero errors). Runtime validation uses Pydantic.
- Tests use pytest. Authorization dependencies and time rules get unit tests that use an injectable clock. The full exam flow gets an integration test with a stubbed LLM.

## 13. Milestones

1. **M1 — Foundation:** *[Done]* Docker Compose, Postgres + pgvector, Alembic, settings, health check.
2. **M2 — Auth:** *[Done]* users, login, refresh, logout, the authorization dependencies, and an admin seed.
3. **M3 — Ingestion:** *[Done]* sources, chunking, embeddings, allowlist, and seeding of domains and task statements.
4. **M4 — Exams without AI:** *[Done]* the exam lifecycle, time rules, answers, results, and stats, using fixture questions.
5. **M5 — Generation:** *[Not started]* retrieval, few-shot selection, generation, validation, and the async job.
6. **M6 — Adaptive weighting:** *[Not started]* stats feed into target selection.
7. **M7 (stretch) — Generation quality eval:** *[Not started]* a script that measures validation pass rate and blind-answer agreement over a fixed set of task statements.

## 14. Future (out of POC scope)

- An MCP server exposing tools such as `generate_practice_question` and `get_my_weak_areas`, which call the REST API with the user's token so agents inherit the same authorization and time rules.
- Deployment to AWS (RDS PostgreSQL with pgvector, ECS or Lambda).

## 15. Open questions

- ~~Background jobs~~ Decided: `BackgroundTasks` for ingestion. Revisit for generation (M5) if jobs must survive restarts.
- ~~Which embedding model, and therefore which vector dimension?~~ Decided: `BAAI/bge-small-en-v1.5`, 384 dimensions, via fastembed.
- ~~What chunking strategy should be used?~~ Decided: split at headings, about 1200 characters with 150 overlap, heading prefixed to each chunk.
- What is the minimum valid question count before an exam is marked `failed`? Currently only an empty result fails; a shorter exam is served.
- Is the daily generation quota in or out for the POC?
- Should admins be allowed to create and take exams too? Currently exam endpoints are student-only.
