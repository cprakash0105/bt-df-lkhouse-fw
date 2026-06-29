"""Suggester — Core orchestration engine.
Combines Rules Engine + Embedder + Knowledge Graph to produce discovery suggestions.
Supports two modes: Full Discovery (new asset) and Delta Discovery (schema change)."""
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone

from discovery.engine.knowledge_graph import KnowledgeGraph, BusinessTerm
from discovery.engine.rules_engine import RulesEngine
from discovery.engine.embedder import Embedder


@dataclass
class FieldSuggestion:
    field_name: str
    field_type: str
    linked_term: Optional[str] = None
    linked_term_name: Optional[str] = None
    confidence: float = 0.0
    information_type: Optional[str] = None
    classification: str = "Internal"
    is_pii: bool = False
    is_key_candidate: bool = False
    dq_rules: dict = field(default_factory=dict)
    reference_code_set: Optional[str] = None
    accepted_values: Optional[list] = None
    fk_reference: Optional[str] = None
    new_term_proposed: bool = False
    reasoning: list[str] = field(default_factory=list)


@dataclass
class DiscoverySuggestion:
    asset_name: str
    mode: str  # "full" or "delta"
    discovered_at: str = ""
    business_application: Optional[str] = None
    business_application_name: Optional[str] = None
    app_confidence: float = 0.0
    data_domain: Optional[str] = None
    fields: list[FieldSuggestion] = field(default_factory=list)
    new_term_proposals: list[dict] = field(default_factory=list)
    fk_candidates: list[dict] = field(default_factory=list)
    schema_evolution: dict = field(default_factory=dict)
    primary_key: Optional[str] = None

    def __post_init__(self):
        if not self.discovered_at:
            self.discovered_at = datetime.now(timezone.utc).isoformat()


