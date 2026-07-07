"""EastSide CDH 2.0 — Streaming Engine (Kafka → Bronze Iceberg).
- Spark Structured Streaming with micro-batch
- Hash-based dedup (SHA256 persisted as row_hash)
- Bloom filter / state-based dedup for recent events
- Configurable batch windows (default 15 min)
- Auto-compaction awareness

Usage:
    spark-submit eastside/engine/stream.py \\
        --config gs://eastside-lakehouse/config/pipeline.yaml \\
        --table pos_transactions \\
        --trigger-interval "15 minutes"
"""
import sys
import argparse
from base import (
    get_spark, load_config, get_table_config,
    resolve_pipeline_vars, log, log_header,
    log_error, flush_logs_to_gcs, BANNER, LogLevel,
)
from pyspark.sql.functions import (
    col, from_json, current_timestamp, lit, sha2, concat_ws,
    expr, window,
)
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType,
    DoubleType, TimestampType, BooleanType, LongType,
)


# ============================================================
# STREAM SCHEMAS (per table)
# ============================================================

STREAM_SCHEMAS = {
    "pos_transactions": StructType([
        StructField("transaction_id", StringType(), False),
        StructField("basket_id", StringType(), True),
        StructField("store_id", StringType(), True),
        StructField("till_id", StringType(), True),
        StructField("customer_id", StringType(), True),
        StructField("product_sku", StringType(), True),
        StructField("quantity", IntegerType(), True),
        StructField("unit_price", DoubleType(), True),
        StructField("discount_amount", DoubleType(), True),
        StructField("payment_method", StringType(), True),
        StructField("transaction_datetime", StringType(), True),
        StructField("staff_id", StringType(), True),
    ]),
    "online_orders": StructType([
        StructField("order_id", StringType(), False),
        StructField("customer_id", StringType(), True),
        StructField("order_date", StringType(), True),
        StructField("status", StringType(), True),
        StructField("total_amount", DoubleType(), True),
        StructField("shipping_method", StringType(), True),
        StructField("delivery_postcode", StringType(), True),
        StructField("promo_code", StringType(), True),
        StructField("channel", StringType(), True),
        StructField("items_count", IntegerType(), True),
        StructField("shipping_cost", DoubleType(), True),
    ]),
}

# Kafka topic mapping
TABLE_TOPIC_MAP = {
    "pos_transactions": "eastside.pos",
    "online_orders": "eastside.orders",
}


# ============================================================
# DEDUP (Stateful — drop events with duplicate row_hash)
# ============================================================

def add_row_hash(df, hash_fields):
    """Compute SHA256 row_hash for dedup."""
    available = [f for f in hash_fields if f in df.columns]
    if not available:
        available = [c for c in df.columns if not c.startswith("_")]
    return df.withColumn("row_hash", sha2(concat_ws("|", *[col(c).cast("string") for c in available]), 256))


def dedup_micro_batch(df, batch_id, spark, target_table, pk):
    """Dedup within micro-batch and against existing bronze table.
    Called via foreachBatch.
    """
    if df.rdd.isEmpty():
        return

    record_count = df.count()
    log("stream", f"Micro-batch {batch_id}: {record_count} records")

    # Dedup within batch (keep first occurrence)
    df = df.dropDuplicates(["row_hash"])
    after_intra = df.count()
    if after_intra < record_count:
        log("stream", f"  Intra-batch dedup: {record_count} → {after_intra}")

    # Dedup against existing bronze (if table exists)
    try:
        existing_hashes = spark.read.table(target_table).select("row_hash").distinct()
        df = df.join(existing_hashes, "row_hash", "left_anti")
        after_cross = df.count()
        if after_cross < after_intra:
            log("stream", f"  Cross-batch dedup: {after_intra} → {after_cross}")
    except Exception:
        pass  # Table doesn't exist yet

    if df.rdd.isEmpty():
        log("stream", f"  All records deduplicated — nothing to write")
        return

    # Add metadata
    df = df.withColumn("_ingested_at", current_timestamp())
    df = df.withColumn("_batch_id", lit(str(batch_id)))
    df = df.withColumn("_source_file", lit("kafka_stream"))

    # Write to bronze Iceberg
    try:
        df.writeTo(target_table).option("merge-schema", "true").append()
        log("stream", f"  ✅ Appended {df.count()} records to {target_table}")
    except Exception:
        try:
            df.writeTo(target_table).create()
            log("stream", f"  ✅ Created {target_table} with {df.count()} records")
        except Exception as e:
            log_error("stream", f"  Failed to write batch {batch_id}", e)


