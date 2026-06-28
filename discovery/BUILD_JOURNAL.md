# Semantic Discovery — Complete Build Journal (Updated)

## What This Is

A GCP-native replacement for Ab Initio's Semantic Discovery (SD) tool. SD accelerates data onboarding by automatically classifying fields, matching them to business terms, detecting PII, suggesting DQ rules, and generating pipeline configurations — all from a conversational interface.

**Live URL:** https://semantic-discovery-978009776592.europe-west2.run.app
**Repo:** https://github.com/cprakash0105/bt-df-lkhouse-fw
**GCP Project:** bt-df-lkhouse
**Region:** europe-west2

---

## End-to-End Flow (Proven & Working)

```
Steward speaks to SD (natural language or YAML or CSV)
    │
    ▼
SD discovers: matches fields to BDEs, detects PII, suggests DQ, identifies BA
    │
    ▼
Steward says "approve all"
    │
    ├── Creates new BDE terms in Dataplex Glossary
    ├── Registers dataset in Dataplex Catalog
    ├── Pushes config YAML to GCS
    │
    ▼ (GCS event — Cloud Function triggers automatically)
Pipeline runs:
    ├── Ingest: Landing (JSONL) → Reservoir (Parquet)
    ├── Curate: Reservoir → CCN (Iceberg via BLMS) + DQ + dedup + schema evolution
    ├── Create BQ external table
    ├── Consume: CCN → Data Product (BigQuery native)
    └── Tag columns with metadata
    │
    ▼
Data queryable in BigQuery — consumers (apps, APIs, analysts) use it
```

---

## What Has Been Built & Deployed

### Semantic Discovery Engine (Cloud Run)

| Component | File | What It Does |
|-----------|------|-------------|
| Knowledge Graph | `engine/knowledge_graph.py` | Loads BDE terms from YAML + Dataplex. Synonym search, domain matching. |
| Rules Engine | `engine/rules_engine.py` | Deterministic patterns: naming (*_id, *_amt), PII (*email*, *pan*), FK heuristics. |
| Embedder | `engine/embedder.py` | Vertex AI / TF-IDF fallback. Semantic similarity for field→term matching. |
| Suggester | `engine/suggester.py` | Orchestrates KG + Rules + Embeddings. Full Discovery & Delta Discovery modes. |
| NL Parser | `engine/nl_parser.py` | Gemini REST API converts natural language to structured definition. |
| Profiler | `engine/profiler.py` | Analyses sample CSV data: type inference, PII from values, cardinality, ranges. |
| SQL Generator | `engine/sql_generator.py` | Gemini generates consumption SQL from natural language requirements. |
| Config Generator | `engine/config_generator.py` | Produces pipeline-ready YAML from approved suggestions. |
| Approval Handler | `engine/approval_handler.py` | Writes to Dataplex (BDEs, dataset entry) + pushes config to GCS. |
| LLM Client | `engine/llm_client.py` | Generic OpenAI-compatible client (Perplexity/Gemini/any). urllib only. |
| Catalog Reader | `engine/catalog_reader.py` | Reads/writes Dataplex Glossary terms. |
| Chainlit UI | `ui/app.py` | Conversational interface: NL, YAML, CSV, profile, approve, deploy sql. |

### Pipeline Framework (bt_df_lkhouse_fw)

| Component | File | What It Does |
|-----------|------|-------------|
| Ingest | `engine/ingest.py` | Landing JSONL → Reservoir Parquet. Idempotent, version-aware. |
| Curate | `engine/curate.py` | Reservoir → CCN Iceberg. DQ validation, dedup, type enforcement, schema evolution. |
| Consume | `engine/consume.py` | CCN → Data Product (BigQuery). Handles both SQL files and SCD YAML configs. |
| SCD Engine | `engine/scd.py` | Types 1, 2, 3, 4, 6 slowly changing dimensions in BigQuery. |
| Schema Evolver | `engine/schema_evolver.py` | Detects drift, applies/blocks changes based on governance config. |
| Audit | `engine/audit.py` | Writes pipeline execution metadata to Iceberg audit table. |
| Catalog Tag | `engine/catalog_tag.py` | Post-pipeline: registers physical tables in Dataplex. |
| Base | `engine/base.py` | Spark session, config loading (local + GCS), structured logging. |

### Pipeline Automation (Cloud Function)

| Component | File | What It Does |
|-----------|------|-------------|
| Orchestrator | `functions/main.py` | GCS trigger → ingest → curate → BQ table → consume → tag. Full automation. |
| Deploy script | `functions/deploy.sh` | One command to deploy the function. |

