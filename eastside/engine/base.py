"""EastSide CDH 2.0 — Base module.
Spark session, config loading, structured logging.
Reuses patterns from bt-df-lkhouse-fw but adapted for bronze/silver/gold layers.
"""
import os
import sys
import yaml
import argparse
import traceback
import time
from datetime import datetime
from functools import wraps

BANNER = """
╔════════════════════════════════════════════════════════════╗
║  ███████╗ █████╗ ███████╗████████╗███████╗██╗██████╗ ███████╗  ║
║  ██╔════╝██╔══██╗██╔════╝╚══██╔══╝██╔════╝██║██╔══██╗██╔════╝  ║
║  █████╗  ███████║███████╗   ██║   ███████╗██║██║  ██║█████╗    ║
║  ██╔══╝  ██╔══██║╚════██║   ██║   ╚════██║██║██║  ██║██╔══╝    ║
║  ███████╗██║  ██║███████║   ██║   ███████║██║██████╔╝███████╗  ║
║  ╚══════╝╚═╝  ╚═╝╚══════╝   ╚═╝   ╚══════╝╚═╝╚═════╝ ╚══════╝  ║
║                                                            ║
║  CDH 2.0 — Config-driven Lakehouse                         ║
║  Landing → Bronze(Iceberg) → Silver(Iceberg) → Gold(BQ)   ║
╚════════════════════════════════════════════════════════════╝
"""


# ============================================================
# LOGGING
# ============================================================

class LogLevel:
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"

_log_lines = []


def log(stage, message, level=LogLevel.INFO):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    prefix = {"INFO": "ℹ️ ", "WARN": "⚠️ ", "ERROR": "❌"}.get(level, "  ")
    print(f"  {prefix} [{ts}] [{stage}] {message}")
    _log_lines.append({"ts": ts, "level": level, "stage": stage, "msg": message})


