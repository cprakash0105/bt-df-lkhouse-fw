"""bt-df-lkhouse-fw — Config-driven PySpark Lakehouse Framework.
Base module: Spark session, config loading, logging.

GCP Native: Uses BigLake Metastore (BLMS) as Iceberg catalog + GCS storage.
Spark catalog config is passed via --properties at Dataproc submit time.
"""
import yaml
import argparse
from datetime import datetime

BANNER = """
╔════════════════════════════════════════════════════════════╗
║  ██████╗ ████████╗      ██████╗ ███████╗                  ║
║  ██╔══██╗╚══██╔══╝      ██╔══██╗██╔════╝                  ║
║  ██████╔╝   ██║   █████╗██║  ██║█████╗                    ║
║  ██╔══██╗   ██║   ╚════╝██║  ██║██╔══╝                    ║
║  ██████╔╝   ██║         ██████╔╝██║                       ║
║  ╚═════╝    ╚═╝         ╚═════╝ ╚═╝                       ║
║                                                            ║
║  bt-df-lkhouse-fw                                          ║
║  Config-driven Lakehouse Framework                         ║
║  GCP Native: BLMS + Iceberg + Dataproc Serverless          ║
╚════════════════════════════════════════════════════════════╝
"""


def get_spark(app_name: str):
    """Create Spark session. Catalog config comes from Dataproc --properties."""
    from pyspark.sql import SparkSession
    return SparkSession.builder.appName(f"bt-df-lkhouse-{app_name}").getOrCreate()


def load_config(config_path: str) -> dict:
    """Load pipeline config from YAML (local path or GCS via spark)."""
    if config_path.startswith("gs://"):
        from google.cloud import storage
        import io
        parts = config_path.replace("gs://", "").split("/", 1)
        client = storage.Client()
        blob = client.bucket(parts[0]).blob(parts[1])
        return yaml.safe_load(blob.download_as_text())
    else:
        with open(config_path, "r") as f:
            return yaml.safe_load(f)


def get_table_config(config: dict, table_name: str) -> dict:
    tables = config.get("tables", {})
    if table_name not in tables:
        raise ValueError(f"Table '{table_name}' not found. Available: {list(tables.keys())}")
    return tables[table_name]


def get_consumption_config(config: dict, target_name: str) -> dict:
    targets = config.get("consumption", {})
    if target_name not in targets:
        raise ValueError(f"Target '{target_name}' not found. Available: {list(targets.keys())}")
    return targets[target_name]


def log(stage: str, message: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"  [{timestamp}] [{stage}] {message}")


def log_header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def log_table_info(df, table_name: str):
    log(table_name, f"Records: {df.count()}")
    log(table_name, f"Columns: {df.columns}")


def parse_args(description: str):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--config", required=True, help="Path to pipeline.yaml (local or gs://)")
    parser.add_argument("--table", help="Table name to process")
    parser.add_argument("--target", help="Consumption target name")
    parser.add_argument("--version", default="v1", help="Data version (v1, v2)")
    parser.add_argument("--all", action="store_true", help="Process all tables")
    parser.add_argument("--project", default="bt-df-lkhouse", help="GCP project ID")
    return parser.parse_args()
