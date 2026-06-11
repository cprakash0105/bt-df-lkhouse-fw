"""Landing → Raw: Ingest JSONL into Raw Iceberg tables (BLMS).

No transformations. Data lands as-is with ingestion timestamp.
All layers are Iceberg tables — queryable, time-travel enabled.
"""

import argparse
from datetime import datetime, timezone
from pyspark.sql import SparkSession
from pyspark.sql import functions as F


TABLES = {
    "customers": """
        CREATE TABLE IF NOT EXISTS lakehouse.raw.customers (
            customer_id INT, name STRING, email STRING, phone STRING,
            address STRING, city STRING, postcode STRING, region STRING,
            loyalty_tier STRING, signup_date STRING, is_active BOOLEAN,
            ingestion_ts STRING
        ) USING iceberg PARTITIONED BY (region)
    """,
    "products": """
        CREATE TABLE IF NOT EXISTS lakehouse.raw.products (
            product_id INT, product_name STRING, category STRING,
            price DOUBLE, cost_price DOUBLE, supplier STRING, sku STRING,
            weight_kg DOUBLE, is_active BOOLEAN, created_date STRING,
            ingestion_ts STRING
        ) USING iceberg PARTITIONED BY (category)
    """,
    "orders": """
        CREATE TABLE IF NOT EXISTS lakehouse.raw.orders (
            order_id INT, customer_id INT, order_date STRING, status STRING,
            num_items INT, subtotal DOUBLE, tax DOUBLE, total_amount DOUBLE,
            shipping_cost DOUBLE, discount_amount DOUBLE, channel STRING,
            region STRING, ingestion_ts STRING
        ) USING iceberg PARTITIONED BY (order_date)
    """,
    "payments": """
        CREATE TABLE IF NOT EXISTS lakehouse.raw.payments (
            payment_id INT, order_id INT, payment_date STRING, amount DOUBLE,
            payment_method STRING, status STRING, currency STRING,
            transaction_ref STRING, ingestion_ts STRING
        ) USING iceberg PARTITIONED BY (payment_date)
    """,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="schema-evolution-poc")
    parser.add_argument("--table", default="all")
    args = parser.parse_args()

    bucket = f"{args.project}-lakehouse"
    spark = SparkSession.builder.appName("LandingToRaw").getOrCreate()
    spark.sql("CREATE NAMESPACE IF NOT EXISTS lakehouse.raw")

    tables = TABLES.keys() if args.table == "all" else [args.table]

    for table in tables:
        print(f"\n=== {table}: Landing → Raw ===")
        df = spark.read.json(f"gs://{bucket}/landing/{table}/")
        df = df.withColumn("ingestion_ts", F.lit(datetime.now(timezone.utc).isoformat()))
        print(f"  Records: {df.count():,}")

        spark.sql(TABLES[table])
        df.writeTo(f"lakehouse.raw.{table}").option("merge-schema", "true").append()
        print(f"  ✅ lakehouse.raw.{table}")

    spark.stop()


if __name__ == "__main__":
    main()
