"""EastSide CDH 2.0 — Bronze Engine (Landing → Bronze Iceberg).
- Reads raw files from GCS landing (JSON, CSV, Avro, Parquet)
- Converts all to Parquet/Iceberg
- CDC: reconstructs partial records to full rows
- Computes row_hash (SHA256)
- Adds metadata columns (_ingested_at, _source_file, _batch_id)
- Runs detective policies (flag only, never reject)
- Appends to eastside.bronze.{table}

Usage:
    spark-submit eastside/engine/bronze.py \\
        --config gs://eastside-lakehouse/config/pipeline.yaml --all
"""
import sys
import hashlib
from datetime import datetime
from base import (
    get_spark, load_config, get_table_config, get_all_tables,
    parse_args, resolve_pipeline_vars, log, log_header,
    log_error, log_summary, flush_logs_to_gcs, BANNER, LogLevel,
)
from pyspark.sql.functions import (
    col, lit, current_timestamp, input_file_name, sha2, concat_ws,
    when, array, array_compact, coalesce, lower,
)
from pyspark.sql.types import StringType, ArrayType


def check_watermark(config, table_name, version):
    """Check if this version was already processed. Returns True if already done."""
    import json
    from google.cloud import storage as gcs_storage
    pipeline = config["pipeline"]
    bucket_name = pipeline["bucket"]
    wm_path = f"bronze/_watermarks/{table_name}.json"
    try:
        client = gcs_storage.Client(project=pipeline.get("project_id", "bt-df-lkhouse"))
        blob = client.bucket(bucket_name).blob(wm_path)
        if not blob.exists():
            return False
        wm = json.loads(blob.download_as_text())
        processed = wm.get("processed_versions", [])
        return version in processed
    except Exception:
        return False


def write_watermark(config, table_name, version):
    """Record that this version has been processed."""
    import json
    from google.cloud import storage as gcs_storage
    pipeline = config["pipeline"]
    bucket_name = pipeline["bucket"]
    wm_path = f"bronze/_watermarks/{table_name}.json"
    client = gcs_storage.Client(project=pipeline.get("project_id", "bt-df-lkhouse"))
    blob = client.bucket(bucket_name).blob(wm_path)
    try:
        wm = json.loads(blob.download_as_text()) if blob.exists() else {}
    except Exception:
        wm = {}
    processed = wm.get("processed_versions", [])
    if version not in processed:
        processed.append(version)
    wm["processed_versions"] = processed
    wm["last_version"] = version
    wm["last_processed_at"] = datetime.now().isoformat()
    blob.upload_from_string(json.dumps(wm), content_type="application/json")
    log("bronze", f"Watermark updated: {version} → {wm_path}")


def read_landing(spark, config, table_name, table_config, version):
    """Read raw files from landing, auto-detecting format."""
    pipeline = config["pipeline"]
    source_format = table_config.get("source_format", "json")
    source_path = f"{pipeline['landing_path']}/{table_name}/{version}"

    log("bronze", f"Reading {source_format.upper()} from: {source_path}")

    if source_format == "json":
        df = spark.read.json(source_path)
    elif source_format == "csv":
        df = spark.read.option("header", "true").option("inferSchema", "true").csv(source_path)
    elif source_format == "avro":
        df = spark.read.format("avro").load(source_path)
    elif source_format == "parquet":
        df = spark.read.parquet(source_path)
    else:
        raise ValueError(f"Unsupported source_format: {source_format}")

    log("bronze", f"Read {df.count()} records, {len(df.columns)} columns")
    return df


