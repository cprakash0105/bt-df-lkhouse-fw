"""bt-df-lkhouse-fw — Ingest Engine (Landing → Reservoir).
Config-driven ingestion with schema evolution support."""
from engine.base import get_spark, load_config, get_table_config, parse_args, log, log_header, log_table_info, BANNER
from engine.schema_evolver import SchemaEvolver
from pyspark.sql.functions import current_timestamp


def ingest_table(spark, pipeline_config: dict, table_name: str, version: str):
    table_config = get_table_config(pipeline_config, table_name)
    catalog = pipeline_config["pipeline"]["catalog"]
    ns = pipeline_config["pipeline"]["namespaces"]["reservoir"]
    bucket = pipeline_config["pipeline"]["bucket"]

    source_path = f"gs://{bucket}/landing/{table_name}/{version}"
    table_full = f"{catalog}.{ns}.{table_name}"

    log_header(f"INGEST: {table_name.upper()} ({version})")
    log("ingest", f"Source: {source_path}")
    log("ingest", f"Target: {table_full}")

    # Read landing data
    df = spark.read.json(source_path)
    df = df.withColumn("ingestion_ts", current_timestamp())

    log_table_info(df, table_name)

    if version == "v1":
        df.writeTo(table_full).createOrReplace()
        log("ingest", f"Created table: {table_full}")
    else:
        evolver = SchemaEvolver(spark, table_config)
        df = evolver.apply_evolution(df, table_full)
        df_aligned = evolver.align_dataframe(df, table_full)
        df_aligned.writeTo(table_full).append()
        log("ingest", f"Appended to: {table_full} (schema evolved)")

    final_count = spark.read.table(table_full).count()
    log("ingest", f"Total records: {final_count}")


def main():
    print(BANNER)
    args = parse_args("bt-df-lkhouse-fw Ingest: Landing → Reservoir")
    config = load_config(args.config)

    spark = get_spark("ingest")
    catalog = config["pipeline"]["catalog"]
    ns = config["pipeline"]["namespaces"]["reservoir"]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{ns}")

    if args.all:
        tables = list(config["tables"].keys())
    elif args.table:
        tables = [args.table]
    else:
        raise ValueError("Specify --table <name> or --all")

    for table in tables:
        ingest_table(spark, config, table, args.version)

    log_header("INGEST COMPLETE")
    spark.stop()


if __name__ == "__main__":
    main()
