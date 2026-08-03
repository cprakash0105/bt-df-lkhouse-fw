"""EastSide CDH 2.0 — OpenLineage Emitter.

Emits OpenLineage-compatible events to GCS after each pipeline stage.
Events are written to:
    gs://{bucket}/lineage/{table_name}/{stage}_{run_id}.json

Each event captures:
  - Standard OpenLineage envelope (eventType, eventTime, job, run, inputs, outputs)
  - Rich facets: schema, dataQuality, dataSource, columnLineage, rowStats,
                 schemaEvolution, processingEngine, pipelineContext
  - Dagster context (run_id, asset, job) when available via env vars

The /lineage/{dataset} API endpoint reads these events to render the graph.
"""
import json
import os
from datetime import datetime, timezone

from base import log, LogLevel


# ── helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dataset(namespace: str, name: str, facets: dict = None) -> dict:
    d = {"namespace": namespace, "name": name}
    if facets:
        d["facets"] = facets
    return d


def _schema_facet(df) -> dict:
    """Build OpenLineage SchemaDatasetFacet from a Spark DataFrame."""
    try:
        fields = [
            {
                "name": f.name,
                "type": f.dataType.simpleString(),
                "description": f.metadata.get("comment", "") if f.metadata else "",
            }
            for f in df.schema.fields
        ]
        return {
            "_producer": "eastside-cdh2",
            "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/SchemaDatasetFacet.json",
            "fields": fields,
        }
    except Exception:
        return {}


def _dq_facet(dq_stats: dict) -> dict:
    """Build OpenLineage DataQualityMetricsInputDatasetFacet."""
    assertions = []
    for check, result in dq_stats.items():
        assertions.append({
            "assertion": check,
            "success": result.get("passed", True),
            "column": result.get("column"),
        })
    return {
        "_producer": "eastside-cdh2",
        "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/DataQualityMetricsInputDatasetFacet.json",
        "rowCount": dq_stats.get("_row_count", 0),
        "bytes": dq_stats.get("_bytes", 0),
        "columnMetrics": dq_stats.get("_column_metrics", {}),
        "assertions": assertions,
    }


def _column_lineage_facet(input_cols: list, output_cols: list, stage: str) -> dict:
    """Build OpenLineage ColumnLineageDatasetFacet — maps output cols to input cols."""
    fields = {}
    input_set = set(input_cols)
    for col in output_cols:
        # Metadata cols added by the engine
        if col.startswith("_"):
            fields[col] = {
                "inputFields": [],
                "transformationType": "IDENTITY",
                "transformationDescription": f"Added by {stage} engine",
            }
        elif col == "row_hash":
            fields[col] = {
                "inputFields": [{"namespace": "eastside", "name": col, "field": c}
                                for c in input_cols if not c.startswith("_")],
                "transformationType": "HASH",
                "transformationDescription": "SHA256 of business key fields",
            }
        elif col in input_set:
            fields[col] = {
                "inputFields": [{"namespace": "eastside", "name": col, "field": col}],
                "transformationType": "IDENTITY",
                "transformationDescription": "Pass-through",
            }
        else:
            fields[col] = {
                "inputFields": [],
                "transformationType": "DERIVED",
                "transformationDescription": f"Derived in {stage}",
            }
    return {
        "_producer": "eastside-cdh2",
        "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/ColumnLineageDatasetFacet.json",
        "fields": fields,
    }


# ── main emitter ─────────────────────────────────────────────────────────────

