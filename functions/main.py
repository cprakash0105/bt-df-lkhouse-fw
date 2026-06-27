"""Pipeline Orchestrator — Cloud Function (Gen2).
Triggers when a new table config YAML lands in GCS.
Runs the full pipeline: ingest → curate → create BQ table → consume → tag → notify.

Trigger: GCS object finalize on gs://{BUCKET}/framework/config/tables/*.yaml
Runtime: Python 3.12, 60 min timeout, 1GB memory
"""
import os
import re
import time
import yaml
import functions_framework
from google.cloud import storage, bigquery, dataproc_v1


PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
REGION = os.environ.get("GCP_REGION", "europe-west2")
BUCKET = os.environ.get("CONFIG_BUCKET", f"{PROJECT_ID}-lakehouse")
SA_EMAIL = f"schema-poc-spark@{PROJECT_ID}.iam.gserviceaccount.com"
SUBNET = f"projects/{PROJECT_ID}/regions/{REGION}/subnetworks/schema-poc-network"
CONFIG_PATH = f"gs://{BUCKET}/framework/config/pipeline.yaml"
PY_FILES = f"gs://{BUCKET}/framework/bt_df_lkhouse_fw.zip"
ICEBERG_JAR = f"gs://{BUCKET}/spark/iceberg-spark-runtime.jar"
BIGLAKE_JAR = f"gs://{BUCKET}/spark/biglake-catalog.jar"

SPARK_PROPERTIES = {
    "spark.sql.catalog.lakehouse": "org.apache.iceberg.spark.SparkCatalog",
    "spark.sql.catalog.lakehouse.catalog-impl": "org.apache.iceberg.gcp.biglake.BigLakeCatalog",
    "spark.sql.catalog.lakehouse.gcp_project": PROJECT_ID,
    "spark.sql.catalog.lakehouse.gcp_location": REGION,
    "spark.sql.catalog.lakehouse.blms_catalog": "lakehouse",
    "spark.sql.catalog.lakehouse.warehouse": f"gs://{BUCKET}/ccn",
}


@functions_framework.cloud_event
def pipeline_trigger(cloud_event):
    """Triggered by GCS object finalize on config/tables/*.yaml"""
    data = cloud_event.data
    bucket_name = data["bucket"]
    file_name = data["name"]

    # Only trigger for table configs
    if not file_name.startswith("framework/config/tables/") or not file_name.endswith(".yaml"):
        print(f"Ignoring non-config file: {file_name}")
        return

    # Extract table name
    table_name = file_name.split("/")[-1].replace(".yaml", "")
    print(f"{'=' * 60}")
    print(f"  PIPELINE TRIGGERED: {table_name}")
    print(f"  Config: gs://{bucket_name}/{file_name}")
    print(f"{'=' * 60}")

    # Load the config to verify it's valid
    gcs = storage.Client(project=PROJECT_ID)
    blob = gcs.bucket(bucket_name).blob(file_name)
    config = yaml.safe_load(blob.download_as_text())

    if "table" not in config:
        print(f"Invalid config (no 'table' key): {file_name}")
        return

    # Check if landing data exists
    landing_prefix = f"landing/{table_name}/"
    landing_blobs = list(gcs.bucket(bucket_name).list_blobs(prefix=landing_prefix, max_results=1))
    if not landing_blobs:
        print(f"No landing data found at gs://{bucket_name}/{landing_prefix}")
        print("Skipping pipeline — waiting for data to arrive.")
        return

    try:
        # Step 1: Ingest
        print(f"\n[1/6] INGEST: Landing → Reservoir")
        ingest_batch = submit_dataproc_batch(
            job_name=f"ingest-{table_name}",
            main_py="bt_df_lkhouse_fw/engine/ingest.py",
            args=["--config", CONFIG_PATH, "--table", table_name, "--version", "v1", "--project", PROJECT_ID],
            jars=[],
            properties={},
        )
        wait_for_batch(ingest_batch)

        # Step 2: Curate
        print(f"\n[2/6] CURATE: Reservoir → CCN (Iceberg)")
        curate_batch = submit_dataproc_batch(
            job_name=f"curate-{table_name}",
            main_py="bt_df_lkhouse_fw/engine/curate.py",
            args=["--config", CONFIG_PATH, "--table", table_name, "--project", PROJECT_ID],
            jars=[ICEBERG_JAR, BIGLAKE_JAR],
            properties=SPARK_PROPERTIES,
        )
        wait_for_batch(curate_batch)

        # Step 3: Create BQ external table
        print(f"\n[3/6] CREATE BQ EXTERNAL TABLE")
        create_bq_external_table(table_name)

        # Step 4: Create consumption SQL if not exists
        print(f"\n[4/6] ENSURE CONSUMPTION SQL")
        ensure_consumption_sql(table_name)

        # Step 5: Run consume
        print(f"\n[5/6] CONSUME: CCN → Data Product (BigQuery)")
        run_consume(table_name)

        # Step 6: Tag columns
        print(f"\n[6/6] TAG COLUMNS")
        tag_columns_with_bde(table_name, config)

        print(f"\n{'=' * 60}")
        print(f"  PIPELINE COMPLETE: {table_name}")
        print(f"  Data Product: {PROJECT_ID}.lakehouse_dataproduct.{table_name}")
        print(f"{'=' * 60}")

    except Exception as e:
        print(f"\nPIPELINE FAILED for {table_name}: {e}")
        raise


