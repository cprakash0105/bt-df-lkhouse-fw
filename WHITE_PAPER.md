# White Paper: From Metadata to Executable Data Products
## An AI-Assisted Metadata Control Plane for Enterprise Data Platforms

**Author:** Chandra Prakash
**Reference Implementation:** https://github.com/cprakash0105/bt-df-lkhouse-fw
**Date:** June 2026

---

## 1. Executive Summary

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        PLATFORM OVERVIEW                                         │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                   │
│   Steward                Metadata Control Plane              Integration Layer    │
│                                                                                   │
│   ┌─────────┐    ┌───────────────────────────────┐    ┌─────────────────────┐   │
│   │         │    │  ┌─────────┐ ┌─────────┐     │    │                     │   │
│   │  Speaks │───>│  │ Glossary │ │ Knowledge│     │    │  Landing (JSONL)    │   │
│   │  in NL  │    │  │ (BDEs)   │ │ Graph    │     │    │       │              │   │
│   │         │    │  └─────────┘ └─────────┘     │    │       ▼              │   │
│   └─────────┘    │                               │    │  Reservoir (Parquet)│   │
│        │         │  ┌─────────┐ ┌─────────┐     │    │       │              │   │
│        ▼         │  │ AI       │ │Determin-│     │    │       ▼              │   │
│   ┌─────────┐    │  │ Reasoning│ │istic    │     │    │  CCN (Iceberg)      │   │
│   │         │    │  │ Engine   │ │Core     │     │    │       │              │   │
│   │ Reviews │    │  └─────────┘ └─────────┘     │    │       ▼              │   │
│   │ Approves│    │                               │    │  Data Product (BQ)  │   │
│   │         │───>│  Output:                       │───>│       │              │   │
│   └─────────┘    │  - Pipeline config (YAML)      │    │       ▼              │   │
│                  │  - Data contract (YAML)       │    │  Consumers query    │   │
│                  │  - BDE terms (Dataplex)       │    │                     │   │
│                  │  - Dataset entry (Catalog)    │    │                     │   │
│                  └───────────────────────────────┘    └─────────────────────┘   │
│                                                                                   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

Modern enterprise data platforms fail not because of technology limitations, but because of the gap between governance intent and execution reality. Data stewards define business terms in catalogs. Engineers build pipelines in code. The two rarely meet automatically.

This paper presents an architecture that eliminates this gap by treating metadata as executable infrastructure. A centralised Metadata Control Plane — powered by deterministic rules, semantic AI, and a knowledge graph — automatically translates business definitions into running pipelines, enforced data quality, and governed access control.

The result: data onboarding time drops from weeks to minutes. A steward speaks in natural language, the platform discovers, classifies, contracts, builds, validates, and serves — with human approval as the only manual step.

**Key principles:**
1. Metadata is executable — not documentation
2. Contracts before code — declarative over imperative
3. AI reasons, determinism executes — no hallucination in infrastructure
4. One table, many policies — governance at query time, not at storage time
5. The platform learns — every approval enriches the knowledge graph for next time

---

## 2. The Problem

### 2.1 The Onboarding Tax

In a typical enterprise, onboarding a new data source requires:

| Activity | Who | Time |
|----------|-----|------|
| Understand source schema | BA + Analyst | 2-3 days |
| Classify fields (PII, sensitivity) | Data Steward | 1-2 days |
| Define DQ rules | Steward + Engineering | 1-2 days |
| Map to business terms | Steward + Governance | 1 day |
| Write pipeline config | Engineering | 2-3 days |
| Build and test pipeline | Engineering | 3-5 days |
| Governance review | Governance team | 2-3 days |
| **Total** | | **2-4 weeks** |

This is repeated for every new source. At scale (50-100 sources/year), it becomes the primary bottleneck of the data platform.

### 2.2 The Governance Gap

Even after onboarding, governance degrades over time:
- Schema changes go undetected until pipelines break
- PII fields are missed because classification was manual
- DQ rules are defined once and never updated
- Business terms in the catalog don't match what's in the pipeline
- No one knows who consumes what

### 2.3 The Vendor Lock-in Problem

Existing solutions (Ab Initio Semantic Discovery, Informatica CLAIRE, Collibra) solve parts of this problem but at £500K-1M/year in licensing, tight vendor lock-in, and no interoperability with open lakehouse formats.

---

## 3. Architecture Principles

### Principle 1: Metadata is Executable

**Statement:** Every piece of metadata — a business term definition, a DQ rule, a PII classification — should directly translate into running infrastructure without human interpretation.

