# Part 2 onward: the services the agent calls, and the event path behind them.
#
# Terraform owns the service accounts, permissions, topic and subscription, and
# creates each Cloud Run service with a placeholder image. `make services`
# deploys the real code as new revisions; Terraform ignores the image after that.

locals {
  ces_service_agent = "service-${data.google_project.this.number}@gcp-sa-ces.iam.gserviceaccount.com"
  placeholder_image = "us-docker.pkg.dev/cloudrun/container/hello"
}

resource "google_project_service" "part2" {
  for_each           = toset(["firestore.googleapis.com", "sheets.googleapis.com", "secretmanager.googleapis.com"])
  service            = each.value
  disable_on_destroy = false
}

resource "google_firestore_database" "default" {
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.part2]
}

# ----- Identities: one per service, each with only what it needs.

resource "google_service_account" "tools_api" {
  account_id   = "tools-api"
  display_name = "Brightwater tools API (called by the agent)"
  depends_on   = [google_project_service.enabled]
}

resource "google_service_account" "ticket_worker" {
  account_id   = "ticket-worker"
  display_name = "Writes after-hours tickets for the office"
  depends_on   = [google_project_service.enabled]
}

resource "google_service_account" "pubsub_push" {
  account_id   = "pubsub-push"
  display_name = "Signs Pub/Sub push requests to the ticket worker"
  depends_on   = [google_project_service.enabled]
}

# ----- The event path: tools API publishes, Pub/Sub pushes to the worker.

resource "google_pubsub_topic" "tickets" {
  name = "tickets"
  message_storage_policy {
    allowed_persistence_regions = [var.region]
  }
  depends_on = [google_project_service.enabled]
}

resource "google_pubsub_topic" "tickets_dead_letter" {
  name = "tickets-dead-letter"
  message_storage_policy {
    allowed_persistence_regions = [var.region]
  }
  depends_on = [google_project_service.enabled]
}

resource "google_pubsub_topic_iam_member" "tools_api_publishes" {
  topic  = google_pubsub_topic.tickets.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.tools_api.email}"
}

resource "google_project_iam_member" "worker_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.ticket_worker.email}"
}

resource "google_cloud_run_v2_service" "tools_api" {
  name                = "tools-api"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.tools_api.email
    scaling {
      max_instance_count = 3
    }
    containers {
      image = local.placeholder_image
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "TICKETS_TOPIC"
        value = google_pubsub_topic.tickets.name
      }
      env {
        name  = "UCP_SERVER_URL"
        value = local.ucp_server_url
      }
      env {
        name  = "DISPATCH_CALENDAR_ID"
        value = var.dispatch_calendar_id
      }
      env {
        name  = "PRICE_SHEET_ID"
        value = var.price_sheet_id
      }
      env {
        name  = "FOLLOWUP_SENDER"
        value = var.followup_sender
      }
      env {
        name  = "GMAIL_DELEGATION"
        value = var.gmail_delegation
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
  depends_on = [google_project_service.enabled]
}

resource "google_cloud_run_v2_service" "ticket_worker" {
  name                = "ticket-worker"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.ticket_worker.email
    scaling {
      max_instance_count = 2
    }
    containers {
      image = local.placeholder_image
      env {
        name  = "TICKETS_SHEET_ID"
        value = var.tickets_sheet_id
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
  depends_on = [google_project_service.enabled]
}

# Only CX Agent Studio's service agent may call the tools API (ID token auth).
resource "google_cloud_run_v2_service_iam_member" "ces_invokes_tools_api" {
  name     = google_cloud_run_v2_service.tools_api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.ces_service_agent}"
}

# Only Pub/Sub, signing as pubsub-push, may call the worker.
resource "google_cloud_run_v2_service_iam_member" "push_invokes_worker" {
  name     = google_cloud_run_v2_service.ticket_worker.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pubsub_push.email}"
}

resource "google_pubsub_subscription" "tickets_to_worker" {
  name                 = "tickets-to-worker"
  topic                = google_pubsub_topic.tickets.id
  ack_deadline_seconds = 30

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.ticket_worker.uri}/pubsub"
    oidc_token {
      service_account_email = google_service_account.pubsub_push.email
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.tickets_dead_letter.id
    max_delivery_attempts = 10
  }
}

# A dead-letter topic with no subscription drops what it receives. This one keeps
# undeliverable tickets for seven days so a person can replay them.
resource "google_pubsub_subscription" "tickets_dead_letter_hold" {
  name                       = "tickets-dead-letter-hold"
  topic                      = google_pubsub_topic.tickets_dead_letter.id
  message_retention_duration = "604800s"
  expiration_policy {
    ttl = ""
  }
}

# Pub/Sub's own service agent forwards undeliverable messages to the dead-letter topic.
resource "google_pubsub_topic_iam_member" "dead_letter_publisher" {
  topic  = google_pubsub_topic.tickets_dead_letter.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_subscription_iam_member" "dead_letter_subscriber" {
  subscription = google_pubsub_subscription.tickets_to_worker.id
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
