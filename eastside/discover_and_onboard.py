"""EastSide — Ontika Discovery Onboarding.
Scans all datasets in GCS landing, profiles them, runs semantic discovery,
generates pipeline configs, and pushes to GCS.

Run from Cloud Shell:
    pip install google-cloud-storage python-dotenv pyyaml
    export LLM_PROVIDER=bedrock
    export LLM_API_KEY=<your_bedrock_api_key>
    export LLM_BASE_URL=https://bedrock-mantle.eu-north-1.api.aws/v1
    export LLM_MODEL=openai.gpt-oss-120b
    export LLM_PROJECT=default
    export AWS_REGION=eu-north-1
    python eastside/discover_and_onboard.py --project=bt-df-lkhouse
"""
import os
import sys
import json
import argparse
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from google.cloud import storage
from discovery.engine.discovery_profiler import DiscoveryProfiler
from discovery.engine.llm_client import get_llm


BUCKET = "eastside-lakehouse"
CONFIG_PREFIX = "config/tables"
LANDING_PREFIX = "landing"


def discover_datasets(project_id: str, bucket_name: str):
    """List all datasets in the landing zone."""
    client = storage.Client(project=project_id)
    bucket = client.bucket(bucket_name)
    blobs = bucket.list_blobs(prefix=f"{LANDING_PREFIX}/", delimiter="/")

    # Get prefixes (subdirectories = datasets)
    datasets = []
    for page in blobs.pages:
        for prefix in page.prefixes:
            name = prefix.replace(f"{LANDING_PREFIX}/", "").rstrip("/")
            if name:
                datasets.append(name)
    return sorted(datasets)


def profile_dataset(profiler: DiscoveryProfiler, dataset_name: str, bucket_name: str):
    """Profile a dataset from GCS landing."""
    print(f"\n  Profiling: {dataset_name}")
    profile = profiler.profile_from_gcs(dataset_name, bucket_name=bucket_name)
    if profile:
        print(f"    Rows: {profile.row_count}, Columns: {profile.column_count}")
        for fp in profile.fields:
            pii_flag = " [PII]" if fp.is_pii else ""
            key_flag = " [KEY]" if fp.is_key else ""
            print(f"      {fp.name}: {fp.inferred_type} (nulls: {fp.null_pct:.0%}, distinct: {fp.distinct_count}){pii_flag}{key_flag}")
    return profile


def generate_config_via_llm(dataset_name: str, profile) -> str:
    """Use LLM to generate a pipeline-ready YAML config from the profile."""
    llm = get_llm()

    # Build field descriptions from profile
    fields_desc = []
    for fp in profile.fields:
        desc = f"  - {fp.name}: {fp.inferred_type}"
        if fp.is_pii:
            desc += " [PII]"
        if fp.is_key:
            desc += " [KEY candidate]"
        if fp.distinct_values and len(fp.distinct_values) <= 10:
            desc += f" (values: {fp.distinct_values})"
        if fp.null_pct > 0.1:
            desc += f" (nulls: {fp.null_pct:.0%})"
        fields_desc.append(desc)

    # Detect CDC
    has_cdc = any(fp.name == "_cdc_operation" for fp in profile.fields)
    source_format = "csv" if profile.source_path.endswith(".csv") else "json"

    system = """You are a data engineering config generator for a lakehouse pipeline.
Generate a YAML config for a table. Output ONLY valid YAML, no explanation.
The config must have these fields:
- table: (dataset name)
- description: (one line)
- source_format: json or csv
- source_system: (infer from name)
- domain: (infer: sales, supply_chain, customer, product, procurement, hr)
- is_cdc: true/false
- primary_key: (the most likely PK field)
- dedup_order_by: (a timestamp or date field DESC)
- hash_fields: [list of business key fields for dedup hash]
- dq_rules:
    not_null: [fields that should never be null]
    positive: [numeric fields that should be > 0]
    accepted_values: {field: [values]} for low-cardinality fields
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
Source format: {source_format}
CDC: {has_cdc}
Row count: {profile.row_count}
Fields:
{chr(10).join(fields_desc)}"""

    print(f"    Generating config via LLM...")
    result = llm.generate(system, user, max_tokens=1024)
    return result


def push_config_to_gcs(client, bucket_name: str, dataset_name: str, yaml_content: str):
    """Push generated config to GCS."""
    bucket = client.bucket(bucket_name)
    blob_path = f"{CONFIG_PREFIX}/{dataset_name}.yaml"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(yaml_content, content_type="text/yaml")
    print(f"    ✅ Config pushed: gs://{bucket_name}/{blob_path}")