def reconstruct_cdc(spark, df, table_config, target_table):
    """For CDC tables: reconstruct partial records to full rows.
    - Read last known full row for PK from bronze
    - Overlay changed fields from partial record
    - Return full rows ready for append
    """
    pk = table_config["primary_key"]
    log("cdc", f"Reconstructing partials (PK: {pk})")

    # Separate full inserts from partial updates
    if "_cdc_operation" not in df.columns:
        log("cdc", "No _cdc_operation column — treating all as full records")
        return df

    inserts = df.filter(col("_cdc_operation") == "INSERT")
    updates = df.filter(col("_cdc_operation") == "UPDATE")
    deletes = df.filter(col("_cdc_operation") == "DELETE")

    insert_count = inserts.count()
    update_count = updates.count()
    delete_count = deletes.count()
    log("cdc", f"INSERTs: {insert_count}, UPDATEs: {update_count}, DELETEs: {delete_count}")

    if update_count == 0 and delete_count == 0:
        return df

    # Try to read existing bronze table for last known state
    try:
        existing = spark.read.table(target_table)
        # Get latest row per PK
        from pyspark.sql.window import Window
        from pyspark.sql.functions import row_number
        w = Window.partitionBy(pk).orderBy(col("_ingested_at").desc())
        latest = existing.withColumn("_rn", row_number().over(w)).filter(col("_rn") == 1).drop("_rn")
    except Exception:
        log("cdc", "No existing bronze table — partials will have NULLs for missing fields")
        latest = None

    # Reconstruct updates: overlay partial onto last known full row
    if latest is not None and update_count > 0:
        update_pks = [row[pk] for row in updates.select(pk).collect()]
        base_rows = latest.filter(col(pk).isin(update_pks))

        # For each update, coalesce: update value if present, else base value
        all_cols = list(set(inserts.columns) | set(base_rows.columns))
        all_cols = [c for c in all_cols if not c.startswith("_")]  # exclude metadata

        # Join updates with base on PK, coalesce each column
        joined = updates.alias("u").join(base_rows.alias("b"), pk, "left")
        for c in all_cols:
            if c == pk or c == "_cdc_operation":
                continue
            if c in updates.columns and c in base_rows.columns:
                joined = joined.withColumn(c, coalesce(col(f"u.{c}"), col(f"b.{c}")))
            elif c in updates.columns:
                joined = joined.withColumn(c, col(f"u.{c}"))
            elif c in base_rows.columns:
                joined = joined.withColumn(c, col(f"b.{c}"))

        # Select only the columns that match inserts schema + _cdc_operation
        select_cols = [c for c in inserts.columns if c in joined.columns]
        reconstructed = joined.select(*select_cols)
        log("cdc", f"Reconstructed {reconstructed.count()} partial records to full rows")

        # Union: inserts + reconstructed updates + deletes (as soft-delete markers)
        result = inserts.unionByName(reconstructed, allowMissingColumns=True)
    else:
        result = inserts.unionByName(updates, allowMissingColumns=True)

    if delete_count > 0:
        result = result.unionByName(deletes, allowMissingColumns=True)

    return result


def compute_row_hash(df, hash_fields):
    """Compute SHA256 hash of key business fields for dedup."""
    # Only hash fields that exist in the dataframe
    available = [f for f in hash_fields if f in df.columns]
    if not available:
        log("hash", "No hash fields available — using all columns", LogLevel.WARN)
        available = [c for c in df.columns if not c.startswith("_")]

    df = df.withColumn("row_hash", sha2(concat_ws("|", *[col(c).cast("string") for c in available]), 256))
    log("hash", f"Computed row_hash over: {available}")
    return df


def add_metadata(df, table_name, batch_id):
    """Add bronze metadata columns."""
    df = df.withColumn("_ingested_at", current_timestamp())
    df = df.withColumn("_source_file", input_file_name())
    df = df.withColumn("_batch_id", lit(batch_id))
    return df


def run_detective_policies(df, table_config):
    """Detective-only DQ: flag issues in _dq_flags column, never reject."""
    dq_rules = table_config.get("dq_rules", {})
    flags = []

    # NOT NULL checks
    for col_name in dq_rules.get("not_null", []):
        if col_name in df.columns:
            flag_expr = when(col(col_name).isNull(), lit(f"NULL_{col_name.upper()}"))
            flags.append(flag_expr)

    # POSITIVE checks (only for numeric columns)
    for col_name in dq_rules.get("positive", []):
        if col_name in df.columns:
            dtype = str(df.schema[col_name].dataType).lower()
            if any(t in dtype for t in ["int", "long", "float", "double", "decimal", "short"]):
                flag_expr = when(col(col_name) <= 0, lit(f"NON_POSITIVE_{col_name.upper()}"))
                flags.append(flag_expr)

    # ACCEPTED VALUES checks (case-insensitive, cast to string for type safety)
    for col_name, values in dq_rules.get("accepted_values", {}).items():
        if col_name in df.columns:
            lower_values = [str(v).lower() for v in values]
            flag_expr = when(
                ~lower(col(col_name).cast("string")).isin(lower_values) & col(col_name).isNotNull(),
                lit(f"INVALID_{col_name.upper()}")
            )
            flags.append(flag_expr)

    if flags:
        # Build array of non-null flags
        df = df.withColumn("_dq_flags", array(*flags))
        df = df.withColumn("_dq_flags", array_compact(col("_dq_flags")))
        flagged = df.filter(col("_dq_flags").isNotNull() & (col("_dq_flags").getItem(0).isNotNull())).count()
        log("dq", f"Detective scan: {flagged} records flagged (not rejected)")
    else:
        df = df.withColumn("_dq_flags", array().cast(ArrayType(StringType())))
        log("dq", "No DQ rules configured")

    return df


