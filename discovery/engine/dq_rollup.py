"""DQ Rollup — aggregates physical DQ check results up to BDE and BA level.

Reads all dq_results/{table}/*.json from GCS, groups by bde_id and
business_application, computes scores, writes:
  gs://eastside-lakehouse/dq_scores/bde/{bde_id}.json
  gs://eastside-lakehouse/dq_scores/ba/{ba_id}.json

BDE score = average column score across all tables that contain that BDE.
BA score  = average BDE score across all BDEs owned by that BA.
"""
import json
import os
from datetime import datetime, timezone
from collections import defaultdict

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
BUCKET = "eastside-lakehouse"


def run_rollup() -> dict:
    """Read all DQ results, compute BDE + BA scores, write to GCS. Returns summary."""
    results = _load_all_results()
    if not results:
        return {"bde_count": 0, "ba_count": 0, "error": "no_results"}

    # Group column results by bde_id
    bde_columns: dict[str, list] = defaultdict(list)  # bde_id -> [col_result, ...]
    bde_tables: dict[str, set] = defaultdict(set)     # bde_id -> {table, ...}
    ba_bdes: dict[str, set] = defaultdict(set)        # ba_id -> {bde_id, ...}

    for result in results:
        table = result["table"]
        ba_id = result.get("business_application", "")
        for col in result.get("columns", []):
            bde_id = col.get("bde_id")
            if not bde_id:
                continue
            bde_columns[bde_id].append({
                "table": table,
                "column": col["column"],
                "score": col["score"],
                "results": col.get("results", {}),
                "is_pii": col.get("is_pii", False),
            })
            bde_tables[bde_id].add(table)
            if ba_id:
                ba_bdes[ba_id].add(bde_id)

    # Compute + write BDE scores
    bde_scores: dict[str, int] = {}
    for bde_id, cols in bde_columns.items():
        score = round(sum(c["score"] for c in cols) / len(cols))
        bde_scores[bde_id] = score
        doc = {
            "bde_id": bde_id,
            "score": score,
            "tables": list(bde_tables[bde_id]),
            "column_count": len(cols),
            "columns": cols,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
        _write(f"dq_scores/bde/{bde_id}.json", doc)

    # Compute + write BA scores
    ba_count = 0
    for ba_id, bde_ids in ba_bdes.items():
        scored_bdes = [bde_id for bde_id in bde_ids if bde_id in bde_scores]
        if not scored_bdes:
            continue
        ba_score = round(sum(bde_scores[b] for b in scored_bdes) / len(scored_bdes))
        doc = {
            "ba_id": ba_id,
            "score": ba_score,
            "bde_count": len(scored_bdes),
            "bdes": [
                {"bde_id": b, "score": bde_scores[b]}
                for b in sorted(scored_bdes, key=lambda x: bde_scores[x])
            ],
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
        _write(f"dq_scores/ba/{ba_id}.json", doc)
        ba_count += 1

    print(f"[DQRollup] BDEs scored: {len(bde_scores)}, BAs scored: {ba_count}")
    return {"bde_count": len(bde_scores), "ba_count": ba_count}


def get_bde_score(bde_id: str) -> dict | None:
    return _read(f"dq_scores/bde/{bde_id}.json")


def get_ba_score(ba_id: str) -> dict | None:
    return _read(f"dq_scores/ba/{ba_id}.json")


def _load_all_results() -> list[dict]:
    """Load all dq_results from GCS."""
    results = []
    try:
        from google.cloud import storage
        client = storage.Client(project=PROJECT_ID)
        for blob in client.list_blobs(BUCKET, prefix="dq_results/"):
            if not blob.name.endswith(".json"):
                continue
            try:
                results.append(json.loads(blob.download_as_text()))
            except Exception:
                pass
    except Exception as e:
        print(f"[DQRollup] Load failed: {e}")
    return results


def _write(path: str, doc: dict):
    try:
        from google.cloud import storage
        client = storage.Client(project=PROJECT_ID)
        client.bucket(BUCKET).blob(path).upload_from_string(
            json.dumps(doc, indent=2), content_type="application/json"
        )
    except Exception as e:
        print(f"[DQRollup] Write failed ({path}): {e}")


def _read(path: str) -> dict | None:
    try:
        from google.cloud import storage
        client = storage.Client(project=PROJECT_ID)
        blob = client.bucket(BUCKET).blob(path)
        if blob.exists():
            return json.loads(blob.download_as_text())
    except Exception as e:
        print(f"[DQRollup] Read failed ({path}): {e}")
    return None
