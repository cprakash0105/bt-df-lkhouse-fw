# Final Rundown: What We Built & How to Validate

## Prerequisites

Before validation, ensure these are running:

```bash
# 1. Azure LLM VM
az vm start --resource-group llm-server-rg --name llm-server
# Verify: curl -s http://4.242.19.167:11434/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"gemma2","messages":[{"role":"user","content":"hello"}]}'

# 2. Dataproc cluster
gcloud dataproc clusters start lakehouse-cluster --region=europe-west2 --project=bt-df-lkhouse

# 3. SD (Cloud Run - always on, scales to zero)
# Verify: open https://semantic-discovery-978009776592.europe-west2.run.app

# 4. Cloud Function (always deployed)
# Verify: gcloud functions describe pipeline-orchestrator --region=europe-west2 --project=bt-df-lkhouse --format="value(state)"
```

---

## Component Inventory

### Semantic Discovery (Cloud Run)

| Component | File | Validates |
|-----------|------|-----------|
| Knowledge Graph | `discovery/engine/knowledge_graph.py` | Loads 26+ BDEs from Dataplex + local YAML |
| Rules Engine | `discovery/engine/rules_engine.py` | Pattern matching: naming, PII, FK, types |
| Embedder | `discovery/engine/embedder.py` | Semantic similarity (TF-IDF fallback) |
| Suggester | `discovery/engine/suggester.py` | Full Discovery + Delta Discovery |
| NL Parser | `discovery/engine/nl_parser.py` | Natural language → structured JSON |
| Profiler | `discovery/engine/profiler.py` | CSV analysis → type/PII/cardinality detection |
| SQL Generator | `discovery/engine/sql_generator.py` | NL → BigQuery SQL |
| Config Generator | `discovery/engine/config_generator.py` | Suggestions → pipeline YAML |
| Contract Generator | `discovery/engine/contract_generator.py` | Suggestions → data contract |
| Approval Handler | `discovery/engine/approval_handler.py` | Writes to Dataplex + GCS |
| LLM Client | `discovery/engine/llm_client.py` | Generic OpenAI-compatible (Ollama/Gemini/any) |
| Chainlit UI | `discovery/ui/app.py` | Conversational interface |

### Pipeline Framework (Dataproc)

| Component | File | Validates |
|-----------|------|-----------|
| Ingest | `bt_df_lkhouse_fw/engine/ingest.py` | Landing JSONL → Reservoir Parquet |
| Curate | `bt_df_lkhouse_fw/engine/curate.py` | DQ + dedup + schema evolution + Iceberg write |
| Consume | `bt_df_lkhouse_fw/engine/consume.py` | SQL + SCD execution in BigQuery |
| SCD Engine | `bt_df_lkhouse_fw/engine/scd.py` | Types 1, 2, 3, 4, 6 |
| Schema Evolver | `bt_df_lkhouse_fw/engine/schema_evolver.py` | Drift detection + governance enforcement |

### Automation (Cloud Function)

| Component | File | Validates |
|-----------|------|-----------|
| Pipeline Orchestrator | `functions/main.py` | GCS trigger → full pipeline execution |
| Pipeline Monitor | `functions/monitor.py` | BQ audit table for all events |

### Infrastructure

| Component | Location | Validates |
|-----------|----------|-----------|
| GCS Bucket | gs://bt-df-lkhouse-lakehouse | All data layers |
| BigLake Metastore | lakehouse.ccn | Iceberg catalog |
| BigQuery | lakehouse_ccn + lakehouse_dataproduct | External tables + data products |
| Dataplex Glossary | enterprise-data-glossary | 26 BDE terms |
| Dataplex Hierarchy | CFU → Domain → BA (14 entries) | Organisational structure |
| Dataproc Cluster | lakehouse-cluster | Single-node Spark execution |
| Cloud Run | semantic-discovery | SD UI |
| Azure VM | 4.242.19.167:11434 | Ollama + Gemma2 9B |

---

## Validation Steps

### Test 1: SD Discovery (NL Input)

**What it proves:** AI-assisted metadata classification from natural language