def bronze_table(spark, config, table_name, version):
    """Process a single table: Landing → Bronze Iceberg (append)."""
    table_config = get_table_config(config, table_name)
    pipeline = config["pipeline"]
    catalog = pipeline["catalog"]
    ns = pipeline["bronze_namespace"]
    target_table = f"{catalog}.{ns}.{table_name}"
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    log_header(f"BRONZE: {table_name.upper()}")
    log("bronze", f"Target: {target_table}")

    # 0. Watermark check
    if check_watermark(config, table_name, version):
        log("bronze", f"Version '{version}' already processed — skipping")
        return "SKIPPED"

    # 1. Read landing
    df = read_landing(spark, config, table_name, table_config, version)
    source_count = df.count()
    if source_count == 0:
        log("bronze", "Empty source — skipping", LogLevel.WARN)
        return "SKIPPED"

    # 2. CDC reconstruction (if applicable)
    if table_config.get("is_cdc", False):
        df = reconstruct_cdc(spark, df, table_config, target_table)

    # 3. Compute row_hash
    hash_fields = table_config.get("hash_fields", [])
    df = compute_row_hash(df, hash_fields)

    # 4. Add metadata
    df = add_metadata(df, table_name, batch_id)

    # 5. Detective policies
    df = run_detective_policies(df, table_config)

    # 6. Schema evolution (bronze = accept all)
    from schema_evolver import SchemaEvolver
    evolver = SchemaEvolver(spark, table_config, "bronze")
    df = evolver.apply(df, target_table)
    df = evolver.align_to_table(df, target_table)

    # 7. Append to Iceberg bronze
    log("bronze", f"Appending {df.count()} records to {target_table}")
    try:
        df.writeTo(target_table).option("merge-schema", "true").append()
        log("bronze", f"✅ Appended to existing table")
    except Exception:
        # Table doesn't exist — create it
        try:
            df.writeTo(target_table).create()
            log("bronze", f"✅ Created new table")
        except Exception as e:
            log_error("bronze", f"Failed to write: {target_table}", e)
            raise

    # 8. Write watermark
    write_watermark(config, table_name, version)

    # 9. Reconciliation log
    final_count = spark.read.table(target_table).count()
    log("bronze", f"Reconciliation: source={source_count}, bronze_total={final_count}")

    return "SUCCESS"


def main():
    print(BANNER)
    args = parse_args("EastSide CDH 2.0 — Bronze: Landing → Iceberg (append)")
    config = load_config(args.config)
    config = resolve_pipeline_vars(config, args)

    spark = get_spark("bronze")
    pipeline = config["pipeline"]
    catalog = pipeline["catalog"]
    ns = pipeline["bronze_namespace"]

    # Set catalog and create namespace
    spark.sql(f"USE {catalog}")
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{ns}")

    if args.all:
        tables = get_all_tables(config)
    elif args.table:
        tables = [args.table]
    else:
        log_error("bronze", "Specify --table <name> or --all")
        sys.exit(1)

    log("bronze", f"Tables: {tables}")
    log("bronze", f"Version: {args.version}")

    results = {}
    for table in tables:
        try:
            result = bronze_table(spark, config, table, args.version)
            results[table] = result
        except Exception as e:
            log_error("bronze", f"Table '{table}' failed", e)
            results[table] = "FAILED"

    log_summary("bronze", results)
    flush_logs_to_gcs("bronze", config)
    log_header("BRONZE COMPLETE")
    spark.stop()

    if "FAILED" in results.values():
        sys.exit(1)


if __name__ == "__main__":
    main()
