# EastSide — CDH 2.0 Architecture Design

**Organisation**: EastSide (Apparel & Fashion Retail)
**GCP Project**: `bt-df-lkhouse` | **Region**: `europe-west2`
**GCS Bucket**: `eastside-lakehouse`
**Iceberg Catalog**: BigLake Metastore (BLMS) — catalog name `eastside`
**Discovery/Ontika**: Shared instance (same as existing)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         EastSide CDH 2.0                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  SOURCES              LANDING          BRONZE            SILVER          │
│  ───────              ───────          ──────            ──────          │
│                                                                         │
│  POS System ─┐                     ┌─────────────┐  ┌──────────────┐   │
│  E-commerce ─┤    ┌──────────┐     │  Iceberg    │  │   Iceberg    │   │
│  ERP (CDC) ──┼───▶│  GCS     │────▶│  Append     │─▶│   Merge      │   │
│  Warehouse ──┤    │  Raw     │     │  Schema-    │  │   SCD2       │   │
│  Suppliers ──┤    │  Files   │     │  open       │  │   DQ enforced│   │
│  Loyalty ────┘    └──────────┘     │  Detective  │  │   Preventive │   │
│                                    │  policies   │  │   policies   │   │
│                                    └─────────────┘  └──────┬───────┘   │
│                                                            │            │
│                                                            ▼            │
│                                                     ┌──────────────┐   │
│                                                     │  GOLD        │   │
│                                                     │  BigQuery    │   │
│                                                     │  Data Product│   │
│                                                     │  Contract    │   │
│                                                     │  enforced    │   │
│                                                     └──────────────┘   │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│  AI LAYER (Ontika + RAG + MCP)                                          │
│                                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ Ontika      │  │ RAG         │  │ MCP Agent   │  │ LLM         │  │
│  │ Discovery   │  │ ChromaDB    │  │ Tool-calling│  │ GPT-OSS 120B│  │
│  │ + Onboard   │  │ + Bedrock   │  │ 9 tools     │  │ (Bedrock    │  │
│  │ + Glossary  │  │ embeddings  │  │ + guardrails│  │  Mantle)    │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Layer Definitions

### 2.1 Landing (Raw Files)
- **Storage**: `gs://eastside-lakehouse/landing/{dataset}/v{n}/`
- **Format**: As-received (CSV, JSON, Avro, Parquet, DB extract)
- **Retention**: Immutable archive, never modified
- **Purpose**: Audit trail of exactly what arrived from source

