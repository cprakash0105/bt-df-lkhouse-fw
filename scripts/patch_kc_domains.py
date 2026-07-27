"""Patch KC terms that have Domain: unknown — update to correct domain.

Usage:
    python scripts/patch_kc_domains.py            # dry run
    python scripts/patch_kc_domains.py --execute  # apply patches
"""
import argparse
import time
import sys

PROJECT_ID = "bt-df-lkhouse"
LOCATION = "europe-west2"
GLOSSARY_ID = "enterprise-data-glossary"
GLOSSARY_PARENT = f"projects/{PROJECT_ID}/locations/{LOCATION}/glossaries/{GLOSSARY_ID}"

# Map term-id -> correct domain (for terms written with Domain: unknown)
DOMAIN_PATCHES = {
    "transaction-id":       "retail",
    "basket-id":            "retail",
    "store-id":             "retail",
    "till-id":              "retail",
    "customer-id":          "retail",
    "product-sku":          "retail",
    "quantity":             "retail",
    "unit-price":           "retail",
    "discount-amount":      "retail",
    "payment-method":       "retail",
    "transaction-datetime": "retail",
    "staff-id":             "hr",
}


def main():
    parser = argparse.ArgumentParser(description="Patch Domain: unknown terms in KC")
    parser.add_argument("--execute", action="store_true", help="Actually patch (default is dry run)")
    args = parser.parse_args()
    dry_run = not args.execute

    try:
        from google.cloud import dataplex_v1
    except ImportError:
        print("ERROR: google-cloud-dataplex not installed")
        sys.exit(1)

    if dry_run:
        print("DRY RUN — pass --execute to apply patches\n")
    else:
        print("⚠️  LIVE RUN — patching in 3 seconds... Ctrl+C to abort\n")
        time.sleep(3)

    client = dataplex_v1.BusinessGlossaryServiceClient()

    # List all terms
    req = dataplex_v1.ListGlossaryTermsRequest(parent=GLOSSARY_PARENT)
    terms = list(client.list_glossary_terms(request=req))

    patched = 0
    for term in terms:
        term_id = term.name.split("/")[-1]
        if term_id not in DOMAIN_PATCHES:
            continue
        if "Domain: unknown" not in term.description:
            print(f"  [SKIP] {term_id} — domain already correct")
            continue

        new_domain = DOMAIN_PATCHES[term_id]
        new_description = term.description.replace("Domain: unknown", f"Domain: {new_domain}")

        print(f"  {'[DRY RUN]' if dry_run else 'patching'}: {term_id} → Domain: {new_domain}")

        if not dry_run:
            try:
                updated = dataplex_v1.GlossaryTerm(
                    name=term.name,
                    description=new_description,
                    display_name=term.display_name,
                )
                update_req = dataplex_v1.UpdateGlossaryTermRequest(
                    glossary_term=updated,
                    update_mask={"paths": ["description"]},
                )
                client.update_glossary_term(request=update_req)
                patched += 1
                time.sleep(0.2)
            except Exception as e:
                print(f"    ERROR: {e}")

    if dry_run:
        print(f"\n{len(DOMAIN_PATCHES)} terms would be patched. Run with --execute to apply.")
    else:
        print(f"\nPatched {patched} terms.")


if __name__ == "__main__":
    main()
