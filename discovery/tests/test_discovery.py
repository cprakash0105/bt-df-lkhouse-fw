"""Test Semantic Discovery engine end-to-end.
Run: python -m discovery.tests.test_discovery"""
import sys
import yaml
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from discovery.engine.knowledge_graph import KnowledgeGraph
from discovery.engine.rules_engine import RulesEngine
from discovery.engine.embedder import Embedder
from discovery.engine.suggester import Suggester
from discovery.engine.config_generator import ConfigGenerator


def test_full_discovery():
    print("=" * 70)
    print("SEMANTIC DISCOVERY - Full Discovery Test")
    print("=" * 70)

    # Load sample asset
    sample_path = Path(__file__).parent.parent / "config" / "sample_cibil_feed.yaml"
    with open(sample_path, "r", encoding="utf-8") as f:
        asset_def = yaml.safe_load(f)

    # Initialize engine
    print("\n[1/5] Initializing Knowledge Graph...")
    kg = KnowledgeGraph()
    print(f"       Loaded {len(kg.terms)} business terms, {len(kg.applications)} applications, {len(kg.domains)} domains")

    print("\n[2/5] Initializing Rules Engine...")
    rules = RulesEngine()

    print("\n[3/5] Initializing Embedder (local mode)...")
    embedder = Embedder(mode="local")

    print("\n[4/5] Running Full Discovery...")
    suggester = Suggester(knowledge_graph=kg, rules_engine=rules, embedder=embedder)
    suggestion = suggester.full_discovery(asset_def)

    # Print results
    print(f"\n{'=' * 70}")
    print(f"RESULTS: {suggestion.asset_name}")
    print(f"{'=' * 70}")
    print(f"\n  Business Application: {suggestion.business_application_name} (confidence: {suggestion.app_confidence:.0%})")
    print(f"  Data Domain: {suggestion.data_domain}")
    print(f"  Primary Key: {suggestion.primary_key}")

    print(f"\n  {'Field':<25} {'Business Term':<25} {'Type':<12} {'PII':<5} {'Conf':<6}")
    print(f"  {'-'*25} {'-'*25} {'-'*12} {'-'*5} {'-'*6}")
    for f in suggestion.fields:
        term = f.linked_term_name or "[NEW TERM]"
        pii = "Yes" if f.is_pii else "No"
        conf = f"{f.confidence:.0%}" if f.confidence > 0 else "-"
        info_type = f.information_type or "-"
        print(f"  {f.field_name:<25} {term:<25} {info_type:<12} {pii:<5} {conf:<6}")

    if suggestion.fk_candidates:
        print(f"\n  Foreign Keys:")
        for fk in suggestion.fk_candidates:
            print(f"    {fk['field']} -> {fk['references']}")

    if suggestion.new_term_proposals:
        print(f"\n  New Business Terms Proposed:")
        for prop in suggestion.new_term_proposals:
            print(f"    - {prop['suggested_term_name']} (from {prop['field_name']})")

    print(f"\n  Schema Evolution: {suggestion.schema_evolution}")

    # Generate config
    print(f"\n[5/5] Generating Pipeline Config...")
    config_gen = ConfigGenerator()
    config_yaml = config_gen.generate(suggestion)
    print(f"\n{'=' * 70}")
    print("GENERATED CONFIG:")
    print(f"{'=' * 70}")
    print(config_yaml)

    # Generate catalog entry
    catalog = config_gen.generate_catalog_entry(suggestion)
    print(f"\n{'=' * 70}")
    print("CATALOG ENTRY:")
    print(f"{'=' * 70}")
    import json
    print(json.dumps(catalog, indent=2))

    print(f"\n{'=' * 70}")
    print("[OK] Full Discovery Test Complete")
    print(f"{'=' * 70}")


def test_delta_discovery():
    print(f"\n\n{'=' * 70}")
    print("SEMANTIC DISCOVERY - Delta Discovery Test")
    print(f"{'=' * 70}")

    kg = KnowledgeGraph()
    rules = RulesEngine()
    embedder = Embedder(mode="local")
    suggester = Suggester(knowledge_graph=kg, rules_engine=rules, embedder=embedder)

    # Simulate: existing cibil table gets a new field + type change
    new_fields = [
        {"name": "credit_limit", "type": "decimal", "description": "Maximum credit limit"},
        {"name": "last_payment_date", "type": "date", "description": "Last payment received"},
    ]
    removed_fields = ["dpd_30_plus_count"]
    changed_fields = [
        {"name": "cibil_score", "old_type": "integer", "new_type": "decimal"},
    ]

    print("\n  Schema changes detected:")
    print(f"    New fields: {[f['name'] for f in new_fields]}")
    print(f"    Removed: {removed_fields}")
    print(f"    Type changes: {[f['name'] for f in changed_fields]}")

    suggestion = suggester.delta_discovery("cibil_bureau_feed", new_fields, removed_fields, changed_fields)

    print(f"\n  {'Field':<25} {'Action':<40}")
    print(f"  {'-'*25} {'-'*40}")
    for f in suggestion.fields:
        action = f.reasoning[0] if f.reasoning else "-"
        print(f"  {f.field_name:<25} {action:<40}")

    print(f"\n[OK] Delta Discovery Test Complete")


if __name__ == "__main__":
    test_full_discovery()
    test_delta_discovery()
