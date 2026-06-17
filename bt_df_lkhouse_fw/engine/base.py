"""bt-df-lkhouse-fw — Config-driven PySpark Lakehouse Framework.
Base module: Spark session, config loading, structured logging.

Config structure:
  config/pipeline.yaml         — global settings
  config/tables/*.yaml         — one per table (drop & go)
  config/consumption/*.sql     — one per view (drop & go)

GCP Native: BLMS (Iceberg CCN) + GCS (Parquet Reservoir) + BigQuery (Data Product).
"""
import os
import sys
import glob
import yaml
import argparse
import traceback
import time
from datetime import datetime
from functools import wraps

BANNER = """
╔════════════════════════════════════════════════════════════╗
║  ██████╗ ████████╗      ██████╗ ███████╗                  ║
║  ██╔══██╗╚══██╔══╝      ██╔══██╗██╔════╝                  ║
║  ██████╔╝   ██║   █████╗██║  ██║█████╗                    ║
║  ██╔══██╗   ██║   ╚════╝██║  ██║██╔══╝                    ║
║  ██████╔╝   ██║         ██████╔╝██║                       ║
║  ╚═════╝    ╚═╝         ╚═════╝ ╚═╝                       ║
║                                                            ║
║  bt-df-lkhouse-fw  v2                                      ║
║  Config-driven Lakehouse Framework                         ║
║  GCP: Reservoir(Parquet) → CCN(Iceberg/BLMS) → DP(BigQuery)║
╚════════════════════════════════════════════════════════════╝
"""


# ============================================================
# LOGGING
# ============================================================

class LogLevel:
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"


_log_lines = []
_json_logging = False


def enable_json_logging():
    """Switch to JSON structured logging (one JSON object per line)."""
    global _json_logging
    _json_logging = True


def log(stage: str, message: str, level: str = LogLevel.INFO):
    import json as _json
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    if _json_logging:
        print(_json.dumps({"ts": timestamp, "level": level, "stage": stage, "msg": message}))
    else:
        prefix = {
            LogLevel.DEBUG: "🔍",
            LogLevel.INFO: "ℹ️ ",
            LogLevel.WARN: "⚠️ ",
            LogLevel.ERROR: "❌",
            LogLevel.FATAL: "💀",
        }.get(level, "  ")
        print(f"  {prefix} [{timestamp}] [{level}] [{stage}] {message}")

    _log_lines.append({"timestamp": timestamp, "level": level, "stage": stage, "message": message})


def log_header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def log_table_info(df, table_name: str):
    log(table_name, f"Records: {df.count()}")
    log(table_name, f"Columns: {df.columns}")


def log_error(stage: str, message: str, exception: Exception = None):
    log(stage, message, LogLevel.ERROR)
    if exception:
        log(stage, f"Exception: {type(exception).__name__}: {exception}", LogLevel.ERROR)
        for line in traceback.format_exc().strip().split("\n"):
            log(stage, f"  {line}", LogLevel.ERROR)


def log_summary(stage: str, results: dict):
    log_header(f"{stage.upper()} SUMMARY")
    for table, status in results.items():
        icon = "✅" if status == "SUCCESS" else "❌" if status == "FAILED" else "⏭️"
        log(stage, f"{icon} {table}: {status}")

    succeeded = [t for t, s in results.items() if s == "SUCCESS"]
    failed = [t for t, s in results.items() if s == "FAILED"]
    skipped = [t for t, s in results.items() if s == "SKIPPED"]
    log(stage, "")
    log(stage, f"Total: {len(results)} | Succeeded: {len(succeeded)} | Failed: {len(failed)} | Skipped: {len(skipped)}")
    if failed:
        log(stage, f"FAILED: {failed}", LogLevel.ERROR)


def get_log_lines() -> list:
    return _log_lines


def flush_logs_to_gcs(stage: str, config: dict):
    """Write accumulated JSON log lines to GCS. One file per run."""
    import json as _json
    try:
        from google.cloud import storage as gcs_storage

        if not _log_lines:
            return

        pipeline = config.get("pipeline", {})
        bucket_name = pipeline.get("bucket", "")
        if not bucket_name:
            return

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        blob_path = f"logs/{stage}/{run_id}.jsonl"

        content = "\n".join(_json.dumps(line) for line in _log_lines)

        client = gcs_storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(content, content_type="application/json")

        log("logs", f"Persisted {len(_log_lines)} log lines → gs://{bucket_name}/{blob_path}")
    except Exception as e:
        # Never let log persistence break the pipeline
        print(f"  ⚠️  Log persistence failed (non-fatal): {e}")


