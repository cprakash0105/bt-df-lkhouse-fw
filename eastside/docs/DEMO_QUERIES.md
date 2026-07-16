# Schema Evolution Demo — BigQuery Queries

**Table:** `bt-df-lkhouse.eastside_bronze.pos_transactions`

---

## 1. Schema Evolution Proof

**What I'm asking:** Show me how many records exist per schema version, and which columns are populated in each.

```sql
SELECT
  CASE
    WHEN loyalty_points_earned IS NULL AND unit_price IS NOT NULL THEN 'v1_baseline'
    WHEN loyalty_points_earned IS NOT NULL AND unit_price IS NOT NULL THEN 'v2_add_column'
    WHEN unit_price IS NULL THEN 'v3_drop_column'
    ELSE 'unknown'
  END AS version,
  COUNT(*) AS records,
  COUNT(loyalty_points_earned) AS has_loyalty_points,
  COUNT(unit_price) AS has_unit_price
FROM `bt-df-lkhouse.eastside_bronze.pos_transactions`
GROUP BY 1 ORDER BY 1;
```

**What the results show:**
- v1 rows have `has_loyalty_points = 0` — the column didn't exist when these were written. Iceberg returns NULL at read time without rewriting original Parquet files.
- v2 rows have both columns populated — schema evolution added the new column seamlessly.
- v3 rows have `has_unit_price = 0` — source dropped the column, bronze NULL-filled it to preserve table schema.
- **Proves:** Zero-cost schema evolution. No data rewrite. No data loss.

---

## 2. Table Schema (Column Inventory)

**What I'm asking:** What does the current table schema look like? Show me every column, its type, and position.

```sql
SELECT column_name, data_type, ordinal_position
FROM `bt-df-lkhouse.eastside_bronze.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'pos_transactions'
ORDER BY ordinal_position;
```

**What the results show:**
- The schema is the **union of all versions** — includes `loyalty_points_earned` (added in v2) and `unit_price` (dropped in v3 but still present).
- Platform metadata columns visible: `row_hash`, `_ingested_at`, `_source_file`, `_batch_id`, `_dq_flags`.
- **Proves:** Columns are never physically removed. Bronze accepts everything. Schema only grows.

---

## 3. Data Lineage by Source File

**What I'm asking:** For each file that was ingested, how many records came from it, and what schema version was it?

```sql
SELECT
  _source_file,
  _batch_id,
  COUNT(*) AS records,
  MIN(transaction_datetime) AS earliest_txn,
  MAX(transaction_datetime) AS latest_txn,
  COUNT(loyalty_points_earned) AS has_loyalty,
  COUNT(unit_price) AS has_price
FROM `bt-df-lkhouse.eastside_bronze.pos_transactions`
GROUP BY 1, 2
ORDER BY _batch_id DESC;
```

**What the results show:**
- Every record is traceable to its source file and batch.
- You can see exactly when each schema version was ingested.
- `has_loyalty` and `has_price` columns reveal which schema version each file carried.
- **Proves:** Full audit trail built into the data. If something goes wrong, trace it back to the exact source file.

---

## 4. DQ Flags (Detective Policies)

**What I'm asking:** Show me records that have data quality issues flagged by bronze.

```sql
SELECT
  transaction_id,
  _dq_flags,
  unit_price,
  customer_id
FROM `bt-df-lkhouse.eastside_bronze.pos_transactions`
WHERE ARRAY_LENGTH(_dq_flags) > 0
LIMIT 20;
```

**What the results show:**
- Bronze flags issues (NULL primary keys, non-positive values, invalid enums) but **never rejects**.
- Flagged records are still ingested — zero data loss at bronze layer.
- Downstream layers (silver) use these flags to decide what to enforce.
- **Proves:** Detective-only policy at bronze. Flag, don't reject. Silver decides enforcement.

---

## 5. NULL Pattern Deep Dive (One Record Per Batch)

**What I'm asking:** Pick one record from each ingestion batch and show me how the schema differs across them.

```sql
WITH ranked AS (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY _batch_id ORDER BY transaction_id) AS rn
  FROM `bt-df-lkhouse.eastside_bronze.pos_transactions`
)
SELECT transaction_id, unit_price, loyalty_points_earned, _ingested_at, _batch_id
FROM ranked WHERE rn = 1
ORDER BY _ingested_at;
```

**What the results show:**
- Same table, three different schema states coexisting side by side.
- v1 record: `loyalty_points_earned = NULL`, `unit_price = populated`
- v2 record: both populated
- v3 record: `unit_price = NULL`, `loyalty_points_earned = populated`
- **Proves:** Iceberg's schema versioning by column ID. Old data retains original schema, new data uses new schema, queries return a unified view. No data migration.

---

## 6. Ingestion History

**What I'm asking:** Show me every pipeline run — when it happened, how many records it processed, from how many files.

```sql
SELECT
  DATE(_ingested_at) AS ingestion_date,
  FORMAT_TIMESTAMP('%H:%M', _ingested_at) AS ingestion_time,
  _batch_id,
  COUNT(*) AS records_ingested,
  COUNT(DISTINCT _source_file) AS files_processed
