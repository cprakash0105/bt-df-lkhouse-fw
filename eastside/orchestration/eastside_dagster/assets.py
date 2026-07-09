from dagster import asset, AssetExecutionContext, Config
import yaml
from google.cloud import storage, bigquery
from .resources import DataprocResource


PROJECT_ID = "bt-df-lkhouse"
REGION = "europe-west2"
CATALOG = "lkhouse_eastside"
CONNECTION = f"projects/{PROJECT_ID}/locations/{REGION}/connections/biglake-conn"
# Dataproc 2.2 has built-in BQ connector — no extra JAR needed


class TableConfig(Config):
    table: str = "all"


def get_all_tables() -> list:
    """List all table configs from GCS."""
    gcs = storage.Client(project=PROJECT_ID)
    blobs = gcs.bucket("eastside-lakehouse").list_blobs(prefix="config/tables/")
    return [b.name.split("/")[-1].replace(".yaml", "") for b in blobs if b.name.endswith(".yaml")]


def load_table_config(table_name: str) -> dict:
    """Load a table's YAML config from GCS."""
    gcs = storage.Client(project=PROJECT_ID)
    blob = gcs.bucket("eastside-lakehouse").blob(f"config/tables/{table_name}.yaml")
    return yaml.safe_load(blob.download_as_text())


def register_bq_external_table(table_name: str, database: str, dataset: str, context):
    """Create BQ external table pointing to BLMS Iceberg table."""
    bq = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{dataset}.{table_name}"

    try:
        bq.get_table(table_id)
        context.log.info(f"BQ table already exists: {table_id}")
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


@asset(group_name="eastside")
def bronze_asset(context: AssetExecutionContext, config: TableConfig, dataproc: DataprocResource):
    tables = get_all_tables() if config.table == "all" else [config.table]
    for table in tables:
        context.log.info(f"Bronze: {table}")
        job_id = dataproc.submit_and_wait("bronze", table)
        context.log.info(f"Bronze complete: {job_id}")
        register_bq_external_table(table, "bronze", "eastside_bronze", context)


@asset(group_name="eastside", deps=[bronze_asset])
def silver_asset(context: AssetExecutionContext, config: TableConfig, dataproc: DataprocResource):
    tables = get_all_tables() if config.table == "all" else [config.table]
    for table in tables:
        context.log.info(f"Silver: {table}")
        job_id = dataproc.submit_and_wait("silver", table)
        context.log.info(f"Silver complete: {job_id}")
        register_bq_external_table(table, "silver", "eastside_silver", context)


@asset(group_name="eastside", deps=[silver_asset])
def gold_asset(context: AssetExecutionContext, config: TableConfig, dataproc: DataprocResource):
    tables = get_all_tables() if config.table == "all" else [config.table]
    for table in tables:
        context.log.info(f"Gold: {table}")
        job_id = dataproc.submit_and_wait("gold", table)
        context.log.info(f"Gold complete: {job_id}")

        # Tag columns with metadata
        try:
            tbl_config = load_table_config(table)
            tag_columns(table, tbl_config, context)
        except Exception as e:
            context.log.warning(f"Column tagging skipped for {table}: {e}")