**Steps:**
1. Open https://semantic-discovery-978009776592.europe-west2.run.app
2. Type: `I have a new upi transactions feed with transaction_id, payer_vpa, payee_vpa, amount, transaction_date, status, remitter_account, beneficiary_account, mcc_code and device_id`
3. Verify SD responds with:
   - Business Application suggestion
   - Field-to-BDE matching table
   - PII detection (payer_vpa, payee_vpa, remitter_account, beneficiary_account)
   - DQ rule suggestions
   - Primary key suggestion

**Expected:** 60%+ fields matched, PII detected, DQ rules suggested within 30 seconds.

---

### Test 2: SD Discovery (CSV Profiling)

**What it proves:** PII detection from actual values, not just field names

**Steps:**
1. In SD, type:
```
profile upi_transactions
transaction_id,payer_vpa,payee_vpa,amount,transaction_date,status
UPI123456789012,user42@okaxis,merchant100@paytm,499.99,2024-05-15T14:30:00,success
UPI234567890123,user88@oksbi,merchant200@ybl,1500.00,2024-05-16T09:15:00,success
UPI345678901234,user12@paytm,merchant300@okaxis,250.00,2024-05-16T11:45:00,failed
UPI456789012345,user55@ybl,merchant400@oksbi,8999.99,2024-05-17T16:20:00,success
UPI567890123456,user23@ibl,merchant500@paytm,75.50,2024-05-18T08:00:00,pending
```

2. Verify profiler detects:
   - `transaction_id`: unique, string, likely PK
   - `amount`: decimal, positive, range [75.50, 8999.99]
   - `status`: low cardinality (5 values), reference set
   - Type inference from values

**Expected:** Profile report with types, cardinality, PII flags, DQ suggestions.

---

### Test 3: Full Automation (Approve → Data in BigQuery)

**What it proves:** End-to-end automation from approval to queryable data product

**Prerequisites:**
```bash
python datagen/generate_all.py --project=bt-df-lkhouse
```

**Steps:**
1. In SD, onboard a dataset (e.g., UPI transactions from Test 1)
2. Type: `approve all`
3. Monitor:
```bash
gcloud functions logs read pipeline-orchestrator --region=europe-west2 --project=bt-df-lkhouse --limit=20
```
4. Wait 3-5 minutes
5. Verify:
```bash
bq query --use_legacy_sql=false "SELECT count(*) as cnt FROM \`bt-df-lkhouse.lakehouse_dataproduct.upi_transactions\`"
```

**Expected:** Pipeline runs automatically. Data product appears with correct row count.

---

### Test 4: Pipeline Monitor (Audit Trail)

**What it proves:** Full observability of every pipeline event

**Steps:**
```bash
bq query --use_legacy_sql=false "
SELECT dataset_name, stage, status, records_in, records_out,
       records_rejected, duration_seconds, event_time
FROM \`bt-df-lkhouse.lakehouse_dataproduct.pipeline_monitor\`
ORDER BY event_time DESC
LIMIT 30
"
```

**Expected:** Rows showing ingest (started/succeeded), curate (started/succeeded), consume (started/succeeded) with durations and record counts.

---

### Test 5: Data Contract Generation

**What it proves:** Declarative contracts generated automatically from discovery

**Steps:**
1. After approving any dataset, check:
```bash
gsutil cat gs://bt-df-lkhouse-lakehouse/contracts/ekyc_provider_feed/v1.0.0.yaml
```

**Expected:** Full contract YAML with schema, quality SLAs, governance rules, evolution policies, consumer list.

---

### Test 6: Schema Evolution Governance

**What it proves:** Breaking changes are blocked, safe changes are allowed

**Steps:**
1. Generate V2 data with a schema change:
```bash
python datagen/generate.py --project=bt-df-lkhouse --version=v2
```
2. Run ingest + curate for V2
3. Check logs for schema evolution messages:
   - `add_column` → ALLOWED (new column appears)
   - `type_widen` (int → bigint) → ALLOWED
   - `drop_column` → BLOCKED (pipeline fails with clear error)

**Expected:** Safe changes pass, dangerous changes are blocked with governance error.

---

### Test 7: SQL Generation from NL

**What it proves:** AI generates executable data product SQL from business requirements

**Steps:**
1. In SD, type:
```
data product customer_spend_360 joining customers with upi_transactions on customer_id through remitter_account. Include customer_id, name, total transactions, total spend, average transaction value.
```
2. Wait ~90 seconds (Gemma2 processing)
3. Verify generated SQL is valid BigQuery
4. Type: `deploy sql`
5. Verify SQL pushed to GCS:
```bash
gsutil cat gs://bt-df-lkhouse-lakehouse/framework/config/consumption/customer_spend_360.sql
```

