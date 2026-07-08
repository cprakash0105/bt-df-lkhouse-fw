"""Suggester — Core orchestration engine.
Combines Rules Engine + Embedder + Knowledge Graph to produce discovery suggestions.
Supports two modes: Full Discovery (new asset) and Delta Discovery (schema change)."""
import sys
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from logger import get_logger
_log = get_logger("discovery.suggester")

from discovery.engine.knowledge_graph import KnowledgeGraph, BusinessTerm
from discovery.engine.rules_engine import RulesEngine
from discovery.engine.embedder import Embedder
from discovery.engine.discovery_profiler import DiscoveryProfiler, DatasetProfile, FieldProfile, FieldSignals as DPFieldSignals


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
                 embedder: Optional[Embedder] = None,
                 profiler: Optional[DiscoveryProfiler] = None):
        self.kg = knowledge_graph or KnowledgeGraph()
        self.rules = rules_engine or RulesEngine()
        self.embedder = embedder or Embedder(mode="local")
        self.profiler = profiler or DiscoveryProfiler()

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

        _log.info("Full discovery started", asset_name=asset_name, field_count=len(fields))

        suggestion = DiscoverySuggestion(
            asset_name=asset_name,
            mode="full",
        )

        # Step 0: Try to auto-profile from GCS landing data
        profile = self._auto_profile(asset_name)

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

        # Step 4: Enhance with profile evidence (boost confidence, detect PII, fix types)
        if profile:
            self._enhance_with_profile(suggestion, profile)

        # Step 5: Identify primary key
        self._suggest_primary_key(suggestion)

        # Step 6: Identify foreign keys
        self._suggest_foreign_keys(suggestion)

        # Step 7: Collect new term proposals
        self._collect_new_term_proposals(suggestion)

        # Step 8: Default schema evolution governance
        self._suggest_schema_evolution(suggestion)

        matched = sum(1 for f in suggestion.fields if f.linked_term)
        _log.info("Full discovery complete", asset_name=asset_name,
                  fields_matched=matched, fields_total=len(suggestion.fields),
                  primary_key=suggestion.primary_key,
                  business_app=suggestion.business_application_name,
                  domain=suggestion.data_domain)

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
        """LLM-first: ask LLM to classify BA and domain together."""
        llm_result = self._llm_classify(asset_name, field_names)
        if llm_result:
            ba_id = llm_result.get("business_application")
            domain_id = llm_result.get("data_domain")
            # Match BA
            if ba_id:
                app = self.kg.applications.get(ba_id)
                if not app:
                    # LLM returned a name, try to find by name
                    for a in self.kg.applications.values():
                        if a.name.lower() == ba_id.lower() or a.id == ba_id.lower().replace(" ", "_").replace("&", ""):
                            app = a
                            break
                if app:
                    suggestion.business_application = app.id
                    suggestion.business_application_name = app.name
                    suggestion.app_confidence = 0.85
                else:
                    # LLM suggested something not in glossary — use it as-is
                    suggestion.business_application = ba_id.lower().replace(" ", "_")
                    suggestion.business_application_name = ba_id
                    suggestion.app_confidence = 0.80
            # Store domain for _suggest_domain to use
            if domain_id:
                self._llm_domain_hint = domain_id
            return

        # Fallback: keyword matching
        rule_matches = self.rules.suggest_business_application(asset_name, field_names)
        if rule_matches:
            best = rule_matches[0]
            app = self.kg.applications.get(best.business_application)
            if app:
                suggestion.business_application = app.id
                suggestion.business_application_name = app.name
                suggestion.app_confidence = best.confidence

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
        """Use LLM hint if available, else keyword fallback."""
        # Check if LLM already classified
        hint = getattr(self, "_llm_domain_hint", None)
        if hint:
            # Try to match to existing domain
            for d in self.kg.domains.values():
                if d.id == hint.lower().replace(" ", "_") or d.name.lower() == hint.lower():
                    suggestion.data_domain = d.id
                    self._llm_domain_hint = None
                    return
            # LLM suggested new domain — use it
            suggestion.data_domain = hint.lower().replace(" ", "_")
            self._llm_domain_hint = None
            return

        # Fallback: keyword scoring
        domain_scores: dict[str, int] = {}
        all_text = f"{asset_name} {' '.join(field_names)}".lower()
        for domain in self.kg.domains.values():
            domain_terms = self.kg.get_terms_by_domain(domain.id)
            for term in domain_terms:
                for syn in term.synonyms:
                    if syn.lower() in all_text:
                        domain_scores[domain.id] = domain_scores.get(domain.id, 0) + 1
        if domain_scores:
            best_domain = max(domain_scores, key=domain_scores.get)
            suggestion.data_domain = best_domain

    def _llm_classify(self, asset_name: str, field_names: list[str]) -> Optional[dict]:
        """Ask LLM to classify dataset into BA + domain. Returns dict or None."""
        try:
            from discovery.engine.llm_client import get_llm
            import json as _json

            apps = [f"{a.id}: {a.name}" for a in self.kg.applications.values()]
            domains = [f"{d.id}: {d.name}" for d in self.kg.domains.values()]

            prompt = (
                f"Dataset: {asset_name}\n"
                f"Fields: {', '.join(field_names[:20])}\n\n"
                f"Available business applications:\n{chr(10).join(apps)}\n\n"
                f"Available data domains:\n{chr(10).join(domains)}\n\n"
                f"Pick the best business_application and data_domain for this dataset. "
                f"If none fit well, suggest a new one.\n"
                f"Return ONLY JSON: {{\"business_application\": \"id\", \"data_domain\": \"id\"}}"
            )

            resp = get_llm().generate(
                system="You classify datasets into business applications and data domains. Return only valid JSON.",
                user=prompt,
                max_tokens=150,
                temperature=0.0,
            )
            if resp and resp != "__QUOTA_EXCEEDED__":
                return _json.loads(resp)
        except Exception as e:
            print(f"[Suggester] LLM classify failed: {e}")
        return None

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
        """Collect fields that need new business terms.
        Skip generic/reserved words that don't deserve a BDE."""
        # Fields too generic to become BDEs
        SKIP_TERMS = {
            "description", "name", "type", "status", "category", "sub_category",
            "subcategory", "comments", "notes", "remarks", "details", "info",
            "data", "value", "code", "text", "message", "content", "body",
            "assigned_to", "created_by", "updated_by", "modified_by",
            "created_at", "updated_at", "modified_at", "deleted_at",
            "is_active", "is_deleted", "is_enabled", "flag", "indicator",
            "resolution_date", "start_date", "end_date", "effective_date",
            "row_id", "id", "seq", "sequence", "index",
        }

        for f in suggestion.fields:
            if f.new_term_proposed:
                # Skip generic fields
                if f.field_name.lower() in SKIP_TERMS:
                    f.new_term_proposed = False
                    f.reasoning.append(f"SKIP: '{f.field_name}' is too generic for a BDE")
                    continue
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

    def _auto_profile(self, asset_name: str) -> Optional[DatasetProfile]:
        """Call the Profiler Service to profile landing data.
        Falls back to local lightweight profiler if service unavailable.
        Checks both default and EastSide buckets."""
        import os
        import json
        import urllib.request

        profiler_url = os.environ.get("PROFILER_SERVICE_URL", "")

        # Strategy 1: Call the profiler service (Dataproc)
        if profiler_url:
            try:
                url = f"{profiler_url}/profile"
                payload = json.dumps({"dataset_name": asset_name}).encode()
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=120) as resp:
                    result = json.loads(resp.read().decode())

                if result and result.get("fields"):
                    profile = self._service_response_to_profile(result)
                    print(f"[Suggester] Profiler service returned: {result['row_count']} rows, {result['column_count']} cols ({result['duration_seconds']}s)")
                    return profile
            except Exception as e:
                print(f"[Suggester] Profiler service call failed: {e}, falling back to local")

        # Strategy 2: Fallback to local profiler (try both buckets)
        buckets = [
            os.environ.get("CONFIG_BUCKET", "bt-df-lkhouse-lakehouse"),
            "eastside-lakehouse",
        ]
        for bucket in buckets:
            try:
                profile = self.profiler.profile_from_gcs(asset_name, bucket_name=bucket)
                if profile and profile.fields:
                    self.profiler.persist_profile(profile, bucket_name=bucket)
                    print(f"[Suggester] Local profiled {asset_name} from {bucket}: {profile.row_count} rows")
                    return profile
            except Exception as e:
                print(f"[Suggester] Local profile failed for {bucket}: {e}")
        return None

    def _service_response_to_profile(self, result: dict) -> DatasetProfile:
        """Convert profiler service JSON response to DatasetProfile."""
        ds = DatasetProfile(
            dataset_name=result["dataset_name"],
            row_count=result["row_count"],
            column_count=result["column_count"],
            source_path=result.get("source_path", ""),
        )
        for f in result["fields"]:
            signals = f.get("signals", {})
            fp = FieldProfile(
                name=f["name"],
                row_count=result["row_count"],
                null_pct=f["null_pct"],
                distinct_count=f["distinct_count"],
                distinct_pct=f["distinct_pct"],
                inferred_type=f["inferred_type"],
                is_pii=f["is_pii"],
                is_key=f["is_key"],
                is_reference=f["is_reference"],
                detected_patterns=f.get("detected_patterns", []),
                distinct_values=f.get("distinct_values"),
                fingerprint_set=signals.get("fingerprint_set"),
                fingerprint_ratio=signals.get("fingerprint_score", 0),
                fingerprint_unmatched=signals.get("fingerprint_unmatched", []),
            )
            if f.get("stats"):
                fp.min_val = str(f["stats"].get("min", ""))
                fp.max_val = str(f["stats"].get("max", ""))
                fp.mean_val = f["stats"].get("mean")
            fp.signals = DPFieldSignals(
                field_name=f["name"],
                keyword_score=signals.get("keyword_score", 0),
                keyword_match=signals.get("keyword_match"),
                pattern_score=signals.get("pattern_score", 0),
                detected_pattern=signals.get("detected_pattern"),
                fingerprint_score=signals.get("fingerprint_score", 0),
                fingerprint_set=signals.get("fingerprint_set"),
                stat_score=signals.get("stat_score", 0),
                composite_score=signals.get("composite_score", 0),
                information_type=signals.get("information_type", "Dimension"),
            )
            ds.fields.append(fp)
        return ds

    # BDE patterns: if a BDE implies a specific data pattern, map it here
    _BDE_EXPECTED_PATTERNS = {
        "customer_email": {"patterns": ["email"], "type": "string"},
        "customer_phone": {"patterns": ["phone"], "type": "string"},
        "pan_number": {"patterns": ["pan"], "type": "string"},
        "aadhaar_number": {"patterns": ["aadhaar"], "type": "string"},
        "credit_score": {"type": "integer", "min_distinct_pct": 0.05},
        "emi_amount": {"type": "decimal"},
        "transaction_amount": {"type": "decimal"},
        "premium_amount": {"type": "decimal"},
        "product_price": {"type": "decimal"},
    }

    def _enhance_with_profile(self, suggestion: DiscoverySuggestion, profile: DatasetProfile):
        """Enhance field suggestions with profiling evidence from actual data."""
        profile_map = {fp.name: fp for fp in profile.fields}

        for fs in suggestion.fields:
            fp = profile_map.get(fs.field_name)
            if not fp:
                continue

            # --- Contradiction check: reject BDE match if data doesn't fit ---
            if fs.linked_term and fs.confidence < 0.8:
                rejected = self._check_profile_contradiction(fs, fp)
                if rejected:
                    continue  # skip further enhancement, field is now unlinked

            # Store signal breakdown for UI display
            if fp.signals:
                fs.reasoning.append(
                    f"PROFILE SIGNALS: keyword={fp.signals.keyword_score:.0%}, "
                    f"pattern={fp.signals.pattern_score:.0%}, "
                    f"fingerprint={fp.signals.fingerprint_score:.0%}, "
                    f"stat={fp.signals.stat_score:.0%} → "
                    f"composite={fp.signals.composite_score:.0%}"
                )

            # PII detection from values
            if fp.is_pii and not fs.is_pii:
                fs.is_pii = True
                fs.classification = "PII"
                fs.reasoning.append(
                    f"PROFILE: PII detected from values (pattern: {', '.join(fp.detected_patterns)})"
                )

            # Key detection from cardinality
            if fp.is_key and not fs.is_key_candidate:
                fs.is_key_candidate = True
                fs.reasoning.append(
                    f"PROFILE: Likely key (cardinality: {fp.distinct_pct:.0%}, nulls: {fp.null_pct:.0%})"
                )

            # Fingerprint → override wrong accepted_values or set new ones
            if fp.fingerprint_set and fp.fingerprint_ratio >= 0.5:
                # High fingerprint match → use the reference set from glossary
                ref_values = self.profiler.reference_sets.get(fp.fingerprint_set, [])
                if ref_values:
                    if fs.accepted_values and not self._values_overlap(fs.accepted_values, fp.distinct_values or []):
                        fs.reasoning.append(
                            f"PROFILE: Fingerprint override — actual values match '{fp.fingerprint_set}' "
                            f"({fp.fingerprint_ratio:.0%}), not previous BDE match"
                        )
                    fs.accepted_values = ref_values
                    fs.dq_rules["accepted_values"] = ref_values
                    fs.reference_code_set = fp.fingerprint_set
            elif fp.is_reference and fp.distinct_values:
                # No fingerprint but low cardinality → use actual values
                if fs.accepted_values and not self._values_overlap(fs.accepted_values, fp.distinct_values):
                    fs.reasoning.append(
                        f"PROFILE: Overriding accepted_values — actual values: {fp.distinct_values}"
                    )
                    fs.accepted_values = fp.distinct_values
                    fs.dq_rules["accepted_values"] = fp.distinct_values
                elif not fs.accepted_values:
                    fs.accepted_values = fp.distinct_values
                    fs.dq_rules["accepted_values"] = fp.distinct_values
                    fs.reasoning.append(
                        f"PROFILE: Reference field ({fp.distinct_count} values): {fp.distinct_values}"
                    )

            # Confidence: use composite score if it's higher than current
            if fp.signals and fp.signals.composite_score > fs.confidence:
                fs.confidence = fp.signals.composite_score
                fs.reasoning.append(
                    f"PROFILE: Confidence upgraded to {fp.signals.composite_score:.0%} (composite)"
                )
            elif fp.signals and fs.confidence > 0:
                # Boost existing confidence by up to 10% if profile confirms
                boost = min(fp.signals.composite_score * 0.2, 0.1)
                fs.confidence = min(fs.confidence + boost, 0.99)

            # Information type from profile
            if fp.signals and fp.signals.information_type != "Dimension":
                if not fs.information_type or fs.information_type == "Dimension":
                    fs.information_type = fp.signals.information_type

            # Merge DQ suggestions from profile stats
            if fp.null_pct < 0.05 and "not_null" not in fs.dq_rules:
                fs.dq_rules["not_null"] = True
            if fp.is_key and "unique" not in fs.dq_rules:
                fs.dq_rules["unique"] = True
            if fp.inferred_type in ("integer", "decimal") and fp.min_val is not None:
                if float(fp.min_val) >= 0 and "positive" not in fs.dq_rules:
                    fs.dq_rules["positive"] = True

    def _check_profile_contradiction(self, fs: 'FieldSuggestion', fp: 'FieldProfile') -> bool:
        """Check if profile data contradicts the linked BDE. If so, unlink and propose new term.
        Returns True if the match was rejected."""
        bde_id = fs.linked_term
        expected = self._BDE_EXPECTED_PATTERNS.get(bde_id)

        contradiction = False
        reason = ""

        if expected:
            # Check pattern contradiction (e.g., linked to email BDE but no email pattern in data)
            expected_patterns = expected.get("patterns", [])
            if expected_patterns:
                if not any(p in fp.detected_patterns for p in expected_patterns):
                    contradiction = True
                    reason = (f"PROFILE CONTRADICTION: linked to '{fs.linked_term_name}' "
                              f"(expects {expected_patterns}) but data shows "
                              f"patterns={fp.detected_patterns or 'none'}")

            # Check type contradiction (e.g., linked to decimal BDE but data is string)
            expected_type = expected.get("type")
            if expected_type and not contradiction:
                if fp.inferred_type != expected_type:
                    # Allow string→integer/decimal (could be stored as string)
                    if not (expected_type in ("integer", "decimal") and fp.inferred_type == "string"):
                        contradiction = True
                        reason = (f"PROFILE CONTRADICTION: linked to '{fs.linked_term_name}' "
                                  f"(expects type={expected_type}) but data is {fp.inferred_type}")

        # General check: if BDE name contains a pattern keyword but data doesn't match
        if not contradiction and fs.confidence < 0.6:
            bde_lower = (fs.linked_term or "").lower()
            if "email" in bde_lower and "email" not in fp.detected_patterns:
                contradiction = True
                reason = f"PROFILE CONTRADICTION: BDE '{fs.linked_term_name}' implies email but data has no email pattern"
            elif "phone" in bde_lower and "phone" not in fp.detected_patterns:
                contradiction = True
                reason = f"PROFILE CONTRADICTION: BDE '{fs.linked_term_name}' implies phone but data has no phone pattern"
            elif "aadhaar" in bde_lower and "aadhaar" not in fp.detected_patterns:
                contradiction = True
                reason = f"PROFILE CONTRADICTION: BDE '{fs.linked_term_name}' implies aadhaar but data has no aadhaar pattern"

        if contradiction:
            fs.reasoning.append(reason)
            fs.reasoning.append(f"UNLINKED: '{fs.linked_term_name}' rejected — proposing new term")
            fs.linked_term = None
            fs.linked_term_name = None
            fs.confidence = 0.0
            fs.new_term_proposed = True
            fs.is_pii = fp.is_pii  # reset PII to what profile says
            if not fp.is_pii:
                fs.classification = "Internal"
            return True

        return False

    def _values_overlap(self, expected: list, actual: list) -> bool:
        """Check if expected values overlap with actual values (case-insensitive)."""
        expected_lower = set(str(v).lower() for v in expected)
        actual_lower = set(str(v).lower() for v in actual)
        overlap = expected_lower & actual_lower
        return len(overlap) / max(len(actual_lower), 1) >= 0.3
