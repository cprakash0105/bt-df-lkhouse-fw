"""Raw → Curated: Cleanse, validate, dedup, write to Iceberg (BLMS).

Applies DQ rules, type enforcement, deduplication.
Schema evolution handled via merge-schema on write.
"""

import argparse
from datetime import datetime, timezone
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from pyspark.sql.types import IntegerType, DoubleType, BooleanType


def process_customers(spark, bucket):
    print("\n=== Customers: Raw → Curated ===")
    df = spark.read.table("lakehouse.raw.customers")
    print(f"  Read: {df.count():,}")

    df = (
        df
        .withColumn("customer_id", F.col("customer_id").cast(IntegerType()))
        .withColumn("is_active", F.col("is_active").cast(BooleanType()))
        .withColumn("processed_ts", F.lit(datetime.now(timezone.utc).isoformat()))
    )

    passed = df.filter(
        (F.col("customer_id") > 0)
        & F.col("name").isNotNull()
        & F.col("email").contains("@")
    )
    print(f"  Passed DQ: {passed.count():,}")

    w = Window.partitionBy("customer_id").orderBy(F.desc("signup_date"))
    deduped = passed.withColumn("_rn", F.row_number().over(w)).filter(F.col("_rn") == 1).drop("_rn")
    print(f"  After dedup: {deduped.count():,}")

    spark.sql("""
        CREATE TABLE IF NOT EXISTS lakehouse.curated.customers (
            customer_id INT, name STRING, email STRING, phone STRING,
            address STRING, city STRING, postcode STRING, region STRING,
            loyalty_tier STRING, signup_date STRING, is_active BOOLEAN,
            processed_ts STRING
        ) USING iceberg PARTITIONED BY (region)
    """)
    deduped.writeTo("lakehouse.curated.customers").option("merge-schema", "true").append()
    print("  ✅ lakehouse.curated.customers")


def process_products(spark, bucket):
    print("\n=== Products: Raw → Curated ===")
    df = spark.read.table("lakehouse.raw.products")
    print(f"  Read: {df.count():,}")

    df = (
        df
        .withColumn("product_id", F.col("product_id").cast(IntegerType()))
        .withColumn("price", F.col("price").cast(DoubleType()))
        .withColumn("cost_price", F.col("cost_price").cast(DoubleType()))
        .withColumn("processed_ts", F.lit(datetime.now(timezone.utc).isoformat()))
    )

    passed = df.filter((F.col("product_id") > 0) & (F.col("price") > 0) & F.col("product_name").isNotNull())
    print(f"  Passed DQ: {passed.count():,}")

    w = Window.partitionBy("product_id").orderBy(F.desc("created_date"))
    deduped = passed.withColumn("_rn", F.row_number().over(w)).filter(F.col("_rn") == 1).drop("_rn")
    print(f"  After dedup: {deduped.count():,}")

    spark.sql("""
        CREATE TABLE IF NOT EXISTS lakehouse.curated.products (
            product_id INT, product_name STRING, category STRING,
            price DOUBLE, cost_price DOUBLE, supplier STRING, sku STRING,
            weight_kg DOUBLE, is_active BOOLEAN, created_date STRING,
            processed_ts STRING
        ) USING iceberg PARTITIONED BY (category)
    """)
    deduped.writeTo("lakehouse.curated.products").option("merge-schema", "true").append()
    print("  ✅ lakehouse.curated.products")


def process_orders(spark, bucket):
    print("\n=== Orders: Raw → Curated ===")
    df = spark.read.table("lakehouse.raw.orders")
    print(f"  Read: {df.count():,}")

    df = (
        df
        .withColumn("order_id", F.col("order_id").cast(IntegerType()))
        .withColumn("customer_id", F.col("customer_id").cast(IntegerType()))
        .withColumn("total_amount", F.col("total_amount").cast(DoubleType()))
        .withColumn("processed_ts", F.lit(datetime.now(timezone.utc).isoformat()))
    )

    passed = df.filter(
        (F.col("order_id") > 0) & (F.col("customer_id") > 0)
        & (F.col("total_amount") >= 0) & F.col("order_date").isNotNull()
    )
    print(f"  Passed DQ: {passed.count():,}")

    w = Window.partitionBy("order_id").orderBy(F.desc("order_date"))
    deduped = passed.withColumn("_rn", F.row_number().over(w)).filter(F.col("_rn") == 1).drop("_rn")
    print(f"  After dedup: {deduped.count():,}")

    spark.sql("""
        CREATE TABLE IF NOT EXISTS lakehouse.curated.orders (
            order_id INT, customer_id INT, order_date STRING, status STRING,
            num_items INT, subtotal DOUBLE, tax DOUBLE, total_amount DOUBLE,
            shipping_cost DOUBLE, discount_amount DOUBLE, channel STRING,
            region STRING, processed_ts STRING
        ) USING iceberg PARTITIONED BY (order_date)
    """)
    deduped.writeTo("lakehouse.curated.orders").option("merge-schema", "true").append()
    print("  ✅ lakehouse.curated.orders")


def process_payments(spark, bucket):
    print("\n=== Payments: Raw → Curated ===")
    df = spark.read.table("lakehouse.raw.payments")
    print(f"  Read: {df.count():,}")

    df = (
        df
        .withColumn("payment_id", F.col("payment_id").cast(IntegerType()))
        .withColumn("order_id", F.col("order_id").cast(IntegerType()))
        .withColumn("amount", F.col("amount").cast(DoubleType()))
        .withColumn("processed_ts", F.lit(datetime.now(timezone.utc).isoformat()))
    )

    passed = df.filter(
        (F.col("payment_id") > 0) & (F.col("order_id") > 0)
        & (F.col("amount") > 0) & F.col("payment_date").isNotNull()
    )
    print(f"  Passed DQ: {passed.count():,}")

    w = Window.partitionBy("payment_id").orderBy(F.desc("payment_date"))
    deduped = passed.withColumn("_rn", F.row_number().over(w)).filter(F.col("_rn") == 1).drop("_rn")
    print(f"  After dedup: {deduped.count():,}")

    spark.sql("""
        CREATE TABLE IF NOT EXISTS lakehouse.curated.payments (
            payment_id INT, order_id INT, payment_date STRING, amount DOUBLE,
            payment_method STRING, status STRING, currency STRING,
            transaction_ref STRING, processed_ts STRING
        ) USING iceberg PARTITIONED BY (payment_date)
    """)
    deduped.writeTo("lakehouse.curated.payments").option("merge-schema", "true").append()
    print("  ✅ lakehouse.curated.payments")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="schema-evolution-poc")
    parser.add_argument("--table", default="all")
    args = parser.parse_args()

    bucket = f"{args.project}-lakehouse"
    spark = SparkSession.builder.appName("RawToCurated").getOrCreate()
    spark.sql("CREATE NAMESPACE IF NOT EXISTS lakehouse.curated")

    if args.table in ("all", "customers"): process_customers(spark, bucket)
    if args.table in ("all", "products"): process_products(spark, bucket)
    if args.table in ("all", "orders"): process_orders(spark, bucket)
    if args.table in ("all", "payments"): process_payments(spark, bucket)

    print("\n=== Raw → Curated complete ===")
    spark.stop()


if __name__ == "__main__":
    main()
