# Demo Walkthrough — Schema Evolution POC (v2)

## For: Amanda
## Architecture: Reservoir(Parquet) → CCN(Iceberg/BLMS) → Data Product(BigQuery)

---

## The Story

> "Each layer uses the right technology for its purpose.
> Reservoir is fast and raw. CCN is governed. Data Product is optimised for you."

---

## What You're Looking At

| Layer | Technology | Purpose | Query Access |
|-------|-----------|---------|--------------|
| **Reservoir** | Parquet on GCS | Data as-is, fast ingest | Spark only |
| **CCN** | Iceberg via BLMS | Governed, schema-evolved | BigQuery (linked dataset) |
| **Data Product** | BigQuery native | Reporting-ready, materialised | BigQuery direct |

---

## Demo Steps

### 1. Show Infrastructure (Terraform)

```bash
cd terraform && terraform plan
# One command → bucket, BLMS catalog, BQ datasets, service account, network
```

### 2. Generate V1 Data

```bash
cd datagen
python generate.py --project=bt-df-lkhouse --version=v1 --scale=0.01  # 1% for speed
```

Show: "Data generator is standalone — no Spark, just Python + GCS. Produces realistic JSONL."

### 3. Run Pipeline (V1)

```bash
bash scripts/run_pipeline.sh bt-df-lkhouse europe-west2 all v1
```

Show the logs — structured output per table, DQ stats, dedup counts.

### 4. Query in BigQuery

```sql
-- CCN layer (Iceberg via linked dataset) — governed, deduplicated
SELECT COUNT(*) FROM `bt-df-lkhouse.lakehouse_ccn.customers`;
SELECT * FROM `bt-df-lkhouse.lakehouse_ccn.customers` LIMIT 5;

-- Data Product (native BigQuery) — consumer-ready
SELECT * FROM `bt-df-lkhouse.lakehouse_dataproduct.customer_360` LIMIT 5;

-- See the aggregations
SELECT loyalty_tier, COUNT(*) AS customers, AVG(total_spend) AS avg_spend
FROM `bt-df-lkhouse.lakehouse_dataproduct.customer_360`
GROUP BY 1 ORDER BY avg_spend DESC;
```

### 5. Schema Evolution — Generate V2

```bash
cd datagen
python generate.py --project=bt-df-lkhouse --version=v2 --scale=0.01
```

Show the drift summary:
- `customers`: NEW column `customer_segment` + NEW loyalty tier `Diamond`
- `orders`: amounts > INT_MAX (type widening)
- `payments`: NEW column `payment_channel` + Crypto + multi-currency

### 6. Re-run Pipeline (V2)

```bash
bash scripts/run_pipeline.sh bt-df-lkhouse europe-west2 all v2
```

Watch the logs — schema evolution detected and applied:
```
✅ ALLOWED: Adding column 'customer_segment' (string)
✅ ALLOWED: Adding column 'payment_channel' (string)
```

### 7. Prove Schema Evolution in BigQuery

```sql
-- New column appears — old rows have NULL
SELECT customer_id, name, customer_segment, loyalty_tier
FROM `bt-df-lkhouse.lakehouse_ccn.customers`
WHERE customer_segment IS NOT NULL
LIMIT 5;

-- Old rows (V1) — customer_segment is NULL
SELECT customer_id, name, customer_segment
FROM `bt-df-lkhouse.lakehouse_ccn.customers`
WHERE customer_segment IS NULL
LIMIT 5;

-- New enum value (Diamond)
SELECT loyalty_tier, COUNT(*) AS cnt
FROM `bt-df-lkhouse.lakehouse_ccn.customers`
GROUP BY 1 ORDER BY cnt DESC;

-- New payment channel
SELECT payment_channel, COUNT(*)
FROM `bt-df-lkhouse.lakehouse_ccn.payments`
GROUP BY 1;

-- Schema drift detection (NULL percentage = added in V2)
SELECT
  'customer_segment' AS col,
  ROUND(COUNTIF(customer_segment IS NOT NULL) / COUNT(*) * 100, 1) AS pct_populated
FROM `bt-df-lkhouse.lakehouse_ccn.customers`;
```

### 8. Show Data Product Updated

```sql
-- customer_360 now includes customer_segment
SELECT customer_id, name, customer_segment, loyalty_tier, total_spend
FROM `bt-df-lkhouse.lakehouse_dataproduct.customer_360`
WHERE customer_segment = 'Enterprise'
ORDER BY total_spend DESC
LIMIT 10;
```

### 9. Show Audit Trail

```sql
-- Pipeline execution history
SELECT * FROM `bt-df-lkhouse.lakehouse_ccn.pipeline_audit`
ORDER BY audit_timestamp DESC;
```

### 10. Show "Drop & Go" (Config-Driven)

Open `config/tables/customers.yaml` → "This is all you need to define a table."
Open `config/consumption/customer_360.sql` → "This is all you need for a data product."

> "Adding a new table = drop a YAML. Adding a new view = drop a SQL file. Zero code changes."

---

## Key Points for Amanda

| Question | Answer |
|----------|--------|
| What if source adds a column? | Schema evolver detects it, applies if allowed, blocks if not |
| What if someone drops a column? | Pipeline fails immediately — blocked by governance |
| Where's the governance? | YAML config per table: `allowed` + `blocked` lists |
| How do consumers query? | BigQuery — CCN via linked dataset, Data Product directly |
| Is there an audit trail? | Yes — `pipeline_audit` Iceberg table tracks every run |
| How do I add a new table? | Drop a YAML file, re-run pipeline |
| What about orchestration? | Cloud Composer DAG (Airflow) — `ingest >> curate >> consume` |
| How is this like Databricks? | Same medallion pattern, same governance, but GCP-native |

---

## Architecture Diagram (for slide)

```
┌──────────┐     ┌─────────────────────────────────────────────────────┐
│ Landing  │     │                  GCS Bucket                          │
│ (JSONL)  │────▶│  reservoir/ (Parquet)  │  ccn/ (Iceberg)            │
└──────────┘     └───────────────────────┬─────────────────────────────┘
                                         │ BLMS catalog
                                         ▼
                 ┌───────────────────────────────────────────────────────┐
                 │  BigQuery                                              │
                 │  lakehouse_ccn.* (linked dataset — Iceberg)            │
                 │  lakehouse_dataproduct.* (native tables — materialised)│
                 └───────────────────────────────────────────────────────┘
```
