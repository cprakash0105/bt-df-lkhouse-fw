# Project Context — Schema Evolution GCP Native (CDH 2.0)

## Owner
Chandra Prakash, BT Group

## Platform
- Project: bt-df-lkhouse
- Region: europe-west2
- Cloud: GCP

## What This Is
A config-driven lakehouse platform with 3 major components:
1. **bt_df_lkhouse_fw** — Config-driven pipeline framework (Landing → Reservoir → CCN → Data Product)
2. **EastSide CDH 2.0** — Production deployment (Landing → Bronze → Silver → Gold) with Dagster orchestration
3. **Semantic Discovery** — AI-assisted metadata control plane that auto-generates pipeline configs from natural language

## Tech Stack
| Component | Technology |
|-----------|-----------|
| Storage | GCS (single bucket per deployment) |
| Table Format | Apache Iceberg |
| Catalog | BigLake Metastore (BLMS) |
| Compute | Managed Dataproc Cluster (PySpark) |
| Orchestration | Dagster (GCE VM: eastside-dagster, e2-small) |
| Gold Layer | BigQuery native tables |
| Bronze/Silver Query | BigQuery external tables (via BigLake connection) |
| Encryption | Cloud KMS (AES-256, reversible PII) |
| Hashing | SHA256 (irreversible PII) |
| Governance | Dataplex Knowledge Catalog (policy tags, glossary) |
| SD UI | React + Tailwind (Cloud Run) |
| SD API | FastAPI (Cloud Run) |
| SD LLM | AWS Bedrock Mantle (openai.gpt-oss-120b, eu-north-1, OpenAI-compatible API) |
| Automation | Cloud Functions Gen2 (GCS event trigger) |
| IaC | Terraform |
| CI/CD | Cloud Build (`cloudbuild-web.yaml` at repo root) |

## EastSide Data Flow
```
Sources (POS, E-commerce, ERP, Warehouse, Loyalty, PLM CDC, HR CDC)
    → GCS Landing (gs://eastside-lakehouse/landing/{table}/v{n}/)
    → Dataproc bronze.py (CDC recon, row_hash, metadata cols, detective DQ, SchemaEvolver)
    → Iceberg Bronze (BLMS: lkhouse_eastside.bronze) — Policy: ACCEPT ALL
    → Schema Evolution Engine (detect, alias, fingerprint, type matrix)
    → Dataproc silver.py (dedup, preventative DQ, standardise, PII mask, SCD2, SchemaEvolver)
    → Iceberg Silver (BLMS: lkhouse_eastside.silver) — Policy: NON-BREAKING
    → Contract Registry (versioned YAML: v1.0.0 → v2.0.0)
    → Dataproc gold.py (contract validation, PK check, projection)
    → BigQuery Gold (eastside_dataproduct) — Policy: CONTRACT LOCKED
    → Consumers (BI, ML, APIs, Regulatory)
```

## Schema Evolution Rules
| Change | Bronze | Silver | Gold |
|--------|--------|--------|------|
| Add Column | Accept | Accept (nullable) | Contract change |
| Drop Column | Accept (null-fill) | BLOCK | BLOCK |
| Type Widen | Accept | Accept | Contract change |
| Type Narrow | Accept + alert | BLOCK | BLOCK |
| Rename | Alias mapping | Alias mapping | Contract change |

## Key Engine Files
- `eastside/engine/bronze.py` — Landing → Bronze (append)
- `eastside/engine/silver.py` — Bronze → Silver (SCD2 merge)
- `eastside/engine/gold.py` — Silver → Gold (BQ native write)
- `eastside/engine/schema_evolver.py` — Detect + enforce schema rules
- `eastside/engine/base.py` — Spark session, config loader, logging
- `eastside/config/tables/*.yaml` — Per-table config (DQ, schema evolution, PII, keys)
- `eastside/contracts/` — Gold contract YAML files
- `eastside/orchestration/` — Dagster assets, jobs, resources

## bt_df_lkhouse_fw (Original Framework)
Same concept but 4 layers: Landing → Reservoir (Parquet, no catalog) → CCN (Iceberg/BLMS) → Data Product (BQ native). Automation via Cloud Functions. Config in `bt_df_lkhouse_fw/config/`.

## Semantic Discovery
- Steward describes dataset in natural language
- Engine: profiles data (stats only), matches to BDEs via knowledge graph + rules + embeddings + fingerprinting
- Composite confidence scoring (keyword 30%, pattern 25%, fingerprint 25%, statistical 20%)
- On approval: generates pipeline YAML, data contract, Dataplex entries, SCD config
- LLM boundary: never sees raw data, only statistical summaries
- DQ inheritance: define rule at BDE level, auto-applied to all tables using that term

## Operational Controls
- Schema Audit Table (every change logged with run_id, status)
- Schema Quarantine (blocked payloads preserved with diff for replay)
- Alerting (Slack, Teams, Email, ServiceNow)
- Schema Fingerprint (hash comparison skips checks if unchanged)
- Metadata Ownership (business_owner, technical_owner, steward per table)
- Contract Versioning (patch/minor/major, consumer notification)

## Infrastructure (Terraform)
- GCS bucket, BLMS catalog + bronze/silver databases
- BQ datasets (eastside_dataproduct, eastside_bronze, eastside_silver)
- KMS keyring + pii-encryption-key (90-day rotation)
- Service accounts (eastside-dataproc, eastside-dagster)
- Dagster GCE VM (e2-small, Debian 12, static IP, nginx proxy)
- VPC, NAT, firewall rules

## Deployment
```bash
# From Cloud Shell:
cd ~/schema-evolution-gcp-native
git pull origin main
gcloud builds submit --config cloudbuild-web.yaml .
```

