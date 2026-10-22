# Part 6: Cloud DLP templates CX Agent Studio uses to redact transcripts,
# conversation logs and exports, so a card number a caller reads out never
# lands in a log a person can open. The templates must live in the app's
# location ("us"); CX Agent Studio rejects templates in "global".

resource "google_project_service" "dlp" {
  service            = "dlp.googleapis.com"
  disable_on_destroy = false
}

resource "google_data_loss_prevention_inspect_template" "transcripts" {
  parent       = "projects/${var.project_id}/locations/us"
  display_name = "Brightwater transcript inspection"
  description  = "Payment cards and SSNs in caller speech"

  inspect_config {
    info_types {
      name = "CREDIT_CARD_NUMBER"
    }
    info_types {
      name = "CREDIT_CARD_TRACK_NUMBER"
    }
    info_types {
      name = "US_SOCIAL_SECURITY_NUMBER"
    }
    # DLP has no built-in type for a card's expiry date or security code, and the
    # first redacted transcript kept both ("expires 12/29, code 123").
    custom_info_types {
      info_type {
        name = "CARD_EXPIRY"
      }
      regex {
        pattern = "\\b(?:0[1-9]|1[0-2])\\s?/\\s?(?:\\d{2}|20\\d{2})\\b"
      }
      likelihood = "LIKELY"
    }
    custom_info_types {
      info_type {
        name = "CARD_SECURITY_CODE"
      }
      regex {
        pattern = "(?i)\\b(?:cvv|cvc|security code|code)\\s*:?\\s*\\d{3,4}\\b"
      }
      likelihood = "LIKELY"
    }
    min_likelihood = "POSSIBLE"
  }

  depends_on = [google_project_service.dlp]
}

resource "google_data_loss_prevention_deidentify_template" "transcripts" {
  parent       = "projects/${var.project_id}/locations/us"
  display_name = "Brightwater transcript redaction"
  description  = "Replace each finding with its type, like [CREDIT_CARD_NUMBER]"

  deidentify_config {
    info_type_transformations {
      transformations {
        primitive_transformation {
          replace_with_info_type_config = true
        }
      }
    }
  }

  depends_on = [google_project_service.dlp]
}

# CX Agent Studio calls DLP as its service agent.
resource "google_project_iam_member" "ces_uses_dlp" {
  project = var.project_id
  role    = "roles/dlp.user"
  member  = "serviceAccount:${local.ces_service_agent}"
}

output "dlp_inspect_template" {
  value = google_data_loss_prevention_inspect_template.transcripts.id
}

output "dlp_deidentify_template" {
  value = google_data_loss_prevention_deidentify_template.transcripts.id
}
