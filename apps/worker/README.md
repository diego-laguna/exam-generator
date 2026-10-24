# Exam-Generator worker

Takes background jobs from the queue and does the heavy work, so the API stays small and fast to build and deploy:

| Message | Job |
|---|---|
| `ingest_document` | Read the teacher's PDF from storage, extract numbered lines (pdfminer.six), cut 40-line chunks, embed them (fastembed, `BAAI/bge-small-en-v1.5`) and store them with pgvector |
| `run_generation` | Pick excerpts, draft questions with Claude, verify citations, validate blindly, store the questions |
| `ingest_source` | Fetch an allowlisted AWS documentation page, chunk, embed (student module) |
| `embed_samples` | Fill in the embeddings of freshly added sample questions |

The API creates a row (document `pending`, job `queued`) and sends a message that only names the work. The state always lives in Postgres.

## Run it

```bash
just db-up                          # Postgres and the local queue (ElasticMQ)
cp apps/worker/.env.example apps/worker/.env   # then add ANTHROPIC_API_KEY yourself
just worker-dev                     # or: cd apps/worker && uv run python -m worker
just worker-test                    # tests (need the database)
```

The worker must share the database, the PDF storage folder (or S3 bucket) and the queue with the API. The defaults in both `.env.example` files line up for local development.

## Delivery guarantees

- A message is deleted only after its job finished (successfully, or recorded as `failed` on its row). If the worker crashes, the message reappears after the visibility timeout and, after 3 receives, moves to the dead-letter queue.
- While a job runs, a heartbeat thread extends the message's visibility, so a long job is not handed to a second worker.
- Jobs are idempotent against redelivery: a document is claimed from `pending` or `processing` (a dead worker leaves no chunks behind, so it restarts cleanly); a generation job is claimed only from `queued`, so questions are never produced twice (a job interrupted mid-way is reported `failed` after `JOB_STALE_MINUTES`).
- On SIGTERM (an ECS deploy) the worker finishes its current job, then exits (up to one long-poll of 20 s).

## What this generator does with embeddings

**Embeddings are only a ranking tool, not the source of truth.**
- The only live use is `build_candidate_pool` (`worker/question_gen.py`). It runs when the teacher gives a **focus** topic. The focus is embedded and the `DocumentChunk`s are ordered by cosine distance, taking the closest `max(slots*3, 12)`.
- Without a focus, there is no vector search. Chunks are taken in document order and spread evenly across the slots.
- The LLM never sees the embeddings. It gets the chunk text, and the answer is checked by the citation check (is the quote really in the cited page and lines?) and by blind validation. A weak embedding match costs relevance, not correctness. A bad retrieval can't produce an unverified question.

**Retrieval is small and scoped.**
- It is filtered to the teacher's own `document_ids`, a handful of PDFs. There is no global corpus search, so the candidate set is small.
- Chunks are 40 numbered lines with 5 lines of overlap. That size comes from the citation requirement (page and line), not from what suits the embedding model. The chunking serves the citations first, the retrieval second.
- Chunks shorter than `MIN_CHUNK_CHARS` are skipped.

**The model runs locally and only in the worker.**
- It is `fastembed` with ONNX and `bge-small-en-v1.5` (384 dims). There is no embedding API, no key and no PyTorch.
- The API never imports it (CI checks this). The `Embedder` protocol and `EMBEDDING_DIM` live in `exam_core`, so the DB schema can be shared.
- Tests use `FakeEmbedder`.

**Embedding happens at ingest, asynchronously.**
- Embeddings are computed after upload, in `ingest_document`. Sample question embeddings are filled in later by an `embed_samples` job, so that column is nullable.
- Jobs are idempotent: they claim rows by status, and `embed_samples` only fills rows where `embedding IS NULL`.

**One model and one dimension are baked into the schema.**
- There are three `Vector(384)` columns (`chunks`, `sample_questions`, `document_chunks`), each with an HNSW index using `vector_cosine_ops`.
- Changing the model needs a migration and a re-embed of everything.