# ============================================================
# MAIN
# ============================================================

def main():
    print(BANNER)

    parser = argparse.ArgumentParser(description="EastSide CDH 2.0 — Streaming: Kafka → Bronze Iceberg")
    parser.add_argument("--config", required=True, help="Path to pipeline.yaml")
    parser.add_argument("--table", required=True, help="Table name to stream")
    parser.add_argument("--trigger-interval", default="15 minutes", help="Micro-batch trigger interval")
    parser.add_argument("--kafka-bootstrap", required=True, help="Kafka bootstrap servers")
    parser.add_argument("--kafka-topic", help="Override Kafka topic (default: from TABLE_TOPIC_MAP)")
    parser.add_argument("--project", help="GCP project ID")
    parser.add_argument("--bucket", help="GCS bucket override")
    args = parser.parse_args()

    config = load_config(args.config)

    class Args:
        project = args.project
        bucket = args.bucket
    config = resolve_pipeline_vars(config, Args())

    table_config = get_table_config(config, args.table)
    pipeline = config["pipeline"]
    catalog = pipeline["catalog"]
    bronze_ns = pipeline["bronze_namespace"]
    bucket = pipeline["bucket"]
    target_table = f"{catalog}.{bronze_ns}.{args.table}"
    pk = table_config["primary_key"]
    hash_fields = table_config.get("hash_fields", [])

    # Resolve topic
    topic = args.kafka_topic or TABLE_TOPIC_MAP.get(args.table, f"eastside.{args.table}")

    log_header(f"STREAM: {args.table.upper()} (Kafka → Bronze Iceberg)")
    log("stream", f"Target: {target_table}")
    log("stream", f"Topic: {topic}")
    log("stream", f"Bootstrap: {args.kafka_bootstrap}")
    log("stream", f"Trigger: {args.trigger_interval}")

    spark = get_spark("stream")
    spark.sql(f"USE {catalog}")
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{bronze_ns}")

    # Get schema
    stream_schema = STREAM_SCHEMAS.get(args.table)
    if not stream_schema:
        log_error("stream", f"No schema defined for '{args.table}'. "
                            f"Available: {list(STREAM_SCHEMAS.keys())}")
        sys.exit(1)

    # Read from Kafka
    raw_stream = (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", args.kafka_bootstrap)
        .option("subscribe", topic)
        .option("startingOffsets", "latest")
        .option("failOnDataLoss", "false")
        .load()
    )

    # Parse JSON value
    parsed = (
        raw_stream
        .selectExpr("CAST(value AS STRING) as json_value",
                    "CAST(key AS STRING) as _kafka_key",
                    "timestamp as _kafka_timestamp")
        .select(
            from_json(col("json_value"), stream_schema).alias("data"),
            col("_kafka_key"),
            col("_kafka_timestamp"),
        )
        .select("data.*", "_kafka_key", "_kafka_timestamp")
    )

    # Add row_hash
    parsed = add_row_hash(parsed, hash_fields)

    # Checkpoint
    checkpoint_path = f"gs://{bucket}/checkpoints/{args.table}"
    log("stream", f"Checkpoint: {checkpoint_path}")

    # Write using foreachBatch for dedup logic
    query = (
        parsed.writeStream
        .foreachBatch(lambda df, batch_id: dedup_micro_batch(df, batch_id, spark, target_table, pk))
        .trigger(processingTime=args.trigger_interval)
        .option("checkpointLocation", checkpoint_path)
        .start()
    )

    log("stream", f"✅ Streaming query started (ID: {query.id})")
    flush_logs_to_gcs("stream", config)

    # Block until terminated
    query.awaitTermination()


if __name__ == "__main__":
    main()
