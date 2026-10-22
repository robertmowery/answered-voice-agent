variable "project_id" {
  type        = string
  description = "A Google Cloud project you own, with billing enabled. Create a fresh one for this series."
}

variable "billing_account" {
  type        = string
  description = "Billing account ID linked to the project, such as 000000-000000-000000. Not a secret, but keep it in terraform.tfvars, which git ignores."
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "Region for the Cloud Run services and the budget shutoff."
}

variable "budget_usd" {
  type        = number
  default     = 40
  description = "Hard cap in US dollars. At 100 percent the shutoff function unlinks billing from the project."
}

variable "tickets_sheet_id" {
  description = "Optional: ID of the Google Sheet the office reads tickets from (shared with the ticket-worker service account). Empty keeps tickets in Firestore only."
  type        = string
  default     = ""
}

variable "operator_email" {
  description = "Your Google account, allowed to run scripts/seed_workspace.py as the tools-api service account."
  type        = string
  default     = ""
}

variable "dispatch_calendar_id" {
  description = "Calendar ID printed by scripts/seed_workspace.py. Empty uses an in-memory calendar (demo only)."
  type        = string
  default     = ""
}

variable "price_sheet_id" {
  description = "ID of the price-list Google Sheet shared with the tools-api account. Empty uses policy/price_list.csv."
  type        = string
  default     = ""
}

variable "followup_sender" {
  description = "Workspace mailbox the follow-up emails come from, such as office@yourdomain.com."
  type        = string
  default     = ""
}

variable "gmail_delegation" {
  description = "\"on\" once a Workspace admin has granted gmail.send to the tools-api account; otherwise emails go to the outbox."
  type        = string
  default     = "off"
}
