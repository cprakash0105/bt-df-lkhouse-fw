# Schema Evolution POC — GCP Native Lakehouse

Fully managed, GCP-native lakehouse demonstrating schema evolution with Iceberg tables across Raw → Curated → Consumption layers.

## Architecture

```
Landing (JSONL) → Raw (Iceberg) → Curated (Iceberg) → Consumption (Iceberg) → BigQuery
                  ↕                ↕                    ↕
                  └────── BigLake Metastore (BLMS) ──────┘
```

## Stack

| Component | Technology |
|-----------|-----------|
| Compute | Dataproc Serverless (PySpark) |
| Storage | GCS (single bucket) |
| Table Format | Apache Iceberg |
| Catalog | BigLake Metastore (BLMS) |
| Query | BigQuery (linked datasets) |
| IaC | Terraform |

## Project Structure

```
├── terraform/                    # All infrastructure
├── spark/
│   ├── landing_to_raw.py         # JSONL → Raw Iceberg (no transforms)
│   ├── raw_to_curated.py         # DQ, dedup, schema enforcement
│   └── curated_to_consumption.py # Joins → customer_360 reporting table
├── scripts/
│   ├── generate_data.py          # Faker: 100K customers, 1M orders, 10M payments
│   ├── run_pipeline.sh           # Submit all stages to Dataproc
│   └── create_linked_datasets.sh # BigQuery linked datasets
├── DEMO_WALKTHROUGH.md           # Demo guide for stakeholders
└── DESIGN.md                     # Technical design
```

## Data Model

| Table | Records | Relationships |
|-------|---------|--------------|
| customers | 100,000 | — |
| products | 10,000 | — |
| orders | 1,000,000 | orders.customer_id → customers |
| payments | 10,000,000 | payments.order_id → orders |
| **customer_360** (Gold) | 100,000 | Aggregated: customer + orders + payments |

## Quick Start

```bash
# 1. Deploy infrastructure
cd terraform && terraform init && terraform apply && cd ..

# 2. Generate test data
pip install faker google-cloud-storage
python scripts/generate_data.py

# 3. Create BigQuery linked datasets
bash scripts/create_linked_datasets.sh

# 4. Run pipeline
bash scripts/run_pipeline.sh schema-evolution-poc europe-west2 all

# 5. Query in BigQuery
bq query --use_legacy_sql=false \
  'SELECT * FROM `schema-evolution-poc.lakehouse_consumption.customer_360` LIMIT 10'
```

## Layers

| Layer | Dataset | Purpose | Transforms |
|-------|---------|---------|-----------|
| **Raw** | `lakehouse_raw` | As-is from source | Ingestion timestamp only |
| **Curated** | `lakehouse_curated` | Clean, validated | DQ, type enforcement, dedup |
| **Consumption** | `lakehouse_consumption` | Reporting-ready | Joins, aggregation |
