# End-to-End Use Case: Onboarding Data for "CIBIL Check + Instant Loan with e-KYC"

## Business Context

A Product Manager wants to launch a new mobile banking feature: **"Check your CIBIL score and apply for a loan instantly with e-KYC"**.

This requires data from:
1. **CIBIL Bureau Feed** — credit scores, enquiry history
2. **e-KYC Provider Feed** — identity verification status

Neither dataset currently exists in the Data Platform. This document walks through the full onboarding journey — from business need to production data product — across all personas.

---

## GCP Environment

| Component | Service | URL/Location |
|-----------|---------|-------------|
| Semantic Discovery | Cloud Run | https://semantic-discovery-5uk6wi2iwq-nw.a.run.app |
| Knowledge Catalog | Dataplex Catalog | https://console.cloud.google.com/dataplex/glossaries?project=bt-df-lkhouse |
| Data Lake | GCS | gs://bt-df-lkhouse-lakehouse/ |
| Data Warehouse | BigQuery | bt-df-lkhouse.lakehouse_dataproduct |
| Iceberg Catalog | BigLake Metastore | lakehouse.ccn |
| Pipeline Config | GitHub | https://github.com/cprakash0105/bt-df-lkhouse-fw |

---

## Step 1: Business Analyst — Gap Analysis

**Persona:** Business Analyst
**Tool:** Dataplex Catalog (GCP Console)

### Action

1. Open https://console.cloud.google.com/dataplex/glossaries?project=bt-df-lkhouse
2. Search for: `credit`, `CIBIL`, `KYC`, `customer`
3. Identify what exists vs what's missing

### Expected Findings

| Data Needed | Available? | Source |
|-------------|-----------|--------|
| Customer ID | Yes | customer_master (existing) |
| Customer Name | Yes | customer_master (existing) |
| PAN Number | Yes | customer_master (existing) |
| CIBIL Score | **No** | Need to onboard from TransUnion |
| KYC Status | **No** | Need to onboard from e-KYC provider |
| Loan Eligibility | **No** | Data Product to be built |

### Outcome

BA raises onboarding request:
- "Onboard CIBIL Bureau Feed from TransUnion"
- "Onboard e-KYC Provider Feed from DigiLocker/NSDL"
- Attaches source specification documents

---

## Step 2: Architect — Solution Design

**Persona:** Data Platform Architect
**Tool:** Architecture docs

### Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Ingestion pattern | Batch (monthly pull from bureau) | CIBIL provides monthly files |
| Landing format | JSONL on GCS | Standard for bt_df_lkhouse_fw |
| Storage layers | Landing → Reservoir → CCN → Data Product | Existing framework |
| Data Product | `loan_eligibility_360` in BigQuery | Joins Customer + CIBIL + e-KYC |
| Consumer | Mobile app API reads BigQuery | Low latency via BQ cache |

### Outcome

Architect hands source specs to Data Steward for classification and onboarding.

---

## Step 3: Data Steward — Semantic Discovery (CIBIL Feed)

**Persona:** Data Steward
**Tool:** Semantic Discovery UI

### Action

1. Open https://semantic-discovery-5uk6wi2iwq-nw.a.run.app
2. Paste the following asset definition:

```yaml
name: cibil_bureau_feed
fields:
  - name: customer_id
    type: string
    description: "Internal customer reference"
  - name: pan_number
    type: string
    description: "Permanent Account Number"
  - name: cibil_score
    type: integer
    description: "Credit score from bureau"
  - name: score_date
    type: date
    description: "Date score was calculated"
  - name: enquiry_date
    type: date
    description: "Date of bureau enquiry"
  - name: loan_amount_requested
    type: decimal
    description: "Amount requested in loan application"
  - name: number_of_accounts
    type: integer
    description: "Total credit accounts"
  - name: overdue_amount
    type: decimal
    description: "Total overdue across accounts"
  - name: bureau_reference_id
    type: string
    description: "Bureau enquiry reference"
  - name: mobile_number
    type: string
    description: "Customer mobile on bureau record"
  - name: email_address
    type: string
    description: "Customer email on bureau record"
  - name: date_of_birth
    type: date
    description: "Customer DOB from bureau"
```

### Expected SD Response

