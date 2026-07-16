# Capability Demo Playbook

**Audience:** Non-technical stakeholders (Amanda, leadership)
**Approach:** Show, don't explain. Each demo is a short story with a before/after.

---

## Demo 1: Format Conversion

### Story
"Our source sends CSV. The platform converts it to Iceberg automatically — no manual work."

### Steps
1. Show the raw CSV file in GCS landing: `gsutil cat gs://eastside-lakehouse/landing/customers/v1/customers.csv | head -5`
2. Run bronze: `spark-submit eastside/engine/bronze.py --config ... --table customers --version v1`
3. Query BQ:
```sql
SELECT * FROM `bt-df-lkhouse.eastside_bronze.customers` LIMIT 5;
```
4. Point out: "Same data, now Iceberg. Queryable from BQ. Schema tracked. Metadata added. Zero manual conversion."

### What to say
> "Any format comes in — CSV, JSON, Avro, Parquet — the platform normalises it to Iceberg on ingest. One table format for everything downstream."

### Data needed
- `customers.csv` — already exists in `landing/customers/v1/`
- 10,000 rows, standard customer fields (name, email, address, DOB, etc.)

---

## Demo 2: Time Travel & Late Arriving Feed

### Story
"A transaction from 3 days ago finally arrives. The platform handles it gracefully — and I can show you what the table looked like before and after."

### Steps
1. Show current state:
```sql
SELECT COUNT(*) AS total, MAX(transaction_datetime) AS latest
FROM `bt-df-lkhouse.eastside_silver.pos_transactions`
WHERE is_current = true;
```
2. Load a late-arriving record (transaction dated 3 days ago, arriving now)
3. Run bronze + silver
4. Show the late record made it in:
```sql
SELECT transaction_id, transaction_datetime, _ingested_at
FROM `bt-df-lkhouse.eastside_silver.pos_transactions`
WHERE transaction_id = 'POS_LATE_001'
AND is_current = true;
```
5. Time travel — show table state BEFORE the late record:
```sql
SELECT COUNT(*) FROM `bt-df-lkhouse.eastside_bronze.pos_transactions`
FOR SYSTEM_TIME AS OF TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE);
```
6. Show quarantine — a record older than 7 days gets rejected:
```sql
SELECT * FROM `bt-df-lkhouse.eastside_silver.late_arrival_quarantine`
WHERE transaction_id = 'POS_LATE_002';
```

### What to say
> "Late data is reality. The platform accepts it within a configurable window — here it's 7 days. Anything older goes to quarantine for review. And with Iceberg time travel, I can always show you what the table looked like before the late record arrived. It's like an undo button for data."

### Data needed
- `late_arriving_batch.jsonl` — 5 records:
  - 3 records dated 2-3 days ago (within window → accepted)
  - 2 records dated 10+ days ago (outside window → quarantined)
- Place in `landing/pos_transactions/v1/` with current timestamp filename

---

## Demo 3: SCD2 in Silver

### Story
"Customer John moves from London to Manchester. We don't overwrite — we keep the full history. I can answer: where did John live on any date?"

### Steps
1. Load initial customer data (John in London):
```sql
SELECT customer_id, city, valid_from, valid_to, is_current
FROM `bt-df-lkhouse.eastside_silver.customers`
WHERE customer_id = 'CUST000001';
```
Result: 1 row — London, is_current=true

2. Load updated record (John now in Manchester) → run bronze + silver

3. Query again:
```sql
SELECT customer_id, city, valid_from, valid_to, is_current
FROM `bt-df-lkhouse.eastside_silver.customers`
WHERE customer_id = 'CUST000001'
ORDER BY valid_from;
```
Result: 2 rows:
- London, valid_from=Jan, valid_to=Today, is_current=false
- Manchester, valid_from=Today, valid_to=9999-12-31, is_current=true

4. Point-in-time query:
```sql
SELECT customer_id, city
FROM `bt-df-lkhouse.eastside_silver.customers`
WHERE customer_id = 'CUST000001'
  AND valid_from <= '2026-03-15'
  AND valid_to > '2026-03-15';
```
Result: London (because on March 15th, he still lived there)

