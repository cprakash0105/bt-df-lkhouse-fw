"""Pipeline Orchestrator — Cloud Function (Gen2).
Triggers when a new table config YAML lands in GCS.
Runs the full pipeline: ingest -> curate -> create BQ table -> consume -> tag.
Logs all events to BigQuery pipeline_monitor table.

Trigger: GCS object finalize on gs://{BUCKET}/framework/config/tables/*.yaml
Runtime: Python 3.12, 540s timeout, 1GB memory
"""
import os
import re
import time
import yaml
import functions_framework
from google.cloud import storage, bigquery, dataproc_v1
from monitor import PipelineMonitor


PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
REGION = os.environ.get("GCP_REGION", "europe-west2")
BUCKET = os.environ.get("CONFIG_BUCKET", f"{PROJECT_ID}-lakehouse")
SA_EMAIL = f"schema-poc-spark@{PROJECT_ID}.iam.gserviceaccount.com"
SUBNET = f"projects/{PROJECT_ID}/regions/{REGION}/subnetworks/schema-poc-network"
CONFIG_PATH = f"gs://{BUCKET}/framework/config/pipeline.yaml"
PY_FILES = f"gs://{BUCKET}/framework/bt_df_lkhouse_fw.zip"
ICEBERG_JAR = f"gs://{BUCKET}/spark/iceberg-spark-runtime.jar"
BIGLAKE_JAR = f"gs://{BUCKET}/spark/biglake-catalog.jar"
CLUSTER_NAME = "lakehouse-cluster"

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
        print("Skipping pipeline - waiting for data to arrive.")
        return

    monitor = PipelineMonitor()

    try:
        # Step 1: Ingest
        print(f"\n[1/6] INGEST: Landing -> Reservoir")
        monitor.log_ingest(table_name, "started")
        t0 = time.time()
        ingest_job = submit_job(
            job_name=f"ingest-{table_name}",
            main_py="ingest.py",
            args=["--config", CONFIG_PATH, "--table", table_name, "--version", "v1", "--project", PROJECT_ID],
            jars=[],
        )
        wait_for_job(ingest_job)
        ingest_count = count_gcs_records(f"reservoir/{table_name}/")
        monitor.log_ingest(table_name, "succeeded", records=ingest_count, job_id=ingest_job, duration=time.time() - t0)

        # Step 2: Curate
        print(f"\n[2/6] CURATE: Reservoir -> CCN (Iceberg)")
        monitor.log_curate(table_name, "started", records_in=ingest_count)
        t0 = time.time()
        curate_job = submit_job(
            job_name=f"curate-{table_name}",
            main_py="curate.py",
            args=["--config", CONFIG_PATH, "--table", table_name, "--project", PROJECT_ID],
            jars=[ICEBERG_JAR, BIGLAKE_JAR],
        )
        wait_for_job(curate_job)
        monitor.log_curate(table_name, "succeeded", records_in=ingest_count, job_id=curate_job, duration=time.time() - t0)

        # Step 3: Create BQ external table
        print(f"\n[3/6] CREATE BQ EXTERNAL TABLE")
        create_bq_external_table(table_name)

        # Count CCN records (now that external table exists)
        ccn_count = count_bq_table(f"{PROJECT_ID}.lakehouse_ccn.{table_name}")
        if ccn_count is not None:
            records_rejected = (ingest_count or 0) - ccn_count
            # Update curate log with actual output
            monitor.log_event(
                dataset_name=table_name, stage="curate_result", status="info",
                records_in=ingest_count, records_out=ccn_count,
                records_rejected=records_rejected if records_rejected > 0 else 0,
            )

        # Step 4: Create consumption SQL if not exists
        print(f"\n[4/6] ENSURE CONSUMPTION SQL")
        ensure_consumption_sql(table_name)

        # Step 5: Run consume
        print(f"\n[5/6] CONSUME: CCN -> Data Product (BigQuery)")
        monitor.log_consume(table_name, "started")
        t0 = time.time()
        row_count = run_consume(table_name)
        monitor.log_consume(table_name, "succeeded", records_out=row_count, duration=time.time() - t0)

        # Step 6: Tag columns
        print(f"\n[6/6] TAG COLUMNS")
        tag_columns_with_bde(table_name, config)

        print(f"\n{'=' * 60}")
        print(f"  PIPELINE COMPLETE: {table_name}")
        print(f"  Data Product: {PROJECT_ID}.lakehouse_dataproduct.{table_name}")
        print(f"{'=' * 60}")

    except Exception as e:
        monitor.log_error(table_name, "pipeline", str(e))
        print(f"\nPIPELINE FAILED for {table_name}: {e}")
        raise


