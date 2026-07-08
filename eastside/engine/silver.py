"""EastSide CDH 2.0 — Silver Engine (Bronze Iceberg → Silver Iceberg).
- Reads new records from bronze (incremental via _ingested_at)
- Dedup using row_hash
- Applies preventative DQ (reject bad records)
- Applies policy controls (mask, strip non-printable, standardise)
- Late arrival handling (within window → merge, outside → quarantine)
- Merges into silver with SCD2 (valid_from, valid_to, is_current)
- Schema evolution: non-breaking only

Usage:
    spark-submit eastside/engine/silver.py \\
        --config gs://eastside-lakehouse/config/pipeline.yaml --all
"""
import sys
import re
import hashlib
from datetime import datetime, timedelta
from base import (
    get_spark, load_config, get_table_config, get_all_tables,
    parse_args, resolve_pipeline_vars, log, log_header,
    log_error, log_summary, flush_logs_to_gcs, BANNER, LogLevel,
)
from pyspark.sql.functions import (
    col, lit, current_timestamp, when, coalesce, sha2, concat_ws,
    regexp_replace, trim, upper, to_timestamp, row_number,
)
from pyspark.sql.window import Window
from pyspark.sql.types import TimestampType


# ============================================================
# DEDUP
# ============================================================

def dedup_by_hash(df, spark, target_table):
    """Remove records whose row_hash already exists in silver."""
    try:
        existing_hashes = spark.read.table(target_table).select("row_hash").distinct()
        before = df.count()
        df = df.join(existing_hashes, "row_hash", "left_anti")
        after = df.count()
        dupes = before - after
        if dupes > 0:
            log("dedup", f"Removed {dupes} duplicates (hash match)")
        else:
            log("dedup", "No duplicates found")
    except Exception:
        log("dedup", "No existing silver table — skipping dedup check")
    return df


# ============================================================
# PREVENTATIVE DQ
# ============================================================

def apply_preventative_dq(df, table_config):
    """Enforce DQ rules — reject records that fail critical checks."""
    dq_rules = table_config.get("dq_rules", {})
    pk = table_config["primary_key"]
    initial = df.count()
    rejected_total = 0

    # NOT NULL on primary key is always enforced
    if pk in df.columns:
        before = df.count()
        df = df.filter(col(pk).isNotNull())
        rej = before - df.count()
        if rej > 0:
            log("dq", f"NOT_NULL({pk}): rejected {rej}")
            rejected_total += rej

    # NOT NULL on configured fields
    for col_name in dq_rules.get("not_null", []):
        if col_name in df.columns and col_name != pk:
            before = df.count()
            df = df.filter(col(col_name).isNotNull())
            rej = before - df.count()
            if rej > 0:
                log("dq", f"NOT_NULL({col_name}): rejected {rej}")
                rejected_total += rej

    # POSITIVE
    for col_name in dq_rules.get("positive", []):
        if col_name in df.columns:
            before = df.count()
            df = df.filter((col(col_name) > 0) | col(col_name).isNull())
            rej = before - df.count()
            if rej > 0:
                log("dq", f"POSITIVE({col_name}): rejected {rej}")
                rejected_total += rej

    # ACCEPTED VALUES
    for col_name, values in dq_rules.get("accepted_values", {}).items():
        if col_name in df.columns:
            before = df.count()
            df = df.filter(col(col_name).isin(values) | col(col_name).isNull())
            rej = before - df.count()
            if rej > 0:
                log("dq", f"ACCEPTED_VALUES({col_name}): rejected {rej}")
                rejected_total += rej

    final = df.count()
    log("dq", f"Preventative DQ: {initial} → {final} ({rejected_total} rejected)")
    return df


# ============================================================
# POLICY CONTROLS
# ============================================================

