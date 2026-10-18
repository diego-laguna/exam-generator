# learn-assistant

An exam generator for teachers. Teachers upload PDFs; the API generates multiple-choice and true/false questions with answers, explanations and citations (file, page, line), verifies them automatically, and lets teachers save question sets and download printable PDFs. A smaller student module (timed AWS SAA-C03 practice exams) is kept.

This is a monorepo. A React frontend is planned next.

## Layout

```
apps/api/          Python / FastAPI service (see apps/api/README.md for details)
infra/terraform/   AWS infrastructure (ECS Fargate, RDS pgvector, S3, Secrets Manager, ALB)
docs/              PRDs, deployment guide, system design diagram
compose.yaml       PostgreSQL + pgvector for local development
justfile           One entry point for common tasks (`just` lists them)
.github/workflows/ CI
```

## Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/), Docker with Compose, [just](https://github.com/casey/just).

```bash
just api-install                  # Python dependencies
cp apps/api/.env.example apps/api/.env   # then set JWT_SECRET_KEY (and ANTHROPIC_API_KEY to generate questions)
just db-up                        # PostgreSQL + pgvector
just migrate                      # schema + reference data
just seed                         # sample users (development only)
just api-dev                      # http://127.0.0.1:8000/docs
```

Checks: `just check` (pyright + tests). The walkthroughs for teachers and students, the configuration table and the project layout are in [`apps/api/README.md`](apps/api/README.md).

## Docs

- [`docs/PRD-exam-generator.md`](docs/PRD-exam-generator.md): current requirements
- [`docs/PRD-aws-saa-study-assistant.md`](docs/PRD-aws-saa-study-assistant.md): the student module
- [`docs/DEPLOY.md`](docs/DEPLOY.md): deploying to AWS
