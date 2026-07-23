"""LLM Reviewer — Validates and corrects SD suggestions in one call per dataset.
Catches errors the rules engine makes: wrong accepted_values, false PII, mismatched terms.
Runs AFTER the deterministic engine, BEFORE showing results to steward.

Fixes applied:
- Profile stats (null%, distinct%, numeric range, fingerprint, patterns) now included per field
- Confidence gate: only fields with confidence >= 0.5 sent for per-field LLM validation (cost optimisation)
- Cross-field consistency check added to dataset-level review prompt
- Stage 1 (per-field) and Stage 2 (dataset-level) are now separate, matching the designed flow
"""
import json
from typing import Optional
from discovery.engine.llm_client import get_llm
from discovery.engine.suggester import DiscoverySuggestion

# Confidence threshold — only validate matched fields above this (cost optimisation)
VALIDATION_THRESHOLD = 0.5

# Stage 1a: per-field validation prompt (for fields WITH a BDE match)
FIELD_VALIDATION_PROMPT = """You are validating a single field's BDE (Business Data Element) match.
Dataset: {dataset_name} | Domain: {domain}

Field: {field_name} (type: {field_type})
Matched BDE: {matched_term} (confidence: {confidence:.0%})
Current flags: PII={is_pii}, is_key={is_key}
Current DQ rules: {dq_rules}

Profile evidence from actual data:
{profile_evidence}

Validate this match. Return ONLY JSON:
{{"verdict": "confirm|correct|reject", "reason": "one line", "corrections": {{"is_pii": true/false, "remove_not_null": true/false, "accepted_values": [...] or null, "matched_term": "corrected_bde_id or null"}}}}

- confirm: match is correct, no changes needed
- correct: match is right but some flags/rules need fixing
- reject: BDE match is wrong, field should be unlinked"""

# Stage 1b: new term suggestion prompt (for fields with NO BDE match)
NEW_TERM_PROMPT = """You are a data steward naming a new Business Data Element (BDE) for a field that has no match in the catalog.
Dataset: {dataset_name} | Domain: {domain}

Field: {field_name} (type: {field_type})

Profile evidence from actual data:
{profile_evidence}

Suggest the correct BDE for this field. Return ONLY JSON:
{{"suggested_term_name": "Human Readable Name", "suggested_domain": "domain_id", "information_type": "Identifier|Measure|Temporal|Reference|Dimension", "is_pii": false, "reason": "one line explaining what this field represents"}}

Rules:
- suggested_term_name must be a proper business name (e.g. "Warehouse ID", "Movement Type", "Operator ID")
- suggested_domain must be one of: {available_domains}
- Use the actual distinct values and profile stats to infer what the field represents"""

# Stage 2: dataset-level review prompt (cross-field consistency)
DATASET_REVIEW_PROMPT = """Review this data discovery result for cross-field consistency. Fix any errors. Return ONLY valid JSON.

Dataset: {dataset_name}
Domain: {domain}
Business Application: {business_app}
Primary Key: {primary_key}

All field suggestions (including low-confidence fields not individually validated):
{suggestions_json}

Check and fix:
1. Cross-field consistency: Do accepted_values make sense together? (e.g. if status field has loan values, payment_method should have payment values not retail values)
2. Domain alignment: Are all accepted_values consistent with the domain ({domain})?
3. PII: Any remaining incorrect PII flags? Amounts, dates, IDs are NOT PII. Names, phone, email, aadhaar, PAN ARE PII.
4. not_null reasonableness: Optional fields (payment_date, promo_code, notes) should not be not_null.
5. Primary key: Is {primary_key} the correct PK for this dataset?

Return JSON with ONLY the corrections needed:
{{"corrections": [{{"field": "field_name", "fix": "description", "old_value": "...", "new_value": "..."}}], "accepted_values_override": {{"field_name": ["val1", "val2"]}}, "remove_pii": ["field_names"], "remove_not_null": ["field_names"], "primary_key_override": "field_name or null"}}

If everything looks correct, return: {{"corrections": []}}"""


