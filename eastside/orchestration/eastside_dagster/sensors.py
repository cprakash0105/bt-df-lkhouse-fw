"""GCS Landing Sensor — detects new version folders and triggers bronze pipeline.

How it works:
    1. Every 5 minutes, scans gs://eastside-lakehouse/landing/{table}/ for version folders
    2. Compares against watermarks in gs://eastside-lakehouse/bronze/_watermarks/{table}.json
    3. If unprocessed versions found, triggers a bronze run for that table + version

This eliminates manual triggering — data lands, pipeline runs.
"""
import json
from dagster import (
    sensor, RunRequest, RunConfig, SensorEvaluationContext,
    DefaultSensorStatus, SkipReason,
)
from google.cloud import storage
from .assets import BronzeConfig


PROJECT_ID = "bt-df-lkhouse"
BUCKET = "eastside-lakehouse"


def _get_landing_versions(gcs_client, table_name: str) -> list:
    """List all version folders under landing/{table}/."""
    bucket = gcs_client.bucket(BUCKET)
    prefix = f"landing/{table_name}/"
    blobs = bucket.list_blobs(prefix=prefix, delimiter="/")
    _ = list(blobs)  # force iteration to populate prefixes
    versions = []
    for p in blobs.prefixes:
        version = p.rstrip("/").split("/")[-1]
        if version.startswith("v"):
            versions.append(version)
    return sorted(versions)


def _get_processed_versions(gcs_client, table_name: str) -> list:
    """Read watermark to get already-processed versions."""
    bucket = gcs_client.bucket(BUCKET)
    wm_blob = bucket.blob(f"bronze/_watermarks/{table_name}.json")
    if not wm_blob.exists():
        return []
    wm = json.loads(wm_blob.download_as_text())
    return wm.get("processed_versions", [])


def _get_all_table_names(gcs_client) -> list:
    """List all table config files in GCS."""
    bucket = gcs_client.bucket(BUCKET)
    blobs = bucket.list_blobs(prefix="config/tables/")
    return [b.name.split("/")[-1].replace(".yaml", "") for b in blobs if b.name.endswith(".yaml")]


@sensor(
    job_name="bronze_job",
    minimum_interval_seconds=300,  # 5 minutes
    default_status=DefaultSensorStatus.RUNNING,
    description="Scans GCS landing zone for new version folders. Triggers bronze pipeline when new data arrives.",
)
def landing_sensor(context: SensorEvaluationContext):
    """Detect new landing versions and trigger bronze runs."""
    gcs_client = storage.Client(project=PROJECT_ID)
    tables = _get_all_table_names(gcs_client)

    run_requests = []

    for table in tables:
        landing_versions = _get_landing_versions(gcs_client, table)
        processed_versions = _get_processed_versions(gcs_client, table)
        unprocessed = [v for v in landing_versions if v not in processed_versions]

        if unprocessed:
            context.log.info(f"Sensor [{table}]: new versions detected: {unprocessed}")
            for version in unprocessed:
                run_requests.append(
                    RunRequest(
                        run_key=f"{table}_{version}",
                        run_config=RunConfig(
                            ops={"bronze_asset": BronzeConfig(table=table, version=version)}
                        ),
                        tags={
                            "table": table,
                            "version": version,
                            "trigger": "landing_sensor",
                        },
                    )
                )

    if not run_requests:
        return SkipReason("No new landing versions detected")

    return run_requests