def emit_lineage(
    config: dict,
    table_name: str,
    stage: str,                    # bronze | silver | gold
    run_id: str,
    status: str,                   # COMPLETE | FAIL | START
    # Dataset info
    input_namespace: str = None,
    input_name: str = None,
    output_namespace: str = None,
    output_name: str = None,
    # Schema
    input_df=None,
    output_df=None,
    # Row stats
    input_row_count: int = None,
    output_row_count: int = None,
    rejected_count: int = None,
    quarantined_count: int = None,
    deduped_count: int = None,
    # Schema evolution
    schema_changes: dict = None,
    # DQ
    dq_stats: dict = None,
    # Source details
    source_path: str = None,
    source_format: str = None,
    version: str = None,
    batch_id: str = None,
    # Error
    error_message: str = None,
    # Dagster context (injected by assets.py after the fact)
    dagster_run_id: str = None,
    dagster_job_name: str = None,
    dagster_asset_name: str = None,
    dataproc_job_id: str = None,
):
    """Emit a rich OpenLineage event to GCS.

    Called from:
      - bronze.py  → stage='bronze'
      - silver.py  → stage='silver'
      - gold.py    → stage='gold'
      - assets.py  → enriches existing event with Dagster context
    """
    pipeline = config["pipeline"]
    bucket_name = pipeline["bucket"]
    project_id = pipeline.get("project_id", "")
    region = pipeline.get("region", "europe-west2")

    # ── Resolve dataset namespaces/names from pipeline config ────────────────
    landing_prefix = pipeline.get("landing_prefix", "landing")
    catalog = pipeline.get("catalog", "lkhouse_eastside")
    bronze_ns = pipeline.get("bronze_namespace", "bronze")
    silver_ns = pipeline.get("silver_namespace", "silver")
    bq_dataset = pipeline.get("dataproduct_dataset", "eastside_dataproduct")

    stage_inputs = {
        "bronze": _dataset(
            namespace=f"gs://{bucket_name}",
            name=f"{landing_prefix}/{table_name}" + (f"/{version}" if version else ""),
            facets={
                "dataSource": {
                    "_producer": "eastside-cdh2",
                    "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/DatasourceDatasetFacet.json",
                    "name": f"GCS landing — {table_name}",
                    "uri": f"gs://{bucket_name}/{landing_prefix}/{table_name}",
                },
                **({"schema": _schema_facet(input_df)} if input_df is not None else {}),
            },
        ),
        "silver": _dataset(
            namespace=f"iceberg://{catalog}",
            name=f"{bronze_ns}.{table_name}",
            facets={
                **({"schema": _schema_facet(input_df)} if input_df is not None else {}),
            },
        ),
        "gold": _dataset(
            namespace=f"iceberg://{catalog}",
            name=f"{silver_ns}.{table_name}",
            facets={
                **({"schema": _schema_facet(input_df)} if input_df is not None else {}),
            },
        ),
    }

    stage_outputs = {
        "bronze": _dataset(
            namespace=f"iceberg://{catalog}",
            name=f"{bronze_ns}.{table_name}",
            facets={
                **({"schema": _schema_facet(output_df)} if output_df is not None else {}),
            },
        ),
        "silver": _dataset(
            namespace=f"iceberg://{catalog}",
            name=f"{silver_ns}.{table_name}",
            facets={
                **({"schema": _schema_facet(output_df)} if output_df is not None else {}),
            },
        ),
        "gold": _dataset(
            namespace=f"bigquery://{project_id}",
            name=f"{bq_dataset}.{table_name}",
            facets={
                **({"schema": _schema_facet(output_df)} if output_df is not None else {}),
            },
        ),
    }

    inp = stage_inputs.get(stage, _dataset(input_namespace or "unknown", input_name or table_name))
    out = stage_outputs.get(stage, _dataset(output_namespace or "unknown", output_name or table_name))

    # ── Column lineage ───────────────────────────────────────────────────────
    if input_df is not None and output_df is not None:
        col_lineage = _column_lineage_facet(
            input_df.columns, output_df.columns, stage
        )
        out.setdefault("facets", {})["columnLineage"] = col_lineage

    # ── Row stats facet (custom) ─────────────────────────────────────────────
    row_stats = {k: v for k, v in {
        "inputRows": input_row_count,
        "outputRows": output_row_count,
        "rejectedRows": rejected_count,
        "quarantinedRows": quarantined_count,
        "dedupedRows": deduped_count,
    }.items() if v is not None}

    # ── Schema evolution facet (custom) ──────────────────────────────────────
    schema_evo_facet = None
    if schema_changes and any(schema_changes.values()):
        schema_evo_facet = {
            "_producer": "eastside-cdh2",
            "addedColumns": list(schema_changes.get("add_columns", {}).keys()),
            "droppedColumns": schema_changes.get("dropped_columns", []),
            "typeChanges": schema_changes.get("type_changes", {}),
            "layer": stage,
        }

    # ── DQ facet ─────────────────────────────────────────────────────────────
    dq_facet_data = _dq_facet(dq_stats) if dq_stats else None

    # ── Processing engine facet ──────────────────────────────────────────────
    processing_engine = {
        "_producer": "eastside-cdh2",
        "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/ProcessingEngineRunFacet.json",
        "version": "3.x",
        "name": "Apache Spark on Dataproc",
        "openlineageAdapterVersion": "eastside-cdh2-1.0",
    }

    # ── Pipeline context facet (custom) ──────────────────────────────────────
    pipeline_context = {
        "_producer": "eastside-cdh2",
        "pipeline": "eastside",
        "stage": stage,
        "table": table_name,
        "layer_order": ["landing", "bronze", "silver", "gold"],
        "catalog": catalog,
        "project": project_id,
        "region": region,
        "bucket": bucket_name,
        **({"sourceFormat": source_format} if source_format else {}),
        **({"landingVersion": version} if version is not None else {}),
        **({"batchId": batch_id} if batch_id else {}),
        **({"sourcePath": source_path} if source_path else {}),
    }

    # ── Dagster context facet (custom) ───────────────────────────────────────
    dagster_context = {k: v for k, v in {
        "dagsterRunId": dagster_run_id or os.environ.get("DAGSTER_RUN_ID"),
        "dagsterJobName": dagster_job_name or os.environ.get("DAGSTER_JOB_NAME"),
        "dagsterAssetName": dagster_asset_name or os.environ.get("DAGSTER_ASSET_NAME"),
        "dataprocJobId": dataproc_job_id or os.environ.get("DATAPROC_JOB_ID"),
    }.items() if v}

    # ── Assemble run facets ──────────────────────────────────────────────────
    run_facets = {
        "processingEngine": processing_engine,
        "pipelineContext": pipeline_context,
    }
    if dagster_context:
        run_facets["dagsterContext"] = dagster_context
    if error_message:
        run_facets["errorMessage"] = {
            "_producer": "eastside-cdh2",
            "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/ErrorMessageRunFacet.json",
            "message": error_message,
            "programmingLanguage": "Python",
        }

    # ── Assemble job facets ──────────────────────────────────────────────────
    job_facets = {
        "jobType": {
            "_producer": "eastside-cdh2",
            "_schemaURL": "https://openlineage.io/spec/facets/2-0-2/JobTypeJobFacet.json",
            "processingType": "BATCH",
            "integration": "SPARK",
            "jobType": f"EASTSIDE_{stage.upper()}",
        },
        "sourceCode": {
            "_producer": "eastside-cdh2",
            "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/SourceCodeLocationJobFacet.json",
            "type": "GCS",
            "url": f"gs://{bucket_name}/engine/{stage}.py",
        },
    }

    # ── Assemble input/output facets ─────────────────────────────────────────
    if row_stats:
        out.setdefault("facets", {})["rowStats"] = {
            "_producer": "eastside-cdh2",
            **row_stats,
        }
    if schema_evo_facet:
        out.setdefault("facets", {})["schemaEvolution"] = schema_evo_facet
    if dq_facet_data:
        inp.setdefault("facets", {})["dataQuality"] = dq_facet_data

    # ── Final OpenLineage event ──────────────────────────────────────────────
    event = {
        "eventType": status,           # START | COMPLETE | FAIL
        "eventTime": _now_iso(),
        "producer": f"gs://{bucket_name}/engine/{stage}.py",
        "schemaURL": "https://openlineage.io/spec/1-0-5/OpenLineage.json",
        "job": {
            "namespace": "eastside",
            "name": f"{stage}.{table_name}",
            "facets": job_facets,
        },
        "run": {
            "runId": run_id,
            "facets": run_facets,
        },
        "inputs": [inp],
        "outputs": [out],
    }

    # ── Write to GCS ─────────────────────────────────────────────────────────
    blob_path = f"lineage/{table_name}/{stage}_{run_id}_{status.lower()}.json"
    try:
        from google.cloud import storage as gcs_storage
        client = gcs_storage.Client()
        client.bucket(bucket_name).blob(blob_path).upload_from_string(
            json.dumps(event, indent=2, default=str),
            content_type="application/json",
        )
        log("lineage", f"[{table_name}] Emitted {status} event → gs://{bucket_name}/{blob_path}")
    except Exception as e:
        log("lineage", f"[{table_name}] Failed to emit lineage (non-fatal): {e}", LogLevel.WARN)


