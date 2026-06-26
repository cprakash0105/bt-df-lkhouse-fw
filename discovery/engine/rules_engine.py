"""Rules Engine — Deterministic pattern matching.
Catches obvious patterns before expensive embedding calls."""
import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RuleMatch:
    rule_type: str  # naming, pii, type, fk, business_app
    matched_rule: str
    information_type: Optional[str] = None
    is_pii: bool = False
    classification: Optional[str] = None
    is_key_candidate: bool = False
    confidence: float = 0.0
    dq_suggest: dict = field(default_factory=dict)
    business_application: Optional[str] = None
    fk_reference: Optional[str] = None


class RulesEngine:
    def __init__(self, rules_path: Optional[str] = None):
        if rules_path is None:
            rules_path = str(Path(__file__).parent.parent / "config" / "rules.yaml")
        with open(rules_path, "r", encoding="utf-8") as f:
            self.rules = yaml.safe_load(f)

    def match_field(self, field_name: str, data_type: str = "string") -> list[RuleMatch]:
        """Run all rules against a single field. Returns all matches."""
        matches = []
        matches.extend(self._match_naming(field_name))
        matches.extend(self._match_pii(field_name))
        matches.extend(self._match_type(data_type))
        matches.extend(self._match_fk(field_name))
        return matches

    def suggest_business_application(self, asset_name: str, field_names: list[str]) -> list[RuleMatch]:
        """Suggest which business application this dataset belongs to."""
        all_text = f"{asset_name} {' '.join(field_names)}".lower()
        all_words = set(all_text.replace("_", " ").replace("-", " ").split())
        matches = []

        for rule in self.rules.get("business_application_rules", []):
            keywords = set(rule["keywords"])
            overlap = all_words & keywords
            if overlap:
                score = len(overlap) / max(len(keywords), 1)
                confidence = min(score * rule.get("confidence", 0.8), 0.95)
                if confidence >= 0.3:
                    matches.append(RuleMatch(
                        rule_type="business_app",
                        matched_rule=f"keyword_match: {list(overlap)}",
                        business_application=rule["application"],
                        confidence=round(confidence, 2),
                    ))

        matches.sort(key=lambda x: x.confidence, reverse=True)
        return matches[:3]

    def _match_naming(self, field_name: str) -> list[RuleMatch]:
        matches = []
        field_lower = field_name.lower()

        for rule_name, rule in self.rules.get("naming_rules", {}).items():
            # Check suffixes
            for suffix in rule.get("suffixes", []):
                if field_lower.endswith(f"_{suffix}") or field_lower == suffix:
                    matches.append(RuleMatch(
                        rule_type="naming",
                        matched_rule=f"{rule_name}:suffix_{suffix}",
                        information_type=rule.get("information_type"),
                        is_key_candidate=rule.get("is_key_candidate", False),
                        confidence=0.85,
                        dq_suggest=rule.get("dq_suggest", {}),
                    ))
                    break

            # Check prefixes
            for prefix in rule.get("prefixes", []):
                if field_lower.startswith(prefix):
                    matches.append(RuleMatch(
                        rule_type="naming",
                        matched_rule=f"{rule_name}:prefix_{prefix}",
                        information_type=rule.get("information_type"),
                        confidence=0.80,
                        dq_suggest=rule.get("dq_suggest", {}),
                    ))
                    break

        return matches

    def _match_pii(self, field_name: str) -> list[RuleMatch]:
        matches = []
        field_lower = field_name.lower()

        for level, rule in self.rules.get("pii_rules", {}).items():
            for pattern in rule.get("patterns", []):
                regex = pattern.replace("*", ".*")
                if re.match(regex, field_lower):
                    matches.append(RuleMatch(
                        rule_type="pii",
                        matched_rule=f"{level}:{pattern}",
                        is_pii=True,
                        classification=rule.get("classification", "PII"),
                        confidence=rule.get("confidence", 0.5),
                    ))
                    break
            if matches and matches[-1].rule_type == "pii":
                break  # Take highest confidence PII match only

        return matches

    def _match_type(self, data_type: str) -> list[RuleMatch]:
        matches = []
        type_lower = data_type.lower()

        for rule in self.rules.get("type_rules", []):
            if type_lower in [t.lower() for t in rule.get("data_types", [])]:
                matches.append(RuleMatch(
                    rule_type="type",
                    matched_rule=f"type:{type_lower}",
                    information_type=rule.get("information_type"),
                    confidence=0.70,
                    dq_suggest=rule.get("dq_suggest", {}),
                ))

        return matches

    def _match_fk(self, field_name: str) -> list[RuleMatch]:
        matches = []
        field_lower = field_name.lower()

        for rule in self.rules.get("foreign_key_rules", {}).get("patterns", []):
            if field_lower == rule.get("field_pattern", "").lower():
                matches.append(RuleMatch(
                    rule_type="fk",
                    matched_rule=f"fk:{rule['field_pattern']}",
                    fk_reference=rule.get("likely_references"),
                    confidence=0.80,
                ))
            elif rule.get("heuristic") == "strip_suffix_match":
                # Generic: if field ends with _id, the table might be the prefix
                if field_lower.endswith("_id"):
                    table_guess = field_lower.replace("_id", "") + "s"
                    matches.append(RuleMatch(
                        rule_type="fk",
                        matched_rule=f"fk_heuristic:{field_lower}→{table_guess}",
                        fk_reference=f"{table_guess}.{field_lower}",
                        confidence=0.50,
                    ))

        return matches

    def get_schema_evolution_defaults(self, classification: str) -> dict:
        """Get default schema evolution governance based on classification."""
        defaults = self.rules.get("schema_evolution_defaults", {})
        if classification.lower() in ("pii", "phi"):
            return defaults.get("pii_fields", {})
        elif classification.lower() == "sensitive":
            return defaults.get("sensitive_fields", {})
        return defaults.get("standard_fields", {})
