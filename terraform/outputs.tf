output "bucket_name" {
  value = google_storage_bucket.lakehouse.name
}

output "spark_sa_email" {
  value = google_service_account.spark_sa.email
}

output "blms_catalog" {
  value = google_biglake_catalog.schema_poc.name
}

output "bq_connection_service_agent" {
  value = google_bigquery_connection.biglake.cloud_resource[0].service_account_id
}

output "network" {
  value = google_compute_network.default.name
}

output "submit_job_command" {
  value = "gcloud dataproc batches submit pyspark gs://${google_storage_bucket.lakehouse.name}/spark/bronze_to_silver.py --project=${var.project_id} --region=${var.region} --service-account=${google_service_account.spark_sa.email} --subnet=projects/${var.project_id}/regions/${var.region}/subnetworks/${google_compute_network.default.name} --deps-bucket=gs://${google_storage_bucket.lakehouse.name}/spark/deps --properties=spark.jars.packages=org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.7.1"
}
