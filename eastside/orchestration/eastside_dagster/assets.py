from dagster import asset, AssetExecutionContext, Config, RetryPolicy, AssetIn
import yaml
from google.cloud import storage, bigquery
from .resources import DataprocResource


PROJECT_ID = "bt-df-lkhouse"
REGION = "europe-west2"
CATALOG = "lkhouse_eastside"
BUCKET = "eastside-lakehouse"
CONNECTION = f"projects/{PROJECT_ID}/locations/{REGION}/connections/biglake-conn"


# ============================================================
# CONFIG
# ============================================================

class BronzeConfig(Config):
    table: str = "all"
    version: str = "v1"


class SilverConfig(Config):
    table: str = "all"


class GoldConfig(Config):
    table: str = "all"


# ============================================================
# HELPERS
# ============================================================

def get_all_tables() -> list:
    """List all table configs from GCS."""
    gcs = storage.Client(project=PROJECT_ID)
    blobs = gcs.bucket(BUCKET).list_blobs(prefix="config/tables/")
    return [b.name.split("/")[-1].replace(".yaml", "") for b in blobs if b.name.endswith(".yaml")]


def load_table_config(table_name: str) -> dict:
    """Load a table's YAML config from GCS."""
    gcs = storage.Client(project=PROJECT_ID)
    blob = gcs.bucket(BUCKET).blob(f"config/tables/{table_name}.yaml")
    return yaml.safe_load(blob.download_as_text())


def get_unprocessed_versions(table_name: str) -> list:
    """Get versions in landing that haven't been processed yet (no watermark)."""
    import json
    gcs = storage.Client(project=PROJECT_ID)
    bucket = gcs.bucket(BUCKET)

    # Get all version folders in landing
    prefix = f"landing/{table_name}/"
    blobs = bucket.list_blobs(prefix=prefix, delimiter="/")
    # Force iteration to populate prefixes
    _ = list(blobs)
    versions = []
    for p in blobs.prefixes:
        # p looks like "landing/pos_transactions/v1/"
        version = p.rstrip("/").split("/")[-1]
        versions.append(version)

    # Check watermark for processed versions
    wm_path = f"bronze/_watermarks/{table_name}.json"
    wm_blob = bucket.blob(wm_path)
    processed = []
    if wm_blob.exists():
        wm = json.loads(wm_blob.download_as_text())
        processed = wm.get("processed_versions", [])

    unprocessed = [v for v in sorted(versions) if v not in processed]
    return unprocessed


def register_bq_external_table(table_name: str, database: str, dataset: str, context):
    """Create BQ external table pointing to BLMS Iceberg table."""
    bq = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{dataset}.{table_name}"

    try:
        bq.get_table(table_id)
        context.log.info(f"BQ external table exists: {table_id}")
        return
    except Exception:
        pass

    sql = f"""
    CREATE OR REPLACE EXTERNAL TABLE `{table_id}`
    WITH CONNECTION `{CONNECTION}`
    OPTIONS (
        format = 'ICEBERG',
        uris = ['blms://projects/{PROJECT_ID}/locations/{REGION}/catalogs/{CATALOG}/databases/{database}/tables/{table_name}']
    )
    """
    try:
        bq.query(sql).result()
        context.log.info(f"Created BQ external table: {table_id}")
    except Exception as e:
        context.log.warning(f"Failed to create BQ external table {table_id}: {e}")


