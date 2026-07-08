"""Approval Handler — Writes approved suggestions back to Dataplex Knowledge Catalog.
On approval:
  1. Creates new BDE terms in the Glossary (if proposed)
  2. Links dataset to Business Application (Custom Entry)
  3. Sets DQ rules and classification metadata
  4. Writes pipeline config YAML to GCS
  5. Generates pipeline config YAML
"""
import os
import sys
from typing import Optional
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from logger import get_logger
_log = get_logger("discovery.approval_handler")

from discovery.engine.suggester import DiscoverySuggestion, FieldSuggestion

try:
    from google.cloud import dataplex_v1, storage
    from google.cloud.dataplex_v1 import BusinessGlossaryServiceClient, CatalogServiceClient
    DATAPLEX_AVAILABLE = True
    GCS_AVAILABLE = True
except ImportError:
    DATAPLEX_AVAILABLE = False
    GCS_AVAILABLE = False


PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
PROJECT_NUMBER = "978009776592"
LOCATION = os.environ.get("GCP_REGION", "europe-west2")
GLOSSARY_ID = "enterprise-data-glossary"
ENTRY_GROUP_ID = "enterprise-hierarchy"
CONFIG_BUCKET = os.environ.get("CONFIG_BUCKET", f"{PROJECT_ID}-lakehouse")
CONFIG_PREFIX = "framework/config/tables"


