data "google_project" "this" {
  project_id = var.project_id
}

locals {
  services = [
    "ces.googleapis.com",                # CX Agent Studio (Gemini Enterprise for Customer Experience)
    "dialogflow.googleapis.com",         # Telephony plumbing shared with Conversational Agents
    "cloudquotas.googleapis.com",        # Read and raise the per-minute token quota
    "billingbudgets.googleapis.com",     # The budget
    "cloudbilling.googleapis.com",       # The shutoff unlinks billing through this API
    "pubsub.googleapis.com",             # Budget alerts
    "cloudfunctions.googleapis.com",     # The shutoff function
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "eventarc.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
  ]
}

resource "google_project_service" "enabled" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}
