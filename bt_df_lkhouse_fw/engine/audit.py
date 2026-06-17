"""bt-df-lkhouse-fw — Audit Engine.
Records pipeline execution metadata to Iceberg audit table in CCN."""
from bt_df_lkhouse_fw.engine.base import log, LogLevel
from datetime import datetime


def write_audit(spark, config: dict, stage: str, results: dict, version: str = ""):
    """Write audit records to lakehouse.ccn.pipeline_audit."""
    try:
        from pyspark.sql.types import StructType, StructField, StringType, LongType
        from pyspark.sql.functions import current_timestamp

        pipeline = config["pipeline"]
        catalog = pipeline["catalog"]
        ns_ccn = pipeline["ccn_namespace"]
        reservoir_path = pipeline["reservoir_path"]

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        rows = []

        for table_name, status in results.items():
            reservoir_count = 0
            ccn_count = 0

            try:
                reservoir_count = spark.read.parquet(f"{reservoir_path}/{table_name}").count()
            except Exception:
                pass

            try:
                ccn_count = spark.read.table(f"{catalog}.{ns_ccn}.{table_name}").count()
            except Exception:
                pass

            rows.append((run_id, stage, version, table_name, status, reservoir_count, ccn_count))

        if not rows:
            return

        schema = StructType([
            StructField("run_id", StringType(), False),
            StructField("stage", StringType(), False),
            StructField("version", StringType(), True),
            StructField("table_name", StringType(), False),
            StructField("status", StringType(), False),
            StructField("reservoir_count", LongType(), True),
            StructField("ccn_count", LongType(), True),
        ])

        df = spark.createDataFrame(rows, schema)
        df = df.withColumn("audit_timestamp", current_timestamp())

        audit_table = f"{catalog}.{ns_ccn}.pipeline_audit"
        try:
            df.writeTo(audit_table).append()
        except Exception:
            df.writeTo(audit_table).createOrReplace()

        log("audit", f"Written {len(rows)} audit records (run_id={run_id}, stage={stage})")

    except Exception as e:
        log("audit", f"Audit write failed (non-fatal): {e}", LogLevel.WARN)
