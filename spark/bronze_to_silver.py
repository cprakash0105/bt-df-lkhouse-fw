"""Bronze to Silver: Cleanse, validate, dedup, write to Iceberg (BLMS).

Processes all 4 tables: customers, products, orders, payments.
Each table gets DQ validation, deduplication, and is written as an Iceberg table
registered in BLMS via BigLakeCatalog.

Usage:
    gcloud dataproc batches submit pyspark gs://schema-evolution-poc-lakehouse/spark/bronze_to_silver.py \
      --jars=gs://spark-lib/biglake/biglake-catalog-iceberg1.9.1-0.1.3-with-dependencies.jar \
      --properties="^::^spark.jars.packages=org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.9.1::spark.sql.catalog.lakehouse=org.apache.iceberg.spark.SparkCatalog::spark.sql.catalog.lakehouse.catalog-impl=org.apache.iceberg.gcp.biglake.BigLakeCatalog::spark.sql.catalog.lakehouse.gcp_project=schema-evolution-poc::spark.sql.catalog.lakehouse.gcp_location=europe-west2::spark.sql.catalog.lakehouse.blms_catalog=schema_poc::spark.sql.catalog.lakehouse.warehouse=gs://schema-evolution-poc-lakehouse" \
      -- --project=schema-evolution-poc
"""

import argparse
from datetime import datetime, timezone
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from pyspark.sql.types import LongType, IntegerType, DoubleType, BooleanType


def create_spark():
    return SparkSession.builder.appName("BronzeToSilver").getOrCreate()


def process_customers(spark, bucket):
    """Bronze → Silver: customers."""
    print("=== Customers: Bronze → Silver ===")
    df = spark.read.parquet(f"gs://{bucket}/bronze/customers/")
    print(f"  Read {df.count():,} records")

    # Schema enforcement
    df = (
        df
        .withColumn("customer_id", F.col("customer_id").cast(IntegerType()))
        .withColumn("is_active", F.col("is_active").cast(BooleanType()))
        .withColumn("processed_ts", F.lit(datetime.now(timezone.utc).isoformat()))
    )

    # DQ: remove nulls on key fields
    passed = df.filter(
        F.col("customer_id").isNotNull()
        & (F.col("customer_id") > 0)
        & F.col("name").isNotNull()
        & F.col("email").isNotNull()
        & F.col("email").contains("@")
    )
    rejected = df.subtract(passed)
    print(f"  Passed DQ: {passed.count():,}, Rejected: {rejected.count():,}")

    # Dedup by customer_id (keep latest signup_date)
    w = Window.partitionBy("customer_id").orderBy(F.desc("signup_date"))
    deduped = passed.withColumn("_rn", F.row_number().over(w)).filter(F.col("_rn") == 1).drop("_rn")
    print(f"  After dedup: {deduped.count():,}")

    # Write to Iceberg
    spark.sql("CREATE NAMESPACE IF NOT EXISTS lakehouse.silver")
    spark.sql("""
        CREATE TABLE IF NOT EXISTS lakehouse.silver.customers (
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
            processed_ts STRING
        ) USING iceberg
        PARTITIONED BY (region)
    """)

    deduped.writeTo("lakehouse.silver.customers").option("merge-schema", "true").append()
    print(f"  ✅ Written to lakehouse.silver.customers")


def process_products(spark, bucket):
    """Bronze → Silver: products."""
    print("=== Products: Bronze → Silver ===")
    df = spark.read.parquet(f"gs://{bucket}/bronze/products/")
    print(f"  Read {df.count():,} records")

    df = (
        df
        .withColumn("product_id", F.col("product_id").cast(IntegerType()))
        .withColumn("price", F.col("price").cast(DoubleType()))
        .withColumn("cost_price", F.col("cost_price").cast(DoubleType()))
        .withColumn("weight_kg", F.col("weight_kg").cast(DoubleType()))
        .withColumn("is_active", F.col("is_active").cast(BooleanType()))
        .withColumn("processed_ts", F.lit(datetime.now(timezone.utc).isoformat()))
    )

    # DQ
    passed = df.filter(
        F.col("product_id").isNotNull()
        & (F.col("product_id") > 0)
        & F.col("product_name").isNotNull()
        & (F.col("price") > 0)
    )
    rejected = df.subtract(passed)
    print(f"  Passed DQ: {passed.count():,}, Rejected: {rejected.count():,}")

    # Dedup by product_id
    w = Window.partitionBy("product_id").orderBy(F.desc("created_date"))
    deduped = passed.withColumn("_rn", F.row_number().over(w)).filter(F.col("_rn") == 1).drop("_rn")
    print(f"  After dedup: {deduped.count():,}")

    spark.sql("""
        CREATE TABLE IF NOT EXISTS lakehouse.silver.products (
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
            processed_ts STRING
        ) USING iceberg
        PARTITIONED BY (category)
    """)

    deduped.writeTo("lakehouse.silver.products").option("merge-schema", "true").append()
    print(f"  ✅ Written to lakehouse.silver.products")