class Suggester:
    """Orchestrates the full semantic discovery process."""

    def __init__(self, knowledge_graph: Optional[KnowledgeGraph] = None,
                 rules_engine: Optional[RulesEngine] = None,
                 embedder: Optional[Embedder] = None):
        self.kg = knowledge_graph or KnowledgeGraph()
        self.rules = rules_engine or RulesEngine()
        self.embedder = embedder or Embedder(mode="local")

        # Initialize embedder with knowledge graph terms
        term_dicts = [
            {
                "id": t.id, "name": t.name, "synonyms": t.synonyms,
                "data_type": t.data_type, "information_type": t.information_type,
                "domain": t.domain,
            }
            for t in self.kg.get_all_terms()
        ]
        self.embedder.initialize(term_dicts)

    def full_discovery(self, asset_definition: dict) -> DiscoverySuggestion:
        """Full Discovery — new dataset, never seen before.
        Input: asset definition (name, fields with name+type+description)."""
        asset_name = asset_definition.get("name", "unknown")
        fields = asset_definition.get("fields", [])
        field_names = [f.get("name", "") for f in fields]

        suggestion = DiscoverySuggestion(
            asset_name=asset_name,
            mode="full",
        )

        # Step 1: Suggest Business Application
        self._suggest_business_application(suggestion, asset_name, field_names)

        # Step 2: Suggest Domain
        self._suggest_domain(suggestion, asset_name, field_names)

        # Step 3: Process each field
        for f in fields:
            field_suggestion = self._process_field(
                f.get("name", ""), f.get("type", "string"), f.get("description", "")
            )
            suggestion.fields.append(field_suggestion)

        # Step 4: Identify primary key
        self._suggest_primary_key(suggestion)

        # Step 5: Identify foreign keys
        self._suggest_foreign_keys(suggestion)

        # Step 6: Collect new term proposals
        self._collect_new_term_proposals(suggestion)

        # Step 7: Default schema evolution governance
        self._suggest_schema_evolution(suggestion)

        return suggestion

    def delta_discovery(self, asset_name: str, new_fields: list[dict],
                        removed_fields: list[str] = None,
                        changed_fields: list[dict] = None) -> DiscoverySuggestion:
        """Delta Discovery — existing dataset with schema changes.
        Only processes the changed fields."""
        suggestion = DiscoverySuggestion(
            asset_name=asset_name,
            mode="delta",
        )

        # Process new fields
        for f in new_fields:
            field_suggestion = self._process_field(
                f.get("name", ""), f.get("type", "string"), f.get("description", "")
            )
            field_suggestion.reasoning.append("NEW FIELD - added in schema change")
            suggestion.fields.append(field_suggestion)

        # Flag removed fields
        if removed_fields:
            for field_name in removed_fields:
                fs = FieldSuggestion(
                    field_name=field_name, field_type="unknown",
                    reasoning=["REMOVED - field no longer in source schema"]
                )
                suggestion.fields.append(fs)

        # Process type changes
        if changed_fields:
            for f in changed_fields:
                fs = FieldSuggestion(
                    field_name=f.get("name", ""),
                    field_type=f.get("new_type", "string"),
                    reasoning=[f"TYPE CHANGED: {f.get('old_type')} -> {f.get('new_type')}"]
                )
                suggestion.fields.append(fs)

        self._collect_new_term_proposals(suggestion)
        return suggestion

    def _process_field(self, name: str, dtype: str, description: str) -> FieldSuggestion:
        """Process a single field through rules + embeddings + KG lookup."""
        fs = FieldSuggestion(field_name=name, field_type=dtype)

        # Layer 1: Knowledge Graph synonym match (fastest, highest confidence)
        kg_matches = self.kg.search_by_synonym(name)
        if kg_matches:
            best_term, confidence = kg_matches[0]
            fs.linked_term = best_term.id
            fs.linked_term_name = best_term.name
            fs.confidence = confidence
            fs.information_type = best_term.information_type
            fs.is_pii = best_term.is_pii
            fs.classification = best_term.classification if best_term.is_pii else "Internal"
            fs.is_key_candidate = best_term.is_key_candidate
            fs.dq_rules = dict(best_term.dq_rules)
            # Only set unique if the BDE says so AND it's likely a PK for this table
            # (customer_id is unique in customers table, but NOT in orders table)
            if fs.dq_rules.get("unique") and not best_term.is_key_candidate:
                del fs.dq_rules["unique"]
            if best_term.reference_code_set:
                fs.reference_code_set = best_term.reference_code_set
                fs.accepted_values = self.kg.get_reference_set(best_term.reference_code_set)
            fs.reasoning.append(f"KG synonym match -> '{best_term.name}' (confidence: {confidence})")

        # Layer 2: Rules Engine (deterministic patterns)
        rule_matches = self.rules.match_field(name, dtype)
        for rm in rule_matches:
            if rm.rule_type == "naming":
                if not fs.information_type:
                    fs.information_type = rm.information_type
                # Always apply key candidate from naming rules (overrides KG)
                if rm.is_key_candidate:
                    fs.is_key_candidate = True
                    fs.reasoning.append(f"Rule: {rm.matched_rule} -> key candidate")
                elif not fs.information_type:
                    fs.reasoning.append(f"Rule: {rm.matched_rule} -> {rm.information_type}")
            if rm.rule_type == "pii":
                fs.is_pii = True
                fs.classification = rm.classification or "PII"
                fs.reasoning.append(f"PII rule: {rm.matched_rule} (conf: {rm.confidence})")
            if rm.rule_type == "fk":
                fs.fk_reference = rm.fk_reference
                fs.reasoning.append(f"FK candidate: {rm.fk_reference}")

            # Merge DQ suggestions from rules
            for k, v in rm.dq_suggest.items():
                if k not in fs.dq_rules:
                    fs.dq_rules[k] = v

        # Layer 3: Embedding search (semantic — catches what rules miss)
        if not fs.linked_term or fs.confidence < 0.7:
            embedding_matches = self.embedder.find_similar_terms(name, dtype, description)
            if embedding_matches:
                best = embedding_matches[0]
                if best.similarity > (fs.confidence or 0):
                    # Embedding found better match
                    term = self.kg.terms.get(best.term_id)
                    if term:
                        fs.linked_term = term.id
                        fs.linked_term_name = term.name
                        fs.confidence = best.similarity
                        fs.information_type = fs.information_type or term.information_type
                        fs.is_pii = fs.is_pii or term.is_pii
                        if term.is_pii:
                            fs.classification = term.classification
                        fs.dq_rules = {**term.dq_rules, **fs.dq_rules}
                        fs.reasoning.append(
                            f"Embedding match -> '{term.name}' (similarity: {best.similarity})"
                        )

        # If NO match at all → propose new term
        if not fs.linked_term or fs.confidence < 0.4:
            fs.new_term_proposed = True
            fs.reasoning.append("NO MATCH - propose creating a new Business Term")

        return fs

    def _suggest_business_application(self, suggestion: DiscoverySuggestion,
                                       asset_name: str, field_names: list[str]):
        """Suggest which business application this dataset belongs to."""
        # Try rules engine first
        rule_matches = self.rules.suggest_business_application(asset_name, field_names)
        if rule_matches:
            best = rule_matches[0]
            app = self.kg.applications.get(best.business_application)
            if app:
                suggestion.business_application = app.id
                suggestion.business_application_name = app.name
                suggestion.app_confidence = best.confidence

        # Also try KG keyword matching
        kg_matches = self.kg.search_by_domain_keywords(
            f"{asset_name} {' '.join(field_names)}"
        )
        if kg_matches:
            best_app, conf = kg_matches[0]
            if conf > suggestion.app_confidence:
                suggestion.business_application = best_app.id
                suggestion.business_application_name = best_app.name
                suggestion.app_confidence = conf

    def _suggest_domain(self, suggestion: DiscoverySuggestion,
                        asset_name: str, field_names: list[str]):
        """Infer data domain from field composition."""
        domain_scores: dict[str, int] = {}
        all_text = f"{asset_name} {' '.join(field_names)}".lower()

        for domain in self.kg.domains.values():
            # Check how many terms from this domain match our fields
            domain_terms = self.kg.get_terms_by_domain(domain.id)
            for term in domain_terms:
                for syn in term.synonyms:
                    if syn.lower() in all_text:
                        domain_scores[domain.id] = domain_scores.get(domain.id, 0) + 1

        if domain_scores:
            best_domain = max(domain_scores, key=domain_scores.get)
            suggestion.data_domain = best_domain

    def _suggest_primary_key(self, suggestion: DiscoverySuggestion):
        """Identify the most likely primary key field."""
        candidates = [f for f in suggestion.fields if f.is_key_candidate]
        if not candidates:
            return

        asset_name = suggestion.asset_name.lower()
        # Strip common prefixes/suffixes from asset name for matching
        asset_base = asset_name.replace("_data", "").replace("_feed", "").replace("_extract", "")
        asset_base = asset_base.replace("_transactions", "").replace("_portfolio", "")
        asset_base = asset_base.replace("_master", "").replace("_details", "")
        # Also get individual words from the asset name
        asset_words = set(asset_name.replace("_", " ").split())

        # Priority 1: field that exactly matches {something}_id where {something}
        # relates to the asset name (e.g., loan_portfolio -> loan_id, payment_transactions -> transaction_id)
        for f in candidates:
            fname = f.field_name.lower()
            if fname.endswith("_id"):
                prefix = fname[:-3]  # strip _id
                if prefix in asset_base or asset_base.startswith(prefix) or prefix in asset_words:
                    suggestion.primary_key = f.field_name
                    return

        # Priority 2: first field ending in _id that is NOT customer_id
        # (customer_id is usually an FK unless table is about customers)
        is_customer_table = any(w in asset_words for w in ["customer", "cust", "client", "subscriber", "kyc"])
        if not is_customer_table:
            non_customer_ids = [f for f in candidates
                               if f.field_name.lower().endswith("_id")
                               and f.field_name.lower() != "customer_id"]
            if non_customer_ids:
                suggestion.primary_key = non_customer_ids[0].field_name
                return

        # Priority 3: first field in the definition that is a key candidate
        # (position matters — first field is usually PK by convention)
        field_order = [f.field_name for f in suggestion.fields]
        candidates.sort(key=lambda f: field_order.index(f.field_name))
        suggestion.primary_key = candidates[0].field_name

    def _suggest_foreign_keys(self, suggestion: DiscoverySuggestion):
        """Collect FK candidates."""
        for f in suggestion.fields:
            if f.fk_reference and f.field_name != suggestion.primary_key:
                suggestion.fk_candidates.append({
                    "field": f.field_name,
                    "references": f.fk_reference,
                    "confidence": 0.6,
                })

    def _collect_new_term_proposals(self, suggestion: DiscoverySuggestion):
        """Collect fields that need new business terms."""
        for f in suggestion.fields:
            if f.new_term_proposed:
                suggestion.new_term_proposals.append({
                    "field_name": f.field_name,
                    "suggested_term_name": f.field_name.replace("_", " ").title(),
                    "suggested_domain": suggestion.data_domain or "unknown",
                    "suggested_type": f.field_type,
                    "suggested_info_type": f.information_type or "Dimension",
                })

    def _suggest_schema_evolution(self, suggestion: DiscoverySuggestion):
        """Set default schema evolution governance based on highest classification."""
        has_pii = any(f.is_pii for f in suggestion.fields)
        has_sensitive = any(f.classification == "Sensitive" for f in suggestion.fields)

        if has_pii:
            classification = "PII"
        elif has_sensitive:
            classification = "Sensitive"
        else:
            classification = "Internal"

        suggestion.schema_evolution = self.rules.get_schema_evolution_defaults(classification)