def _build_profile_evidence(field_name: str, profile) -> str:
    """Extract statistical evidence for a single field from the DatasetProfile."""
    if not profile or not profile.fields:
        return "No profile data available."

    fp = next((f for f in profile.fields if f.name == field_name), None)
    if not fp:
        return "No profile data for this field."

    lines = [
        f"- null%: {fp.null_pct:.0%}",
        f"- distinct values: {fp.distinct_count} ({fp.distinct_pct:.0%} of rows)",
        f"- inferred type: {fp.inferred_type}",
    ]

    # Numeric stats
    if fp.min_val is not None:
        lines.append(f"- range: [{fp.min_val}, {fp.max_val}], mean: {fp.mean_val}")

    # String length
    if fp.min_length is not None:
        lines.append(f"- string length: {fp.min_length}–{fp.max_length} chars")

    # PII patterns detected in actual values
    if fp.detected_patterns:
        lines.append(f"- detected patterns in values: {fp.detected_patterns}")

    # Fingerprint match against reference code sets
    if fp.fingerprint_set and fp.fingerprint_ratio > 0:
        lines.append(f"- fingerprint: {fp.fingerprint_ratio:.0%} of values match reference set '{fp.fingerprint_set}'")

    # Actual distinct values (for low-cardinality / reference fields)
    if fp.distinct_values:
        lines.append(f"- actual distinct values: {fp.distinct_values}")

    # Composite confidence signal breakdown
    if fp.signals:
        lines.append(
            f"- signal breakdown: keyword={fp.signals.keyword_score:.0%}, "
            f"pattern={fp.signals.pattern_score:.0%}, "
            f"fingerprint={fp.signals.fingerprint_score:.0%}, "
            f"stat={fp.signals.stat_score:.0%} → composite={fp.signals.composite_score:.0%}"
        )

    return "\n".join(lines)


