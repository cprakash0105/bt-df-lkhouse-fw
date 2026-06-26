# Semantic Discovery — GCP Native

A metadata intelligence engine that accelerates data onboarding by semantically matching asset definitions against a knowledge graph of business terms, domains, and classifications.

## What It Does

Given a new dataset definition (YAML/JSON with field names + types), Semantic Discovery:

1. **Suggests Business Application** — which area this data belongs to (e.g., "Credit Risk & Lending")
2. **Suggests Data Domain** — logical grouping (Customer, Finance, Bureau, etc.)
3. **Links fields to Business Terms** — matches against the glossary using rules + embeddings
4. **Detects PII** — flags personally identifiable information
5. **Suggests DQ Rules** — not_null, positive, range, format, accepted_values
6. **Identifies Keys** — primary key and foreign key candidates
7. **Proposes New Terms** — when a field has no glossary match
8. **Sets Schema Governance** — allowed/blocked evolution rules based on classification
9. **Generates Pipeline Config** — outputs `config/tables/*.yaml` for bt_df_lkhouse_fw

## Quick Start

### 1. Run the Engine Test (no dependencies beyond pyyaml + numpy)

```bash
cd schema-evolution-gcp-native
pip install pyyaml numpy
python -m discovery.tests.test_discovery
```

### 2. Run with Better Embeddings (sentence-transformers)

```bash
pip install sentence-transformers
python -m discovery.tests.test_discovery
```

### 3. Run the Chainlit UI

```bash
cd discovery
pip install -r requirements.txt
chainlit run ui/app.py --port 8000
```

Then open http://localhost:8000 and paste an asset definition.

### 4. Run on GCP (Vertex AI Embeddings)

Set your project:
```bash
export GCP_PROJECT_ID=bt-df-lkhouse
```

The embedder auto-detects Vertex AI availability and uses `text-embedding-005`.

## How It Works

```
Asset Definition (YAML)
        |
        v
+------------------+     +------------------+     +------------------+
|  Knowledge Graph |     |  Rules Engine    |     |  Embedder        |
|  (synonym match) |     |  (patterns/PII)  |     |  (semantic sim)  |
+--------+---------+     +--------+---------+     +--------+---------+
         |                         |                         |
         +-------------------------+-------------------------+
                                   |
                                   v
                          +------------------+
                          |    Suggester     |
                          |  (orchestrator)  |
                          +--------+---------+
                                   |
                                   v
                    +-----------------------------+
                    |  Suggestions (per field):   |
                    |  - Business Term linkage    |
                    |  - PII classification       |
                    |  - DQ rules                 |
                    |  - Key candidates           |
                    |  - New term proposals       |
                    +-------------+---------------+
                                  |
                                  v (after steward approval)
                    +-----------------------------+
                    |  Config Generator           |
                    |  -> config/tables/*.yaml    |
                    |  -> catalog entry JSON      |
                    +-----------------------------+
```

## Two Modes

### Full Discovery (New Dataset)
For data never onboarded before. Runs all steps.

### Delta Discovery (Schema Change)
For existing datasets where schema has changed. Only processes new/changed/removed fields.
Integrates with `SchemaEvolver` in the pipeline.

## Project Structure

```
discovery/
├── config/
│   ├── rules.yaml              # Deterministic matching rules
│   ├── seed_glossary.yaml      # Business terms, domains, reference sets
│   └── sample_cibil_feed.yaml  # Example input
├── engine/
│   ├── knowledge_graph.py      # Business term store + synonym search
│   ├── rules_engine.py         # Pattern-based matching (naming, PII, FK)
│   ├── embedder.py             # Vertex AI / sentence-transformers / TF-IDF
│   ├── suggester.py            # Core orchestrator (Full + Delta discovery)
│   └── config_generator.py     # Approved suggestions -> pipeline YAML
├── ui/
│   └── app.py                  # Chainlit interactive UI
├── tests/
│   └── test_discovery.py       # End-to-end validation
├── requirements.txt
├── start.bat                   # Windows: start Chainlit UI
├── test.bat                    # Windows: run engine test
├── DESIGN.md                   # Full architecture design
└── README.md                   # This file
```

## Extending the Glossary

Add terms to `config/seed_glossary.yaml`:

```yaml
business_terms:
  - id: loan_amount
    name: "Loan Amount"
    domain: finance
    synonyms: [loan_amount, loan_amt, requested_amount, loan_amount_requested]
    data_type: double
    information_type: Measure
    is_pii: false
    dq_rules:
      not_null: true
      positive: true
```

The graph grows automatically as stewards approve discoveries.

## Integration with Pipeline

```
SD generates config/tables/cibil_bureau_feed.yaml
                |
                v
bt_df_lkhouse_fw picks up new YAML (zero code changes)
                |
                v
Landing -> Reservoir -> CCN -> Data Product
```
