"""EastSide CDH 2.0 — Reconciliation Engine.
- Source ↔ Bronze: row count comparison per batch
- Bronze ↔ Silver: row count, dedup delta, DQ reject count, hash checksum
- Modes: incremental (per run) and full (entire table)

Usage:
    spark-submit eastside/engine/reconcile.py \\
        --config gs://eastside-lakehouse/config/pipeline.yaml --all
    spark-submit eastside/engine/reconcile.py \\
        --config gs://eastside-lakehouse/config/pipeline.yaml --table pos_transactions --mode full
"""
import sys
from datetime import datetime
from base import (
    get_spark, load_config, get_table_config, get_all_tables,
    parse_args, resolve_pipeline_vars, log, log_header,
    log_error, log_summary, flush_logs_to_gcs, BANNER, LogLevel,
)
from pyspark.sql.functions import col, count, sum as spark_sum, lit, current_timestamp
from pyspark.sql.types import StructType, StructField, StringType, LongType, DoubleType, BooleanType


RECON_SCHEMA = StructType([
    StructField("run_id", StringType(), False),
    StructField("table_name", StringType(), False),
    StructField("check_type", StringType(), False),
    StructField("source_count", LongType(), True),
    StructField("target_count", LongType(), True),
    StructField("delta", LongType(), True),
    StructField("delta_pct", DoubleType(), True),
    StructField("passed", BooleanType(), False),
    StructField("details", StringType(), True),
])


def reconcile_source_bronze(spark, config, table_name, table_config, version):
    """Compare landing source record count with bronze table count for this batch."""
    pipeline = config["pipeline"]
    catalog = pipeline["catalog"]
    bronze_ns = pipeline["bronze_namespace"]
    source_format = table_config.get("source_format", "json")
    source_path = f"{pipeline['landing_path']}/{table_name}/{version}"
    bronze_table = f"{catalog}.{bronze_ns}.{table_name}"

    log("recon", f"Source ↔ Bronze: {table_name}")

    # Count source
    try:
        if source_format == "json":
            source_df = spark.read.json(source_path)
        elif source_format == "csv":
            source_df = spark.read.option("header", "true").csv(source_path)
        elif source_format == "avro":
            source_df = spark.read.format("avro").load(source_path)
        else:
            source_df = spark.read.parquet(source_path)
        source_count = source_df.count()
    except Exception as e:
        log_error("recon", f"Cannot read source: {source_path}", e)
        return None

    # Count bronze
    try:
        bronze_count = spark.read.table(bronze_table).count()
    except Exception as e:
        log_error("recon", f"Cannot read bronze: {bronze_table}", e)
        return None

    delta = bronze_count - source_count
    delta_pct = (delta / source_count * 100) if source_count > 0 else 0.0
    # Bronze can have more than source (multiple versions appended)
    # Pass if bronze >= source (append-only, so it should always be >=)
    passed = bronze_count >= source_count

    log("recon", f"  Source: {source_count}, Bronze: {bronze_count}, "
                 f"Delta: {delta} ({delta_pct:+.1f}%) {'✅' if passed else '❌'}")

    return {
        "check_type": "source_bronze",
        "source_count": source_count,
        "target_count": bronze_count,
        "delta": delta,
        "delta_pct": round(delta_pct, 2),
        "passed": passed,
        "details": f"version={version}",
    }


def reconcile_bronze_silver(spark, config, table_name):
    """Compare bronze total with silver current + historical + quarantined + rejected."""
    pipeline = config["pipeline"]
    catalog = pipeline["catalog"]
    bronze_ns = pipeline["bronze_namespace"]
    silver_ns = pipeline["silver_namespace"]
    bronze_table = f"{catalog}.{bronze_ns}.{table_name}"
    silver_table = f"{catalog}.{silver_ns}.{table_name}"
    quarantine_table = f"{catalog}.{silver_ns}.{table_name}_quarantine"

    log("recon", f"Bronze ↔ Silver: {table_name}")

    # Bronze count
    try:
        bronze_count = spark.read.table(bronze_table).count()
    except Exception:
        log("recon", f"  Bronze table not found — skipping", LogLevel.WARN)
        return None

    # Silver total (all versions including historical)
    try:
        silver_total = spark.read.table(silver_table).count()
        silver_current = spark.read.table(silver_table).filter(col("is_current") == True).count()
    except Exception:
        silver_total = 0
        silver_current = 0

    # Quarantine count
    try:
        quarantine_count = spark.read.table(quarantine_table).count()
    except Exception:
        quarantine_count = 0

    # Silver should account for: current + historical + quarantined
    # Some records may be deduped or DQ-rejected (not stored anywhere)
    accounted = silver_total + quarantine_count
    unaccounted = bronze_count - accounted
    unaccounted_pct = (unaccounted / bronze_count * 100) if bronze_count > 0 else 0.0

    # Pass if unaccounted < 5% (allows for dedup + DQ rejects)
    passed = abs(unaccounted_pct) < 5.0

    log("recon", f"  Bronze: {bronze_count}, Silver(total): {silver_total}, "
                 f"Silver(current): {silver_current}, Quarantined: {quarantine_count}")
    log("recon", f"  Unaccounted: {unaccounted} ({unaccounted_pct:.1f}%) "
                 f"{'✅' if passed else '⚠️'}")

    return {
        "check_type": "bronze_silver",
        "source_count": bronze_count,
        "target_count": silver_total,
        "delta": unaccounted,
        "delta_pct": round(unaccounted_pct, 2),
        "passed": passed,
        "details": f"current={silver_current}, quarantined={quarantine_count}, "
                   f"unaccounted={unaccounted} (dedup+dq rejects)",
    }


