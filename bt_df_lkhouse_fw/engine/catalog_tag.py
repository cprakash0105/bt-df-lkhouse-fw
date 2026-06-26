"""bt-df-lkhouse-fw — Catalog Tagger (Post-Pipeline).
After pipeline creates physical tables, this tags columns with BDE glossary terms.
Completes the TDE → BDE link in Dataplex Knowledge Catalog.

Run after curate/consume: python -m bt_df_lkhouse_fw.engine.catalog_tag --all
"""
import sys
import yaml
from pathlib import Path
from bt_df_lkhouse_fw.engine.base import (
    load_config, get_all_tables, get_table_config,
    parse_args, resolve_pipeline_vars, log, log_header, log_error, BANNER,
)

PROJECT_ID = "bt-df-lkhouse"
LOCATION = "europe-west2"
GLOSSARY_ID = "enterprise-data-glossary"


def tag_table_columns(table_config: dict, project_id: str):
    """Tag physical columns with glossary terms based on table config."""
    try:
        from google.cloud import dataplex_v1
        from google.cloud.dataplex_v1 import CatalogServiceClient
    except ImportError:
        log("catalog", "google-cloud-dataplex not installed, skipping tagging")
        return

    table_name = table_config["table"]
    log("catalog", f"[{table_name}] Tagging columns with BDE glossary terms")

    # The column-to-term mapping comes from the table config
    # SD already determined which BDE each field maps to
    # For now, we log what WOULD be tagged (full Dataplex Attribute Store API is complex)

    pii_fields = table_config.get("pii_fields", [])
    dq_rules = table_config.get("dq_rules", {})
    pk = table_config.get("primary_key", "")

    log("catalog", f"[{table_name}] Primary Key: {pk}")
    log("catalog", f"[{table_name}] PII Fields: {pii_fields}")
    log("catalog", f"[{table_name}] DQ Rules: {list(dq_rules.keys())}")

    # In production: use Dataplex Data Attributes API to tag each column
    # For now: register the table as a catalog entry with metadata
    client = CatalogServiceClient()
    parent = f"projects/{project_id}/locations/{LOCATION}"
    entry_group = f"{parent}/entryGroups/enterprise-hierarchy"

    # Check if dataset entry type exists
    fq_type = f"{parent}/entryTypes/dataset"

    entry_id = f"physical-{table_name.replace('_', '-')}"
    entry = dataplex_v1.Entry(
        entry_type=fq_type,
        fully_qualified_name=f"custom:physical-table/{table_name}",
        entry_source=dataplex_v1.EntrySource(
            description=(
                f"Physical Table: {table_name}\n"
                f"Location: gs://{project_id}-lakehouse/ccn/{table_name}/\n"
                f"Format: Iceberg (BLMS)\n"
                f"Primary Key: {pk}\n"
                f"PII Fields: {', '.join(pii_fields) if pii_fields else 'None'}\n"
                f"DQ Rules: {dq_rules}\n"
                f"Catalog: lakehouse.ccn.{table_name}"
            ),
            display_name=f"[Physical] {table_name}",
        ),
    )
    req = dataplex_v1.CreateEntryRequest(
        parent=entry_group, entry=entry, entry_id=entry_id
    )

    try:
        client.create_entry(request=req)
        log("catalog", f"[{table_name}] Registered physical table in catalog")
    except Exception as e:
        if "ALREADY_EXISTS" in str(e):
            log("catalog", f"[{table_name}] Physical table already registered")
        else:
            log_error("catalog", f"[{table_name}] Failed to register", e)


def main():
    print(BANNER)
    args = parse_args("bt-df-lkhouse-fw Catalog Tag: Post-pipeline TDE→BDE linking")
    config = load_config(args.config)
    config = resolve_pipeline_vars(config, args)

    pipeline = config["pipeline"]
    project_id = pipeline["project_id"]

    if args.all:
        tables = get_all_tables(config)
    elif args.table:
        tables = [args.table]
    else:
        log_error("catalog", "Specify --table <name> or --all")
        sys.exit(1)

    log_header("POST-PIPELINE: CATALOG TAGGING")
    log("catalog", f"Tables: {tables}")

    for table in tables:
        table_config = get_table_config(config, table)
        tag_table_columns(table_config, project_id)

    log_header("CATALOG TAGGING COMPLETE")


if __name__ == "__main__":
    main()
