# Schema Evolution POC — GCP Native Design (v2)

## Architecture

Each layer uses the right technology for its purpose:

```
┌─────────────────┐    ┌──────────────────────────────────────────────┐
│  Source Files   │    │          GCS Bucket (single)                   │
│  (GCS JSONL)    │───▶│  landing/ → reservoir/ → ccn/                 │
└─────────────────┘    │  (JSONL)    (Parquet)    (Iceberg)            │
                       └──────────────────────────────────────────────┘
                                                      ↑
                                                      │
                       ┌──────────────────────────────┴────────────────┐
                       │  BigLake Metastore (BLMS)                      │
                       │  Catalog: lakehouse  │  Database: ccn          │
                       └──────────────────────┬────────────────────────┘
                                              │ linked dataset
                                              ▼
                       ┌──────────────────────────────────────────────┐
                       │  BigQuery                                      │
                       │  lakehouse_ccn.*  (linked — Iceberg)           │
                       │  lakehouse_dataproduct.*  (native BQ tables)   │
                       └──────────────────────────────────────────────┘
```

## Layer Design

| Layer | Storage | Format | Catalog | Purpose |
|-------|---------|--------|---------|---------|
| **Landing** | GCS `landing/` | JSONL | None | Raw files from source |
| **Reservoir** | GCS `reservoir/` | Parquet | None | As-is + ingestion_ts, fast ingestion |
| **CCN** | GCS `ccn/` | Iceberg | BLMS `lakehouse.ccn` | Governed: DQ, dedup, schema evolution |
| **Data Product** | BigQuery | Native tables | BigQuery | Materialised joins/aggs for consumers |

### Why This Split?

| Decision | Rationale |
|----------|-----------|
| Reservoir = Parquet (no catalog) | Fast writes, no catalog overhead. Schema-on-read. If source changes, we see it raw. |
| CCN = Iceberg (BLMS) | Governance checkpoint. Schema evolution is controlled here. Time-travel. Linked to BQ. |
| Data Product = BigQuery native | Optimised for consumers. BQ-native features (clustering, partitioning, ML). No Iceberg overhead. |

## Pipeline Flow

```
Landing (JSONL on GCS)
    │
    ▼  [Dataproc Serverless — PySpark]
Reservoir (Parquet on GCS)
    │  • Read JSONL, add ingestion_ts
    │  • Write Parquet (append mode)
    │  • No catalog registration
    ▼
CCN (Iceberg via BLMS)
    │  • Read Parquet from Reservoir
    │  • DQ validation (not_null, positive, accepted_values)
    │  • Deduplication (primary_key + order_by)
    │  • Type enforcement (config-driven casts)
    │  • Schema evolution (detect → govern → apply/block)
    │  • Write Iceberg (merge-schema)
    ▼
Data Product (BigQuery native)
    │  • Execute SQL from config/consumption/*.sql
    │  • CREATE OR REPLACE TABLE (materialised)
    │  • Reads CCN via linked dataset
    ▼
Consumers query BigQuery directly
```

## CPFlow Framework (v2)

Config-driven — add tables and views with zero code changes.

### Adding a Table
Drop a YAML into `config/tables/`:
```yaml
table: new_table
source: landing/new_table
primary_key: id
dedup_order_by: ingestion_ts DESC
dq_rules:
  not_null: [id]
schema_evolution:
  allowed: [add_column, type_widen]
  blocked: [drop_column, type_narrow]
```

### Adding a Data Product View
Drop a SQL into `config/consumption/`:
```sql
CREATE OR REPLACE TABLE `${PROJECT_ID}.lakehouse_dataproduct.new_view` AS
SELECT ... FROM `${PROJECT_ID}.lakehouse_ccn.some_table`
```

### Engine Components

| Engine | Input | Output | Spark? |
|--------|-------|--------|--------|
| `ingest.py` | Landing JSONL | Reservoir Parquet | Yes (Dataproc) |
| `curate.py` | Reservoir Parquet | CCN Iceberg | Yes (Dataproc + BLMS) |
| `consume.py` | CCN (via BQ linked dataset) | Data Product (BQ native) | No (BQ client only) |
| `audit.py` | Pipeline results | `lakehouse.ccn.pipeline_audit` | Yes (called by ingest/curate) |

## Schema Governance

```
Incoming Data              Existing Iceberg Table (CCN)
    ↓                              ↓
┌─────────────────────────────────────────────┐
│  SchemaEvolver.detect_changes()             │
│  • New columns?     → add_column            │
│  • Type changed?    → type_widen / narrow   │
│  • Column missing?  → drop_column           │
└──────────────────────┬──────────────────────┘
                       ▼
┌─────────────────────────────────────────────┐
│  Governance (from table YAML config)        │
│  allowed: [add_column, type_widen]          │
│  blocked: [drop_column, type_narrow]        │
│                                             │
│  ✅ Allowed → ALTER TABLE + write           │
│  🚫 Blocked → RuntimeError (pipeline fails) │
└─────────────────────────────────────────────┘
```

## Data Generator (Standalone)

Separate concern — no Spark dependency, pure Python + GCS client.

```bash
# Full scale V1 (100K customers, 1M orders, 10M payments)
python datagen/generate.py --project=bt-df-lkhouse --version=v1

# Small scale for testing (1% of full)
python datagen/generate.py --project=bt-df-lkhouse --version=v1 --scale=0.01

# V2 with schema drift
python datagen/generate.py --project=bt-df-lkhouse --version=v2
```

## Infrastructure (Terraform)

| Resource | Purpose |
|----------|---------|
| GCS bucket | Single bucket for all layers |
| Service account | Dataproc Serverless identity |
| BLMS catalog + ccn database | Iceberg catalog for CCN layer |
| BQ connection | For linked dataset to read Iceberg |
| BQ linked dataset (lakehouse_ccn) | Query CCN Iceberg tables from BQ |
| BQ dataset (lakehouse_dataproduct) | Native BQ tables for data products |
| VPC + NAT | Network for Dataproc Serverless |

## GCS Bucket Layout

```
gs://{project}-lakehouse/
├── landing/
│   ├── customers/{v1,v2}/    (JSONL)
│   ├── products/v1/          (JSONL)
│   ├── orders/{v1,v2}/       (JSONL)
│   └── payments/{v1,v2}/     (JSONL)
├── reservoir/
│   ├── customers/            (Parquet — no catalog)
│   ├── products/
│   ├── orders/
│   └── payments/
├── ccn/
│   ├── customers/            (Iceberg — BLMS registered)
│   ├── products/
│   ├── orders/
│   ├── payments/
│   └── pipeline_audit/       (Iceberg — audit trail)
└── framework/
    ├── config/               (pipeline.yaml, tables/, consumption/)
    ├── engine/               (Python modules)
    └── bt_df_lkhouse_fw.zip  (packaged for Dataproc)
```
