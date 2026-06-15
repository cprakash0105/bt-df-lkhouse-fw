# Schema Evolution POC — GCP Native Lakehouse

Fully managed, GCP-native lakehouse demonstrating schema evolution with Iceberg tables across Reservoir → CCN → Data Product layers.

## Architecture

```
Landing (JSONL) → Reservoir (Iceberg) → CCN (Iceberg) → Data Product (Iceberg) → BigQuery
                  ↕                      ↕                ↕
                  └──────── BigLake Metastore (BLMS) ─────┘
```

## Stack

| Component | Technology |
|-----------|-----------|
| Compute | Dataproc Serverless (PySpark) |
| Storage | GCS (single bucket) |
| Table Format | Apache Iceberg |
| Catalog | BigLake Metastore (BLMS) |
| Query | BigQuery (linked datasets) |
| Orchestration | Cloud Composer (Airflow) |
| IaC | Terraform |

## Project Structure

```
├── bt_df_lkhouse_fw/                # Config-driven PySpark framework
│   ├── config/
│   │   └── pipeline.yaml            # All table definitions, DQ rules, consumption targets
│   └── engine/
│       ├── base.py                   # Spark session, config loading, CLI
│       ├── ingest.py                 # Landing → Reservoir (schema evolution)
│       ├── curate.py                 # Reservoir → CCN (DQ, dedup, type enforcement)
│       ├── consume.py                # CCN → Data Product (joins, aggregation)
│       └── schema_evolver.py         # Drift detection, allowed/blocked changes
├── composer/
│   └── lakehouse_pipeline_dag.py     # Cloud Composer DAG
├── scripts/
│   ├── generate_data.py              # V1: 100K customers, 1M orders, 10M payments
│   ├── generate_data_v2.py           # V2: schema drift (new columns, type widen)
│   ├── run_pipeline.sh               # Submit all stages to Dataproc Serverless
│   └── create_linked_datasets.sh     # BigQuery linked datasets
├── terraform/                        # All infrastructure
├── DEMO_WALKTHROUGH.md               # Demo guide for stakeholders
└── DESIGN.md                         # Technical design
```

## Data Model

| Table | Records | Relationships |
|-------|---------|--------------|
| customers | 100,000 | — |
| products | 10,000 | — |
| orders | 1,000,000 | orders.customer_id → customers |
| payments | 10,000,000 | payments.order_id → orders |
| **customer_360** (Data Product) | 100,000 | Aggregated: customer + orders + payments |

## Quick Start

```bash
# 1. Deploy infrastructure
cd terraform && terraform init && terraform apply && cd ..

# 2. Generate V1 test data
pip install faker google-cloud-storage
python scripts/generate_data.py --project=bt-df-lkhouse

# 3. Create BigQuery linked datasets
bash scripts/create_linked_datasets.sh bt-df-lkhouse europe-west2

# 4. Run pipeline (V1)
bash scripts/run_pipeline.sh bt-df-lkhouse europe-west2 all v1

# 5. Query in BigQuery
bq query --use_legacy_sql=false \
  'SELECT * FROM `bt-df-lkhouse.lakehouse_dataproduct.customer_360` LIMIT 10'

# 6. Schema evolution — generate V2 data with drift
python scripts/generate_data_v2.py --project=bt-df-lkhouse

# 7. Re-run pipeline (V2) — schema evolves automatically
bash scripts/run_pipeline.sh bt-df-lkhouse europe-west2 all v2
```

## Layers

| Layer | Namespace | Purpose | Transforms |
|-------|-----------|---------|-----------|
| **Reservoir** | `reservoir` | As-is from source | Ingestion timestamp only |
| **CCN** | `ccn` | Clean, validated | DQ, type enforcement, dedup |
| **Data Product** | `dataproduct` | Reporting-ready | Joins, aggregation |

## Schema Evolution

The framework detects and handles schema drift at ingest time:

| Change Type | Behaviour |
|-------------|-----------|
| Add nullable column | ✅ Allowed — ALTER TABLE + merge-schema |
| Type widening (INT→BIGINT) | ✅ Allowed — Iceberg auto-promotes |
| Enum expansion | ✅ Allowed — DQ rules updated in config |
| Drop column | 🚫 Blocked — pipeline fails |
| Type narrowing | 🚫 Blocked — pipeline fails |