Cloud Build files:
- `cloudbuild-web.yaml` — Semantic Discovery (React UI + FastAPI) → Cloud Run
- `cloudbuild-profiler.yaml` — Profiler service → Cloud Run
- `cloudbuild.yaml` — Original framework
- `eastside/cloudbuild.yaml` — EastSide pipeline engine

## Data Generation
```bash
# Generate all 8 datasets (v1) to GCS landing:
python eastside/datagen/generate.py --project=bt-df-lkhouse

# Generate schema evolution demo data (v2 + v3 for pos_transactions):
python eastside/datagen/generate_schema_evolution_demo.py --project=bt-df-lkhouse
```

### Schema Evolution Demo (pos_transactions)

Production-realistic generator with state management:
```bash
# Generate all 3 versions (prep):
python eastside/datagen/generate_evolution.py --project=bt-df-lkhouse --all

# Or one at a time (live demo):
python eastside/datagen/generate_evolution.py --project=bt-df-lkhouse --version v1
python eastside/datagen/generate_evolution.py --project=bt-df-lkhouse --version v2
python eastside/datagen/generate_evolution.py --project=bt-df-lkhouse --version v3

# Reset state:
python eastside/datagen/generate_evolution.py --project=bt-df-lkhouse --reset
```

| Version | Records | Change | Landing Path |
|---------|---------|--------|--------------|
| v1 | 3,000 | Baseline (12 fields) | `landing/pos_transactions/v1/` |
| v2 | 2,000 | +`loyalty_points_earned` (new column) | `landing/pos_transactions/v2/` |
| v3 | 1,500 | −`unit_price` (dropped column) | `landing/pos_transactions/v3/` |

- State file: `gs://eastside-lakehouse/datagen/_state/pos_transactions.json`
- Each run increments IDs from last run (no duplicates, no watermark clearing needed)
- Timestamps relative to `now` — data always looks fresh

Demo flow:
1. Bronze v1 → baseline table created
2. Silver → SCD2 merge succeeds ✅
3. Bronze v2 → SchemaEvolver auto-adds `loyalty_points_earned` ✅
4. Silver → new column accepted as nullable ✅
5. Bronze v3 → `unit_price` NULL-filled (bronze accepts drops) ✅
6. Silver → **FAILS** — `drop_column blocked` ❌ (proves governance)

Legacy generator (fixed IDs, requires watermark clearing): `eastside/datagen/generate_schema_evolution_demo.py`

## Capability Demos

File: `eastside/docs/CAPABILITY_DEMO_PLAYBOOK.md`

| # | Capability | Status | Demo Story |
|---|-----------|--------|------------|
| 1 | Format Conversion (CSV/JSON → Iceberg) | ✅ Done | Drop CSV, query as Iceberg in BQ |
| 2 | Time Travel & Late Arriving Feed | 🔨 Build | Late record arrives, show before/after, quarantine if too old |
| 3 | SCD2 in Silver | ✅ Done | Customer moves city, show history + point-in-time query |
| 4 | Streaming Dedup | ✅ Done | Duplicate arrives, bronze keeps both, silver deduplicates |
| 5 | CDC & Partial Records | ✅ Done | Partial update reconstructed to full row |
| 6 | Policy Controls (PII) | 🔨 Build | Write-time masking (SHA256) + read-time Dataplex policies |

Priority build order: test data generator → Demo 2 (late arrival) → Demo 6 (Dataplex policies)

## Demo Queries (BQ)

File: `eastside/docs/DEMO_QUERIES.md`

| # | Query | What It Proves |
|---|-------|----------------|
| 1 | Schema Evolution Proof | v1/v2/v3 coexist — NULL pattern shows zero-cost column add/drop |
| 2 | Table Schema (INFORMATION_SCHEMA) | Schema is union of all versions, columns never removed |
| 3 | Data Lineage by Source File | Every record traceable to source file + batch |
| 4 | DQ Flags | Bronze flags but never rejects (detective-only policy) |
| 5 | NULL Pattern Deep Dive | One record per batch showing different schemas coexisting |
| 6 | Ingestion History | Pipeline run history visible from the data itself |
| 7 | Silver Governed Data | Only clean data passes; v3 blocked if drop_column enforced |
| 8 | Bronze vs Silver (Governance Gap) | Record count difference = governance working |
| 9 | Row Hash Dedup Check | Bronze is append-only; row_hash enables silver dedup |
| 10 | Pipeline Monitor | Unified observability from GCS logs via external table |

Suggested demo flow: 1 → 2 → 5 → 3 → 8 → 7 → 10

## Project Paths
```
schema-evolution-gcp-native/
├── bt_df_lkhouse_fw/          # Original framework (config + engine)
├── eastside/                   # EastSide CDH 2.0 production deployment
│   ├── config/tables/         # Per-table YAML configs
│   ├── contracts/             # Gold contract versions
│   ├── engine/                # bronze.py, silver.py, gold.py, schema_evolver.py
│   ├── orchestration/         # Dagster assets, jobs, resources
│   ├── docs/                  # Design docs, runbooks, drawio generators
│   └── terraform/             # EastSide infra
├── discovery/                  # Semantic Discovery service
│   ├── api/                   # FastAPI backend
│   ├── engine/                # Profiler, suggester, rules, embedder
│   ├── ui/                    # React steward UI
│   └── web/                   # Chainlit chat interface
├── presentation/              # HTML presentations (schema evolution, framework, SD)
├── terraform/                 # Original framework infra
├── functions/                 # Cloud Functions (pipeline trigger)
└── datagen/                   # Test data generators
```
