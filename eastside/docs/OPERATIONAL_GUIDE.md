# EastSide CDH 2.0 — Operational Guide

**Last Updated**: July 2025
**Author**: Chandra Prakash
**Repo**: `cprakash0105/bt-df-lkhouse-fw`
**GCP Project**: `bt-df-lkhouse`
**Region**: `europe-west2`

---

## Quick Reference

| Resource | Value |
|---|---|
| GCP Project | `bt-df-lkhouse` |
| Region | `europe-west2` |
| EastSide Bucket | `gs://eastside-lakehouse/` |
| Original Bucket | `gs://bt-df-lkhouse-lakehouse/` |
| Iceberg Catalog | `eastside` (BLMS) |
| Bronze Namespace | `eastside.bronze` |
| Silver Namespace | `eastside.silver` |
| Gold Dataset | `bt-df-lkhouse.eastside_dataproduct` |
| Dagster UI | `http://<dagster-static-ip>` (port 80, nginx) |
| Ontika URL | `https://sd-web-978009776592.europe-west2.run.app` |
| LLM | OpenAI GPT-OSS 120B on AWS Bedrock Mantle `https://bedrock-mantle.eu-north-1.api.aws/v1` |
| GitHub | `cprakash0105/bt-df-lkhouse-fw` (main branch) |
| Cloud Shell User | `cp0105_admin` |

---

## Architecture Summary

```
Landing (GCS raw files)
    │  JSON, CSV, Avro, Parquet — as received from source
    ▼
Bronze (Iceberg, append-only)
    │  Format conversion, CDC reconstruct, row_hash, detective DQ
    │  Schema evolution: accept all changes
    ▼
Silver (Iceberg, merge/SCD2)
    │  Dedup, preventative DQ, masking, late arrival handling
    │  Schema evolution: non-breaking only
    ▼
Gold (BigQuery)
    │  Contract-enforced, column-level security
    │  Read-time protection via Dataplex
    ▼
Consumers (BI, ML, APIs)
```

---

## Folder Structure

```
schema-evolution-gcp-native/
├── eastside/                          ← NEW: EastSide CDH 2.0
│   ├── docs/DESIGN.md                ← Full architecture doc
│   ├── config/
│   │   ├── pipeline.yaml             ← Global config
│   │   └── tables/*.yaml             ← 8 table configs
│   ├── engine/
│   │   ├── base.py                   ← Spark session, config, logging
│   │   ├── bronze.py                 ← Landing → Bronze Iceberg
│   │   ├── silver.py                 ← Bronze → Silver Iceberg
│   │   ├── gold.py                   ← Silver → BigQuery
│   │   ├── reconcile.py              ← Source↔Bronze↔Silver checks
│   │   ├── schema_evolver.py         ← Layer-aware schema evolution
│   │   └── stream.py                 ← Kafka → Bronze (streaming)
│   ├── datagen/generate.py           ← 8 datasets → GCS
│   ├── scripts/run_*.sh              ← Dataproc submission scripts
│   ├── terraform/main.tf             ← Infrastructure
│   └── cloudbuild.yaml               ← CI/CD
│
├── bt_df_lkhouse_fw/                  ← ORIGINAL: v1 framework
│   ├── engine/                        ← ingest.py, curate.py, scd.py, etc.
│   └── config/                        ← Original table configs
│
├── discovery/                         ← ONTIKA: Shared discovery layer
│   ├── api/main.py                   ← FastAPI backend (Cloud Run)
│   ├── engine/                        ← Knowledge graph, KC agent, LLM client
│   ├── config/seed_glossary.yaml     ← Business terms, BAs, domains
│   └── web/src/                       ← React UI
│
├── datagen/                           ← Original + IB feed generators
├── DATA_CATALOGUE.md                  ← All 18 onboarded datasets documented
└── cloudbuild-web.yaml                ← Ontika deployment
```

---

## Datasets (EastSide)