### Data Generator

| Component | File | What It Does |
|-----------|------|-------------|
| E-commerce data | `datagen/generate.py` | Customers, orders, payments, products. V1 baseline + V2 schema drift. |
| CIBIL feed | `datagen/generate_cibil.py` | Realistic bureau data: PAN, scores, enquiry dates, amounts. |

### Dataplex Knowledge Catalog

| What | Status |
|------|--------|
| Glossary: `enterprise-data-glossary` | ✅ 26 BDE terms with definitions, types, DQ, synonyms |
| Entry Types: cfu, domain, business-application, dataset | ✅ Created |
| Hierarchy: 2 CFUs, 5 Domains, 7 Business Applications | ✅ Registered |
| Dataset entries (from SD approval) | ✅ Auto-created on approve |
| Column-level TDE→BDE tagging | ⚠️ Data Catalog SDK has install issues; using BQ column descriptions as alternative |

---

## What Was Proven End-to-End

### CIBIL Bureau Feed — Full Pipeline Run

```
✅ SD: NL input → "I have a new CIBIL bureau feed..." → parsed by Gemini
✅ SD: Profiled CSV sample → detected PAN, email, phone from VALUES
✅ SD: Discovered fields → matched to 7/9 BDEs correctly
✅ SD: approve all → created BDEs in glossary + dataset in catalog + config to GCS
✅ Data Generator: 1000 CIBIL records → gs://bt-df-lkhouse-lakehouse/landing/cibil_bureau_feed/v1/
✅ Ingest: Landing → Reservoir (Parquet) via Dataproc Serverless
✅ Curate: Reservoir → CCN (Iceberg) with DQ validation + dedup via Dataproc + BLMS
✅ BQ External Table: Created via BLMS URI pointing to Iceberg metadata
✅ Consume: CCN → lakehouse_dataproduct.cibil_bureau_feed (BigQuery native)
✅ Data Product: loan_eligibility_360 (430 rows) — joins customers + CIBIL scores
```

---

## Dataplex API Learnings

| Issue | Fix |
|-------|-----|
| Glossary: use `BusinessGlossaryServiceClient` | Not `CatalogServiceClient` |
| Categories: `create_glossary_category` returns directly | No `.result()` needed |
| Terms can't nest under categories | Terms are flat under glossary only |
| Terms: use `term` and `term_id` fields | Not `glossary_term` |
| Category: use `category` and `category_id` | Not `glossary_category` |
| Entry FQN: must be `system:path` format | e.g., `custom:dataset/name` |
| `delete_glossary` needs children removed first | Delete terms, then categories, then glossary |
| BigQuery linked dataset recreation | Use external table with `blms://` URI instead |
| BQ connection SA needs `biglake.admin` + `storage.objectViewer` | Grant to `bqcx-*@gcp-sa-bigquery-condel.iam.gserviceaccount.com` |

## GCP Quota Learnings

| Issue | Resolution |
|-------|-----------|
| Dataproc Serverless needs 12 vCPUs minimum | Trial account has exactly 12 — no headroom |
| `CPUS_ALL_REGIONS` quota | Failed batches may temporarily hold quota; wait and retry |
| Gemini `gemini-2.0-flash` not in europe-west2 | Use REST API with API key (global endpoint) |
| Gemini free tier rate limit | Per-minute + per-day quota; shows `__QUOTA_EXCEEDED__` in UI |

---

## Dataproc Submit Commands (Reference)

### Ingest (no Iceberg needed)
```bash
gcloud dataproc batches submit pyspark bt_df_lkhouse_fw/engine/ingest.py \
  --project=bt-df-lkhouse --region=europe-west2 \
  --service-account=schema-poc-spark@bt-df-lkhouse.iam.gserviceaccount.com \
  --deps-bucket=gs://bt-df-lkhouse-lakehouse \
  --subnet=projects/bt-df-lkhouse/regions/europe-west2/subnetworks/schema-poc-network \
  --py-files=gs://bt-df-lkhouse-lakehouse/framework/bt_df_lkhouse_fw.zip \
  -- --config gs://bt-df-lkhouse-lakehouse/framework/config/pipeline.yaml --table TABLE_NAME --version v1 --project bt-df-lkhouse
```