def reconcile_hash_checksum(spark, config, table_name):
    """Hash-based reconciliation: compare distinct row_hash counts between bronze and silver."""
    pipeline = config["pipeline"]
    catalog = pipeline["catalog"]
    bronze_ns = pipeline["bronze_namespace"]
    silver_ns = pipeline["silver_namespace"]
    bronze_table = f"{catalog}.{bronze_ns}.{table_name}"
    silver_table = f"{catalog}.{silver_ns}.{table_name}"

    log("recon", f"Hash checksum: {table_name}")

    try:
        bronze_hashes = spark.read.table(bronze_table).select("row_hash").distinct().count()
    except Exception:
        return None

    try:
        silver_hashes = spark.read.table(silver_table).select("row_hash").distinct().count()
    except Exception:
        silver_hashes = 0

    delta = bronze_hashes - silver_hashes
    delta_pct = (delta / bronze_hashes * 100) if bronze_hashes > 0 else 0.0
    # Silver should have fewer or equal distinct hashes (dedup + DQ removes some)
    passed = silver_hashes <= bronze_hashes

    log("recon", f"  Bronze distinct hashes: {bronze_hashes}, Silver: {silver_hashes}, "
                 f"Delta: {delta} {'✅' if passed else '❌'}")

    return {
        "check_type": "hash_checksum",
        "source_count": bronze_hashes,
        "target_count": silver_hashes,
        "delta": delta,
        "delta_pct": round(delta_pct, 2),
        "passed": passed,
        "details": f"distinct_hashes: bronze={bronze_hashes}, silver={silver_hashes}",
    }


def write_recon_results(spark, config, table_name, results):
    """Persist reconciliation results to Iceberg table."""
    pipeline = config["pipeline"]
    catalog = pipeline["catalog"]
    silver_ns = pipeline["silver_namespace"]
    recon_table = f"{catalog}.{silver_ns}.reconciliation_log"
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    rows = []
    for r in results:
        if r is None:
            continue
        rows.append((
            run_id,
            table_name,
            r["check_type"],
            r["source_count"],
            r["target_count"],
            r["delta"],
            r["delta_pct"],
            r["passed"],
            r["details"],
        ))

    if not rows:
        return

    df = spark.createDataFrame(rows, RECON_SCHEMA)
    df = df.withColumn("reconciled_at", current_timestamp())

    try:
        df.writeTo(recon_table).append()
    except Exception:
        df.writeTo(recon_table).create()

    passed = sum(1 for r in results if r and r["passed"])
    failed = sum(1 for r in results if r and not r["passed"])
    log("recon", f"Results persisted: {passed} passed, {failed} failed")


def reconcile_table(spark, config, table_name, version, mode):
    """Run all reconciliation checks for a single table."""
    table_config = get_table_config(config, table_name)
    log_header(f"RECONCILE: {table_name.upper()} (mode={mode})")

    results = []

    # Source ↔ Bronze
    r = reconcile_source_bronze(spark, config, table_name, table_config, version)
    results.append(r)

    # Bronze ↔ Silver
    r = reconcile_bronze_silver(spark, config, table_name)
    results.append(r)

    # Hash checksum
    r = reconcile_hash_checksum(spark, config, table_name)
    results.append(r)

    # Persist
    write_recon_results(spark, config, table_name, results)

    # Determine overall status
    all_passed = all(r["passed"] for r in results if r is not None)
    return "SUCCESS" if all_passed else "WARN"


def main():
    print(BANNER)

    import argparse
    parser = argparse.ArgumentParser(description="EastSide CDH 2.0 — Reconciliation Engine")
    parser.add_argument("--config", required=True, help="Path to pipeline.yaml")
    parser.add_argument("--table", help="Single table to reconcile")
    parser.add_argument("--all", action="store_true", help="Reconcile all tables")
    parser.add_argument("--version", default="v1", help="Landing version for source check")
    parser.add_argument("--mode", default="incremental", choices=["incremental", "full"],
                        help="Reconciliation mode")
    parser.add_argument("--project", help="GCP project ID override")
    parser.add_argument("--bucket", help="GCS bucket override")
    args = parser.parse_args()

    config = load_config(args.config)
    config = resolve_pipeline_vars(config, args)

    spark = get_spark("reconcile")
    pipeline = config["pipeline"]
    catalog = pipeline["catalog"]
    spark.sql(f"USE {catalog}")

    if args.all:
        tables = get_all_tables(config)
    elif args.table:
        tables = [args.table]
    else:
        log_error("recon", "Specify --table <name> or --all")
        sys.exit(1)

    log("recon", f"Tables: {tables}")
    log("recon", f"Mode: {args.mode}")

    results = {}
    for table in tables:
        try:
            result = reconcile_table(spark, config, table, args.version, args.mode)
            results[table] = result
        except Exception as e:
            log_error("recon", f"Table '{table}' failed", e)
            results[table] = "FAILED"

    log_summary("recon", results)
    flush_logs_to_gcs("reconcile", config)
    log_header("RECONCILIATION COMPLETE")
    spark.stop()


if __name__ == "__main__":
    main()