### What to say
> "We never lose history. Every change creates a new version with timestamps. I can answer 'what was true on any date' — critical for regulatory reporting and audit."

### Data needed
- **Batch 1:** `customers_initial.jsonl` — 100 customers with addresses (CUST000001 = John Smith, London)
- **Batch 2:** `customers_update.jsonl` — 10 customers with changed fields (CUST000001 = John Smith, Manchester; others with new emails, phone numbers)
- Place in `landing/customers/v1/` and `landing/customers/v2/`

---

## Demo 4: Streaming Dedup

### Story
"Same transaction arrives twice — a retry from the POS system. Bronze keeps both. Silver deduplicates automatically."

### Steps
1. Load a batch that contains a duplicate transaction
2. Query bronze:
```sql
SELECT transaction_id, row_hash, _ingested_at, _source_file
FROM `bt-df-lkhouse.eastside_bronze.pos_transactions`
WHERE transaction_id = 'POS_DUP_001'
ORDER BY _ingested_at;
```
Result: 2 rows, same `row_hash`

3. Run silver
4. Query silver:
```sql
SELECT transaction_id, _ingested_at
FROM `bt-df-lkhouse.eastside_silver.pos_transactions`
WHERE transaction_id = 'POS_DUP_001'
AND is_current = true;
```
Result: 1 row only

5. Show the dedup stats:
```sql
SELECT
  COUNT(*) AS bronze_records,
  COUNT(DISTINCT row_hash) AS unique_records,
  COUNT(*) - COUNT(DISTINCT row_hash) AS duplicates_removed
FROM `bt-df-lkhouse.eastside_bronze.pos_transactions`;
```

### What to say
> "Bronze is the raw truth — it keeps everything, even duplicates. Silver is the clean truth — it deduplicates using a SHA256 hash of the business fields. The hash is persisted as a column, so you can always audit why something was considered a duplicate."

### Data needed
- `pos_with_duplicates.jsonl` — 50 records where 5 are exact duplicates of others (same business fields, different ingestion metadata)
- Place in `landing/pos_transactions/v1/`

---

## Demo 5: CDC & Partial Records

### Story
"Source sends a full record first. Then only the changed field. The platform reconstructs the complete row — ready for AI."

### Steps
1. Load full CDC record:
```sql
SELECT customer_id, first_name, last_name, email, city, _cdc_operation
FROM `bt-df-lkhouse.eastside_bronze.customers`
WHERE customer_id = 'CUST_CDC_001'
ORDER BY _ingested_at;
```
Result: 1 full row (INSERT)

2. Load partial update (only email changed):
   - Source sends: `{"customer_id": "CUST_CDC_001", "email": "new@email.com", "_cdc_operation": "UPDATE"}`

3. Run bronze
4. Query:
```sql
SELECT customer_id, first_name, last_name, email, city, _cdc_operation, _ingested_at
FROM `bt-df-lkhouse.eastside_bronze.customers`
WHERE customer_id = 'CUST_CDC_001'
ORDER BY _ingested_at;
```
Result: 2 rows:
- Row 1: Full record (INSERT) — all fields populated
- Row 2: Full record (UPDATE) — email changed, all other fields filled from last known state

5. Point out: "Row 2 has all 15 fields populated even though source only sent 2. The engine reconstructed it."

### What to say
> "CDC sources often send only what changed. That's fine for a changelog, but useless for AI or analytics — they need complete rows. The platform automatically fills in the gaps from the last known state. Every row in bronze is a full, consumable record."

### Data needed
- `cdc_customers_insert.jsonl` — 20 full records with `_cdc_operation: INSERT`
- `cdc_customers_update.jsonl` — 10 partial records with `_cdc_operation: UPDATE` (only 2-3 fields + PK)
- `cdc_customers_delete.jsonl` — 3 records with `_cdc_operation: DELETE` (PK only)
- Place in `landing/customers_cdc/v1/` (inserts) and `landing/customers_cdc/v2/` (updates + deletes)
- Table config needs `is_cdc: true`

