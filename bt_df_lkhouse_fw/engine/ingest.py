"""bt-df-lkhouse-fw — Ingest Engine (Landing JSONL → Reservoir Parquet).
Writes plain Parquet to GCS. No catalog, no Iceberg at this layer.
Add a new table: drop a YAML into config/tables/ → engine picks it up."""
import sys
from bt_df_lkhouse_fw.engine.base import (
    get_spark, load_config, get_table_config, get_all_tables,
    parse_args, resolve_pipeline_vars, log, log_header, log_table_info,
    log_error, log_summary, flush_logs_to_gcs, BANNER, LogLevel,
)
from bt_df_lkhouse_fw.engine.audit import write_audit
from pyspark.sql.functions import current_timestamp


def ingest_table(spark, config: dict, table_name: str, version: str):
    table_config = get_table_config(config, table_name)
    pipeline = config["pipeline"]

    source_path = f"{pipeline['landing_path']}/{table_name}/{version}"
    target_path = f"{pipeline['reservoir_path']}/{table_name}"

    log_header(f"INGEST: {table_name.upper()} ({version})")
    log("ingest", f"Source: {source_path}")
    log("ingest", f"Target: {target_path} (Parquet)")

    # Read landing data
    try:
        df = spark.read.json(source_path)
    except Exception as e:
        log_error("ingest", f"Cannot read source: {source_path}", e)
        raise RuntimeError(f"Source not found: {source_path}") from e

    source_count = df.count()
    if source_count == 0:
        log("ingest", f"Empty source at {source_path}", LogLevel.WARN)
        raise RuntimeError(f"Empty source: {source_path}")

    log("ingest", f"Source records: {source_count}")

    # Skip if reservoir already has data for v1 (idempotency)
    try:
        existing_count = spark.read.parquet(target_path).count()
    except Exception:
        existing_count = 0

    if existing_count >= source_count and version == "v1":
        log("ingest", f"SKIPPED: Reservoir already has {existing_count} records (source: {source_count})", LogLevel.WARN)
        return "SKIPPED"

    # Add ingestion timestamp
    df = df.withColumn("ingestion_ts", current_timestamp())
    log_table_info(df, table_name)

    # Write Parquet (append mode — allows V1 + V2 to coexist)
    try:
        df.write.mode("append").parquet(target_path)
        log("ingest", f"Written {source_count} records to: {target_path}")
    except Exception as e:
        log_error("ingest", f"Failed to write: {target_path}", e)
        raise

    # Verify
    try:
        total = spark.read.parquet(target_path).count()
        log("ingest", f"Reservoir total: {total} records")
    except Exception as e:
        log("ingest", f"Verification failed (non-fatal): {e}", LogLevel.WARN)


def main():
    print(BANNER)
    args = parse_args("bt-df-lkhouse-fw Ingest: Landing → Reservoir (Parquet)")
    config = load_config(args.config)
    config = resolve_pipeline_vars(config, args)

    spark = get_spark("ingest")

    if args.all:
        tables = get_all_tables(config)
    elif args.table:
        tables = [args.table]
    else:
        log_error("ingest", "Specify --table <name> or --all")
        sys.exit(1)

    log("ingest", f"Tables: {tables}")
    log("ingest", f"Version: {args.version}")

    results = {}
    for table in tables:
        try:
            result = ingest_table(spark, config, table, args.version)
            results[table] = result if result == "SKIPPED" else "SUCCESS"
        except Exception as e:
            log_error("ingest", f"Table '{table}' failed", e)
            results[table] = "FAILED"

    log_summary("ingest", results)
    write_audit(spark, config, "ingest", results, args.version)

    log_header("INGEST COMPLETE")
    flush_logs_to_gcs("ingest", config)
    spark.stop()

    if "FAILED" in results.values():
        sys.exit(1)


if __name__ == "__main__":
    main()
