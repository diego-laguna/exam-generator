# PRD — Exam Generator for Teachers (POC)

**Status:** Draft v0.3. Teacher flow (G1–G5) implemented; AWS deployment files provided. Replaces the AWS-SAA framing of [`PRD-aws-saa-study-assistant.md`](PRD-aws-saa-study-assistant.md), which remains the spec for the legacy student module (section 9).
**Type:** Proof of concept
**Owner:** Diego Laguna

---

## 1. Summary

A REST API for teachers. A teacher uploads PDFs (lesson notes, textbook chapters). The system generates multiple-choice and true/false questions from them, each with the correct answer, an explanation, and citations (source file, **page, line**). Every question is checked automatically before the teacher sees it. The teacher picks questions into a **question set**, saves the set for reuse, and downloads a printable PDF for students (and an answer key for themselves).

## 2. Goals and non-goals

### Goals
- G1: Generate questions grounded in the teacher's PDFs, each citing file, page, line range and a verbatim quote.
- G2: Reject bad questions automatically: citations that do not match the cited lines, and questions a blind validator cannot answer identically or finds ambiguous.
- G3: Let teachers select questions into named sets that are saved and reused.
- G4: Export a set as a printable student PDF (no answers) and a teacher PDF (answers, explanations, sources).
- G5: Teachers only ever see their own documents, questions and sets.
- G6: Be deployable on AWS (container, RDS PostgreSQL + pgvector, S3, Secrets Manager, ECS Fargate).

### Non-goals (POC)
- Frontend. The API is the product.
- OCR for scanned PDFs (rejected with a clear error), non-PDF formats, images and tables as sources.
- Editing a question's text (delete and regenerate instead).
- Letting students take a teacher's set online (the legacy student module uses its own fixture bank).
- Sharing documents or sets between teachers.
- Non-Latin scripts in exported PDFs (the built-in PDF fonts cover Western European languages).

## 3. Roles

| Role | Description |
|---|---|
| `teacher` | Uploads documents, generates questions, builds sets, downloads PDFs. Owns everything they create. |
| `admin` | Creates users (including teachers) and manages the documentation sources of the student module. Cannot see teachers' data. |
| `student` | Legacy module only: takes exams from the fixture bank. |

Admins create users; there is no public registration.

## 4. Citations: page and line

PDF text is extracted line by line in reading order. For each page, non-empty lines are numbered 1, 2, 3… A citation is `{document, page, line_start, line_end, quote}` and always stays on one page.

- The numbers refer to extracted text lines, not to line numbers printed in the margin. They match what a reader sees on a normal text PDF, but a multi-column layout or a header counts as lines too.
- **Verified, not trusted.** The model must copy a quote from the cited lines. The server checks that the quote occurs in exactly those lines (ignoring case, whitespace and hyphenation). A question with a citation that fails the check is discarded.
- Citations are stored as snapshots (file name, page, lines, quote), so they stay readable if the document is deleted.

## 5. Pipeline

```
PDF upload → S3 → extract numbered lines → chunk (40 lines, 5 overlap) → embed → pgvector
                                                      │
 POST /generations (documents, counts, optional focus)│
   per slot: pick chunk (spread over the document, or nearest to the focus)
     → LLM draft (stem, options, answer, explanation, citations)   [forced structured output]
     → deterministic checks (options shape, duplicates, citations match the lines)
     → blind validation (second call sees the excerpt and question, not the answer)
     → store, or retry with the next chunk (default 3 attempts per slot)
```

- Question types: `mcq` (A–D, one correct) and `true_false` (A=True, B=False).
- Questions are written in the language of the source text.
- Document text is treated as untrusted data in the prompt (prompt-injection mitigation); output is validated with Pydantic and never executed.
- At most one running generation per teacher, and at most 50 questions per request, to bound LLM spend.
- Jobs run as FastAPI `BackgroundTasks` and are recorded in `generation_jobs`. A job or document stuck in `running`/`processing` longer than `JOB_STALE_MINUTES` is reported as failed. A durable queue (SQS + worker) is the next step if jobs must survive restarts (section 11).

