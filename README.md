# Exam-Generator

An exam generator for teachers. Teachers upload PDFs; the API generates multiple-choice and true/false questions with answers, explanations and citations (file, page, line), verifies them automatically, and lets teachers save question sets and download printable PDFs. A smaller student module (timed AWS SAA-C03 practice exams) is kept.

This is a monorepo with a Python API and a React web app. The web app covers every endpoint, shown by role: teachers (documents, generation, question sets), students (practice sessions and timed exams, results, stats) and admins (users, samples, sources).

## Layout

```
apps/api/          Python / FastAPI service (see apps/api/README.md for details)
apps/web/          React + TypeScript app for teachers (Vite)
packages/api-client/ OpenAPI schema and generated TypeScript client used by the web app
infra/terraform/   AWS infrastructure (ECS Fargate, RDS pgvector, S3, Secrets Manager, ALB)
docs/              PRDs, deployment guide, system design diagram
compose.yaml       PostgreSQL + pgvector for local development
justfile           One entry point for common tasks (`just` lists them)
.github/workflows/ CI
```

## Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/), Docker with Compose, [just](https://github.com/casey/just), Node 24 and [pnpm](https://pnpm.io/).

```bash
just api-install                  # Python dependencies
cp apps/api/.env.example apps/api/.env   # then set JWT_SECRET_KEY (and ANTHROPIC_API_KEY to generate questions)
just db-up                        # PostgreSQL + pgvector
just migrate                      # schema + reference data
just seed                         # sample users (development only)
just api-dev                      # http://127.0.0.1:8000/docs

# in a second terminal
just js-install                   # JS dependencies
just web-dev                      # http://localhost:5173  (sign in as dave / teacher-pass, bob / builder, or alice / wonderland)
```

The web app talks to the API through the Vite dev proxy, so there is no CORS to configure. After changing an API endpoint or schema, run `just gen-client` and commit the regenerated `packages/api-client` files; CI fails if they are stale.

Checks: `just check` (pyright, API tests, JS typecheck, web tests). The walkthroughs for teachers and students, the configuration table and the project layout are in [`apps/api/README.md`](apps/api/README.md).

## Tools and models

| Area | What is used |
|---|---|
| API | Python 3.14, FastAPI, Pydantic, SQLAlchemy 2 + Alembic, managed with uv |
| Database | PostgreSQL 17 with the pgvector extension (relational data and vectors in one database) |
| PDF text | pdfminer.six (text layer with page and line positions) |
| Embeddings | `BAAI/bge-small-en-v1.5` (384 dimensions) run locally with fastembed (ONNX), so no embedding API or GPU is needed |
| Question model | Anthropic Claude through the Anthropic API, `claude-sonnet-5-5` for both drafting and validation (`LLM_GENERATION_MODEL`, `LLM_VALIDATION_MODEL`) |
| Printable PDFs | ReportLab |
| File storage | A local folder in development, S3 on AWS |
| Auth | PyJWT access tokens, argon2 password hashes, rotating refresh tokens |
| Web | React 19, TypeScript, Vite, React Router, TanStack Query, generated OpenAPI client |
| Infra | Docker, Terraform (ECS Fargate, RDS, S3, Secrets Manager, ALB), GitHub Actions |

Without `ANTHROPIC_API_KEY`, everything works except generation, which answers 503.

## How PDFs become questions

The pipeline is retrieval-augmented: questions are written from excerpts of the teacher's own PDFs, never from the model's general knowledge, and every question has to point back to the lines it came from.

**1. Ingestion** (background task after `POST /documents`)
1. The upload is checked (is a PDF, size under 25 MB, at most `PDF_MAX_PAGES` pages) and stored.
2. pdfminer.six extracts the text layer. Each non-empty text line is numbered 1, 2, 3... within its page. This is what "page and line" means in a citation. Scanned PDFs have no text layer and are rejected.
3. The lines are cut into **chunks** of 40 consecutive lines, each overlapping the previous one by 5, so a fact on a boundary appears whole in at least one chunk.
4. Each chunk is embedded locally (384-dimension vector) and saved in Postgres with its lines, as `[page, line, text]`, and the vector (HNSW index, cosine distance).
5. The document goes `pending` -> `processing` -> `ready`, or `failed` with a readable reason.

**2. Choosing excerpts** (when `POST /generations` runs)
- Without a `focus`, the question slots are spread evenly over all usable chunks of the selected documents, so the questions cover the whole text.
- With a `focus` (for example "photosynthesis"), the focus text is embedded and the nearest chunks by cosine similarity are used. This is the vector-search step of the RAG.
- Very short chunks are skipped, and the teacher's recent questions are passed along so the model does not repeat them.

**3. Drafting and checking** (one question "slot" at a time, up to 3 attempts per slot, each on a different chunk)
1. **Draft.** Claude gets one excerpt, with every line prefixed `[p12 l7]`, and is forced to answer through a tool call whose schema is validated by Pydantic: question, options, correct option, explanation and 1-3 citations (page, line range, quote copied word for word). The prompt says the excerpt is untrusted data, so instructions hidden in a PDF are ignored.
2. **Citation check (deterministic code, no model).** Each quoted text must appear in the cited lines of that chunk, ignoring case, whitespace and line-end hyphenation. Multiple-choice questions need four distinct options; true/false questions use A = True, B = False.
3. **Blind validation (second model call).** A fresh call sees the excerpt and the question but not the answer key. If it picks a different answer, or says the excerpt does not settle it or several options are defensible, the draft is dropped and the next attempt starts.
4. Only questions that pass all three steps are saved, with their citations stored as snapshots (document name, page, lines, quote) so they survive deleting the PDF.

The job ends `done` if at least one question was produced, otherwise `failed`. If a job asks for 10 questions and only 7 pass, you get 7.

**Limits to know about**
- Page and line numbers come from the extracted text layout. They match the printed page for ordinary text PDFs, but a PDF with front matter or unusual layout may number pages differently from the printed numbers.
- The checks show that the quote exists and that a second reading agrees with the answer. They do not replace a teacher reviewing the questions.

## Docs

- [`docs/PRD-exam-generator.md`](docs/PRD-exam-generator.md): current requirements
- [`docs/PRD-aws-saa-study-assistant.md`](docs/PRD-aws-saa-study-assistant.md): the student module
- [`docs/DEPLOY.md`](docs/DEPLOY.md): deploying to AWS