**Implementation:** When a steward approves a field as "PII" in Semantic Discovery, the platform:
- Writes the classification to the Knowledge Catalog (Dataplex Glossary)
- Adds `pii_fields: [field_name]` to the pipeline config
- Sets schema evolution to "strict" (block column drops)
- Applies column-level security via Policy Tags in BigQuery
- Generates a data contract with masking requirements

No engineer touches the pipeline. The metadata IS the config.

**Evidence:** `discovery/engine/approval_handler.py` — on approval, writes to Dataplex + pushes config to GCS. `functions/main.py` — Cloud Function reads config and executes the pipeline automatically.

### Principle 2: Contracts Before Code

**Statement:** No pipeline should exist without a contract. The contract defines what the data IS, what quality it MUST have, who OWNS it, and what changes are ALLOWED. The pipeline is compiled from the contract.

**Implementation:** Semantic Discovery generates a data contract on every approval:

```yaml
contract:
  name: cibil_bureau_feed
  version: "1.0.0"
  owner:
    team: Bureau Data Team
    domain: Credit
    business_application: Credit Bureau Integration
  schema:
    primary_key: customer_id
    fields:
      - name: cibil_score
        type: integer
        business_term: Credit Score
        nullable: false
        range: [300, 900]
  quality:
    completeness:
      target: 99.5%
      critical_fields: [customer_id, cibil_score]
    freshness:
      max_delay: 24h
  governance:
    classification: PII
    pii_fields: [pan_number, mobile_number, email_address]
    masking: required_in_non_prod
  evolution:
    allowed: [add_column]
    blocked: [drop_column, type_narrow]
```

The pipeline framework reads this contract and enforces it at every layer.

**Evidence:** `discovery/engine/contract_generator.py` — generates contract from SD suggestions. `contracts/schema.yaml` — full contract specification. `bt_df_lkhouse_fw/engine/curate.py` — enforces DQ and schema evolution from config.

### Principle 3: AI Reasons, Determinism Executes

**Statement:** Large Language Models are powerful for semantic understanding but unreliable for infrastructure operations. The platform uses AI ONLY for reasoning (what does this field mean? what SQL should I generate?) and NEVER for execution (writing to storage, modifying schemas, creating tables).

**Implementation:** The platform has a clear separation:

| AI Does (reasoning) | Determinism Does (execution) |
|---------------------|------------------------------|
| Parse natural language into structured definitions | Write config YAML to GCS |
| Match field names to business terms semantically | Apply DQ rules (not_null, range, format) |
| Generate SQL from requirements | Create/alter BigQuery tables |
| Suggest business application classification | Submit Dataproc jobs |
| Detect PII from value patterns | Enforce schema evolution governance |

The AI's output is ALWAYS validated by deterministic rules before execution. If the AI suggests something that violates governance, the deterministic core blocks it.

**Evidence:** `discovery/engine/suggester.py` — Layer 1 (KG synonym match) and Layer 2 (Rules Engine) run BEFORE Layer 3 (Embeddings/AI). The AI only fires when deterministic methods are insufficient. `discovery/engine/llm_client.py` — isolated, stateless, zero access to infrastructure.

### Principle 4: One Table, Many Policies

**Statement:** Data should exist in one place. Access control, masking, and security should be applied at query time based on who is asking — not by creating multiple copies of data with different access levels.

**Implementation:** Physical data lives in one Iceberg table in the CCN layer. BigQuery serves it via external tables. Column-level security is applied via Data Catalog Policy Tags:

```
User in "pii_reader" group → queries lakehouse_dataproduct.ekyc_provider_feed → sees all columns
User NOT in group → queries same table → PII columns return ACCESS DENIED
```

No masked views. No duplicate tables. One source of truth.

**Evidence:** `functions/main.py` → `apply_column_security()` — creates PII taxonomy and attaches policy tags to columns. Access is controlled via IAM grants on the policy tag.

### Principle 5: The Platform Learns

**Statement:** Every onboarding should make the next onboarding faster. The knowledge graph grows with every approval, making future semantic matching more accurate.

**Implementation:**

```
Onboarding #1: CIBIL feed
    SD matches: 7/9 fields (78% accuracy)
    Steward creates: 2 new BDE terms ("Credit Utilization", "DPD Count")
    → Glossary grows from 26 to 28 terms

Onboarding #2: e-KYC feed
    SD matches: "aadhaar_number" → "Aadhaar Number" (instant, 65% confidence)
    → Because it was already in the glossary from setup

Onboarding #5: Complaints feed
    SD matches: "customer_id" → instant (seen 4 times before)
    → Confidence increases with repetition
```

The more the platform is used, the less the steward needs to do.

