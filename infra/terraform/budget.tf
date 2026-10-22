# Google Cloud budgets alert; they do not stop spending. The shutoff below does:
# when the budget's own alert reports cost at or above the cap, a small function
# unlinks billing from the project, which stops every billable service in it.

resource "google_pubsub_topic" "budget_alerts" {
  name = "budget-alerts"

  message_storage_policy {
    allowed_persistence_regions = [var.region]
  }

  depends_on = [google_project_service.enabled]
}

resource "google_billing_budget" "cap" {
  billing_account = var.billing_account
  display_name    = "${var.project_id} hard cap"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.budget_usd)
    }
  }

  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 0.75 }
  threshold_rules { threshold_percent = 1.0 }

  all_updates_rule {
    pubsub_topic = google_pubsub_topic.budget_alerts.id
  }
}

# ----- The shutoff function and the one permission it needs.

resource "google_service_account" "budget_shutoff" {
  account_id   = "budget-shutoff"
  display_name = "Unlinks billing when the budget cap is reached"

  # A fresh project rejects service accounts until the IAM API is enabled.
  depends_on = [google_project_service.enabled]
}

# Project Billing Manager can unlink this project's billing and nothing else.
resource "google_project_iam_member" "shutoff_billing" {
  project = var.project_id
  role    = "roles/billing.projectManager"
  member  = "serviceAccount:${google_service_account.budget_shutoff.email}"
}

resource "google_project_iam_member" "shutoff_events" {
  project = var.project_id
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${google_service_account.budget_shutoff.email}"
}

resource "google_storage_bucket" "function_source" {
  name                        = "${var.project_id}-function-source"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true

  depends_on = [google_project_service.enabled]
}

data "archive_file" "budget_shutoff" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/budget_shutoff"
  output_path = "${path.module}/.build/budget_shutoff.zip"
  excludes    = ["test_main.py", "__pycache__"]
}

resource "google_storage_bucket_object" "budget_shutoff" {
  name   = "budget_shutoff-${data.archive_file.budget_shutoff.output_md5}.zip"
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.budget_shutoff.output_path
}

resource "google_cloudfunctions2_function" "budget_shutoff" {
  name     = "budget-shutoff"
  location = var.region

  build_config {
    runtime     = "python312"
    entry_point = "on_budget_alert"
    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.budget_shutoff.name
      }
    }
  }

  service_config {
    max_instance_count    = 1
    available_memory      = "256M"
    timeout_seconds       = 60
    service_account_email = google_service_account.budget_shutoff.email
    environment_variables = {
      PROJECT_ID = var.project_id
    }
  }

  event_trigger {
    trigger_region        = var.region
    event_type            = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic          = google_pubsub_topic.budget_alerts.id
    retry_policy          = "RETRY_POLICY_RETRY"
    service_account_email = google_service_account.budget_shutoff.email
  }

  depends_on = [google_project_iam_member.shutoff_events]
}

# Eventarc delivers to the function's Cloud Run service as this account.
resource "google_cloud_run_service_iam_member" "shutoff_invoker" {
  location = var.region
  service  = google_cloudfunctions2_function.budget_shutoff.service_config[0].service
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.budget_shutoff.email}"
}
