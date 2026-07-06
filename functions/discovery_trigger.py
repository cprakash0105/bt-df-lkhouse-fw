"""EastSide — Discovery Trigger (Cloud Function Gen2).
Triggers when new data lands in gs://eastside-lakehouse/landing/{dataset}/.
Profiles the data, calls LLM to generate config, pushes config to GCS.
The config landing then triggers the existing pipeline_trigger function.

Trigger: GCS object finalize on gs://eastside-lakehouse/landing/**
Runtime: Python 3.12, 540s timeout, 512MB memory

Flow:
  Data lands → THIS FUNCTION → profiles → LLM generates config → pushes config
  Config lands → pipeline_trigger (existing) → Bronze → Silver → Gold
"""
import os
import json
import yaml
import urllib.request
import functions_framework
from google.cloud import storage


PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
BUCKET = os.environ.get("CONFIG_BUCKET", "eastside-lakehouse")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://bedrock-mantle.eu-north-1.api.aws/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "openai.gpt-oss-120b")
LLM_PROJECT = os.environ.get("LLM_PROJECT", "default")

# Track datasets already being processed (avoid re-trigger on multiple files)
_processing = set()


@functions_framework.cloud_event
def discovery_trigger(cloud_event):
    """Triggered by GCS object finalize on landing/**"""
    data = cloud_event.data
    bucket_name = data["bucket"]
    file_name = data["name"]

    # Only trigger for landing data files
    if not file_name.startswith("landing/"):
        return
    # Skip marker files
    if file_name.endswith(".keep") or file_name.endswith("_SUCCESS"):
        return

    # Extract dataset name: landing/{dataset}/v1/file.jsonl → dataset
    parts = file_name.split("/")
    if len(parts) < 3:
        return
    dataset_name = parts[1]

    # Deduplicate: only process once per dataset per invocation
    if dataset_name in _processing:
        return
    _processing.add(dataset_name)

    # Check if config already exists (don't re-discover)
    gcs = storage.Client(project=PROJECT_ID)
    bucket = gcs.bucket(bucket_name)
    config_blob = bucket.blob(f"config/tables/{dataset_name}.yaml")
    if config_blob.exists():
        print(f"Config already exists for {dataset_name} — skipping discovery")
        return

    print(f"{'=' * 60}")
    print(f"  DISCOVERY TRIGGERED: {dataset_name}")
    print(f"  File: gs://{bucket_name}/{file_name}")
    print(f"{'=' * 60}")

    try:
        # 1. Profile the landing data
        profile = profile_dataset(gcs, bucket_name, dataset_name)
        if not profile:
            print(f"  No data to profile for {dataset_name}")
            return

        # 2. Generate config via LLM
        yaml_content = generate_config(dataset_name, profile)
        if not yaml_content:
            print(f"  LLM failed to generate config for {dataset_name}")
            return

        # 3. Validate
        parsed = yaml.safe_load(yaml_content)
        if not parsed or "table" not in parsed:
            print(f"  Invalid YAML generated for {dataset_name}")
            return

        # 4. Persist profile
        profile_blob = bucket.blob(f"profiles/{dataset_name}/latest.json")
        profile_blob.upload_from_string(
            json.dumps(profile, indent=2), content_type="application/json"
        )

        # 5. Push config → this triggers pipeline_trigger function
        config_blob.upload_from_string(yaml_content, content_type="text/yaml")
        print(f"  ✅ Config pushed: gs://{bucket_name}/config/tables/{dataset_name}.yaml")
        print(f"  → Pipeline will be triggered automatically")

    except Exception as e:
        print(f"  ❌ Discovery failed for {dataset_name}: {e}")
        raise


def profile_dataset(gcs, bucket_name: str, dataset_name: str) -> dict:
    """Lightweight profiling of landing data."""
    bucket = gcs.bucket(bucket_name)
    prefix = f"landing/{dataset_name}/"
    blobs = list(bucket.list_blobs(prefix=prefix, max_results=5))

    data_blobs = [b for b in blobs if not b.name.endswith((".keep", "_SUCCESS"))]
    if not data_blobs:
        return None

    blob = data_blobs[0]
    content = blob.download_as_text()
    if not content.strip():
        return None

    # Parse based on format
    if blob.name.endswith(".csv"):
        rows = parse_csv(content)
    else:
        rows = parse_jsonl(content)

    if not rows:
        return None

    # Build profile
    columns = list(rows[0].keys())
    fields = []
    for col in columns:
        values = [str(row.get(col, "")).strip() for row in rows]
        non_null = [v for v in values if v and v.lower() not in ("", "null", "none")]
        distinct = set(non_null)

        field_info = {
            "name": col,
            "type": infer_type(non_null),
            "null_pct": round((len(values) - len(non_null)) / max(len(values), 1), 2),
            "distinct_count": len(distinct),
            "is_pii": detect_pii(col, non_null),
            "is_key": len(distinct) / max(len(values), 1) > 0.95 and len(non_null) / max(len(values), 1) > 0.99,
        }
        if len(distinct) <= 10:
            field_info["distinct_values"] = sorted(list(distinct))[:10]
        fields.append(field_info)

    return {
        "dataset_name": dataset_name,
        "row_count": len(rows),
        "column_count": len(columns),
        "source_path": f"gs://{bucket_name}/{blob.name}",
        "source_format": "csv" if blob.name.endswith(".csv") else "json",
        "has_cdc": any(f["name"] == "_cdc_operation" for f in fields),
        "fields": fields,
    }