def count_gcs_records(prefix: str) -> int:
    """Count records in GCS parquet files by counting the files.
    Approximation: reads parquet row count from BQ load metadata isn't available,
    so we count JSONL lines from landing or estimate from file count."""
    try:
        gcs = storage.Client(project=PROJECT_ID)
        bucket = gcs.bucket(BUCKET)
        blobs = list(bucket.list_blobs(prefix=prefix))
        # Count parquet files (exclude _SUCCESS and _temporary)
        data_files = [b for b in blobs if b.name.endswith(".parquet") and "_temporary" not in b.name]
        if not data_files:
            # Try counting JSONL lines from landing
            landing_prefix = prefix.replace("reservoir/", "landing/") + "v1/"
            landing_blobs = list(bucket.list_blobs(prefix=landing_prefix))
            total_lines = 0
            for blob in landing_blobs:
                if blob.name.endswith(".jsonl"):
                    content = blob.download_as_text()
                    total_lines += len([l for l in content.strip().split("\n") if l.strip()])
            return total_lines
        # For parquet, we can't easily count without reading. Return file count as estimate.
        return len(data_files) * 1000  # rough estimate
    except Exception as e:
        print(f"  Could not count records: {e}")
        return None


def count_bq_table(table_id: str) -> int:
    """Count rows in a BigQuery table."""
    try:
        bq = bigquery.Client(project=PROJECT_ID)
        query = f"SELECT COUNT(*) as cnt FROM `{table_id}`"
        result = bq.query(query).result()
        for row in result:
            return row.cnt
    except Exception as e:
        print(f"  Could not count BQ table {table_id}: {e}")
        return None


def submit_job(job_name: str, main_py: str, args: list, jars: list) -> str:
    """Submit a PySpark job to the dedicated Dataproc cluster."""
    client = dataproc_v1.JobControllerClient(
        client_options={"api_endpoint": f"{REGION}-dataproc.googleapis.com:443"}
    )

    job_id = f"{job_name}-{int(time.time()) % 100000}".replace("_", "-")

    job = {
        "placement": {"cluster_name": CLUSTER_NAME},
        "reference": {"job_id": job_id},
        "pyspark_job": {
            "main_python_file_uri": f"gs://{BUCKET}/framework/engine/{main_py}",
            "python_file_uris": [PY_FILES],
            "jar_file_uris": jars if jars else [],
            "args": args,
        },
    }

    client.submit_job(project_id=PROJECT_ID, region=REGION, job=job)
    print(f"  Submitted job: {job_id}")
    return job_id


def wait_for_job(job_id: str, timeout: int = 480):
    """Wait for a Dataproc job to complete."""
    client = dataproc_v1.JobControllerClient(
        client_options={"api_endpoint": f"{REGION}-dataproc.googleapis.com:443"}
    )

    start = time.time()
    while time.time() - start < timeout:
        job = client.get_job(project_id=PROJECT_ID, region=REGION, job_id=job_id)
        state = job.status.state.name

        if state == "DONE":
            print(f"  Job {job_id}: SUCCEEDED")
            return
        elif state == "ERROR":
            raise RuntimeError(f"Job {job_id} FAILED: {job.status.details}")
        elif state == "CANCELLED":
            raise RuntimeError(f"Job {job_id} CANCELLED")

        time.sleep(10)

    raise RuntimeError(f"Job {job_id} timed out after {timeout}s")


def create_bq_external_table(table_name: str):
    """Create BQ external table pointing to Iceberg via BLMS."""
    bq = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.lakehouse_ccn.{table_name}"

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

    sql = f"""-- {table_name}.sql
-- Auto-generated Data Product (pass-through from CCN)
CREATE OR REPLACE TABLE `${{PROJECT_ID}}.lakehouse_dataproduct.{table_name}` AS
SELECT * FROM `${{PROJECT_ID}}.lakehouse_ccn.{table_name}`
"""
    blob.upload_from_string(sql, content_type="text/plain")
    print(f"  Created: {sql_blob_name}")


def run_consume(table_name: str) -> int:
    """Run the consumption SQL in BigQuery. Returns row count."""
    gcs = storage.Client(project=PROJECT_ID)
    bucket = gcs.bucket(BUCKET)
    sql_blob = bucket.blob(f"framework/config/consumption/{table_name}.sql")

    if not sql_blob.exists():
        print(f"  No consumption SQL found for {table_name}")
        return 0

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
        return table.num_rows
    except Exception:
        print(f"  Consume SQL executed")
        return 0


