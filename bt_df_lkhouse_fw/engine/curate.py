"""bt-df-lkhouse-fw — Curate Engine (Reservoir Parquet → CCN Iceberg).
Reads Parquet from GCS, applies DQ + dedup + type enforcement, writes Iceberg via BLMS.
Add a new table: drop a YAML into config/tables/ → engine picks it up."""
import sys
from bt_df_lkhouse_fw.engine.base import (
    get_spark, load_config, get_table_config, get_all_tables,
    parse_args, resolve_pipeline_vars, log, log_header, log_table_info,
    log_error, log_summary, flush_logs_to_gcs, BANNER, LogLevel,
)
from bt_df_lkhouse_fw.engine.audit import write_audit
from bt_df_lkhouse_fw.engine.schema_evolver import SchemaEvolver
from pyspark.sql.functions import col, row_number
from pyspark.sql.window import Window
from pyspark.sql.types import LongType, DoubleType, StringType, IntegerType


TYPE_MAP = {
    "bigint": LongType(),
    "double": DoubleType(),
    "string": StringType(),
    "int": IntegerType(),
    "integer": IntegerType(),
}


def apply_dq_rules(df, table_name: str, dq_rules: dict):
    initial_count = df.count()
    log("dq", f"[{table_name}] Starting DQ validation ({initial_count} records)")

    for col_name in dq_rules.get("not_null", []):
        if col_name in df.columns:
            before = df.count()
            df = df.filter(col(col_name).isNotNull())
            rejected = before - df.count()
            if rejected > 0:
                log("dq", f"[{table_name}] NOT_NULL({col_name}): rejected {rejected}", LogLevel.WARN)

    for col_name in dq_rules.get("positive", []):
        if col_name in df.columns:
            before = df.count()
            df = df.filter(col(col_name) > 0)
            rejected = before - df.count()
            if rejected > 0:
                log("dq", f"[{table_name}] POSITIVE({col_name}): rejected {rejected}", LogLevel.WARN)

    for col_name, values in dq_rules.get("accepted_values", {}).items():
        if col_name in df.columns:
            # Skip accepted_values for boolean/numeric columns (type mismatch with isin)
            col_type = str(df.schema[col_name].dataType).lower()
            if "boolean" in col_type or "int" in col_type or "long" in col_type or "double" in col_type or "float" in col_type or "decimal" in col_type:
                log("dq", f"[{table_name}] SKIPPED ACCEPTED_VALUES({col_name}): column is {col_type}, not string", LogLevel.WARN)
                continue
            before = df.count()
            try:
                df = df.filter(col(col_name).isin(values) | col(col_name).isNull())
                rejected = before - df.count()
                if rejected > 0:
                    log("dq", f"[{table_name}] ACCEPTED_VALUES({col_name}): rejected {rejected}", LogLevel.WARN)
            except Exception as e:
                log("dq", f"[{table_name}] ACCEPTED_VALUES({col_name}): SKIPPED due to error: {e}", LogLevel.WARN)

    final_count = df.count()
    total_rejected = initial_count - final_count
    reject_pct = (total_rejected / initial_count * 100) if initial_count > 0 else 0
    log("dq", f"[{table_name}] DQ complete: {final_count} passed, {total_rejected} rejected ({reject_pct:.1f}%)")

    if reject_pct > 50:
        log("dq", f"[{table_name}] HIGH REJECT RATE: {reject_pct:.1f}%", LogLevel.WARN)

    return df


def apply_dedup(df, table_name: str, primary_key: str, order_by: str):
    parts = order_by.split()
    order_col = parts[0]
    descending = len(parts) > 1 and parts[1].upper() == "DESC"

    if order_col not in df.columns:
        log("dedup", f"[{table_name}] Order column '{order_col}' not found — skipping", LogLevel.WARN)
        return df

    order_expr = col(order_col).desc() if descending else col(order_col).asc()
    w = Window.partitionBy(primary_key).orderBy(order_expr)

    before = df.count()
    df = df.withColumn("_rn", row_number().over(w)).filter(col("_rn") == 1).drop("_rn")
    after = df.count()

    log("dedup", f"[{table_name}] Dedup on '{primary_key}': {before} → {after} (removed {before - after})")
    return df


