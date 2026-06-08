variable "region" {
  description = "AWS region for Lambda and Secrets Manager."
  type        = string
  default     = "eu-west-2"
}

variable "function_name" {
  description = "Lambda function name."
  type        = string
  default     = "webhook-komodor-rca"
}

variable "container_image_uri" {
  description = "Existing ECR image URI built using Dockerfile.lambda."
  type        = string
}

variable "komodor_api_key_secret_id" {
  description = "Secrets Manager secret name containing the Komodor API key."
  type        = string
  default     = "komodor-api-key"
}

variable "slack_webhook_uri_secret_id" {
  description = "Secrets Manager secret name containing the Slack incoming webhook URI."
  type        = string
  default     = "slack-webhook-uri"
}

variable "slack_delivery_mode" {
  description = "Slack delivery mode: bot posts an initial message with threaded RCA details; webhook posts one combined message."
  type        = string
  default     = "webhook"

  validation {
    condition     = contains(["bot", "webhook"], var.slack_delivery_mode)
    error_message = "slack_delivery_mode must be bot or webhook."
  }
}

variable "slack_bot_token_secret_id" {
  description = "Secrets Manager secret name containing a Slack bot token with chat:write."
  type        = string
  default     = "slack-bot-token"
}

variable "slack_channel_id" {
  description = "Slack channel ID used in bot mode."
  type        = string
  default     = ""

  validation {
    condition     = var.slack_delivery_mode != "bot" || var.slack_channel_id != ""
    error_message = "slack_channel_id is required when slack_delivery_mode is bot."
  }
}

variable "webhook_token_secret_id" {
  description = "Secrets Manager secret name containing the generated or existing inbound webhook bearer token."
  type        = string
  default     = "rca-webhook-token"
}

variable "generate_webhook_token" {
  description = "Create the webhook token secret and generate its value ephemerally during deployment."
  type        = bool
  default     = true
}

variable "webhook_token_generation" {
  description = "Increment to rotate the generated webhook token."
  type        = number
  default     = 1
}

variable "default_workload_kind" {
  type    = string
  default = "Deployment"
}

variable "process_statuses" {
  type    = string
  default = "firing"
}

variable "process_severities" {
  description = "Comma-separated event severities that are allowed to trigger an RCA."
  type        = string
  default     = "critical"
}

variable "publish_custom_event" {
  description = "Publish a scoped Komodor custom event when an RCA session is triggered."
  type        = bool
  default     = true
}

variable "investigation_timeout" {
  description = "Must be shorter than Lambda's 15-minute timeout."
  type        = string
  default     = "14m"
}

variable "log_level" {
  description = "Structured application log level."
  type        = string
  default     = "info"

  validation {
    condition     = contains(["debug", "info", "warn", "error"], var.log_level)
    error_message = "log_level must be debug, info, warn, or error."
  }
}

variable "memory_size" {
  type    = number
  default = 512
}

variable "reserved_concurrent_executions" {
  description = "Maximum concurrent RCA investigations. Use -1 for unreserved concurrency."
  type        = number
  default     = 10
}

variable "log_retention_days" {
  type    = number
  default = 30
}
