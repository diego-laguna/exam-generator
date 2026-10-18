# Student exam module (AWS SAA-C03) — spec

> The product is an exam generator for teachers: see [`PRD-exam-generator.md`](PRD-exam-generator.md). That document also holds the shared authentication, authorization, security and non-functional requirements. This one only specifies the student-facing module that was built first and is kept: timed exams and practice sessions over a fixture question bank, plus admin ingestion of AWS documentation pages. The original plan to generate its questions with an LLM (RAG over AWS docs, adaptive weighting by weak areas) was dropped in favor of the teacher pipeline.

**Status:** implemented and tested.

## 1. Scope

Students take timed exams (65 questions, 130 minutes, like the real SAA-C03) or untimed practice sessions. Questions come from 20 hand-written fixture questions (`scripts/question_fixtures.py`, `model = 'fixture'`); there is no generation for this module. The bank lacks task statements 3.2, 3.5 and 4.3.

Roles: `student` (creates and takes exams, sees own results and stats) and `admin` (manages sources and sample questions). Exam endpoints are student-only; admins get 403.

## 2. Reference data

SAA-C03 domains (ids 1–4 follow the exam guide) and their task statements are seeded by `scripts.seed_reference`.

| Domain | Weight |
|---|---|
| 1 Design Secure Architectures | 30% |
| 2 Design Resilient Architectures | 26% |
| 3 Design High-Performing Architectures | 24% |
| 4 Design Cost-Optimized Architectures | 20% |

## 3. Modes and time rules

| Rule | Exam mode | Practice mode |
|---|---|---|
| Question count | 65 (configurable) | User-defined (default 10) |
| Time limit | 2 minutes per question from `start`, so fewer questions get a proportionally shorter window | None |
| Answers after `ends_at` | Rejected (server clock) | N/A |
| Explanations and correct answers | Locked until submitted or expired | Returned in the answer response |

- `ends_at = started_at + duration`, set server-side at `POST /exams/{id}/start`; the client clock is never trusted.
- An exam past `ends_at` is finalized and scored on next access.
- Requesting more questions than the bank holds serves what exists (`requested_question_count` vs `question_count`); an empty bank marks the exam `failed`.
- `GET /exams/{id}` returns questions only after start and never `correct_option` or `explanation`.

## 4. API

Under `/api/v1`. Auth endpoints and `POST /users` are specified in the teacher PRD.

| Method & path | Purpose | Auth |
|---|---|---|
| `POST /sources` | Ingest an AWS documentation page (async chunk + embed) | admin |
| `GET /sources` | List sources and status (`pending`/`ingesting`/`ready`/`failed`); `error` text is visible to admins only | any role |
| `DELETE /sources/{id}` | Remove a source and its chunks | admin |
| `POST /samples` | Add up to 50 sample questions (task statement code or domain id; all-or-nothing) | admin |
| `GET /exams` | The caller's 100 most recent exams, newest first (expired ones are finalized first) | student |
| `POST /exams` | Body: `mode`, `domains` (ids 1–4), `question_count` → 202 | student |
| `GET /exams/{id}` | Status (`generating`/`ready`/`in_progress`/`finished`/`failed`) and questions once started | student + owner |
| `POST /exams/{id}/start` | Start the timer | student + owner |
| `PUT /exams/{id}/answers/{question_id}` | Save or overwrite an answer; practice mode returns feedback | student + owner + active window |
| `POST /exams/{id}/submit` | Finalize | student + owner + active window |
| `GET /exams/{id}/results` | Score, correct answers, explanations | student + owner + unlocked |
| `GET /me/stats` | Accuracy per domain and task statement (practice answers and finished exams only) | any role |

Authorization layers specific to exams: `get_owned_exam` (404 on foreign exams), `require_active_window` (`started_at <= now < ends_at`), `require_results_unlocked` (practice always; exam mode only when finished or expired). Error bodies use `detail: {code, message}` with codes such as `EXAM_NOT_STARTED`, `EXAM_WINDOW_CLOSED`, `RESULTS_LOCKED`.

### Source ingestion constraints (SSRF)
- URLs must match an allowlist (default `docs.aws.amazon.com`, `aws.amazon.com`): exact `https` host, no credentials, no custom port.
- Redirects are followed manually and re-validated on every hop; fetches are capped in size, time and redirect count.
- Chunks: about 1200 characters, 150 overlap, split at headings, heading prefixed. Embeddings: fastembed `BAAI/bge-small-en-v1.5`, 384 dimensions. The `similar_chunks` helper (cosine search) exists but nothing calls it yet.

## 5. Data model

- `domains`: id, name, weight · `task_statements`: id, domain_id, code, description
- `sources`: id, url (unique), title, status, error, created_at · `chunks`: id, source_id, position, content, embedding `vector(384)`, metadata
- `sample_questions`: id, domain_id, task_statement_id, stem, options, correct_option, embedding (few-shot exemplars; unused until a generator needs them)
- `questions`: id, domain_id, task_statement_id, stem, options, correct_option, explanation, cited_chunk_ids, validation, model, created_at
- `exams`: id, user_id, mode, status, question_count, requested_question_count, duration_minutes, started_at, ends_at, submitted_at, score, created_at
- `exam_questions`: exam_id, question_id, position · `answers`: exam_id, question_id, selected_option, answered_at, is_correct

## 6. Acceptance criteria

- **FR-TIME-1:** Answering or submitting after `ends_at` returns 409 `EXAM_WINDOW_CLOSED`.
- **FR-TIME-2:** Exam-mode results before finish or expiry return 403 `RESULTS_LOCKED`; practice-mode results are always available.
- **FR-TIME-3:** Expired exams are finalized and scored on next access.
- **FR-EXAM-1:** `GET /exams/{id}` never includes `correct_option` or `explanation` before results are unlocked.
- **FR-OWN-2:** A student accessing another student's exam gets 404.
- **FR-INGEST-1:** Non-allowlisted URLs, including redirects to them, are rejected.
- **FR-STATS-1:** `/me/stats` returns accuracy per domain and task statement.

## 7. Open questions

- Should admins be able to create and take exams too? Currently exam endpoints are student-only.
- Is a daily quota on exam creation needed? (Not implemented; it only matters if generation is ever added here.)
- Should students be able to take a teacher's saved question set online? That would connect this module to the teacher flow.
