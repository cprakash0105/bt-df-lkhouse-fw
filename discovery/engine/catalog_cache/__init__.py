"""Catalog Cache — Firestore-backed cache of the Knowledge Catalog.

Responsibilities:
1. Sync from Dataplex KC (entries, links, glossary terms) on startup / periodically
2. Serve the full hierarchy tree to the UI instantly
3. Update immediately on SD approval (no wait for full sync)
4. Support structured queries (PII across domain, datasets using a BDE, etc.)

Firestore structure:
  catalog/cfus/{id}          → {name, domains}
  catalog/domains/{id}       → {name, description, term_count, applications}
  catalog/applications/{id}  → {name, description, keywords, bdes, datasets}
  catalog/terms/{id}         → {name, domain, type, is_pii, dq_rules, synonyms, ref_set}
  catalog/datasets/{id}      → {name, domain, ba, fields, profile_path, onboarded_at}
  catalog/links/{id}         → {source, target, link_type}
  sync_metadata/status       → {last_sync, entries_count, terms_count}
"""
import os
import json
import time
from typing import Optional
from datetime import datetime, timezone

try:
    from google.cloud import firestore
    FIRESTORE_AVAILABLE = True
except ImportError:
    FIRESTORE_AVAILABLE = False


PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
COLLECTION_PREFIX = "catalog"