def apply_masking(df, table_config):
    """Apply SHA256 masking on configured PII fields."""
    masking_config = table_config.get("masking", {})
    for col_name, method in masking_config.items():
        if col_name in df.columns:
            if method == "sha256":
                df = df.withColumn(col_name, sha2(col(col_name).cast("string"), 256))
                log("policy", f"Masked {col_name} (SHA256)")
            elif method == "tokenise":
                # Simple tokenisation: first 2 chars + hash suffix
                df = df.withColumn(col_name,
                    concat_ws("", col(col_name).substr(1, 2), lit("***"),
                              sha2(col(col_name).cast("string"), 256).substr(1, 8)))
                log("policy", f"Tokenised {col_name}")
    return df


def strip_non_printable(df):
    """Remove non-printable characters from all string columns."""
    string_cols = [f.name for f in df.schema.fields if f.dataType.simpleString() == "string"
                   and not f.name.startswith("_") and f.name != "row_hash"]
    for col_name in string_cols:
        df = df.withColumn(col_name, regexp_replace(col(col_name), r"[^\x20-\x7E\xA0-\xFF]", ""))
    if string_cols:
        log("policy", f"Stripped non-printable chars from {len(string_cols)} string columns")
    return df


def standardise_fields(df):
    """Trim whitespace from strings, uppercase postcodes."""
    string_cols = [f.name for f in df.schema.fields if f.dataType.simpleString() == "string"
                   and not f.name.startswith("_") and f.name != "row_hash"]
    for col_name in string_cols:
        df = df.withColumn(col_name, trim(col(col_name)))

    # Uppercase postcode-like fields
    for col_name in ["postcode", "delivery_postcode"]:
        if col_name in df.columns:
            df = df.withColumn(col_name, upper(col(col_name)))
    return df


# ============================================================
# LATE ARRIVAL HANDLING
# ============================================================

def handle_late_arrivals(spark, df, table_config, config, target_table):
    """Split records into on-time and late. Quarantine late records outside window.
    On first load (silver table doesn't exist), skip — no concept of 'late'."""
    # Skip late arrival check on initial load
    try:
        spark.read.table(target_table).limit(1).count()
    except Exception:
        log("late", "First load — skipping late arrival check")
        return df, None

    window_days = table_config.get("late_arrival_window_days",
                                   config["pipeline"].get("late_arrival_window_days", 7))

    # Determine the event time column (first temporal column found)
    time_cols = [c for c in df.columns if any(t in c for t in
                 ["_datetime", "_date", "date", "timestamp", "_at", "_time"])]
    time_cols = [c for c in time_cols if not c.startswith("_")]

    if not time_cols:
        log("late", "No event time column found — skipping late arrival check")
        return df, None

    event_col = time_cols[0]
    cutoff = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%dT%H:%M:%S")

    # Cast to timestamp if needed
    if df.schema[event_col].dataType.simpleString() == "string":
        df = df.withColumn(f"_{event_col}_ts", to_timestamp(col(event_col)))
        ts_col = f"_{event_col}_ts"
    else:
        ts_col = event_col

    # Split
    on_time = df.filter((col(ts_col) >= lit(cutoff)) | col(ts_col).isNull())
    late = df.filter(col(ts_col) < lit(cutoff))

    late_count = late.count()
    if late_count > 0:
        log("late", f"Late arrivals: {late_count} records older than {window_days} days")
        # Write to quarantine
        quarantine_table = f"{target_table}_quarantine"
        late_q = late.withColumn("_quarantine_reason", lit(f"LATE_ARRIVAL_BEYOND_{window_days}_DAYS"))
        late_q = late_q.withColumn("_quarantined_at", current_timestamp())
        try:
            late_q.writeTo(quarantine_table).option("merge-schema", "true").append()
            log("late", f"Quarantined {late_count} records → {quarantine_table}")
        except Exception:
            late_q.writeTo(quarantine_table).create()
            log("late", f"Created quarantine table with {late_count} records")
    else:
        log("late", "No late arrivals detected")

    # Drop temp column if added
    if f"_{event_col}_ts" in on_time.columns:
        on_time = on_time.drop(f"_{event_col}_ts")

    return on_time, late_count


# ============================================================
# SCD2 MERGE
# ============================================================

