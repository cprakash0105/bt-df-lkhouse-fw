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

# --- Bootstrap ---
resource "google_project_service" "resourcemanager" {
  service            = "cloudresourcemanager.googleapis.com"
  disable_on_destroy = false
}

# --- APIs ---
resource "google_project_service" "apis" {
  for_each = toset([
    "storage.googleapis.com",
    "bigquery.googleapis.com",
    "bigqueryconnection.googleapis.com",
    "biglake.googleapis.com",
    "dataproc.googleapis.com",
    "iam.googleapis.com",
    "compute.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
  depends_on         = [google_project_service.resourcemanager]
}

# --- GCS Bucket ---
resource "google_storage_bucket" "lakehouse" {
  name          = "${var.project_id}-lakehouse"
  location      = var.region
  storage_class = "STANDARD"
  force_destroy = true

  uniform_bucket_level_access = true
}

resource "google_storage_bucket_object" "folders" {
  for_each = toset(["landing/", "reservoir/", "ccn/", "dataproduct/", "spark/", "contracts/"])
  name     = each.value
  bucket   = google_storage_bucket.lakehouse.name
  content  = " "
}

# --- Service Account ---
resource "google_service_account" "spark_sa" {
  account_id   = "schema-poc-spark"
  display_name = "Schema POC - Dataproc Serverless"
}

resource "google_project_iam_member" "spark_dataproc_worker" {
  project = var.project_id
  role    = "roles/dataproc.worker"
  member  = "serviceAccount:${google_service_account.spark_sa.email}"
}

resource "google_storage_bucket_iam_member" "spark_bucket" {
  bucket = google_storage_bucket.lakehouse.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.spark_sa.email}"
}

resource "google_project_iam_member" "spark_biglake" {
  project = var.project_id
  role    = "roles/biglake.admin"
  member  = "serviceAccount:${google_service_account.spark_sa.email}"
}

resource "google_project_iam_member" "spark_bq" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.spark_sa.email}"
}

resource "google_project_iam_member" "spark_sa_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${google_service_account.spark_sa.email}"
}

# --- BigLake Metastore Catalog ---
resource "google_biglake_catalog" "lakehouse" {
  name     = "lakehouse"
  location = var.region
  depends_on = [google_project_service.apis["biglake.googleapis.com"]]
}

resource "google_biglake_database" "reservoir" {
  name    = "reservoir"
  catalog = google_biglake_catalog.lakehouse.id
  type    = "HIVE"
  hive_options {
    location_uri = "gs://${google_storage_bucket.lakehouse.name}/reservoir"
    parameters   = {}
  }
}

resource "google_biglake_database" "ccn" {
  name    = "ccn"
  catalog = google_biglake_catalog.lakehouse.id
  type    = "HIVE"
  hive_options {
    location_uri = "gs://${google_storage_bucket.lakehouse.name}/ccn"
    parameters   = {}
  }
}

resource "google_biglake_database" "dataproduct" {
  name    = "dataproduct"
  catalog = google_biglake_catalog.lakehouse.id
  type    = "HIVE"
  hive_options {
    location_uri = "gs://${google_storage_bucket.lakehouse.name}/dataproduct"
    parameters   = {}
  }
}

# --- BigQuery Connection ---
resource "google_bigquery_connection" "biglake" {
  connection_id = "biglake-conn"
  location      = var.region
  cloud_resource {}
  depends_on = [google_project_service.apis["bigqueryconnection.googleapis.com"]]
}

resource "google_storage_bucket_iam_member" "bq_agent_reader" {
  bucket = google_storage_bucket.lakehouse.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_bigquery_connection.biglake.cloud_resource[0].service_account_id}"
}

# --- Network ---
resource "google_compute_network" "default" {
  name                    = "schema-poc-network"
  auto_create_subnetworks = true
  depends_on              = [google_project_service.apis["compute.googleapis.com"]]
}

resource "google_compute_firewall" "allow_internal" {
  name    = "schema-poc-allow-internal"
  network = google_compute_network.default.name
  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }
  allow {
    protocol = "udp"
    ports    = ["0-65535"]
  }
  allow { protocol = "icmp" }
  source_ranges = ["10.0.0.0/8"]
}

resource "google_compute_router" "router" {
  name    = "schema-poc-router"
  network = google_compute_network.default.name
  region  = var.region
}

resource "google_compute_router_nat" "nat" {
  name                               = "schema-poc-nat"
  router                             = google_compute_router.router.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}
