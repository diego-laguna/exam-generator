# Deploying to AWS

Architecture: ALB → ECS Fargate (API container) → RDS PostgreSQL 17 (pgvector), S3 (PDFs) and an SQS queue; a second Fargate service (the worker) consumes the queue. Secrets live in Secrets Manager and are injected as environment variables, so the app's settings code is the same as locally. Infrastructure is Terraform in `infra/terraform/` (validated with `terraform validate`, not applied by CI).

```
Internet → ALB (public subnets) → API tasks (private subnets) → RDS (private)
                                        │
                                        ├→ S3 (PDFs, private, encrypted)
                                        └→ SQS jobs queue (+ dead-letter queue)
                                                │
                                   Worker tasks ┘ → RDS, S3 (read PDFs)
                                        │
                                        ├→ Secrets Manager (JWT key, Anthropic key, DB password)
                                        └→ NAT gateway → api.anthropic.com
```

| Concern | Resource |
|---|---|
| Container images | Two ECR repositories, `exam-generator` (API) and `exam-generator-worker` (scan on push, keeps last 20 each) |
| API | ECS Fargate service, circuit-breaker rollback, `/health` target check. Gets only the JWT key and DB secrets; may send to the queue |
| Worker | ECS Fargate service without a load balancer: embeddings, PDF processing, question generation. Gets the DB secrets and the Anthropic key; may receive from the queue and read PDFs |
| Job queue | SQS standard queue with long polling and a dead-letter queue after 3 receives (14-day retention), SSE, and CloudWatch alarms (dead-letter queue not empty, oldest job too old) that publish to an SNS topic |
| Migrations | One-off ECS task (`migrate`): `alembic upgrade head` + reference data |
| Database | RDS PostgreSQL 17, encrypted, 7-day backups, master password managed (and rotatable) by RDS in Secrets Manager |
| PDFs | S3 bucket: public access blocked, SSE, TLS-only policy; the API task role writes and the worker role reads `documents/*` only |
| Secrets | `exam-generator/jwt-secret-key` (generated), `exam-generator/anthropic-api-key` (you set it), RDS secret |
| Network | VPC, 2 AZs, ALB in public subnets, tasks and DB in private subnets, S3 gateway endpoint, one NAT |
| Logs | CloudWatch `/ecs/exam-generator` |

## Prerequisites

AWS credentials for the target account (`aws sso login` or a profile), Terraform ≥ 1.9, Docker, and optionally an ACM certificate for HTTPS.

## First deployment

The API and worker services start at 0 tasks, because they cannot run before their images and the Anthropic key exist.

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars        # edit region / certificate_arn
terraform init && terraform apply

ECR=$(terraform output -raw ecr_repository_url)
ECR_WORKER=$(terraform output -raw worker_ecr_repository_url)
REGION=us-east-1                                    # same as in tfvars

# 1. Build and push both images (Fargate runs linux/amd64 here). The build context is the repository root.
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin "${ECR%%/*}"
docker build --platform linux/amd64 -f ../../apps/api/Dockerfile -t "$ECR:latest" ../..
docker build --platform linux/amd64 -f ../../apps/worker/Dockerfile -t "$ECR_WORKER:latest" ../..
docker push "$ECR:latest"
docker push "$ECR_WORKER:latest"

# 2. Store the Anthropic key without echoing it or putting it on the command line
read -rs ANTHROPIC_KEY
aws secretsmanager put-secret-value --region $REGION \
  --secret-id "$(terraform output -raw anthropic_secret_name)" --secret-string "$ANTHROPIC_KEY"
unset ANTHROPIC_KEY

# 3. Run migrations
SUBNETS=$(terraform output -json private_subnet_ids | jq -r 'join(",")')
SG=$(terraform output -raw api_security_group_id)
aws ecs run-task --region $REGION --cluster "$(terraform output -raw ecs_cluster)" --launch-type FARGATE \
  --task-definition "$(terraform output -raw migrate_task_definition)" \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=DISABLED}"
# watch it in CloudWatch (stream prefix "migrate"), wait for exit code 0

