locals {
  required_apis = toset([
    "run.googleapis.com",
    "secretmanager.googleapis.com",
  ])
}

resource "google_project_service" "required" {
  for_each = local.required_apis

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "service" {
  account_id   = "webhook-komodor-rca"
  display_name = "Webhook Komodor RCA Cloud Run service"
}

ephemeral "random_password" "webhook_token" {
  count = var.generate_webhook_token ? 1 : 0

  length  = 48
  special = false
}

resource "google_secret_manager_secret" "webhook_token" {
  count = var.generate_webhook_token ? 1 : 0

  secret_id = var.webhook_token_secret_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "webhook_token" {
  count = var.generate_webhook_token ? 1 : 0

  secret                 = google_secret_manager_secret.webhook_token[0].id
  secret_data_wo         = ephemeral.random_password.webhook_token[0].result
  secret_data_wo_version = var.webhook_token_generation
}

resource "google_secret_manager_secret_iam_member" "komodor_api_key" {
  project   = var.project_id
  secret_id = var.komodor_api_key_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.service.email}"
}

resource "google_secret_manager_secret_iam_member" "slack_webhook_uri" {
  count = var.slack_delivery_mode == "webhook" ? 1 : 0

  project   = var.project_id
  secret_id = var.slack_webhook_uri_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.service.email}"
}

resource "google_secret_manager_secret_iam_member" "slack_bot_token" {
  count = var.slack_delivery_mode == "bot" ? 1 : 0

  project   = var.project_id
  secret_id = var.slack_bot_token_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.service.email}"
}

resource "google_secret_manager_secret_iam_member" "webhook_token" {
  project   = var.project_id
  secret_id = var.webhook_token_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.service.email}"

  depends_on = [google_secret_manager_secret_version.webhook_token]
}

resource "google_cloud_run_v2_service" "service" {
  name     = var.service_name
  location = var.region

  deletion_protection = var.deletion_protection
  ingress             = "INGRESS_TRAFFIC_ALL"
  # Requests are authenticated by WEBHOOK_TOKEN inside the application.
  # Disable Cloud Run's IAM invoker check instead of granting allUsers a role.
  invoker_iam_disabled = true

  template {
    service_account                  = google_service_account.service.email
    timeout                          = "3600s"
    max_instance_request_concurrency = 10

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.container_image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        # Background polling continues after the webhook receives its 202.
        cpu_idle = false
      }

      ports {
        container_port = 8080
      }

      env {
        name  = "DEFAULT_WORKLOAD_KIND"
        value = var.default_workload_kind
      }

      env {
        name  = "PROCESS_STATUSES"
        value = var.process_statuses
      }

      env {
        name  = "PROCESS_SEVERITIES"
        value = var.process_severities
      }

      env {
        name  = "PUBLISH_CUSTOM_EVENT"
        value = tostring(var.publish_custom_event)
      }

      env {
        name  = "INVESTIGATION_TIMEOUT"
        value = var.investigation_timeout
      }

      env {
        name  = "LOG_LEVEL"
        value = var.log_level
      }

      env {
        name = "KOMODOR_API_KEY"
        value_source {
          secret_key_ref {
            secret  = var.komodor_api_key_secret_id
            version = var.secret_version
          }
        }
      }

      dynamic "env" {
        for_each = var.slack_delivery_mode == "webhook" ? [1] : []
        content {
          name = "SLACK_WEBHOOK_URI"
          value_source {
            secret_key_ref {
              secret  = var.slack_webhook_uri_secret_id
              version = var.secret_version
            }
          }
        }
      }

      dynamic "env" {
        for_each = var.slack_delivery_mode == "bot" ? [1] : []
        content {
          name = "SLACK_BOT_TOKEN"
          value_source {
            secret_key_ref {
              secret  = var.slack_bot_token_secret_id
              version = var.secret_version
            }
          }
        }
      }

      dynamic "env" {
        for_each = var.slack_delivery_mode == "bot" ? [1] : []
        content {
          name  = "SLACK_CHANNEL_ID"
          value = var.slack_channel_id
        }
      }

      env {
        name = "WEBHOOK_TOKEN"
        value_source {
          secret_key_ref {
            secret  = var.webhook_token_secret_id
            version = var.secret_version
          }
        }
      }

      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 3
        period_seconds        = 10
        failure_threshold     = 3

        http_get {
          path = "/healthz"
          port = 8080
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.komodor_api_key,
    google_secret_manager_secret_iam_member.slack_webhook_uri,
    google_secret_manager_secret_iam_member.slack_bot_token,
    google_secret_manager_secret_iam_member.webhook_token,
  ]
}
