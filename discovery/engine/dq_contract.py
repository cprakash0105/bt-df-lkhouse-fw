"""DQ Contract Generator — semantic layer DQ control.

At approval time, maps each physical column → its linked BDE → inherits
that BDE's dq_rules. Writes a contract JSON to GCS:
  gs://{bucket}/dq_contracts/{table}.json

Contract schema:
{
  "table": "customers",
  "business_application": "customer_management",
  "domain": "customer",
  "generated_at": "...",
  "columns": [
    {
      "column": "customer_id",
      "bde_id": "customer_id",
      "bde_name": "Customer ID",
      "is_pii": true,
      "rules": {"not_null": true, "unique": true}
    },
    ...
  ]
}
"""
import json
import os
from datetime import datetime, timezone
from typing import Optional

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
BUCKET = os.environ.get("CONFIG_BUCKET", "bt-df-lkhouse-lakehouse")
EASTSIDE_BUCKET = "eastside-lakehouse"


def generate_contract(suggestion, knowledge_graph) -> Optional[dict]:
    """Build a DQ contract from an approved DiscoverySuggestion + KnowledgeGraph.

    Returns the contract dict (also written to GCS).
    """
    columns = []
    for field in suggestion.fields:
        # Inherit rules from linked BDE if available, else use field-level rules
        bde_rules = {}
        bde_id = field.linked_term
        bde_name = field.linked_term_name or field.field_name

        if bde_id and bde_id in knowledge_graph.terms:
            term = knowledge_graph.terms[bde_id]
            bde_rules = dict(term.dq_rules)
            bde_name = term.name

        # Merge field-level rules on top (field-level wins)
        merged_rules = {**bde_rules, **field.dq_rules}

        if not merged_rules and not field.is_pii:
            continue  # skip columns with no rules and no PII flag

        columns.append({
            "column": field.field_name,
            "bde_id": bde_id or "",
            "bde_name": bde_name,
            "is_pii": field.is_pii,
            "rules": merged_rules,
        })

    contract = {
        "table": suggestion.asset_name,
        "business_application": suggestion.business_application or "",
        "business_application_name": suggestion.business_application_name or "",
        "domain": suggestion.data_domain or "",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "columns": columns,
    }

    _write_to_gcs(suggestion.asset_name, contract)
    return contract


def _write_to_gcs(table_name: str, contract: dict):
    try:
        from google.cloud import storage
        client = storage.Client(project=PROJECT_ID)

        # Route to eastside bucket if dataset lives there
        target_bucket = BUCKET
        try:
            blobs = list(client.bucket(EASTSIDE_BUCKET).list_blobs(
                prefix=f"landing/{table_name}/", max_results=1
            ))
            if blobs:
                target_bucket = EASTSIDE_BUCKET
        except Exception:
            pass

        blob = client.bucket(target_bucket).blob(f"dq_contracts/{table_name}.json")
        blob.upload_from_string(
            json.dumps(contract, indent=2),
            content_type="application/json",
        )
        print(f"[DQContract] Written: gs://{target_bucket}/dq_contracts/{table_name}.json")
    except Exception as e:
        print(f"[DQContract] GCS write failed: {e}")


def load_contract(table_name: str) -> Optional[dict]:
    """Load a DQ contract from GCS. Checks both buckets."""
    try:
        from google.cloud import storage
        client = storage.Client(project=PROJECT_ID)
        for bucket_name in [EASTSIDE_BUCKET, BUCKET]:
            blob = client.bucket(bucket_name).blob(f"dq_contracts/{table_name}.json")
            if blob.exists():
                return json.loads(blob.download_as_text())
    except Exception as e:
        print(f"[DQContract] Load failed for {table_name}: {e}")
    return None


def list_contracts() -> list[str]:
    """List all tables that have a DQ contract."""
    tables = []
    try:
        from google.cloud import storage
        client = storage.Client(project=PROJECT_ID)
        for bucket_name in [EASTSIDE_BUCKET, BUCKET]:
            try:
                for blob in client.list_blobs(bucket_name, prefix="dq_contracts/"):
                    if blob.name.endswith(".json"):
                        tables.append(blob.name.replace("dq_contracts/", "").replace(".json", ""))
            except Exception:
                pass
    except Exception as e:
        print(f"[DQContract] List failed: {e}")
    return list(set(tables))