def parse_csv(content: str) -> list:
    import csv
    import io
    reader = csv.DictReader(io.StringIO(content))
    return [row for i, row in enumerate(reader) if i < 5000]


def parse_jsonl(content: str) -> list:
    rows = []
    for line in content.strip().split("\n"):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if len(rows) >= 5000:
            break
    return rows


def infer_type(values: list) -> str:
    if not values:
        return "string"
    sample = values[:100]
    int_count = sum(1 for v in sample if v.replace("-", "").replace(",", "").isdigit())
    float_count = sum(1 for v in sample if is_float(v))
    bool_count = sum(1 for v in sample if v.lower() in ("true", "false"))
    date_count = sum(1 for v in sample if looks_like_date(v))

    total = len(sample)
    if int_count / total > 0.7:
        return "integer"
    if float_count / total > 0.7:
        return "decimal"
    if bool_count / total > 0.7:
        return "boolean"
    if date_count / total > 0.7:
        return "date"
    return "string"


def is_float(v: str) -> bool:
    try:
        float(v.replace(",", ""))
        return "." in v
    except (ValueError, TypeError):
        return False


def looks_like_date(v: str) -> bool:
    import re
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}", v))


def detect_pii(col_name: str, values: list) -> bool:
    import re
    pii_keywords = {"first_name", "last_name", "email", "phone", "mobile",
                    "date_of_birth", "dob", "address", "postcode", "ssn",
                    "national_id", "passport", "aadhaar", "pan"}
    if col_name.lower() in pii_keywords:
        return True
    # Check email pattern in values
    sample = values[:50]
    email_count = sum(1 for v in sample if re.match(r"^[\w.+-]+@[\w.-]+\.\w{2,}$", v))
    if email_count / max(len(sample), 1) > 0.5:
        return True
    return False


def generate_config(dataset_name: str, profile: dict) -> str:
    """Call LLM to generate pipeline config YAML."""
    fields_desc = []
    for f in profile["fields"]:
        desc = f"  - {f['name']}: {f['type']}"
        if f["is_pii"]:
            desc += " [PII]"
        if f["is_key"]:
            desc += " [KEY]"
        if f.get("distinct_values"):
            desc += f" (values: {f['distinct_values']})"
        if f["null_pct"] > 0.1:
            desc += f" (nulls: {f['null_pct']:.0%})"
        fields_desc.append(desc)

    system = """You are a data engineering config generator for a lakehouse pipeline.
Generate a YAML config for a table. Output ONLY valid YAML, no explanation.
The config must have these fields:
- table: (dataset name)
- description: (one line)
- source_format: json or csv
- source_system: (infer from name)
- domain: (infer: sales, supply_chain, customer, product, procurement, hr)
- business_application: (infer: retail_pos, ecommerce, warehouse_mgmt, loyalty, merchandising, erp, returns_portal, hr_system)
- is_cdc: true/false
- primary_key: (the most likely PK field)
- dedup_order_by: (a timestamp or date field DESC)
- hash_fields: [list of business key fields for dedup hash]
- dq_rules:
    not_null: [fields that should never be null]
    positive: [numeric fields that should be > 0]
    accepted_values: {field: [values]} for low-cardinality fields (only if distinct values provided)
- pii_fields: [fields containing personal data]
- policy:
    bronze: detective
    silver: preventative
- schema_evolution:
    bronze:
      allowed: [add_column, type_widen, drop_column]
    silver:
      allowed: [add_column, type_widen]
      blocked: [drop_column, type_narrow]"""

    user = f"""Dataset: {dataset_name}
Source format: {profile['source_format']}
CDC: {profile['has_cdc']}
Row count: {profile['row_count']}
Fields:
{chr(10).join(fields_desc)}"""

    # Call LLM
    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 1024,
        "temperature": 0.1,
    })

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
    }
    if LLM_PROJECT:
        headers["OpenAI-Project"] = LLM_PROJECT

    url = f"{LLM_BASE_URL}/chat/completions"
    req = urllib.request.Request(url, data=payload.encode(), headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode())
        msg = result["choices"][0]["message"]
        text = msg.get("content") or msg.get("reasoning") or ""
        # Strip markdown fences
        if text.strip().startswith("```"):
            lines = text.strip().split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        return text.strip()
    except Exception as e:
        print(f"  LLM call failed: {e}")
        return None
