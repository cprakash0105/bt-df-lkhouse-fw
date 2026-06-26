"""bt-df-lkhouse-fw — Consume Engine (CCN Iceberg → Data Product BigQuery).
Auto-discovers SQL files and SCD YAML configs from config/consumption/.
- .sql files: executed as CREATE OR REPLACE TABLE (full refresh)
- .yaml files: processed via SCD Engine (Type 1/2/3/4/6)
Add a new view: drop a .sql or .yaml file into config/consumption/ → engine deploys it."""
import sys
import yaml as yaml_lib
from pathlib import Path
from bt_df_lkhouse_fw.engine.base import (
    load_config, get_all_consumption_views,
    parse_args, resolve_pipeline_vars, log, log_header,
    log_error, log_summary, flush_logs_to_gcs, BANNER, LogLevel,
)
from bt_df_lkhouse_fw.engine.scd import SCDEngine


def execute_bq_sql(sql: str, view_name: str, project_id: str) -> bool:
    """Execute SQL in BigQuery using the bigquery client."""
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=project_id)

        # Substitute project variable
        resolved_sql = sql.replace("${PROJECT_ID}", project_id)

        log("bq", f"[{view_name}] Executing SQL ({len(resolved_sql)} chars)")
        job = client.query(resolved_sql)
        job.result()  # Wait for completion

        log("bq", f"[{view_name}] ✅ Deployed successfully (job: {job.job_id})")

        # Get row count if it's a CREATE TABLE
        if "CREATE OR REPLACE TABLE" in resolved_sql.upper():
            table_ref = None
            # Extract table reference from SQL
            for part in resolved_sql.split("`"):
                if project_id in part:
                    table_ref = part
                    break
            if table_ref:
                table = client.get_table(table_ref)
                log("bq", f"[{view_name}] Rows: {table.num_rows}")

        return True

    except Exception as e:
        log_error("bq", f"[{view_name}] Failed", e)
        return False


def main():
    print(BANNER)
    args = parse_args("bt-df-lkhouse-fw Consume: CCN (Iceberg) → Data Product (BigQuery)")
    config = load_config(args.config)
    config = resolve_pipeline_vars(config, args)

    pipeline = config["pipeline"]
    project_id = pipeline["project_id"]
    dataset = pipeline["dataproduct_dataset"]

    views = get_all_consumption_views(config)

    if not views:
        log("consume", "No SQL files found in config/consumption/", LogLevel.WARN)
        sys.exit(0)

    log_header("DEPLOYING DATA PRODUCT VIEWS (BigQuery)")
    log("consume", f"Project: {project_id}")
    log("consume", f"Dataset: {dataset}")

    # Ensure dataset exists
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=project_id)
        ds_ref = bigquery.DatasetReference(project_id, dataset)
        try:
            client.get_dataset(ds_ref)
            log("consume", f"Dataset '{dataset}' exists")
        except Exception:
            ds = bigquery.Dataset(ds_ref)
            ds.location = pipeline.get("region", "europe-west2")
            client.create_dataset(ds)
            log("consume", f"Created dataset: {dataset}")
    except Exception as e:
        log_error("consume", f"Cannot verify/create dataset: {dataset}", e)
        sys.exit(1)

    if args.all:
        targets = list(views.keys())
    elif args.target:
        targets = [args.target]
    else:
        log_error("consume", "Specify --target <name> or --all")
        sys.exit(1)

    log("consume", f"Views to deploy: {targets}")

    # Load SCD configs if present
    scd_configs = _load_scd_configs(config)
    if scd_configs:
        log("consume", f"SCD dimensions found: {list(scd_configs.keys())}")

    results = {}
    for target in targets:
        if target in scd_configs:
            # SCD-based dimension
            log("consume", f"Deploying SCD: {target} (Type {scd_configs[target].get('scd_type', '?')})")
            scd = SCDEngine(project_id, dataset)
            scd_conf = scd_configs[target]
            scd.ensure_table_schema(scd_conf)
            success = scd.apply_scd(scd_conf)
            results[target] = "SUCCESS" if success else "FAILED"
        elif target in views:
            # SQL-based view (full refresh)
            sql = views[target]
            log("consume", f"Deploying SQL: {target}")
            success = execute_bq_sql(sql, target, project_id)
            results[target] = "SUCCESS" if success else "FAILED"
        else:
            log("consume", f"Target '{target}' not found. Available: {list(views.keys()) + list(scd_configs.keys())}", LogLevel.WARN)
            results[target] = "SKIPPED"

    log_summary("consume", results)
    log_header("CONSUME COMPLETE")
    flush_logs_to_gcs("consume", config)

    if "FAILED" in results.values():
        sys.exit(1)


def _load_scd_configs(config: dict) -> dict:
    """Load SCD YAML configs from config/consumption/*.yaml"""
    scd_configs = {}
    config_path = config.get("_config_dir", "")
    if not config_path:
        # Try standard location
        possible = Path("bt_df_lkhouse_fw/config/consumption")
        if not possible.exists():
            possible = Path("config/consumption")
        config_path = str(possible)

    consumption_dir = Path(config_path) if Path(config_path).exists() else None
    if not consumption_dir:
        return scd_configs

    for yaml_file in consumption_dir.glob("*.yaml"):
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml_lib.safe_load(f)
            if isinstance(data, dict):
                for name, conf in data.items():
                    if isinstance(conf, dict) and "scd_type" in conf:
                        scd_configs[name] = conf
        except Exception as e:
            log("consume", f"Failed to load SCD config {yaml_file}: {e}", LogLevel.WARN)

    return scd_configs


if __name__ == "__main__":
    main()
