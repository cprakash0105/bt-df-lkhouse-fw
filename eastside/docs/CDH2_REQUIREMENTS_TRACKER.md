# CDH 2.0 Requirements — Implementation & Demo Tracker

**Date**: 6 July 2025
**Owner**: Chandra Prakash
**Stakeholder**: Amanda
**Project**: EastSide CDH 2.0 (`bt-df-lkhouse`)

---

## Status Key

| Symbol | Meaning |
|--------|---------|
| ✅ | Code complete, tested |
| 🔨 | Code complete, not yet run on Dataproc |
| ⏳ | In progress |
| ❌ | Not started |
| 🗣️ | Pending discussion/confirmation |

---

## Requirements

| # | Requirement | Status | Engine File | Demo Command | Notes |
|---|---|---|---|---|---|
| 1 | **Format Conversion** — All source formats (CSV, JSON, Avro, Parquet) → Iceberg in bronze | 🔨 | `bronze.py` read_landing() | `run_bronze.sh` with mixed-format tables | 5 JSON + 3 CSV feeds in datagen |
| 2 | **Schema Evolution (Bronze)** — Open: accept all changes (add, drop, widen, narrow) | 🔨 | `schema_evolver.py` layer=bronze | Add a column to source, re-run bronze | SchemaEvolver auto-accepts |
| 3 | **Schema Evolution (Silver)** — Non-breaking: add + widen allowed, drop + narrow blocked | 🔨 | `schema_evolver.py` layer=silver | Attempt a column drop → should block | Logs rejection reason |
| 4 | **Schema Evolution (Gold)** — Locked: contract validation before BQ write | 🔨 | `gold.py` validate_contract() | Add unexpected column → should fail | Contract = required cols + PK uniqueness |
| 5 | **Time Travel (Bronze)** — Iceberg snapshots, query any historical state | 🔨 | Native Iceberg | `SELECT * FROM table VERSION AS OF <snapshot>` | Requires Spark SQL or Trino |
| 6 | **Late Arriving Data** — Configurable window + quarantine | 🔨 | `silver.py` handle_late_arrivals() | Insert record with old timestamp → quarantine | `late_arrival_window_days: 7` in config |
| 7 | **SCD2 Processing** — valid_from / valid_to / is_current on all dimension tables | 🔨 | `silver.py` merge_scd2() | Update a customer profile → old row closed, new row current | MERGE INTO with matched/not-matched |
| 8 | **Streaming Dedup** — SHA256 row_hash, two-level dedup (intra + cross-batch) | 🔨 | `stream.py` dedup_micro_batch() | Send duplicate Kafka messages → only one lands | foreachBatch + left_anti join |
| 9 | **CDC Partial Records** — Reconstruct to full rows in bronze | 🔨 | `bronze.py` reconstruct_cdc() | Send partial CDC (only changed fields) → full row in bronze | product_catalogue, supplier_POs, store_staff |
| 10 | **Reconciliation (Source↔Bronze)** — Row count comparison | 🔨 | `reconcile.py` reconcile_source_bronze() | Run after bronze → check log | Pass = bronze ≥ source |
| 11 | **Reconciliation (Bronze↔Silver)** — Row count + hash checksum | 🔨 | `reconcile.py` reconcile_bronze_silver() | Run after silver → check log | Pass = unaccounted < 5% |
| 12 | **Detective DQ (Bronze)** — Flag but never reject, _dq_flags array | 🔨 | `bronze.py` run_detective_policies() | Insert bad data → flags appear, row still lands | NULL_PK, INVALID_DATE, etc. |
| 13 | **Preventative DQ (Silver)** — Reject bad records, standardise | 🔨 | `silver.py` apply_preventative_dq() | Insert NULL PK → rejected, not in silver | Rejects logged |
| 14 | **Masking (On-Write)** — SHA256 hash for high-sensitivity PII | 🔨 | `silver.py` apply_masking() | Check silver table → email/phone are hashed | Config: `masking: sha256` per column |
| 15 | **Non-Printable Removal** — Strip from all string columns in silver | 🔨 | `silver.py` strip_non_printable() | Insert record with \x00 chars → cleaned in silver | Regex strip |
| 16 | **Gold Contract Enforcement** — Required cols, PK uniqueness | 🔨 | `gold.py` validate_contract() | Run gold → BQ table matches contract | Drops internal cols (row_hash, _dq_flags, etc.) |
| 17 | **Policy Controls (Read-Time)** — Column-level security via Dataplex/BQ | 🗣️ | N/A (Dataplex config) | Show BQ column policy | Discuss with Rhys: which fields |

---

## Demo Sequence (Recommended)

Run in this order to show the full pipeline story:

### Phase 1: Data Generation
```bash
python eastside/datagen/generate.py --project=bt-df-lkhouse
```
- Shows: 8 datasets, 18,100 records, mixed formats, CDC feeds

### Phase 2: Bronze (Requirements 1, 9, 12)
```bash
bash eastside/scripts/run_bronze.sh bt-df-lkhouse europe-west2 all v1
```
- Shows: format conversion, CDC reconstruct, detective DQ flags, row_hash

### Phase 3: Silver (Requirements 6, 7, 13, 14, 15)
```bash
bash eastside/scripts/run_silver.sh bt-df-lkhouse europe-west2 all
```
- Shows: dedup, SCD2 merge, late arrival quarantine, masking, DQ enforcement

### Phase 4: Gold (Requirements 4, 16)
```bash
bash eastside/scripts/run_gold.sh bt-df-lkhouse europe-west2 all
```
- Shows: contract validation, BQ write, internal columns stripped

### Phase 5: Reconciliation (Requirements 10, 11)
```bash
bash eastside/scripts/run_reconcile.sh bt-df-lkhouse europe-west2 all
```
- Shows: source↔bronze counts, bronze↔silver counts + hash checksum

### Phase 6: Schema Evolution (Requirements 2, 3, 4)
- Modify source data (add column) → re-run bronze → auto-accepted
- Attempt column drop in silver → blocked with log message
- Attempt schema change in gold → contract validation fails

### Phase 7: Time Travel (Requirement 5)
```sql
SELECT * FROM eastside.bronze.pos_transactions VERSION AS OF <snapshot_id>
```

### Phase 8: Streaming (Requirement 8)
```bash
bash eastside/scripts/run_stream.sh bt-df-lkhouse europe-west2 pos_transactions
```
- Shows: Kafka → Bronze with SHA256 dedup

---

## Pending Discussions

| Topic | With | Question | Status |
|---|---|---|---|
| Read-time masking | Rhys | Which fields get write-time (SHA256) vs read-time (Dataplex column policy)? | 🗣️ Not scheduled |
| Reconciliation mode | Amanda | Part of pipeline (automatic) or separate on-demand job? | 🗣️ Not confirmed |
| Streaming datasets | Amanda | Which EastSide datasets (if any) need real-time? | 🗣️ Not confirmed |
| Gold data products | Amanda | What consumption views are needed beyond raw table mirrors? | 🗣️ Not confirmed |
| Compaction | Amanda | Time-based vs file-count threshold for Iceberg compaction? | 🗣️ Not confirmed |

---

## Execution Log

| Date | Action | Result |
|---|---|---|
| 6 Jul 2025 | Tracker created | — |
| | | |

---

## Notes

- All engine code is written and in the repo (`eastside/engine/`)
- Datagen script generates directly to GCS (no local files)
- Pipeline runs on Dataproc Serverless (PySpark)
- Each requirement can be demoed independently by running the relevant script
- Ontika can query the gold tables via MCP agent (`query_table` tool → BigQuery)