**Evidence:** `discovery/engine/knowledge_graph.py` — loads from Dataplex Glossary on startup. `discovery/engine/approval_handler.py` — writes new terms back to Dataplex on approval. Next discovery reads the updated glossary.

---

## 4. The Metadata Control Plane

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         METADATA CONTROL PLANE                                    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                   │
│  ┌───────────────────┐  ┌───────────────────┐  ┌───────────────────────────┐    │
│  │ ENTERPRISE        │  │ KNOWLEDGE GRAPH   │  │ AI REASONING ENGINE       │    │
│  │ GLOSSARY          │  │                   │  │                           │    │
│  │                   │  │ CFU               │  │ ┌───────────────────────┐ │    │
│  │ BDE: Credit Score │  │  └─Domain          │  │ │ Self-hosted LLM       │ │    │
│  │ BDE: PAN Number   │  │     └─Business App │  │ │ (Gemma2 9B / Ollama)  │ │    │
│  │ BDE: Customer ID  │  │        └─uses BDEs │  │ │                       │ │    │
│  │ BDE: Aadhaar      │  │           └─TDEs   │  │ │ • NL parsing          │ │    │
│  │ ...26+ terms      │  │                   │  │ │ • SQL generation      │ │    │
│  │                   │  │ Relationships:    │  │ │ • Semantic matching   │ │    │
│  │ Each BDE has:     │  │ • belongs_to      │  │ └───────────────────────┘ │    │
│  │ • Definition      │  │ • linked_to       │  │                           │    │
│  │ • Data Type       │  │ • references      │  │ Isolated. Stateless.      │    │
│  │ • Classification  │  │ • consumes        │  │ No infra access.          │    │
│  │ • DQ Rules        │  │                   │  │                           │    │
│  │ • Synonyms        │  │                   │  │                           │    │
│  └───────────────────┘  └───────────────────┘  └───────────────────────────┘    │
│                                                                                   │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ DETERMINISTIC CORE                                                         │  │
│  │                                                                            │  │
│  │  Rules Engine ──── Schema Evolver ──── DQ Validator ──── Deduplicator     │  │
│  │       │                  │                  │                  │           │  │
│  │       ▼                  ▼                  ▼                  ▼           │  │
│  │  Pattern match      Detect drift      Enforce rules      Window dedup    │  │
│  │  (naming, PII,      (add/drop/type)   (null, range,      (PK + order)    │  │
│  │   FK, types)        Allow or Block     format, values)                    │  │
│  │                                                                            │  │
│  │  Config Generator ──── Contract Generator ──── Approval Handler            │  │
│  │       │                      │                       │                     │  │
│  │       ▼                      ▼                       ▼                     │  │
│  │  pipeline.yaml          contract.yaml          Write to Dataplex          │  │
│  │  (executable)           (enforceable)          + push to GCS              │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Enterprise Glossary

A flat dictionary of Business Data Elements (BDEs). Each BDE is a reusable, versioned definition:

- **Name:** "Credit Score"
- **Definition:** Credit score provided by TransUnion CIBIL bureau
- **Data Type:** integer
- **Classification:** Sensitive
- **DQ Rules:** not_null, range [300, 900]
- **Synonyms:** cibil_score, bureau_score, fico_score, risk_score

BDEs are universal — used across all business applications. A change to a BDE definition triggers version creation, never mutation.

**Implementation:** Dataplex Business Glossary with 26+ terms. `discovery/scripts/setup_glossary.py` creates the initial dictionary.

### 4.2 Knowledge Graph (Enterprise Hierarchy)

The organisational structure that connects business intent to physical data:

```
CFU (Customer Facing Unit)
  └── Domain (Credit, Payments, Digital Banking)
        └── Business Application (Loan Origination, Payments Hub)
              └── Uses BDEs (from Glossary)
                    └── Linked to TDEs (physical columns in tables)
```

This hierarchy enables:
- "Show me all PII across the Credit domain" → traverse graph
- "What's impacted if CIBIL schema changes?" → lineage from BDE to all linked TDEs
- "Which business application does this new feed belong to?" → keyword + semantic matching

**Implementation:** Dataplex Custom Entry Types (cfu, domain, business-application, dataset). `discovery/scripts/setup_hierarchy.py` creates the structure. SD suggests business application on discovery.

### 4.3 AI Reasoning Engine

A self-hosted Large Language Model (Gemma2 9B on Azure VM) that handles:

1. **Natural Language Parsing:** "I have a new CIBIL feed with customer_id, pan_number, cibil_score..." → structured JSON definition
2. **SQL Generation:** "Create a data product joining customers with CIBIL scores, add eligibility status..." → executable BigQuery SQL
3. **Semantic Matching:** When deterministic rules can't match a field name, embeddings find the closest BDE

