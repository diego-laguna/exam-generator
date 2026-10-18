# learn-assistant

An exam generator for teachers. Teachers upload PDFs; the API generates multiple-choice and true/false questions with answers, explanations and citations (file, page, line), verifies them automatically, and lets teachers save question sets and download printable PDFs. A smaller student module (timed AWS SAA-C03 practice exams) is kept.

This is a monorepo with a Python API and a React web app for teachers.

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
just web-dev                      # http://localhost:5173  (sign in as dave / teacher-pass)
```

The web app talks to the API through the Vite dev proxy, so there is no CORS to configure. After changing an API endpoint or schema, run `just gen-client` and commit the regenerated `packages/api-client` files; CI fails if they are stale.

Checks: `just check` (pyright, API tests, JS typecheck, web tests). The walkthroughs for teachers and students, the configuration table and the project layout are in [`apps/api/README.md`](apps/api/README.md).

## Docs

- [`docs/PRD-exam-generator.md`](docs/PRD-exam-generator.md): current requirements
- [`docs/PRD-aws-saa-study-assistant.md`](docs/PRD-aws-saa-study-assistant.md): the student module
- [`docs/DEPLOY.md`](docs/DEPLOY.md): deploying to AWS
