"""Establish structural relationships in Dataplex Knowledge Catalog.
Creates EntryLinks between:
  - Domains → Business Applications (related)
  - Business Applications → BDEs/Glossary Terms (definition)

This enables click-through navigation in the KC UI.

Run: python discovery/scripts/link_catalog.py
"""
import json
import urllib.request
import subprocess


PROJECT_ID = "bt-df-lkhouse"
PROJECT_NUMBER = "978009776592"
LOCATION = "europe-west2"
ENTRY_GROUP = f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/entryGroups/enterprise-hierarchy"
GLOSSARY_ENTRY_PREFIX = f"projects/{PROJECT_ID}/locations/{LOCATION}/entryGroups/@dataplex/entries/projects/{PROJECT_NUMBER}/locations/{LOCATION}/glossaries/enterprise-data-glossary/terms"

# Hierarchy: Domain → Business Applications
DOMAIN_TO_BA = {
    "credit": ["loan_origination_system", "credit_bureau_integration"],
    "customer_management": ["crm", "kyc_system"],
    "payments": ["payments_hub"],
    "digital_banking": ["mobile_banking_app"],
    "trade_finance": ["trade_finance_system"],
}

# Business Application → BDEs (glossary term IDs)
BA_TO_BDES = {
    "credit_bureau_integration": [
        "credit_score", "bureau_reference", "pan_number", "customer_identifier",
    ],
    "loan_origination_system": [
        "credit_score", "loan_amount", "customer_identifier", "pan_number",
    ],
    "crm": [
        "customer_identifier", "customer_name", "customer_email",
        "customer_phone", "date_of_birth", "address",
    ],
    "kyc_system": [
        "customer_identifier", "pan_number", "aadhaar_number",
        "kyc_status", "customer_name", "address",
    ],
    "payments_hub": [
        "transaction_amount", "transaction_date", "payment_method",
        "currency_code", "account_identifier", "customer_identifier",
    ],
    "mobile_banking_app": [
        "session_identifier", "event_timestamp", "customer_identifier",
    ],
    "trade_finance_system": [
        "transaction_amount", "currency_code", "account_identifier",
    ],
}


def get_token():
    """Get access token from gcloud."""
    result = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True, text=True
    )
    return result.stdout.strip()


def create_entry_link(token, link_id, link_type, source_entry, target_entry, use_unspecified=False):
    """Create an EntryLink between two entries or entry and term."""
    url = f"https://dataplex.googleapis.com/v1/{ENTRY_GROUP}/entryLinks?entry_link_id={link_id}"

    if use_unspecified:
        refs = [
            {"name": source_entry, "type": "UNSPECIFIED"},
            {"name": target_entry, "type": "UNSPECIFIED"},
        ]
    else:
        refs = [
            {"name": source_entry, "type": "SOURCE"},
            {"name": target_entry, "type": "TARGET"},
        ]

    payload = {
        "entry_link_type": link_type,
        "entry_references": refs,
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req) as resp:
            print(f"  [OK] {link_id}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if "ALREADY_EXISTS" in body:
            print(f"  [EXISTS] {link_id}")
            return True
        print(f"  [FAIL] {link_id}: {e.code} - {body[:200]}")
        return False


def main():
    print("=" * 60)
    print("  Link Catalog: Establish Structural Relationships")
    print("=" * 60)
    print(f"  Project: {PROJECT_ID}")
    print(f"  Entry Group: {ENTRY_GROUP}")
    print(f"  Glossary Term Prefix: {GLOSSARY_ENTRY_PREFIX}")
    print()

    token = get_token()
    if not token:
        print("ERROR: Could not get access token. Run 'gcloud auth login' first.")
        return

    # Link type for hierarchical/related relationships
    related_link_type = "projects/dataplex-types/locations/global/entryLinkTypes/related"
    # Link type for definition (BA uses this BDE)
    definition_link_type = "projects/dataplex-types/locations/global/entryLinkTypes/definition"

    # Step 1: Link Domains to Business Applications
    print("[1/2] Linking Domains -> Business Applications...")
    link_count = 0
    for domain_id, ba_ids in DOMAIN_TO_BA.items():
        domain_entry = f"projects/{PROJECT_ID}/locations/{LOCATION}/entryGroups/enterprise-hierarchy/entries/{domain_id}"
        for ba_id in ba_ids:
            ba_entry = f"projects/{PROJECT_ID}/locations/{LOCATION}/entryGroups/enterprise-hierarchy/entries/{ba_id}"
            link_id = f"domain-{domain_id}-to-ba-{ba_id}".replace("_", "-")
            success = create_entry_link(token, link_id, related_link_type, domain_entry, ba_entry, use_unspecified=True)
            if success:
                link_count += 1

    print(f"\n  Created {link_count} Domain -> BA links")

    # Step 2: Link Business Applications to BDEs (Glossary Terms)
    print("\n[2/2] Linking Business Applications -> BDEs (Glossary Terms)...")
    link_count = 0
    for ba_id, bde_ids in BA_TO_BDES.items():
        ba_entry = f"projects/{PROJECT_ID}/locations/{LOCATION}/entryGroups/enterprise-hierarchy/entries/{ba_id}"
        for bde_id in bde_ids:
            term_entry = f"{GLOSSARY_ENTRY_PREFIX}/{bde_id}"
            link_id = f"ba-{ba_id}-to-bde-{bde_id}".replace("_", "-")
            success = create_entry_link(token, link_id, definition_link_type, ba_entry, term_entry)
            if success:
                link_count += 1

    print(f"\n  Created {link_count} BA -> BDE links")

    print(f"\n{'=' * 60}")
    print("  Catalog Linking Complete!")
    print("=" * 60)
    print(f"\n  View in console:")
    print(f"  https://console.cloud.google.com/dataplex/catalog?project={PROJECT_ID}")
    print(f"\n  Click on any BA to see its linked BDEs.")
    print(f"  Click on any Domain to see its linked BAs.")
    print(f"  Click on any BDE to see which BAs use it.")


if __name__ == "__main__":
    main()
