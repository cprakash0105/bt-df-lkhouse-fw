"""Landing to Bronze: Ingest raw JSONL into Bronze Iceberg tables (BLMS).

Raw data written as-is to Iceberg — no transformations, no DQ.
This gives us time-travel, schema tracking, and unified catalog from the start.
Same pattern as Databricks Delta Lake: all layers are managed tables.

Usage:
    gcloud dataproc batches submit pyspark gs://schema-evolution-poc-lakehouse/spark/landing_to_bronze.py \
      --jars=gs://spark-lib/biglake/biglake-catalog-iceberg1.9.1-0.1.3-with-dependencies.jar \
      --properties="^::^spark.jars.packages=org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.9.1::spark.sql.catalog.lakehouse=org.apache.iceberg.spark.SparkCatalog::spark.sql.catalog.lakehouse.catalog-impl=org.apache.iceberg.gcp.biglake.BigLakeCatalog::spark.sql.catalog.lakehouse.gcp_project=schema-evolution-poc::spark.sql.catalog.lakehouse.gcp_location=europe-west2::spark.sql.catalog.lakehouse.blms_catalog=schema_poc::spark.sql.catalog.lakehouse.warehouse=gs://schema-evolution-poc-lakehouse" \
      -- --project=schema-evolution-poc
"""

import argparse
from datetime import datetime, timezone
from pyspark.sql import SparkSession
from pyspark.sql import functions as F


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="schema-evolution-poc")
    parser.add_argument("--region", default="europe-west2")
    parser.add_argument("--table", default="all", help="Process specific table or 'all'")
    args = parser.parse_args()

    bucket = f"{args.project}-lakehouse"
    spark = SparkSession.builder.appName("LandingToBronze").getOrCreate()

    # Create bronze namespace
    spark.sql("CREATE NAMESPACE IF NOT EXISTS lakehouse.bronze")

    tables_config = {
        "customers": {
            "partition_by": "signup_date",
            "create_sql": """
                CREATE TABLE IF NOT EXISTS lakehouse.bronze.customers (
                    customer_id INT,
                    name STRING,
                    email STRING,
                    phone STRING,
                    address STRING,
                    city STRING,
                    postcode STRING,
                    region STRING,
                    loyalty_tier STRING,
                    signup_date STRING,
                    is_active BOOLEAN,
                    ingestion_ts STRING
                ) USING iceberg
                PARTITIONED BY (region)
            """
        },
        "products": {
            "partition_by": "category",
            "create_sql": """
                CREATE TABLE IF NOT EXISTS lakehouse.bronze.products (
                    product_id INT,
                    product_name STRING,
                    category STRING,
                    price DOUBLE,
                    cost_price DOUBLE,
                    supplier STRING,
                    sku STRING,
                    weight_kg DOUBLE,
                    is_active BOOLEAN,
                    created_date STRING,
                    ingestion_ts STRING
                ) USING iceberg
                PARTITIONED BY (category)
            """
        },
        "orders": {
            "partition_by": "order_date",
            "create_sql": """
                CREATE TABLE IF NOT EXISTS lakehouse.bronze.orders (
                    order_id INT,
                    customer_id INT,
                    order_date STRING,
                    status STRING,
                    num_items INT,
                    subtotal DOUBLE,
                    tax DOUBLE,
                    total_amount DOUBLE,
                    shipping_cost DOUBLE,
                    discount_amount DOUBLE,
                    channel STRING,
                    region STRING,
                    ingestion_ts STRING
                ) USING iceberg
                PARTITIONED BY (order_date)
            """
        },
        "payments": {
            "partition_by": "payment_date",
            "create_sql": """
                CREATE TABLE IF NOT EXISTS lakehouse.bronze.payments (
                    payment_id INT,
                    order_id INT,
                    payment_date STRING,
                    amount DOUBLE,
                    payment_method STRING,
                    status STRING,
                    currency STRING,
                    transaction_ref STRING,
                    ingestion_ts STRING
                ) USING iceberg
                PARTITIONED BY (payment_date)
            """
        },
    }

    tables_to_process = tables_config.keys() if args.table == "all" else [args.table]

    for table in tables_to_process:
        config = tables_config[table]
        landing_path = f"gs://{bucket}/landing/{table}/"

        print(f"=== {table}: Landing → Bronze (Iceberg) ===")

        # Read raw JSONL
        df = spark.read.json(landing_path)
        count = df.count()
        print(f"  Read {count:,} records from landing/{table}/")

        # Add ingestion metadata (only transformation allowed at Bronze)
        df = df.withColumn("ingestion_ts", F.lit(datetime.now(timezone.utc).isoformat()))

        # Create Iceberg table if not exists
        spark.sql(config["create_sql"])

        # Write to Bronze Iceberg table
        df.writeTo(f"lakehouse.bronze.{table}").option("merge-schema", "true").append()
        
        # Verify
        written = spark.sql(f"SELECT COUNT(*) as cnt FROM lakehouse.bronze.{table}").collect()[0]["cnt"]
        print(f"  ✅ Written to lakehouse.bronze.{table} ({written:,} total records)")

    print("\n=== Landing → Bronze complete ===")
    spark.stop()


if __name__ == "__main__":
    main()
