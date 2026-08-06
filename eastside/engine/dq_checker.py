"""DQ Checker — executes semantic DQ rules against physical BigQuery tables.

Reads a DQ contract from GCS, runs SQL checks in BigQuery,
writes results to GCS:
  gs://eastside-lakehouse/dq_results/{table}/{run_id}.json

Result schema:
{
  "table": "customers",
  "run_id": "...",
  "checked_at": "...",
  "layer": "gold",
  "overall_score": 94,
  "columns": [
    {
      "column": "customer_id",
      "bde_id": "customer_id",
      "rules_checked": {"not_null": true, "unique": true},
      "results": {"not_null": {"passed": true, "fail_count": 0, "total": 1000},
                  "unique":   {"passed": false, "fail_count": 3, "total": 1000}},
      "score": 85
    }
  ]
}
"""
import json
import os
from datetime import datetime, timezone

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
BUCKET = "eastside-lakehouse"

# BQ dataset per layer
LAYER_DATASET = {
    "bronze": "eastside_bronze",
    "silver": "eastside_silver",
    "gold": "eastside_gold",
}


def run_checks(table_name: str, run_id: str, layer: str = "gold") -> dict:
    """Load contract for table_name, run BQ checks, write + return results."""
    from google.cloud import bigquery, storage

    # Load contract
    contract = _load_contract(table_name)
    if not contract or not contract.get("columns"):
        return {"table": table_name, "run_id": run_id, "error": "no_contract", "overall_score": None}

    bq_dataset = LAYER_DATASET.get(layer, "eastside_gold")
    bq_table = f"`{PROJECT_ID}.{bq_dataset}.{table_name}`"
    bq = bigquery.Client(project=PROJECT_ID)

    # Get total row count once
    try:
        total_rows = list(bq.query(f"SELECT COUNT(*) AS n FROM {bq_table}").result())[0]["n"]
    except Exception as e:
        return {"table": table_name, "run_id": run_id, "error": f"table_not_found: {e}", "overall_score": None}

    column_results = []
    for col_def in contract["columns"]:
        col = col_def["column"]
        rules = col_def.get("rules", {})
        if not rules:
            continue

        rule_results = {}
        col_score = 100

        for rule, rule_val in rules.items():
            try:
                result = _check_rule(bq, bq_table, col, rule, rule_val, total_rows)
                rule_results[rule] = result
                if not result["passed"]:
                    # Deduct score proportional to failure rate
                    fail_rate = result["fail_count"] / max(total_rows, 1)
                    col_score -= min(40, round(fail_rate * 100 * 2))
            except Exception as e:
                rule_results[rule] = {"passed": None, "error": str(e)}

        column_results.append({
            "column": col,
            "bde_id": col_def.get("bde_id", ""),
            "bde_name": col_def.get("bde_name", col),
            "is_pii": col_def.get("is_pii", False),
            "rules_checked": rules,
            "results": rule_results,
            "score": max(0, col_score),
        })

    overall_score = (
        round(sum(c["score"] for c in column_results) / len(column_results))
        if column_results else 100
    )

    result_doc = {
        "table": table_name,
        "business_application": contract.get("business_application", ""),
        "domain": contract.get("domain", ""),
        "run_id": run_id,
        "layer": layer,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_rows": total_rows,
        "overall_score": overall_score,
        "columns": column_results,
    }

    _write_result(table_name, run_id, result_doc)
    return result_doc


def _check_rule(bq, bq_table: str, col: str, rule: str, rule_val, total_rows: int) -> dict:
    """Run a single rule check. Returns {passed, fail_count, total}."""
    if rule == "not_null":
        sql = f"SELECT COUNTIF(`{col}` IS NULL) AS fail_count FROM {bq_table}"
        row = list(bq.query(sql).result())[0]
        fail = row["fail_count"]
        return {"passed": fail == 0, "fail_count": fail, "total": total_rows}

    elif rule == "unique":
        sql = f"""
            SELECT COUNT(*) - COUNT(DISTINCT `{col}`) AS fail_count
            FROM {bq_table}
        """
        row = list(bq.query(sql).result())[0]
        fail = row["fail_count"]
        return {"passed": fail == 0, "fail_count": fail, "total": total_rows}

    elif rule == "accepted_values" and isinstance(rule_val, list):
        quoted = ", ".join(f"'{v}'" for v in rule_val)
        sql = f"""
            SELECT COUNTIF(`{col}` NOT IN ({quoted}) AND `{col}` IS NOT NULL) AS fail_count
            FROM {bq_table}
        """
        row = list(bq.query(sql).result())[0]
        fail = row["fail_count"]
        return {"passed": fail == 0, "fail_count": fail, "total": total_rows, "accepted": rule_val}

    elif rule == "pattern" and isinstance(rule_val, str):
        sql = f"""
            SELECT COUNTIF(NOT REGEXP_CONTAINS(CAST(`{col}` AS STRING), r'{rule_val}')
                           AND `{col}` IS NOT NULL) AS fail_count
            FROM {bq_table}
        """
        row = list(bq.query(sql).result())[0]
        fail = row["fail_count"]
        return {"passed": fail == 0, "fail_count": fail, "total": total_rows, "pattern": rule_val}

    elif rule == "min_value":
        sql = f"SELECT COUNTIF(`{col}` < {rule_val}) AS fail_count FROM {bq_table}"
        row = list(bq.query(sql).result())[0]
        fail = row["fail_count"]
        return {"passed": fail == 0, "fail_count": fail, "total": total_rows}

    elif rule == "max_value":
        sql = f"SELECT COUNTIF(`{col}` > {rule_val}) AS fail_count FROM {bq_table}"
        row = list(bq.query(sql).result())[0]
        fail = row["fail_count"]
        return {"passed": fail == 0, "fail_count": fail, "total": total_rows}

    else:
        return {"passed": None, "error": f"unsupported_rule: {rule}"}


def _load_contract(table_name: str) -> dict | None:
    try:
        from google.cloud import storage
        client = storage.Client(project=PROJECT_ID)
        for bucket_name in [BUCKET, f"{PROJECT_ID}-lakehouse"]:
            blob = client.bucket(bucket_name).blob(f"dq_contracts/{table_name}.json")
            if blob.exists():
                return json.loads(blob.download_as_text())
    except Exception as e:
        print(f"[DQChecker] Contract load failed: {e}")
    return None


def _write_result(table_name: str, run_id: str, result: dict):
    try:
        from google.cloud import storage
        client = storage.Client(project=PROJECT_ID)
        blob = client.bucket(BUCKET).blob(f"dq_results/{table_name}/{run_id}.json")
        blob.upload_from_string(json.dumps(result, indent=2), content_type="application/json")
        print(f"[DQChecker] Result written: gs://{BUCKET}/dq_results/{table_name}/{run_id}.json")
    except Exception as e:
        print(f"[DQChecker] Result write failed: {e}")