def tag_columns(table_name: str, config: dict, context):
    """Tag BQ columns with BDE descriptions and PII markers."""
    bq = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.eastside_dataproduct.{table_name}"

    try:
        table = bq.get_table(table_id)
    except Exception:
        context.log.warning(f"Table not found for tagging: {table_id}")
        return

    pii_fields = config.get("pii_fields", [])
    pk = config.get("primary_key", "")

    new_schema = []
    tagged = 0
    for field in table.schema:
        desc_parts = []
        if field.name == pk:
            desc_parts.append("Primary Key")
        if field.name in pii_fields:
            desc_parts.append("PII")
        desc = " | ".join(desc_parts) if desc_parts else field.description or ""
        new_schema.append(bigquery.SchemaField(
            field.name, field.field_type,
            description=desc,
            policy_tags=field.policy_tags,
        ))
        if desc_parts:
            tagged += 1

    table.schema = new_schema
    bq.update_table(table, ["schema"])
    context.log.info(f"Tagged {tagged} columns on {table_id}")


# ============================================================
# ASSETS
# ============================================================

@asset(
    group_name="eastside",
    retry_policy=RetryPolicy(max_retries=2, delay=30),
    metadata={"layer": "bronze", "description": "Landing → Bronze Iceberg (append)"},
)
def bronze_asset(context: AssetExecutionContext, config: BronzeConfig, dataproc: DataprocResource):
    """Ingest raw landing files into Bronze Iceberg tables.

    Processes a specific version of landing data. If version is 'auto',
    discovers and processes all unprocessed versions in order.
    """
    tables = get_all_tables() if config.table == "all" else [config.table]

    for table in tables:
        if config.version == "auto":
            # Auto-discover unprocessed versions
            versions = get_unprocessed_versions(table)
            if not versions:
                context.log.info(f"Bronze [{table}]: no unprocessed versions found — skipping")
                continue
            context.log.info(f"Bronze [{table}]: found unprocessed versions: {versions}")
        else:
            versions = [config.version]

        for version in versions:
            context.log.info(f"Bronze [{table}]: processing {version}")
            job_id = dataproc.submit_and_wait("bronze", table, version=version)
            context.log.info(f"Bronze [{table}]: {version} complete (job: {job_id})")

        # Register BQ external table (idempotent)
        register_bq_external_table(table, "bronze", "eastside_bronze", context)


@asset(
    group_name="eastside",
    deps=[bronze_asset],
    retry_policy=RetryPolicy(max_retries=1, delay=30),
    metadata={"layer": "silver", "description": "Bronze → Silver Iceberg (merge/SCD2)"},
)
def silver_asset(context: AssetExecutionContext, config: SilverConfig, dataproc: DataprocResource):
    """Curate bronze data into Silver with dedup, DQ, masking, and SCD2 merge.

    Reads all unprocessed records from bronze (incremental via _ingested_at).
    Schema evolution enforced: add_column and type_widen allowed, drop_column and type_narrow blocked.
    """
    tables = get_all_tables() if config.table == "all" else [config.table]

    for table in tables:
        context.log.info(f"Silver [{table}]: starting")
        job_id = dataproc.submit_and_wait("silver", table)
        context.log.info(f"Silver [{table}]: complete (job: {job_id})")

        # Register BQ external table (idempotent)
        register_bq_external_table(table, "silver", "eastside_silver", context)


@asset(
    group_name="eastside",
    deps=[silver_asset],
    retry_policy=RetryPolicy(max_retries=1, delay=30),
    metadata={"layer": "gold", "description": "Silver → BigQuery Data Product"},
)
def gold_asset(context: AssetExecutionContext, config: GoldConfig, dataproc: DataprocResource):
    """Publish curated silver data as Gold data products in BigQuery.

    Reads is_current=true from silver, validates against contract, writes native BQ table.
    Schema is contract-locked — any missing required column fails the pipeline.
    """
    tables = get_all_tables() if config.table == "all" else [config.table]

    for table in tables:
        context.log.info(f"Gold [{table}]: starting")
        job_id = dataproc.submit_and_wait("gold", table)
        context.log.info(f"Gold [{table}]: complete (job: {job_id})")

        # Tag columns with PII/PK metadata
        try:
            tbl_config = load_table_config(table)
            tag_columns(table, tbl_config, context)
        except Exception as e:
            context.log.warning(f"Column tagging skipped for {table}: {e}")
