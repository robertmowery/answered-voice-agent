# Part 3: the tools API reads and writes Brightwater's Google Workspace.
#
# No user's password or key is involved. The dispatch calendar belongs to the
# tools-api service account and is shared with the office. The price list is
# a sheet the office shares with that account as a reader. Email is the only
# piece that needs a Workspace admin: domain-wide delegation of one scope,
# gmail.send, to this account. Until that grant exists, GMAIL_DELEGATION stays
# "off" and follow-up emails wait in a Firestore outbox for a person.

resource "google_project_service" "part3" {
  for_each           = toset(["calendar-json.googleapis.com", "gmail.googleapis.com", "drive.googleapis.com"])
  service            = each.value
  disable_on_destroy = false
}

# The outbox, while email delegation is off.
resource "google_project_iam_member" "tools_api_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.tools_api.email}"
}

# Cloud Run has no key file. To act as the office mailbox through delegation, the
# service signs its own token request through the IAM API, which needs this.
resource "google_service_account_iam_member" "tools_api_signs_for_itself" {
  service_account_id = google_service_account.tools_api.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.tools_api.email}"
}

# Lets the operator run scripts/seed_workspace.py as the tools-api account, once.
resource "google_service_account_iam_member" "operator_impersonates_tools_api" {
  count              = var.operator_email == "" ? 0 : 1
  service_account_id = google_service_account.tools_api.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "user:${var.operator_email}"
}
