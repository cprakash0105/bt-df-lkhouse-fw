"""EastSide CDH 2.0 — Catalog Tagger (Post-Pipeline).
After pipeline creates physical tables, this tags columns with BDE glossary terms
in Dataplex Knowledge Catalog. Completes the TDE → BDE link.

Registers:
- Physical table entries (bronze, silver, gold) with metadata
- PII field annotations
- DQ rule summaries
- Schema evolution policy

Run after pipeline:
    spark-submit eastside/engine/catalog_tag.py \
        --config gs://eastside-lakehouse/config/pipeline.yaml --all

    # Single table:
    spark-submit eastside/engine/catalog_tag.py \
        --config gs://eastside-lakehouse/config/pipeline.yaml --table pos_transactions
"""
import sys
import os
from base import (
    load_config, get_all_tables, get_table_config,
    parse_args, resolve_pipeline_vars, log, log_header,
    log_error, log_summary, flush_logs_to_gcs, BANNER, LogLevel,
)

LOCATION = "europe-west2"
ENTRY_GROUP_ID = "enterprise-hierarchy"


def tag_table(table_config: dict, pipeline: dict):
    """Register a physical table in Dataplex and tag columns with metadata."""
    try:
        from google.cloud import dataplex_v1
        from google.cloud.dataplex_v1 import CatalogServiceClient
    except ImportError:
        log("catalog", "google-cloud-dataplex not installed — skipping", LogLevel.WARN)
        return "SKIPPED"

    table_name = table_config["table"]
    project_id = pipeline["project_id"]
    bucket = pipeline["bucket"]
    catalog = pipeline["catalog"]
    bronze_ns = pipeline["bronze_namespace"]
    silver_ns = pipeline["silver_namespace"]

    pk = table_config.get("primary_key", "")
    pii_fields = table_config.get("pii_fields", [])
    dq_rules = table_config.get("dq_rules", {})
    schema_evo = table_config.get("schema_evolution", {})
    source_format = table_config.get("source_format", "json")
    metadata = table_config.get("_metadata", {})
    domain = metadata.get("data_domain", "unknown")
    ba = metadata.get("business_application", "unknown")

    log("catalog", f"[{table_name}] Tagging — domain={domain}, BA={ba}")
    log("catalog", f"[{table_name}] PK={pk}, PII={pii_fields}, format={source_format}")

    client = CatalogServiceClient()
    parent = f"projects/{project_id}/locations/{LOCATION}"
    entry_group = f"{parent}/entryGroups/{ENTRY_GROUP_ID}"
    fq_type = f"{parent}/entryTypes/dataset"

    # Register entries for each layer
    layers = [
        ("bronze", f"gs://{bucket}/bronze/{table_name}/", f"{catalog}.{bronze_ns}.{table_name}"),
        ("silver", f"gs://{bucket}/silver/{table_name}/", f"{catalog}.{silver_ns}.{table_name}"),
        ("gold", f"BigQuery: {project_id}.{pipeline.get('dataproduct_dataset', 'eastside_dataproduct')}.{table_name}", "BigQuery native"),
    ]

    registered = 0
    for layer, location, catalog_ref in layers:
        entry_id = f"eastside-{layer}-{table_name.replace('_', '-')}"

        # Build description with full metadata
        desc_parts = [
            f"Physical Table: {table_name}",
            f"Layer: {layer.upper()}",
            f"Location: {location}",
            f"Format: {'Iceberg (BLMS)' if layer != 'gold' else 'BigQuery native'}",
            f"Catalog Ref: {catalog_ref}",
            f"Domain: {domain}",
            f"Business Application: {ba}",
            f"Primary Key: {pk}",
            f"Source Format: {source_format}",
            f"PII Fields: {', '.join(pii_fields) if pii_fields else 'None'}",
        ]

        if layer == "bronze":
            desc_parts.append(f"DQ Policy: Detective (flag only)")
            desc_parts.append(f"Schema Evolution: {schema_evo.get('allowed', ['add_column', 'type_widen', 'drop_column'])}")
        elif layer == "silver":
            desc_parts.append(f"DQ Policy: Preventative (reject)")
            desc_parts.append(f"Schema Evolution: {schema_evo.get('allowed', ['add_column', 'type_widen'])} | Blocked: {schema_evo.get('blocked', ['drop_column', 'type_narrow'])}")
            desc_parts.append(f"SCD: Type 2 (valid_from, valid_to, is_current)")
        elif layer == "gold":
            desc_parts.append(f"DQ Policy: Contract locked")
            desc_parts.append(f"Schema Evolution: Contract versioned")

        # DQ rules summary
        if dq_rules:
            desc_parts.append(f"DQ Rules: not_null={dq_rules.get('not_null', [])}, "
                            f"positive={dq_rules.get('positive', [])}, "
                            f"accepted_values={list(dq_rules.get('accepted_values', {}).keys())}")

        entry = dataplex_v1.Entry(
            entry_type=fq_type,
            fully_qualified_name=f"custom:eastside-{layer}/{table_name}",
            entry_source=dataplex_v1.EntrySource(
                description="\n".join(desc_parts),
                display_name=f"[EastSide {layer.title()}] {table_name}",
            ),
        )
        req = dataplex_v1.CreateEntryRequest(
            parent=entry_group, entry=entry, entry_id=entry_id
        )

        try:
            client.create_entry(request=req)
            log("catalog", f"[{table_name}] Registered {layer} entry")
            registered += 1
        except Exception as e:
            if "ALREADY_EXISTS" in str(e):
                # Update existing entry
                try:
                    entry.name = f"{entry_group}/entries/{entry_id}"
                    update_req = dataplex_v1.UpdateEntryRequest(entry=entry)
                    client.update_entry(request=update_req)
                    log("catalog", f"[{table_name}] Updated {layer} entry")
                    registered += 1
                except Exception as ue:
                    log("catalog", f"[{table_name}] Update {layer} failed: {ue}", LogLevel.WARN)
            else:
                log_error("catalog", f"[{table_name}] Failed to register {layer}", e)

    return "SUCCESS" if registered > 0 else "FAILED"


