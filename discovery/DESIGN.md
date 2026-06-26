# Semantic Discovery — GCP Native Design

## Problem Statement

When onboarding new data sources into the Data Fabric lakehouse, teams currently must:
1. Manually inspect source schemas and understand field semantics
2. Manually classify PII/PHI fields
3. Manually define DQ rules based on gut feel
4. Manually identify primary/foreign key candidates
5. Manually map technical fields to business terms

Ab Initio's Semantic Discovery automates this. We need an equivalent GCP-native solution that:
- Works **pre-pipeline** (before data lands)
- Operates on **catalog metadata** (not raw data scanning)
- Leverages a **knowledge graph** of business terms, glossaries, and reference data
- **Suggests** linkages, classifications, and pipeline configs for human review

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         SEMANTIC DISCOVERY SERVICE                             │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  ┌─────────────────┐     ┌──────────────────┐     ┌──────────────────────┐   │
│  │  Catalog Reader  │     │  Knowledge Graph  │     │  Suggestion Engine   │   │
│  │  (Source of      │────▶│  (Business Terms, │────▶│  (NLP + Rules)       │   │
│  │   Truth for      │     │   Glossary,       │     │                      │   │
│  │   asset metadata)│     │   Classifications)│     │  • Term matching     │   │
│  └─────────────────┘     └──────────────────┘     │  • PII detection     │   │
│          │                        ▲                 │  • DQ suggestion     │   │
│          │                        │                 │  • Key discovery     │   │
│          ▼                        │                 │  • Type inference    │   │
│  ┌─────────────────┐     ┌──────────────────┐     └─────────┬────────────┘   │
│  │  Data Profiler   │     │  Reference Store  │               │                │
│  │  (Optional:      │     │  (Known patterns, │               ▼                │
│  │   sample-based)  │     │   regex, ref sets)│     ┌──────────────────────┐   │
│  └─────────────────┘     └──────────────────┘     │  Config Generator    │   │
│                                                     │  (YAML output)       │   │
│                                                     └──────────────────────┘   │
│                                                                                │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                        ┌──────────────────────────┐
                        │  Output:                  │
                        │  • Draft table YAML       │
                        │  • Linkage suggestions    │
                        │  • New term proposals     │
                        │  • Classification report  │
                        └──────────────────────────┘
                                      │
                                      ▼
                        ┌──────────────────────────┐
                        │  Data Steward Review UI   │
                        │  (Approve / Reject /Edit) │
                        └──────────────────────────┘
```

## GCP Service Mapping

| Component | GCP Service | Why |
|-----------|------------|-----|
| Knowledge Graph Store | **Firestore** (document DB) or **Cloud Spanner** (if scale) | Stores business glossary, terms, relationships, reference data |
| Embedding Store | **Vertex AI Vector Search** (Matching Engine) | Stores embeddings of business terms for similarity search |
| Embedding Generation | **Vertex AI Embeddings API** (`text-embedding-005`) | Generate embeddings for field names, descriptions |
| NLP/Suggestion Engine | **Vertex AI Gemini** (for complex inference) + **Rules Engine** (deterministic) | Classify, suggest, reason about metadata |
| Catalog Source | **Dataplex Catalog** or **OpenMetadata** (self-hosted) | Where data steward registers assets before onboarding |
| Profiler (optional) | **Dataproc Serverless** (Spark) or **Cloud Functions** | Sample-based profiling when catalog metadata is insufficient |
| Config Generator | **Cloud Functions** or **Cloud Run** | Stateless: takes suggestions → outputs YAML |
| Steward Review UI | **Cloud Run** (lightweight web app) | Approve/reject suggestions |
| Orchestration | **Cloud Composer** (Airflow) or **Cloud Workflows** | Trigger discovery flow |
| Audit/Lineage | **BigQuery** `discovery_audit` dataset | Track all suggestions, approvals, rejections |

## Knowledge Graph Design

### Entity Types

```
┌─────────────────────────────────────────────────────────────────┐
│                      KNOWLEDGE GRAPH                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  BusinessGlossary                                                 │
│  ├── DataDomain (e.g., "Customer", "Order", "Finance")           │
│  │   ├── BusinessTerm (e.g., "Customer Identifier")              │
│  │   │   ├── synonyms: ["cust_id", "customer_no", "cust_num"]   │
│  │   │   ├── data_type: "string"                                 │
│  │   │   ├── is_pii: false                                       │
│  │   │   ├── is_key_candidate: true                              │
│  │   │   ├── dq_rules: {not_null: true, unique: true}           │
│  │   │   └── linked_fields: [...]                                │
│  │   │                                                            │
│  │   ├── BusinessTerm (e.g., "Customer Email")                   │
│  │   │   ├── synonyms: ["email", "email_addr", "e_mail"]        │
│  │   │   ├── data_type: "string"                                 │
│  │   │   ├── is_pii: true                                        │
│  │   │   ├── pattern: "^[\\w.]+@[\\w.]+$"                       │
│  │   │   └── dq_rules: {not_null: true, format: "email"}        │
│  │   │                                                            │
│  │   └── BusinessTerm (e.g., "Customer Phone")                   │
│  │       ├── synonyms: ["phone", "tel", "mobile", "phn_nbr"]    │
│  │       ├── data_type: "string"                                 │
│  │       ├── is_pii: true                                        │
│  │       ├── classification: "PHI"                               │
│  │       └── dq_rules: {not_null: false, pattern: "phone"}      │
│  │                                                                │
│  InformationType                                                  │
│  ├── "Identifier" — fields that identify entities                │
│  ├── "Measure" — numeric/quantitative fields                     │
│  ├── "Dimension" — categorical/descriptive fields                │
│  ├── "Temporal" — date/time fields                               │
│  └── "Reference" — codes from known reference sets               │
│                                                                   │
│  ReferenceCodeSet                                                 │
│  ├── "ISO Country Codes" — [GB, US, DE, ...]                    │
│  ├── "Currency Codes" — [GBP, USD, EUR, ...]                    │
│  ├── "BT Regions" — [North, South, Midlands, ...]              │
│  └── "Order Status" — [delivered, shipped, processing, ...]     │
│                                                                   │
│  DataClassification                                               │
│  ├── "PII" — Personally Identifiable Information                 │
│  ├── "PHI" — Protected Health Information                        │
│  ├── "Sensitive" — Business sensitive                            │
│  ├── "Internal" — Internal only                                  │
│  └── "Public" — No restrictions                                  │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Relationships (Edges)