def enrich_lineage_with_dagster(
    config: dict,
    table_name: str,
    stage: str,
    run_id: str,
    dagster_run_id: str,
    dagster_job_name: str,
    dagster_asset_name: str,
    dataproc_job_id: str,
):
    """Read the COMPLETE event written by the engine and patch in Dagster context.
    Called from assets.py after submit_and_wait() returns.
    """
    pipeline = config["pipeline"]
    bucket_name = pipeline["bucket"]
    blob_path = f"lineage/{table_name}/{stage}_{run_id}_complete.json"

    try:
        from google.cloud import storage as gcs_storage
        client = gcs_storage.Client()
        blob = client.bucket(bucket_name).blob(blob_path)
        if not blob.exists():
            log("lineage", f"[{table_name}] No COMPLETE event found at {blob_path} — skipping enrichment", LogLevel.WARN)
            return

        event = json.loads(blob.download_as_text())
        event["run"]["facets"].setdefault("dagsterContext", {}).update({
            "dagsterRunId": dagster_run_id,
            "dagsterJobName": dagster_job_name,
            "dagsterAssetName": dagster_asset_name,
            "dataprocJobId": dataproc_job_id,
            "enrichedAt": _now_iso(),
        })
        blob.upload_from_string(
            json.dumps(event, indent=2, default=str),
            content_type="application/json",
        )
        log("lineage", f"[{table_name}] Enriched lineage event with Dagster context")
    except Exception as e:
        log("lineage", f"[{table_name}] Lineage enrichment failed (non-fatal): {e}", LogLevel.WARN)
