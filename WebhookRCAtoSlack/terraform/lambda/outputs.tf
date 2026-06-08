output "webhook_url" {
  description = "Configure this URL as the webhook destination."
  value       = "${aws_lambda_function_url.service.function_url}webhooks/rca"
}

output "function_name" {
  value = aws_lambda_function.service.function_name
}

output "webhook_token_secret_id" {
  description = "Retrieve this secret directly from Secrets Manager to configure the webhook sender."
  value       = var.webhook_token_secret_id
}
