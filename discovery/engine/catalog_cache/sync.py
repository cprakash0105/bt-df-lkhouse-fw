"""Catalog Sync — Populates Firestore cache from KC APIs + local glossary.

Run on startup or periodically to keep cache fresh.
Sources:
1. Local seed_glossary.yaml (BDEs, domains, apps, reference sets)
2. link_catalog.py hierarchy (CFUs, domain→BA, BA→BDE mappings)
3. Dataplex API (entries, entry links) — for live KC state
"""
import os
import yaml
import json
import time
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from discovery.engine.catalog_cache import CatalogCache


# Hierarchy definition (same as link_catalog.py)
CFUS = {
    "consumer_banking": {
        "name": "Consumer Banking",
        "domains": ["credit", "customer", "finance", "order", "digital", "bureau"],
    },
    "enterprise_services": {
        "name": "Enterprise Services",
        "domains": ["product"],
    },
}

DOMAIN_TO_APPS = {
    "bureau": ["credit_risk"],
    "customer": ["customer_management"],
    "finance": ["billing_finance"],
    "order": ["order_management"],
    "product": ["product_catalog"],
    "digital": ["marketing_campaigns"],
}

BA_TO_BDES = {
    "credit_risk": [
        "credit_score", "bureau_reference", "pan_number", "customer_identifier",
        "loan_identifier", "emi_amount", "days_past_due",
    ],
    "customer_management": [
        "customer_identifier", "customer_name", "customer_email",
        "customer_phone", "date_of_birth", "address", "aadhaar_number",
        "kyc_status", "complaint_identifier", "priority_level", "csat_score",
    ],
    "billing_finance": [
        "transaction_amount", "currency_code", "payment_method",
        "payment_status", "upi_transaction_id", "vpa", "premium_amount",
    ],
    "order_management": [
        "order_identifier", "order_status", "order_date", "order_channel",
    ],
    "product_catalog": [
        "product_identifier", "product_name", "product_price",
        "policy_identifier", "claim_identifier", "vehicle_registration",
    ],
    "marketing_campaigns": [
        "session_id", "page_url", "event_timestamp",
    ],
}


def sync_from_glossary(cache: CatalogCache, glossary_path: Optional[str] = None):
    """Sync local glossary into Firestore cache."""
    glossary_path = glossary_path or str(
        Path(__file__).parent.parent.parent / "config" / "seed_glossary.yaml"
    )

    with open(glossary_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    counts = {"cfus": 0, "domains": 0, "apps": 0, "terms": 0, "links": 0}

    # Sync CFUs
    for cfu_id, cfu_data in CFUS.items():
        cache.upsert_cfu(cfu_id, cfu_data)
        counts["cfus"] += 1

    # Sync Domains
    for domain in data.get("data_domains", []):
        domain_apps = DOMAIN_TO_APPS.get(domain["id"], [])
        terms_in_domain = [t for t in data.get("business_terms", []) if t.get("domain") == domain["id"]]
        cache.upsert_domain(domain["id"], {
            "name": domain["name"],
            "description": domain.get("description", ""),
            "applications": domain_apps,
            "term_count": len(terms_in_domain),
        })
        counts["domains"] += 1

    # Sync Business Applications
    for app in data.get("business_applications", []):
        bdes = BA_TO_BDES.get(app["id"], [])
        cache.upsert_application(app["id"], {
            "name": app["name"],
            "description": app.get("description", ""),
            "keywords": app.get("keywords", []),
            "bdes": bdes,
        })
        counts["apps"] += 1

    # Sync BDEs (glossary terms)
    for term in data.get("business_terms", []):
        cache.upsert_term(term["id"], {
            "name": term["name"],
            "domain": term.get("domain", ""),
            "data_type": term.get("data_type", "string"),
            "information_type": term.get("information_type", "Dimension"),
            "is_pii": term.get("is_pii", False),
            "classification": term.get("classification", "Internal"),
            "dq_rules": term.get("dq_rules", {}),
            "synonyms": term.get("synonyms", []),
            "reference_code_set": term.get("reference_code_set"),
            "is_key_candidate": term.get("is_key_candidate", False),
        })
        counts["terms"] += 1

    # Sync links (domain→app, app→bde)
    for domain_id, app_ids in DOMAIN_TO_APPS.items():
        for app_id in app_ids:
            link_id = f"domain-{domain_id}-to-app-{app_id}"
            cache.upsert_link(link_id, {
                "source_id": domain_id,
                "target_id": app_id,
                "link_type": "related",
                "source_type": "domain",
                "target_type": "application",
            })
            counts["links"] += 1

    for app_id, bde_ids in BA_TO_BDES.items():
        for bde_id in bde_ids:
            link_id = f"app-{app_id}-to-bde-{bde_id}"
            cache.upsert_link(link_id, {
                "source_id": app_id,
                "target_id": bde_id,
                "link_type": "definition",
                "source_type": "application",
                "target_type": "term",
            })
            counts["links"] += 1

    # Update sync status
    cache.set_sync_status({
        "last_sync": datetime.now(timezone.utc).isoformat(),
        "source": "local_glossary",
        **counts,
    })

    print(f"[CatalogSync] Synced: {counts}")
    return counts


def sync_dataset_on_approval(cache: CatalogCache, suggestion) -> str:
    """Called when SD approves a dataset — immediately update cache."""
    dataset_id = suggestion.asset_name.replace("_", "-")
    fields = []
    for f in suggestion.fields:
        fields.append({
            "name": f.field_name,
            "type": f.field_type,
            "linked_bde": f.linked_term,
            "is_pii": f.is_pii,
            "confidence": round(f.confidence, 2),
        })

    cache.upsert_dataset(dataset_id, {
        "name": suggestion.asset_name,
        "domain": suggestion.data_domain,
        "business_application": suggestion.business_application,
        "primary_key": suggestion.primary_key,
        "field_count": len(fields),
        "fields": fields,
        "pii_fields": [f.field_name for f in suggestion.fields if f.is_pii],
        "onboarded_at": datetime.now(timezone.utc).isoformat(),
    })

    # Also create link: dataset → BA
    if suggestion.business_application:
        cache.upsert_link(f"dataset-{dataset_id}-to-app-{suggestion.business_application}", {
            "source_id": dataset_id,
            "target_id": suggestion.business_application,
            "link_type": "related",
            "source_type": "dataset",
            "target_type": "application",
        })

    print(f"[CatalogSync] Dataset cached: {suggestion.asset_name}")
    return dataset_id
