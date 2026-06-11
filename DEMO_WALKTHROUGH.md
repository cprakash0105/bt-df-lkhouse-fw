# Demo Walkthrough — Schema Evolution POC

## For: Amanda
## Architecture: GCP Native Lakehouse (Dataproc Serverless + Iceberg + BLMS + BigQuery)

---

## What You're Looking At

A fully managed, GCP-native lakehouse with three layers — all Iceberg tables, all in one catalog:

| Layer | Purpose | BigQuery Dataset |
|-------|---------|-----------------|
| **Raw** | Data as-is from source (no transforms) | `lakehouse_raw` |
| **Curated** | Cleansed, validated, deduplicated | `lakehouse_curated` |
| **Consumption** | Reporting-ready (joined, aggregated) | `lakehouse_consumption` |

---

## Data Model

```
100,000 Customers
 └── 1,000,000 Orders (customer_id → customers)
      └── 10,000,000 Payments (order_id → orders)

10,000 Products

Gold: customer_360 (one row per customer with full order/payment history)
```

---

## Pipeline Flow

```
Landing (JSONL on GCS)
    │
    ▼  [Dataproc Serverless - PySpark]
Raw (Iceberg / BLMS)     ← no transforms, just format + catalog registration
    │
    ▼  [Dataproc Serverless - PySpark]
Curated (Iceberg / BLMS) ← DQ validation, type enforcement, deduplication
    │
    ▼  [Dataproc Serverless - PySpark]
Consumption (Iceberg / BLMS) ← joins + aggregation → customer_360
    │
    ▼  [auto]
BigQuery (linked datasets) ← query immediately, no manual setup
```

---

## Spark Jobs

| Job | File | What It Does |
|-----|------|-------------|
| Landing → Raw | `spark/landing_to_raw.py` | Reads JSONL, adds ingestion timestamp, writes Iceberg |
| Raw → Curated | `spark/raw_to_curated.py` | Schema enforcement, DQ rules, dedup by primary key |
| Curated → Consumption | `spark/curated_to_consumption.py` | Joins customers + orders + payments → customer_360 |

---

## Demo Steps

### 1. Show the data in BigQuery

```sql
-- Raw layer (as-is from source)
SELECT * FROM `schema-evolution-poc.lakehouse_raw.customers` LIMIT 5;
SELECT COUNT(*) FROM `schema-evolution-poc.lakehouse_raw.orders`;

-- Curated layer (cleansed)
SELECT * FROM `schema-evolution-poc.lakehouse_curated.customers` LIMIT 5;

-- Consumption layer (reporting)
SELECT * FROM `schema-evolution-poc.lakehouse_consumption.customer_360` LIMIT 5;
```

### 2. Show schema evolution

```sql
-- Run a new batch with loyalty_tier populated differently
-- After the pipeline re-runs, new column values appear immediately

SELECT customer_id, name, loyalty_tier, total_orders, total_spend
FROM `schema-evolution-poc.lakehouse_consumption.customer_360`
WHERE loyalty_tier = 'Platinum'
ORDER BY total_spend DESC
LIMIT 10;
```

### 3. Show time-travel (Iceberg snapshots)

```sql
-- Query the table as it was before the last write
-- (via Spark: spark.read.option("as-of-timestamp", "2025-06-10T00:00:00Z").table(...))
```

### 4. Show governance (same table, different consumer views)

```sql
-- Consumer A: sees v1 schema (no loyalty_tier)
SELECT customer_id, name, total_spend
FROM `schema-evolution-poc.lakehouse_consumption.customer_360` LIMIT 5;

-- Consumer B: sees full schema
SELECT * FROM `schema-evolution-poc.lakehouse_consumption.customer_360` LIMIT 5;
```

---

## Key Technical Points

| Question | Answer |
|----------|--------|
| What if source adds a new column? | `merge-schema=true` on write → Iceberg adds it automatically |
| What if we need to widen a type? | Iceberg handles INT→BIGINT without rewriting data |
| Where is the catalog? | BigLake Metastore (BLMS) — fully managed |
| How does BigQuery see it? | Linked datasets auto-discover BLMS tables |
| Is Bronze/Raw queryable? | Yes — all layers are Iceberg, all queryable via BQ |
| How is this like Databricks? | Same pattern: all layers are managed Delta/Iceberg tables in a catalog |
| What about governance? | Curated layer enforces DQ; blocked changes fail the pipeline |

---

## Architecture Diagram

```
┌──────────────┐     ┌─────────────────────────────────────────────┐
│  Landing     │     │           GCS Bucket                         │
│  (JSONL)     │────▶│  raw/ → curated/ → consumption/             │
└──────────────┘     │  (all Iceberg tables)                       │
                     └─────────────────────────────────────────────┘
                                ↕ managed by
                     ┌─────────────────────────────────────────────┐
                     │  BigLake Metastore (BLMS)                    │
                     │  Catalog: lakehouse                          │
                     │  Databases: raw | curated | consumption      │
                     └──────────────────────┬──────────────────────┘
                                            │ linked datasets
                                            ▼
                     ┌─────────────────────────────────────────────┐
                     │  BigQuery                                    │
                     │  lakehouse_raw.*                             │
                     │  lakehouse_curated.*                         │
                     │  lakehouse_consumption.customer_360          │
                     └─────────────────────────────────────────────┘
```

---

## Infrastructure (all Terraform)

- 1 GCS bucket
- 1 BLMS catalog + 3 databases
- 1 service account
- 1 BigQuery connection + 3 linked datasets
- Network (VPC + NAT for Dataproc)
- All APIs enabled automatically

`terraform apply` → everything created in ~2 minutes.