**Expected:** Valid CREATE OR REPLACE TABLE SQL with correct JOINs and aggregations.

---

### Test 8: Knowledge Catalog Verification

**What it proves:** Glossary, hierarchy, and dataset entries exist in Dataplex

**Steps:**
1. Open https://console.cloud.google.com/dataplex/glossaries?project=bt-df-lkhouse
2. Verify: 26+ Business Data Element terms
3. Open https://console.cloud.google.com/dataplex/catalog?project=bt-df-lkhouse
4. Verify: Entry Types (cfu, domain, business-application, dataset)
5. Verify: Entries (Consumer Banking, Credit, Loan Origination System, etc.)
6. Verify: Dataset entries created by SD on approval

**Expected:** Full hierarchy visible. BDEs with definitions, types, classifications.

---

### Test 9: SCD Type 2 (Customer Dimension)

**What it proves:** Historical tracking of attribute changes

**Steps:**
```bash
# Consume with SCD config
python3 -m bt_df_lkhouse_fw.engine.consume \
  --config gs://bt-df-lkhouse-lakehouse/framework/config/pipeline.yaml \
  --target dim_customer --project bt-df-lkhouse
```

Verify:
```bash
bq query --use_legacy_sql=false "
SELECT customer_id, loyalty_tier, is_current, effective_from, version
FROM \`bt-df-lkhouse.lakehouse_dataproduct.dim_customer\`
WHERE customer_id = 1
ORDER BY version
"
```

**Expected:** Multiple rows per customer showing history of changes with effective dates.

---

### Test 10: Multi-Dataset Onboarding (Stress Test)

**What it proves:** Platform handles multiple datasets flowing through simultaneously

**Steps:**
1. Ensure all data is generated: `python datagen/generate_all.py`
2. Onboard all remaining datasets via SD one by one:
   - `upi_transactions`
   - `loan_repayment_schedule`
   - `customer_complaints`
3. Monitor all pipelines:
```bash
bq query --use_legacy_sql=false "
SELECT dataset_name, stage, status, records_out, event_time
FROM \`bt-df-lkhouse.lakehouse_dataproduct.pipeline_monitor\`
ORDER BY event_time DESC
LIMIT 50
"
```
4. Verify all data products exist:
```bash
bq ls bt-df-lkhouse:lakehouse_dataproduct
```

**Expected:** All datasets visible as tables/views in lakehouse_dataproduct.

---

## Cleanup (When Done)

```bash
# Stop Dataproc cluster (saves ~$3/day)
gcloud dataproc clusters stop lakehouse-cluster --region=europe-west2 --project=bt-df-lkhouse

# Stop Azure LLM VM (saves ~$5/day)
az vm deallocate --resource-group llm-server-rg --name llm-server

# Cloud Run scales to zero automatically — no action needed
# Cloud Function — no cost when not triggered
```

---

## Summary

| What | Status | Evidence |
|------|--------|----------|
| Semantic Discovery (NL + YAML + CSV) | ✅ Working | Cloud Run UI live |
| Knowledge Catalog (Glossary + Hierarchy) | ✅ Working | 26 BDEs + 14 entries in Dataplex |
| Self-hosted LLM (Gemma2 on Azure) | ✅ Working | http://4.242.19.167:11434 |
| Pipeline automation (Cloud Function) | ✅ Working | Triggers on GCS config upload |
| Data layers (Landing→Reservoir→CCN→DP) | ✅ Working | GCS + Iceberg + BigQuery |
| DQ validation | ✅ Working | not_null, range, format, positive enforced |
| Schema evolution governance | ✅ Working | add_column allowed, drop_column blocked |
| Data contracts | ✅ Working | Auto-generated on approval |
| Pipeline monitor | ✅ Working | BQ audit table with all events |
| SCD Types 1-6 | ✅ Built | Config-driven in consume engine |
| Column-level security | ✅ Built | Policy Tags (needs BQ Enterprise for masking) |
| SQL generation from NL | ✅ Working | Gemma2 generates valid BigQuery SQL |
| Multi-dataset proven | ✅ CIBIL + e-KYC loaded | 1800 rows across 2 data products |
