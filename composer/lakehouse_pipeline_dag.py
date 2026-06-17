"""Cloud Composer DAG: Lakehouse Pipeline
Reservoir(Parquet) → CCN(Iceberg/BLMS) → Data Product(BigQuery native).

Ingest + Curate: Dataproc Serverless (PySpark)
Consume: BigQuery SQL (no Spark needed)

Deploy: gsutil cp composer/lakehouse_pipeline_dag.py gs://<composer-bucket>/dags/
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.google.cloud.operators.dataproc import DataprocCreateBatchOperator
from airflow.providers.google.cloud.operators.bigquery import BigQueryInsertJobOperator

PROJECT_ID = "bt-df-lkhouse"
REGION = "europe-west2"
BUCKET = f"{PROJECT_ID}-lakehouse"
SA_EMAIL = f"schema-poc-spark@{PROJECT_ID}.iam.gserviceaccount.com"
SUBNET = f"projects/{PROJECT_ID}/regions/{REGION}/subnetworks/schema-poc-network"

ICEBERG_JARS = ["gs://spark-lib/biglake/biglake-catalog-iceberg1.9.1-0.1.3-with-dependencies.jar"]
ICEBERG_PROPERTIES = {
    "spark.jars.packages": "org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.9.1",
    "spark.sql.catalog.lakehouse": "org.apache.iceberg.spark.SparkCatalog",
    "spark.sql.catalog.lakehouse.catalog-impl": "org.apache.iceberg.gcp.biglake.BigLakeCatalog",
    "spark.sql.catalog.lakehouse.gcp_project": PROJECT_ID,
    "spark.sql.catalog.lakehouse.gcp_location": REGION,
    "spark.sql.catalog.lakehouse.blms_catalog": "lakehouse",
    "spark.sql.catalog.lakehouse.warehouse": f"gs://{BUCKET}",
}

CONFIG_PATH = f"gs://{BUCKET}/framework/config/pipeline.yaml"
PY_FILES = f"gs://{BUCKET}/framework/bt_df_lkhouse_fw.zip"

default_args = {
    "owner": "data-engineering",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

# customer_360 SQL (same as config/consumption/customer_360.sql)
CUSTOMER_360_SQL = f"""
CREATE OR REPLACE TABLE `{PROJECT_ID}.lakehouse_dataproduct.customer_360` AS
SELECT
    c.customer_id, c.name, c.email, c.region, c.loyalty_tier,
    c.signup_date, c.is_active, c.customer_segment,
    COALESCE(o.total_orders, 0) AS total_orders,
    COALESCE(o.total_spend, 0.0) AS total_spend,
    COALESCE(o.avg_order_value, 0.0) AS avg_order_value,
    o.first_order_date, o.last_order_date,
    COALESCE(o.total_discounts, 0.0) AS total_discounts,
    COALESCE(p.total_payments, 0) AS total_payments,
    COALESCE(p.total_paid, 0.0) AS total_paid
FROM `{PROJECT_ID}.lakehouse_ccn.customers` c
LEFT JOIN (
    SELECT customer_id,
        COUNT(*) AS total_orders, SUM(total_amount) AS total_spend,
        AVG(total_amount) AS avg_order_value,
        MIN(order_date) AS first_order_date, MAX(order_date) AS last_order_date,
        SUM(discount_amount) AS total_discounts
    FROM `{PROJECT_ID}.lakehouse_ccn.orders` GROUP BY customer_id
) o ON c.customer_id = o.customer_id
LEFT JOIN (
    SELECT ord.customer_id, COUNT(*) AS total_payments, SUM(pay.amount) AS total_paid
    FROM `{PROJECT_ID}.lakehouse_ccn.payments` pay
    JOIN `{PROJECT_ID}.lakehouse_ccn.orders` ord ON pay.order_id = ord.order_id
    GROUP BY ord.customer_id
) p ON c.customer_id = p.customer_id
"""

with DAG(
    dag_id="lakehouse_pipeline",
    default_args=default_args,
    description="Reservoir(Parquet) → CCN(Iceberg) → Data Product(BigQuery)",
    schedule_interval="@daily",
    start_date=datetime(2025, 6, 1),
    catchup=False,
    tags=["lakehouse", "iceberg", "schema-evolution"],
    params={"version": "v1"},
) as dag:

    # Stage 1: Landing → Reservoir (Parquet)
    ingest = DataprocCreateBatchOperator(
        task_id="ingest",
        project_id=PROJECT_ID,
        region=REGION,
        batch_id=f"ingest-{{{{ ds_nodash }}}}",
        batch={
            "pyspark_batch": {
                "main_python_file_uri": f"gs://{BUCKET}/framework/engine/ingest.py",
                "args": ["--config", CONFIG_PATH, "--all", "--version", "{{ params.version }}", "--project", PROJECT_ID],
                "python_file_uris": [PY_FILES],
            },
            "runtime_config": {
                "version": "2.2",
                "properties": {"spark.jars.packages": "org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.9.1"},
            },
            "environment_config": {
                "execution_config": {
                    "service_account": SA_EMAIL,
                    "subnetwork_uri": SUBNET,
                    "staging_bucket": BUCKET,
                }
            },
        },
    )

    # Stage 2: Reservoir (Parquet) → CCN (Iceberg/BLMS)
    curate = DataprocCreateBatchOperator(
        task_id="curate",
        project_id=PROJECT_ID,
        region=REGION,
        batch_id=f"curate-{{{{ ds_nodash }}}}",
        batch={
            "pyspark_batch": {
                "main_python_file_uri": f"gs://{BUCKET}/framework/engine/curate.py",
                "args": ["--config", CONFIG_PATH, "--all", "--project", PROJECT_ID],
                "jar_file_uris": ICEBERG_JARS,
                "python_file_uris": [PY_FILES],
            },
            "runtime_config": {
                "version": "2.2",
                "properties": ICEBERG_PROPERTIES,
            },
            "environment_config": {
                "execution_config": {
                    "service_account": SA_EMAIL,
                    "subnetwork_uri": SUBNET,
                    "staging_bucket": BUCKET,
                }
            },
        },
    )

    # Stage 3: CCN (Iceberg) → Data Product (BigQuery native)
    consume = BigQueryInsertJobOperator(
        task_id="consume",
        configuration={
            "query": {
                "query": CUSTOMER_360_SQL,
                "useLegacySql": False,
            }
        },
        project_id=PROJECT_ID,
        location=REGION,
    )

    ingest >> curate >> consume
