# Schema Evolution POC — GCP Native Lakehouse (v2)

Config-driven lakehouse framework demonstrating schema evolution across three layers, each with the right technology for its purpose.

## Architecture

```
Landing (JSONL/GCS)
    │
    ▼  [Dataproc Serverless - PySpark]
Reservoir (Parquet/GCS)         ← as-is from source, no catalog
    │
    ▼  [Dataproc Serverless - PySpark]
CCN (Iceberg/BLMS)              ← DQ, dedup, governed schema evolution
    │
    ▼  [BigQuery SQL]
Data Product (BigQuery native)  ← materialised joins/aggs for consumers
```

## Stack

| Layer | Technology | Queryable via |
|-------|-----------|---------------|
| Reservoir | Parquet on GCS | Spark only |
| CCN | Iceberg (BLMS catalog) | BigQuery linked dataset |
| Data Product | BigQuery native tables | BigQuery direct |

| Component | Technology |
|-----------|-----------:|
| Compute | Dataproc Serverless |
| Storage | GCS (single bucket) |
| Table Format | Iceberg (CCN layer) |
| Catalog | BigLake Metastore |
| Query | BigQuery |
| Orchestration | Cloud Composer |
| IaC | Terraform |

## Project Structure

```
├── bt_df_lkhouse_fw/                # Config-driven PySpark framework
│   ├── config/
│   │   ├── pipeline.yaml            # Global settings
│   │   ├── tables/                  # Drop a YAML → table is picked up
│   │   │   ├── customers.yaml
│   │   │   ├── products.yaml
│   │   │   ├── orders.yaml
│   │   │   └── payments.yaml
│   │   └── consumption/             # Drop a SQL → view is deployed
│   │       └── customer_360.sql
│   └── engine/
│       ├── base.py                  # Spark session, config auto-discovery, logging
│       ├── audit.py                 # Pipeline audit trail (Iceberg table)
│       ├── ingest.py                # Landing → Reservoir (Parquet)
│       ├── curate.py                # Reservoir → CCN (Iceberg, schema evolution)
│       ├── consume.py               # CCN → Data Product (BigQuery SQL)
│       └── schema_evolver.py        # Drift detection + governance
├── datagen/                         # Standalone data generator (no Spark)
│   ├── generate.py                  # V1 + V2, --version flag, --scale for testing
│   └── requirements.txt
├── composer/
│   └── lakehouse_pipeline_dag.py    # Cloud Composer DAG
├── scripts/
│   ├── run_pipeline.sh              # Submit all stages
│   └── create_linked_datasets.sh    # BQ linked dataset for CCN
└── terraform/                       # All infrastructure
```

## Quick Start

```bash
# 1. Deploy infrastructure
cd terraform && terraform init && terraform apply && cd ..

# 2. Generate V1 data (standalone — no Spark)
cd datagen && pip install -r requirements.txt
python generate.py --project=bt-df-lkhouse --version=v1
cd ..

# 3. Run pipeline
bash scripts/run_pipeline.sh bt-df-lkhouse europe-west2 all v1

# 4. Query in BigQuery
bq query --use_legacy_sql=false \
  'SELECT * FROM `bt-df-lkhouse.lakehouse_dataproduct.customer_360` LIMIT 10'

# 5. Schema evolution — V2 data with drift
cd datagen && python generate.py --project=bt-df-lkhouse --version=v2 && cd ..
bash scripts/run_pipeline.sh bt-df-lkhouse europe-west2 all v2

# 6. See evolution in BigQuery
bq query --use_legacy_sql=false \
  'SELECT customer_segment, COUNT(*) FROM `bt-df-lkhouse.lakehouse_ccn.customers` GROUP BY 1'
```

## Adding a New Table

Drop a YAML file into `config/tables/`:

```yaml
# wishlists.yaml
table: wishlists
description: "Customer wishlists"
source: landing/wishlists
primary_key: wishlist_id
dedup_order_by: ingestion_ts DESC

dq_rules:
  not_null: [wishlist_id, customer_id]

type_overrides: {}

schema_evolution:
  allowed: [add_column, type_widen]
  blocked: [drop_column, type_narrow]
```

Re-run the pipeline — the new table flows through automatically.

## Adding a New Data Product

Drop a SQL file into `config/consumption/`:

```sql
-- product_performance.sql
CREATE OR REPLACE TABLE `${PROJECT_ID}.lakehouse_dataproduct.product_performance` AS
SELECT p.product_id, p.product_name, p.category,
       COUNT(o.order_id) AS times_ordered,
       SUM(o.total_amount) AS total_revenue
FROM `${PROJECT_ID}.lakehouse_ccn.products` p
LEFT JOIN `${PROJECT_ID}.lakehouse_ccn.orders` o ON ...
GROUP BY 1, 2, 3
```

## Schema Evolution

| Change Type | Handling |
|-------------|----------|
| Add nullable column | ✅ Auto-allowed (ALTER TABLE + merge-schema) |
| Type widening (INT→BIGINT) | ✅ Auto-allowed (Iceberg metadata update) |
| Enum expansion | ✅ Auto-allowed (no schema change) |
| Drop column | 🚫 Blocked (pipeline fails) |
| Type narrowing | 🚫 Blocked (pipeline fails) |

## Testing at Small Scale

```bash
# Generate 1% of full data (fast iteration)
python datagen/generate.py --project=bt-df-lkhouse --version=v1 --scale=0.01
```

## Structured Logging

All application logs are written as JSONL to GCS for analysis. See [docs/LOGGING.md](docs/LOGGING.md) for full details.

```bash
# Query logs in BigQuery (after running scripts/setup_log_table.sql)
bq query --use_legacy_sql=false \
  'SELECT * FROM `bt-df-lkhouse.lakehouse_logs.app_logs` WHERE level = "ERROR" ORDER BY timestamp DESC LIMIT 20'
```
