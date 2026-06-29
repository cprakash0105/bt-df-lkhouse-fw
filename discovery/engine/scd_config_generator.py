"""SCD Config Generator — Produces SCD consumption config from business intent.
Infers SCD type from natural language cues and generates the YAML config
that the consume engine uses to apply the correct SCD logic."""
import os
import yaml
from typing import Optional
from discovery.engine.suggester import DiscoverySuggestion

try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
CONFIG_BUCKET = os.environ.get("CONFIG_BUCKET", f"{PROJECT_ID}-lakehouse")

# Keywords that hint at SCD type
SCD_INDICATORS = {
    1: ["overwrite", "latest only", "no history", "just load", "replace", "current only", "reference data", "lookup"],
    2: ["track history", "audit trail", "every change", "versioned", "effective date", "full history", "lifecycle"],
    3: ["previous value", "track trend", "before and after", "compare previous", "score change", "delta"],
    4: ["fast lookup", "current plus history", "separate history", "archive old", "hot and cold"],
    6: ["track everything", "complete history", "hybrid", "current and previous and history", "full tracking"],
    0: ["append only", "event", "stream", "log", "clickstream", "immutable", "insert only"],
}


class SCDConfigGenerator:
    """Generates SCD consumption config from discovery suggestions + business intent."""

    def infer_scd_type(self, description: str, domain: str = None) -> int:
        """Infer SCD type from natural language description and domain."""
        desc_lower = description.lower() if description else ""

        # Check explicit keywords
        for scd_type, keywords in SCD_INDICATORS.items():
            for kw in keywords:
                if kw in desc_lower:
                    return scd_type

        # Infer from domain if no explicit keywords
        if domain:
            domain_lower = domain.lower()
            if domain_lower in ("digital", "clickstream", "event"):
                return 0  # append only
            elif domain_lower in ("customer", "account", "kyc"):
                return 2  # track history
            elif domain_lower in ("bureau", "credit", "score"):
                return 3  # track previous
            elif domain_lower in ("product", "reference"):
                return 1  # overwrite

        # Default: Type 2 (safest - keeps history)
        return 2

    def generate(self, suggestion: DiscoverySuggestion,
                 scd_type: int = None,
                 tracked_columns: list = None,
                 business_intent: str = "") -> Optional[str]:
        """Generate SCD consumption YAML config."""
        if scd_type is None:
            scd_type = self.infer_scd_type(business_intent, suggestion.data_domain)

        if scd_type == 0:
            # Append only - no SCD, just a pass-through SQL
            return None

        table_name = f"dim_{suggestion.asset_name}"
        pk = suggestion.primary_key or "id"

        # If tracked columns not specified, use all non-key, non-PII columns
        if not tracked_columns:
            tracked_columns = [
                f.field_name for f in suggestion.fields
                if f.field_name != pk
                and not f.field_name.endswith("_id")
                and f.field_name != "ingestion_ts"
            ]
            # Limit to reasonable number
            tracked_columns = tracked_columns[:6]

        config = {
            table_name: {
                "table": table_name,
                "scd_type": scd_type,
                "primary_key": pk,
                "source_query": f"SELECT * FROM `${{PROJECT_ID}}.lakehouse_ccn.{suggestion.asset_name}`",
                "tracked_columns": tracked_columns,
            }
        }

        # Type 4 needs history table name
        if scd_type == 4:
            config[table_name]["history_table"] = f"{table_name}_archive"

        return yaml.dump(config, default_flow_style=False, sort_keys=False)

    def generate_and_push(self, suggestion: DiscoverySuggestion,
                          scd_type: int = None,
                          tracked_columns: list = None,
                          business_intent: str = "") -> Optional[str]:
        """Generate SCD config and push to GCS."""
        config_yaml = self.generate(suggestion, scd_type, tracked_columns, business_intent)

        if not config_yaml:
            return None

        if not GCS_AVAILABLE:
            return None

        table_name = f"dim_{suggestion.asset_name}"
        gcs_path = f"gs://{CONFIG_BUCKET}/framework/config/consumption/scd_{suggestion.asset_name}.yaml"
        blob_name = f"framework/config/consumption/scd_{suggestion.asset_name}.yaml"

        try:
            client = storage.Client(project=PROJECT_ID)
            bucket = client.bucket(CONFIG_BUCKET)
            blob = bucket.blob(blob_name)
            blob.upload_from_string(config_yaml, content_type="application/x-yaml")
            print(f"[SCDConfigGen] Pushed: {gcs_path}")
            return gcs_path
        except Exception as e:
            print(f"[SCDConfigGen] Failed to push: {e}")
            return None

    def get_scd_description(self, scd_type: int) -> str:
        """Human-readable description of what the SCD type does."""
        descriptions = {
            0: "Append Only — events inserted, never updated",
            1: "Type 1 (Overwrite) — always latest value, no history",
            2: "Type 2 (Full History) — new row per change with effective dates",
            3: "Type 3 (Previous Value) — current + one previous value per column",
            4: "Type 4 (Current + Archive) — fast current table + separate history",
            6: "Type 6 (Hybrid) — full history + current_ + prev_ columns on every row",
        }
        return descriptions.get(scd_type, "Unknown")
