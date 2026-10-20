output "url" {
  value = var.certificate_arn == null ? "http://${aws_lb.main.dns_name}" : "https://${aws_lb.main.dns_name}"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "worker_ecr_repository_url" {
  value = aws_ecr_repository.worker.repository_url
}

output "jobs_queue_url" {
  value = aws_sqs_queue.jobs.url
}

output "jobs_dead_letter_queue_url" {
  value = aws_sqs_queue.dlq.url
}

output "documents_bucket" {
  value = aws_s3_bucket.documents.bucket
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "migrate_task_definition" {
  value = aws_ecs_task_definition.migrate.family
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "api_security_group_id" {
  value = aws_security_group.api.id
}

output "anthropic_secret_name" {
  value = aws_secretsmanager_secret.anthropic.name
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}
