variable "project_id" {
  description = "Google Cloud project ID."
  type        = string
}

variable "region" {
  description = "Cloud Run region."
  type        = string
  default     = "europe-west2"
}

variable "service_name" {
  description = "Cloud Run service name."
  type        = string
  default     = "webhook-komodor-rca"
}

variable "container_image" {
  description = "Existing container image URI to deploy."
  type        = string
}

variable "komodor_api_key_secret_id" {
  description = "Existing Secret Manager secret ID containing the Komodor API key."
  type        = string
  default     = "komodor-api-key"
}

variable "slack_webhook_uri_secret_id" {
  description = "Existing Secret Manager secret ID containing the Slack incoming webhook URI."
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
  description = "Existing Secret Manager secret ID containing a Slack bot token with chat:write."
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
  description = "Secret Manager secret ID containing the generated or existing inbound webhook bearer token."
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

variable "secret_version" {
  description = "Secret Manager version exposed to the container."
  type        = string
  default     = "latest"
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
  type    = string
  default = "20m"
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

variable "min_instances" {
  type    = number
  default = 1
}

variable "max_instances" {
  type    = number
  default = 10
}

variable "deletion_protection" {
  type    = bool
  default = false
}
