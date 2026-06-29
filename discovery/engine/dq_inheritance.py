"""DQ Inheritance Engine — Business-level DQ rules that cascade to all TDEs.

Principle: Define DQ once at the BDE level in the glossary.
Every table that uses that BDE automatically inherits its DQ rules.

Example:
  Glossary BDE "Credit Score" → DQ: range [300, 900], not_null
  Any table with a field linked to "Credit Score" → gets range + not_null applied

This replaces defining DQ per-table manually. You define a handful of rules
at the business term level, not thousands at the column level.
"""
import yaml
from pathlib import Path
from typing import Optional


class DQInheritanceEngine:
    """Resolves DQ rules from BDE definitions and applies to table configs."""

    def __init__(self, glossary_path: Optional[str] = None):
        self.bde_rules = {}  # term_id -> {dq_rules, classification, etc.}
        self._load_glossary(glossary_path)

    def _load_glossary(self, glossary_path: Optional[str] = None):
        """Load BDE DQ rules from the glossary."""
        if glossary_path is None:
            glossary_path = str(Path(__file__).parent.parent / "config" / "seed_glossary.yaml")

        try:
            with open(glossary_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            for term in data.get("business_terms", []):
                term_id = term["id"]
                self.bde_rules[term_id] = {
                    "name": term.get("name", ""),
                    "dq_rules": term.get("dq_rules", {}),
                    "classification": term.get("classification", "Internal"),
                    "is_pii": term.get("is_pii", False),
                    "data_type": term.get("data_type", "string"),
                    "reference_code_set": term.get("reference_code_set"),
                    "pattern": term.get("pattern"),
                }

            # Also load reference code sets for accepted_values
            self.reference_sets = data.get("reference_code_sets", {})

        except Exception as e:
            print(f"[DQInheritance] Failed to load glossary: {e}")

    def get_inherited_rules(self, term_id: str) -> dict:
        """Get DQ rules defined at the BDE level for a given term."""
        bde = self.bde_rules.get(term_id, {})
        rules = dict(bde.get("dq_rules", {}))

        # Add reference set as accepted_values if defined
        ref_set = bde.get("reference_code_set")
        if ref_set and ref_set in self.reference_sets:
            rules["accepted_values"] = self.reference_sets[ref_set]

        # Add format rule from pattern
        pattern = bde.get("pattern")
        if pattern:
            rules["format"] = pattern

        return rules

    def enrich_table_config(self, table_config: dict, field_to_bde: dict) -> dict:
        """Enrich a table config with inherited DQ rules from BDEs.

        Args:
            table_config: The pipeline config for a table
            field_to_bde: Mapping of field_name -> bde_term_id

        Returns:
            Updated table config with inherited DQ rules merged in
        """
        existing_dq = table_config.get("dq_rules", {})

        # Initialize DQ rule categories if not present
        not_null = list(existing_dq.get("not_null", []))
        positive = list(existing_dq.get("positive", []))
        unique = list(existing_dq.get("unique", []))
        accepted_values = dict(existing_dq.get("accepted_values", {}))
        ranges = dict(existing_dq.get("range", {}))
        formats = dict(existing_dq.get("format", {}))

        # For each field, inherit rules from its BDE
        for field_name, term_id in field_to_bde.items():
            inherited = self.get_inherited_rules(term_id)

            if inherited.get("not_null") and field_name not in not_null:
                not_null.append(field_name)

            if inherited.get("positive") and field_name not in positive:
                positive.append(field_name)

            if inherited.get("unique") and field_name not in unique:
                unique.append(field_name)

            if "accepted_values" in inherited and field_name not in accepted_values:
                accepted_values[field_name] = inherited["accepted_values"]

            if "range" in inherited and field_name not in ranges:
                ranges[field_name] = inherited["range"]

            if "format" in inherited and field_name not in formats:
                formats[field_name] = inherited["format"]

        # Rebuild DQ rules
        new_dq = {}
        if not_null:
            new_dq["not_null"] = not_null
        if positive:
            new_dq["positive"] = positive
        if unique:
            new_dq["unique"] = unique
        if accepted_values:
            new_dq["accepted_values"] = accepted_values
        if ranges:
            new_dq["range"] = ranges
        if formats:
            new_dq["format"] = formats

        table_config["dq_rules"] = new_dq
        return table_config

    def enrich_from_suggestion(self, table_config: dict, suggestion) -> dict:
        """Enrich table config using SD suggestion's field-to-BDE mappings."""
        field_to_bde = {}
        for field in suggestion.fields:
            if field.linked_term and field.confidence >= 0.5:
                field_to_bde[field.field_name] = field.linked_term

        if field_to_bde:
            table_config = self.enrich_table_config(table_config, field_to_bde)
            print(f"[DQInheritance] Enriched {len(field_to_bde)} fields with BDE-level DQ rules")

        return table_config

    def explain_inheritance(self, field_name: str, term_id: str) -> str:
        """Explain why a DQ rule was applied (for audit/transparency)."""
        bde = self.bde_rules.get(term_id, {})
        rules = self.get_inherited_rules(term_id)
        if not rules:
            return f"{field_name}: no inherited rules"

        parts = [f"{field_name} inherits from BDE '{bde.get('name', term_id)}':"]
        for rule, value in rules.items():
            parts.append(f"  - {rule}: {value}")
        return "\n".join(parts)