### Curate (needs Iceberg JARs + catalog properties)
```bash
gcloud dataproc batches submit pyspark bt_df_lkhouse_fw/engine/curate.py \
  --project=bt-df-lkhouse --region=europe-west2 \
  --service-account=schema-poc-spark@bt-df-lkhouse.iam.gserviceaccount.com \
  --deps-bucket=gs://bt-df-lkhouse-lakehouse \
  --subnet=projects/bt-df-lkhouse/regions/europe-west2/subnetworks/schema-poc-network \
  --py-files=gs://bt-df-lkhouse-lakehouse/framework/bt_df_lkhouse_fw.zip \
  --jars=gs://bt-df-lkhouse-lakehouse/spark/iceberg-spark-runtime.jar,gs://bt-df-lkhouse-lakehouse/spark/biglake-catalog.jar \
  --properties="spark.sql.catalog.lakehouse=org.apache.iceberg.spark.SparkCatalog,spark.sql.catalog.lakehouse.catalog-impl=org.apache.iceberg.gcp.biglake.BigLakeCatalog,spark.sql.catalog.lakehouse.gcp_project=bt-df-lkhouse,spark.sql.catalog.lakehouse.gcp_location=europe-west2,spark.sql.catalog.lakehouse.blms_catalog=lakehouse,spark.sql.catalog.lakehouse.warehouse=gs://bt-df-lkhouse-lakehouse/ccn" \
  -- --config gs://bt-df-lkhouse-lakehouse/framework/config/pipeline.yaml --table TABLE_NAME --project bt-df-lkhouse
```

### Consume (pure Python, no Dataproc)
```bash
python3 -m bt_df_lkhouse_fw.engine.consume \
  --config gs://bt-df-lkhouse-lakehouse/framework/config/pipeline.yaml \
  --target TARGET_NAME --project bt-df-lkhouse
```