## 6. API

All under `/api/v1`, teacher-only unless stated. Anything owned by another teacher is a 404.

| Method & path | Purpose |
|---|---|
| `POST /documents` | Upload a PDF (multipart, max 25 MB). 202; poll until `ready`. Duplicate file → 409; not a PDF → 422 |
| `GET /documents`, `GET /documents/{id}` | Status (`pending`/`processing`/`ready`/`failed`), page count, chunk count, error |
| `DELETE /documents/{id}` | Remove the document, its chunks and the stored file. Questions stay |
| `POST /generations` | `document_ids`, `mcq_count`, `true_false_count`, optional `focus` → 202. 503 `LLM_NOT_CONFIGURED` without an API key; 409 `JOB_IN_PROGRESS` |
| `GET /generations`, `GET /generations/{id}` | Status, requested vs produced count, `question_ids` |
| `GET /questions`, `GET /questions/{id}` | The teacher's bank, filter by `document_id`, `type` |
| `DELETE /questions/{id}` | Delete a question (also leaves any set) |
| `POST /question-sets` | `title` + ordered `question_ids` → saved set |
| `GET /question-sets`, `GET /question-sets/{id}` | List and read sets |
| `PUT /question-sets/{id}` | Replace title and questions |
| `DELETE /question-sets/{id}` | Delete the set (questions stay) |
| `GET /question-sets/{id}/pdf?version=student\|teacher` | Printable PDF. `student`: questions and name/date lines. `teacher`: answers, explanations, page/line sources |

Shared endpoints (any role unless noted): `POST /auth/login` and `POST /auth/refresh` (public), `POST /auth/logout`, `POST /users` (admin; sets the role), and the unversioned public `GET /health`. Behavior is in section 8.

## 7. Data model (new tables)

- `documents`: id, owner_id, filename, sha256 (unique per owner), size_bytes, storage_key, page_count, status, error, timestamps
- `document_chunks`: id, document_id, position, `lines` (jsonb `[[page, line, text], …]`), content, embedding `vector(384)` (HNSW cosine)
- `generation_jobs`: id, owner_id, document_ids, mcq_count, true_false_count, focus, status (`queued`/`running`/`done`/`failed`), produced_count, error, timestamps
- `bank_questions`: id, owner_id, document_id (nullable, set null on delete), job_id, type, stem, options, correct_option, explanation, citations (jsonb), validation (jsonb), model, created_at
- `question_sets`: id, owner_id, title, timestamps
- `question_set_items`: set_id, question_id, position

## 8. Authentication, authorization and security

### Authentication
- Passwords are hashed with argon2.
- Access tokens are JWTs that expire after 15 minutes. Claims: `sub`, `role`, `exp`, `iat`, `jti`.
- Refresh tokens are opaque, stored as a hash, valid 7 days, single-use and rotated on every refresh. They are returned in the JSON body (API clients) and also set as an `httpOnly`, `Secure`, `SameSite=Strict` cookie scoped to `/api/v1/auth` (browsers), so page scripts never hold them. `/auth/refresh` and `/auth/logout` accept the token from the body or, if absent, the cookie; the body wins.
- **Decision:** refresh tokens are deleted (not flagged) on use, on logout and on password change (`revoke_all_refresh_tokens`; there is no password-change endpoint yet). Logout also denylists the access token's `jti` until it expires, so logout takes effect immediately.
- Admins create users; there is no public registration. Login takes the same time for unknown and known users (dummy hash verification).

### Authorization: composable FastAPI dependencies
1. `get_current_user`: validates the JWT, checks the denylist, loads the active user.
2. `require_role(role)`: RBAC (`TeacherOnly`, `AdminOnly`, `StudentOnly`).
3. Ownership dependencies (`get_owned_document`, `get_owned_job`, `get_owned_question`, `get_owned_set`): load the resource for the caller only. Foreign and missing ids both return 404, so existence is not leaked.
4. Time and state rules for the student module (section 9).

All authorization lives in dependencies; route handlers contain little beyond calls to services. A test fails if any route is added without authentication or without an entry in the role matrix.

