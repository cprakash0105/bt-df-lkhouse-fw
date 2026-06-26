"""Create Enterprise Hierarchy in Dataplex Knowledge Catalog.
Hierarchy: CFU -> Domain -> Business Application -> references BDEs (glossary terms)

Uses Custom Entry Types and Entries to model the organisational structure.
This is SEPARATE from the Glossary (which is just a dictionary of BDE definitions).

Run: python discovery/scripts/setup_hierarchy.py
"""
from google.cloud import dataplex_v1
from google.cloud.dataplex_v1 import CatalogServiceClient

PROJECT_ID = "bt-df-lkhouse"
LOCATION = "europe-west2"
ENTRY_GROUP_ID = "enterprise-hierarchy"

client = CatalogServiceClient()
parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"
entry_group_name = f"{parent}/entryGroups/{ENTRY_GROUP_ID}"

# Enterprise Hierarchy Definition
HIERARCHY = {
    "cfus": [
        {
            "id": "consumer_banking",
            "name": "Consumer Banking",
            "description": "Retail banking services for individual customers",
            "domains": [
                {
                    "id": "credit",
                    "name": "Credit",
                    "description": "Credit products, scoring, and risk management",
                    "applications": [
                        {
                            "id": "loan_origination_system",
                            "name": "Loan Origination System",
                            "description": "Processes loan applications from intake to disbursement",
                            "owner": "Credit Risk Team",
                            "bdes": ["credit_score", "loan_amount", "customer_identifier", "pan_number"],
                        },
                        {
                            "id": "credit_bureau_integration",
                            "name": "Credit Bureau Integration",
                            "description": "Integration with TransUnion CIBIL and other bureaus",
                            "owner": "Bureau Data Team",
                            "bdes": ["credit_score", "bureau_reference", "pan_number", "customer_identifier"],
                        },
                    ],
                },
                {
                    "id": "customer_management",
                    "name": "Customer Management",
                    "description": "Customer lifecycle, identity, and relationship management",
                    "applications": [
                        {
                            "id": "crm",
                            "name": "Customer Relationship Management",
                            "description": "Manages customer profiles, interactions, and segmentation",
                            "owner": "Customer Data Team",
                            "bdes": ["customer_identifier", "customer_name", "customer_email", "customer_phone", "date_of_birth", "address"],
                        },
                        {
                            "id": "kyc_system",
                            "name": "KYC & Onboarding System",
                            "description": "Customer identity verification and e-KYC processing",
                            "owner": "KYC Operations",
                            "bdes": ["customer_identifier", "pan_number", "aadhaar_number", "kyc_status", "customer_name", "address"],
                        },
                    ],
                },
                {
                    "id": "payments",
                    "name": "Payments",
                    "description": "Payment processing, settlements, and transfers",
                    "applications": [
                        {
                            "id": "payments_hub",
                            "name": "Payments Hub",
                            "description": "Handles NEFT, RTGS, IMPS, UPI payment flows",
                            "owner": "Payments Engineering",
                            "bdes": ["transaction_amount", "transaction_date", "payment_method", "currency_code", "account_identifier", "customer_identifier"],
                        },
                    ],
                },
                {
                    "id": "digital_banking",
                    "name": "Digital Banking",
                    "description": "Mobile app, internet banking, and digital channels",
                    "applications": [
                        {
                            "id": "mobile_banking_app",
                            "name": "Mobile Banking Application",
                            "description": "Customer-facing mobile app for banking services",
                            "owner": "Digital Products Team",
                            "bdes": ["session_identifier", "event_timestamp", "customer_identifier"],
                        },
                    ],
                },
            ],
        },
        {
            "id": "wholesale_banking",
            "name": "Wholesale Banking",
            "description": "Corporate and institutional banking services",
            "domains": [
                {
                    "id": "trade_finance",
                    "name": "Trade Finance",
                    "description": "Letters of credit, guarantees, and trade settlements",
                    "applications": [
                        {
                            "id": "trade_finance_system",
                            "name": "Trade Finance System",
                            "description": "Manages trade finance instruments and settlements",
                            "owner": "Trade Operations",
                            "bdes": ["transaction_amount", "currency_code", "account_identifier"],
                        },
                    ],
                },
            ],
        },
    ],
}