### Create BQ External Table (after curate)
```bash
bq query --use_legacy_sql=false "
CREATE OR REPLACE EXTERNAL TABLE \`bt-df-lkhouse.lakehouse_ccn.TABLE_NAME\`
WITH CONNECTION \`projects/bt-df-lkhouse/locations/europe-west2/connections/biglake-conn\`
OPTIONS (
  format = 'ICEBERG',
  uris = ['blms://projects/bt-df-lkhouse/locations/europe-west2/catalogs/lakehouse/databases/ccn/tables/TABLE_NAME']
)
"
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         GCP PROJECT: bt-df-lkhouse                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  SEMANTIC DISCOVERY (Cloud Run)          KNOWLEDGE CATALOG (Dataplex)         │
│  ┌─────────────────────────────┐        ┌─────────────────────────────────┐ │
│  │ Chainlit UI                  │        │ Glossary (26+ BDE terms)         │ │
│  │ NL Parser (Gemini)           │◄──────►│ Hierarchy (CFU→Domain→BA)        │ │
│  │ Profiler (CSV analysis)      │        │ Dataset entries                   │ │
│  │ Rules + Embeddings + KG      │        │ Column tags (BDE metadata)        │ │
│  │ Approval → GCS + Dataplex    │        └─────────────────────────────────┘ │
│  └──────────────┬──────────────┘                                              │
│                 │ pushes config                                                │
│                 ▼                                                              │
│  ┌─────────────────────────────┐        ┌─────────────────────────────────┐ │
│  │ GCS Bucket                   │───────►│ Cloud Function (Gen2)            │ │
│  │ • landing/ (JSONL)           │trigger │ • Submits Dataproc ingest        │ │
│  │ • reservoir/ (Parquet)       │        │ • Submits Dataproc curate        │ │
│  │ • ccn/ (Iceberg)             │        │ • Creates BQ external table      │ │
│  │ • framework/config/          │        │ • Runs consume SQL               │ │
│  └─────────────────────────────┘        │ • Tags columns                   │ │
│                                          └──────────────┬──────────────────┘ │
│                                                         │                     │
│  ┌─────────────────────────────┐                       │                     │
│  │ Dataproc Serverless          │◄──────────────────────┘                     │
│  │ • ingest.py (PySpark)        │                                             │
│  │ • curate.py (PySpark+Iceberg)│                                             │
│  └─────────────────────────────┘                                              │
│                                                                               │
│  ┌─────────────────────────────┐        ┌─────────────────────────────────┐ │
│  │ BigLake Metastore (BLMS)     │        │ BigQuery                         │ │
│  │ • Catalog: lakehouse         │───────►│ • lakehouse_ccn (external/Iceberg)│ │
│  │ • Database: ccn              │        │ • lakehouse_dataproduct (native)  │ │
│  │ • Tables: customers, orders, │        │   - customer_360                  │ │
│  │   cibil_bureau_feed, etc.    │        │   - loan_eligibility_360          │ │
│  └─────────────────────────────┘        │   - cibil_bureau_feed             │ │
│                                          └─────────────────────────────────┘ │
│                                                                               │
│  INFRA                                                                        │
│  ┌─────────────────────────────┐        ┌─────────────────────────────────┐ │
│  │ Artifact Registry            │        │ VPC + NAT + Subnet               │ │
│  │ Cloud Build (CI/CD)          │        │ IAM + Service Accounts           │ │
│  └─────────────────────────────┘        └─────────────────────────────────┘ │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## SCD Types Implemented

| Type | Behaviour | Use Case | Config Key |
|------|-----------|----------|------------|
| 1 | Overwrite (MERGE UPDATE) | Reference data, corrections | `scd_type: 1` |
| 2 | New row per change + effective_from/to/is_current/version | Customer attributes, audit trail | `scd_type: 2` |
| 3 | Previous value columns (prev_X) | Track one prior value | `scd_type: 3` |
| 4 | Current table + separate history table | Fast lookup + full archive | `scd_type: 4` |
| 6 | Hybrid 1+2+3 (current_ + prev_ + history rows) | Most complete tracking | `scd_type: 6` |

---

## Cost (Actual Usage — Day 1)

| Service | What happened | Cost |
|---------|-------------|------|
| Cloud Run (SD) | ~100 requests | < ₹5 |
| Cloud Build | 8 builds | < ₹20 |
| Dataproc Serverless | 5 batch jobs (ingest + curate attempts) | ~₹30 |
| GCS | Config files + data | < ₹1 |
| BigQuery | Queries + data products | < ₹5 |
| Dataplex | Glossary + entries | Free |
| Gemini API | NL parsing + SQL gen (hit free tier limit) | Free |
| **Total Day 1** | | **~₹60 ($0.70)** |

Remaining credits: ~₹28,540. Enough for months of operation.

---

## Known Issues / TODO

| Issue | Severity | Status |
|-------|----------|--------|
| Gemini free tier quota limit | Resolved | Using self-hosted Ollama (Gemma2 9B) on Azure VM |
| Data Catalog SDK install issues | Low | Using BQ column descriptions as alternative |
| `enquiry_date` sometimes flagged as PII | Low | Rules engine *date* pattern too broad |
| Profiler with 5 rows generates bad DQ rules | Medium | Need minimum row threshold; sample should come from actual data |
| BQ connection permission for Cloud Function | Resolved | Granted bigquery.connectionAdmin to appspot SA |
| Dataproc Serverless quota issues | Resolved | Using dedicated single-node cluster |
| LLM response time (~90s) | Acceptable | Chainlit/Cloud Run timeout set to 600s |

---

## How to Resume

### Start Azure LLM VM
```bash
az vm start --resource-group llm-server-rg --name llm-server
# IP: 4.242.19.167 (may change after restart)
```

### Start Dataproc cluster
```bash
gcloud dataproc clusters start lakehouse-cluster --region=europe-west2 --project=bt-df-lkhouse
```

### Stop when done
```bash
az vm deallocate --resource-group llm-server-rg --name llm-server
gcloud dataproc clusters stop lakehouse-cluster --region=europe-west2 --project=bt-df-lkhouse
```

### Deploy changes
```bash
cd ~/bt-df-lkhouse-fw && git pull
gcloud builds submit --config=cloudbuild.yaml --project=bt-df-lkhouse
```

### Deploy Cloud Function
```bash
cd ~/bt-df-lkhouse-fw && git pull
bash functions/deploy.sh
```

### Generate test data
```bash
python datagen/generate_all.py --project=bt-df-lkhouse
```

### Monitor pipeline
```bash
bq query --use_legacy_sql=false "SELECT dataset_name, stage, status, records_out, duration_seconds, event_time FROM \`bt-df-lkhouse.lakehouse_dataproduct.pipeline_monitor\` ORDER BY event_time DESC LIMIT 20"
```

### Onboard via SD
Open: https://semantic-discovery-978009776592.europe-west2.run.app

Example:
```
I have a new ekyc provider feed with customer_id, aadhaar_number, kyc_status, kyc_verified_date, verification_mode, full_name, address, photo_url, consent_timestamp and provider_reference_id
```
Then: `approve all`

---

## Next Steps (Prioritised)

1. **Onboard remaining use cases** — UPI transactions, loan repayment, customer complaints
2. **Fix profiler** — minimum row threshold, better type detection
3. **Column-level tagging** — resolve Data Catalog SDK or use BQ descriptions
4. **React UI** — replace Chainlit for multi-persona production use
5. **SCD implementation test** — run Type 2 on customer dimension with schema changes
