# Backlog

Kept by the `orchestrator` agent. One line per task: what, owner (`api-dev`, `worker-dev`, `web-dev`, `infra-dev`), and the dependency if any. Order within each section is priority.

## Now

## Next
- Login rate limiting: Postgres-backed counter of failed logins per username and IP (new `login_attempts` table, a dependency that raises a `TOO_MANY_REQUESTS` DomainError -> 429 problem+json with `Retry-After`, trust `X-Forwarded-For` from the ALB only); reuse it for `/auth/refresh` and the public `/join/...` endpoints. No Redis. Owner: api-dev (core migration + API + `just gen-client`, error code in `apps/api/README.md`). Optional follow-up: AWS WAF rate rule on the ALB. Owner: infra-dev.
- Question editing (teacher edits a generated question before saving it to a set). Owners: api-dev, then web-dev.
- Run exam sessions from saved question sets, not only the built-in exam. Owners: api-dev, then web-dev.
- Assign question sets to students. Owners: api-dev, then web-dev.

## Later
- Live quality evaluation of generation with a real Anthropic key. Owner: worker-dev.
- Worker autoscaling on queue depth (Terraform). Owner: infra-dev.
- Log the SQS `MessageId` and `ApproximateReceiveCount` in worker job context: add `message_id`/`receive_count` to `exam_core.queue.Received` (api-dev), then bind them in `worker/consumer.py` (worker-dev).

## Done
- (done) Error handling refactor (branch `refactor/error-handling`): RFC 9457 problem+json for every error, domain exceptions in `exam_core/errors.py`, global handlers, request ids, JSON logging in `exam_core/logging.py`. Owner: api-dev (core + API + client).
- (done) Worker uses the shared JSON logging with job context. Owner: worker-dev (after api-dev).
- (done) Web parses problem+json errors (`src/errors.ts`). Owner: web-dev (after `just gen-client`, parallel with worker-dev).
