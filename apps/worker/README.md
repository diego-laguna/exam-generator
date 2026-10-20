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