class CatalogCache:
    """Firestore-backed catalog cache."""

    def __init__(self):
        self._db = None
        self._initialized = False

    @property
    def db(self):
        if self._db is None:
            if not FIRESTORE_AVAILABLE:
                raise RuntimeError("google-cloud-firestore not installed")
            self._db = firestore.Client(project=PROJECT_ID)
        return self._db

    def is_available(self) -> bool:
        try:
            _ = self.db
            return True
        except Exception:
            return False

    # --- Write Operations (called during sync or on approval) ---

    def upsert_cfu(self, cfu_id: str, data: dict):
        self.db.collection(f"{COLLECTION_PREFIX}/hierarchy/cfus").document(cfu_id).set(data, merge=True)

    def upsert_domain(self, domain_id: str, data: dict):
        self.db.collection(f"{COLLECTION_PREFIX}/hierarchy/domains").document(domain_id).set(data, merge=True)

    def upsert_application(self, app_id: str, data: dict):
        self.db.collection(f"{COLLECTION_PREFIX}/hierarchy/applications").document(app_id).set(data, merge=True)

    def upsert_term(self, term_id: str, data: dict):
        self.db.collection(f"{COLLECTION_PREFIX}/glossary/terms").document(term_id).set(data, merge=True)

    def upsert_dataset(self, dataset_id: str, data: dict):
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.db.collection(f"{COLLECTION_PREFIX}/datasets/entries").document(dataset_id).set(data, merge=True)

    def upsert_link(self, link_id: str, data: dict):
        self.db.collection(f"{COLLECTION_PREFIX}/links/entries").document(link_id).set(data, merge=True)

    # --- Read Operations (called by UI/API) ---

    def get_full_tree(self) -> dict:
        """Get the entire catalog hierarchy as a tree structure for the UI."""
        tree = {
            "cfus": self._get_all("hierarchy/cfus"),
            "domains": self._get_all("hierarchy/domains"),
            "applications": self._get_all("hierarchy/applications"),
            "terms": self._get_all("glossary/terms"),
            "datasets": self._get_all("datasets/entries"),
            "links": self._get_all("links/entries"),
        }
        return tree

    def get_hierarchy(self) -> list:
        """Get structured hierarchy: CFU → Domain → BA → BDEs."""
        cfus = self._get_all("hierarchy/cfus")
        domains = self._get_all("hierarchy/domains")
        apps = self._get_all("hierarchy/applications")
        terms = self._get_all("glossary/terms")
        datasets = self._get_all("datasets/entries")
        links = self._get_all("links/entries")

        # Build parent-child relationships from links
        domain_to_apps = {}
        app_to_terms = {}
        app_to_datasets = {}

        for link in links.values():
            src = link.get("source_id", "")
            tgt = link.get("target_id", "")
            lt = link.get("link_type", "")

            if "domain" in src and ("ba" in tgt or "application" in tgt or tgt in apps):
                domain_to_apps.setdefault(src, []).append(tgt)
            elif lt == "definition":
                app_to_terms.setdefault(src, []).append(tgt)

        # Also map datasets to apps
        for ds_id, ds in datasets.items():
            ba = ds.get("business_application")
            if ba:
                app_to_datasets.setdefault(ba, []).append(ds_id)

        # Build tree
        hierarchy = []
        for cfu_id, cfu in cfus.items():
            cfu_node = {
                "id": cfu_id,
                "name": cfu.get("name", cfu_id),
                "type": "cfu",
                "children": [],
            }
            for domain_id in cfu.get("domains", []):
                domain = domains.get(domain_id, {"name": domain_id})
                domain_node = {
                    "id": domain_id,
                    "name": domain.get("name", domain_id),
                    "type": "domain",
                    "description": domain.get("description", ""),
                    "term_count": domain.get("term_count", 0),
                    "children": [],
                }
                for app_id in domain_to_apps.get(domain_id, domain.get("applications", [])):
                    app = apps.get(app_id, {"name": app_id})
                    app_node = {
                        "id": app_id,
                        "name": app.get("name", app_id),
                        "type": "application",
                        "description": app.get("description", ""),
                        "children": [],
                    }
                    # BDEs under this app
                    for term_id in app_to_terms.get(app_id, app.get("bdes", [])):
                        term = terms.get(term_id, {"name": term_id})
                        app_node["children"].append({
                            "id": term_id,
                            "name": term.get("name", term_id),
                            "type": "term",
                            "is_pii": term.get("is_pii", False),
                            "dq_rules": term.get("dq_rules", {}),
                            "data_type": term.get("data_type", "string"),
                        })
                    # Datasets under this app
                    for ds_id in app_to_datasets.get(app_id, []):
                        ds = datasets.get(ds_id, {"name": ds_id})
                        app_node["children"].append({
                            "id": ds_id,
                            "name": ds.get("name", ds_id),
                            "type": "dataset",
                            "field_count": len(ds.get("fields", [])),
                            "onboarded_at": ds.get("onboarded_at"),
                        })
                    domain_node["children"].append(app_node)
                cfu_node["children"].append(domain_node)
            hierarchy.append(cfu_node)

        # Add orphan domains (not under any CFU)
        assigned_domains = set()
        for cfu in cfus.values():
            assigned_domains.update(cfu.get("domains", []))
        for domain_id, domain in domains.items():
            if domain_id not in assigned_domains:
                hierarchy.append({
                    "id": domain_id,
                    "name": domain.get("name", domain_id),
                    "type": "domain",
                    "description": domain.get("description", ""),
                    "children": [],
                })

        return hierarchy

    def get_terms_by_domain(self, domain_id: str) -> list:
        terms = self._get_all("glossary/terms")
        return [t for t in terms.values() if t.get("domain") == domain_id]

    def get_datasets_by_app(self, app_id: str) -> list:
        datasets = self._get_all("datasets/entries")
        return [d for d in datasets.values() if d.get("business_application") == app_id]

    def get_pii_terms(self) -> list:
        terms = self._get_all("glossary/terms")
        return [t for t in terms.values() if t.get("is_pii")]

    def search(self, query: str) -> list:
        """Search across all catalog entities."""
        query_lower = query.lower()
        results = []

        for coll in ["glossary/terms", "hierarchy/domains", "hierarchy/applications", "datasets/entries"]:
            items = self._get_all(coll)
            for item_id, item in items.items():
                name = item.get("name", "").lower()
                desc = item.get("description", "").lower()
                synonyms = " ".join(item.get("synonyms", [])).lower()
                if query_lower in name or query_lower in desc or query_lower in synonyms:
                    results.append({"id": item_id, "collection": coll, **item})

        return results

    def get_sync_status(self) -> dict:
        try:
            doc = self.db.document("sync_metadata/status").get()
            return doc.to_dict() if doc.exists else {"last_sync": None}
        except Exception:
            return {"last_sync": None}

    def set_sync_status(self, status: dict):
        status["timestamp"] = datetime.now(timezone.utc).isoformat()
        self.db.document("sync_metadata/status").set(status)

    # --- Helpers ---

    def _get_all(self, sub_collection: str) -> dict:
        """Get all documents in a sub-collection. Returns {id: data}."""
        try:
            docs = self.db.collection(f"{COLLECTION_PREFIX}/{sub_collection}").stream()
            return {doc.id: doc.to_dict() for doc in docs}
        except Exception as e:
            print(f"[CatalogCache] Failed to read {sub_collection}: {e}")
            return {}
