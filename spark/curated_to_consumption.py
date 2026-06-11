"""Curated → Consumption: Build reporting-ready customer_360 table.

Joins customers + orders + payments from Curated layer.
Aggregates into a single customer-level reporting table.
"""

import argparse
from datetime import datetime, timezone
from pyspark.sql import SparkSession
from pyspark.sql import functions as F


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="schema-evolution-poc")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("CuratedToConsumption").getOrCreate()

    print("=== Curated → Consumption: customer_360 ===")

    customers = spark.read.table("lakehouse.curated.customers")
    orders = spark.read.table("lakehouse.curated.orders")
    payments = spark.read.table("lakehouse.curated.payments")

    print(f"  Customers: {customers.count():,}")
    print(f"  Orders:    {orders.count():,}")
    print(f"  Payments:  {payments.count():,}")

    # Aggregate payments per order
    payment_agg = (
        payments
        .filter(F.col("status") == "completed")
        .groupBy("order_id")
        .agg(
            F.sum("amount").alias("total_paid"),
            F.count("payment_id").alias("payment_count"),
        )
    )

    # Enrich orders with payment data
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
            F.round(F.avg("total_amount"), 2).alias("avg_order_value"),
            F.sum("total_paid").alias("total_paid"),
            F.sum("payment_count").alias("total_payments"),
            F.round(F.sum("discount_amount"), 2).alias("total_discounts"),
            F.min("order_date").alias("first_order_date"),
            F.max("order_date").alias("last_order_date"),
            F.countDistinct("channel").alias("channels_used"),
            F.sum(F.when(F.col("status") == "delivered", 1).otherwise(0)).alias("delivered_orders"),
            F.sum(F.when(F.col("status") == "cancelled", 1).otherwise(0)).alias("cancelled_orders"),
            F.sum(F.when(F.col("status") == "returned", 1).otherwise(0)).alias("returned_orders"),
        )
    )

    # Join with customer dimensions
    customer_360 = (
        customers
        .select("customer_id", "name", "email", "region", "loyalty_tier",
                "signup_date", "is_active", "city", "postcode")
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

    print(f"  Customer 360 records: {customer_360.count():,}")

    # Write to Consumption layer
    spark.sql("CREATE NAMESPACE IF NOT EXISTS lakehouse.consumption")
    spark.sql("""
        CREATE TABLE IF NOT EXISTS lakehouse.consumption.customer_360 (
            customer_id INT, name STRING, email STRING, region STRING,
            loyalty_tier STRING, signup_date STRING, is_active BOOLEAN,
            city STRING, postcode STRING,
            total_orders BIGINT, total_spend DOUBLE, avg_order_value DOUBLE,
            total_paid DOUBLE, total_payments BIGINT, total_discounts DOUBLE,
            first_order_date STRING, last_order_date STRING, channels_used BIGINT,
            delivered_orders BIGINT, cancelled_orders BIGINT, returned_orders BIGINT,
            generated_ts STRING
        ) USING iceberg PARTITIONED BY (region)
    """)

    customer_360.writeTo("lakehouse.consumption.customer_360").overwritePartitions()
    print("  ✅ lakehouse.consumption.customer_360")

    # Summary
    print("\n=== Summary by Region & Loyalty ===")
    spark.sql("""
        SELECT region, loyalty_tier, COUNT(*) as customers,
               SUM(total_orders) as orders, ROUND(SUM(total_spend), 2) as revenue
        FROM lakehouse.consumption.customer_360
        GROUP BY region, loyalty_tier
        ORDER BY revenue DESC LIMIT 20
    """).show(truncate=False)

    spark.stop()


if __name__ == "__main__":
    main()
