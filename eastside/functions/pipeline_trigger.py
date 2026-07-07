"""EastSide CDH 2.0 — Pipeline Trigger Cloud Function (Gen2).
Triggers when a table config YAML lands in gs://eastside-lakehouse/config/tables/*.yaml.
Submits: bronze.py -> silver.py -> gold.py on lakehouse-cluster.

Trigger: GCS object finalize on gs://eastside-lakehouse/config/tables/*.yaml
Runtime: Python 3.12, 540s timeout, 1GB memory
"""
import os
import time
import yaml
import functions_framework
from google.cloud import storage, dataproc_v1

PROJECT = "bt-df-lkhouse"
REGION = "europe-west2"
BUCKET = "eastside-lakehouse"
CLUSTER = "lakehouse-cluster"
CONFIG = f"gs://{BUCKET}/config/pipeline.yaml"

PY_FILES = [
    f"gs://{BUCKET}/engine/base.py",
    f"gs://{BUCKET}/engine/schema_evolver.py",
]
JARS = [
    "gs://bt-df-lkhouse-lakehouse/spark/iceberg-spark-runtime.jar",
    "gs://bt-df-lkhouse-lakehouse/spark/biglake-catalog.jar",
]

SPARK_PROPERTIES = {
    "spark.sql.catalog.eastside": "org.apache.iceberg.spark.SparkCatalog",
    "spark.sql.catalog.eastside.catalog-impl": "org.apache.iceberg.gcp.biglake.BigLakeCatalog",
    "spark.sql.catalog.eastside.gcp_project": PROJECT,
    "spark.sql.catalog.eastside.gcp_location": REGION,
    "spark.sql.catalog.eastside.blms_catalog": "eastside",
    "spark.sql.catalog.eastside.warehouse": f"gs://{BUCKET}",
    "spark.sql.extensions": "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
}


@functions_framework.cloud_event
def pipeline_trigger(cloud_event):
    """Triggered by GCS object finalize on config/tables/*.yaml"""
    data = cloud_event.data
    bucket_name = data["bucket"]
    file_name = data["name"]

    if not file_name.startswith("config/tables/") or not file_name.endswith(".yaml"):
        print(f"Ignoring: {file_name}")
        return

    table_name = file_name.split("/")[-1].replace(".yaml", "")
    print(f"{'=' * 60}")
    print(f"  EASTSIDE PIPELINE TRIGGERED: {table_name}")
    print(f"{'=' * 60}")

    # Validate config
    gcs = storage.Client(project=PROJECT)
    blob = gcs.bucket(bucket_name).blob(file_name)
    config = yaml.safe_load(blob.download_as_text())
    if "table" not in config:
        print(f"Invalid config: {file_name}")
        return

    # Check landing data exists
    landing_prefix = f"landing/{table_name}/"
    if not list(gcs.bucket(bucket_name).list_blobs(prefix=landing_prefix, max_results=1)):
        print(f"No landing data at gs://{bucket_name}/{landing_prefix} — skipping.")
        return

    # Submit bronze -> silver -> gold
    stages = [
        ("bronze", ["--config", CONFIG, "--table", table_name, "--version", "v1", "--project", PROJECT]),
        ("silver", ["--config", CONFIG, "--table", table_name, "--project", PROJECT]),
        ("gold",   ["--config", CONFIG, "--table", table_name, "--project", PROJECT]),
    ]

    for stage, args in stages:
        print(f"\n[{stage.upper()}] Submitting...")
        job_id = submit_job(stage, table_name, args)
        wait_for_job(job_id)
        print(f"[{stage.upper()}] Complete.")

    print(f"\n{'=' * 60}")
    print(f"  PIPELINE COMPLETE: {table_name}")
    print(f"{'=' * 60}")


def submit_job(stage: str, table_name: str, args: list) -> str:
    client = dataproc_v1.JobControllerClient(
        client_options={"api_endpoint": f"{REGION}-dataproc.googleapis.com:443"}
    )
    job_id = f"eastside-{stage}-{table_name}-{int(time.time()) % 100000}"

    # Gold needs BQ connector jar
    jars = list(JARS)
    if stage == "gold":
        jars.append("gs://spark-lib/bigquery/spark-bigquery-with-dependencies_2.12-0.36.1.jar")

    job = {
        "placement": {"cluster_name": CLUSTER},
        "reference": {"job_id": job_id},
        "pyspark_job": {
            "main_python_file_uri": f"gs://{BUCKET}/engine/{stage}.py",
            "python_file_uris": PY_FILES,
            "jar_file_uris": jars,
            "args": args,
            "properties": SPARK_PROPERTIES,
        },
    }

    client.submit_job(project_id=PROJECT, region=REGION, job=job)
    print(f"  Submitted: {job_id}")
    return job_id


def wait_for_job(job_id: str, timeout: int = 600):
    client = dataproc_v1.JobControllerClient(
        client_options={"api_endpoint": f"{REGION}-dataproc.googleapis.com:443"}
    )
    start = time.time()
    while time.time() - start < timeout:
        job = client.get_job(project_id=PROJECT, region=REGION, job_id=job_id)
        state = job.status.state.name
        if state == "DONE":
            return
        if state in ("ERROR", "CANCELLED"):
            raise RuntimeError(f"Job {job_id} {state}: {job.status.details}")
        time.sleep(10)
    raise RuntimeError(f"Job {job_id} timed out after {timeout}s")