The LLM is:
- Self-hosted (no data leaves the perimeter)
- Stateless (no memory between requests)
- Isolated (no access to infrastructure, storage, or execution)
- Replaceable (any OpenAI-compatible API works — swap model by changing one env var)

**Implementation:** `discovery/engine/llm_client.py` — generic OpenAI-compatible client. `discovery/engine/nl_parser.py` — NL parsing. `discovery/engine/sql_generator.py` — SQL generation. Azure VM with Ollama at `http://4.242.19.167:11434/v1`.

### 4.4 Deterministic Core

Everything that touches infrastructure is deterministic Python — no AI, no ambiguity:

| Component | What It Does |
|-----------|-------------|
| Rules Engine | Pattern matching: `*_id` → Identifier, `*email*` → PII |
| Schema Evolver | Detects drift, applies/blocks changes based on governance |
| DQ Validator | Enforces not_null, range, format, accepted_values, positive |
| Deduplicator | Window function dedup on primary_key + order_by |
| Config Generator | Converts suggestions → pipeline-ready YAML |
| Contract Generator | Converts suggestions → data contract YAML |

**Implementation:** `discovery/engine/rules_engine.py`, `bt_df_lkhouse_fw/engine/schema_evolver.py`, `bt_df_lkhouse_fw/engine/curate.py`.

### 4.5 Semantic Discovery (The Front Door)

The entry point for all data onboarding. A conversational interface where stewards:

1. Describe a dataset (NL, YAML, CSV, or file upload)
2. SD discovers: matches fields to BDEs, detects PII, suggests DQ, identifies business application
3. Steward reviews and approves
4. Platform executes: creates BDEs, registers dataset, pushes config, generates contract
5. Pipeline triggers automatically

**Implementation:** `discovery/ui/app.py` (Chainlit on Cloud Run). Deployed at https://semantic-discovery-978009776592.europe-west2.run.app

---

## 5. The Integration Layer

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           INTEGRATION LAYER                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                   │
│  DATA FLOW:                                                                       │
│                                                                                   │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────┐   ┌─────────────────┐  │
│  │   LANDING   │   │   RESERVOIR   │   │     CCN      │   │  DATA PRODUCT    │  │
│  │             │   │              │   │              │   │                 │  │
│  │  GCS/JSONL  │──>│  GCS/Parquet │──>│  GCS/Iceberg │──>│    BigQuery     │  │
│  │             │   │              │   │              │   │                 │  │
│  │  Raw from   │   │  + ingestion │   │  + DQ valid  │   │  + Materialised │  │
│  │  source     │   │    timestamp │   │  + Dedup     │   │    joins/aggs   │  │
│  │  Immutable  │   │  Schema on   │   │  + Schema   │   │  + SCD Types    │  │
│  │             │   │  read        │   │    governed  │   │  + Policy Tags  │  │
│  └─────────────┘   └──────────────┘   └──────────────┘   └─────────────────┘  │
│       │                │                 │                  │               │
│       │   ingest.py    │    curate.py    │    consume.py    │               │
│       │   (PySpark)    │    (PySpark     │    (BQ SQL       │               │
│       │                │     + Iceberg)  │     + SCD)       │               │
│       │                │                 │                  │               │
│  ┌────┴──────────────┴────────────────┴──────────────────┴───────────────┐  │
│  │              DATAPROC CLUSTER (dedicated, single-node)                    │  │
│  │              Spark 3.5 + Iceberg + BigLake Catalog JAR                    │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                   │
│  AUTOMATION:                                                                      │
│                                                                                   │
│  ┌─────────────────┐     ┌───────────────────────────────────────────────────────┐  │
│  │  GCS Bucket      │     │  CLOUD FUNCTION (Gen2)                               │  │
│  │                 │     │                                                       │  │
│  │  config/tables/  │────>│  Trigger: object finalize on *.yaml                  │  │
│  │  *.yaml lands    │     │                                                       │  │
│  │                 │     │  1. Submit ingest job to cluster                      │  │
│  │  (pushed by SD   │     │  2. Wait -> submit curate job                        │  │
│  │   on approval)   │     │  3. Create BQ external table (Iceberg via BLMS)      │  │
│  │                 │     │  4. Generate + run consumption SQL                   │  │
│  │                 │     │  5. Apply column-level security (Policy Tags)        │  │
│  │                 │     │  6. Log to pipeline_monitor (BQ audit table)         │  │
│  └─────────────────┘     └───────────────────────────────────────────────────────┘  │
│                                                                                   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 5.1 Layered Storage Architecture