```
BusinessTerm --[belongs_to]--> DataDomain
BusinessTerm --[has_type]--> InformationType
BusinessTerm --[classified_as]--> DataClassification
BusinessTerm --[references]--> ReferenceCodeSet
BusinessTerm --[related_to]--> BusinessTerm  (e.g., customer_id <-> order.customer_id FK)
Field --[linked_to]--> BusinessTerm
Field --[part_of]--> DataAsset
```

## Discovery Process (Step-by-Step)

### Phase 1: Catalog Read

```
Input: Data Asset registered in Catalog (by Data Steward)
       → table name, field names, field types, descriptions (if any)

Example:
  asset: "wholesale_billing_extract"
  fields:
    - name: "acct_id", type: "string", description: ""
    - name: "cust_nm", type: "string", description: ""
    - name: "bill_amt", type: "decimal", description: ""
    - name: "bill_dt", type: "date", description: ""
    - name: "cntry_cd", type: "string", description: ""
    - name: "email_addr", type: "string", description: ""
```

### Phase 2: Fingerprinting (Semantic Matching)

For each field, the engine:
1. Generates an embedding of `{field_name} + {type} + {description}`
2. Searches the Knowledge Graph for top-N similar business terms
3. Applies deterministic rules (regex patterns, naming conventions)

```
field: "acct_id" (string)
  → Embedding search: cosine_sim("acct_id string") vs all BusinessTerms
  → Top matches:
      1. "Account Identifier" (0.91) — InformationType: Identifier, PII: No
      2. "Customer Identifier" (0.72) — InformationType: Identifier, PII: No
  → Rule match: ends with "_id" → likely Identifier, likely PK candidate
  → SUGGESTION: Link to "Account Identifier", mark as PK candidate

field: "email_addr" (string)
  → Embedding search: cosine_sim("email_addr string") vs all BusinessTerms
  → Top matches:
      1. "Customer Email" (0.95) — PII: Yes, pattern: email
  → Rule match: contains "email" → PII flag
  → SUGGESTION: Link to "Customer Email", classify PII, add format DQ rule

field: "cntry_cd" (string)
  → Embedding search: matches "Country Code"
  → Reference check: values likely from "ISO Country Codes" ref set
  → SUGGESTION: Link to "Country Code", add accepted_values DQ from ref set

field: "bill_amt" (decimal)
  → Embedding search: matches "Billing Amount"
  → Rule match: numeric + "amt" suffix → InformationType: Measure
  → SUGGESTION: Link to "Billing Amount", add positive DQ rule
```