def merge_scd2(spark, df, table_config, target_table):
    """Merge into silver with SCD2 logic (valid_from, valid_to, is_current)."""
    pk = table_config["primary_key"]

    # Add SCD2 columns to incoming
    df = df.withColumn("valid_from", current_timestamp())
    df = df.withColumn("valid_to", lit("9999-12-31 00:00:00").cast(TimestampType()))
    df = df.withColumn("is_current", lit(True))

    # Check if silver table exists
    try:
        existing = spark.read.table(target_table)
        table_exists = True
        log("scd2", f"Silver table exists — merging with SCD2")
    except Exception:
        table_exists = False
        log("scd2", f"Silver table does not exist — creating with initial load")

    if not table_exists:
        df.writeTo(target_table).create()
        log("scd2", f"Created {target_table} with {df.count()} records")
        return

    # Identify changed records: incoming PK exists in silver with different row_hash
    current_silver = existing.filter(col("is_current") == True).alias("s")
    incoming = df.alias("i")

    # Records that exist in silver and have changed
    changed = incoming.join(current_silver, incoming[pk] == current_silver[pk], "inner") \
        .filter(col(f"i.row_hash") != col(f"s.row_hash")) \
        .select("i.*")

    # Net new records (not in silver at all)
    new_records = incoming.join(current_silver, incoming[pk] == current_silver[pk], "left_anti")

    changed_count = changed.count()
    new_count = new_records.count()
    unchanged = df.count() - changed_count - new_count

    log("scd2", f"Changed: {changed_count}, New: {new_count}, Unchanged: {unchanged}")

    if changed_count > 0:
        # Close existing current records for changed PKs
        changed_pks = [row[pk] for row in changed.select(pk).collect()]

        # Use Iceberg MERGE via SQL for atomicity
        # Register incoming as temp view
        changed.createOrReplaceTempView("_scd2_changed")
        new_records.createOrReplaceTempView("_scd2_new")

        # Close old records
        spark.sql(f"""
            MERGE INTO {target_table} t
            USING _scd2_changed s
            ON t.{pk} = s.{pk} AND t.is_current = true
            WHEN MATCHED THEN UPDATE SET
                t.valid_to = current_timestamp(),
                t.is_current = false
        """)
        log("scd2", f"Closed {changed_count} existing records")

        # Append new versions
        changed.writeTo(target_table).append()
        log("scd2", f"Appended {changed_count} new versions")

    if new_count > 0:
        new_records.writeTo(target_table).append()
        log("scd2", f"Appended {new_count} net new records")

    total = spark.read.table(target_table).count()
    current = spark.read.table(target_table).filter(col("is_current") == True).count()
    log("scd2", f"Silver total: {total} rows ({current} current)")



# ============================================================
# RECONCILIATION
# ============================================================

def reconcile(spark, config, table_name, bronze_count, silver_count, rejected, quarantined):
    """Write reconciliation record."""
    pipeline = config["pipeline"]
    catalog = pipeline["catalog"]
    ns = pipeline["silver_namespace"]
    recon_table = f"{catalog}.{ns}.reconciliation_log"

    from pyspark.sql.types import StructType, StructField, StringType, LongType
    row = [(
        datetime.now().strftime("%Y%m%d_%H%M%S"),
        table_name,
        bronze_count,
        silver_count,
        rejected,
        quarantined or 0,
    )]
    schema = StructType([
        StructField("run_id", StringType()),
        StructField("table_name", StringType()),
        StructField("bronze_records", LongType()),
        StructField("silver_records", LongType()),
        StructField("dq_rejected", LongType()),
        StructField("quarantined", LongType()),
    ])
    df = spark.createDataFrame(row, schema)
    df = df.withColumn("reconciled_at", current_timestamp())

    try:
        df.writeTo(recon_table).append()
    except Exception:
        df.writeTo(recon_table).create()
    log("recon", f"Reconciliation logged: bronze={bronze_count}, silver={silver_count}, "
                 f"rejected={rejected}, quarantined={quarantined or 0}")


# ============================================================
# MAIN SILVER PROCESSING
# ============================================================

