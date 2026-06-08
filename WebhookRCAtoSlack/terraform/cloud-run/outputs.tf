output "webhook_url" {
  description = "Configure this URL as the webhook destination."
  value       = "${google_cloud_run_v2_service.service.uri}/webhooks/rca"
}

output "service_account" {
  value = google_service_account.service.email
}

output "webhook_token_secret_id" {
  description = "Retrieve this secret directly from Secret Manager to configure the webhook sender."
  value       = var.webhook_token_secret_id
}
