"""Tag physical columns (TDEs) with Business Data Elements (BDEs).
Creates a Data Catalog tag template and tags each column with its glossary term.

Run: python discovery/scripts/tag_columns.py --table cibil_bureau_feed
"""
import argparse
import yaml
from pathlib import Path
from google.cloud import datacatalog_v1, bigquery


PROJECT_ID = "bt-df-lkhouse"
LOCATION = "europe-west2"
DATASET = "lakehouse_dataproduct"
TAG_TEMPLATE_ID = "bde_mapping"


def ensure_tag_template(client):
    """Create tag template if not exists."""
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"
    template_name = f"{parent}/tagTemplates/{TAG_TEMPLATE_ID}"

    try:
        client.get_tag_template(name=template_name)
        print(f"[OK] Tag template exists: {TAG_TEMPLATE_ID}")
        return template_name
    except Exception:
        pass

    template = datacatalog_v1.TagTemplate(
        display_name="Business Data Element Mapping",
        fields={
            "business_term": datacatalog_v1.TagTemplateField(
                display_name="Business Term",
                type_=datacatalog_v1.FieldType(
                    primitive_type=datacatalog_v1.FieldType.PrimitiveType.STRING
                ),
                is_required=True,
            ),
            "classification": datacatalog_v1.TagTemplateField(
                display_name="Classification",
                type_=datacatalog_v1.FieldType(
                    primitive_type=datacatalog_v1.FieldType.PrimitiveType.STRING
                ),
            ),
            "is_pii": datacatalog_v1.TagTemplateField(
                display_name="Is PII",
                type_=datacatalog_v1.FieldType(
                    primitive_type=datacatalog_v1.FieldType.PrimitiveType.BOOL
                ),
            ),
            "dq_rules": datacatalog_v1.TagTemplateField(
                display_name="DQ Rules",
                type_=datacatalog_v1.FieldType(
                    primitive_type=datacatalog_v1.FieldType.PrimitiveType.STRING
                ),
            ),
        },
    )

    try:
        result = client.create_tag_template(
            parent=parent, tag_template=template, tag_template_id=TAG_TEMPLATE_ID
        )
        print(f"[OK] Created tag template: {result.name}")
        return result.name
    except Exception as e:
        print(f"[FAIL] Tag template: {e}")
        return None


def get_table_entry(client, table_name):
    """Look up the Data Catalog entry for a BigQuery table."""
    resource = f"//bigquery.googleapis.com/projects/{PROJECT_ID}/datasets/{DATASET}/tables/{table_name}"
    try:
        entry = client.lookup_entry(
            request={"linked_resource": resource}
        )
        print(f"[OK] Found entry: {entry.name}")
        return entry
    except Exception as e:
        print(f"[FAIL] Lookup entry for {table_name}: {e}")
        return None


def load_table_config(table_name):
    """Load the table config YAML to get field-to-BDE mappings."""
    # Try local config
    config_path = Path(f"bt_df_lkhouse_fw/config/tables/{table_name}.yaml")
    if config_path.exists():
        with open(config_path, "r") as f:
            return yaml.safe_load(f)

    # Try GCS
    try:
        from google.cloud import storage
        gcs = storage.Client(project=PROJECT_ID)
        bucket = gcs.bucket(f"{PROJECT_ID}-lakehouse")
        blob = bucket.blob(f"framework/config/tables/{table_name}.yaml")
        return yaml.safe_load(blob.download_as_text())
    except Exception:
        return None


# Known field-to-BDE mappings (from SD discovery results)
BDE_MAPPINGS = {
    "customer_id": {"term": "Customer Identifier", "classification": "Internal", "is_pii": False},
    "pan_number": {"term": "PAN Number", "classification": "PII", "is_pii": True},
    "cibil_score": {"term": "Credit Score", "classification": "Sensitive", "is_pii": False},
    "bureau_reference_id": {"term": "Bureau Reference", "classification": "Internal", "is_pii": False},
    "mobile_number": {"term": "Customer Phone", "classification": "PII", "is_pii": True},
    "email_address": {"term": "Customer Email", "classification": "PII", "is_pii": True},
    "date_of_birth": {"term": "Date of Birth", "classification": "PII", "is_pii": True},
    "loan_amount_requested": {"term": "Loan Amount", "classification": "Sensitive", "is_pii": False},
    "account_identifier": {"term": "Account Identifier", "classification": "Internal", "is_pii": False},
    "transaction_amount": {"term": "Transaction Amount", "classification": "Internal", "is_pii": False},
    "name": {"term": "Customer Name", "classification": "PII", "is_pii": True},
    "email": {"term": "Customer Email", "classification": "PII", "is_pii": True},
    "phone": {"term": "Customer Phone", "classification": "PII", "is_pii": True},
    "address": {"term": "Address", "classification": "PII", "is_pii": True},
}