| # | Dataset | Format | CDC | Records | Domain |
|---|---|---|---|---|---|
| 1 | `pos_transactions` | JSON | No | 5,000 | Sales |
| 2 | `online_orders` | JSON | No | 3,000 | Sales |
| 3 | `inventory_movements` | CSV | No | 4,000 | Supply Chain |
| 4 | `customer_profiles` | JSON | No | 2,000 | Customer |
| 5 | `product_catalogue` | JSON | Yes | 1,000 | Product |
| 6 | `supplier_purchase_orders` | CSV | Yes | 1,500 | Procurement |
| 7 | `returns_exchanges` | JSON | No | 1,200 | Sales |
| 8 | `store_staff` | CSV | Yes | 400 | HR |

**CDC feeds** have `_cdc_operation` column (INSERT/UPDATE/DELETE). Partial records contain only PK + changed fields.

**PII fields**:
- `customer_profiles`: first_name, last_name, email, phone, date_of_birth
- `store_staff`: first_name, last_name, email

---

## Deployment Steps (First Time)

### 1. Infrastructure (Terraform)

```bash
cd eastside/terraform
terraform init
terraform apply -var="project_id=bt-df-lkhouse"
```

Creates: GCS bucket, BLMS catalog + namespaces, BQ dataset, KMS key, service account + IAM.

### 2. Upload Engine + Config (Cloud Build)

```bash
gcloud builds submit --config eastside/cloudbuild.yaml --project bt-df-lkhouse
```

Or manually from Cloud Shell:
```bash
gcloud storage cp eastside/engine/*.py gs://eastside-lakehouse/engine/
gcloud storage cp eastside/config/pipeline.yaml gs://eastside-lakehouse/config/pipeline.yaml
gcloud storage cp eastside/config/tables/*.yaml gs://eastside-lakehouse/config/tables/
```

### 3. Generate Data

```bash
pip install google-cloud-storage
python eastside/datagen/generate.py --project=bt-df-lkhouse
```

### 4. Run Pipeline

```bash
# Bronze (all tables)
bash eastside/scripts/run_bronze.sh bt-df-lkhouse europe-west2 all v1

# Silver (all tables)
bash eastside/scripts/run_silver.sh bt-df-lkhouse europe-west2 all

# Gold (all tables)
bash eastside/scripts/run_gold.sh bt-df-lkhouse europe-west2 all

# Reconciliation
bash eastside/scripts/run_reconcile.sh bt-df-lkhouse europe-west2 all
```

### 5. Single Table

```bash
bash eastside/scripts/run_bronze.sh bt-df-lkhouse europe-west2 pos_transactions v1
bash eastside/scripts/run_silver.sh bt-df-lkhouse europe-west2 pos_transactions
bash eastside/scripts/run_gold.sh bt-df-lkhouse europe-west2 pos_transactions
```

### 6. Dagster VM (Orchestration)

The Dagster VM is provisioned by Terraform and auto-starts on boot — no SSH required.

```bash
# Deploy infrastructure (creates VM, static IP, firewall)
cd eastside/terraform
terraform apply -var="project_id=bt-df-lkhouse"

# Get the Dagster URL
terraform output dagster_url
# → http://34.89.x.x
```

**VM Spec**: `e2-small` (2 vCPU, 2GB RAM) — sufficient for Dagster daemon + webserver.

**What happens on boot**:
1. Installs Python, nginx, creates dagster user
2. Creates virtualenv, installs dagster + GCP SDKs
3. Pulls workspace code from `gs://eastside-lakehouse/orchestration/`
4. Starts `dagster-daemon` (schedules, sensors) via systemd
5. Starts `dagster-webserver` on `127.0.0.1:3000` via systemd
6. nginx reverse-proxies port 80 → 3000 (no `:3000` in URL)

**After code changes**:
```bash
# Upload new code to GCS
bash eastside/deploy_dagster.sh

# Restart services on the VM (no SSH needed if using gcloud)
gcloud compute ssh eastside-dagster --zone=europe-west2-a -- \
  'sudo systemctl restart dagster-daemon dagster-webserver'
```