| Field | Business Term | PII | DQ Rule |
|-------|--------------|-----|---------|
| customer_id | Customer Identifier | No | not_null, unique |
| pan_number | PAN Number | **Yes** | format: PAN |
| cibil_score | Credit Score | No | range [300,900] |
| score_date | (temporal) | No | not_null: false |
| enquiry_date | (temporal) | No | not_null: false |
| loan_amount_requested | Transaction Amount | No | positive |
| number_of_accounts | [NEW TERM] | No | - |
| overdue_amount | Transaction Amount | No | positive |
| bureau_reference_id | Bureau Reference | No | not_null, unique |
| mobile_number | Customer Phone | **Yes** | - |
| email_address | Customer Email | **Yes** | format: email |
| date_of_birth | Date of Birth | **Yes** | - |

**Business Application:** Credit Risk & Lending
**Schema Evolution:** Strict (PII dataset — block drop_column, type_narrow)

### Steward Actions

1. Review suggestions
2. Approve PII classifications
3. Create new business terms for unmatched fields (e.g., "Number of Accounts", "Overdue Amount")
4. Type `approve all`
5. Copy generated `config/tables/cibil_bureau_feed.yaml`

---

## Step 4: Data Steward — Semantic Discovery (e-KYC Feed)

**Persona:** Data Steward
**Tool:** Semantic Discovery UI

### Action

Paste the e-KYC definition:

```yaml
name: ekyc_provider_feed
fields:
  - name: customer_id
    type: string
    description: "Internal customer reference"
  - name: aadhaar_number
    type: string
    description: "Aadhaar UID"
  - name: kyc_status
    type: string
    description: "Verification status"
  - name: kyc_verified_date
    type: date
    description: "Date KYC was verified"
  - name: verification_mode
    type: string
    description: "Mode of verification (video/otp/biometric)"
  - name: full_name
    type: string
    description: "Name as per Aadhaar"
  - name: address
    type: string
    description: "Address as per Aadhaar"
  - name: photo_url
    type: string
    description: "URL to KYC photo"
  - name: consent_timestamp
    type: timestamp
    description: "When customer gave consent"
  - name: provider_reference_id
    type: string
    description: "e-KYC provider transaction ID"
```

### Expected SD Response

| Field | Business Term | PII | DQ Rule |
|-------|--------------|-----|---------|
| customer_id | Customer Identifier | No | not_null, unique |
| aadhaar_number | Aadhaar Number | **Yes** | format: aadhaar |
| kyc_status | KYC Status | No | accepted_values |
| kyc_verified_date | (temporal) | No | - |
| verification_mode | [NEW TERM] | No | accepted_values |
| full_name | Customer Name | **Yes** | not_null |
| address | Address | **Yes** | - |
| photo_url | [NEW TERM] | **Yes** | - |
| consent_timestamp | Event Timestamp | No | not_null |
| provider_reference_id | [NEW TERM] | No | not_null, unique |

**Business Application:** Customer Management
**Schema Evolution:** Strict (PII dataset)

### Steward Actions

1. Approve all suggestions
2. Create new terms: "Verification Mode", "Photo URL", "Provider Reference ID"
3. Add accepted_values for kyc_status: [verified, pending, rejected, expired]
4. Add accepted_values for verification_mode: [video, otp, biometric, offline]
5. Type `approve all`
6. Copy generated `config/tables/ekyc_provider_feed.yaml`

---

## Step 5: Governance Team — Review & Approve

**Persona:** Data Governance Officer
**Tool:** Dataplex Catalog

### Action

1. Open Dataplex Catalog
2. Review newly created terms from SD:
   - Confirm PII classifications are correct
   - Confirm data retention policies
   - Confirm masking requirements for non-prod
3. Sign off

### Checklist

| Check | Status |
|-------|--------|
| PAN, Aadhaar, DOB, Name, Address, Mobile, Email = PII | ✅ |
| PII fields masked in dev/test environments | ✅ |
| Bureau data retention: 7 years | ✅ |
| e-KYC consent data: must retain consent proof indefinitely | ✅ |
| No PII in Data Product without purpose limitation | ✅ |

---

## Step 6: Engineering — Build & Deploy Pipeline

**Persona:** Data Engineer
**Tool:** GitHub repo + Cloud Shell

### Action

1. Place SD-generated configs in the repo:

```
bt_df_lkhouse_fw/config/tables/cibil_bureau_feed.yaml    ← from SD
bt_df_lkhouse_fw/config/tables/ekyc_provider_feed.yaml   ← from SD
```

2. Create the Data Product SQL:

```sql
-- config/consumption/loan_eligibility_360.sql
CREATE OR REPLACE TABLE `bt-df-lkhouse.lakehouse_dataproduct.loan_eligibility_360` AS
SELECT
    c.customer_id,
    c.name,
    c.region,
    b.cibil_score,
    b.enquiry_date,
    b.number_of_accounts,
    k.kyc_status,
    k.kyc_verified_date,
    k.verification_mode,
    CASE
        WHEN b.cibil_score >= 750 AND k.kyc_status = 'verified' THEN 'pre_approved'
        WHEN b.cibil_score >= 650 AND k.kyc_status = 'verified' THEN 'eligible'
        WHEN b.cibil_score >= 650 AND k.kyc_status = 'pending' THEN 'kyc_required'
        ELSE 'not_eligible'
    END AS loan_eligibility_status
FROM `bt-df-lkhouse.lakehouse_ccn.customers` c
LEFT JOIN `bt-df-lkhouse.lakehouse_ccn.cibil_bureau_feed` b
    ON c.customer_id = b.customer_id
LEFT JOIN `bt-df-lkhouse.lakehouse_ccn.ekyc_provider_feed` k
    ON c.customer_id = k.customer_id
```

3. Generate test data (in Cloud Shell):

```bash
cd ~/bt-df-lkhouse-fw
python datagen/generate.py --project=bt-df-lkhouse --version=v1 --scale=0.01
```

4. Run the pipeline:

```bash
# Ingest: Landing → Reservoir
python -m bt_df_lkhouse_fw.engine.ingest --all --version=v1 --project=bt-df-lkhouse --region=europe-west2

# Curate: Reservoir → CCN (Iceberg)
python -m bt_df_lkhouse_fw.engine.curate --all --project=bt-df-lkhouse --region=europe-west2

# Consume: CCN → Data Product (BigQuery)
python -m bt_df_lkhouse_fw.engine.consume --all --project=bt-df-lkhouse --region=europe-west2
```

### What the Pipeline Does

```
gs://bt-df-lkhouse-lakehouse/landing/cibil_bureau_feed/v1/*.jsonl
        │
        ▼  [ingest.py — Dataproc Serverless]
gs://bt-df-lkhouse-lakehouse/reservoir/cibil_bureau_feed/ (Parquet)
        │
        ▼  [curate.py — Dataproc Serverless + SchemaEvolver]
gs://bt-df-lkhouse-lakehouse/ccn/cibil_bureau_feed/ (Iceberg via BLMS)
        │  • DQ validation (not_null, range, format)
        │  • Deduplication (customer_id + ingestion_ts DESC)
        │  • Schema evolution governance (block drop_column)
        │
        ▼  [consume.py — BigQuery SQL]
bt-df-lkhouse.lakehouse_dataproduct.loan_eligibility_360 (BigQuery native)
```

---

## Step 7: Testing — Validate

**Persona:** QA / Testing Team
**Tool:** BigQuery + Pipeline Logs

### Validation Queries

```sql
-- Check CIBIL score range
SELECT COUNT(*) as violations
FROM `bt-df-lkhouse.lakehouse_ccn.cibil_bureau_feed`
WHERE cibil_score < 300 OR cibil_score > 900;
-- Expected: 0

-- Check PAN format
SELECT COUNT(*) as violations
FROM `bt-df-lkhouse.lakehouse_ccn.cibil_bureau_feed`
WHERE NOT REGEXP_CONTAINS(pan_number, r'^[A-Z]{5}[0-9]{4}[A-Z]$');
-- Expected: 0

-- Check KYC accepted values
SELECT DISTINCT kyc_status
FROM `bt-df-lkhouse.lakehouse_ccn.ekyc_provider_feed`;
-- Expected: only verified, pending, rejected, expired

-- Check Data Product completeness
SELECT loan_eligibility_status, COUNT(*) as cnt
FROM `bt-df-lkhouse.lakehouse_dataproduct.loan_eligibility_360`
GROUP BY 1;
-- Expected: distribution across pre_approved, eligible, kyc_required, not_eligible

-- Check no PII leaks in data product
SELECT * FROM `bt-df-lkhouse.lakehouse_dataproduct.loan_eligibility_360` LIMIT 5;
-- Expected: no pan_number, aadhaar, dob, mobile, email visible
```

