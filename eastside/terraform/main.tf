# ============================================================
# EastSide CDH 2.0 — Terraform Infrastructure
# GCS bucket, BigLake Metastore catalog, BigQuery dataset, IAM
# ============================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

variable "project_id" {
  description = "GCP project ID"
  default     = "bt-df-lkhouse"
}

variable "region" {
  description = "GCP region"
  default     = "europe-west2"
}

variable "bucket_name" {
  description = "GCS bucket for EastSide lakehouse"
  default     = "eastside-lakehouse"
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ============================================================
# GCS Bucket
# ============================================================

resource "google_storage_bucket" "lakehouse" {
  name          = var.bucket_name
  location      = var.region
  force_destroy = false

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  labels = {
    environment = "dev"
    team        = "data-engineering"
    project     = "eastside"
  }
}

# Landing, bronze, silver folder markers
resource "google_storage_bucket_object" "landing_marker" {
  name    = "landing/.keep"
  bucket  = google_storage_bucket.lakehouse.name
  content = ""
}

resource "google_storage_bucket_object" "bronze_marker" {
  name    = "bronze/.keep"
  bucket  = google_storage_bucket.lakehouse.name
  content = ""
}

resource "google_storage_bucket_object" "silver_marker" {
  name    = "silver/.keep"
  bucket  = google_storage_bucket.lakehouse.name
  content = ""
}

resource "google_storage_bucket_object" "config_marker" {
  name    = "config/.keep"
  bucket  = google_storage_bucket.lakehouse.name
  content = ""
}

# ============================================================
# BigLake Metastore (BLMS) — Iceberg Catalog
# ============================================================

resource "google_biglake_catalog" "eastside" {
  name     = "eastside"
  location = var.region
}

resource "google_biglake_database" "bronze" {
  name    = "bronze"
  catalog = google_biglake_catalog.eastside.id
  type    = "HIVE"

  hive_options {
    location_uri = "gs://${var.bucket_name}/bronze"
  }
}

resource "google_biglake_database" "silver" {
  name    = "silver"
  catalog = google_biglake_catalog.eastside.id
  type    = "HIVE"

  hive_options {
    location_uri = "gs://${var.bucket_name}/silver"
  }
}

# ============================================================
# BigQuery Dataset (Gold Layer)
# ============================================================

resource "google_bigquery_dataset" "dataproduct" {
  dataset_id  = "eastside_dataproduct"
  location    = var.region
  description = "EastSide CDH 2.0 — Gold layer data products"

  labels = {
    environment = "dev"
    team        = "data-engineering"
    layer       = "gold"
  }

  default_table_expiration_ms = null

  access {
    role          = "OWNER"
    special_group = "projectOwners"
  }

  access {
    role          = "READER"
    special_group = "projectReaders"
  }
}

# ============================================================
# Cloud KMS (for PII encryption in silver)
# ============================================================

resource "google_kms_key_ring" "eastside" {
  name     = "eastside-keyring"
  location = var.region
}

resource "google_kms_crypto_key" "pii_encryption" {
  name     = "pii-encryption-key"
  key_ring = google_kms_key_ring.eastside.id
  purpose  = "ENCRYPT_DECRYPT"

  rotation_period = "7776000s" # 90 days

  labels = {
    usage = "pii-protection"
  }
}

# ============================================================
# Service Account for Dataproc jobs
# ============================================================

resource "google_service_account" "dataproc_sa" {
  account_id   = "eastside-dataproc"
  display_name = "EastSide Dataproc Service Account"
}

# GCS access
resource "google_storage_bucket_iam_member" "dataproc_gcs" {
  bucket = google_storage_bucket.lakehouse.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.dataproc_sa.email}"
}

# BigQuery access
resource "google_bigquery_dataset_iam_member" "dataproc_bq" {
  dataset_id = google_bigquery_dataset.dataproduct.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.dataproc_sa.email}"
}

# BigLake access
resource "google_project_iam_member" "dataproc_biglake" {
  project = var.project_id
  role    = "roles/biglake.admin"
  member  = "serviceAccount:${google_service_account.dataproc_sa.email}"
}

# KMS access
resource "google_kms_crypto_key_iam_member" "dataproc_kms" {
  crypto_key_id = google_kms_crypto_key.pii_encryption.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.dataproc_sa.email}"
}

# Dataproc worker role
resource "google_project_iam_member" "dataproc_worker" {
  project = var.project_id
  role    = "roles/dataproc.worker"
  member  = "serviceAccount:${google_service_account.dataproc_sa.email}"
}

# ============================================================
# Outputs
# ============================================================

output "bucket_url" {
  value = "gs://${google_storage_bucket.lakehouse.name}"
}

output "catalog_name" {
  value = google_biglake_catalog.eastside.name
}

output "bq_dataset" {
  value = google_bigquery_dataset.dataproduct.dataset_id
}

output "dataproc_sa_email" {
  value = google_service_account.dataproc_sa.email
}

output "kms_key_id" {
  value = google_kms_crypto_key.pii_encryption.id
}