### Uploads, storage and secrets
- Uploads: size cap enforced while streaming, `%PDF-` magic-byte check, page cap, parse errors turned into safe messages, storage keys generated server-side (never from the file name), file names sanitized for display.
- PDFs are stored in a private, encrypted S3 bucket with public access blocked; the task role can only touch `documents/*`.
- Secrets (`JWT_SECRET_KEY`, DB credentials, `ANTHROPIC_API_KEY`) come from the environment; on AWS they are injected from Secrets Manager. The API key is a `SecretStr` and is never logged.
- Exported PDF text is XML-escaped before layout, so question text cannot inject markup.

## 9. Legacy student module (kept)

The SAA-C03 student exam flow (timed exams, practice mode, stats, URL ingestion of AWS docs for admins) is unchanged and still tested. Its spec is [`PRD-aws-saa-study-assistant.md`](PRD-aws-saa-study-assistant.md). It is isolated from the teacher tables. Connecting the two (students taking a teacher's set) is a possible later step.

## 10. Tech stack

Python 3.14, FastAPI, PostgreSQL 17 + pgvector, SQLAlchemy 2 + Alembic, PyJWT, fastembed (`BAAI/bge-small-en-v1.5`), pdfminer.six (PDF text), ReportLab (PDF export), Anthropic API (generation + validation), boto3 (S3). Local: Docker Compose runs Postgres. AWS: see [`DEPLOY.md`](DEPLOY.md).

**Why one PostgreSQL database:** retrieval can filter by document and rank by similarity in one SQL query, with transactions across all data and no second store to keep in sync. It also maps directly to RDS or Aurora PostgreSQL, which support pgvector. A dedicated vector database adds nothing at POC scale. The embedding dimension (384) is fixed by the embedding model; changing the model needs a migration and re-embedding.

## 11. Acceptance criteria

- **FR-AUTH-1:** Login with valid credentials returns an access and a refresh token; invalid credentials return 401.
- **FR-AUTH-2:** An expired, invalid or logged-out access token returns 401 on every protected endpoint.
- **FR-AUTH-3:** A refresh token rotates on use; a reused or revoked one returns 401.
- **FR-RBAC-1:** A caller with the wrong role gets 403 on every endpoint (verified by the role matrix test).
- **FR-OWN-1:** A teacher accessing another teacher's document, generation, question or set gets 404.
- **FR-DOC-1:** A non-PDF or oversized upload is rejected (422/413); an unreadable or text-less PDF ends as `failed` with a safe message.
- **FR-GEN-1:** `POST /generations` returns 202 and the job reaches `done` or `failed`; without an API key it returns 503 `LLM_NOT_CONFIGURED`.
- **FR-GEN-2:** Every stored question has at least one citation whose quote occurs in the cited page and lines.
- **FR-GEN-3:** No stored question failed blind validation or was flagged ambiguous.
- **FR-SET-1:** A saved set keeps its question order and can be changed, reused and deleted without deleting its questions.
- **FR-PDF-1:** The student PDF contains no answers or sources; the teacher PDF contains the answer, explanation and page/line source of every question.

## 12. Non-functional requirements

- All time comparisons use the server clock in UTC (injectable in tests).
- Configuration comes from environment variables (pydantic-settings); no secrets are kept in the repo.
- OpenAPI docs are generated automatically and serve as the API contract.
- Code is type-annotated and passes pyright (standard mode, zero errors); runtime validation uses Pydantic, including all LLM output.
- Tests use pytest against a real PostgreSQL. They never call the real LLM, S3 or the network (fakes for the model, storage, embedder and PDF input).

## 13. Open questions and next steps

- Durable jobs: replace `BackgroundTasks` with SQS + a worker task so a deploy or crash does not lose a running generation.
- Edit a question before saving it into a set.
- Assign a saved set to students for online use.
- Option shuffling and multiple exam versions (A/B) in the PDF export.
- Bedrock as an alternative LLM backend (IAM role instead of an API key): the `Llm` protocol in `app/llm.py` is the seam.
- Generation quality evaluation (pass rate of validation, human spot-check sample).
