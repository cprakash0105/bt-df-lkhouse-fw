"""KC Reset — deletes all glossary terms and custom entries from enterprise-hierarchy.

Usage (from Cloud Shell, repo root):
    python scripts/reset_kc.py            # dry run — shows what would be deleted
    python scripts/reset_kc.py --execute  # actually deletes

Keeps:
- The glossary itself (enterprise-data-glossary)
- The entry group itself (enterprise-hierarchy)
- System entry groups (@bigquery, @storage, etc.)
- System-managed entries (entrygroup self-entry)
"""
import argparse
import sys
import time

PROJECT_ID  = "bt-df-lkhouse"
LOCATION    = "europe-west2"
GLOSSARY_ID     = "enterprise-data-glossary"
ENTRY_GROUP_ID  = "enterprise-hierarchy"

GLOSSARY_PARENT     = f"projects/{PROJECT_ID}/locations/{LOCATION}/glossaries/{GLOSSARY_ID}"
ENTRY_GROUP_PARENT  = f"projects/{PROJECT_ID}/locations/{LOCATION}/entryGroups/{ENTRY_GROUP_ID}"

# System-managed entry suffix — never delete
SKIP_ENTRY_SUFFIX = "_entry"


def delete_all_terms(client, dry_run: bool):
    from google.cloud import dataplex_v1
    req = dataplex_v1.ListGlossaryTermsRequest(parent=GLOSSARY_PARENT)
    terms = list(client.list_glossary_terms(request=req))
    print(f"\n── Glossary Terms ({len(terms)}) ──────────────────────────")
    for t in terms:
        term_id = t.name.split("/")[-1]
        print(f"  {'[DRY RUN] would delete' if dry_run else 'deleting'}: {term_id}  ({t.display_name})")
        if not dry_run:
            try:
                client.delete_glossary_term(name=t.name)
                time.sleep(0.1)  # avoid quota burst
            except Exception as e:
                if "NOT_FOUND" in str(e):
                    pass
                else:
                    print(f"    ERROR: {e}")
    return len(terms)


def delete_all_entries(client, dry_run: bool):
    from google.cloud import dataplex_v1
    req = dataplex_v1.ListEntriesRequest(parent=ENTRY_GROUP_PARENT)
    entries = list(client.list_entries(request=req))

    # Skip the system self-entry for the entry group
    deletable = [e for e in entries if not e.name.endswith(SKIP_ENTRY_SUFFIX)]
    skipped   = [e for e in entries if e.name.endswith(SKIP_ENTRY_SUFFIX)]

    print(f"\n── Entries ({len(entries)} total, {len(skipped)} system-skipped) ──────────────────────────")
    for e in skipped:
        print(f"  [SKIP system]: {e.name.split('/')[-1]}")

    for e in deletable:
        entry_id = e.name.split("/")[-1]
        display  = e.entry_source.display_name if e.entry_source else ""
        etype    = e.entry_type.split("/")[-1] if e.entry_type else ""
        print(f"  {'[DRY RUN] would delete' if dry_run else 'deleting'}: {entry_id}  [{etype}] {display}")
        if not dry_run:
            try:
                client.delete_entry(name=e.name)
                time.sleep(0.1)
            except Exception as e2:
                if "NOT_FOUND" in str(e2):
                    pass
                else:
                    print(f"    ERROR: {e2}")

    return len(deletable)


def main():
    parser = argparse.ArgumentParser(description="Reset Dataplex KC — delete all terms and entries")
    parser.add_argument("--execute", action="store_true", help="Actually delete (default is dry run)")
    args = parser.parse_args()
    dry_run = not args.execute

    try:
        from google.cloud import dataplex_v1
    except ImportError:
        print("ERROR: google-cloud-dataplex not installed")
        sys.exit(1)

    if dry_run:
        print("DRY RUN — pass --execute to actually delete")
    else:
        print("⚠️  LIVE RUN — deleting from KC in 3 seconds... Ctrl+C to abort")
        time.sleep(3)

    glossary_client = dataplex_v1.BusinessGlossaryServiceClient()
    catalog_client  = dataplex_v1.CatalogServiceClient()

    terms_count   = delete_all_terms(glossary_client, dry_run)
    entries_count = delete_all_entries(catalog_client, dry_run)

    print(f"\n── Summary ──────────────────────────────────────────────")
    action = "would delete" if dry_run else "deleted"
    print(f"  Terms   {action}: {terms_count}")
    print(f"  Entries {action}: {entries_count}")
    if dry_run:
        print("\nRun with --execute to apply.")
    else:
        print("\nKC reset complete. Glossary and entry group structure preserved.")


if __name__ == "__main__":
    main()
