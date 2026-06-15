"""bt-df-lkhouse-fw — Curate Engine (Reservoir → CCN).
Config-driven DQ validation, deduplication, type enforcement."""
from engine.base import get_spark, load_config, get_table_config, parse_args, log, log_header, log_table_info, BANNER
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

    for col_name in dq_rules.get("not_null", []):
        if col_name in df.columns:
            df = df.filter(col(col_name).isNotNull())

    for col_name in dq_rules.get("positive", []):
        if col_name in df.columns:
            df = df.filter(col(col_name) > 0)

    for col_name, values in dq_rules.get("accepted_values", {}).items():
        if col_name in df.columns:
            df = df.filter(col(col_name).isin(values) | col(col_name).isNull())

    final_count = df.count()
    rejected = initial_count - final_count
    log("dq", f"[{table_name}] Passed: {final_count}, Rejected: {rejected}")
    return df


def apply_dedup(df, table_name: str, primary_key: str, order_by: str):
    parts = order_by.split()
    order_col = parts[0]
    descending = len(parts) > 1 and parts[1].upper() == "DESC"

    order_expr = col(order_col).desc() if descending else col(order_col).asc()
    w = Window.partitionBy(primary_key).orderBy(order_expr)

    before = df.count()
    df = df.withColumn("_rn", row_number().over(w)).filter(col("_rn") == 1).drop("_rn")
    after = df.count()

    log("dedup", f"[{table_name}] Before: {before}, After: {after}, Removed: {before - after}")
    return df


def apply_type_overrides(df, table_name: str, type_overrides: dict):
    for col_name, target_type in type_overrides.items():
        if col_name in df.columns and target_type in TYPE_MAP:
            df = df.withColumn(col_name, col(col_name).cast(TYPE_MAP[target_type]))
            log("types", f"[{table_name}] Cast {col_name} → {target_type}")
    return df


def curate_table(spark, pipeline_config: dict, table_name: str):
    table_config = get_table_config(pipeline_config, table_name)
    catalog = pipeline_config["pipeline"]["catalog"]
    ns_reservoir = pipeline_config["pipeline"]["namespaces"]["reservoir"]
    ns_ccn = pipeline_config["pipeline"]["namespaces"]["ccn"]

    source_table = f"{catalog}.{ns_reservoir}.{table_name}"
    target_table = f"{catalog}.{ns_ccn}.{table_name}"

    log_header(f"CURATE: {table_name.upper()}")
    log("curate", f"Source: {source_table}")
    log("curate", f"Target: {target_table}")

    df = spark.read.table(source_table)
    log("curate", f"Reservoir records: {df.count()}")

    dq_rules = table_config.get("dq_rules", {})
    df = apply_dq_rules(df, table_name, dq_rules)

    primary_key = table_config["primary_key"]
    order_by = table_config["dedup_order_by"]
    df = apply_dedup(df, table_name, primary_key, order_by)

    type_overrides = table_config.get("type_overrides", {})
    df = apply_type_overrides(df, table_name, type_overrides)

    df.writeTo(target_table).option("merge-schema", "true").createOrReplace()

    log("curate", f"Written to: {target_table}")
    log("curate", f"Final records: {df.count()}")


def main():
    print(BANNER)
    args = parse_args("bt-df-lkhouse-fw Curate: Reservoir → CCN")
    config = load_config(args.config)

    spark = get_spark("curate")
    catalog = config["pipeline"]["catalog"]
    ns_ccn = config["pipeline"]["namespaces"]["ccn"]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{ns_ccn}")

    if args.all:
        tables = list(config["tables"].keys())
    elif args.table:
        tables = [args.table]
    else:
        raise ValueError("Specify --table <name> or --all")

    for table in tables:
        curate_table(spark, config, table)

    log_header("CURATE COMPLETE")
    spark.stop()


if __name__ == "__main__":
    main()
