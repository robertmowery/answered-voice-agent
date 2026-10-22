output "budget_topic" {
  value       = google_pubsub_topic.budget_alerts.id
  description = "Budget alerts land here; the shutoff function listens to it."
}

output "budget_shutoff_function" {
  value = google_cloudfunctions2_function.budget_shutoff.name
}

output "tools_api_url" {
  description = "Set TOOLS_API_URL to this before make deploy"
  value       = google_cloud_run_v2_service.tools_api.uri
}

output "ticket_worker_email" {
  description = "Share the office's ticket sheet with this account as an editor"
  value       = google_service_account.ticket_worker.email
}

output "tools_api_email" {
  description = "Share the price-list sheet with this account (reader); grant it gmail.send delegation for email"
  value       = google_service_account.tools_api.email
}

output "tools_api_client_id" {
  description = "The numeric client ID a Workspace admin enters for domain-wide delegation"
  value       = google_service_account.tools_api.unique_id
}