class LLMReviewer:
    """Uses LLM to review and correct SD suggestions.

    Stage 1: Per-field validation for fields with confidence >= VALIDATION_THRESHOLD.
             LLM confirms, corrects, or rejects each BDE match using profile evidence.
    Stage 2: Dataset-level cross-field consistency review across all fields.
    """

    def review(self, suggestion: DiscoverySuggestion) -> dict:
        """Run Stage 1 (per-field) then Stage 2 (dataset-level). Returns merged corrections."""
        llm = get_llm()
        profile = getattr(suggestion, "profile", None)

        stage1_corrections = self._stage1_per_field(llm, suggestion, profile)
        stage2_corrections = self._stage2_dataset_level(llm, suggestion)

        # Merge: stage1 per-field verdicts take precedence for individual fields,
        # stage2 fills in cross-field and low-confidence field corrections
        return self._merge_corrections(stage1_corrections, stage2_corrections)

    def _stage1_per_field(self, llm, suggestion: DiscoverySuggestion, profile) -> dict:
        """Stage 1a: validate matched fields (confidence >= threshold).
        Stage 1b: ask LLM to suggest BDE name for unmatched fields."""
        field_verdicts = {}  # field_name -> verdict dict
        new_term_suggestions = {}  # field_name -> suggested term dict

        available_domains = ", ".join(suggestion._kg_domains) if hasattr(suggestion, "_kg_domains") else "supply_chain, retail, finance, customer, product, order"

        for fs in suggestion.fields:
            profile_evidence = _build_profile_evidence(fs.field_name, profile)

            # Stage 1b — unmatched field OR low-confidence match below threshold: ask LLM to name the BDE
            if fs.new_term_proposed or (fs.linked_term and fs.confidence < VALIDATION_THRESHOLD):
                prompt = NEW_TERM_PROMPT.format(
                    dataset_name=suggestion.asset_name,
                    domain=suggestion.data_domain or "unknown",
                    field_name=fs.field_name,
                    field_type=fs.field_type,
                    profile_evidence=profile_evidence,
                    available_domains=available_domains,
                )
                response = llm.generate(
                    system="You are a data steward naming new Business Data Elements. Return ONLY JSON.",
                    user=prompt,
                    max_tokens=200,
                    temperature=0.0,
                )
                if response and response != "__QUOTA_EXCEEDED__":
                    try:
                        suggestion_dict = json.loads(response)
                        new_term_suggestions[fs.field_name] = suggestion_dict
                        term_name = suggestion_dict.get("suggested_term_name", "")
                        reason = suggestion_dict.get("reason", "")
                        fs.reasoning.append(f"LLM STAGE1 💡: suggested BDE '{term_name}' — {reason}")
                    except (json.JSONDecodeError, TypeError):
                        print(f"[LLMReviewer] Stage1b parse failed for '{fs.field_name}': {response[:100]}")
                continue

            # Stage 1a — matched field: validate if confidence >= threshold
            if not fs.linked_term or fs.confidence < VALIDATION_THRESHOLD:
                continue

            prompt = FIELD_VALIDATION_PROMPT.format(
                dataset_name=suggestion.asset_name,
                domain=suggestion.data_domain or "unknown",
                field_name=fs.field_name,
                field_type=fs.field_type,
                matched_term=fs.linked_term_name or fs.linked_term,
                confidence=fs.confidence,
                is_pii=fs.is_pii,
                is_key=fs.is_key_candidate,
                dq_rules=json.dumps(fs.dq_rules),
                profile_evidence=profile_evidence,
            )

            response = llm.generate(
                system="You validate data field BDE matches using statistical profile evidence. Return ONLY JSON.",
                user=prompt,
                max_tokens=300,
                temperature=0.0,
            )

            if not response or response == "__QUOTA_EXCEEDED__":
                continue

            try:
                verdict = json.loads(response)
                field_verdicts[fs.field_name] = verdict
                v = verdict.get("verdict", "confirm")
                reason = verdict.get("reason", "")
                icon = "✓" if v == "confirm" else "⚠️" if v == "correct" else "❌"
                fs.reasoning.append(f"LLM STAGE1 {icon}: {reason}")
            except (json.JSONDecodeError, TypeError):
                print(f"[LLMReviewer] Stage1 parse failed for '{fs.field_name}': {response[:100]}")

        return {"field_verdicts": field_verdicts, "new_term_suggestions": new_term_suggestions}

    def _stage2_dataset_level(self, llm, suggestion: DiscoverySuggestion) -> dict:
        """Dataset-level cross-field consistency review."""
        suggestions_summary = []
        for f in suggestion.fields:
            entry = {
                "field": f.field_name,
                "type": f.field_type,
                "matched_term": f.linked_term_name,
                "confidence": round(f.confidence, 2),
                "is_pii": f.is_pii,
                "dq_rules": f.dq_rules,
            }
            if f.accepted_values:
                entry["accepted_values"] = f.accepted_values
            suggestions_summary.append(entry)

        prompt = DATASET_REVIEW_PROMPT.format(
            dataset_name=suggestion.asset_name,
            domain=suggestion.data_domain or "unknown",
            business_app=suggestion.business_application_name or "unknown",
            primary_key=suggestion.primary_key or "unknown",
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
            return json.loads(response)
        except (json.JSONDecodeError, TypeError):
            print(f"[LLMReviewer] Stage2 parse failed: {response[:200]}")
            return {"corrections": []}

    def _merge_corrections(self, stage1: dict, stage2: dict) -> dict:
        """Merge Stage 1 per-field verdicts into Stage 2 dataset-level corrections."""
        merged = {
            "corrections": list(stage2.get("corrections", [])),
            "accepted_values_override": dict(stage2.get("accepted_values_override", {})),
            "remove_pii": list(stage2.get("remove_pii", [])),
            "remove_not_null": list(stage2.get("remove_not_null", [])),
            "primary_key_override": stage2.get("primary_key_override"),
            "field_verdicts": stage1.get("field_verdicts", {}),
            "new_term_suggestions": stage1.get("new_term_suggestions", {}),
        }

        # Promote Stage 1 per-field corrections into the merged structure
        for field_name, verdict in stage1.get("field_verdicts", {}).items():
            v = verdict.get("verdict", "confirm")
            corrections = verdict.get("corrections", {})
            if not corrections:
                continue

            if v == "reject":
                merged["corrections"].append({
                    "field": field_name,
                    "fix": "BDE match rejected by Stage 1 validation",
                    "old_value": "linked",
                    "new_value": "unlinked",
                })

            if v in ("correct", "reject"):
                if corrections.get("remove_not_null") and field_name not in merged["remove_not_null"]:
                    merged["remove_not_null"].append(field_name)
                if corrections.get("is_pii") is False and field_name not in merged["remove_pii"]:
                    merged["remove_pii"].append(field_name)
                if corrections.get("accepted_values"):
                    merged["accepted_values_override"][field_name] = corrections["accepted_values"]

        return merged

    def apply_corrections(self, suggestion: DiscoverySuggestion, corrections: dict) -> DiscoverySuggestion:
        """Apply merged corrections from Stage 1 + Stage 2 to the suggestion."""
        field_map = {f.field_name: f for f in suggestion.fields}

        # Apply accepted_values overrides
        for field_name, values in corrections.get("accepted_values_override", {}).items():
            f = field_map.get(field_name)
            if f:
                f.accepted_values = values
                f.dq_rules["accepted_values"] = values
                f.reasoning.append(f"LLM REVIEW: accepted_values corrected to {values}")

        # Remove incorrect PII flags
        for field_name in corrections.get("remove_pii", []):
            f = field_map.get(field_name)
            if f:
                f.is_pii = False
                f.classification = "Internal"
                f.reasoning.append("LLM REVIEW: PII flag removed (not personally identifiable)")

        # Remove incorrect not_null
        for field_name in corrections.get("remove_not_null", []):
            f = field_map.get(field_name)
            if f and "not_null" in f.dq_rules:
                del f.dq_rules["not_null"]
                f.reasoning.append("LLM REVIEW: not_null removed (field is nullable)")

        # Primary key override
        pk_override = corrections.get("primary_key_override")
        if pk_override and pk_override in field_map:
            suggestion.primary_key = pk_override
            suggestion.fields[0].reasoning.append(f"LLM REVIEW: primary_key overridden to '{pk_override}'")

        # Apply Stage 1 reject verdicts — unlink the BDE match
        for field_name, verdict in corrections.get("field_verdicts", {}).items():
            if verdict.get("verdict") == "reject":
                f = field_map.get(field_name)
                if f:
                    f.linked_term = None
                    f.linked_term_name = None
                    f.confidence = 0.0
                    f.new_term_proposed = True

        # Apply Stage 1b new term suggestions — enrich new_term_proposals
        new_term_suggestions = corrections.get("new_term_suggestions", {})
        for proposal in suggestion.new_term_proposals:
            field_name = proposal["field_name"]
            llm_suggestion = new_term_suggestions.get(field_name)
            if llm_suggestion:
                proposal["suggested_term_name"] = llm_suggestion.get("suggested_term_name", proposal["suggested_term_name"])
                proposal["suggested_domain"] = llm_suggestion.get("suggested_domain", proposal["suggested_domain"])
                proposal["suggested_info_type"] = llm_suggestion.get("information_type", proposal["suggested_info_type"])
                proposal["is_pii"] = llm_suggestion.get("is_pii", False)
                proposal["llm_reason"] = llm_suggestion.get("reason", "")

        # Apply individual field corrections from Stage 2
        for correction in corrections.get("corrections", []):
            field_name = correction.get("field")
            fix = correction.get("fix", "")
            f = field_map.get(field_name)
            if f:
                f.reasoning.append(f"LLM REVIEW: {fix}")

        return suggestion