| Layer | Storage | Format | Purpose |
|-------|---------|--------|---------|
| Landing | GCS | JSONL | Raw from source, immutable |
| Reservoir | GCS | Parquet | Typed, partitioned, schema-on-read |
| CCN (Curated/Conformed/Normalised) | GCS | Apache Iceberg | Governed: DQ validated, deduplicated, schema-controlled |
| Data Product | BigQuery | Native tables | Optimised for consumers: materialised joins, aggregations |

Each layer has a clear purpose and data only flows forward through validation gates.

**Implementation:** `bt_df_lkhouse_fw/engine/ingest.py` (Landing→Reservoir), `curate.py` (Reservoir→CCN), `consume.py` (CCN→Data Product).

### 5.2 Processing Pipeline

Config-driven — add a new table with zero code changes:

```yaml
table: cibil_bureau_feed
primary_key: customer_id
dedup_order_by: ingestion_ts DESC
dq_rules:
  not_null: [customer_id, cibil_score]
  range:
    cibil_score: [300, 900]
  format:
    pan_number: pan
schema_evolution:
  allowed: [add_column, type_widen]
  blocked: [drop_column, type_narrow]
```

Drop this YAML into GCS → pipeline processes the table automatically.

### 5.3 Schema Evolution Governance

When source schemas change (they always do), the platform:

1. **Detects** the change (new column? type change? dropped column?)
2. **Classifies** it (add_column, type_widen, type_narrow, drop_column)
3. **Checks** governance (is this allowed for this dataset?)
4. **Acts**: allowed → ALTER TABLE + continue. Blocked → fail pipeline + alert.

This prevents breaking changes from propagating to consumers silently.

**Implementation:** `bt_df_lkhouse_fw/engine/schema_evolver.py`

### 5.4 Slowly Changing Dimensions (SCD)

The consumption layer supports all SCD types natively:

| Type | Behaviour | Use Case |
|------|-----------|----------|
| 1 | Overwrite | Reference data, corrections |
| 2 | New row per change (effective_from/to, is_current) | Full audit trail |
| 3 | Previous value columns (prev_X) | One level of history |
| 4 | Current table + history table | Fast lookup + archive |
| 6 | Hybrid 1+2+3 | Most complete tracking |

Config-driven — specify `scd_type: 2` in the consumption YAML and the framework handles the rest.

**Implementation:** `bt_df_lkhouse_fw/engine/scd.py`

### 5.5 Event-Driven Automation

```
SD approves → config YAML lands in GCS
    │
    ▼ (GCS Eventarc trigger)
Cloud Function (Gen2) fires:
    ├── Submits ingest job to Dataproc cluster
    ├── Waits → submits curate job
    ├── Creates BigQuery external table
    ├── Runs consumption SQL
    ├── Applies column-level security
    ├── Logs everything to pipeline_monitor
    └── Done — data product ready in BigQuery
```

No manual intervention between approval and queryable data.

**Implementation:** `functions/main.py` — Cloud Function triggered by GCS object finalize.

---

## 6. Operational Model

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    END-TO-END ONBOARDING FLOW                                    │
└─────────────────────────────────────────────────────────────────────────────────┘

  HUMAN STEPS:                          AUTOMATED STEPS:
  (steward, ~5 min)                     (platform, ~3 min)

  ┌───────────────────────┐
  │ Steward speaks to SD  │
  │ "I have a new feed    │
  │  with these fields..." │
  └───────────┬───────────┘
              │
              ▼
  ┌───────────────────────┐
  │ SD discovers:         │
  │ - Matches to BDEs     │
  │ - Detects PII         │
  │ - Suggests DQ rules   │
  │ - Identifies BA       │
  └───────────┬───────────┘
              │
              ▼
  ┌───────────────────────┐
  │ Steward reviews &     │
  │ types "approve all"   │
  └───────────┬───────────┘
              │
              │  ┌─────────────────────────────────────────────┐
              └─>│ Creates BDEs in Dataplex Glossary         │
                 │ Registers dataset in Catalog              │
                 │ Generates data contract (v1.0.0)          │
                 │ Pushes pipeline config YAML to GCS        │
                 └──────────────────────┬──────────────────────┘
                                       │
                                       ▼ (GCS event trigger)
                 ┌─────────────────────────────────────────────┐
                 │ Cloud Function fires:                      │
                 │ 1. Ingest (Landing -> Reservoir)            │
                 │ 2. Curate (Reservoir -> CCN/Iceberg)        │
                 │    - DQ validation                          │
                 │    - Deduplication                          │
                 │    - Schema evolution check                  │
                 │ 3. Create BQ external table                  │
                 │ 4. Run consume SQL (Data Product)            │
                 │ 5. Apply column-level security               │
                 │ 6. Log to pipeline_monitor                   │
                 └──────────────────────┬──────────────────────┘
                                       │
                                       ▼
                 ┌─────────────────────────────────────────────┐
                 │ DATA PRODUCT READY IN BIGQUERY              │
                 │ Consumers can query immediately             │
                 └─────────────────────────────────────────────┘

  Total time: ~8 minutes (5 min human + 3 min automated)
  vs. traditional: 2-4 weeks
