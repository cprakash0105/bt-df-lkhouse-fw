"""Import seed glossary + banking catalog into Google Dataplex Catalog.
Run in Cloud Shell: python discovery/scripts/import_to_dataplex.py

This creates:
  - A Glossary in Dataplex
  - Categories (from our data domains)
  - Terms (from our business terms) with synonyms, descriptions, classifications
"""
import yaml
import argparse
from pathlib import Path

try:
    from google.cloud import dataplex_v1
    from google.cloud.dataplex_v1 import BusinessGlossaryServiceClient
except ImportError:
    print("ERROR: google-cloud-dataplex not installed.")
    print("Run: pip install google-cloud-dataplex")
    exit(1)


PROJECT_ID = "bt-df-lkhouse"
LOCATION = "europe-west2"
GLOSSARY_ID = "enterprise-data-glossary"


def load_config():
    """Load all local config files."""
    config_dir = Path(__file__).parent.parent / "config"

    # Seed glossary
    with open(config_dir / "seed_glossary.yaml", "r", encoding="utf-8") as f:
        seed = yaml.safe_load(f)

    # Banking catalog
    banking = {}
    for fname in ["business_applications.yaml", "business_glossary.yaml",
                  "business_data_elements.yaml", "governance_rules.yaml"]:
        fpath = config_dir / fname
        if fpath.exists():
            with open(fpath, "r", encoding="utf-8") as f:
                banking[fname] = yaml.safe_load(f)

    return seed, banking


def create_glossary(client, project_id, location):
    """Create the enterprise glossary."""
    parent = f"projects/{project_id}/locations/{location}"

    glossary = dataplex_v1.Glossary(
        description="Enterprise Data Glossary - Business terms, classifications, and data elements"
    )

    request = dataplex_v1.CreateGlossaryRequest(
        parent=parent,
        glossary=glossary,
        glossary_id=GLOSSARY_ID,
    )

    try:
        operation = client.create_glossary(request=request)
        result = operation.result()
        print(f"[OK] Created glossary: {result.name}")
        return result.name
    except Exception as e:
        if "already exists" in str(e).lower() or "ALREADY_EXISTS" in str(e):
            glossary_name = f"{parent}/glossaries/{GLOSSARY_ID}"
            print(f"[OK] Glossary already exists: {glossary_name}")
            return glossary_name
        raise


def create_category(client, glossary_name, category_id, name, description):
    """Create a category (domain) in the glossary."""
    category = dataplex_v1.GlossaryCategory(
        description=description,
        display_name=name,
    )

    request = dataplex_v1.CreateGlossaryCategoryRequest(
        parent=glossary_name,
        category=category,
        category_id=category_id,
    )

    try:
        operation = client.create_glossary_category(request=request)
        result = operation.result()
        print(f"  [OK] Category: {name}")
        return result.name
    except Exception as e:
        if "already exists" in str(e).lower() or "ALREADY_EXISTS" in str(e):
            print(f"  [OK] Category exists: {name}")
            return f"{glossary_name}/categories/{category_id}"
        print(f"  [WARN] Category '{name}': {e}")
        return None


