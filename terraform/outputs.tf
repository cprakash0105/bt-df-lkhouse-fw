output "bucket_name" {
  value = google_storage_bucket.lakehouse.name
}

output "spark_sa_email" {
  value = google_service_account.spark_sa.email
}

output "blms_catalog" {
  value = google_biglake_catalog.lakehouse.name
}

output "ccn_linked_dataset" {
  value = google_bigquery_dataset.ccn_linked.dataset_id
}

output "dataproduct_dataset" {
  value = google_bigquery_dataset.dataproduct.dataset_id
}

output "bq_connection_service_agent" {
  value = google_bigquery_connection.biglake.cloud_resource[0].service_account_id
}