**Two of the three tables are not used for generation yet.** `similar_chunks` (`apps/api/app/retrieval.py`) and the `chunks` and `sample_questions` tables belong to the legacy student module ("ready for M5").

## Functional Programming

LLM and embedding calls are slow, costly and non-deterministic, so everything around them is kept deterministic.

**Pure core, thin shell.**
- The core is pure functions: values in, new values out, no I/O, no DB session, no clock, no argument mutation.
- The job handlers (`handlers.py`, `document_ingestion.py`, `source_ingestion.py`, the generation entry in `question_gen.py`) are the shell. They keep the embedding call, the LLM call, storage and queue I/O, and all database access.
- Style: `map`/`filter`/comprehensions, tuples and frozen dataclasses, no module-level mutable state.

**Where it lives.**
- `worker/pure.py`: `question_slots`, `citation_snapshots`, `blind_validation`, `generation_failure`, `avoid_window`, `document_chunk_rows`.
- `pdf_text.number_lines` and `chunk_lines`; `chunking` (a reduce over immutable tuples, frozen `Section` and `Chunk`).
- `quote_matches`, `check_draft` and the prompt builders.
- Tests: `tests/test_pure_functions.py`. Plain input and output, no mocks, fakes or DB.

**Why.**
1. **Testing without mocks.** The logic that decides whether to trust model output (checking that a quote appears in the cited page and lines, filtering and de-duplicating candidates) is cheap to test thoroughly.
2. **A clear boundary around the non-deterministic part.** When quality regresses, you can tell whether the model or your logic changed. It fits the rule that generated questions need verified citations and blind validation.
3. **Safe retries and redelivery.** Pure steps give the same result when re-run; only the shell must claim the row by status first. LLM pipelines fail and retry often (rate limits, timeouts, malformed output).
4. **Immutable data, no shared state.** No step can mutate data another still needs (prompts, retrieved chunks, the avoid list). It is also simpler if jobs later run in parallel.
5. **Composable pipelines.** Extract text, number lines, chunk, embed, retrieve, prompt, validate, persist: each pure stage can be swapped independently.
6. **Reproducibility.** A recorded input (chunks, a model response) reproduces the exact result, so real failures become regression cases.

**Trade-offs.**
- In Python this is a style, not enforced.
- `reduce` over tuples can read worse than a loop, and copying immutable structures costs a little.
- The value is the pure core / thin shell split; the idioms are secondary.
- It does not make the model deterministic. It isolates the non-determinism so you can test, retry and audit around it.

## Configuration

Shared settings (`DATABASE_URL`/`DB_*`, `STORAGE_BACKEND`, `LOCAL_STORAGE_DIR`, `S3_BUCKET`, `SQS_QUEUE_URL`, `SQS_ENDPOINT_URL`, `JOB_STALE_MINUTES`) are described in [`apps/api/README.md`](../api/README.md). Worker-only settings:

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | Enables generation. Blank counts as unset; jobs then fail with a clear message. Never commit it |
| `LLM_GENERATION_MODEL` / `LLM_VALIDATION_MODEL` | `claude-sonnet-5-5` | Models for drafting and for blind validation |
| `PDF_MAX_PAGES` | `400` | Longer PDFs fail with a readable error |
| `GENERATION_ATTEMPTS_PER_SLOT` | `3` | Tries per requested question |
| `EMBEDDING_MODEL` / `EMBEDDING_CACHE_DIR` | `BAAI/bge-small-en-v1.5` / `../../.cache/fastembed` | Must output 384 dimensions |
| `WORKER_VISIBILITY_SECONDS` | `300` | Message visibility while working (extended by the heartbeat) |

## Image

`docker build -f apps/worker/Dockerfile .` (context: the repository root). The embedding model is baked in a separate build stage, so it is downloaded again only when the model changes, not on every code or dependency update. The API image has none of these libraries.