def create_term(client, glossary_name, term_id, term_data, category_name=None):
    """Create a business term in the glossary."""
    description_parts = []
    if term_data.get("information_type"):
        description_parts.append(f"Information Type: {term_data['information_type']}")
    if term_data.get("is_pii"):
        description_parts.append("Classification: PII")
    if term_data.get("classification"):
        description_parts.append(f"Classification: {term_data['classification']}")
    if term_data.get("synonyms"):
        description_parts.append(f"Synonyms: {', '.join(term_data['synonyms'])}")
    if term_data.get("data_type"):
        description_parts.append(f"Data Type: {term_data['data_type']}")
    if term_data.get("dq_rules"):
        description_parts.append(f"DQ Rules: {term_data['dq_rules']}")
    if term_data.get("reference_code_set"):
        description_parts.append(f"Reference Set: {term_data['reference_code_set']}")
    if term_data.get("pattern"):
        description_parts.append(f"Pattern: {term_data['pattern']}")

    description = " | ".join(description_parts) if description_parts else term_data.get("name", "")

    term = dataplex_v1.GlossaryTerm(
        description=description,
        display_name=term_data.get("name", term_id),
    )

    # Link to parent category if provided
    if category_name:
        term.parent = category_name

    request = dataplex_v1.CreateGlossaryTermRequest(
        parent=glossary_name,
        term=term,
        term_id=term_id,
    )

    try:
        operation = client.create_glossary_term(request=request)
        result = operation.result()
        print(f"    [OK] Term: {term_data.get('name', term_id)}")
        return result.name
    except Exception as e:
        if "already exists" in str(e).lower() or "ALREADY_EXISTS" in str(e):
            print(f"    [OK] Term exists: {term_data.get('name', term_id)}")
            return f"{glossary_name}/terms/{term_id}"
        print(f"    [WARN] Term '{term_data.get('name', term_id)}': {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Import glossary to Dataplex Catalog")
    parser.add_argument("--project", default=PROJECT_ID)
    parser.add_argument("--location", default=LOCATION)
    parser.add_argument("--dry-run", action="store_true", help="Print what would be created")
    args = parser.parse_args()

    print("=" * 60)
    print("  Import to Dataplex Catalog")
    print("=" * 60)
    print(f"  Project:  {args.project}")
    print(f"  Location: {args.location}")
    print()

    # Load local config
    seed, banking = load_config()

    domains = seed.get("data_domains", [])
    terms = seed.get("business_terms", [])
    applications = seed.get("business_applications", [])

    # Add banking glossary terms
    for term in banking.get("business_glossary.yaml", {}).get("business_glossary", []):
        terms.append({
            "id": term["id"].lower(),
            "name": term["name"],
            "domain": term.get("domain", "general").lower(),
            "synonyms": [term["name"].lower(), term["name"].lower().replace(" ", "_")],
            "information_type": "Dimension",
            "data_type": "string",
        })

    print(f"  Domains: {len(domains)}")
    print(f"  Terms: {len(terms)}")
    print(f"  Applications: {len(applications)}")
    print()

    if args.dry_run:
        print("[DRY RUN] Would create:")
        print(f"  1 Glossary: {GLOSSARY_ID}")
        for d in domains:
            print(f"  Category: {d['name']}")
        for t in terms:
            print(f"  Term: {t['name']} (domain: {t.get('domain', '?')})")
        print("\nRe-run without --dry-run to create in Dataplex.")
        return

    # Initialize client
    client = BusinessGlossaryServiceClient()

    # Create glossary
    print("\n[1/3] Creating glossary...")
    glossary_name = create_glossary(client, args.project, args.location)

    # Create categories (domains)
    print("\n[2/3] Creating categories (domains)...")
    category_map = {}
    for domain in domains:
        cat_name = create_category(
            client, glossary_name,
            domain["id"], domain["name"], domain.get("description", "")
        )
        if cat_name:
            category_map[domain["id"]] = cat_name

    # Also add business applications as categories
    for app in applications:
        cat_name = create_category(
            client, glossary_name,
            f"app_{app['id']}", f"[App] {app['name']}", app.get("description", "")
        )

    # Create terms
    print("\n[3/3] Creating business terms...")
    for term in terms:
        domain_id = term.get("domain", "")
        category_name = category_map.get(domain_id)
        create_term(client, glossary_name, term["id"], term, category_name)

    print("\n" + "=" * 60)
    print("  Import Complete!")
    print("=" * 60)
    print(f"\n  View in console:")
    print(f"  https://console.cloud.google.com/dataplex/glossaries?project={args.project}")
    print()


if __name__ == "__main__":
    main()
