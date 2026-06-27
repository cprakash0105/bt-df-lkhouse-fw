"""Contract Generator — Produces a Data Contract from SD discovery suggestions.
A data contract is the formal agreement between producer and consumer.
Generated on approval, pushed to GCS, enforced by the pipeline."""
import os
import yaml
from datetime import datetime, timezone
from typing import Optional
from discovery.engine.suggester import DiscoverySuggestion

try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
CONFIG_BUCKET = os.environ.get("CONFIG_BUCKET", f"{PROJECT_ID}-lakehouse")


class ContractGenerator:
    """Generates data contracts from SD suggestions."""

    def generate(self, suggestion: DiscoverySuggestion,
                 owner_team: str = "TBD",
                 owner_email: str = "tbd@bank.com",
                 source_system: str = "Unknown",
                 frequency: str = "daily") -> str:
        """Generate a data contract YAML from discovery suggestion."""
        now = datetime.now(timezone.utc).isoformat()
        pii_fields = [f.field_name for f in suggestion.fields if f.is_pii]
        has_pii = len(pii_fields) > 0

        contract = {
            "contract": {
                "name": suggestion.asset_name,
                "version": "1.0.0",
                "status": "draft",
                "created_at": now,
                "updated_at": now,
                "owner": {
                    "team": owner_team,
                    "email": owner_email,
                    "domain": suggestion.data_domain or "Unknown",
                    "business_application": suggestion.business_application_name or "Unknown",
                },
                "source": {
                    "system": source_system,
                    "format": "JSONL",
                    "frequency": frequency,
                    "landing_path": f"gs://{CONFIG_BUCKET}/landing/{suggestion.asset_name}/",
                },
                "schema": self._build_schema(suggestion),
                "quality": self._build_quality(suggestion),
                "governance": self._build_governance(suggestion, pii_fields),
                "evolution": self._build_evolution(suggestion, has_pii),
                "consumers": [],
                "slo": {
                    "availability": "99.9%",
                    "freshness": "24h",
                    "quality_score": "98%",
                    "breach_notification": owner_email,
                },
            }
        }

        return yaml.dump(contract, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def generate_and_push(self, suggestion: DiscoverySuggestion, **kwargs) -> Optional[str]:
        """Generate contract and push to GCS."""
        contract_yaml = self.generate(suggestion, **kwargs)

        if not GCS_AVAILABLE:
            return None

        gcs_path = f"gs://{CONFIG_BUCKET}/contracts/{suggestion.asset_name}/v1.0.0.yaml"
        blob_name = f"contracts/{suggestion.asset_name}/v1.0.0.yaml"

        try:
            client = storage.Client(project=PROJECT_ID)
            bucket = client.bucket(CONFIG_BUCKET)
            blob = bucket.blob(blob_name)
            blob.upload_from_string(contract_yaml, content_type="application/x-yaml")
            print(f"[ContractGenerator] Pushed: {gcs_path}")
            return gcs_path
        except Exception as e:
            print(f"[ContractGenerator] Failed to push: {e}")
            return None

    def _build_schema(self, suggestion: DiscoverySuggestion) -> dict:
        fields = []
        for f in suggestion.fields:
            field_def = {
                "name": f.field_name,
                "type": f.field_type,
                "nullable": not f.dq_rules.get("not_null", False),
                "description": "",
            }
            if f.linked_term_name:
                field_def["business_term"] = f.linked_term_name
            if f.is_pii:
                field_def["pii"] = True
            if f.dq_rules.get("unique"):
                field_def["unique"] = True
            if f.dq_rules.get("positive"):
                field_def["positive"] = True
            if f.dq_rules.get("range"):
                field_def["range"] = f.dq_rules["range"]
            if f.dq_rules.get("format"):
                field_def["format"] = f.dq_rules["format"]
            if f.accepted_values:
                field_def["accepted_values"] = f.accepted_values
            fields.append(field_def)

        return {
            "primary_key": suggestion.primary_key or "id",
            "dedup_order_by": "ingestion_ts DESC",
            "fields": fields,
        }

    def _build_quality(self, suggestion: DiscoverySuggestion) -> dict:
        not_null_fields = [f.field_name for f in suggestion.fields if f.dq_rules.get("not_null")]
        unique_fields = [f.field_name for f in suggestion.fields if f.dq_rules.get("unique")]

        validity_rules = []
        for f in suggestion.fields:
            if f.dq_rules.get("range"):
                validity_rules.append({"field": f.field_name, "check": "range", "params": f.dq_rules["range"]})
            if f.dq_rules.get("format"):
                validity_rules.append({"field": f.field_name, "check": "format", "params": f.dq_rules["format"]})
            if f.dq_rules.get("positive"):
                validity_rules.append({"field": f.field_name, "check": "positive"})

        return {
            "completeness": {
                "target": "99.5%",
                "critical_fields": not_null_fields,
            },
            "validity": {
                "target": "98%",
                "rules": validity_rules,
            },
            "uniqueness": {
                "target": "100%",
                "fields": unique_fields,
            },
            "freshness": {
                "max_delay": "24h",
                "check_field": "ingestion_ts",
            },
        }

    def _build_governance(self, suggestion: DiscoverySuggestion, pii_fields: list) -> dict:
        classification = "PII" if pii_fields else "Internal"

        masking = {}
        if pii_fields:
            masking["non_prod"] = "required"
            strategy = {}
            for field in pii_fields:
                if "pan" in field or "aadhaar" in field:
                    strategy[field] = "hash"
                elif "email" in field:
                    strategy[field] = "partial"
                elif "phone" in field or "mobile" in field:
                    strategy[field] = "last_4_digits"
                elif "dob" in field or "birth" in field:
                    strategy[field] = "year_only"
                else:
                    strategy[field] = "redact"
            masking["strategy"] = strategy

        return {
            "classification": classification,
            "pii_fields": pii_fields,
            "masking": masking,
            "retention": {
                "period": "7 years" if classification == "PII" else "3 years",
                "policy": "Regulatory compliance",
            },
            "access": {
                "teams": [suggestion.business_application_name or "Data Engineering"],
                "role_required": f"{suggestion.asset_name}_reader",
            },
        }

    def _build_evolution(self, suggestion: DiscoverySuggestion, has_pii: bool) -> dict:
        if has_pii:
            return {
                "allowed": ["add_column"],
                "blocked": ["drop_column", "type_narrow", "type_widen", "rename_column"],
                "on_violation": "fail_pipeline",
                "notification": "data-governance@bank.com",
            }
        return {
            "allowed": ["add_column", "type_widen"],
            "blocked": ["drop_column", "type_narrow", "rename_column"],
            "on_violation": "fail_pipeline",
            "notification": "data-engineering@bank.com",
        }