def timed(stage: str):
    """Decorator to time and log function execution."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            table_name = kwargs.get("table_name") or (args[2] if len(args) > 2 else "unknown")
            log(stage, f"Started: {table_name}")
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                log(stage, f"Completed: {table_name} ({elapsed:.1f}s)")
                return result
            except Exception as e:
                elapsed = time.time() - start
                log_error(stage, f"Failed: {table_name} after {elapsed:.1f}s", e)
                raise
        return wrapper
    return decorator


# ============================================================
# SPARK SESSION
# ============================================================

def get_spark(app_name: str):
    """Create Spark session. Catalog config comes from Dataproc --properties."""
    from pyspark.sql import SparkSession
    log("spark", f"Creating session: bt-df-lkhouse-{app_name}")
    spark = SparkSession.builder.appName(f"bt-df-lkhouse-{app_name}").getOrCreate()
    log("spark", f"Session created (version: {spark.version})")
    return spark


# ============================================================
# CONFIG LOADING (auto-discovery)
# ============================================================

def load_config(config_path: str) -> dict:
    """Load global pipeline config + auto-discover tables and consumption SQL."""
    log("config", f"Loading config from: {config_path}")

    if config_path.startswith("gs://"):
        from google.cloud import storage as gcs_storage
        parts = config_path.replace("gs://", "").split("/", 1)
        client = gcs_storage.Client()
        blob = client.bucket(parts[0]).blob(parts[1])
        config = yaml.safe_load(blob.download_as_text())
        # For GCS configs, load tables and consumption from GCS too
        prefix = parts[1].rsplit("/", 1)[0]
        config["tables"] = _load_tables_from_gcs(client, parts[0], f"{prefix}/tables/")
        config["consumption"] = _load_consumption_from_gcs(client, parts[0], f"{prefix}/consumption/")
    else:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        config_dir = os.path.dirname(config_path)
        config["tables"] = _load_tables_from_disk(config_dir)
        config["consumption"] = _load_consumption_from_disk(config_dir)

    log("config", f"Loaded: {len(config['tables'])} tables, {len(config['consumption'])} views")
    return config


def _load_tables_from_disk(config_dir: str) -> dict:
    tables = {}
    tables_dir = os.path.join(config_dir, "tables")
    if not os.path.isdir(tables_dir):
        log("config", f"No tables directory: {tables_dir}", LogLevel.WARN)
        return tables
    for yaml_file in sorted(glob.glob(os.path.join(tables_dir, "*.yaml"))):
        try:
            with open(yaml_file, "r") as f:
                tc = yaml.safe_load(f)
            tables[tc["table"]] = tc
            log("config", f"  ✅ Table: {tc['table']} ← {os.path.basename(yaml_file)}")
        except Exception as e:
            log_error("config", f"  ❌ Failed: {os.path.basename(yaml_file)}", e)
    return tables


def _load_consumption_from_disk(config_dir: str) -> dict:
    views = {}
    consumption_dir = os.path.join(config_dir, "consumption")
    if not os.path.isdir(consumption_dir):
        log("config", f"No consumption directory: {consumption_dir}", LogLevel.WARN)
        return views
    for sql_file in sorted(glob.glob(os.path.join(consumption_dir, "*.sql"))):
        try:
            view_name = os.path.splitext(os.path.basename(sql_file))[0]
            with open(sql_file, "r") as f:
                sql = f.read()
            # Strip comments
            sql_lines = [l for l in sql.strip().split("\n") if not l.strip().startswith("--")]
            views[view_name] = "\n".join(sql_lines).strip()
            log("config", f"  ✅ View: {view_name} ← {os.path.basename(sql_file)}")
        except Exception as e:
            log_error("config", f"  ❌ Failed: {os.path.basename(sql_file)}", e)
    return views


def _load_tables_from_gcs(client, bucket_name: str, prefix: str) -> dict:
    tables = {}
    bucket = client.bucket(bucket_name)
    blobs = list(bucket.list_blobs(prefix=prefix))
    for blob in blobs:
        if blob.name.endswith(".yaml"):
            try:
                tc = yaml.safe_load(blob.download_as_text())
                tables[tc["table"]] = tc
                log("config", f"  ✅ Table: {tc['table']} ← gs://{bucket_name}/{blob.name}")
            except Exception as e:
                log_error("config", f"  ❌ Failed: {blob.name}", e)
    return tables


def _load_consumption_from_gcs(client, bucket_name: str, prefix: str) -> dict:
    views = {}
    bucket = client.bucket(bucket_name)
    blobs = list(bucket.list_blobs(prefix=prefix))
    for blob in blobs:
        if blob.name.endswith(".sql"):
            try:
                view_name = os.path.splitext(os.path.basename(blob.name))[0]
                sql = blob.download_as_text()
                sql_lines = [l for l in sql.strip().split("\n") if not l.strip().startswith("--")]
                views[view_name] = "\n".join(sql_lines).strip()
                log("config", f"  ✅ View: {view_name} ← gs://{bucket_name}/{blob.name}")
            except Exception as e:
                log_error("config", f"  ❌ Failed: {blob.name}", e)
    return views


# ============================================================
# CONFIG ACCESSORS
# ============================================================

def get_table_config(config: dict, table_name: str) -> dict:
    tables = config.get("tables", {})
    if table_name not in tables:
        raise ValueError(f"Table '{table_name}' not found. Available: {list(tables.keys())}")
    return tables[table_name]


def get_all_tables(config: dict) -> list:
    return list(config.get("tables", {}).keys())


def get_all_consumption_views(config: dict) -> dict:
    return config.get("consumption", {})


def get_pipeline_config(config: dict) -> dict:
    return config["pipeline"]


# ============================================================
# CLI
# ============================================================

def parse_args(description: str):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--config", required=True, help="Path to pipeline.yaml (local or gs://)")
    parser.add_argument("--table", help="Table name to process")
    parser.add_argument("--target", help="Consumption target name")
    parser.add_argument("--version", default="v1", help="Data version (v1, v2)")
    parser.add_argument("--all", action="store_true", help="Process all tables/views")
    parser.add_argument("--project", help="GCP project ID (overrides config)")
    parser.add_argument("--bucket", help="GCS bucket (overrides config)")
    parser.add_argument("--json-logs", action="store_true", help="Output logs as JSON lines")
    args = parser.parse_args()
    if args.json_logs:
        enable_json_logging()
    return args


def resolve_pipeline_vars(config: dict, args) -> dict:
    """Resolve ${VAR} placeholders in pipeline config using args or env."""
    pipeline = config["pipeline"]
    project_id = args.project or os.environ.get("PROJECT_ID", pipeline.get("project_id", ""))
    region = os.environ.get("REGION", pipeline.get("region", "europe-west2"))
    bucket = args.bucket or os.environ.get("BUCKET", f"{project_id}-lakehouse")

    # Replace placeholders
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
