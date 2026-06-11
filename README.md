# Schema Evolution POC — GCP Native (Dataproc Serverless + Iceberg + BLMS + BigQuery)

Fully GCP-native implementation of schema evolution using managed services only.

## Architecture

```
Source (GCS JSONL)
    │
    ▼
Dataproc Serverless (PySpark)
    │
    ├── Schema Bridge (normalise any version → Silver)
    ├── DQ Validation
    ├── Dedup
    │
    ▼
Spark Iceberg Write ──── BiglakeCatalog ──── BLMS (managed catalog)
    │                                            │
    ▼                                            ▼
GCS (Parquet data + Iceberg metadata)      BigQuery (linked datasets)
```

## Stack

| Layer | Technology |
|-------|-----------|
| Compute | Dataproc Serverless (PySpark) |
| Storage | GCS (single bucket) |
| Table Format | Apache Iceberg (via Spark runtime) |
| Catalog | BigLake Metastore (BLMS) via `BiglakeCatalog` |
| Query | BigQuery (linked datasets) |
| IaC | Terraform |

## Project Structure

```
├── terraform/            # All infrastructure (APIs, bucket, SA, BLMS, BQ, network)
├── spark/
│   ├── bronze_to_silver.py    # PySpark: source → schema bridge → DQ → Iceberg write
│   └── silver_to_gold.py      # PySpark: read Iceberg → aggregate → write Iceberg
├── dataflow/testdata/         # Test data (JSONL) for v1, v2, v3
├── bigquery/                  # Consumer views SQL
├── scripts/
│   ├── setup.sh
│   ├── submit_spark_job.sh    # Submit to Dataproc Serverless
│   └── validate.sh
└── .gitignore
```

## Quick Start

```bash
# 1. Deploy infrastructure
cd terraform
terraform init
terraform apply
cd ..

# 2. Run Bronze → Silver (schema v1)
bash scripts/submit_spark_job.sh schema-evolution-poc europe-west2 1

# 3. Query in BigQuery
bq query --use_legacy_sql=false \
  'SELECT * FROM `schema-evolution-poc.silver_dataset.customer` LIMIT 10'

# 4. Evolve schema (v2: add loyalty_tier)
bash scripts/submit_spark_job.sh schema-evolution-poc europe-west2 2

# 5. Verify evolution
bq query --use_legacy_sql=false \
  'SELECT customer_id, loyalty_tier, source_schema_version
   FROM `schema-evolution-poc.silver_dataset.customer` ORDER BY customer_id'
```

## Why Dataproc Serverless + Spark (not Dataflow + PyIceberg)

| Concern | Dataflow + PyIceberg | Dataproc Serverless + Spark |
|---------|---------------------|----------------------------|
| Iceberg write | PyIceberg (library) | Spark Iceberg runtime (native) |
| BLMS catalog | REST auth issues | BiglakeCatalog (native, ADC) |
| Serverless | ✅ | ✅ |
| Schema evolution | Manual PyIceberg calls | `merge-schema` option built-in |
| Production maturity | PyIceberg is newer | Spark + Iceberg is battle-tested |
| Persistent catalog | Needs external DB | BLMS via BiglakeCatalog |
```
