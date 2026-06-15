"""bt-df-lkhouse-fw — Consume Engine (CCN → Data Product).
Config-driven joins and aggregations to build data products."""
from bt_df_lkhouse_fw.engine.base import get_spark, load_config, get_consumption_config, parse_args, log, log_header, BANNER
from pyspark.sql.functions import col, count, sum as spark_sum, avg, max as spark_max, min as spark_min


AGG_FUNCTIONS = {
    "count": count,
    "sum": spark_sum,
    "avg": avg,
    "max": spark_max,
    "min": spark_min,
}


def build_aggregation(spark, catalog: str, ns: str, join_config: dict, base_key: str):
    source_table = f"{catalog}.{ns}.{join_config['source']}"
    source_df = spark.read.table(source_table)
    join_key = join_config["on"]

    if "link_through" in join_config:
        link_table = f"{catalog}.{ns}.{join_config['link_through']}"
        link_df = spark.read.table(link_table)
        link_key = join_config["link_key"]
        source_df = source_df.join(
            link_df.select(link_key, join_key).distinct(),
            link_key,
            "inner"
        )

    if "aggregations" in join_config:
        agg_exprs = []
        for agg in join_config["aggregations"]:
            func = AGG_FUNCTIONS[agg["function"]]
            agg_exprs.append(func(agg["column"]).alias(agg["alias"]))

        agg_df = source_df.groupBy(join_key).agg(*agg_exprs)
        log("consume", f"  Aggregated {join_config['source']} → {[a['alias'] for a in join_config['aggregations']]}")
        return agg_df

    elif "columns" in join_config:
        select_cols = [join_key] + [c for c in join_config["columns"] if c in source_df.columns]
        return source_df.select(*select_cols).distinct()

    return source_df


def consume_target(spark, pipeline_config: dict, target_name: str):
    consumption_config = get_consumption_config(pipeline_config, target_name)
    catalog = pipeline_config["pipeline"]["catalog"]
    ns_ccn = pipeline_config["pipeline"]["namespaces"]["ccn"]
    ns_dataproduct = pipeline_config["pipeline"]["namespaces"]["dataproduct"]

    log_header(f"CONSUME: {target_name.upper()}")
    log("consume", f"Description: {consumption_config.get('description', '')}")

    base_table_name = consumption_config["base_table"]
    base_table = f"{catalog}.{ns_ccn}.{base_table_name}"
    base_df = spark.read.table(base_table)
    log("consume", f"Base table: {base_table} ({base_df.count()} records)")

    for join_config in consumption_config.get("joins", []):
        join_name = join_config["name"]
        join_type = join_config.get("type", "left")
        join_key = join_config["on"]

        log("consume", f"Joining: {join_name} ({join_type} on {join_key})")
        join_df = build_aggregation(spark, catalog, ns_ccn, join_config, join_key)
        base_df = base_df.join(join_df, join_key, join_type)

    output_config = consumption_config.get("output_columns", {})
    output_cols = []

    for col_name in output_config.get("from_base", []):
        if col_name in base_df.columns:
            output_cols.append(col_name)

    for col_name in output_config.get("from_joins", []):
        if col_name in base_df.columns:
            output_cols.append(col_name)

    if output_cols:
        result_df = base_df.select(*output_cols)
    else:
        result_df = base_df

    target_table = f"{catalog}.{ns_dataproduct}.{target_name}"
    result_df.writeTo(target_table).option("merge-schema", "true").createOrReplace()

    log("consume", f"Written to: {target_table}")
    log("consume", f"Records: {result_df.count()}")
    log("consume", f"Schema: {result_df.columns}")


def main():
    print(BANNER)
    args = parse_args("bt-df-lkhouse-fw Consume: CCN → Data Product")
    config = load_config(args.config)

    spark = get_spark("consume")
    catalog = config["pipeline"]["catalog"]
    ns_dataproduct = config["pipeline"]["namespaces"]["dataproduct"]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{ns_dataproduct}")

    if args.all:
        targets = list(config["consumption"].keys())
    elif args.target:
        targets = [args.target]
    else:
        raise ValueError("Specify --target <name> or --all")

    for target in targets:
        consume_target(spark, config, target)

    log_header("CONSUME COMPLETE")
    spark.stop()


if __name__ == "__main__":
    main()