**Service management** (if SSH'd into the VM):
```bash
sudo systemctl status dagster-daemon dagster-webserver nginx
sudo journalctl -u dagster-daemon -f   # live daemon logs
sudo journalctl -u dagster-webserver -f # live webserver logs
```

---

## Engine Behaviour

### Bronze (`bronze.py`)
1. Reads landing files (auto-detects format from `source_format` in table config)
2. CDC tables: reconstructs partial records to full rows (reads last known state from bronze, overlays changed fields)
3. Computes `row_hash` = SHA256 over `hash_fields` from config
4. Adds metadata: `_ingested_at`, `_source_file`, `_batch_id`
5. Runs detective DQ: populates `_dq_flags` array (flags only, never rejects)
6. Schema evolution: accepts all changes (add, drop, widen, narrow)
7. Appends to `eastside.bronze.{table}` (Iceberg)

### Silver (`silver.py`)
1. Reads all records from bronze table
2. Dedup: drops records whose `row_hash` already exists in silver
3. Preventative DQ: rejects records failing NOT NULL (PK), POSITIVE, ACCEPTED_VALUES
4. Policy controls:
   - Strip non-printable characters
   - Trim whitespace, uppercase postcodes
   - SHA256 masking on configured PII fields
5. Late arrival: within window → merge, outside → quarantine table
6. Schema evolution: non-breaking only (add + widen allowed, drop + narrow blocked)
7. SCD2 merge: `valid_from`, `valid_to`, `is_current`
   - Changed records: close existing (is_current=false), append new version
   - New records: append with is_current=true
8. Reconciliation log written

### Gold (`gold.py`)
1. Reads silver where `is_current=true`
2. Contract validation: required columns must exist, PK uniqueness enforced
3. Drops internal columns (row_hash, valid_from/to, _dq_flags, etc.)
4. Writes to BigQuery `eastside_dataproduct.{table}` (overwrite mode)

### Reconciliation (`reconcile.py`)
- Source ↔ Bronze: row count (bronze ≥ source = pass)
- Bronze ↔ Silver: unaccounted < 5% = pass
- Hash checksum: distinct hashes (silver ≤ bronze = pass)
- Results in `eastside.silver.reconciliation_log`

### Schema Evolution (`schema_evolver.py`)
- Layer-aware: reads `schema_evolution.{layer}` from table config
- Bronze: accepts everything
- Silver: allows add_column + type_widen, blocks drop_column + type_narrow
- Gold: contract-enforced (blocks all changes)

### Streaming (`stream.py`)
- Kafka → Bronze Iceberg via Spark Structured Streaming
- SHA256 row_hash persisted for auditability
- Two-level dedup: intra-batch (dropDuplicates) + cross-batch (left_anti join)
- foreachBatch pattern for stateful dedup
- Configurable trigger interval (default 15 min)

---

## Ontika (Shared Discovery Layer)

### Deployment
```bash
gcloud builds submit --config cloudbuild-web.yaml --project bt-df-lkhouse
```

### Key Files
- `discovery/api/main.py` — FastAPI backend
- `discovery/engine/kc_agent.py` — Knowledge Catalog agent (rule-based Q&A)
- `discovery/engine/rag/` — RAG pipeline (embedder, indexer, retriever)
- `discovery/engine/mcp/` — MCP agent (agentic tool-calling)
- `discovery/engine/knowledge_graph.py` — Business term matching
- `discovery/config/seed_glossary.yaml` — BAs, domains, terms
- `discovery/web/src/App.jsx` — React UI with intent routing

### API Endpoints
| Endpoint | Method | Purpose |
|---|---|---|
| `/ask` | POST | Main Q&A — Cache → MCP agent → LLM → KC agent (priority chain) |
| `/rag/index` | POST | Rebuild RAG knowledge index |
| `/mcp/tools` | GET | List available MCP tools |
| `/cache/stats` | GET | Response cache statistics |
| `/cache/clear` | POST | Clear response cache |
| `/debug/llm` | GET | Test LLM connectivity |
| `/discover` | POST | Run discovery on a dataset |
| `/approve` | POST | Approve current suggestion |
| `/landing/datasets` | GET | List datasets in GCS landing |
| `/catalog/tree` | GET | Full catalog hierarchy |
| `/catalog/sync` | POST | Sync catalog from glossary |
| `/health` | GET | Health check |

### `/ask` Priority Chain
1. **Response Cache** — exact MD5 hash match OR semantic similarity > 0.92 (ChromaDB cosine)
2. **MCP Agent** — triggered for data-access questions (query, pull, top N, count, chart). Executes real SQL against BigQuery via `query_table` tool. Returns inline charts for aggregate results.
3. **LLM (Bedrock Mantle)** — general questions answered with full catalog context (domains, BAs, terms)
4. **KC Agent** — rule-based fallback (never returns dead-end "no results found")

### Activating RAG
After deploy, build the index once:
```bash
curl -X POST https://sd-web-978009776592.europe-west2.run.app/rag/index
```
This indexes all configs, glossary, docs, and pipeline logs. Subsequent questions get RAG-augmented answers.

### Session State
- Firestore-backed (`sessions/default` doc) — survives Cloud Run scale-to-zero
- Falls back to in-memory if Firestore unavailable

### Intent Routing (App.jsx)
Priority chain:
1. Landing list → 2. Profile → 3. Approve → 4. Config → 5. Correction
6. Glossary Q&A → 7. Discovery-context Q&A (only if suggestion active)
8. Onboard → 9. Question-shaped catch-all → LLM → 10. Statement → guide

### For EastSide
- Point landing scan to `gs://eastside-lakehouse/landing/`
- Config output to `gs://eastside-lakehouse/config/tables/`
- Let LLM build glossary organically through onboarding

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Bronze format | Iceberg (not raw Parquet) | Time travel, schema evolution, snapshot isolation |
| CDC in bronze | Reconstruct to full rows | Makes bronze AI-consumable without joins |
| SCD2 in silver | valid_from/valid_to/is_current | Matches Openreach pattern, full history |
| Dedup | SHA256 row_hash persisted | Auditability + cross-batch dedup in streaming |
| Late arrival | Window + quarantine | Both time travel merge AND configurable rejection |
| Masking | On-write (SHA256) for high-sensitivity | Irreversible, protects even if storage is breached |
| Gold write mode | Overwrite (full refresh) | Simple, consistent, no merge complexity in BQ |
| Schema evolution | Layer-aware config | Bronze=open, Silver=guarded, Gold=locked |

---

## Amanda's Requirements Mapping

| Requirement | Implementation | Location |
|---|---|---|
| Format conversion (CSV/JSON/Avro/DB → Parquet) | `source_format` in table config, auto-detect in bronze.py | `bronze.py` read_landing() |
| Append mode bronze | Iceberg append-only writes | `bronze.py` writeTo().append() |
| Merge mode silver | SCD2 merge with MERGE INTO | `silver.py` merge_scd2() |
| Schema evolution bronze (open) | SchemaEvolver layer=bronze, accept all | `schema_evolver.py` |
| Schema evolution silver (non-breaking) | SchemaEvolver layer=silver, block drop+narrow | `schema_evolver.py` |
| Schema evolution gold (contract) | Contract validation before BQ write | `gold.py` validate_contract() |
| Time travel bronze | Iceberg snapshots (VERSION AS OF) | Native Iceberg capability |
| Late arriving data silver | Configurable window + quarantine | `silver.py` handle_late_arrivals() |
| SCD2 processing | valid_from/valid_to/is_current | `silver.py` merge_scd2() |
| Streaming batch windows | Configurable trigger interval | `stream.py` --trigger-interval |
| Streaming dedup (hash) | SHA256 row_hash, two-level dedup | `stream.py` dedup_micro_batch() |
| CDC partial records | Reconstruct full rows in bronze | `bronze.py` reconstruct_cdc() |
| Reconciliation source↔bronze | Row count comparison | `reconcile.py` reconcile_source_bronze() |
| Reconciliation bronze↔silver | Row count + hash checksum | `reconcile.py` reconcile_bronze_silver() |
| Policy detective (bronze) | _dq_flags array, never reject | `bronze.py` run_detective_policies() |
| Policy preventative (silver) | Reject bad records, standardise | `silver.py` apply_preventative_dq() |
| Masking/encryption | SHA256 on configured PII columns | `silver.py` apply_masking() |
| Non-printable removal | Regex strip on all string columns | `silver.py` strip_non_printable() |

---

## Troubleshooting

### "No active discovery" in Ontika
- Cause: `_isQuestion()` was catching general questions when no suggestion was active
- Fix: `_isQuestion` only fires when `suggestion` is not null (commit `248e44b`)

### Cloud Run scale-to-zero wipes session
- Cause: In-memory `_session` dict lost between requests
- Fix: Firestore-backed session at `sessions/default` (commit `ee2e534`)

### Dataset assigned to wrong BA
- Cause: Missing BA in glossary (e.g. no `core_banking` → falls back to low-confidence match)
- Fix: Add BA with explicit keywords to `seed_glossary.yaml`, hit Refresh in Ontika

### BA keywords dirty (commas in words)
- Cause: Keywords derived from description text including punctuation
- Fix: Use explicit `keywords` list from YAML, or clean name+domain words only (commit `52d0133`)

### Dataproc job fails with "table not found"
- Cause: BLMS namespace doesn't exist
- Fix: Engine creates namespace on startup (`CREATE NAMESPACE IF NOT EXISTS`)

### Bronze append fails on schema mismatch
- Cause: New columns in source not in existing Iceberg table
- Fix: `merge-schema=true` option + SchemaEvolver adds columns via ALTER TABLE

---

## Commits (Key)

| Commit | Description |
|---|---|
| `ee2e534` | Firestore session fix |
| `345b9d2` | Smart intent routing (LLM catch-all) |
| `014b8db` | IB feeds datagen |
| `52d0133` | BA keywords fix + LINKED_DATASETS intent |
| `1cac3de` | Tree structure + 9 new BAs |
| `248e44b` | Fix general questions routing to LLM |

---

## Open Items

- [ ] Discuss with Rhys: which PII fields get write-time vs read-time protection
- [ ] Confirm with Amanda: reconciliation as part of pipeline or separate job
- [ ] Confirm: which EastSide datasets (if any) need real-time streaming
- [ ] Confirm: gold layer consumption views / data products required
- [ ] Iceberg compaction strategy (time-based vs file-count threshold)
- [x] ~~RAG pipeline for LLM~~ (done)
- [x] ~~MCP (Model Context Protocol) integration~~ (done)
- [x] ~~Dagster VM: e2-small, systemd, static IP, nginx~~ (done)

---

## RAG Pipeline & MCP (Implemented)

### RAG (Retrieval-Augmented Generation)

Ontika now has a full RAG pipeline that grounds LLM answers in real platform data.

**Architecture**:
- **Vector store**: ChromaDB (in-memory, ephemeral per Cloud Run instance) — zero cost
- **Embeddings**: AWS Bedrock Mantle (Titan Embed v2) via OpenAI-compatible API
- **Documents indexed**: table configs, seed glossary, DATA_CATALOGUE.md, DESIGN.md, OPERATIONAL_GUIDE.md, pipeline logs from GCS
- **Chunk size**: ~1500 chars with 200 char overlap
- **Retrieval**: Top-5 chunks by cosine similarity

**Files**:
- `discovery/engine/rag/embedder.py` — Ollama embedding client
- `discovery/engine/rag/indexer.py` — Chunks documents, embeds, stores in ChromaDB
- `discovery/engine/rag/retriever.py` — Queries ChromaDB, augments LLM prompt

**To rebuild index**:
```bash
curl -X POST https://sd-web-978009776592.europe-west2.run.app/rag/index
```

### MCP (Model Context Protocol)

Ontika now has an agentic LLM with tool-calling capability — the Ab Initio Agentic AI equivalent.

**How it works**:
1. User asks a question
2. LLM sees available tools + RAG context
3. LLM decides: answer directly OR call a tool
4. If tool called → agent executes → feeds result back to LLM
5. LLM generates final answer grounded in tool results
6. Max 3 tool-call iterations per question

**Available tools**:
| Tool | Description |
|---|---|
| `query_table` | Execute real SQL against BigQuery — returns actual rows (up to 100) |
| `get_table_stats` | Row count, columns, last modified for any table |
| `get_table_config` | Read full YAML config (DQ rules, PII, schema evolution) |
| `list_tables` | List all configured tables with domain and format |
| `get_reconciliation_status` | Latest recon results (pass/fail, counts) |
| `get_dq_report` | DQ flag summary for a table in bronze |
| `get_pipeline_history` | Recent pipeline runs for a stage |
| `trigger_pipeline` | Generate pipeline trigger command (with confirmation) |
| `refresh_rag_index` | Rebuild the RAG knowledge index |

**BigQuery tables available to the agent**:
- `bt-df-lkhouse.lakehouse_dataproduct.*` (loan_eligibility_360, customer_spend_360, etc.)
- `bt-df-lkhouse.eastside_dataproduct.*` (pos_transactions, online_orders, etc.)

### Response Cache

All LLM responses are cached to avoid repeated calls for same/similar questions.

- **Exact match**: MD5 hash of normalised question → instant hit
- **Semantic match**: ChromaDB cosine similarity > 0.92 → near-match hit
- **Persistence**: Firestore (`qa_cache` collection) survives Cloud Run restarts
- **TTL**: 24 hours (configurable via `CACHE_TTL` env var)
- **Management**: `GET /cache/stats`, `POST /cache/clear`
- **Smart caching**: Failed/error responses are never cached

### Inline Charts

When the MCP agent returns aggregate/tabular data and the question contains chart triggers
("top", "breakdown", "by category", "distribution"), the API extracts chart-ready JSON
and the frontend renders inline horizontal bar charts with the Ontika colour palette.

### UI Design

Light theme with Google Material-style cards:
- **Font**: Inter (Google Fonts)
- **Colours**: Indigo (#4F46E5), Purple (#7C3AED), Gold (#F59E0B), White
- **Cards**: Rounded corners, subtle shadows, hover elevation (-translate-y-0.5)
- **Logo**: Stylised orbital O with gradient ring and gold data-node accent
- **Chat**: Card-style message bubbles, animated typing indicator, send icon button

**Files**:
- `discovery/engine/mcp/tools.py` — Tool definitions and handlers
- `discovery/engine/mcp/agent.py` — Agentic loop (LLM + tool execution)

**API priority chain** (`/ask` endpoint):
1. Response Cache (exact hash + semantic similarity)
2. MCP Agent (agentic, tool-calling, BigQuery execution) — for data-access questions
3. LLM (Bedrock Mantle GPT-OSS 120B) — for general questions
4. KC Agent (rule-based) — fallback, never returns dead-ends

**Cost: Pay-per-token** — Bedrock Mantle, ChromaDB is open-source. No VM to manage.

**Example flow**:
```
User: "What's the DQ reject rate for pos_transactions?"
  → MCP Agent calls: get_dq_report(table_name="pos_transactions")
  → Tool returns: {"dq_log": [...flagged 150 records...]}
  → LLM answers: "DQ reject rate is 3% (150/5000 records flagged)"
```
