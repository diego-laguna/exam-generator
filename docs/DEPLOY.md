# Deploying to AWS

Architecture: ALB → ECS Fargate (API container) → RDS PostgreSQL 17 (pgvector) and S3 (PDFs). Secrets live in Secrets Manager and are injected as environment variables, so the app's settings code is the same as locally. Infrastructure is Terraform in `infra/terraform/` (validated with `terraform validate`, not applied by CI).

```
Internet → ALB (public subnets) → ECS Fargate tasks (private subnets) → RDS (private)
                                        │                                 
                                        ├→ S3 (PDFs, private, encrypted)
                                        ├→ Secrets Manager (JWT key, Anthropic key, DB password)
                                        └→ NAT gateway → api.anthropic.com
```

| Concern | Resource |
|---|---|
| Container image | ECR (scan on push, keeps last 20) |
| API | ECS Fargate service, 1 task by default, circuit-breaker rollback, `/health` target check |
| Migrations | One-off ECS task (`migrate`): `alembic upgrade head` + reference data |
| Database | RDS PostgreSQL 17, encrypted, 7-day backups, master password managed (and rotatable) by RDS in Secrets Manager |
| PDFs | S3 bucket: public access blocked, SSE, TLS-only policy; task role limited to `documents/*` |
| Secrets | `exam-generator/jwt-secret-key` (generated), `exam-generator/anthropic-api-key` (you set it), RDS secret |
| Network | VPC, 2 AZs, ALB in public subnets, tasks and DB in private subnets, S3 gateway endpoint, one NAT |
| Logs | CloudWatch `/ecs/exam-generator` |

## Prerequisites

AWS credentials for the target account (`aws sso login` or a profile), Terraform ≥ 1.9, Docker, and optionally an ACM certificate for HTTPS.

## First deployment

The service starts at 0 tasks, because it cannot run before the image and the Anthropic key exist.

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars        # edit region / certificate_arn
terraform init && terraform apply

ECR=$(terraform output -raw ecr_repository_url)
REGION=us-east-1                                    # same as in tfvars

# 1. Build and push the image (Fargate runs linux/amd64 here)
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin "${ECR%%/*}"
docker build --platform linux/amd64 -t "$ECR:latest" ../../apps/api
docker push "$ECR:latest"

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

# 4. Start the API
terraform apply -var desired_count=1
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

Push a new image tag, run the migrate task if the schema changed, then `terraform apply -var image_tag=<tag>` (or force a new deployment with `aws ecs update-service --force-new-deployment`). The circuit breaker rolls back a deployment whose tasks fail health checks.

## Things to know before real use

- **HTTPS:** without `certificate_arn` the ALB serves plain HTTP, so passwords and tokens cross the internet unencrypted. Set a certificate before anyone real logs in.
- **Background jobs:** document processing and generation run inside the API task. A deploy or crash mid-job leaves it `processing`/`running`; it is reported as failed after `JOB_STALE_MINUTES` and the teacher retries. Use a single task until jobs move to SQS.
- **Cost (rough, us-east-1):** NAT gateway ≈ $33/month, ALB ≈ $17, Fargate 1 vCPU / 2 GB ≈ $36, RDS t4g.micro ≈ $13, plus LLM usage. Tear down a POC with `protect_data=false` then `terraform destroy`.
- **Terraform state** holds the generated JWT key. Use an encrypted remote backend (see `versions.tf`) beyond a personal POC.
- **Rotating secrets:** the JWT key rotates by changing the secret and redeploying (it signs out everyone). The DB password is rotated by RDS; redeploy to pick it up.
- **Not included:** WAF, autoscaling, multi-region, VPC endpoints for ECR/Secrets Manager (they go through the NAT), a CI deploy pipeline.