### Phase 3: Suggestion Output

```yaml
# discovery/suggestions/wholesale_billing_extract.yaml
asset: wholesale_billing_extract
discovered_at: "2025-01-15T10:30:00Z"
confidence_threshold: 0.7

suggestions:
  - field: acct_id
    linked_term: "Account Identifier"
    confidence: 0.91
    information_type: Identifier
    classification: Internal
    is_pii: false
    key_candidate: primary_key
    dq_rules:
      not_null: true
      unique: true

  - field: cust_nm
    linked_term: "Customer Name"
    confidence: 0.88
    information_type: Dimension
    classification: PII
    is_pii: true
    dq_rules:
      not_null: true

  - field: bill_amt
    linked_term: "Billing Amount"
    confidence: 0.85
    information_type: Measure
    classification: Internal
    is_pii: false
    dq_rules:
      not_null: true
      positive: true

  - field: bill_dt
    linked_term: "Billing Date"
    confidence: 0.92
    information_type: Temporal
    classification: Internal
    is_pii: false
    dq_rules:
      not_null: true

  - field: cntry_cd
    linked_term: "Country Code"
    confidence: 0.90
    information_type: Reference
    classification: Internal
    is_pii: false
    reference_code_set: "ISO Country Codes"
    dq_rules:
      not_null: true
      accepted_values: [GB, US, DE, FR, IN, AU, ...]

  - field: email_addr
    linked_term: "Customer Email"
    confidence: 0.95
    information_type: Dimension
    classification: PII
    is_pii: true
    dq_rules:
      not_null: false
      format: "email"

new_term_proposals: []
  # If no match found above threshold, propose creating a new business term

foreign_key_candidates:
  - field: acct_id
    likely_references: "accounts.account_id"
    confidence: 0.75
```

### Phase 4: Config Generation (Post-Approval)

Once a Data Steward approves the suggestions, auto-generate:

```yaml
# config/tables/wholesale_billing_extract.yaml (AUTO-GENERATED)
table: wholesale_billing_extract
description: "Wholesale billing extract — discovered via Semantic Discovery"
source: landing/wholesale_billing_extract
primary_key: acct_id
dedup_order_by: ingestion_ts DESC

dq_rules:
  not_null: [acct_id, cust_nm, bill_amt, bill_dt, cntry_cd]
  positive: [bill_amt]
  accepted_values:
    cntry_cd: [GB, US, DE, FR, IN, AU]
  format:
    email_addr: "email"

pii_fields: [cust_nm, email_addr]

type_overrides:
  bill_amt: double

schema_evolution:
  allowed: [add_column, type_widen]
  blocked: [drop_column, type_narrow]
```

## Component Deep-Dive

### 1. Embedding Strategy

| What gets embedded | Embedding model | Stored in |
|--------------------|----------------|-----------|
| Business Term name + description + synonyms | `text-embedding-005` (Vertex AI) | Vertex AI Vector Search |
| Field name + type + description (incoming) | Same model | Transient (query-time) |

Similarity threshold: **0.7** (configurable) — below this, propose "new term".

### 2. Deterministic Rules Engine (Complements NLP)

NLP alone isn't reliable for enterprise data. Combine with rules:

```yaml
# discovery/config/rules.yaml
naming_rules:
  identifiers:
    patterns: ["*_id", "*_key", "*_no", "*_num", "*_code"]
    info_type: Identifier
    key_candidate: true
  
  temporal:
    patterns: ["*_dt", "*_date", "*_ts", "*_timestamp", "*_time"]
    info_type: Temporal
  
  measures:
    patterns: ["*_amt", "*_amount", "*_qty", "*_count", "*_total", "*_price"]
    info_type: Measure
    dq: {positive: true}
  
  pii_indicators:
    patterns: ["*email*", "*phone*", "*mobile*", "*name*", "*addr*", "*ssn*", "*dob*"]
    is_pii: true

type_rules:
  - type: "decimal|double|float"
    info_type: Measure
  - type: "date|timestamp"
    info_type: Temporal

reference_matching:
  # If field has low cardinality + values match a known ref set
  match_threshold: 0.8  # 80% of values must be in ref set
```

### 3. Optional Data Sampling (When Metadata Isn't Enough)

If field names are cryptic (e.g., legacy mainframe: `FLD001`, `FLD002`), we can optionally sample:

```
Catalog metadata insufficient?
    │
    ▼
Sample N rows from landing (Cloud Function reads GCS)
    │
    ▼
Run Presidio PII scan on sampled values
Run regex patterns against sampled values
Check cardinality, uniqueness ratios
Compare values against reference code sets
    │
    ▼
Enhance suggestions with sample-based evidence
```