```

### 6.1 Contract-First Onboarding Flow

```
1. Business User: "I need CIBIL scores for the loan app feature"
2. BA searches Catalog: "CIBIL score doesn't exist yet"
3. Architect designs: "Onboard CIBIL bureau feed"
4. Steward talks to SD: "I have a new cibil bureau feed with..."
5. SD discovers: matches fields, detects PII, suggests DQ
6. Steward approves: SD creates BDEs, contract, config
7. Pipeline auto-triggers: ingest → curate → consume
8. Data appears in BigQuery: 800 rows, DQ validated, PII secured
9. Mobile app queries BigQuery: loan eligibility decisions served
```

Time: ~5 minutes (steward) + ~3 minutes (pipeline) = **8 minutes total**

### 6.2 Multi-Persona Access

| Persona | What They Use | What They See |
|---------|--------------|---------------|
| Business User | Nothing (raises request) | Data products in BI tools |
| BA | Dataplex Catalog | Business terms, data assets, gaps |
| Steward | Semantic Discovery UI | Suggestions, approvals, contracts |
| Governance | Dataplex Catalog + Monitor | PII classifications, access policies |
| Engineering | GitHub + Cloud Shell | Pipeline configs, logs, code |
| App Support | Pipeline Monitor (BQ) | Job status, DQ failures, durations |

### 6.3 Observability

Every pipeline event is logged to BigQuery `pipeline_monitor`:

```sql
SELECT dataset_name, stage, status, records_in, records_out,
       records_rejected, duration_seconds, event_time
FROM lakehouse_dataproduct.pipeline_monitor
ORDER BY event_time DESC
```

Tracks: discovery, approval, ingest, curate, consume, errors — with record counts and durations.

**Implementation:** `functions/monitor.py`

---

## 7. Data Profiling & Fingerprinting

Inspired by Ab Initio's Semantic Discovery approach, the platform implements a full profiling and fingerprinting pipeline that runs automatically during discovery.

### 7.1 Auto-Profile from Source

When a dataset is discovered, the engine automatically fetches landing data from GCS and profiles it — no manual step required:

```
User: "discover customer_complaints"
  │
  ▼
Step 0: Fetch gs://bucket/landing/customer_complaints/*.jsonl
  │
  ▼
Profile each field:
  - Type inference (integer, decimal, date, string, boolean)
  - Null percentage
  - Distinct count & cardinality ratio
  - Min/max/mean for numerics
  - PII pattern detection (PAN, Aadhaar, email, phone, credit card)
  - Key candidate detection (>95% unique, <1% null)
  - Reference field detection (≤15 distinct values, <5% cardinality)
```

### 7.2 Fingerprinting Against Reference Code Sets

The platform compares each field's actual values against **all reference code sets** in the glossary (14 sets currently). This is Ab Initio's "fingerprinting" concept:

```
Field: "status"
Actual values: [open, in_progress, resolved, escalated, closed]

vs. order_statuses:      [delivered, shipped, processing...]     → 0% match ✗
vs. complaint_statuses:  [open, in_progress, resolved...]        → 100% match ✓
vs. payment_statuses:    [paid, overdue, partial, waived]        → 0% match ✗
vs. upi_statuses:        [success, failed, pending, declined]    → 0% match ✗
... (checks all 14 sets)

Result: fingerprint = complaint_statuses (100%)
```

This prevents the #1 cause of DQ failures: wrong `accepted_values` from an incorrect BDE match.

### 7.3 Composite Confidence Scoring

Rather than a single confidence number, the platform synthesizes multiple test results (matching Ab Initio's approach):

| Signal | Weight | What It Measures |
|--------|--------|------------------|
| Keyword | 30% | Field name matches BDE synonym |
| Pattern | 25% | Values match known regex patterns (PII) |
| Fingerprint | 25% | Values match reference code sets |
| Statistical | 20% | Type + range + cardinality aligns with BDE definition |

**Composite Score** = Σ(weight × signal)

Example:
```
csat_score:
  keyword    = 1.0  (exact synonym match to "CSAT Score" BDE)
  pattern    = 0.0  (no PII pattern)
  fingerprint = 0.0 (not a reference field)
  stat       = 0.8  (integer, range [1,5] matches BDE)
  → composite = 0.30×1.0 + 0.25×0.0 + 0.25×0.0 + 0.20×0.8 = 0.46
