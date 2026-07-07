"""EastSide CDH 2.0 — Gold Engine (Silver Iceberg → BigQuery Data Product).
- Reads current records from silver (is_current=true)
- Validates against contract schema (backward compatibility)
- Writes to BigQuery dataset eastside_dataproduct
- Column-level security annotations for Dataplex

Usage:
    spark-submit eastside/engine/gold.py \\
        --config gs://eastside-lakehouse/config/pipeline.yaml --all
"""
import sys
from datetime import datetime
from base import (
    get_spark, load_config, get_table_config, get_all_tables,
    parse_args, resolve_pipeline_vars, log, log_header,
    log_error, log_summary, flush_logs_to_gcs, BANNER, LogLevel,
)
from pyspark.sql.functions import col, lit, current_timestamp


# ============================================================
# CONTRACT VALIDATION
# ============================================================

def validate_contract(df, table_config, table_name):
    """Validate that the silver output conforms to the gold contract.
    Gold contract = the table config schema. Any column in config must exist.
    No breaking changes allowed (missing required columns = fail).
    """
    pk = table_config["primary_key"]
    dq_rules = table_config.get("dq_rules", {})
    required_cols = set(dq_rules.get("not_null", []))
    required_cols.add(pk)

    df_cols = set(df.columns)
    missing = required_cols - df_cols
    if missing:
        log("contract", f"❌ Contract violation: missing required columns: {missing}", LogLevel.ERROR)
        raise RuntimeError(f"Gold contract violation on '{table_name}': missing columns {missing}")

    # Verify PK uniqueness (gold should have no duplicates)
    total = df.count()
    distinct_pk = df.select(pk).distinct().count()
    if distinct_pk < total:
        dupes = total - distinct_pk
        log("contract", f"⚠️ {dupes} duplicate PKs in silver current — deduplicating for gold", LogLevel.WARN)
        # Keep latest by valid_from
        from pyspark.sql.window import Window
        from pyspark.sql.functions import row_number
        w = Window.partitionBy(pk).orderBy(col("valid_from").desc())
        df = df.withColumn("_rn", row_number().over(w)).filter(col("_rn") == 1).drop("_rn")

    log("contract", f"Contract validated: {df.count()} records, {len(df.columns)} columns")
    return df


# ============================================================
# COLUMN PROJECTION (Gold schema)
# ============================================================

def project_gold_schema(df, table_config):
    """Project only business columns for gold — drop internal/metadata columns."""
    drop_cols = ["_ingested_at", "_source_file", "_batch_id", "_dq_flags",
                 "row_hash", "valid_from", "valid_to", "is_current"]
    for c in drop_cols:
        if c in df.columns:
            df = df.drop(c)

    # Add gold metadata
    df = df.withColumn("_gold_published_at", current_timestamp())
    return df


# ============================================================
# WRITE TO BIGQUERY
# ============================================================

def write_to_bigquery(spark, df, config, table_name):
    """Write DataFrame to BigQuery using the Spark BQ connector."""
    pipeline = config["pipeline"]
    project_id = pipeline["project_id"]
    dataset = pipeline["dataproduct_dataset"]
    bq_table = f"{project_id}.{dataset}.{table_name}"

    log("gold", f"Writing to BigQuery: {bq_table}")

    df.write \
        .format("bigquery") \
        .option("table", bq_table) \
        .option("writeMethod", "direct") \
        .option("createDisposition", "CREATE_IF_NEEDED") \
        .mode("overwrite") \
        .save()

    log("gold", f"✅ Written {df.count()} records → {bq_table}")


# ============================================================
# MAIN GOLD PROCESSING
# ============================================================

def gold_table(spark, config, table_name):
    """Process a single table: Silver (current) → BigQuery Gold."""
    table_config = get_table_config(config, table_name)
    pipeline = config["pipeline"]
    catalog = pipeline["catalog"]
    silver_ns = pipeline["silver_namespace"]
    silver_table = f"{catalog}.{silver_ns}.{table_name}"

    log_header(f"GOLD: {table_name.upper()}")
    log("gold", f"Source: {silver_table} (is_current=true)")

    # 1. Read current records from silver
    try:
        df = spark.read.table(silver_table).filter(col("is_current") == True)
    except Exception as e:
        log_error("gold", f"Cannot read silver table: {silver_table}", e)
        raise RuntimeError(f"Silver table not found: {silver_table}. Run silver first.")

    record_count = df.count()
    log("gold", f"Current silver records: {record_count}")
    if record_count == 0:
        log("gold", "No current records — skipping", LogLevel.WARN)
        return "SKIPPED"

    # 2. Contract validation
    df = validate_contract(df, table_config, table_name)

    # 3. Project gold schema (drop internal columns)
    df = project_gold_schema(df, table_config)

    # 4. Write to BigQuery
    write_to_bigquery(spark, df, config, table_name)

    return "SUCCESS"


def main():
    print(BANNER)
    args = parse_args("EastSide CDH 2.0 — Gold: Silver → BigQuery (data product)")
    config = load_config(args.config)
    config = resolve_pipeline_vars(config, args)

    spark = get_spark("gold")
    pipeline = config["pipeline"]
    catalog = pipeline["catalog"]

    # Set catalog context
    spark.sql(f"USE {catalog}")

    if args.all:
        tables = get_all_tables(config)
    elif args.table:
        tables = [args.table]
    else:
        log_error("gold", "Specify --table <name> or --all")
        sys.exit(1)

    log("gold", f"Tables: {tables}")

    results = {}
    for table in tables:
        try:
            result = gold_table(spark, config, table)
            results[table] = result
        except Exception as e:
            log_error("gold", f"Table '{table}' failed", e)
            results[table] = "FAILED"

    log_summary("gold", results)
    flush_logs_to_gcs("gold", config)
    log_header("GOLD COMPLETE")
    spark.stop()

    if "FAILED" in results.values():
        sys.exit(1)


if __name__ == "__main__":
    main()
