from dagster import asset, AssetExecutionContext, Config
from google.cloud import storage
from .resources import DataprocResource


class TableConfig(Config):
    table: str = "all"


BQ_JAR = "gs://spark-lib/bigquery/spark-bigquery-with-dependencies_2.12-0.36.1.jar"


def get_all_tables() -> list:
    """List all table configs from GCS."""
    gcs = storage.Client(project="bt-df-lkhouse")
    blobs = gcs.bucket("eastside-lakehouse").list_blobs(prefix="config/tables/")
    return [b.name.split("/")[-1].replace(".yaml", "") for b in blobs if b.name.endswith(".yaml")]


@asset(group_name="eastside")
def bronze_asset(context: AssetExecutionContext, config: TableConfig, dataproc: DataprocResource):
    tables = get_all_tables() if config.table == "all" else [config.table]
    for table in tables:
        context.log.info(f"Bronze: {table}")
        job_id = dataproc.submit_and_wait("bronze", table)
        context.log.info(f"Bronze complete: {job_id}")


@asset(group_name="eastside", deps=[bronze_asset])
def silver_asset(context: AssetExecutionContext, config: TableConfig, dataproc: DataprocResource):
    tables = get_all_tables() if config.table == "all" else [config.table]
    for table in tables:
        context.log.info(f"Silver: {table}")
        job_id = dataproc.submit_and_wait("silver", table)
        context.log.info(f"Silver complete: {job_id}")


@asset(group_name="eastside", deps=[silver_asset])
def gold_asset(context: AssetExecutionContext, config: TableConfig, dataproc: DataprocResource):
    tables = get_all_tables() if config.table == "all" else [config.table]
    for table in tables:
        context.log.info(f"Gold: {table}")
        job_id = dataproc.submit_and_wait("gold", table, extra_jars=[BQ_JAR])
        context.log.info(f"Gold complete: {job_id}")