```

The signal breakdown is shown in the UI and stored in reasoning for full auditability.

### 7.4 Information Type Classification

Each field is classified into one of five Information Types (Ab Initio's hierarchy above BDEs):

| Information Type | Criteria |
|-----------------|----------|
| **Identifier** | High cardinality (>95%), likely PK/FK |
| **Measure** | Numeric with moderate-high cardinality |
| **Temporal** | Date or timestamp type |
| **Reference** | Low cardinality (≤15 values), fingerprint match |
| **Dimension** | String with moderate cardinality (default) |

### 7.5 Profile Persistence

Every profile is persisted to GCS for audit trail and re-validation:

```
gs://bt-df-lkhouse-lakehouse/profiles/customer_complaints/latest.json
```

Contains: all field statistics, signals breakdown, fingerprint results, detected patterns. Enables:
- Re-running discovery against the same profile
- Tuning phase: review results and adjust thresholds
- Historical comparison: has the data distribution changed?

### 7.6 Profile Enhancement of Suggestions

After profiling, the results enhance SD's suggestions:

1. **Override wrong accepted_values** — if fingerprint doesn't match current BDE's reference set, replace with actual fingerprint match
2. **Boost confidence** — if profile confirms the BDE match (type + range + patterns align), increase confidence
3. **Detect PII from values** — even if field name is cryptic, PAN/Aadhaar patterns in values → mark as PII
4. **Fix type declarations** — if declared "string" but values are dates, report the discrepancy
5. **Identify keys** — 100% unique + 0% null → primary key candidate

**Implementation:** `discovery/engine/discovery_profiler.py` — lightweight profiler with fingerprinting and composite scoring (no pandas/GE dependency). `discovery/engine/ge_profiler.py` — full GE-powered profiler (optional, for advanced statistical analysis).

---

## 8. Economics

### 8.1 Platform Cost (Monthly)

| Service | Cost |
|---------|------|
| Cloud Run (SD) | ~$5 |
| Dataproc cluster (4 vCPUs, when running) | ~$100 |
| Azure VM (LLM, 4 vCPUs) | ~$140 |
| BigQuery | ~$5 |
| GCS | ~$1 |
| Dataplex Catalog | Free |
| Cloud Function | Free tier |
| **Total** | **~$250/month** |

### 8.2 Comparison

| | Ab Initio | Informatica | Collibra | This Platform |
|---|---|---|---|---|
| Annual cost | $500K-1M | $300K-500K | $200K-400K | **~$3K** |
| Semantic Discovery | ✅ | ✅ (CLAIRE) | ❌ | ✅ |
| Fingerprinting | ✅ | ❌ | ❌ | ✅ |
| Composite Confidence Scoring | ✅ | ❌ | ❌ | ✅ |
| Information Types | ✅ | ❌ | ❌ | ✅ |
| Data Contracts | ❌ | ❌ | Partial | ✅ |
| DQ Inheritance (BDE → TDE) | ✅ | ❌ | ❌ | ✅ |
| Schema Evolution | ✅ | ❌ | ❌ | ✅ |
| Self-hosted LLM | ❌ | ❌ | ❌ | ✅ |
| Open formats (Iceberg) | ❌ | ❌ | ❌ | ✅ |
| Profile Persistence (audit) | ✅ | ❌ | ❌ | ✅ |
| Multi-feed Onboarding | ❌ | ❌ | ❌ | ✅ |
| Conversational Corrections | ❌ | ❌ | ❌ | ✅ |
| Vendor lock-in | High | High | Medium | **None** |

---

## 9. DQ Inheritance Engine

Addressing the need for business-level DQ that cascades automatically:

### 9.1 The Principle

"Define a handful of rules at the business term level, not thousands at the column level."

When a BDE like "Credit Score" has DQ rules (not_null, range [300, 900]), every table that uses that BDE automatically inherits those rules — without any per-table configuration.

### 9.2 How It Works

```
Glossary BDE "Credit Score":
  dq_rules:
    not_null: true
    range: [300, 900]

→ Automatically applied to ALL tables using "Credit Score":
    • cibil_bureau_feed.cibil_score
    • credit_risk_model.bureau_score
    • loan_eligibility.score