This is the equivalent of Ab Initio's "Profile Data" + "Analyze Data" steps.

### 4. Knowledge Graph Seeding

The graph needs initial content. Sources:

| Source | What it provides |
|--------|-----------------|
| Existing `config/tables/*.yaml` | DQ rules, keys, accepted_values already defined |
| BT data standards documents | Business terms, domains, naming conventions |
| Industry standards | ISO codes, GDPR PII definitions |
| OpenMetadata / Dataplex glossary | If already populated |
| Manual curation | Data stewards add terms over time |

The graph **grows** with every onboarding — each approved linkage enriches it for next time.

## API Design

```
POST /discover
  Input: { asset_id: "...", catalog_source: "dataplex|openmetadata" }
  Output: { suggestion_id: "...", status: "processing" }

GET /discover/{suggestion_id}
  Output: { suggestions: [...], new_term_proposals: [...], fk_candidates: [...] }

POST /discover/{suggestion_id}/approve
  Input: { approved_fields: [...], rejected_fields: [...], edits: [...] }
  Output: { config_yaml: "...", glossary_updates: [...] }

GET /glossary/search?q=customer
  Output: { terms: [...] }

POST /glossary/terms
  Input: { name: "...", domain: "...", synonyms: [...], ... }
  Output: { term_id: "..." }
```

## Integration with Existing Pipeline

```
                    EXISTING PIPELINE (unchanged)
                    ─────────────────────────────
                    Landing → Reservoir → CCN → Data Product

    NEW: SEMANTIC DISCOVERY (pre-pipeline)
    ──────────────────────────────────────

    Data Steward registers asset in Catalog
            │
            ▼
    Semantic Discovery runs (Cloud Run service)
            │
            ▼
    Suggestions generated → stored in Firestore + BQ audit
            │
            ▼
    Steward reviews in UI (approve/reject/edit)
            │
            ▼
    Approved → config/tables/{asset}.yaml auto-generated
            │
            ▼
    Pipeline picks up new YAML → Landing → Reservoir → CCN → Data Product
```

Zero changes to existing `ingest.py`, `curate.py`, `consume.py`.

## Cost Estimate (Monthly — POC Scale)

| Service | Usage (POC) | Estimated Cost |
|---------|-------------|----------------|
| Vertex AI Embeddings (`text-embedding-005`) | ~10K embeddings/month (onboarding ~50 assets × 200 fields) | ~$0.50 |
| Vertex AI Vector Search | 1 index, <10K vectors | ~$10-20 (min deployment) |
| Vertex AI Gemini (optional complex inference) | ~100 requests/month | ~$1-5 |
| Firestore | <1GB storage, <100K reads/month | ~$0-1 (free tier) |
| Cloud Run (Discovery service) | <10 hours compute/month | ~$0-5 |
| BigQuery (audit) | <1GB stored, minimal queries | ~$0 (free tier) |
| Cloud Functions (sampler) | <1K invocations/month | ~$0 (free tier) |
| **Total POC** | | **~$15-35/month** |

### Production Scale Estimate

| Service | Usage (Prod) | Estimated Cost |
|---------|-------------|----------------|
| Vertex AI Embeddings | ~500K embeddings/month | ~$25 |
| Vertex AI Vector Search | 100K+ vectors, auto-scaling | ~$100-200 |
| Vertex AI Gemini | ~5K requests/month | ~$50-100 |
| Firestore | 10GB, 1M+ reads/month | ~$20-50 |
| Cloud Run | Always-on min instance | ~$30-50 |
| BigQuery (audit) | 50GB, regular queries | ~$10-20 |
| **Total Production** | | **~$250-450/month** |

## Validation Plan

### Phase 1: Prove the Matching Works (Week 1-2)

1. Seed Knowledge Graph with business terms from your existing `config/tables/*.yaml`
   - Extract: field names, DQ rules, accepted_values, types
   - Create BusinessTerms: "Customer ID", "Order ID", "Email", "Total Amount", etc.
2. Run discovery against a **known** asset (e.g., `customers` table)
3. Validate: does it correctly suggest the same DQ rules, PK, PII flags as your manually-written YAML?
4. **Success criteria**: ≥80% match rate against hand-crafted config

### Phase 2: Unknown Data Source (Week 3)

