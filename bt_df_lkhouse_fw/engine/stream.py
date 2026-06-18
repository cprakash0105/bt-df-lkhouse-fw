"""bt-df-lkhouse-fw — Stream Engine (Kafka → CCN Iceberg).
Spark Structured Streaming: reads from Confluent Kafka, applies DQ inline,
writes directly to CCN Iceberg tables via BLMS.

Runs as a long-lived Dataproc Serverless batch.

Usage (via run_stream.sh):
    --config gs://bucket/framework/config/pipeline.yaml
    --kafka-config gs://bucket/framework/confluent/kafka.yaml
    --table clickstream
    --trigger-interval 30s
"""
import sys
import yaml
from bt_df_lkhouse_fw.engine.base import (
    get_spark, load_config, get_table_config,
    parse_args, resolve_pipeline_vars, log, log_header,
    log_error, flush_logs_to_gcs, BANNER, LogLevel,
)
from pyspark.sql.functions import from_json, col, current_timestamp, expr
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, TimestampType
)


# Schemas for streaming tables (V2 fields included as nullable)
STREAM_SCHEMAS = {
    "clickstream": StructType([
        StructField("event_id", StringType(), False),
        StructField("customer_id", IntegerType(), True),
        StructField("event_type", StringType(), True),
        StructField("page_url", StringType(), True),
        StructField("product_id", IntegerType(), True),
        StructField("event_timestamp", StringType(), True),
        StructField("session_id", StringType(), True),
        StructField("device_type", StringType(), True),
        StructField("browser", StringType(), True),
        StructField("referrer", StringType(), True),
    ]),
    "transactions_stream": StructType([
        StructField("transaction_id", StringType(), False),
        StructField("order_id", IntegerType(), True),
        StructField("customer_id", IntegerType(), True),
        StructField("amount", StringType(), True),
        StructField("currency", StringType(), True),
        StructField("transaction_type", StringType(), True),
        StructField("status", StringType(), True),
        StructField("payment_method", StringType(), True),
        StructField("event_timestamp", StringType(), True),
        StructField("risk_score", StringType(), True),
        StructField("gateway", StringType(), True),
    ]),
}

# Map table name to Kafka topic key in kafka.yaml
TABLE_TOPIC_MAP = {
    "clickstream": "clickstream",
    "transactions_stream": "transactions",
}


def load_kafka_config(spark, kafka_config_path: str) -> dict:
    """Load Kafka connection config from local path or GCS."""
    if kafka_config_path.startswith("gs://"):
        from google.cloud import storage as gcs_storage
        parts = kafka_config_path.replace("gs://", "").split("/", 1)
        client = gcs_storage.Client()
        blob = client.bucket(parts[0]).blob(parts[1])
        config = yaml.safe_load(blob.download_as_text())
    else:
        with open(kafka_config_path, "r") as f:
            config = yaml.safe_load(f)
    return config


def apply_stream_dq(df, table_config: dict):
    """Apply DQ rules inline on streaming DataFrame (filter-based)."""
    dq_rules = table_config.get("dq_rules", {})

    for col_name in dq_rules.get("not_null", []):
        if col_name in df.columns:
            df = df.filter(col(col_name).isNotNull())

    for col_name, values in dq_rules.get("accepted_values", {}).items():
        if col_name in df.columns:
            df = df.filter(col(col_name).isin(values) | col(col_name).isNull())

    return df


def main():
    print(BANNER)

    # Extended args for streaming
    import argparse
    parser = argparse.ArgumentParser(description="bt-df-lkhouse-fw Stream: Kafka → CCN Iceberg")
    parser.add_argument("--config", required=True, help="Path to pipeline.yaml")
    parser.add_argument("--kafka-config", required=True, help="Path to kafka.yaml")
    parser.add_argument("--table", default="clickstream", help="Table name")
    parser.add_argument("--trigger-interval", default="30 seconds", help="Micro-batch trigger interval")
    parser.add_argument("--project", help="GCP project ID")
    parser.add_argument("--bucket", help="GCS bucket")
    parser.add_argument("--json-logs", action="store_true")
    args = parser.parse_args()

    if args.json_logs:
        from bt_df_lkhouse_fw.engine.base import enable_json_logging
        enable_json_logging()

    config = load_config(args.config)
    # Resolve vars using a minimal namespace object
    class Args:
        project = args.project
        bucket = args.bucket
    config = resolve_pipeline_vars(config, Args())

    pipeline = config["pipeline"]
    table_config = get_table_config(config, args.table)

    catalog = pipeline["catalog"]
    ns_ccn = pipeline["ccn_namespace"]
    bucket = pipeline["bucket"]
    target_table = f"{catalog}.{ns_ccn}.{args.table}"

    log_header(f"STREAM: {args.table.upper()} (Kafka → Iceberg)")
    log("stream", f"Target: {target_table}")
    log("stream", f"Trigger: {args.trigger_interval}")

    spark = get_spark("stream")
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{ns_ccn}")

    # Load Kafka connection
    kafka_config = load_kafka_config(spark, args.kafka_config)
    kafka_options = kafka_config.get("kafka_options", {})

    # Resolve topic from config
    topic_key = TABLE_TOPIC_MAP.get(args.table, args.table)
    kafka_topic = kafka_config.get("topics", {}).get(topic_key, f"ecommerce.{topic_key}")
    kafka_options["subscribe"] = kafka_topic

    log("stream", f"Kafka bootstrap: {kafka_options.get('kafka.bootstrap.servers', 'unknown')}")
    log("stream", f"Topic: {kafka_topic}")

    # Get schema for this table
    stream_schema = STREAM_SCHEMAS.get(args.table)
    if not stream_schema:
        log_error("stream", f"No schema defined for table '{args.table}'. Available: {list(STREAM_SCHEMAS.keys())}")
        sys.exit(1)

    # Read stream from Kafka
    raw_stream = (
        spark.readStream
        .format("kafka")
        .options(**kafka_options)
        .load()
    )

    # Parse JSON value
    parsed_stream = (
        raw_stream
        .selectExpr("CAST(value AS STRING) as json_value")
        .select(from_json(col("json_value"), stream_schema).alias("data"))
        .select("data.*")
        .withColumn("ingestion_ts", current_timestamp())
    )

    # Ensure target Iceberg table exists (create empty if not)
    try:
        spark.read.table(target_table)
        log("stream", f"Table {target_table} exists")
    except Exception:
        log("stream", f"Table {target_table} not found — creating from schema")
        empty_df = spark.createDataFrame([], stream_schema)
        from pyspark.sql.functions import current_timestamp as _ct
        empty_df = empty_df.withColumn("ingestion_ts", _ct())
        empty_df.writeTo(target_table).create()
        log("stream", f"Created empty table: {target_table}")

    # Apply DQ
    clean_stream = apply_stream_dq(parsed_stream, table_config)

    # Write to Iceberg (CCN)
    checkpoint_path = f"gs://{bucket}/checkpoints/{args.table}"
    log("stream", f"Checkpoint: {checkpoint_path}")

    query = (
        clean_stream.writeStream
        .format("iceberg")
        .outputMode("append")
        .trigger(processingTime=args.trigger_interval)
        .option("path", target_table)
        .option("checkpointLocation", checkpoint_path)
        .option("merge-schema", "true")
        .start()
    )

    log("stream", "✅ Streaming query started — awaiting termination")
    log("stream", f"Query ID: {query.id}")
    log("stream", f"Query name: {query.name}")

    flush_logs_to_gcs("stream", config)

    # Block until terminated
    query.awaitTermination()


if __name__ == "__main__":
    main()