= 1 rule defined. Applied everywhere. Zero engineering.
```

### 9.3 Smart Inheritance

The engine is intelligent about what to inherit:

- **`unique` only on PK** — `customer_id` inherits `unique` only on the `customers` table, not on `orders` where it's an FK
- **Reference sets from fingerprint** — if fingerprint finds a better reference set than the BDE match, fingerprint wins
- **Field-level overrides** — per-table rules take precedence over inherited BDE rules

**Implementation:** `discovery/engine/dq_inheritance.py` — reads BDE definitions, merges into table configs for fields matched with confidence ≥ 0.5.

---

## 10. React UI & API Layer

### 10.1 Architecture

The platform provides two UIs (running in parallel during transition):

| UI | Technology | URL | Status |
|----|-----------|-----|--------|
| Chainlit | Python/Chainlit | semantic-discovery-*.run.app | Original (conversational) |
| React | React + Tailwind + Vite | sd-web-*.run.app | New (panel-based) |

Both share the same FastAPI backend and engine.

### 10.2 FastAPI Backend

REST endpoints wrapping all engine capabilities:

| Endpoint | Purpose |
|----------|--------|
| POST /discover | Run SD (NL, YAML, or field list) |
| POST /discover/multi | Multi-feed domain onboarding |
| POST /profile | Profile sample data |
| POST /approve | Approve + push to Dataplex/GCS |
| POST /correct | Conversational corrections |
| GET /glossary | Browse all BDEs |
| POST /generate/config | Generate pipeline YAML |
| POST /generate/sql | Generate consumption SQL |

### 10.3 Conversational Corrections

The UI supports inline corrections without re-running discovery:

- "due_date is not PII" → removes PII flag
- "status values are open, closed, pending" → overrides accepted_values
- "customer_id is not unique" → removes unique constraint
- "priority maps to priority_level" → changes BDE linkage

### 10.4 Multi-Feed Onboarding

One prompt can describe an entire domain with multiple datasets:

```
discover domain Insurance:
1. motor_policy: policy_id, customer_id, vehicle_reg, premium_amount, start_date, status
2. motor_claims: claim_id, policy_id, claim_date, claim_amount, status
3. vehicle_master: vehicle_id, make, model, year, registration_number
4. premium_payments: payment_id, policy_id, amount, payment_date, status
```

SD discovers all 4 datasets, shows combined results, approves all at once.

**Implementation:** `discovery/api/main.py` (FastAPI), `discovery/web/` (React + Vite + Tailwind).

---

## 11. Limitations & Future Work

| Limitation | Planned Resolution |
|---|---|
| LLM response time (~90s on CPU) | GPU VM or Gemini API when quotas stabilise |
| OpenLineage not integrated | Emit events from Spark jobs |
| Single cloud (GCP) | Add Trino for cross-cloud federation |
| No row-level security | BigQuery supports it via row access policies |
| Manual data generator | Connect to real source systems |
| No CI/CD for contracts | Git-based contract versioning with approval workflows |
| Feedback loop not persistent | Store corrections in Firestore, improve future matching |
| Glossary at 40 terms | Target: 500+ terms for production coverage |

---

## 12. Conclusion

The gap between data governance and data engineering is not a technology problem — it's an integration problem. By treating metadata as executable artifacts, contracts as pipeline specifications, and AI as a reasoning layer (not an execution layer), we built a platform that:

- Onboards new data sources in minutes, not weeks
- Enforces governance automatically, not manually
- Profiles and fingerprints data to validate classifications with evidence
- Provides composite confidence scores with full signal breakdown for auditability
- Inherits business DQ rules from glossary BDEs (define once, apply everywhere)
- Learns from every interaction, getting smarter over time
- Costs 99% less than enterprise alternatives
- Uses open standards (Iceberg, YAML, OpenAI-compatible APIs) with zero vendor lock-in

The reference implementation is live, deployed on GCP, and proven end-to-end with 5 banking datasets. The React UI and FastAPI backend provide a production-ready interface for data stewards.

---

## References

- **Reference Implementation:** https://github.com/cprakash0105/bt-df-lkhouse-fw
- **React UI:** https://sd-web-978009776592.europe-west2.run.app
- **Chainlit UI:** https://semantic-discovery-978009776592.europe-west2.run.app
- **GCP Project:** bt-df-lkhouse
- **Apache Iceberg:** https://iceberg.apache.org
- **BigLake Metastore:** https://cloud.google.com/bigquery/docs/biglake-metastore
- **Dataplex Knowledge Catalog:** https://cloud.google.com/dataplex/docs
- **Great Expectations:** https://greatexpectations.io