1. Get a raw dataset with no documentation (simulated or real legacy extract)
2. Register in catalog with only field names + types
3. Run discovery
4. Have a data steward validate the suggestions
5. **Success criteria**: saves ≥60% of manual classification effort

### Phase 3: Knowledge Graph Growth (Week 4)

1. Onboard 5 new assets through discovery
2. Each approval enriches the graph
3. Measure: does suggestion quality improve for asset #5 vs asset #1?
4. **Success criteria**: confidence scores increase over time

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Graph storage | Firestore (not Neo4j) | Simpler ops on GCP, sufficient for metadata-to-metadata matching. Neo4j overkill for POC. |
| Embeddings | Vertex AI (not self-hosted) | Managed, no GPU infra, pay-per-use |
| Matching approach | Hybrid (embeddings + rules) | Rules catch deterministic patterns (naming conventions). Embeddings catch semantic similarity. Neither alone is sufficient. |
| Profiler | Optional (not default) | Discovery should work from catalog metadata alone. Profiling is fallback for cryptic schemas. |
| Output | YAML (not direct pipeline trigger) | Human-in-the-loop. Steward must approve before pipeline runs. |
| LLM usage | Gemini for edge cases only | Not in the hot path. Used when rules + embeddings are inconclusive. Cost control. |

## Comparison: Ab Initio SD vs Our Solution

| Capability | Ab Initio SD | Our GCP-Native Solution |
|-----------|-------------|------------------------|
| Profile Data | ✅ Built-in | ✅ Optional (Cloud Function + Spark) |
| Analyze Data | ✅ Built-in | ✅ Rules engine + statistical checks |
| Fingerprint Data | ✅ Against Metadata Hub | ✅ Embeddings + Vector Search against Knowledge Graph |
| Suggest Linkage | ✅ Automated | ✅ Hybrid: embeddings + rules + optional LLM |
| Business Glossary | ✅ Metadata Hub | ✅ Firestore (or OpenMetadata glossary) |
| PII Detection | ✅ Built-in | ✅ Rules + Presidio + naming patterns |
| Key Discovery | ✅ Built-in | ✅ Uniqueness heuristics + FK pattern matching |
| Reference Code Sets | ✅ Built-in | ✅ Stored in Knowledge Graph, matched by cardinality + overlap |
| Human Review | ✅ Workflow | ✅ Cloud Run UI + approval API |
| Learning Over Time | ✅ (proprietary) | ✅ Graph enrichment on each approval |
| Integration | Ab Initio graphs/plans | config/tables/*.yaml → existing pipeline |

## File Structure

```
schema-evolution-gcp-native/
├── discovery/
│   ├── config/
│   │   ├── rules.yaml          # Deterministic matching rules
│   │   └── seed_glossary.yaml  # Initial business terms to seed
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── catalog_reader.py   # Read asset metadata from Dataplex/OpenMetadata
│   │   ├── knowledge_graph.py  # Firestore CRUD for business terms/relationships
│   │   ├── embedder.py         # Vertex AI embedding generation + vector search
│   │   ├── rules_engine.py     # Deterministic pattern matching
│   │   ├── suggester.py        # Orchestrates: read → match → suggest
│   │   ├── config_generator.py # Converts approved suggestions → table YAML
│   │   └── profiler.py         # Optional: sample-based data profiling
│   ├── api/
│   │   ├── main.py             # Cloud Run FastAPI service
│   │   ├── routes.py           # /discover, /glossary, /approve endpoints
│   │   └── Dockerfile
│   ├── ui/                     # Steward review interface (optional - Phase 2)
│   ├── terraform/
│   │   └── discovery.tf        # Firestore, Vector Search, Cloud Run, IAM
│   ├── tests/
│   │   ├── test_rules_engine.py
│   │   ├── test_embedder.py
│   │   └── test_suggester.py
│   ├── requirements.txt
│   ├── DESIGN.md               # This file
│   └── README.md
├── bt_df_lkhouse_fw/           # Existing (unchanged)
├── composer/                    # Existing (unchanged)
├── terraform/                   # Existing (unchanged)
└── ...
```

## Next Steps

1. **Implement Knowledge Graph** (Firestore schema + seed data)
2. **Implement Rules Engine** (deterministic matching from naming patterns)
3. **Implement Embedder** (Vertex AI embeddings + vector search)
4. **Implement Suggester** (orchestration: combines rules + embeddings)
5. **Implement Config Generator** (approved suggestions → YAML)
6. **Implement API** (Cloud Run FastAPI)
7. **Terraform** (infra for discovery components)
8. **Validate** (run against existing tables, measure accuracy)