def silver_table(spark, config, table_name):
    """Process a single table: Bronze → Silver Iceberg (merge/SCD2)."""
    table_config = get_table_config(config, table_name)
    pipeline = config["pipeline"]
    catalog = pipeline["catalog"]
    bronze_ns = pipeline["bronze_namespace"]
    silver_ns = pipeline["silver_namespace"]
    bronze_table = f"{catalog}.{bronze_ns}.{table_name}"
    target_table = f"{catalog}.{silver_ns}.{table_name}"

    log_header(f"SILVER: {table_name.upper()}")
    log("silver", f"Source: {bronze_table}")
    log("silver", f"Target: {target_table}")

    # 1. Read from bronze (incremental: all records for now, dedup handles idempotency)
    try:
        df = spark.read.table(bronze_table)
    except Exception as e:
        log_error("silver", f"Cannot read bronze table: {bronze_table}", e)
        raise RuntimeError(f"Bronze table not found: {bronze_table}. Run bronze first.")

    bronze_count = df.count()
    log("silver", f"Bronze records: {bronze_count}")
    if bronze_count == 0:
        return "SKIPPED"

    # Drop bronze metadata columns (keep row_hash)
    drop_cols = ["_source_file", "_batch_id", "_dq_flags"]
    for c in drop_cols:
        if c in df.columns:
            df = df.drop(c)

    # Drop _cdc_operation (already processed in bronze)
    if "_cdc_operation" in df.columns:
        # Filter out DELETE operations for silver (soft-delete handling)
        df = df.filter((col("_cdc_operation") != "DELETE") | col("_cdc_operation").isNull())
        df = df.drop("_cdc_operation")

    # 2. Dedup
    df = dedup_by_hash(df, spark, target_table)

    # 3. Preventative DQ
    pre_dq_count = df.count()
    df = apply_preventative_dq(df, table_config)
    rejected = pre_dq_count - df.count()

    # 4. Policy controls
    df = strip_non_printable(df)
    df = standardise_fields(df)
    df = apply_masking(df, table_config)

    # 5. Late arrival handling
    quarantined = None
    df, quarantined = handle_late_arrivals(spark, df, table_config, config, target_table)

    if df.count() == 0:
        log("silver", "No records to merge after DQ + dedup + late arrival filtering")
        return "SKIPPED"

    # 6. Schema evolution check (silver = non-breaking only)
    from schema_evolver import SchemaEvolver
    evolver = SchemaEvolver(spark, table_config, "silver")
    df = evolver.apply(df, target_table)
    df = evolver.align_to_table(df, target_table)

    # Drop _ingested_at from bronze (silver will have its own valid_from)
    if "_ingested_at" in df.columns:
        df = df.drop("_ingested_at")

    # 7. SCD2 merge
    merge_scd2(spark, df, table_config, target_table)

    # 8. Reconciliation
    silver_count = spark.read.table(target_table).filter(col("is_current") == True).count()
    reconcile(spark, config, table_name, bronze_count, silver_count, rejected, quarantined)

    return "SUCCESS"


def main():
    print(BANNER)
    args = parse_args("EastSide CDH 2.0 — Silver: Bronze → Iceberg (merge/SCD2)")
    config = load_config(args.config)
    config = resolve_pipeline_vars(config, args)

    spark = get_spark("silver")
    pipeline = config["pipeline"]
    catalog = pipeline["catalog"]
    silver_ns = pipeline["silver_namespace"]

    # Set catalog and create namespace
    spark.sql(f"USE {catalog}")
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{silver_ns}")

    if args.all:
        tables = get_all_tables(config)
    elif args.table:
        tables = [args.table]
    else:
        log_error("silver", "Specify --table <name> or --all")
        sys.exit(1)

    log("silver", f"Tables: {tables}")

    results = {}
    for table in tables:
        try:
            result = silver_table(spark, config, table)
            results[table] = result
        except Exception as e:
            log_error("silver", f"Table '{table}' failed", e)
            results[table] = "FAILED"

    log_summary("silver", results)
    flush_logs_to_gcs("silver", config)
    log_header("SILVER COMPLETE")
    spark.stop()

    if "FAILED" in results.values():
        sys.exit(1)


if __name__ == "__main__":
    main()