def create_entry_group():
    """Create the entry group for enterprise hierarchy."""
    entry_group = dataplex_v1.EntryGroup(
        description="Enterprise organisational hierarchy: CFU -> Domain -> Business Application"
    )
    req = dataplex_v1.CreateEntryGroupRequest(
        parent=parent,
        entry_group=entry_group,
        entry_group_id=ENTRY_GROUP_ID,
    )
    try:
        client.create_entry_group(request=req)
        print(f"  [OK] Entry Group created: {ENTRY_GROUP_ID}")
    except Exception as e:
        if "ALREADY_EXISTS" in str(e):
            print(f"  [OK] Entry Group already exists")
        else:
            raise


def create_entry(entry_id: str, display_name: str, description: str,
                 entry_type: str, attributes: dict = None):
    """Create an entry in the hierarchy."""
    # Build fully qualified entry type
    fq_entry_type = f"projects/{PROJECT_ID}/locations/{LOCATION}/entryTypes/{entry_type}"

    entry = dataplex_v1.Entry(
        entry_type=fq_entry_type,
        aspects={},
    )

    # Store metadata in a general aspect
    aspect_key = f"{PROJECT_ID}.{LOCATION}.enterprise-metadata"

    req = dataplex_v1.CreateEntryRequest(
        parent=entry_group_name,
        entry=entry,
        entry_id=entry_id,
    )

    try:
        client.create_entry(request=req)
        print(f"  [OK] {display_name}")
        return True
    except Exception as e:
        if "ALREADY_EXISTS" in str(e):
            print(f"  [EXISTS] {display_name}")
            return True
        else:
            print(f"  [FAIL] {display_name}: {e}")
            return False


def main():
    print("=" * 60)
    print("  Setup Enterprise Hierarchy")
    print("=" * 60)
    print(f"  Project: {PROJECT_ID}")
    print(f"  Structure: CFU -> Domain -> Business Application")
    print()

    # Step 1: Create Entry Group
    print("[1/2] Creating entry group...")
    create_entry_group()

    # Step 2: Print hierarchy (for now, entry types need to be created via console/terraform)
    print("\n[2/2] Enterprise Hierarchy:\n")

    for cfu in HIERARCHY["cfus"]:
        print(f"  CFU: {cfu['name']}")
        print(f"       {cfu['description']}")
        for domain in cfu["domains"]:
            print(f"    Domain: {domain['name']}")
            print(f"            {domain['description']}")
            for app in domain["applications"]:
                print(f"      BA: {app['name']}")
                print(f"          Owner: {app['owner']}")
                print(f"          BDEs: {', '.join(app['bdes'])}")
        print()

    print("=" * 60)
    print("  Hierarchy Definition Complete")
    print("=" * 60)
    print(f"""
  Note: Custom Entry Types need to be created in Dataplex before
  entries can be registered. Create these Entry Types:
  
  1. Go to: https://console.cloud.google.com/dataplex/catalog?project={PROJECT_ID}
  2. Create Entry Types:
     - 'cfu' (Customer Facing Unit)
     - 'domain' (Business Domain)  
     - 'business-application' (Business Application)
  3. Then re-run this script to register the entries.

  Alternatively, the hierarchy is stored in this script and can be
  queried by Semantic Discovery directly from the HIERARCHY dict.
""")

    # Export hierarchy as YAML for SD to use
    import yaml
    output_path = "discovery/config/enterprise_hierarchy.yaml"
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(HIERARCHY, f, default_flow_style=False, allow_unicode=True)
    print(f"  Hierarchy exported to: {output_path}")


if __name__ == "__main__":
    main()