def tag_columns(dc_client, entry, table_name, template_name):
    """Tag each column with its BDE."""
    # Get table config for DQ rules
    config = load_table_config(table_name)
    dq_rules = config.get("dq_rules", {}) if config else {}
    pii_fields = config.get("pii_fields", []) if config else []

    # Get columns from BigQuery
    bq = bigquery.Client(project=PROJECT_ID)
    table = bq.get_table(f"{PROJECT_ID}.{DATASET}.{table_name}")

    tagged = 0
    for field in table.schema:
        col_name = field.name
        mapping = BDE_MAPPINGS.get(col_name)

        if not mapping:
            # Check if it's in PII fields from config
            if col_name in pii_fields:
                mapping = {"term": col_name.replace("_", " ").title(), "classification": "PII", "is_pii": True}
            else:
                continue

        # Build DQ string for this column
        col_dq = []
        if col_name in dq_rules.get("not_null", []):
            col_dq.append("not_null")
        if col_name in dq_rules.get("positive", []):
            col_dq.append("positive")
        if col_name in dq_rules.get("unique", []):
            col_dq.append("unique")
        if col_name in (dq_rules.get("format", {}) or {}):
            col_dq.append(f"format:{dq_rules['format'][col_name]}")
        if col_name in (dq_rules.get("range", {}) or {}):
            col_dq.append(f"range:{dq_rules['range'][col_name]}")

        tag = datacatalog_v1.Tag(
            template=template_name,
            column=col_name,
            fields={
                "business_term": datacatalog_v1.TagField(string_value=mapping["term"]),
                "classification": datacatalog_v1.TagField(string_value=mapping["classification"]),
                "is_pii": datacatalog_v1.TagField(bool_value=mapping["is_pii"]),
                "dq_rules": datacatalog_v1.TagField(string_value=", ".join(col_dq) if col_dq else "none"),
            },
        )

        try:
            dc_client.create_tag(parent=entry.name, tag=tag)
            print(f"  [OK] {col_name} -> {mapping['term']} ({mapping['classification']})")
            tagged += 1
        except Exception as e:
            if "ALREADY_EXISTS" in str(e):
                print(f"  [EXISTS] {col_name} -> {mapping['term']}")
                tagged += 1
            else:
                print(f"  [FAIL] {col_name}: {e}")

    return tagged


def main():
    parser = argparse.ArgumentParser(description="Tag physical columns with BDE glossary terms")
    parser.add_argument("--table", required=True, help="Table name in lakehouse_dataproduct")
    args = parser.parse_args()

    print("=" * 60)
    print("  Tag TDEs with BDEs (Column-level catalog tagging)")
    print("=" * 60)
    print(f"  Table: {PROJECT_ID}.{DATASET}.{args.table}")
    print()

    dc_client = datacatalog_v1.DataCatalogClient()

    # Step 1: Ensure tag template
    print("[1/3] Ensuring tag template...")
    template_name = ensure_tag_template(dc_client)
    if not template_name:
        print("Failed to create tag template")
        return

    # Step 2: Look up table entry
    print("\n[2/3] Looking up table in Data Catalog...")
    entry = get_table_entry(dc_client, args.table)
    if not entry:
        print("Table not found in Data Catalog")
        return

    # Step 3: Tag columns
    print(f"\n[3/3] Tagging columns...")
    tagged = tag_columns(dc_client, entry, args.table, template_name)

    print(f"\n{'=' * 60}")
    print(f"  Done: {tagged} columns tagged")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
