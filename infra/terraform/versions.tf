# Landing zone for The Always-On Agentic Front Office.
# Copyright 2026 Robert H. Mowery III. Licensed under the Apache License, Version 2.0.

terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.6"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region

  # The Budgets API bills its quota to a project; without this it falls back to
  # the gcloud default project, which may not be this one.
  user_project_override = true
  billing_project       = var.project_id
}
