"""KC Inspector — dumps everything in Dataplex Knowledge Catalog to a file.

Usage (from Cloud Shell, repo root):
    python scripts/inspect_kc.py
    python scripts/inspect_kc.py --out kc_snapshot.json   # custom output path

Output: kc_snapshot.json (or --out path)
"""
import json
import os
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
LOCATION   = os.environ.get("GCP_REGION",     "europe-west2")
GLOSSARY_ID    = "enterprise-data-glossary"
ENTRY_GROUP_ID = "enterprise-hierarchy"


def _glossary_parent():
    return f"projects/{PROJECT_ID}/locations/{LOCATION}/glossaries/{GLOSSARY_ID}"

def _entry_group_parent():
    return f"projects/{PROJECT_ID}/locations/{LOCATION}/entryGroups/{ENTRY_GROUP_ID}"


# ── Glossary ──────────────────────────────────────────────────────────────────

def read_glossary_meta(client):
    try:
        from google.cloud import dataplex_v1
        g = client.get_glossary(name=_glossary_parent())
        return {
            "name":         g.name,
            "display_name": g.display_name,
            "description":  g.description,
            "state":        g.state.name if hasattr(g.state, "name") else str(g.state),
        }
    except Exception as e:
        return {"error": str(e)}


def read_categories(client):
    try:
        from google.cloud import dataplex_v1
        req = dataplex_v1.ListGlossaryCategoriesRequest(parent=_glossary_parent())
        return [
            {
                "id":           c.name.split("/")[-1],
                "display_name": c.display_name,
                "description":  c.description or "",
                "parent_category": c.parent_category or "",
            }
            for c in client.list_glossary_categories(request=req)
        ]
    except Exception as e:
        return [{"error": str(e)}]


def read_terms(client):
    try:
        from google.cloud import dataplex_v1
        req = dataplex_v1.ListGlossaryTermsRequest(parent=_glossary_parent())
        terms = []
        for t in client.list_glossary_terms(request=req):
            terms.append({
                "id":              t.name.split("/")[-1],
                "display_name":    t.display_name,
                "description":     t.description or "",
                "parent_category": t.parent_category or "",
                "data_steward":    t.data_steward or "",
                "create_time":     t.create_time.isoformat() if t.create_time else "",
                "update_time":     t.update_time.isoformat() if t.update_time else "",
            })
        return terms
    except Exception as e:
        return [{"error": str(e)}]


# ── Entry Group + Entries ─────────────────────────────────────────────────────

def read_entry_groups(catalog_client):
    try:
        from google.cloud import dataplex_v1
        parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"
        req = dataplex_v1.ListEntryGroupsRequest(parent=parent)
        return [
            {
                "id":           eg.name.split("/")[-1],
                "display_name": eg.display_name,
                "description":  eg.description or "",
            }
            for eg in catalog_client.list_entry_groups(request=req)
        ]
    except Exception as e:
        return [{"error": str(e)}]


def read_entries(catalog_client):
    try:
        from google.cloud import dataplex_v1
        req = dataplex_v1.ListEntriesRequest(parent=_entry_group_parent())
        entries = []
        for e in catalog_client.list_entries(request=req):
            entries.append({
                "id":           e.name.split("/")[-1],
                "display_name": e.entry_source.display_name if e.entry_source else "",
                "description":  e.entry_source.description[:300] if e.entry_source else "",
                "entry_type":   e.entry_type.split("/")[-1] if e.entry_type else "",
                "fqn":          e.fully_qualified_name or "",
            })
        return entries
    except Exception as e:
        return [{"error": str(e)}]


def read_entry_links(catalog_client):
    try:
        from google.cloud import dataplex_v1
        req = dataplex_v1.ListEntryLinksRequest(parent=_entry_group_parent())
        links = []
        for lnk in catalog_client.list_entry_links(request=req):
            refs = [
                {"name": r.name, "type": r.type_.name if hasattr(r.type_, "name") else str(r.type_)}
                for r in lnk.entry_references
            ]
            links.append({
                "id":             lnk.name.split("/")[-1],
                "entry_link_type": lnk.entry_link_type.split("/")[-1] if lnk.entry_link_type else "",
                "entry_references": refs,
            })
        return links
    except Exception as e:
        return [{"error": str(e)}]


# ── Entry Types ───────────────────────────────────────────────────────────────

def read_entry_types(catalog_client):
    try:
        from google.cloud import dataplex_v1
        parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"
        req = dataplex_v1.ListEntryTypesRequest(parent=parent)
        return [
            {
                "id":           et.name.split("/")[-1],
                "display_name": et.display_name,
                "description":  et.description or "",
            }
            for et in catalog_client.list_entry_types(request=req)
        ]
    except Exception as e:
        return [{"error": str(e)}]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Dump Dataplex KC contents to JSON")
    parser.add_argument("--out", default="kc_snapshot.json", help="Output file path")
    args = parser.parse_args()

    try:
        from google.cloud import dataplex_v1
    except ImportError as e:
        print(f"ERROR: cannot import google-cloud-dataplex: {e}")
        print(f"Python executable: {sys.executable}")
        print(f"sys.path: {sys.path}")
        print("Try: python3 -m pip install google-cloud-dataplex")
        sys.exit(1)

    print(f"Connecting to KC: project={PROJECT_ID}, location={LOCATION}")

    glossary_client = dataplex_v1.BusinessGlossaryServiceClient()
    catalog_client  = dataplex_v1.CatalogServiceClient()

    snapshot = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "project":     PROJECT_ID,
        "location":    LOCATION,
        "glossary": {
            "id":         GLOSSARY_ID,
            "meta":       read_glossary_meta(glossary_client),
            "categories": read_categories(glossary_client),
            "terms":      read_terms(glossary_client),
        },
        "catalog": {
            "entry_groups": read_entry_groups(catalog_client),
            "entry_types":  read_entry_types(catalog_client),
            "entries":      read_entries(catalog_client),
            "entry_links":  read_entry_links(catalog_client),
        },
    }

    # Summary counts
    cats  = [c for c in snapshot["glossary"]["categories"] if "error" not in c]
    terms = [t for t in snapshot["glossary"]["terms"]      if "error" not in t]
    egs   = [e for e in snapshot["catalog"]["entry_groups"] if "error" not in e]
    ets   = [e for e in snapshot["catalog"]["entry_types"]  if "error" not in e]
    ents  = [e for e in snapshot["catalog"]["entries"]      if "error" not in e]
    links = [l for l in snapshot["catalog"]["entry_links"]  if "error" not in l]

    snapshot["summary"] = {
        "glossary_categories": len(cats),
        "glossary_terms":      len(terms),
        "entry_groups":        len(egs),
        "entry_types":         len(ets),
        "entries":             len(ents),
        "entry_links":         len(links),
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(snapshot, indent=2, default=str))

    print(f"\n── Summary ──────────────────────────────")
    for k, v in snapshot["summary"].items():
        print(f"  {k:<25} {v}")
    print(f"\nSnapshot written to: {out_path.resolve()}")


if __name__ == "__main__":
    main()