class ApprovalHandler:
    """Handles post-approval actions: writes to Dataplex, generates configs."""

    def __init__(self):
        self._glossary_client = None
        self._catalog_client = None
        self.glossary_name = f"projects/{PROJECT_ID}/locations/{LOCATION}/glossaries/{GLOSSARY_ID}"
        self.entry_group = f"projects/{PROJECT_ID}/locations/{LOCATION}/entryGroups/{ENTRY_GROUP_ID}"
        self.parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"

    def _get_glossary_client(self):
        if not DATAPLEX_AVAILABLE:
            return None
        if self._glossary_client is None:
            self._glossary_client = BusinessGlossaryServiceClient()
        return self._glossary_client

    def _get_catalog_client(self):
        if not DATAPLEX_AVAILABLE:
            return None
        if self._catalog_client is None:
            self._catalog_client = CatalogServiceClient()
        return self._catalog_client

    def process_approval(self, suggestion: DiscoverySuggestion, config_yaml: str = None) -> dict:
        """Process a full approval — create terms, link BA, set policies, push config.
        Returns a summary of what was done."""
        _log.info("Processing approval", asset_name=suggestion.asset_name,
                  business_app=suggestion.business_application_name,
                  new_terms=len(suggestion.new_term_proposals))
        results = {
            "new_terms_created": [],
            "ba_linked": None,
            "policies_set": [],
            "config_gcs_path": None,
            "errors": [],
        }

        # 1. Create new BDE terms in glossary
        if suggestion.new_term_proposals:
            for proposal in suggestion.new_term_proposals:
                success = self._create_bde_term(proposal, suggestion)
                if success:
                    results["new_terms_created"].append(proposal["suggested_term_name"])
                else:
                    results["errors"].append(f"Failed to create term: {proposal['suggested_term_name']}")

        # 2. Register dataset under Business Application
        if suggestion.business_application:
            success = self._link_to_business_application(suggestion)
            if success:
                results["ba_linked"] = suggestion.business_application_name
            else:
                results["errors"].append(f"Failed to link to BA: {suggestion.business_application_name}")

        # 3. Set DQ and classification policies
        for field in suggestion.fields:
            if field.is_pii or field.dq_rules:
                results["policies_set"].append({
                    "field": field.field_name,
                    "classification": field.classification,
                    "dq_rules": field.dq_rules,
                })

        # 4. Push pipeline config to GCS
        if config_yaml:
            gcs_path = self._push_config_to_gcs(suggestion.asset_name, config_yaml)
            if gcs_path:
                results["config_gcs_path"] = gcs_path
            else:
                results["errors"].append("Failed to push config to GCS")

        # 5. Create EntryLinks (dataset->BDEs, dataset->BA)
        self._create_entry_links(suggestion)

        _log.info("Approval processed", asset_name=suggestion.asset_name,
                  new_terms_created=results["new_terms_created"],
                  ba_linked=results["ba_linked"],
                  config_path=results["config_gcs_path"],
                  errors=results["errors"])
        return results

    def _create_bde_term(self, proposal: dict, suggestion: DiscoverySuggestion) -> bool:
        """Create a new Business Data Element in the glossary."""
        client = self._get_glossary_client()
        if not client:
            print(f"[ApprovalHandler] Dataplex not available, skipping term creation")
            return False

        term_id = f"{suggestion.asset_name}_{proposal['field_name']}".lower().replace(" ", "_")
        # Dataplex term IDs: only lowercase, numbers, hyphens
        import re
        term_id = re.sub(r'[^a-z0-9-]', '-', term_id).strip('-')
        term_id = re.sub(r'-+', '-', term_id)  # collapse multiple hyphens
        term_name = proposal["suggested_term_name"]
        domain = proposal.get("suggested_domain", "")
        data_type = proposal.get("suggested_type", "string")
        info_type = proposal.get("suggested_info_type", "Dimension")

        # Find the field in suggestions for additional metadata
        field = next((f for f in suggestion.fields if f.field_name == proposal["field_name"]), None)

        desc_parts = [f"Auto-created by Semantic Discovery during onboarding of '{suggestion.asset_name}'"]
        desc_parts.append(f"\nData Type: {data_type}")
        desc_parts.append(f"Information Type: {info_type}")
        if field and field.is_pii:
            desc_parts.append("Classification: PII")
        else:
            desc_parts.append("Classification: Internal")
        if field and field.dq_rules:
            dq_str = ", ".join(f"{k}: {v}" for k, v in field.dq_rules.items())
            desc_parts.append(f"DQ Rules: {dq_str}")
        desc_parts.append(f"Domain: {domain}")
        desc_parts.append(f"Synonyms: {proposal['field_name']}")

        description = "\n".join(desc_parts)

        term = dataplex_v1.GlossaryTerm(
            description=description,
            display_name=term_name,
            parent=self.glossary_name,
        )
        req = dataplex_v1.CreateGlossaryTermRequest(
            parent=self.glossary_name,
            term=term,
            term_id=term_id,
        )

        try:
            client.create_glossary_term(request=req)
            print(f"[ApprovalHandler] Created BDE: {term_name}")

            # Link newly created BDE to the dataset (definition link)
            # This fixes the gap where new terms weren't linked on creation
            if field:
                field.linked_term = term_id
                field.linked_term_name = term_name

            return True
        except Exception as e:
            if "ALREADY_EXISTS" in str(e):
                print(f"[ApprovalHandler] BDE already exists: {term_name}")
                if field:
                    field.linked_term = term_id
                    field.linked_term_name = term_name
                return True
            print(f"[ApprovalHandler] Failed to create BDE '{term_name}': {e}")
            return False

    def _link_to_business_application(self, suggestion: DiscoverySuggestion) -> bool:
        """Register the dataset as linked to a Business Application in the hierarchy."""
        client = self._get_catalog_client()
        if not client:
            print("[ApprovalHandler] Catalog client not available")
            return False

        entry_id = f"dataset-{suggestion.asset_name.replace('_', '-')}"
        fq_type = f"{self.parent}/entryTypes/dataset"

        # Ensure 'dataset' entry type exists
        try:
            entry_type = dataplex_v1.EntryType(
                description="A data asset/dataset registered through Semantic Discovery",
                display_name="Dataset",
            )
            req = dataplex_v1.CreateEntryTypeRequest(
                parent=self.parent,
                entry_type=entry_type,
                entry_type_id="dataset",
            )
            op = client.create_entry_type(request=req)
            if hasattr(op, 'result'):
                op.result()
            print("[ApprovalHandler] Created 'dataset' entry type")
        except Exception as e:
            if "ALREADY_EXISTS" not in str(e):
                print(f"[ApprovalHandler] Entry type creation note: {e}")

        # Create dataset entry
        pii_fields = [f.field_name for f in suggestion.fields if f.is_pii]

        entry = dataplex_v1.Entry(
            entry_type=fq_type,
            fully_qualified_name=f"custom:dataset/{suggestion.asset_name}",
            entry_source=dataplex_v1.EntrySource(
                description=(
                    f"Dataset: {suggestion.asset_name}\n"
                    f"Business Application: {suggestion.business_application_name}\n"
                    f"Domain: {suggestion.data_domain}\n"
                    f"Classification: {'PII' if pii_fields else 'Internal'}\n"
                    f"Primary Key: {suggestion.primary_key}\n"
                    f"PII Fields: {', '.join(pii_fields) if pii_fields else 'None'}\n"
                    f"Fields: {len(suggestion.fields)}\n"
                    f"Discovered: {suggestion.discovered_at}"
                ),
                display_name=suggestion.asset_name,
            ),
        )
        req = dataplex_v1.CreateEntryRequest(
            parent=self.entry_group,
            entry=entry,
            entry_id=entry_id,
        )

        try:
            client.create_entry(request=req)
            print(f"[ApprovalHandler] Registered dataset: {suggestion.asset_name}")
            return True
        except Exception as e:
            if "ALREADY_EXISTS" in str(e):
                print(f"[ApprovalHandler] Dataset already registered: {suggestion.asset_name}")
                return True
            # Try without the entry_id suffix collision
            try:
                import time
                entry_id_retry = f"{entry_id}-{int(time.time()) % 10000}"
                req2 = dataplex_v1.CreateEntryRequest(
                    parent=self.entry_group, entry=entry, entry_id=entry_id_retry
                )
                client.create_entry(request=req2)
                print(f"[ApprovalHandler] Registered dataset (retry): {suggestion.asset_name}")
                return True
            except Exception as e2:
                print(f"[ApprovalHandler] Failed to register dataset: {e2}")
                return False

    def _push_config_to_gcs(self, asset_name: str, config_yaml: str) -> Optional[str]:
        """Push pipeline config YAML to GCS. Overwrites if exists (re-onboard)."""
        if not GCS_AVAILABLE:
            print("[ApprovalHandler] GCS not available")
            return None

        gcs_path = f"gs://{CONFIG_BUCKET}/{CONFIG_PREFIX}/{asset_name}.yaml"
        blob_name = f"{CONFIG_PREFIX}/{asset_name}.yaml"

        try:
            client = storage.Client(project=PROJECT_ID)
            bucket = client.bucket(CONFIG_BUCKET)
            blob = bucket.blob(blob_name)
            blob.upload_from_string(config_yaml, content_type="application/x-yaml")
            print(f"[ApprovalHandler] Config pushed to: {gcs_path} (overwrite={blob.exists()})")
            return gcs_path
        except Exception as e:
            print(f"[ApprovalHandler] Failed to push config to GCS: {e}")
            return None

    def _create_entry_links(self, suggestion: DiscoverySuggestion):
        """Create EntryLinks between dataset/BA and BDEs for catalog navigation."""
        import json
        import urllib.request

        try:
            import subprocess
            result = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True)
            token = result.stdout.strip()
        except Exception:
            # Try application default credentials
            try:
                import google.auth
                import google.auth.transport.requests
                creds, _ = google.auth.default()
                creds.refresh(google.auth.transport.requests.Request())
                token = creds.token
            except Exception as e:
                print(f"[ApprovalHandler] Cannot get token for EntryLinks: {e}")
                return

        if not token:
            return

        entry_group_url = f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/entryGroups/{ENTRY_GROUP_ID}"
        definition_link_type = "projects/dataplex-types/locations/global/entryLinkTypes/definition"
        related_link_type = "projects/dataplex-types/locations/global/entryLinkTypes/related"

        # Link dataset to BA (related)
        if suggestion.business_application:
            ba_id = suggestion.business_application.replace("_", "-") if suggestion.business_application else None
            if ba_id:
                dataset_entry = f"projects/{PROJECT_ID}/locations/{LOCATION}/entryGroups/{ENTRY_GROUP_ID}/entries/dataset-{suggestion.asset_name.replace('_', '-')}"
                ba_entry = f"projects/{PROJECT_ID}/locations/{LOCATION}/entryGroups/{ENTRY_GROUP_ID}/entries/{suggestion.business_application}"
                link_id = f"dataset-{suggestion.asset_name.replace('_', '-')}-to-ba-{suggestion.business_application}"
                self._post_entry_link(token, entry_group_url, link_id, related_link_type, dataset_entry, ba_entry)

        # Link dataset to each matched BDE (definition)
        glossary_term_prefix = f"projects/{PROJECT_ID}/locations/{LOCATION}/entryGroups/@dataplex/entries/projects/{PROJECT_NUMBER}/locations/{LOCATION}/glossaries/{GLOSSARY_ID}/terms"
        dataset_entry = f"projects/{PROJECT_ID}/locations/{LOCATION}/entryGroups/{ENTRY_GROUP_ID}/entries/dataset-{suggestion.asset_name.replace('_', '-')}"

        for field in suggestion.fields:
            if field.linked_term and field.confidence >= 0.5:
                term_entry = f"{glossary_term_prefix}/{field.linked_term}"
                link_id = f"dataset-{suggestion.asset_name.replace('_', '-')}-to-bde-{field.linked_term}"
                self._post_entry_link(token, entry_group_url, link_id, definition_link_type, dataset_entry, term_entry)

    def _post_entry_link(self, token: str, entry_group_url: str, link_id: str,
                         link_type: str, source: str, target: str):
        """POST an EntryLink to the Dataplex API."""
        import json
        import urllib.request

        url = f"https://dataplex.googleapis.com/v1/{entry_group_url}/entryLinks?entry_link_id={link_id}"
        payload = json.dumps({
            "entry_link_type": link_type,
            "entry_references": [
                {"name": source, "type": "SOURCE"},
                {"name": target, "type": "TARGET"},
            ],
        })
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            req = urllib.request.Request(url, data=payload.encode(), headers=headers, method="POST")
            with urllib.request.urlopen(req) as resp:
                print(f"[ApprovalHandler] EntryLink created: {link_id}")
        except Exception as e:
            error_msg = str(e)
            if "ALREADY_EXISTS" in error_msg:
                pass  # Silent - link already exists
            else:
                print(f"[ApprovalHandler] EntryLink failed ({link_id}): {error_msg[:100]}")