def process_orders(spark, bucket):
    """Bronze → Silver: orders."""
    print("=== Orders: Bronze → Silver ===")
    df = spark.read.parquet(f"gs://{bucket}/bronze/orders/")
    print(f"  Read {df.count():,} records")

    df = (
        df
        .withColumn("order_id", F.col("order_id").cast(IntegerType()))
        .withColumn("customer_id", F.col("customer_id").cast(IntegerType()))
        .withColumn("num_items", F.col("num_items").cast(IntegerType()))
        .withColumn("subtotal", F.col("subtotal").cast(DoubleType()))
        .withColumn("tax", F.col("tax").cast(DoubleType()))
        .withColumn("total_amount", F.col("total_amount").cast(DoubleType()))
        .withColumn("shipping_cost", F.col("shipping_cost").cast(DoubleType()))
        .withColumn("discount_amount", F.col("discount_amount").cast(DoubleType()))
        .withColumn("processed_ts", F.lit(datetime.now(timezone.utc).isoformat()))
    )

    # DQ
    passed = df.filter(
        F.col("order_id").isNotNull()
        & (F.col("order_id") > 0)
        & F.col("customer_id").isNotNull()
        & (F.col("customer_id") > 0)
        & (F.col("total_amount") >= 0)
        & F.col("order_date").isNotNull()
    )
    rejected = df.subtract(passed)
    print(f"  Passed DQ: {passed.count():,}, Rejected: {rejected.count():,}")

    # Dedup by order_id
    w = Window.partitionBy("order_id").orderBy(F.desc("order_date"))
    deduped = passed.withColumn("_rn", F.row_number().over(w)).filter(F.col("_rn") == 1).drop("_rn")
    print(f"  After dedup: {deduped.count():,}")

    spark.sql("""
        CREATE TABLE IF NOT EXISTS lakehouse.silver.orders (
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
            processed_ts STRING
        ) USING iceberg
        PARTITIONED BY (order_date)
    """)

    deduped.writeTo("lakehouse.silver.orders").option("merge-schema", "true").append()
    print(f"  ✅ Written to lakehouse.silver.orders")


def process_payments(spark, bucket):
    """Bronze → Silver: payments."""
    print("=== Payments: Bronze → Silver ===")
    df = spark.read.parquet(f"gs://{bucket}/bronze/payments/")
    print(f"  Read {df.count():,} records")

    df = (
        df
        .withColumn("payment_id", F.col("payment_id").cast(IntegerType()))
        .withColumn("order_id", F.col("order_id").cast(IntegerType()))
        .withColumn("amount", F.col("amount").cast(DoubleType()))
        .withColumn("processed_ts", F.lit(datetime.now(timezone.utc).isoformat()))
    )

    # DQ
    passed = df.filter(
        F.col("payment_id").isNotNull()
        & (F.col("payment_id") > 0)
        & F.col("order_id").isNotNull()
        & (F.col("order_id") > 0)
        & (F.col("amount") > 0)
        & F.col("payment_date").isNotNull()
    )
    rejected = df.subtract(passed)
    print(f"  Passed DQ: {passed.count():,}, Rejected: {rejected.count():,}")

    # Dedup by payment_id
    w = Window.partitionBy("payment_id").orderBy(F.desc("payment_date"))
    deduped = passed.withColumn("_rn", F.row_number().over(w)).filter(F.col("_rn") == 1).drop("_rn")
    print(f"  After dedup: {deduped.count():,}")

    spark.sql("""
        CREATE TABLE IF NOT EXISTS lakehouse.silver.payments (
            payment_id INT,
            order_id INT,
            payment_date STRING,
            amount DOUBLE,
            payment_method STRING,
            status STRING,
            currency STRING,
            transaction_ref STRING,
            processed_ts STRING
        ) USING iceberg
        PARTITIONED BY (payment_date)
    """)

    deduped.writeTo("lakehouse.silver.payments").option("merge-schema", "true").append()
    print(f"  ✅ Written to lakehouse.silver.payments")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="schema-evolution-poc")
    parser.add_argument("--region", default="europe-west2")
    parser.add_argument("--table", default="all", help="Process specific table or 'all'")
    args = parser.parse_args()

    bucket = f"{args.project}-lakehouse"
    spark = create_spark()

    if args.table in ("all", "customers"):
        process_customers(spark, bucket)
    if args.table in ("all", "products"):
        process_products(spark, bucket)
    if args.table in ("all", "orders"):
        process_orders(spark, bucket)
    if args.table in ("all", "payments"):
        process_payments(spark, bucket)

    print("\n=== Bronze → Silver complete ===")
    spark.stop()


if __name__ == "__main__":
    main()