FROM `bt-df-lkhouse.eastside_bronze.pos_transactions`
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 2 DESC;
```

**What the results show:**
- Complete pipeline execution history visible directly from the data.
- Each batch is identifiable and countable.
- Supports reconciliation: compare source count vs bronze count per run.
- **Proves:** Operational observability without a separate monitoring system.

---

## 7. Silver Layer — Governed Data

**What I'm asking:** What made it through to the governed silver layer? How does it compare to bronze?

```sql
SELECT
  COUNT(*) AS total_records,
  COUNT(DISTINCT transaction_id) AS unique_transactions,
  COUNT(loyalty_points_earned) AS has_loyalty_points,
  COUNT(unit_price) AS has_unit_price
FROM `bt-df-lkhouse.eastside_silver.pos_transactions`
WHERE is_current = true;
```

**What the results show:**
- Silver only contains data that passed governance checks.
- If v3 was blocked, silver won't have records with NULL `unit_price`.
- `is_current = true` gives the latest SCD2 state of each record.
- **Proves:** Silver enforces schema contracts. Destructive changes (drop_column) are blocked. Consumers are protected.

---

## 8. Bronze vs Silver (Governance Gap)

**What I'm asking:** How many records does each layer have? What's the difference?

```sql
SELECT 'bronze' AS layer, COUNT(*) AS records
FROM `bt-df-lkhouse.eastside_bronze.pos_transactions`
UNION ALL
SELECT 'silver' AS layer, COUNT(*) AS records
FROM `bt-df-lkhouse.eastside_silver.pos_transactions`
WHERE is_current = true;
```

**What the results show:**
- Bronze has MORE records than silver (because bronze accepts everything).
- The difference = records blocked by governance (schema violations + DQ rejects).
- This is the **governance gap** — intentional, auditable, and recoverable.
- **Proves:** Layer-aware governance. Bronze = accept all. Silver = enforce rules. The gap is the proof that governance is working.

---

## 9. Row Hash Dedup Check

**What I'm asking:** Are there any duplicate records in bronze (same business content)?

```sql
SELECT row_hash, COUNT(*) AS occurrences
FROM `bt-df-lkhouse.eastside_bronze.pos_transactions`
GROUP BY 1
HAVING COUNT(*) > 1
LIMIT 10;
```

**What the results show:**
- If rows appear: bronze has duplicates from retries or overlapping batches (expected — it's append-only).
- If empty: no duplicates exist (clean source data).
- `row_hash` enables silver to deduplicate efficiently via hash-based anti-join.
- **Proves:** Bronze preserves everything (even duplicates). Silver deduplicates. Separation of concerns.

---

## 10. Pipeline Monitor

**What I'm asking:** Show me the latest pipeline activity across all layers.

```sql
SELECT *
FROM `bt-df-lkhouse.lakehouse_dataproduct.pipeline_monitor`
ORDER BY event_time DESC
LIMIT 20;
```

**What the results show:**
- Unified view of bronze/silver/gold activity from GCS logs.
- Shows successes, failures, skips, and schema events.
- Queryable from BQ without needing access to Cloud Shell or Dataproc logs.
- **Proves:** Full observability. Pipeline is self-documenting.

---

## Suggested Demo Flow

| Step | Query | Narrative |
|------|-------|-----------|
| 1 | Query 1 | "Here's the proof — three schema versions coexisting, zero data rewrite" |
| 2 | Query 2 | "The schema only grows — columns are never removed" |
| 3 | Query 5 | "Drill into specific records — same table, different schemas" |
| 4 | Query 3 | "Every record is traceable to its source file" |
| 5 | Query 8 | "The governance gap — bronze accepts all, silver enforces" |
| 6 | Query 7 | "Silver blocked the breaking change — consumers are protected" |
| 7 | Query 10 | "Full pipeline observability from BQ" |
