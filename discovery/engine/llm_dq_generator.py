"""LLM DQ Generator — Generates business DQ rules from GE statistical profiles.

Flow: GE profiles data → statistical summary → LLM generates:
  1. Business-level DQ rules per field
  2. BDE definitions/descriptions
  3. Business Application classification
  4. Information Type assignment

Key: Only statistical summaries go to LLM (no raw data). Amanda's requirement.
"""
import json
from typing import Optional

from .llm_client import LLMClient


SYSTEM_PROMPT = """You are a Data Governance expert for a banking/telecom enterprise.
You analyze STATISTICAL PROFILES of datasets (never raw data) and generate:
1. Business-level Data Quality rules
2. Business Data Element definitions
3. Business Application classification
4. Information Type assignment (Identifier, Measure, Temporal, Reference, Dimension)

Rules you can define:
- not_null: field must always have a value
- unique: no duplicates allowed
- positive: numeric value must be > 0
- range: [min, max] bounds
- accepted_values: list of valid codes/enums
- format: regex pattern name (email, pan, aadhaar, phone, uuid)
- freshness: data must be within N days of current
- referential: values must exist in another dataset

Be conservative — only suggest rules you're confident about from the statistics.
If null_pct > 20%, don't suggest not_null.
If distinct_pct > 50% for a string field, it's probably not a reference/enum.
"""

USER_TEMPLATE = """Analyze this dataset profile and generate business DQ rules.

Dataset: {dataset_name}
Rows: {row_count} | Columns: {column_count}

Field Profiles:
{field_profiles}

Respond in JSON format:
{{
  "business_application": "<app_name>",
  "domain": "<data_domain>",
  "fields": [
    {{
      "name": "<field_name>",
      "bde_name": "<Business Data Element name>",
      "bde_description": "<1-line business description>",
      "information_type": "Identifier|Measure|Temporal|Reference|Dimension",
      "dq_rules": {{
        "not_null": true/false,
        "unique": true/false,
        "positive": true/false,
        "range": [min, max] or null,
        "accepted_values": [...] or null,
        "format": "pattern_name" or null
      }},
      "is_pii": true/false,
      "classification": "PII|Sensitive|Internal|Public"
    }}
  ]
}}
"""


class LLMDQGenerator:
    """Generates business DQ rules from GE statistical profiles using LLM."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()

    def _ask(self, prompt: str, system: str) -> Optional[str]:
        return self.llm.generate(system=system, user=prompt, max_tokens=4096)

    def generate(self, llm_summary: dict) -> dict:
        """Generate business DQ from GE profile summary.

        Args:
            llm_summary: Output of GEProfile.llm_summary (statistical only)

        Returns:
            Dict with business_application, domain, and per-field DQ rules
        """
        # Format field profiles for prompt
        field_lines = []
        for f in llm_summary.get("fields", []):
            line = f"- {f['name']}: type={f['type']}, info_type={f['information_type']}, "
            line += f"null={f['null_pct']:.0%}, distinct={f['distinct_count']} ({f['distinct_pct']:.0%})"

            if f.get("is_key"):
                line += ", KEY_CANDIDATE"
            if f.get("is_pii"):
                line += ", LIKELY_PII"
            if f.get("is_reference"):
                line += ", REFERENCE_FIELD"
            if f.get("stats"):
                s = f["stats"]
                line += f", range=[{s['min']}, {s['max']}], mean={s['mean']}"
            if f.get("fingerprint"):
                fp = f["fingerprint"]
                line += f", fingerprint={fp['matched_set']}({fp['match_ratio']:.0%})"
            if f.get("detected_pattern"):
                line += f", pattern={f['detected_pattern']}"
            if f.get("suggested_bde"):
                line += f", bde_match={f['suggested_bde']}(conf={f['confidence']:.0%})"
            if f.get("value_distribution"):
                top_vals = [v for v, _ in f["value_distribution"][:5]]
                line += f", top_values={top_vals}"

            field_lines.append(line)

        prompt = USER_TEMPLATE.format(
            dataset_name=llm_summary.get("dataset", "unknown"),
            row_count=llm_summary.get("row_count", 0),
            column_count=llm_summary.get("column_count", 0),
            field_profiles="\n".join(field_lines),
        )

        response = self._ask(prompt, system=SYSTEM_PROMPT)

        if not response or "__QUOTA_EXCEEDED__" in response:
            return {"error": "LLM unavailable", "fields": []}

        return self._parse_response(response)

    def _parse_response(self, response: str) -> dict:
        """Parse LLM JSON response, handling markdown fences."""
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            # Remove json language tag
            if text.startswith("json"):
                text = text[4:]

        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            # Try to find JSON in response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            return {"error": "Failed to parse LLM response", "raw": response[:500]}

    def merge_with_profile(self, ge_profile, llm_result: dict) -> dict:
        """Merge LLM-generated DQ with GE profile signals for final output.

        Combines:
        - GE's statistical confidence (data-driven)
        - LLM's business understanding (context-driven)
        - Fingerprint matches (reference-driven)
        """
        if "error" in llm_result:
            return llm_result

        merged = {
            "business_application": llm_result.get("business_application"),
            "domain": llm_result.get("domain"),
            "fields": [],
        }

        # Build lookup from LLM result
        llm_fields = {f["name"]: f for f in llm_result.get("fields", [])}

        for col in ge_profile.columns:
            llm_field = llm_fields.get(col.name, {})
            field_out = {
                "name": col.name,
                "bde_name": llm_field.get("bde_name", col.suggested_bde),
                "bde_description": llm_field.get("bde_description", ""),
                "information_type": llm_field.get("information_type", col.information_type),
                "is_pii": llm_field.get("is_pii", col.is_pii),
                "classification": llm_field.get("classification", "Internal"),
                "confidence": col.confidence,
                "dq_rules": {},
                "sources": [],  # Audit trail: where each rule came from
            }

            # Merge DQ rules from LLM
            llm_dq = llm_field.get("dq_rules", {})
            for rule, value in llm_dq.items():
                if value and value is not None:
                    field_out["dq_rules"][rule] = value
                    field_out["sources"].append(f"{rule}: LLM")

            # Override/supplement with GE fingerprint (higher trust for reference sets)
            if col.fingerprint and col.fingerprint.matched_code_set:
                ref_set = col.fingerprint.matched_code_set
                if col.fingerprint.match_ratio >= 0.7:
                    # High fingerprint match overrides LLM's accepted_values
                    field_out["dq_rules"]["accepted_values"] = ref_set
                    field_out["sources"].append(f"accepted_values: fingerprint ({ref_set})")

            # GE statistical override: if GE says it's a key, ensure unique+not_null
            if col.is_key:
                field_out["dq_rules"]["unique"] = True
                field_out["dq_rules"]["not_null"] = True
                if "unique: LLM" not in field_out["sources"]:
                    field_out["sources"].append("unique: GE_stats")

            merged["fields"].append(field_out)

        return merged