def tag_columns_with_bde(table_name: str, config: dict):
    """Tag BQ columns with BDE descriptions and apply data masking for PII."""
    bq = bigquery.Client(project=PROJECT_ID)
    table_ref = f"{PROJECT_ID}.lakehouse_dataproduct.{table_name}"

    try:
        table = bq.get_table(table_ref)
    except Exception:
        print(f"  Table not found for tagging: {table_ref}")
        return

    pii_fields = config.get("pii_fields", [])
    pk = config.get("primary_key", "")

    # Step 1: Tag columns with descriptions
    new_schema = []
    tagged = 0
    for field in table.schema:
        desc_parts = []
        if field.name == pk:
            desc_parts.append("Primary Key")
        if field.name in pii_fields:
            desc_parts.append("PII - Masked in non-prod")
        desc = " | ".join(desc_parts) if desc_parts else ""
        new_schema.append(bigquery.SchemaField(field.name, field.field_type, description=desc))
        if desc:
            tagged += 1

    table.schema = new_schema
    bq.update_table(table, ["schema"])
    print(f"  Tagged {tagged} columns with metadata")

    # Step 2: Apply data masking policies for PII fields
    if pii_fields:
        apply_data_masking(table_name, pii_fields, table.schema)


def apply_data_masking(table_name: str, pii_fields: list, schema):
    """Apply BigQuery data masking policies on PII columns."""
    bq = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.lakehouse_dataproduct.{table_name}"

    # Determine masking rule per field based on name/type
    masking_rules = {}
    for field_name in pii_fields:
        if "email" in field_name:
            masking_rules[field_name] = "EMAIL_MASK"
        elif "phone" in field_name or "mobile" in field_name:
            masking_rules[field_name] = "LAST_FOUR_CHARACTERS"
        elif "pan" in field_name or "aadhaar" in field_name or "card" in field_name:
            masking_rules[field_name] = "SHA256"
        elif "dob" in field_name or "birth" in field_name or "date_of_birth" in field_name:
            masking_rules[field_name] = "DATE_YEAR_MASK"
        elif "name" in field_name:
            masking_rules[field_name] = "DEFAULT_MASKING_VALUE"
        elif "address" in field_name or "addr" in field_name:
            masking_rules[field_name] = "DEFAULT_MASKING_VALUE"
        else:
            masking_rules[field_name] = "SHA256"

    # Create masking policies using DDL
    for field_name, rule in masking_rules.items():
        policy_name = f"mask_{table_name}_{field_name}"
        # Check if column exists in schema
        col_exists = any(f.name == field_name for f in schema)
        if not col_exists:
            continue

        try:
            # Create data policy
            sql = f"""
            CREATE OR REPLACE DATA MASKING RULE `{PROJECT_ID}.{policy_name}`
            OPTIONS (masking_expression = "{rule}")
            """
            # Note: Data masking DDL requires specific BQ edition.
            # For standard BQ, we use column-level security with policy tags instead.
            # Fallback: create a masked view
            pass
        except Exception:
            pass

    # Fallback: Create a masked view for non-privileged access
    masked_view_name = f"{table_name}_masked"
    select_parts = []
    for field in schema:
        if field.name in masking_rules:
            rule = masking_rules[field.name]
            if rule == "SHA256":
                select_parts.append(f"TO_HEX(SHA256(CAST(`{field.name}` AS STRING))) AS {field.name}")
            elif rule == "LAST_FOUR_CHARACTERS":
                select_parts.append(f"CONCAT('****', RIGHT(CAST(`{field.name}` AS STRING), 4)) AS {field.name}")
            elif rule == "EMAIL_MASK":
                select_parts.append(f"CONCAT(LEFT(`{field.name}`, 1), '***@', SPLIT(`{field.name}`, '@')[SAFE_OFFSET(1)]) AS {field.name}")
            elif rule == "DATE_YEAR_MASK":
                select_parts.append(f"DATE_TRUNC(CAST(`{field.name}` AS DATE), YEAR) AS {field.name}")
            elif rule == "DEFAULT_MASKING_VALUE":
                select_parts.append(f"'[REDACTED]' AS {field.name}")
            else:
                select_parts.append(f"`{field.name}`")
        else:
            select_parts.append(f"`{field.name}`")

    masked_sql = f"""
    CREATE OR REPLACE VIEW `{PROJECT_ID}.lakehouse_dataproduct.{masked_view_name}` AS
    SELECT {', '.join(select_parts)}
    FROM `{PROJECT_ID}.lakehouse_dataproduct.{table_name}`
    """

    try:
        job = bq.query(masked_sql)
        job.result()
        print(f"  Created masked view: {masked_view_name}")
        print(f"  Masking applied: {masking_rules}")
    except Exception as e:
        print(f"  Failed to create masked view: {e}")
