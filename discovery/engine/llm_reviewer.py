"""LLM Reviewer — Validates and corrects SD suggestions in one call per dataset.
Catches errors the rules engine makes: wrong accepted_values, false PII, mismatched terms.
Runs AFTER the deterministic engine, BEFORE showing results to steward."""
import json
from typing import Optional
from discovery.engine.llm_client import get_llm
from discovery.engine.suggester import DiscoverySuggestion


REVIEW_PROMPT = """Review this data discovery result. Fix any errors. Return ONLY valid JSON.

Dataset: {dataset_name}
Domain: {domain}
Business Application: {business_app}

Current suggestions:
{suggestions_json}

Check and fix:
1. accepted_values: Are they correct for this dataset's domain? (e.g., loan statuses should be [paid, overdue, partial, waived], not [delivered, shipped, cancelled])
2. PII: Is each PII flag correct? Amounts and dates are NOT PII. Names, phone, email, aadhaar, PAN ARE PII.
3. primary_key: Is it correct for this dataset?
4. DQ rules: Are not_null fields reasonable? (nullable fields like payment_date shouldn't be not_null)

Return JSON with ONLY the corrections needed:
{{"corrections": [{{"field": "field_name", "fix": "what to fix", "old_value": "...", "new_value": "..."}}], "accepted_values_override": {{"field_name": ["val1", "val2"]}}, "remove_pii": ["field_names_incorrectly_flagged"], "remove_not_null": ["field_names_that_should_be_nullable"]}}

If everything looks correct, return: {{"corrections": []}}"""


class LLMReviewer:
    """Uses LLM to review and correct SD suggestions."""

    def review(self, suggestion: DiscoverySuggestion) -> dict:
        """Review suggestions and return corrections."""
        llm = get_llm()

        # Build compact summary of suggestions for LLM
        suggestions_summary = []
        for f in suggestion.fields:
            entry = {
                "field": f.field_name,
                "type": f.field_type,
                "matched_term": f.linked_term_name,
                "is_pii": f.is_pii,
                "dq_rules": f.dq_rules,
            }
            if f.accepted_values:
                entry["accepted_values"] = f.accepted_values
            suggestions_summary.append(entry)

        prompt = REVIEW_PROMPT.format(
            dataset_name=suggestion.asset_name,
            domain=suggestion.data_domain or "unknown",
            business_app=suggestion.business_application_name or "unknown",
            suggestions_json=json.dumps(suggestions_summary, indent=2),
        )

        response = llm.generate(
            system="You are a data quality reviewer. Fix incorrect metadata suggestions. Return ONLY JSON.",
            user=prompt,
            max_tokens=1024,
        )

        if not response or response == "__QUOTA_EXCEEDED__":
            return {"corrections": []}

        try:
            corrections = json.loads(response)
            return corrections
        except (json.JSONDecodeError, TypeError):
            print(f"[LLMReviewer] Could not parse response: {response[:200]}")
            return {"corrections": []}

    def apply_corrections(self, suggestion: DiscoverySuggestion, corrections: dict) -> DiscoverySuggestion:
        """Apply LLM corrections to the suggestion."""
        if not corrections or not corrections.get("corrections"):
            # Check for override fields
            pass

        # Apply accepted_values overrides
        av_overrides = corrections.get("accepted_values_override", {})
        for field_name, values in av_overrides.items():
            for f in suggestion.fields:
                if f.field_name == field_name:
                    f.accepted_values = values
                    if "accepted_values" in f.dq_rules:
                        f.dq_rules["accepted_values"] = values
                    f.reasoning.append(f"LLM REVIEW: accepted_values corrected to {values}")
                    break

        # Remove incorrect PII flags
        remove_pii = corrections.get("remove_pii", [])
        for field_name in remove_pii:
            for f in suggestion.fields:
                if f.field_name == field_name:
                    f.is_pii = False
                    f.classification = "Internal"
                    f.reasoning.append("LLM REVIEW: PII flag removed (not personally identifiable)")
                    break

        # Remove incorrect not_null
        remove_not_null = corrections.get("remove_not_null", [])
        for field_name in remove_not_null:
            for f in suggestion.fields:
                if f.field_name == field_name:
                    if "not_null" in f.dq_rules:
                        del f.dq_rules["not_null"]
                    f.reasoning.append("LLM REVIEW: not_null removed (field is nullable)")
                    break

        # Apply individual field corrections
        for correction in corrections.get("corrections", []):
            field_name = correction.get("field")
            fix = correction.get("fix")
            new_value = correction.get("new_value")

            for f in suggestion.fields:
                if f.field_name == field_name:
                    f.reasoning.append(f"LLM REVIEW: {fix}")
                    break

        return suggestion
