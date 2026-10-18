variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  description = "Prefix for resource names."
  type        = string
  default     = "exam-generator"
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "image_tag" {
  description = "Tag of the image in the ECR repository to run."
  type        = string
  default     = "latest"
}

variable "desired_count" {
  description = "API tasks. Keep 0 for the first apply: the image and the Anthropic key must exist before tasks can start."
  type        = number
  default     = 0
}

variable "task_cpu" {
  type    = number
  default = 1024
}

variable "task_memory" {
  description = "MiB. The embedding model and PDF parsing need headroom; do not go below 2048."
  type        = number
  default     = 2048
}

variable "certificate_arn" {
  description = "ACM certificate for HTTPS. When null the ALB serves plain HTTP only (fine for a throwaway POC, not for real users)."
  type        = string
  default     = null
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "db_allocated_storage" {
  type    = number
  default = 20
}

variable "db_multi_az" {
  type    = bool
  default = false
}

variable "protect_data" {
  description = "Deletion protection and a final snapshot on the database. Set false to tear a POC down."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "llm_generation_model" {
  type    = string
  default = "claude-sonnet-5-5"
}

variable "llm_validation_model" {
  type    = string
  default = "claude-sonnet-5-5"
}
