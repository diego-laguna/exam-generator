# Background work: the API sends a small message (`ingest_document 12`), the worker service does it.
# A message that fails three times (the worker crashed each time) lands in the dead-letter queue.
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name}-jobs-dlq"
  message_retention_seconds = 1209600 # 14 days to look at what went wrong
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "jobs" {
  name                       = "${var.name}-jobs"
  visibility_timeout_seconds = 300 # the worker extends it while a job runs
  message_retention_seconds  = 86400
  receive_wait_time_seconds  = 20 # long polling
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "${var.name}-jobs-dlq-not-empty"
  alarm_description   = "A background job failed repeatedly. Inspect the dead-letter queue."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
}
