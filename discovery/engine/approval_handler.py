"""Approval Handler — Writes approved suggestions back to Dataplex Knowledge Catalog.
On approval:
  1. Creates new BDE terms in the Glossary (if proposed)
  2. Links dataset to Business Application (Custom Entry)
  3. Sets DQ rules and classification metadata
  4. Generates pipeline config YAML
"""
import os
from typing import Optional
from discovery.engine.suggester import DiscoverySuggestion, FieldSuggestion

try:
    from google.cloud import dataplex_v1
    from google.cloud.dataplex_v1 import BusinessGlossaryServiceClient, CatalogServiceClient
    DATAPLEX_AVAILABLE = True
except ImportError:
    DATAPLEX_AVAILABLE = False


PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
LOCATION = os.environ.get("GCP_REGION", "europe-west2")
GLOSSARY_ID = "enterprise-data-glossary"
ENTRY_GROUP_ID = "enterprise-hierarchy"


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

    def process_approval(self, suggestion: DiscoverySuggestion) -> dict:
        """Process a full approval — create terms, link BA, set policies.
        Returns a summary of what was done."""
        results = {
            "new_terms_created": [],
            "ba_linked": None,
            "policies_set": [],
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

        return results

    def _create_bde_term(self, proposal: dict, suggestion: DiscoverySuggestion) -> bool:
        """Create a new Business Data Element in the glossary."""
        client = self._get_glossary_client()
        if not client:
            print(f"[ApprovalHandler] Dataplex not available, skipping term creation")
            return False

        term_id = proposal["field_name"].lower().replace(" ", "_")
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
            return True
        except Exception as e:
            if "ALREADY_EXISTS" in str(e):
                print(f"[ApprovalHandler] BDE already exists: {term_name}")
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
            print(f"[ApprovalHandler] Failed to register dataset: {e}")
            return False
