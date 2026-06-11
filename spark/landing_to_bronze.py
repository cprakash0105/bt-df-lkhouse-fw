"""Landing to Bronze: Convert JSONL to Parquet (no transformation).

Raw data lands as-is in Parquet format. No schema enforcement, no DQ.
This is the immutable raw layer.

Usage:
    gcloud dataproc batches submit pyspark gs://schema-evolution-poc-lakehouse/spark/landing_to_bronze.py ...
    -- --project=schema-evolution-poc
"""

import argparse
from pyspark.sql import SparkSession


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="schema-evolution-poc")
    parser.add_argument("--region", default="europe-west2")
    args = parser.parse_args()

    bucket = f"{args.project}-lakehouse"
    spark = SparkSession.builder.appName("LandingToBronze").getOrCreate()

    tables = ["customers", "products", "orders", "payments"]

    for table in tables:
        landing_path = f"gs://{bucket}/landing/{table}/"
        bronze_path = f"gs://{bucket}/bronze/{table}/"

        print(f"=== {table}: Landing → Bronze ===")
        df = spark.read.json(landing_path)
        count = df.count()
        print(f"  Read {count:,} records from landing/{table}/")

        df.write.mode("overwrite").parquet(bronze_path)
        print(f"  Written to bronze/{table}/ as Parquet")

    print("\n=== Landing → Bronze complete ===")
    spark.stop()


if __name__ == "__main__":
    main()