def log_header(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def log_error(stage, message, exception=None):
    log(stage, message, LogLevel.ERROR)
    if exception:
        log(stage, f"  {type(exception).__name__}: {exception}", LogLevel.ERROR)


def log_summary(stage, results):
    log_header(f"{stage.upper()} SUMMARY")
    for table, status in results.items():
        icon = "✅" if status == "SUCCESS" else "❌" if status == "FAILED" else "⏭️"
        log(stage, f"{icon} {table}: {status}")
    s = sum(1 for v in results.values() if v == "SUCCESS")
    f = sum(1 for v in results.values() if v == "FAILED")
    log(stage, f"Total: {len(results)} | Success: {s} | Failed: {f}")


def flush_logs_to_gcs(stage, config):
    import json as _json
    try:
        from google.cloud import storage as gcs
        if not _log_lines:
            return
        bucket_name = config["pipeline"]["bucket"]
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        blob_path = f"logs/{stage}/{run_id}.jsonl"
        content = "\n".join(_json.dumps(l) for l in _log_lines)
        client = gcs.Client()
        bucket = client.bucket(bucket_name)
        bucket.blob(blob_path).upload_from_string(content, content_type="application/json")
        log("logs", f"Persisted {len(_log_lines)} lines → gs://{bucket_name}/{blob_path}")
    except Exception as e:
        print(f"  ⚠️  Log persistence failed (non-fatal): {e}")


# ============================================================
# SPARK SESSION
# ============================================================

def get_spark(app_name):
    from pyspark.sql import SparkSession
    log("spark", f"Creating session: eastside-{app_name}")
    spark = SparkSession.builder.appName(f"eastside-{app_name}").getOrCreate()
    log("spark", f"Session created (Spark {spark.version})")
    return spark


# ============================================================
# CONFIG LOADING
# ============================================================

def load_config(config_path):
    log("config", f"Loading: {config_path}")
    if config_path.startswith("gs://"):
        from google.cloud import storage as gcs
        parts = config_path.replace("gs://", "").split("/", 1)
        client = gcs.Client()
        blob = client.bucket(parts[0]).blob(parts[1])
        config = yaml.safe_load(blob.download_as_text())
        prefix = parts[1].rsplit("/", 1)[0]
        config["tables"] = _load_tables_gcs(client, parts[0], f"{prefix}/tables/")
    else:
        with open(config_path) as f:
            config = yaml.safe_load(f)
        config_dir = os.path.dirname(config_path)
        config["tables"] = _load_tables_disk(config_dir)

    log("config", f"Loaded {len(config['tables'])} tables")
    return config


def _load_tables_disk(config_dir):
    import glob
    tables = {}
    tables_dir = os.path.join(config_dir, "tables")
    if not os.path.isdir(tables_dir):
        return tables
    for f in sorted(glob.glob(os.path.join(tables_dir, "*.yaml"))):
        tc = yaml.safe_load(open(f))
        tables[tc["table"]] = tc
        log("config", f"  ✅ {tc['table']}")
    return tables


def _load_tables_gcs(client, bucket_name, prefix):
    tables = {}
    bucket = client.bucket(bucket_name)
    for blob in bucket.list_blobs(prefix=prefix):
        if blob.name.endswith(".yaml"):
            tc = yaml.safe_load(blob.download_as_text())
            tables[tc["table"]] = tc
            log("config", f"  ✅ {tc['table']}")
    return tables


def get_table_config(config, table_name):
    tables = config.get("tables", {})
    if table_name not in tables:
        raise ValueError(f"Table '{table_name}' not found. Available: {list(tables.keys())}")
    return tables[table_name]


def get_all_tables(config):
    return list(config.get("tables", {}).keys())


# ============================================================
# CLI
# ============================================================

def parse_args(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--config", required=True, help="Path to pipeline.yaml (local or gs://)")
    parser.add_argument("--table", help="Single table to process")
    parser.add_argument("--version", default=None, help="Data version (e.g. v2). Defaults to latest in landing.")
    parser.add_argument("--all", action="store_true", help="Process all tables")
    parser.add_argument("--project", help="GCP project ID override")
    parser.add_argument("--bucket", help="GCS bucket override")
    return parser.parse_args()


def resolve_latest_version(config, table_name):
    """Scan GCS landing prefix and return the latest version folder (e.g. v3).
    Falls back to 'v1' if nothing found."""
    try:
        from google.cloud import storage as gcs
        pipeline = config["pipeline"]
        bucket_name = pipeline["bucket"]
        prefix = f"{pipeline.get('landing_prefix', 'landing')}/{table_name}/"
        client = gcs.Client(project=pipeline.get("project_id", "bt-df-lkhouse"))
        blobs = client.list_blobs(bucket_name, prefix=prefix, delimiter="/")
        list(blobs)  # consume to populate prefixes
        versions = []
        for p in blobs.prefixes:
            folder = p.rstrip("/").split("/")[-1]  # e.g. "v2"
            if folder.startswith("v") and folder[1:].isdigit():
                versions.append(folder)
        if versions:
            latest = sorted(versions, key=lambda v: int(v[1:]))[-1]
            log("config", f"Latest version for {table_name}: {latest}")
            return latest
    except Exception as e:
        log("config", f"Version auto-detect failed for {table_name}: {e}", LogLevel.WARN)
    return "v1"


def resolve_pipeline_vars(config, args):
    pipeline = config["pipeline"]
    project_id = args.project or os.environ.get("PROJECT_ID", pipeline.get("project_id", ""))
    region = os.environ.get("REGION", pipeline.get("region", "europe-west2"))
    bucket = args.bucket or os.environ.get("BUCKET", pipeline.get("bucket", ""))

    resolved = {}
    for k, v in pipeline.items():
        if isinstance(v, str):
            resolved[k] = v.replace("${PROJECT_ID}", project_id).replace("${REGION}", region).replace("${BUCKET}", bucket)
        else:
            resolved[k] = v
    resolved["project_id"] = project_id
    resolved["region"] = region
    resolved["bucket"] = bucket
    config["pipeline"] = resolved
    return config