### Schema Evolution Test

```sql
-- Simulate: source adds a new column (should be ALLOWED)
-- curate.py will detect add_column → SchemaEvolver allows it

-- Simulate: source drops customer_id (should be BLOCKED)
-- curate.py will detect drop_column → SchemaEvolver raises RuntimeError → pipeline fails
-- This is correct behaviour — governance working as designed
```

---

## Step 8: Application Support — Monitor

**Persona:** App Support / SRE
**Tool:** Cloud Monitoring + Pipeline Audit + Dataplex Lineage

### Monitoring

| What to Monitor | Where |
|----------------|-------|
| Pipeline success/failure | Cloud Composer DAG runs |
| DQ violations | `lakehouse.ccn.pipeline_audit` table |
| Schema change attempts | Pipeline logs (SchemaEvolver output) |
| Cloud Run health (SD) | Cloud Run metrics |
| Data freshness | BigQuery `__TABLES__` metadata |

### Incident Response

```
Alert: "loan_eligibility_360 not refreshed in 24 hours"
        │
        ▼
Check Cloud Composer → DAG failed at curate step
        │
        ▼
Check logs → SchemaEvolver BLOCKED: "type_narrow on cibil_score (int → string)"
        │
        ▼
Root cause: Bureau provider changed schema without notice
        │
        ▼
Resolution: Contact bureau team → revert change → re-run pipeline
```

### Lineage (in Dataplex)

```
TransUnion CIBIL API
    → gs://bt-df-lkhouse-lakehouse/landing/cibil_bureau_feed/
        → gs://bt-df-lkhouse-lakehouse/reservoir/cibil_bureau_feed/
            → lakehouse.ccn.cibil_bureau_feed (Iceberg)
                → bt-df-lkhouse.lakehouse_dataproduct.loan_eligibility_360
                    → Mobile App Loan Eligibility API
```

---

## Summary: What Each Persona Uses

| Persona | Primary Tool | What They Do |
|---------|-------------|-------------|
| Business User | (none — raises request) | Defines the business need |
| Business Analyst | **Dataplex Catalog** | Gap analysis — what data exists, what's missing |
| Architect | Architecture docs | Designs the end-to-end solution |
| Data Steward | **Semantic Discovery** | Classifies fields, approves metadata, generates config |
| Governance | **Dataplex Catalog** | Reviews PII, retention, masking policies |
| Engineering | **bt_df_lkhouse_fw** + Cloud Shell | Deploys pipeline configs, runs ingestion |
| Testing | **BigQuery** | Validates DQ rules, schema governance |
| App Support | **Cloud Monitoring** + Dataplex Lineage | Monitors health, traces failures |

---

## Time Estimate: With SD vs Without SD

| Activity | Without SD | With SD |
|----------|-----------|---------|
| Classify 12 fields (CIBIL) | 2-3 hours | **5 minutes** |
| Classify 10 fields (e-KYC) | 2-3 hours | **5 minutes** |
| Define DQ rules | 1-2 hours | **auto-suggested** |
| Identify PII | 30 min (risk of missing) | **auto-detected** |
| Write pipeline YAML | 1-2 hours | **auto-generated** |
| Governance review | 2-3 hours | 1 hour (pre-filled) |
| **Total onboarding** | **1-2 weeks** | **1-2 days** |

---

## How to Run This Yourself

### Prerequisites

- GCP project `bt-df-lkhouse` with APIs enabled
- Semantic Discovery deployed at https://semantic-discovery-5uk6wi2iwq-nw.a.run.app
- Dataplex Catalog populated (33 terms imported)
- bt_df_lkhouse_fw repo cloned in Cloud Shell

### Quick Start

1. Open SD: https://semantic-discovery-5uk6wi2iwq-nw.a.run.app
2. Paste the CIBIL YAML from Step 3 above
3. Review suggestions
4. Type `approve all`
5. Copy the generated YAML
6. Repeat for e-KYC feed (Step 4)
7. In Cloud Shell, add the YAMLs to the repo and run the pipeline (Step 6)
8. Query BigQuery to validate (Step 7)