---

## Demo 6: Policy Controls (PII Protection)

### Story
"Highly sensitive data is destroyed on write — irreversible. Less sensitive data is protected by role — you see it or you don't, depending on who you are."

### Steps
1. Query bronze (raw — detective only):
```sql
SELECT customer_id, first_name, email, date_of_birth, city
FROM `bt-df-lkhouse.eastside_bronze.customers`
WHERE customer_id = 'CUST000001';
```
Result: All fields visible in clear text

2. Run silver (applies write-time masking)
3. Query silver:
```sql
SELECT customer_id, first_name, email, date_of_birth, city
FROM `bt-df-lkhouse.eastside_silver.customers`
WHERE customer_id = 'CUST000001';
```
Result:
- `email` → `a3f2b8c9d1e4...` (SHA256 hashed — irreversible)
- `date_of_birth` → encrypted (reversible with KMS key)
- `first_name` → visible (less sensitive, read-time policy)
- `city` → visible or masked depending on user role (Dataplex policy tag)

4. Show Dataplex policy tag in console (screenshot or live):
   - "This column has a policy tag. Users with `roles/datacatalog.categoryFineGrainedReader` see the value. Others see NULL."

5. Show same query as a different service account (restricted role):
```sql
-- As restricted_analyst@bt-df-lkhouse.iam.gserviceaccount.com:
SELECT customer_id, first_name, city
FROM `bt-df-lkhouse.eastside_silver.customers`
WHERE customer_id = 'CUST000001';
```
Result: `city` = NULL (masked by policy)

### What to say
> "Two levels of protection. Highly sensitive — email, DOB — is destroyed or encrypted on write. Even a DBA can't reverse the SHA256 hash. Less sensitive — city, name — is controlled by Dataplex policies. Same table, different views depending on your role. No separate copies of data needed."

### Data needed
- Same `customers` dataset (already has PII fields: email, DOB, name, address)
- Table config with `pii_fields` defined (already exists)
- Dataplex policy tags configured on `city` column in silver
- Two service accounts: one with full access, one restricted

---

## Data Generation Summary

| Demo | Dataset | File | Records | Special Requirements |
|------|---------|------|---------|---------------------|
| 1 | customers | `customers.csv` | 10,000 | Standard CSV with header |
| 2 | pos_transactions | `late_arriving_batch.jsonl` | 5 | 3 within 7-day window, 2 outside |
| 3 | customers | `customers_initial.jsonl` + `customers_update.jsonl` | 100 + 10 | Known customer CUST000001 with address change |
| 4 | pos_transactions | `pos_with_duplicates.jsonl` | 50 | 5 exact duplicates (same business fields) |
| 5 | customers_cdc | `cdc_insert.jsonl` + `cdc_update.jsonl` + `cdc_delete.jsonl` | 20 + 10 + 3 | Partial records, `_cdc_operation` field |
| 6 | customers | Same as Demo 3 | — | Dataplex policy tags + two service accounts |

---

## Code Changes Needed

| Demo | What's Needed | Effort |
|------|---------------|--------|
| 1 | Nothing — already works | ✅ Done |
| 2 | Late arrival window config + quarantine table + time travel query support | Medium |
| 3 | Nothing — SCD2 already in silver.py | ✅ Done (verify with customers table) |
| 4 | Nothing — row_hash + dedup already works | ✅ Done (need test data) |
| 5 | Nothing — `reconstruct_cdc` already in bronze.py | ✅ Done (need CDC test data + config) |
| 6 | Dataplex policy tag setup (Terraform) + dual-mode masking in silver | Medium |

**Priority order for building:**
1. Generate all test data (one script)
2. Late arrival window + quarantine (Demo 2)
3. Dataplex policy tag integration (Demo 6)
4. Verify existing capabilities work with test data (Demos 3, 4, 5)
