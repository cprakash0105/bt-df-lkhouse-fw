"""Pipeline Monitor — Logs all events to BigQuery audit table.
Tracks: SD interactions, pipeline jobs, DQ results, contract status, errors.
Query: SELECT * FROM lakehouse_dataproduct.pipeline_monitor ORDER BY event_time DESC
"""
import os
import json
from datetime import datetime, timezone
from typing import Optional

try:
    from google.cloud import bigquery
    BQ_AVAILABLE = True
except ImportError:
    BQ_AVAILABLE = False

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
DATASET = "lakehouse_dataproduct"
TABLE = "pipeline_monitor"
FULL_TABLE = f"{PROJECT_ID}.{DATASET}.{TABLE}"

# Schema for the monitor table
SCHEMA = [
    bigquery.SchemaField("event_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("event_time", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("dataset_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("stage", "STRING", mode="REQUIRED"),  # sd_discover, sd_approve, ingest, curate, consume, create_table, tag, contract, error
    bigquery.SchemaField("status", "STRING", mode="REQUIRED"),  # started, succeeded, failed, skipped
    bigquery.SchemaField("records_in", "INTEGER"),
    bigquery.SchemaField("records_out", "INTEGER"),
    bigquery.SchemaField("records_rejected", "INTEGER"),
    bigquery.SchemaField("duration_seconds", "FLOAT"),
    bigquery.SchemaField("job_id", "STRING"),
    bigquery.SchemaField("error_message", "STRING"),
    bigquery.SchemaField("details", "STRING"),  # JSON blob for extra metadata
    bigquery.SchemaField("triggered_by", "STRING"),  # user, cloud_function, manual
]


class PipelineMonitor:
    """Logs pipeline events to BigQuery."""

    def __init__(self):
        self._client = None
        self._table_ensured = False

    def _get_client(self):
        if not BQ_AVAILABLE:
            return None
        if self._client is None:
            self._client = bigquery.Client(project=PROJECT_ID)
        return self._client

    def _ensure_table(self):
        """Create monitor table if not exists."""
        if self._table_ensured:
            return
        client = self._get_client()
        if not client:
            return

        try:
            client.get_table(FULL_TABLE)
        except Exception:
            table = bigquery.Table(FULL_TABLE, schema=SCHEMA)
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field="event_time",
            )
            client.create_table(table)
            print(f"[Monitor] Created table: {FULL_TABLE}")

        self._table_ensured = True

    def log_event(self, dataset_name: str, stage: str, status: str,
                  records_in: int = None, records_out: int = None,
                  records_rejected: int = None, duration_seconds: float = None,
                  job_id: str = None, error_message: str = None,
                  details: dict = None, triggered_by: str = "cloud_function"):
        """Log a pipeline event."""
        client = self._get_client()
        if not client:
            print(f"[Monitor] BQ not available, event: {dataset_name}/{stage}/{status}")
            return

        self._ensure_table()

        import uuid
        row = {
            "event_id": str(uuid.uuid4())[:8],
            "event_time": datetime.now(timezone.utc).isoformat(),
            "dataset_name": dataset_name,
            "stage": stage,
            "status": status,
            "records_in": records_in,
            "records_out": records_out,
            "records_rejected": records_rejected,
            "duration_seconds": duration_seconds,
            "job_id": job_id,
            "error_message": error_message,
            "details": json.dumps(details) if details else None,
            "triggered_by": triggered_by,
        }

        try:
            errors = client.insert_rows_json(FULL_TABLE, [row])
            if errors:
                print(f"[Monitor] Insert error: {errors}")
        except Exception as e:
            print(f"[Monitor] Failed to log: {e}")

    def log_discovery(self, dataset_name: str, num_fields: int,
                      business_app: str = None, pii_count: int = 0):
        """Log SD discovery event."""
        self.log_event(
            dataset_name=dataset_name,
            stage="sd_discover",
            status="succeeded",
            records_in=num_fields,
            details={
                "business_application": business_app,
                "pii_fields_detected": pii_count,
            },
            triggered_by="user",
        )

    def log_approval(self, dataset_name: str, config_path: str = None,
                     contract_path: str = None, new_terms: list = None):
        """Log SD approval event."""
        self.log_event(
            dataset_name=dataset_name,
            stage="sd_approve",
            status="succeeded",
            details={
                "config_gcs_path": config_path,
                "contract_gcs_path": contract_path,
                "new_terms_created": new_terms or [],
            },
            triggered_by="user",
        )

    def log_ingest(self, dataset_name: str, status: str, records: int = None,
                   job_id: str = None, duration: float = None, error: str = None):
        """Log ingest step."""
        self.log_event(
            dataset_name=dataset_name,
            stage="ingest",
            status=status,
            records_in=records,
            records_out=records,
            job_id=job_id,
            duration_seconds=duration,
            error_message=error,
        )

    def log_curate(self, dataset_name: str, status: str, records_in: int = None,
                   records_out: int = None, records_rejected: int = None,
                   job_id: str = None, duration: float = None, error: str = None):
        """Log curate step."""
        self.log_event(
            dataset_name=dataset_name,
            stage="curate",
            status=status,
            records_in=records_in,
            records_out=records_out,
            records_rejected=records_rejected,
            job_id=job_id,
            duration_seconds=duration,
            error_message=error,
        )

    def log_consume(self, dataset_name: str, status: str, records_out: int = None,
                    duration: float = None, error: str = None):
        """Log consume step."""
        self.log_event(
            dataset_name=dataset_name,
            stage="consume",
            status=status,
            records_out=records_out,
            duration_seconds=duration,
            error_message=error,
        )

    def log_error(self, dataset_name: str, stage: str, error_message: str):
        """Log an error."""
        self.log_event(
            dataset_name=dataset_name,
            stage=stage,
            status="failed",
            error_message=error_message,
        )

    def get_status(self, dataset_name: str) -> list:
        """Get pipeline status for a dataset."""
        client = self._get_client()
        if not client:
            return []

        query = f"""
        SELECT stage, status, records_in, records_out, records_rejected,
               duration_seconds, event_time, error_message
        FROM `{FULL_TABLE}`
        WHERE dataset_name = '{dataset_name}'
        ORDER BY event_time DESC
        LIMIT 20
        """
        try:
            results = client.query(query).result()
            return [dict(row) for row in results]
        except Exception as e:
            print(f"[Monitor] Query failed: {e}")
            return []

    def get_summary(self) -> list:
        """Get summary of all datasets."""
        client = self._get_client()
        if not client:
            return []

        query = f"""
        SELECT
            dataset_name,
            MAX(CASE WHEN stage = 'sd_approve' THEN event_time END) AS approved_at,
            MAX(CASE WHEN stage = 'ingest' AND status = 'succeeded' THEN event_time END) AS ingested_at,
            MAX(CASE WHEN stage = 'curate' AND status = 'succeeded' THEN event_time END) AS curated_at,
            MAX(CASE WHEN stage = 'consume' AND status = 'succeeded' THEN event_time END) AS consumed_at,
            MAX(CASE WHEN stage = 'curate' AND status = 'succeeded' THEN records_out END) AS last_record_count,
            COUNTIF(status = 'failed') AS total_failures
        FROM `{FULL_TABLE}`
        GROUP BY dataset_name
        ORDER BY approved_at DESC
        """
        try:
            results = client.query(query).result()
            return [dict(row) for row in results]
        except Exception as e:
            print(f"[Monitor] Summary query failed: {e}")
            return []
