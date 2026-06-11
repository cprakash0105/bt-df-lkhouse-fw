"""Silver to Gold: Join all tables into a reporting-ready Gold Iceberg table.

Reads customers, orders, payments from Silver Iceberg tables,
joins them, aggregates, and writes to Gold Iceberg table via BLMS.

Gold table: customer_order_summary
- Per customer: total orders, total spend, avg order value, payment stats, loyalty, region

Usage:
    gcloud dataproc batches submit pyspark gs://schema-evolution-poc-lakehouse/spark/silver_to_gold.py \
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
    args = parser.parse_args()

    spark = SparkSession.builder.appName("SilverToGold").getOrCreate()

    print("=== Silver → Gold: Building reporting table ===")

    # Read Silver Iceberg tables
    customers = spark.read.table("lakehouse.silver.customers")
    orders = spark.read.table("lakehouse.silver.orders")
    payments = spark.read.table("lakehouse.silver.payments")

    print(f"  Customers: {customers.count():,}")
    print(f"  Orders: {orders.count():,}")
    print(f"  Payments: {payments.count():,}")

    # Aggregate payments per order
    payment_agg = (
        payments
        .filter(F.col("status") == "completed")
        .groupBy("order_id")
        .agg(
            F.sum("amount").alias("total_paid"),
            F.count("payment_id").alias("payment_count"),
            F.collect_set("payment_method").alias("payment_methods_used"),
        )
    )

    # Join orders with payment aggregation
    orders_enriched = (
        orders
        .join(payment_agg, on="order_id", how="left")
        .withColumn("total_paid", F.coalesce(F.col("total_paid"), F.lit(0.0)))
        .withColumn("payment_count", F.coalesce(F.col("payment_count"), F.lit(0)))
    )

    # Aggregate per customer
    customer_orders = (
        orders_enriched
        .groupBy("customer_id")
        .agg(
            F.count("order_id").alias("total_orders"),
            F.sum("total_amount").alias("total_spend"),
            F.avg("total_amount").alias("avg_order_value"),
            F.sum("total_paid").alias("total_paid"),
            F.sum("payment_count").alias("total_payments"),
            F.sum("discount_amount").alias("total_discounts"),
            F.min("order_date").alias("first_order_date"),
            F.max("order_date").alias("last_order_date"),
            F.countDistinct("channel").alias("channels_used"),
            F.sum(F.when(F.col("status") == "delivered", 1).otherwise(0)).alias("delivered_orders"),
            F.sum(F.when(F.col("status") == "cancelled", 1).otherwise(0)).alias("cancelled_orders"),
            F.sum(F.when(F.col("status") == "returned", 1).otherwise(0)).alias("returned_orders"),
        )
    )

    # Join with customer dimensions
    gold_df = (
        customers
        .select("customer_id", "name", "email", "region", "loyalty_tier", "signup_date", "is_active")
        .join(customer_orders, on="customer_id", how="left")
        .withColumn("total_orders", F.coalesce(F.col("total_orders"), F.lit(0)))
        .withColumn("total_spend", F.coalesce(F.col("total_spend"), F.lit(0.0)))
        .withColumn("avg_order_value", F.coalesce(F.col("avg_order_value"), F.lit(0.0)))
        .withColumn("total_paid", F.coalesce(F.col("total_paid"), F.lit(0.0)))
        .withColumn("total_payments", F.coalesce(F.col("total_payments"), F.lit(0)))
        .withColumn("total_discounts", F.coalesce(F.col("total_discounts"), F.lit(0.0)))
        .withColumn("delivered_orders", F.coalesce(F.col("delivered_orders"), F.lit(0)))
        .withColumn("cancelled_orders", F.coalesce(F.col("cancelled_orders"), F.lit(0)))
        .withColumn("returned_orders", F.coalesce(F.col("returned_orders"), F.lit(0)))
        .withColumn("generated_ts", F.lit(datetime.now(timezone.utc).isoformat()))
    )

    print(f"  Gold records: {gold_df.count():,}")

    # Write to Gold Iceberg
    spark.sql("CREATE NAMESPACE IF NOT EXISTS lakehouse.gold")
    spark.sql("""
        CREATE TABLE IF NOT EXISTS lakehouse.gold.customer_order_summary (
            customer_id INT,
            name STRING,
            email STRING,
            region STRING,
            loyalty_tier STRING,
            signup_date STRING,
            is_active BOOLEAN,
            total_orders BIGINT,
            total_spend DOUBLE,
            avg_order_value DOUBLE,
            total_paid DOUBLE,
            total_payments BIGINT,
            total_discounts DOUBLE,
            first_order_date STRING,
            last_order_date STRING,
            channels_used BIGINT,
            delivered_orders BIGINT,
            cancelled_orders BIGINT,
            returned_orders BIGINT,
            generated_ts STRING
        ) USING iceberg
        PARTITIONED BY (region)
    """)

    gold_df.writeTo("lakehouse.gold.customer_order_summary").overwritePartitions()
    print("  ✅ Written to lakehouse.gold.customer_order_summary")

    # Show summary stats
    print("\n=== Gold Summary ===")
    spark.sql("""
        SELECT region, loyalty_tier, 
               COUNT(*) as customers,
               SUM(total_orders) as orders,
               ROUND(SUM(total_spend), 2) as revenue
        FROM lakehouse.gold.customer_order_summary
        GROUP BY region, loyalty_tier
        ORDER BY revenue DESC
        LIMIT 20
    """).show(truncate=False)

    spark.stop()


if __name__ == "__main__":
    main()
