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

# Alerts: both alarms publish to one SNS topic. Without `alert_email` the topic has no subscriber
# (alarms only change state in the console); subscribe a chat or paging endpoint to it by hand if you prefer.
resource "aws_sns_topic" "alerts" {
  name = "${var.name}-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email" # AWS sends a confirmation link first; alerts start after it is clicked
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "${var.name}-jobs-dlq-not-empty"
  alarm_description   = "A background job failed repeatedly. Inspect the dead-letter queue (see docs/DEPLOY.md)."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# Work is waiting but nothing takes it: the worker is down, crash-looping or too slow. Such messages never
# reach the dead-letter queue, so the alarm above cannot see them.
resource "aws_cloudwatch_metric_alarm" "jobs_backlog_old" {
  alarm_name          = "${var.name}-jobs-oldest-message-old"
  alarm_description   = "The oldest queued job has waited too long. Check that the worker service is running (see docs/DEPLOY.md)."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = aws_sqs_queue.jobs.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = var.queue_max_age_seconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching" # an empty queue reports nothing
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
