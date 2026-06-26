terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  default = "bt-df-lkhouse"
}

variable "region" {
  default = "europe-west2"
}

# --- APIs ---
resource "google_project_service" "discovery_apis" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "firestore.googleapis.com",
    "aiplatform.googleapis.com",
    "cloudbuild.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# --- Artifact Registry (container images) ---
resource "google_artifact_registry_repository" "discovery" {
  location      = var.region
  repository_id = "semantic-discovery"
  format        = "DOCKER"
  description   = "Semantic Discovery container images"
  depends_on    = [google_project_service.discovery_apis["artifactregistry.googleapis.com"]]
}

# --- Service Account ---
resource "google_service_account" "discovery_sa" {
  account_id   = "semantic-discovery"
  display_name = "Semantic Discovery Service"
}

# Vertex AI access (embeddings)
resource "google_project_iam_member" "discovery_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.discovery_sa.email}"
}

# Firestore access (knowledge graph)
resource "google_project_iam_member" "discovery_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.discovery_sa.email}"
}

# --- Firestore Database (knowledge graph store) ---
resource "google_firestore_database" "discovery" {
  name        = "semantic-discovery"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
  depends_on  = [google_project_service.discovery_apis["firestore.googleapis.com"]]
}

# --- Cloud Run Service ---
resource "google_cloud_run_v2_service" "discovery" {
  name     = "semantic-discovery"
  location = var.region

  template {
    service_account = google_service_account.discovery_sa.email

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/semantic-discovery/ui:latest"

      ports {
        container_port = 8000
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = var.region
      }
      env {
        name  = "EMBEDDER_MODE"
        value = "vertex"
      }
      env {
        name  = "FIRESTORE_DATABASE"
        value = google_firestore_database.discovery.name
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
  }

  depends_on = [
    google_project_service.discovery_apis["run.googleapis.com"],
    google_artifact_registry_repository.discovery,
  ]
}

# Allow unauthenticated access (for POC - restrict in production)
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.discovery.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Outputs ---
output "service_url" {
  value = google_cloud_run_v2_service.discovery.uri
}

output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/semantic-discovery"
}

output "service_account" {
  value = google_service_account.discovery_sa.email
}