### 2.2 Bronze (Iceberg — Append)
- **Storage**: `gs://eastside-lakehouse/bronze/` (Iceberg data files)
- **Catalog**: `eastside.bronze.{table_name}`
- **Write mode**: Append only — no updates, no deletes
- **Format conversion**: All sources converted to Parquet (Iceberg's storage format)
- **Schema evolution**: Automatic — new columns accepted, type widening allowed, no blocking
- **Policy controls**: Detective only — flag issues, never reject or modify
- **CDC handling**: Partial records reconstructed to full rows (fill from last known state) before append
- **Late arriving data**: Accepted unconditionally (append-only, no window restriction)
- **Dedup**: Hash column (`row_hash` — SHA256 of key fields) persisted for downstream dedup
- **Metadata columns**: `_ingested_at`, `_source_file`, `_batch_id`, `row_hash`

### 2.3 Silver (Iceberg — Merge / SCD2)
- **Storage**: `gs://eastside-lakehouse/silver/` (Iceberg data files)
- **Catalog**: `eastside.silver.{table_name}`
- **Write mode**: Merge (upsert on primary key)
- **SCD2**: `valid_from`, `valid_to`, `is_current` on all dimension tables
- **Schema evolution**: Non-breaking only — new columns allowed, type widening allowed, column drops and type narrowing blocked
- **Policy controls**: Preventative/corrective — DQ rules enforced, non-printable characters stripped, masking/encryption applied on write for highly sensitive fields
- **Late arriving data**: Configurable window per table (`late_arrival_window_days`). Within window → merge into correct snapshot. Outside window → quarantine table.
- **Dedup**: Hash-based dedup using `row_hash` from bronze — duplicates dropped
- **Reconciliation**: Row count and hash reconciliation against bronze after each run

### 2.4 Gold (BigQuery — Data Product)
- **Storage**: BigQuery dataset `eastside_dataproduct`
- **Write mode**: Materialised views or MERGE from silver
- **Schema**: Contract-enforced — backward compatible only, versioned
- **Policy controls**: Column-level security via BigQuery/Dataplex for read-time protection
- **Purpose**: Business-ready, consumption-optimised, governed

---

## 3. Datasets

EastSide is an apparel/fashion retailer with physical stores and e-commerce. The following datasets represent their core data estate:

| # | Dataset | Source System | Format | Domain | CDC |
|---|---|---|---|---|---|
| 1 | `pos_transactions` | POS System | JSON | Sales | No (batch) |
| 2 | `online_orders` | E-commerce Platform | JSON | Sales | No (batch) |
| 3 | `inventory_movements` | Warehouse Management | CSV | Supply Chain | No (batch) |
| 4 | `customer_profiles` | Loyalty Platform | JSON | Customer | No (batch) |
| 5 | `product_catalogue` | Merchandising/PLM | JSON | Product | Yes (CDC) |
| 6 | `supplier_purchase_orders` | ERP (SAP) | CSV | Procurement | Yes (CDC) |
| 7 | `returns_exchanges` | Returns Portal | JSON | Sales | No (batch) |
| 8 | `store_staff` | HR System | CSV | HR | Yes (CDC) |

### 3.1 POS Transactions
Point-of-sale transactions from 50+ physical stores. Each record is a line item (one product per row within a basket). High volume (~100K records/day).

**Key fields**: `transaction_id`, `store_id`, `till_id`, `customer_id` (nullable — not all customers scan loyalty card), `product_sku`, `quantity`, `unit_price`, `discount_amount`, `payment_method`, `transaction_datetime`

### 3.2 Online Orders
E-commerce orders from the website and mobile app. Order-level grain (one row per order, items as nested or separate feed).

**Key fields**: `order_id`, `customer_id`, `order_date`, `status`, `total_amount`, `shipping_method`, `delivery_postcode`, `promo_code`, `channel` (web/app)

### 3.3 Inventory Movements
Stock movements across warehouses and stores — receipts, transfers, adjustments, and sales deductions. CSV extract from WMS nightly.

**Key fields**: `movement_id`, `product_sku`, `warehouse_id`, `store_id`, `movement_type` (receipt/transfer/adjustment/sale), `quantity`, `movement_date`, `reference_id`

### 3.4 Customer Profiles
Loyalty programme members — demographics, preferences, tier, and opt-in status. Contains PII.

**Key fields**: `customer_id`, `first_name` (PII), `last_name` (PII), `email` (PII), `phone` (PII), `date_of_birth` (PII), `postcode`, `loyalty_tier`, `signup_date`, `marketing_opt_in`, `preferred_store_id`

### 3.5 Product Catalogue (CDC)
Master product data from the PLM (Product Lifecycle Management) system. CDC feed — only changed fields sent when a product is updated (e.g. price change, new colour added).

**Key fields**: `product_sku`, `product_name`, `category`, `sub_category`, `brand`, `colour`, `size_range`, `rrp`, `cost_price`, `supplier_id`, `season`, `status` (active/discontinued/clearance)

### 3.6 Supplier Purchase Orders (CDC)
Purchase orders raised to suppliers via SAP. CDC feed — partial records when PO status changes (e.g. confirmed → shipped → received).

**Key fields**: `po_number`, `supplier_id`, `supplier_name`, `product_sku`, `quantity_ordered`, `unit_cost`, `order_date`, `expected_delivery_date`, `status` (draft/confirmed/shipped/received/cancelled), `warehouse_id`

### 3.7 Returns & Exchanges
Customer returns and exchanges from both online and in-store channels.

**Key fields**: `return_id`, `order_id`, `customer_id`, `product_sku`, `return_reason`, `return_date`, `refund_amount`, `exchange_sku`, `channel` (online/store), `condition` (new/worn/damaged)

### 3.8 Store Staff (CDC)
Staff records from the HR system. CDC feed — partial records when role/store changes.

**Key fields**: `staff_id`, `first_name` (PII), `last_name` (PII), `email` (PII), `store_id`, `role`, `department`, `start_date`, `hourly_rate` (sensitive), `status` (active/on_leave/terminated)

---

## 4. Schema Evolution by Layer

| Change Type | Bronze | Silver | Gold |
|---|---|---|---|
| New column | ✅ Auto-accept | ✅ Accept (nullable) | ❌ Contract change required |
| Column drop | ✅ Accept (NULL fill) | ❌ Block | ❌ Block |
| Type widening (int→bigint) | ✅ Auto-accept | ✅ Accept | ❌ Contract change required |
| Type narrowing (bigint→int) | ✅ Accept (cast) | ❌ Block | ❌ Block |
| Enum expansion | ✅ Accept | ✅ Accept | ⚠️ Validate against contract |
| Column rename | ✅ Accept (treated as add+drop) | ❌ Block (use alias mapping) | ❌ Block |

---

## 5. Time Travel & Late Arriving Data

### Bronze
- Append-only — all data accepted regardless of event time
- Iceberg snapshots provide full time travel capability
- Query any historical state: `SELECT * FROM eastside.bronze.pos_transactions VERSION AS OF <snapshot_id>`

### Silver
- **Within window**: Late records merged into the correct SCD2 time slice
  - Engine identifies the `valid_from`/`valid_to` window the record belongs to
  - Reopens the closed record, applies the change, re-closes with correct timestamps
- **Outside window**: Records written to `eastside.silver.{table}_quarantine`
  - Quarantine table has same schema + `_quarantine_reason`, `_original_event_time`
  - Steward reviews and manually approves or rejects
- **Config**: `late_arrival_window_days` per table (default: 7)

---

## 6. CDC & Partial Record Handling

```
Source (CDC) ──▶ Landing (partial) ──▶ Bronze (full row, append)
                                           │
                                           │  Reconstruct:
                                           │  1. Read last known full row for PK
                                           │  2. Overlay changed fields
                                           │  3. Append reconstructed full row
                                           │
                                           ▼
                                       Silver (merge/SCD2)
```

- Bronze always stores **full rows** — even if source sends partials
- Reconstruction uses the latest row in bronze for that PK as the base
- If no prior row exists (new record), partial is accepted as-is (missing fields = NULL)
- `_cdc_operation` column tracks: `INSERT`, `UPDATE`, `DELETE`
- Deletes are soft-deletes in bronze (append a row with `_cdc_operation=DELETE`)

---

## 7. Streaming & Dedup

- **Batch windows**: Configurable per table — default 15 minutes for near-real-time, 1 hour for standard
- **Compaction**: Iceberg auto-compaction triggered when small file count exceeds threshold (configurable)
- **Dedup approach**:
  1. On ingest: compute `row_hash = SHA256(primary_key + event_timestamp + key_business_fields)`
  2. Persist `row_hash` as a column in bronze
  3. On merge to silver: `WHERE row_hash NOT IN (SELECT row_hash FROM silver.{table})`
  4. Streaming: maintain a Bloom filter or hash set of recent hashes in checkpoint state

---

## 8. Reconciliation

### Source ↔ Bronze
- Row count comparison (source file record count vs bronze append count per batch)
- Written to `eastside.bronze.reconciliation_log`

### Bronze ↔ Silver
- Row count: bronze total vs silver total (accounting for dedup and DQ rejects)
- Incremental: records processed in this run vs records written to silver
- Hash reconciliation: sum of `row_hash` values as a checksum
- Written to `eastside.silver.reconciliation_log`

### Reconciliation modes
- **Full**: Compare entire table (scheduled weekly)
- **Incremental**: Compare only the current batch (every run)

---

## 9. Policy Controls

### Bronze — Detective Only
- Flag but never reject or modify
- Policies produce `_dq_flags` column (array of triggered rules)
- Examples: `NULL_PK`, `INVALID_DATE_FORMAT`, `UNEXPECTED_ENUM`, `POSSIBLE_PII_IN_FREETEXT`
- No masking, no encryption — raw data preserved for AI/ML consumption

### Silver — Preventative / Corrective
- **DQ enforcement**: Reject records that fail critical rules (NOT NULL on PK, invalid types)
- **Standardisation**: Trim whitespace, uppercase postcodes, normalise dates to ISO 8601
- **Non-printable removal**: Strip characters outside printable ASCII + standard Unicode
- **Masking (on write)**: Highly sensitive fields (PII) → SHA256 hash or tokenisation
  - Config-driven: `masking: sha256` or `masking: tokenise` per column
- **Encryption (on write)**: Fields requiring reversible protection → AES-256 with KMS key
  - Config-driven: `encryption: aes256` per column, key reference in config
- **Filtering**: Exclude test/internal records based on configurable filter expressions

### Gold — Contract Enforced
- Schema locked to published contract version
- Column-level security via BigQuery/Dataplex (read-time protection for less sensitive fields)
- Row-level security for multi-tenant access patterns
- Backward compatibility enforced — consumers never see breaking changes

---

## 10. Folder Structure

```
eastside/
├── docs/
│   └── DESIGN.md              ← this file
├── config/
│   ├── pipeline.yaml          ← global pipeline config
│   ├── tables/
│   │   ├── pos_transactions.yaml
│   │   ├── online_orders.yaml
│   │   ├── inventory_movements.yaml
│   │   ├── customer_profiles.yaml
│   │   ├── product_catalogue.yaml
│   │   ├── supplier_purchase_orders.yaml
│   │   ├── returns_exchanges.yaml
│   │   └── store_staff.yaml
│   └── consumption/
│       └── *.sql
├── engine/
│   ├── __init__.py
│   ├── base.py                ← shared: Spark session, config, logging (reuse)
│   ├── bronze.py              ← Landing → Bronze (Iceberg append)
│   ├── silver.py              ← Bronze → Silver (Iceberg merge/SCD2)
│   ├── gold.py                ← Silver → Gold (BigQuery data product)
│   ├── schema_evolver.py      ← layer-aware schema evolution
│   ├── reconcile.py           ← source↔bronze, bronze↔silver reconciliation
│   ├── policy.py              ← detective/preventative policy engine
│   └── cdc.py                 ← partial record reconstruction
├── datagen/
│   └── generate.py            ← generates all 8 datasets → GCS landing
├── scripts/
│   ├── run_bronze.sh
│   ├── run_silver.sh
│   ├── run_gold.sh
│   └── run_reconcile.sh
├── terraform/
│   └── main.tf               ← bucket, BLMS catalog, BQ dataset, IAM
└── cloudbuild.yaml            ← CI/CD for EastSide
```

---

## 11. Pipeline Flow

```
1. datagen/generate.py --project=bt-df-lkhouse
   └── Uploads raw files to gs://eastside-lakehouse/landing/{dataset}/v1/

2. engine/bronze.py --config gs://eastside-lakehouse/config/pipeline.yaml --all
   └── For each table:
       a. Read landing files (auto-detect format from config)
       b. Convert to Parquet/Iceberg schema
       c. CDC? → Reconstruct full rows from partials
       d. Compute row_hash (SHA256)
       e. Add metadata columns (_ingested_at, _source_file, _batch_id)
       f. Run detective policies → populate _dq_flags
       g. Schema evolution check (auto-accept all changes)
       h. Append to eastside.bronze.{table}
       i. Write reconciliation log (source ↔ bronze)

3. engine/silver.py --config gs://eastside-lakehouse/config/pipeline.yaml --all
   └── For each table:
       a. Read new records from bronze (incremental via _ingested_at > last_run)
       b. Dedup using row_hash
       c. Apply preventative DQ (reject/correct)
       d. Apply policy controls (mask, encrypt, filter, strip)
       e. Late arrival check:
          - Within window → merge into correct SCD2 slice
          - Outside window → quarantine
       f. Schema evolution check (non-breaking only)
       g. Merge into eastside.silver.{table} with SCD2 (valid_from/valid_to)
       h. Write reconciliation log (bronze ↔ silver)

4. engine/gold.py --config gs://eastside-lakehouse/config/pipeline.yaml --all
   └── For each consumption view:
       a. Read from silver (current records only: is_current=true)
       b. Validate against contract schema
       c. Write to BigQuery eastside_dataproduct.{view}
```

---

## 12. Technology Stack

| Component | Technology |
|---|---|
| Compute | Dataproc Serverless (PySpark) |
| Storage | GCS (Parquet files managed by Iceberg) |
| Table format | Apache Iceberg |
| Catalog | BigLake Metastore (BLMS) |
| Gold layer | BigQuery |
| Orchestration | Cloud Composer (Airflow) |
| Discovery | Ontika (shared instance) |
| Streaming | Spark Structured Streaming on Dataproc |
| Encryption keys | Cloud KMS |
| Column security | Dataplex / BigQuery column-level security |
| RAG vector store | ChromaDB (in-memory, ephemeral) |
| RAG embeddings | AWS Bedrock Mantle (Titan Embed v2) |
| MCP agent | Agentic LLM with tool-calling (9 tools) |
| Response cache | Hybrid exact-hash + semantic (ChromaDB + Firestore) |
| LLM | OpenAI GPT-OSS 120B on AWS Bedrock Mantle |
| CI/CD | Cloud Build |
| IaC | Terraform |

---

## 13. Ontika — Intelligent Data Discovery

Ontika is the shared discovery and governance layer that sits **before** the pipeline. It is reused as-is for EastSide — no changes needed to the Ontika codebase. EastSide datasets are onboarded through the same Ontika UI and API.

### 13.1 What Ontika Does

Ontika automates the manual work of onboarding a new dataset:
- Inspects source schema (field names, types)
- Matches fields to known business terms using a Knowledge Graph
- Classifies PII/sensitive fields
- Suggests DQ rules, primary keys, and foreign key relationships
- Proposes a Business Application and Data Domain assignment
- Generates the pipeline config YAML on approval

### 13.2 Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              ONTIKA                                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐   ┌──────────────────┐   ┌────────────────────────┐  │
│  │ Catalog      │   │ Knowledge Graph  │   │ Suggestion Engine      │  │
│  │ Reader       │──▶│ (Firestore)      │──▶│ (Embeddings + Rules)   │  │
│  │              │   │                  │   │                        │  │
│  │ • GCS scan   │   │ • Business terms │   │ • Synonym matching     │  │
│  │ • Schema     │   │ • Domains        │   │ • PII detection        │  │
│  │   inference  │   │ • BAs            │   │ • Key discovery        │  │
│  └──────────────┘   │ • Ref code sets  │   │ • DQ rule suggestion   │  │
│                     │ • Synonyms       │   │ • BA/Domain assignment │  │
│                     └──────────────────┘   └───────────┬────────────┘  │
│                                                        │               │
│  ┌──────────────┐   ┌──────────────────┐              ▼               │
│  │ KC Agent     │   │ LLM Client       │   ┌────────────────────────┐  │
│  │ (Q&A)       │   │ (Gemma2 on Azure) │   │ Config Generator       │  │
│  │              │   │                  │   │ (YAML output)          │  │
│  │ • Intent     │   │ • Catch-all Q&A  │   └───────────┬────────────┘  │
│  │   routing    │   │ • Complex        │               │               │
│  │ • Glossary   │   │   inference      │               ▼               │
│  │   queries    │   │                  │   ┌────────────────────────┐  │
│  │ • Linked     │   └──────────────────┘   │ Approval Handler       │  │
│  │   datasets   │                          │ • Write config to GCS  │  │
│  └──────────────┘                          │ • Update glossary      │  │
│                                            │ • Create new BDEs      │  │
│                                            └────────────────────────┘  │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│  ONTIKA WEB UI (React + Vite)                                           │
│  • Chat panel — natural language interaction                            │
│  • Home page — catalog tree (Domain → BA → Dataset → Columns)          │
│  • Data Products panel                                                  │
│  • Business Glossary panel                                              │
│  • Profiler panel                                                       │
│  • Results panel — discovery suggestions with approve/correct flow      │
└─────────────────────────────────────────────────────────────────────────┘
```

### 13.3 Discovery Flow (How a Dataset Gets Onboarded)

```
1. User says: "Onboard pos_transactions"
        │
        ▼
2. Catalog Reader scans GCS landing path
   → Reads schema from file (JSON/CSV/Avro/Parquet)
   → Extracts field names, inferred types
        │
        ▼
3. Fingerprinting (per field)
   → Synonym matching against Knowledge Graph business terms
   → Naming pattern rules (e.g. *_id → Identifier, *_amt → Measure)
   → PII detection (name/email/phone/dob patterns)
   → Confidence score per match
        │
        ▼
4. BA & Domain Assignment
   → Match dataset keywords against BA keyword lists
   → Highest confidence BA wins (e.g. pos_transactions → "Retail POS")
        │
        ▼
5. Suggestion presented to user in chat:
   "Discovered pos_transactions — 12 fields
    • Domain: Sales
    • Business App: Retail POS (87%)
    • Primary Key: transaction_id
    • PII: customer_id (linked to PII in customer_profiles)
    Say approve when ready, or correct anything."
        │
        ▼
6. User says: "approve"
        │
        ▼
7. Approval Handler:
   a. Generates table config YAML
   b. Uploads to gs://eastside-lakehouse/config/tables/pos_transactions.yaml
   c. Creates new BDEs in glossary (if any fields are novel)
   d. Links dataset to BA in catalog
   e. Generates data contract YAML
        │
        ▼
8. Pipeline picks up new config → bronze.py processes the dataset
```

### 13.4 Intent Routing (Chat)

The Ontika chat panel routes user input through a priority chain:

| Priority | Intent | Example | Handler |
|---|---|---|---|
| 1 | Landing list | "What's available?" | List GCS landing datasets |
| 2 | Profile | "Run profile on pos_transactions" | Spark profiler |
| 3 | Approve | "Approve" | Approval handler → GCS config |
| 4 | Generate config | "Show config" | YAML generator |
| 5 | Correction | "customer_id is not PII" | Update suggestion in session |
| 6 | Glossary/catalog Q&A | "Which datasets are linked to Retail POS?" | KC Agent (Firestore lookup) |
| 7 | Discovery-context Q&A | "Why is email marked PII?" | Answer from current suggestion |
| 8 | Onboard | "Onboard pos_transactions" | Discovery engine |
| 9 | General question | "What tables are in the curated layer?" | LLM (Gemma2) |
| 10 | Statement | "Thanks" | Acknowledge + guide |

### 13.5 Knowledge Graph (Seed Glossary)

The Knowledge Graph is seeded from `seed_glossary.yaml` and grows with every approval:

- **Business Applications**: Retail POS, E-commerce, Warehouse Management, Loyalty, Merchandising, Procurement, HR
- **Data Domains**: Sales, Customer, Product, Supply Chain, Procurement, HR
- **Business Terms**: ~40+ terms with synonyms, data types, PII flags, DQ rules
- **Reference Code Sets**: payment_methods, return_reasons, movement_types, loyalty_tiers, etc.

For EastSide, we'll extend the seed glossary with apparel-specific BAs, domains, and terms.

### 13.6 Technology Stack

| Component | Technology | Deployment |
|---|---|---|
| API | FastAPI (Python) | Cloud Run (`sd-web`) |
| Web UI | React + Vite + Tailwind | Same Cloud Run container |
| Session state | Firestore (`sessions/default`) | Survives scale-to-zero |
| Knowledge Graph | In-memory from `seed_glossary.yaml` | Loaded on startup |
| LLM | Gemma2 (latest) | Azure VM `4.242.19.167:11434` via Ollama |
| RAG Vector Store | ChromaDB (in-memory, ephemeral) | Same Cloud Run container |
| RAG Embeddings | AWS Bedrock Mantle (Titan Embed v2) | `https://bedrock-mantle.eu-north-1.api.aws/v1` |
| MCP Agent | Agentic loop with tool-calling | Same Cloud Run container |
| Response Cache | ChromaDB (semantic) + Firestore (persistence) | Same Cloud Run + Firestore |
| Profiler | PySpark | Separate Cloud Run (`sd-profiler`) |
| Config storage | GCS | `gs://{bucket}/framework/config/tables/` |
| CI/CD | Cloud Build | `cloudbuild-web.yaml` |

### 13.7 RAG Pipeline

Ontika uses Retrieval-Augmented Generation to ground LLM answers in real platform data.

```
┌─────────────────────────────────────────────────────────────────┐
│                     RAG PIPELINE                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  INDEX TIME (on deploy / POST /rag/index):                      │
│                                                                 │
│  Table configs ───┐                                              │
│  Seed glossary ───┤    ┌─────────┐    ┌───────────────┐          │
│  DATA_CATALOGUE ──┼──▶│ Chunker │──▶│ Ollama Embed │──┐       │
│  DESIGN.md ───────┤    └─────────┘    │ (Gemma2)      │  │       │
│  Pipeline logs ───┘                   └───────────────┘  │       │
│                                                       ▼       │
│                                              ┌───────────┐   │
│                                              │ ChromaDB  │   │
│                                              │ (vectors) │   │
│                                              └─────┬─────┘   │
│                                                    │         │
│  QUERY TIME (user asks a question):                │         │
│                                                    ▼         │
│  User question ──▶ Embed ──▶ Top-5 retrieve ─────────┐       │
│                                                    │       │
│                                                    ▼       │
│                                         ┌──────────────┐ │
│                                         │ LLM Prompt   │ │
│                                         │ + context    │ │
│                                         │ + question   │ │
│                                         └──────┬───────┘ │
│                                                │        │
│                                                ▼        │
│                                         Grounded answer │
│                                                         │
└─────────────────────────────────────────────────────────────────┘
```

**Cost: £0** — ChromaDB is open-source in-process, embeddings from existing Ollama instance.

### 13.8 MCP (Model Context Protocol) — Agentic AI

The MCP layer turns Ontika from a Q&A tool into an autonomous data operations agent.
This is the equivalent of Ab Initio's Agentic AI platform.

The MCP agent can **execute real SQL queries against BigQuery** and return actual data,
render results as **inline charts** in the UI, and chain multiple tool calls to answer
complex questions.

```
┌─────────────────────────────────────────────────────────────────┐
│                     MCP AGENT                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  User: "What's the DQ reject rate for pos_transactions?"        │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  LLM (Gemma2) sees:                                        │   │
│  │  • System prompt with tool descriptions                    │   │
│  │  • RAG context (relevant chunks)                           │   │
│  │  • User question                                           │   │
│  │                                                             │   │
│  │  LLM decides: call get_dq_report("pos_transactions")        │   │
│  └───────────────────────────┬─────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  TOOL EXECUTOR                                            │   │
│  │  • query_table        • get_table_config                  │   │
│  │  • get_table_stats    • list_tables                       │   │
│  │  • get_recon_status   • get_dq_report                     │   │
│  │  • get_pipeline_history • trigger_pipeline                 │   │
│  │  • refresh_rag_index                                      │   │
│  └───────────────────────────┬─────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  Tool result fed back to LLM → Final grounded answer            │
│                                                                 │
│  Max 3 iterations (LLM can chain multiple tool calls)           │
│  Guardrails: trigger_pipeline returns command, doesn't execute  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 13.9 EastSide Integration

For EastSide, Ontika needs:
1. **New BAs** added to `seed_glossary.yaml` (Retail POS, E-commerce, Warehouse, Loyalty, Merchandising, Procurement, HR)
2. **New domains** (Sales, Supply Chain, Procurement, HR)
3. **New business terms** (transaction_id, store_id, product_sku, basket_id, movement_type, po_number, etc.)
4. **Config output path** pointed to `gs://eastside-lakehouse/config/tables/` on approval
5. **Landing scan path** pointed to `gs://eastside-lakehouse/landing/`

These are config changes only — no code changes to Ontika.

---

## 14. Build Order

| Phase | Scope | Deliverable |
|---|---|---|
| 1 | Datagen + Landing | `generate.py` → 8 datasets in GCS |
| 2 | Bronze engine | `bronze.py` — format conversion, append, CDC reconstruct, detective policies, row_hash |
| 3 | Silver engine | `silver.py` — merge, SCD2, dedup, preventative policies, late arrival, masking |
| 4 | Gold engine | `gold.py` — BigQuery materialisation, contract enforcement |
| 5 | Reconciliation | `reconcile.py` — source↔bronze, bronze↔silver |
| 6 | Schema evolution | Layer-aware `schema_evolver.py` |
| 7 | Streaming | Streaming variant of bronze with hash dedup |
| 8 | Ontika integration | New BAs, domains, terms in seed glossary for EastSide |
| 9 | Terraform + CI/CD | Infrastructure and deployment automation |

---

## 15. Open Items

- [ ] Policy controls: Discuss with Rhys — which fields get write-time vs read-time protection
- [ ] Reconciliation: Confirm if Amanda wants it as part of pipeline or separate on-demand job
- [ ] Streaming: Confirm which EastSide datasets (if any) are real-time vs batch
- [ ] Gold layer: Confirm consumption views / data products required
- [ ] Compaction: Confirm Iceberg compaction strategy (time-based vs file-count threshold)
- [ ] RAG: Tune chunk size and top-K retrieval for best answer quality
- [x] MCP: query_table tool now executes real SQL against BigQuery
- [ ] MCP: Add lineage and schema history tools
- [x] Response cache: Hybrid exact + semantic (ChromaDB + Firestore)
- [x] UI: Light theme redesign with Google-style cards, Inter font, new logo
- [x] Charts: Inline bar chart rendering for aggregate/top-N query results
- [ ] Charts: Add pie chart and line chart support