def ensure_entry_group(project_id: str):
    """Create the entry group if it doesn't exist."""
    try:
        from google.cloud import dataplex_v1
        from google.cloud.dataplex_v1 import CatalogServiceClient

        client = CatalogServiceClient()
        parent = f"projects/{project_id}/locations/{LOCATION}"
        entry_group_name = f"{parent}/entryGroups/{ENTRY_GROUP_ID}"

        try:
            client.get_entry_group(name=entry_group_name)
            log("catalog", f"Entry group exists: {ENTRY_GROUP_ID}")
        except Exception:
            req = dataplex_v1.CreateEntryGroupRequest(
                parent=parent,
                entry_group_id=ENTRY_GROUP_ID,
                entry_group=dataplex_v1.EntryGroup(
                    description="EastSide CDH 2.0 — Enterprise Data Hierarchy",
                ),
            )
            client.create_entry_group(request=req)
            log("catalog", f"Created entry group: {ENTRY_GROUP_ID}")
    except ImportError:
        log("catalog", "google-cloud-dataplex not installed", LogLevel.WARN)
    except Exception as e:
        log("catalog", f"Entry group check failed: {e}", LogLevel.WARN)


def main():
    print(BANNER)
    args = parse_args("EastSide CDH 2.0 — Catalog Tagger: Post-pipeline TDE→BDE linking")
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
    log("catalog", f"Project: {project_id}")
    log("catalog", f"Tables: {tables}")

    # Ensure entry group exists
    ensure_entry_group(project_id)

    results = {}
    for table in tables:
        try:
            table_config = get_table_config(config, table)
            result = tag_table(table_config, pipeline)
            results[table] = result
        except Exception as e:
            log_error("catalog", f"Table '{table}' failed", e)
            results[table] = "FAILED"

    log_summary("catalog", results)
    flush_logs_to_gcs("catalog", config)
    log_header("CATALOG TAGGING COMPLETE")

    if "FAILED" in results.values():
        sys.exit(1)


if __name__ == "__main__":
    main()
