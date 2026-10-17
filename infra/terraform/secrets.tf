resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "jwt" {
  name                    = "${var.name}/jwt-secret-key"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "jwt" {
  secret_id     = aws_secretsmanager_secret.jwt.id
  secret_string = random_password.jwt.result
}

# Only the container is created here. Set the value out of band so the key never enters Terraform
# state or this repository:
#   aws secretsmanager put-secret-value --secret-id learn-assistant/anthropic-api-key --secret-string "$KEY"
resource "aws_secretsmanager_secret" "anthropic" {
  name                    = "${var.name}/anthropic-api-key"
  recovery_window_in_days = 7
}