def push_pipeline_yaml(client, bucket_name: str):
    """Push the pipeline.yaml to GCS."""
    pipeline_path = os.path.join(os.path.dirname(__file__), "config", "pipeline.yaml")
    if os.path.exists(pipeline_path):
        bucket = client.bucket(bucket_name)
        blob = bucket.blob("config/pipeline.yaml")
        blob.upload_from_string(open(pipeline_path).read(), content_type="text/yaml")
        print(f"  ✅ Pipeline config: gs://{bucket_name}/config/pipeline.yaml")


def main():
    parser = argparse.ArgumentParser(description="EastSide — Ontika Discovery & Onboarding")
    parser.add_argument("--project", default="bt-df-lkhouse")
    parser.add_argument("--bucket", default=BUCKET)
    parser.add_argument("--dataset", help="Single dataset to onboard (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Profile only, don't push configs")
    args = parser.parse_args()

    print("=" * 60)
    print("  EastSide — Ontika Discovery & Onboarding")
    print("=" * 60)
    print(f"  Project: {args.project}")
    print(f"  Bucket:  gs://{args.bucket}/")
    print(f"  LLM:     {os.environ.get('LLM_MODEL', 'not set')}")
    print()

    gcs_client = storage.Client(project=args.project)
    profiler = DiscoveryProfiler()

    # Discover datasets in landing
    if args.dataset:
        datasets = [args.dataset]
    else:
        datasets = discover_datasets(args.project, args.bucket)

    print(f"  Found {len(datasets)} datasets in landing zone:")
    for d in datasets:
        print(f"    - {d}")

    # Process each dataset
    results = {}
    for dataset_name in datasets:
        print(f"\n{'─' * 60}")
        print(f"  ONBOARDING: {dataset_name}")
        print(f"{'─' * 60}")

        try:
            # 1. Profile
            profile = profile_dataset(profiler, dataset_name, args.bucket)
            if not profile or not profile.fields:
                print(f"    ⚠️  No data found — skipping")
                results[dataset_name] = "SKIPPED"
                continue

            # 2. Persist profile
            profiler.persist_profile(profile, bucket_name=args.bucket)

            # 3. Generate config via LLM
            yaml_content = generate_config_via_llm(dataset_name, profile)
            if not yaml_content:
                print(f"    ❌ LLM failed to generate config")
                results[dataset_name] = "FAILED"
                continue

            # Validate YAML
            try:
                parsed = yaml.safe_load(yaml_content)
                if not parsed or "table" not in parsed:
                    print(f"    ❌ Invalid YAML generated")
                    results[dataset_name] = "FAILED"
                    continue
            except yaml.YAMLError as e:
                print(f"    ❌ YAML parse error: {e}")
                results[dataset_name] = "FAILED"
                continue

            print(f"    Generated config:")
            print(f"      PK: {parsed.get('primary_key')}")
            print(f"      Domain: {parsed.get('domain')}")
            print(f"      CDC: {parsed.get('is_cdc')}")
            print(f"      PII: {parsed.get('pii_fields', [])}")

            # 4. Push to GCS (unless dry-run)
            if not args.dry_run:
                push_config_to_gcs(gcs_client, args.bucket, dataset_name, yaml_content)
                results[dataset_name] = "SUCCESS"
            else:
                print(f"    [DRY RUN] Would push config to GCS")
                print(f"    --- Generated YAML ---")
                print(yaml_content)
                results[dataset_name] = "DRY_RUN"

        except Exception as e:
            print(f"    ❌ Error: {e}")
            results[dataset_name] = "FAILED"

    # Push pipeline.yaml
    if not args.dry_run:
        print(f"\n{'─' * 60}")
        push_pipeline_yaml(gcs_client, args.bucket)

    # Summary
    print(f"\n{'=' * 60}")
    print("  ONBOARDING SUMMARY")
    print(f"{'=' * 60}")
    for dataset, status in results.items():
        icon = "✅" if status == "SUCCESS" else "❌" if status == "FAILED" else "⏭️"
        print(f"  {icon} {dataset}: {status}")

    success = sum(1 for v in results.values() if v in ("SUCCESS", "DRY_RUN"))
    print(f"\n  Total: {len(results)} | Success: {success} | Failed: {sum(1 for v in results.values() if v == 'FAILED')}")
    print(f"\n  Configs at: gs://{args.bucket}/{CONFIG_PREFIX}/")
    print(f"  Next: Submit bronze job to Dataproc")
    print("=" * 60)


if __name__ == "__main__":
    main()
