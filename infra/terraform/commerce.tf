# Part 4: agentic commerce. A UCP business server, public like any storefront
# endpoint, and an ADK commerce agent reachable only by CX Agent Studio over A2A.

locals {
  ucp_server_url     = "https://ucp-server-${data.google_project.this.number}.${var.region}.run.app"
  commerce_agent_url = "https://commerce-agent-${data.google_project.this.number}.${var.region}.run.app"
}

resource "google_project_service" "part4" {
  for_each           = toset(["aiplatform.googleapis.com"])
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "ucp_server" {
  account_id   = "ucp-server"
  display_name = "Brightwater UCP business server"
  depends_on   = [google_project_service.enabled]
}

resource "google_service_account" "commerce_agent" {
  account_id   = "commerce-agent"
  display_name = "Brightwater ADK commerce agent (A2A)"
  depends_on   = [google_project_service.enabled]
}

resource "google_project_iam_member" "ucp_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.ucp_server.email}"
}

# The commerce agent calls Gemini through Vertex AI as itself.
resource "google_project_iam_member" "commerce_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.commerce_agent.email}"
}

resource "google_cloud_run_v2_service" "ucp_server" {
  name                = "ucp-server"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.ucp_server.email
    scaling {
      max_instance_count = 2
    }
    containers {
      image = local.placeholder_image
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "PUBLIC_BASE_URL"
        value = local.ucp_server_url
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
  depends_on = [google_project_service.enabled]
}

# A merchant's UCP endpoint and its payment page are public by design; the
# limits that matter (prices, quantities, order totals) are enforced inside it.
resource "google_cloud_run_v2_service_iam_member" "ucp_public" {
  name     = google_cloud_run_v2_service.ucp_server.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service" "commerce_agent" {
  name                = "commerce-agent"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.commerce_agent.email
    scaling {
      max_instance_count = 2
    }
    containers {
      image = local.placeholder_image
      resources {
        limits = { memory = "2Gi", cpu = "1" }
      }
      env {
        name  = "UCP_SERVER_URL"
        value = local.ucp_server_url
      }
      env {
        name  = "PUBLIC_URL"
        value = local.commerce_agent_url
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "TRUE"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = "global"
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
  depends_on = [google_project_service.part4]
}

# Only CX Agent Studio may call the commerce agent.
resource "google_cloud_run_v2_service_iam_member" "ces_invokes_commerce" {
  name     = google_cloud_run_v2_service.commerce_agent.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.ces_service_agent}"
}

output "ucp_server_url" {
  value = local.ucp_server_url
}

output "commerce_agent_url" {
  description = "Set COMMERCE_AGENT_URL to this before make deploy"
  value       = local.commerce_agent_url
}