# 4. Start the API and the worker
terraform apply -var desired_count=1 -var worker_desired_count=1
curl "$(terraform output -raw url)/health"
```

Use a dedicated Anthropic key with a monthly spend limit. Never commit it.

### Create the first admin

Run the bootstrap script as a one-off task with the password supplied through the task override, not typed into shell history:

```bash
read -rs ADMIN_PASSWORD
OVERRIDES=$(jq -n --arg p "$ADMIN_PASSWORD" --arg u admin '{containerOverrides:[{name:"migrate",
  command:["python","-m","scripts.create_admin",$u],environment:[{name:"ADMIN_PASSWORD",value:$p}]}]}')
unset ADMIN_PASSWORD
aws ecs run-task --region $REGION --cluster "$(terraform output -raw ecs_cluster)" --launch-type FARGATE \
  --task-definition "$(terraform output -raw migrate_task_definition)" --overrides "$OVERRIDES" \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=DISABLED}"
```

The admin then creates teachers with `POST /api/v1/users` (`"role": "teacher"`). The sample users (`scripts.seed`) are for local development only and are never created on AWS.

## Updating

Push new image tags (only the images whose code changed need a new build: an API-only change does not touch the worker image or its embedding model), run the migrate task if the schema changed, then `terraform apply -var image_tag=<tag>` (or force a new deployment with `aws ecs update-service --force-new-deployment` for `api` and `worker`). The circuit breaker rolls back a deployment whose tasks fail health checks. The worker finishes its current job on SIGTERM (stop timeout 120 s).

## Things to know before real use

- **HTTPS:** without `certificate_arn` the ALB serves plain HTTP, so passwords and tokens cross the internet unencrypted. Set a certificate before anyone real logs in.
- **Login rate limiting:** the API limits failed logins per username and per client IP (counters in the `login_attempts` table). The task definition of the API (not the worker) sets `TRUSTED_PROXY_HOPS=1` (variable `trusted_proxy_hops`, default 1): the ALB appends the real client IP to `X-Forwarded-For`, and the API uses the entry that many hops from the right. Without it every client would appear as the ALB's private IP and the per-IP limit would hit all users together. The Terraform has only the ALB in front of the API; if you add CloudFront or another proxy, raise `trusted_proxy_hops` by one per extra proxy that appends to the header. The limits themselves (`LOGIN_MAX_FAILURES_PER_USERNAME`, `LOGIN_MAX_FAILURES_PER_IP`, `LOGIN_WINDOW_SECONDS`) keep their code defaults. The migration that creates `login_attempts` must be applied (run the `migrate` task, see *First deployment* step 3) before deploying the new API image, otherwise logins fail.
- **Background jobs:** the API only queues work; the worker does it. If the worker is down, uploads stay `pending` (reported failed after `JOB_STALE_MINUTES`) while their messages wait in the queue. Two CloudWatch alarms publish to the `alerts` SNS topic (set `alert_email` to get them by email): the dead-letter queue is not empty (a message crashed the worker three times) and the oldest waiting job is older than `queue_max_age_seconds` (worker down or too slow). See *When an alarm fires* below. A generation job interrupted mid-way is reported failed and the teacher retries. One worker task is enough to start; run more by raising `worker_desired_count` (there is no autoscaling on queue depth yet).
- **When an alarm fires:** *Backlog old*: check the `worker` ECS service (desired count, stopped tasks, CloudWatch logs); the messages are still queued and are processed once it runs. *DLQ not empty*: open the SQS console, `exam-generator-jobs-dlq`, **Poll for messages** to read the message (it names only the work, for example `ingest_document 12`), find that row's `error` and the worker logs, fix the cause, then **Start DLQ redrive** to send the messages back to the main queue. Jobs are idempotent, so a redrive is safe. The row itself is already reported failed after `JOB_STALE_MINUTES`; the teacher can also just upload or generate again.
- **Cost (rough, us-east-1):** NAT gateway ≈ $33/month, ALB ≈ $17, Fargate 1 vCPU / 2 GB ≈ $36, RDS t4g.micro ≈ $13, plus LLM usage. Tear down a POC with `protect_data=false` then `terraform destroy`.
- **Terraform state** holds the generated JWT key. Use an encrypted remote backend (see `versions.tf`) beyond a personal POC.
- **Rotating secrets:** the JWT key rotates by changing the secret and redeploying (it signs out everyone). The DB password is rotated by RDS; redeploy to pick it up.
- **Not included:** WAF, autoscaling (API or worker), multi-region, VPC endpoints for ECR/Secrets Manager (they go through the NAT), a CI deploy pipeline.