def submit_dataproc_batch(job_name: str, main_py: str, args: list,
                          jars: list, properties: dict) -> str:
    """Submit a Dataproc Serverless batch job."""
    client = dataproc_v1.BatchControllerClient(
        client_options={"api_endpoint": f"{REGION}-dataproc.googleapis.com:443"}
    )

    batch = dataproc_v1.Batch(
        pyspark_batch=dataproc_v1.PySparkBatch(
            main_python_file_uri=f"gs://{BUCKET}/framework/engine/{main_py.split('/')[-1]}",
            python_file_uris=[PY_FILES],
            jar_file_uris=jars,
            args=args,
        ),
        runtime_config=dataproc_v1.RuntimeConfig(
            properties=properties,
        ),
        environment_config=dataproc_v1.EnvironmentConfig(
            execution_config=dataproc_v1.ExecutionConfig(
                service_account=SA_EMAIL,
                subnetwork_uri=SUBNET,
            ),
        ),
    )

    parent = f"projects/{PROJECT_ID}/locations/{REGION}"
    # Generate a unique batch ID
    batch_id = f"{job_name}-{int(time.time()) % 100000}"

    operation = client.create_batch(
        parent=parent,
        batch=batch,
        batch_id=batch_id,
    )

    print(f"  Submitted batch: {batch_id}")
    return batch_id


def wait_for_batch(batch_id: str, timeout: int = 600):
    """Wait for a Dataproc batch to complete."""
    client = dataproc_v1.BatchControllerClient(
        client_options={"api_endpoint": f"{REGION}-dataproc.googleapis.com:443"}
    )
    batch_name = f"projects/{PROJECT_ID}/locations/{REGION}/batches/{batch_id}"

    start = time.time()
    while time.time() - start < timeout:
        batch = client.get_batch(name=batch_name)
        state = batch.state.name

        if state == "SUCCEEDED":
            print(f"  Batch {batch_id}: SUCCEEDED")
            return
        elif state in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Batch {batch_id} {state}: {batch.state_message}")

        time.sleep(15)

    raise RuntimeError(f"Batch {batch_id} timed out after {timeout}s")


def create_bq_external_table(table_name: str):
    """Create BQ external table pointing to Iceberg via BLMS."""
    bq = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.lakehouse_ccn.{table_name}"

    # Check if already exists
    try:
        bq.get_table(table_id)
        print(f"  Table already exists: {table_id}")
        return
    except Exception:
        pass

    sql = f"""
    CREATE OR REPLACE EXTERNAL TABLE `{table_id}`
    WITH CONNECTION `projects/{PROJECT_ID}/locations/{REGION}/connections/biglake-conn`
    OPTIONS (
        format = 'ICEBERG',
        uris = ['blms://projects/{PROJECT_ID}/locations/{REGION}/catalogs/lakehouse/databases/ccn/tables/{table_name}']
    )
    """

    try:
        job = bq.query(sql)
        job.result()
        print(f"  Created: {table_id}")
    except Exception as e:
        print(f"  Failed to create external table: {e}")


def ensure_consumption_sql(table_name: str):
    """Create a basic consumption SQL if one doesn't exist."""
    gcs = storage.Client(project=PROJECT_ID)
    bucket = gcs.bucket(BUCKET)
    sql_blob_name = f"framework/config/consumption/{table_name}.sql"
    blob = bucket.blob(sql_blob_name)

    if blob.exists():
        print(f"  Consumption SQL exists: {sql_blob_name}")
        return

    # Generate a simple pass-through SQL
    sql = f"""-- {table_name}.sql
-- Auto-generated Data Product (pass-through from CCN)
CREATE OR REPLACE TABLE `${{PROJECT_ID}}.lakehouse_dataproduct.{table_name}` AS
SELECT * FROM `${{PROJECT_ID}}.lakehouse_ccn.{table_name}`
"""
    blob.upload_from_string(sql, content_type="text/plain")
    print(f"  Created: {sql_blob_name}")


def run_consume(table_name: str):
    """Run the consumption SQL in BigQuery."""
    gcs = storage.Client(project=PROJECT_ID)
    bucket = gcs.bucket(BUCKET)
    sql_blob = bucket.blob(f"framework/config/consumption/{table_name}.sql")

    if not sql_blob.exists():
        print(f"  No consumption SQL found for {table_name}")
        return

    sql = sql_blob.download_as_text()
    sql = sql.replace("${PROJECT_ID}", PROJECT_ID)

    # Remove comments
    sql_lines = [l for l in sql.strip().split("\n") if not l.strip().startswith("--")]
    sql = "\n".join(sql_lines).strip()

    bq = bigquery.Client(project=PROJECT_ID)
    job = bq.query(sql)
    job.result()

    # Get row count
    try:
        table_ref = f"{PROJECT_ID}.lakehouse_dataproduct.{table_name}"
        table = bq.get_table(table_ref)
        print(f"  Data Product: {table_ref} ({table.num_rows} rows)")
    except Exception:
        print(f"  Consume SQL executed")


def tag_columns_with_bde(table_name: str, config: dict):
    """Tag BQ columns with BDE descriptions."""
    bq = bigquery.Client(project=PROJECT_ID)
    table_ref = f"{PROJECT_ID}.lakehouse_dataproduct.{table_name}"

    try:
        table = bq.get_table(table_ref)
    except Exception:
        print(f"  Table not found for tagging: {table_ref}")
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
        desc = " | ".join(desc_parts) if desc_parts else ""
        new_schema.append(bigquery.SchemaField(field.name, field.field_type, description=desc))
        if desc:
            tagged += 1

    table.schema = new_schema
    bq.update_table(table, ["schema"])
    print(f"  Tagged {tagged} columns with metadata")