def apply_type_overrides(df, table_name: str, type_overrides: dict):
    for col_name, target_type in type_overrides.items():
        if col_name in df.columns and target_type in TYPE_MAP:
            df = df.withColumn(col_name, col(col_name).cast(TYPE_MAP[target_type]))
            log("types", f"[{table_name}] Cast {col_name} → {target_type}")
        elif col_name not in df.columns:
            log("types", f"[{table_name}] Column '{col_name}' not found — skipping", LogLevel.WARN)
    return df


def table_exists(spark, table_full: str) -> bool:
    try:
        spark.read.table(table_full)
        return True
    except Exception:
        return False


def curate_table(spark, config: dict, table_name: str):
    table_config = get_table_config(config, table_name)
    pipeline = config["pipeline"]
    catalog = pipeline["catalog"]
    reservoir_path = pipeline["reservoir_path"]
    ns_ccn = pipeline["ccn_namespace"]

    source_path = f"{reservoir_path}/{table_name}"
    target_table = f"{catalog}.{ns_ccn}.{table_name}"

    log_header(f"CURATE: {table_name.upper()}")
    log("curate", f"Source: {source_path} (Parquet)")
    log("curate", f"Target: {target_table} (Iceberg)")

    # Read reservoir Parquet
    try:
        df = spark.read.parquet(source_path)
    except Exception as e:
        log_error("curate", f"Cannot read: {source_path}", e)
        raise RuntimeError(f"Reservoir data not found: {source_path}. Run ingest first.") from e

    raw_count = df.count()
    log("curate", f"Reservoir records: {raw_count}")

    if raw_count == 0:
        log("curate", f"Empty reservoir — skipping", LogLevel.WARN)
        raise RuntimeError(f"Empty reservoir for {table_name}")

    # DQ
    dq_rules = table_config.get("dq_rules", {})
    df = apply_dq_rules(df, table_name, dq_rules)

    # Dedup
    primary_key = table_config["primary_key"]
    order_by = table_config["dedup_order_by"]
    df = apply_dedup(df, table_name, primary_key, order_by)

    # Type enforcement
    type_overrides = table_config.get("type_overrides", {})
    df = apply_type_overrides(df, table_name, type_overrides)

    # Schema evolution (if table already exists)
    if table_exists(spark, target_table):
        log("curate", "Table exists — checking schema evolution...")
        evolver = SchemaEvolver(spark, table_config)
        df = evolver.apply_evolution(df, target_table)
        df = evolver.align_dataframe(df, target_table)
        log("curate", "Schema evolution applied")

    # Write Iceberg
    try:
        df.writeTo(target_table).option("merge-schema", "true").createOrReplace()
        log("curate", f"Written to: {target_table}")
        log("curate", f"Final records: {df.count()}")
        log("curate", f"Final schema: {df.columns}")
    except Exception as e:
        log_error("curate", f"Failed to write: {target_table}", e)
        raise


def main():
    print(BANNER)
    args = parse_args("bt-df-lkhouse-fw Curate: Reservoir (Parquet) → CCN (Iceberg)")
    config = load_config(args.config)
    config = resolve_pipeline_vars(config, args)

    spark = get_spark("curate")
    pipeline = config["pipeline"]
    catalog = pipeline["catalog"]
    ns_ccn = pipeline["ccn_namespace"]

    # Set catalog context and create namespace
    spark.sql(f"USE {catalog}")
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {ns_ccn}")

    if args.all:
        tables = [t for t in get_all_tables(config)
                  if config["tables"][t].get("source") != "kafka"]
    elif args.table:
        tables = [args.table]
    else:
        log_error("curate", "Specify --table <name> or --all")
        sys.exit(1)

    log("curate", f"Tables: {tables}")

    results = {}
    for table in tables:
        try:
            result = curate_table(spark, config, table)
            results[table] = result if result == "SKIPPED" else "SUCCESS"
        except Exception as e:
            log_error("curate", f"Table '{table}' failed", e)
            results[table] = "FAILED"

    log_summary("curate", results)
    write_audit(spark, config, "curate", results)

    log_header("CURATE COMPLETE")
    flush_logs_to_gcs("curate", config)
    spark.stop()

    if "FAILED" in results.values():
        sys.exit(1)


if __name__ == "__main__":
    main()
