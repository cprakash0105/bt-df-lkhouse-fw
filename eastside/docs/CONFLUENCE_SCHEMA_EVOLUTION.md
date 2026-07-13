# Schema Evolution — Iceberg — CDH 2.0

**Owner:** Chandra Prakash
**Platform:** EastSide CDH 2.0 (GCP — `bt-df-lkhouse`)
**Table Format:** Apache Iceberg (BigLake Metastore)
**Compute:** Dataproc Serverless (PySpark)
**Orchestration:** Dagster (GCE VM — `eastside-dagster`)
**Region:** `europe-west2`

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              EastSide CDH 2.0 — Data Flow                                       │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                 │
│  SOURCES                    GCS (Storage Layer)                     QUERY LAYER                  │
│  ────────                   ────────────────────                    ───────────                  │
│                                                                                                 │
│  POS System ─┐              ┌──────────────────────────────────────────────────────┐            │
│  E-commerce ─┤              │  gs://eastside-lakehouse/                             │            │
│  ERP (SAP) ──┤              │                                                      │            │
│  Warehouse ──┼─── Files ──▶ │  landing/{table}/v{n}/     ← Raw files (immutable)   │            │
│  Loyalty ────┤              │       │                                              │            │
│  PLM (CDC) ──┤              │       │  bronze.py (Dataproc Serverless)              │            │
│  HR (CDC) ───┘              │       ▼                                              │            │
│                             │  bronze/                   ← Iceberg (append-only)   │──┐         │
│                             │       │                      Schema: OPEN            │  │         │
│                             │       │  silver.py (Dataproc Serverless)              │  │         │
│                             │       ▼                                              │  │         │
│                             │  silver/                   ← Iceberg (merge/SCD2)    │──┤         │
│                             │       │                      Schema: NON-BREAKING    │  │         │
│                             │       │  gold.py (Dataproc Serverless)                │  │         │
│                             │       ▼                                              │  │         │
│                             │  ┌─────────────────────────────────────────────┐     │  │         │
│                             │  │ BigQuery: eastside_dataproduct              │     │  │         │
│                             │  │ (Native tables — Spark BQ connector write)  │     │  │         │
│                             │  │ Schema: CONTRACT-LOCKED                    │     │  │         │
│                             │  └─────────────────────────────────────────────┘     │  │         │
│                             └──────────────────────────────────────────────────────┘  │         │
│                                                                                       │         │
│                                                                                       │         │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┘         │
│  │                                                                                              │
│  │  BIGQUERY (Query Layer)                                                                      │
│  │  ──────────────────────                                                                      │
│  │                                                                                              │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────┐        │
│  │  │  eastside_bronze (External Dataset)                                              │        │
│  │  │  ├── pos_transactions        ← External table → BLMS bronze.pos_transactions     │        │
│  │  │  ├── online_orders           ← External table → BLMS bronze.online_orders        │        │
│  │  │  ├── customer_profiles       ← External table → BLMS bronze.customer_profiles    │        │
│  │  │  └── ...                                                                         │        │
│  │  └──────────────────────────────────────────────────────────────────────────────────┘        │
│  │                                                                                              │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────┐        │
│  │  │  eastside_silver (External Dataset)                                              │        │
│  │  │  ├── pos_transactions        ← External table → BLMS silver.pos_transactions     │        │
│  │  │  ├── online_orders           ← External table → BLMS silver.online_orders        │        │
│  │  │  ├── customer_profiles       ← External table → BLMS silver.customer_profiles    │        │
│  │  │  └── ...                                                                         │        │
│  │  └──────────────────────────────────────────────────────────────────────────────────┘        │
│  │                                                                                              │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────┐        │
│  │  │  eastside_dataproduct (Native Dataset — Gold)                                    │        │
│  │  │  ├── pos_transactions        ← Native BQ table (written by gold.py)              │        │
│  │  │  ├── online_orders           ← Native BQ table (written by gold.py)              │        │
│  │  │  └── ...                                                                         │        │
│  │  └──────────────────────────────────────────────────────────────────────────────────┘        │
│  │                                                                                              │
│  └──────────────────────────────────────────────────────────────────────────────────────────────┘
│                                                                                                 │
│                                                                                                 │
│  ORCHESTRATION (Dagster)                    CATALOG (BigLake Metastore)                          │
│  ────────────────────────                   ──────────────────────────────                       │
│                                                                                                 │
│  ┌──────────────────────────┐               ┌──────────────────────────────┐                    │
│  │  GCE VM: eastside-dagster│               │  Catalog: lkhouse_eastside   │                    │
│  │  (e2-small, Debian 12)   │               │                              │                    │
│  │                          │               │  Database: bronze             │                    │
│  │  Assets:                 │               │    └── pos_transactions      │                    │
│  │   bronze_asset ──────────┼── submits ──▶ │    └── online_orders         │                    │
│  │       │                  │   Dataproc    │    └── customer_profiles     │                    │
│  │       ▼                  │   Serverless  │    └── ...                   │                    │
│  │   silver_asset ──────────┼── submits ──▶ │                              │                    │
│  │       │                  │   Dataproc    │  Database: silver             │                    │
│  │       ▼                  │   Serverless  │    └── pos_transactions      │                    │
│  │   gold_asset ────────────┼── submits ──▶ │    └── online_orders         │                    │
│  │                          │   Dataproc    │    └── customer_profiles     │                    │
│  │  Job: eastside_pipeline  │   Serverless  │    └── ...                   │                    │
│  │                          │               │                              │                    │
│  │  After each stage:       │               │  Stores:                     │                    │
│  │   → register_bq_external │               │   • Table schemas            │                    │
│  │   → tag_columns          │               │   • Partition specs          │                    │
│  │                          │               │   • Snapshot history         │                    │
│  └──────────────────────────┘               │   • Schema evolution log     │                    │
│                                             └──────────────────────────────┘                    │
│                                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. What Schema Evolution Means

Schema evolution is the ability of a data platform to handle changes in source data structure — new columns appearing, columns disappearing, data types changing — without breaking existing pipelines or downstream consumers.

In Apache Iceberg, schema evolution is a first-class operation. Iceberg tracks schema versions in its metadata layer. Each table snapshot records which schema version it was written with. This means:

- Old data retains its original schema
- New data uses the new schema
- Queries across both return a unified view (missing columns filled with NULL)
- No data rewrite is required when schema changes

**In CDH 2.0, schema evolution is not a single behaviour. It is a layer-specific governance policy that determines what changes are permitted at each stage of the pipeline.**

---

## 3. What We Are Implementing

We are implementing a **layer-aware schema evolution engine** that enforces different rules at each pipeline layer:

| Layer | Policy | Rationale |
|-------|--------|-----------|
| **Bronze** | Accept everything | Bronze is the raw audit trail. Source systems change without notice. We never lose data. |
| **Silver** | Non-breaking only | Silver is the curated, governed layer. Breaking changes (column drops, type narrowing) would corrupt SCD2 history and break downstream joins. |
| **Gold** | Contract-locked | Gold is the published data product. Consumers depend on a fixed schema. Any change requires an explicit contract version bump. |

### Specific Change Types and Their Treatment

| Change Type | Bronze | Silver | Gold |
|-------------|--------|--------|------|
| New column added by source | ✅ Auto-accept | ✅ Accept (nullable) | ❌ Blocked — contract change required |
| Column dropped by source | ✅ Accept (NULL-fill) | ❌ Blocked — pipeline fails with error | ❌ Blocked |
| Type widening (int → bigint, float → double) | ✅ Auto-accept | ✅ Accept | ❌ Blocked — contract change required |
| Type narrowing (bigint → int, double → float) | ✅ Accept (cast) | ❌ Blocked — pipeline fails with error | ❌ Blocked |
| Column rename | ✅ Treated as add + drop | ❌ Blocked (use alias mapping) | ❌ Blocked |

---

## 4. How It Is Implemented

### 4.1 Configuration (Per-Table YAML)

Every table declares its schema evolution rules explicitly in its config file:

```yaml
# config/tables/pos_transactions.yaml
schema_evolution:
  bronze:
    allowed: [add_column, type_widen, drop_column]
  silver:
    allowed: [add_column, type_widen]
    blocked: [drop_column, type_narrow]
```

There is no implicit behaviour. If a change type is not in `allowed`, it is not permitted. If it is in `blocked`, the pipeline raises a RuntimeError and halts.

### 4.2 Engine: SchemaEvolver Class

**File:** `eastside/engine/schema_evolver.py`

The SchemaEvolver is instantiated with three arguments:
1. `spark` — the SparkSession
2. `table_config` — the table's YAML config (contains `schema_evolution` block)
3. `layer` — one of `bronze`, `silver`, `gold`

It exposes two methods:
- `detect_changes(df, table_full)` — compares incoming DataFrame schema against the existing Iceberg table schema
- `apply(df, table_full)` — enforces the layer's rules and returns an aligned DataFrame

### 4.3 Detection Logic

The engine compares incoming vs existing schemas and classifies changes into three categories:

```
changes = {
    "add_columns":    {col_name: data_type},   # columns in incoming but not in table
    "type_changes":   {col_name: {from, to}},  # same column, different type
    "dropped_columns": [col_name]              # columns in table but not in incoming
}
```

Metadata columns (`_ingested_at`, `_source_file`, `_batch_id`, `_dq_flags`, `row_hash`, `valid_from`, `valid_to`, `is_current`, `_gold_published_at`) are excluded from drop detection. These are platform-managed columns, not source columns.

### 4.4 Enforcement Logic

For each detected change, the engine checks the layer's `allowed` and `blocked` lists:

**Add Column:**
- If `add_column` in `allowed` → execute `ALTER TABLE ADD COLUMNS` via Spark SQL
- If `add_column` in `blocked` → raise RuntimeError (pipeline halts)
- If neither → warn and let Iceberg's `merge-schema` handle it

**Type Change:**
- Determine if the change is a widening (safe promotion) using a hardcoded map:
  ```
  int → bigint     ✅ widen
  int → double     ✅ widen
  bigint → double  ✅ widen
  float → double   ✅ widen
  short → int      ✅ widen
  ```
- If widen and `type_widen` in `allowed` → proceed
- If narrow and `type_narrow` in `blocked` → raise RuntimeError (pipeline halts)
- Otherwise → warn and cast

**Drop Column:**
- If `drop_column` in `blocked` → raise RuntimeError (pipeline halts)
- Otherwise → NULL-fill the missing columns in the incoming DataFrame so the write succeeds

### 4.5 Column Alignment

After enforcement, `align_to_table(df, table_full)` reorders the DataFrame columns to match the existing table's column order and adds any missing columns as NULL. This prevents Iceberg write failures due to column ordering mismatches.

### 4.6 Integration Points

The SchemaEvolver is called at two points in the pipeline:

**Bronze (in `bronze.py`):**
```python
evolver = SchemaEvolver(spark, table_config, "bronze")
df = evolver.apply(df, target_table)
df = evolver.align_to_table(df, target_table)
df.writeTo(target_table).option("merge-schema", "true").append()
```

**Silver (in `silver.py`):**
```python
evolver = SchemaEvolver(spark, table_config, "silver")
df = evolver.apply(df, target_table)
df = evolver.align_to_table(df, target_table)
```

**Gold (in `gold.py`):**
Gold does not use SchemaEvolver directly. Instead, it uses contract validation: if the silver output does not contain all required columns defined in the table config, the pipeline fails. This is a stricter check — it validates presence of expected columns rather than reacting to drift.

---

## 5. Failure Modes

| Scenario | Layer | Behaviour |
|----------|-------|-----------|
| Source adds a new column | Bronze | Column added to Iceberg table automatically. No intervention needed. |
| Source adds a new column | Silver | Column added as nullable. Existing rows have NULL for this column. |
| Source drops a column | Bronze | Incoming data NULL-filled for the missing column. Write succeeds. |
| Source drops a column | Silver | **Pipeline fails.** RuntimeError raised. Requires manual intervention: either update the config to remove the column from expectations, or fix the source. |
| Source changes int to bigint | Bronze | Accepted silently. |
| Source changes int to bigint | Silver | Accepted (safe widening). |
| Source changes bigint to int | Silver | **Pipeline fails.** Type narrowing blocked. |
| Gold schema missing a required column | Gold | **Pipeline fails.** Contract violation. |

---

## 6. Why This Design

### Bronze accepts everything because:
- It is the immutable audit trail of what the source sent
- Rejecting data at bronze means data loss with no recovery path
- Detective policies flag issues without blocking ingestion
- Downstream layers (silver) handle governance

### Silver blocks breaking changes because:
- SCD2 history depends on schema stability — dropping a column corrupts historical records
- Type narrowing causes data truncation (bigint 3,000,000,000 → int overflow)
- Downstream gold and consumers depend on silver's schema being backward-compatible

### Gold enforces contracts because:
- Consumers (BI tools, APIs, ML models) bind to specific column names and types
- A schema change in gold without consumer coordination causes production failures
- Contract versioning forces explicit communication of breaking changes

---

## 7. Orchestration — Dagster

### 7.1 What Dagster Does

Dagster is the orchestration layer. It does not process data. It submits PySpark jobs to Dataproc Serverless and waits for completion. After each stage completes, it registers BigQuery external tables so the data is queryable.

### 7.2 Deployment

- **VM:** `eastside-dagster` — GCE `e2-small` (2 vCPU, 2GB RAM), Debian 12, `europe-west2-a`
- **Service Account:** `eastside-dagster@bt-df-lkhouse.iam.gserviceaccount.com`
- **IAM Roles:** `roles/dataproc.editor` (submit jobs), `roles/storage.objectViewer` (read configs)
- **Access:** Static IP, nginx reverse proxy on port 80, Dagster webserver on port 3000
- **Provisioned by:** Terraform (`eastside/terraform/main.tf`)

### 7.3 Asset Graph

Dagster defines three assets with explicit dependencies:

```
bronze_asset → silver_asset → gold_asset
```

Each asset:
1. Resolves which tables to process (`all` or a specific table name)
2. Submits a PySpark job to Dataproc Serverless via the `DataprocResource`
3. Polls the job status every 10 seconds until DONE, ERROR, or timeout (600s)
4. On success: registers a BigQuery external table pointing to the BLMS Iceberg table
5. On gold: additionally tags BQ columns with PII/PK metadata

### 7.4 Job Submission Detail

The `DataprocResource` constructs a Dataproc PySpark job with:

| Parameter | Value |
|-----------|-------|
| `main_python_file_uri` | `gs://eastside-lakehouse/engine/{stage}.py` |
| `python_file_uris` | `base.py`, `schema_evolver.py` |
| `jar_file_uris` | `iceberg-spark-runtime.jar`, `biglake-catalog.jar` |
| `args` | `--config gs://eastside-lakehouse/config/pipeline.yaml --table {table} --project bt-df-lkhouse` |
| `properties` | Spark catalog config pointing to BLMS (see section 8.2) |

### 7.5 Job Definition

```python
# eastside/orchestration/eastside_dagster/jobs.py
eastside_pipeline_job = define_asset_job(
    name="eastside_pipeline_job",
    selection=AssetSelection.groups("eastside"),
)
```

This job materialises all three assets in dependency order. Triggered manually from the Dagster UI or via schedule/sensor.

---

## 8. Role of BigLake Metastore (BLMS)

### 8.1 What BLMS Is

BigLake Metastore is GCP's managed Iceberg catalog. It is the equivalent of a Hive Metastore but purpose-built for Iceberg tables on GCS. It stores:

- **Table metadata:** schema (column names, types, IDs), partition specs, sort orders
- **Snapshot history:** every write creates a new snapshot; BLMS tracks the full chain
- **Schema versions:** each schema change is recorded with a version ID
- **Data file manifests:** pointers to the actual Parquet files in GCS

### 8.2 How Spark Connects to BLMS

The Spark session is configured with these properties (set by Dagster's `DataprocResource`):

```properties
spark.sql.catalog.lkhouse_eastside = org.apache.iceberg.spark.SparkCatalog
spark.sql.catalog.lkhouse_eastside.catalog-impl = org.apache.iceberg.gcp.biglake.BigLakeCatalog
spark.sql.catalog.lkhouse_eastside.gcp_project = bt-df-lkhouse
spark.sql.catalog.lkhouse_eastside.gcp_location = europe-west2
spark.sql.catalog.lkhouse_eastside.blms_catalog = lkhouse_eastside
spark.sql.catalog.lkhouse_eastside.warehouse = gs://eastside-lakehouse
```

With this config, Spark SQL statements like `ALTER TABLE lkhouse_eastside.bronze.pos_transactions ADD COLUMNS (...)` are executed against BLMS. BLMS updates the metadata; Spark writes the data files to GCS.

### 8.3 BLMS Structure for EastSide

```
Catalog: lkhouse_eastside
├── Database: bronze
│   ├── pos_transactions
│   ├── online_orders
│   ├── inventory_movements
│   ├── customer_profiles
│   ├── product_catalogue
│   ├── supplier_purchase_orders
│   ├── returns_exchanges
│   └── store_staff
└── Database: silver
    ├── pos_transactions
    ├── online_orders
    ├── inventory_movements
    ├── customer_profiles
    ├── product_catalogue
    ├── supplier_purchase_orders
    ├── returns_exchanges
    └── store_staff
```

Provisioned by Terraform:
```hcl
resource "google_biglake_catalog" "eastside" {
  name     = "eastside"
  location = "europe-west2"
}

resource "google_biglake_database" "bronze" {
  name    = "bronze"
  catalog = google_biglake_catalog.eastside.id
  type    = "HIVE"
  hive_options {
    location_uri = "gs://eastside-lakehouse/bronze"
  }
}

resource "google_biglake_database" "silver" {
  name    = "silver"
  catalog = google_biglake_catalog.eastside.id
  type    = "HIVE"
  hive_options {
    location_uri = "gs://eastside-lakehouse/silver"
  }
}
```

### 8.4 BLMS and Schema Evolution

When the SchemaEvolver executes `ALTER TABLE ... ADD COLUMNS`, BLMS:
1. Creates a new schema version (increments schema ID)
2. Records the new column with a unique column ID
3. Updates the current-schema pointer
4. Does NOT rewrite existing data files — old files retain the old schema

When a query reads across snapshots with different schemas, Iceberg resolves columns by ID (not by name or position). Missing columns in old files return NULL.

---

## 9. BigQuery External Tables — How Iceberg Data Is Viewed in BQ

### 9.1 The Problem

Iceberg tables live in GCS as Parquet files, managed by BLMS. BigQuery cannot natively query GCS Parquet files with Iceberg metadata (snapshots, schema evolution, partition pruning) unless it knows about the Iceberg catalog.

### 9.2 The Solution: BigLake External Tables

After each Dagster asset completes, it creates a BigQuery external table that points to the BLMS Iceberg table. This gives BigQuery users (analysts, BI tools) direct SQL access to bronze and silver data without any data movement.

### 9.3 How It Works

```sql
CREATE OR REPLACE EXTERNAL TABLE `bt-df-lkhouse.eastside_bronze.pos_transactions`
WITH CONNECTION `projects/bt-df-lkhouse/locations/europe-west2/connections/biglake-conn`
OPTIONS (
    format = 'ICEBERG',
    uris = ['blms://projects/bt-df-lkhouse/locations/europe-west2/catalogs/lkhouse_eastside/databases/bronze/tables/pos_transactions']
)
```

**What this does:**
- Creates a table in BQ dataset `eastside_bronze` called `pos_transactions`
- The table is not a copy — it reads directly from the Iceberg data files in GCS
- Uses the `biglake-conn` BigQuery connection for authentication to GCS
- The `blms://` URI tells BigQuery to resolve the table via BLMS metadata
- BigQuery inherits Iceberg's schema, partition pruning, and snapshot isolation

### 9.4 External Table Registration Flow

```
Dataproc job completes (e.g. bronze.py writes to lkhouse_eastside.bronze.pos_transactions)
    │
    ▼
Dagster asset calls register_bq_external_table()
    │
    ├── Check: does BQ table already exist?
    │   ├── Yes → skip (idempotent)
    │   └── No → execute CREATE EXTERNAL TABLE SQL
    │
    ▼
BQ external table now queryable:
    SELECT * FROM `bt-df-lkhouse.eastside_bronze.pos_transactions`
```

### 9.5 Three BQ Datasets, Three Purposes

| BQ Dataset | Type | Source | Purpose |
|------------|------|--------|---------|
| `eastside_bronze` | External tables | BLMS bronze database | Debug, audit, data exploration. Full raw data with DQ flags. |
| `eastside_silver` | External tables | BLMS silver database | Curated data access. SCD2 history. Used by analysts who need historical views. |
| `eastside_dataproduct` | Native BQ tables | Written by `gold.py` via Spark BQ connector | Production data products. Contract-enforced schema. Consumed by BI tools, APIs, ML. |

### 9.6 Why Gold Is Native, Not External

Gold tables are written directly to BigQuery as native tables (not external). This is intentional:
- Native BQ tables support column-level security (Dataplex policy tags)
- Native BQ tables support row-level security
- Native BQ tables have full BQ performance optimisation (clustering, caching)
- Gold is the consumption layer — it needs BQ's full feature set

Bronze and silver are external because:
- They are primarily accessed by engineers and the pipeline itself (via Spark)
- External tables provide zero-copy access — no data duplication
- Schema evolution in Iceberg is reflected immediately in BQ without re-registration

### 9.7 Column Tagging

After gold tables are written, Dagster calls `tag_columns()` which:
1. Reads the table config YAML
2. Identifies PII fields and the primary key
3. Updates BQ column descriptions with metadata (e.g. "Primary Key", "PII")
4. This enables Dataplex to apply column-level security policies based on these tags

---

## 10. Operational Procedures

### When a source adds a new column:
1. Bronze picks it up automatically on next run
2. Silver picks it up automatically (nullable)
3. Gold ignores it (not in contract) — column is available in silver for ad-hoc queries
4. To expose in gold: update the table config, bump contract version, notify consumers

### When a source drops a column:
1. Bronze NULL-fills and succeeds
2. Silver fails with: `Schema evolution BLOCKED on '{table}' (silver): drop_column blocked. Missing: [col_name]`
3. Action required: investigate why source dropped the column
   - If intentional: remove column from silver's expected schema in config, re-run
   - If accidental: fix the source, re-run

### When a source changes a data type:
1. If widening (int → bigint): passes through bronze and silver automatically
2. If narrowing (bigint → int): bronze accepts, silver blocks
3. Action required for narrowing: investigate source, either revert the source change or explicitly update the config to accept the new type

---

## 11. Monitoring

Schema evolution events are logged to GCS (`gs://eastside-lakehouse/{layer}/_logs/`) with structured messages:

- `✅ ADD: {col_name} ({type})` — column added successfully
- `✅ WIDEN: {col_name} ({from} → {to})` — type widened successfully
- `🚫 BLOCKED: drop_column [{col_names}]` — pipeline halted due to blocked change
- `🚫 BLOCKED: type_narrow on {col_name} ({from} → {to})` — pipeline halted
- `⚠️ Dropped columns (NULL-filled): [{col_names}]` — columns missing but accepted (bronze)
- `No schema changes detected` — schema matches, no action taken

---

## 12. Relationship to Iceberg Features

| Iceberg Feature | How CDH 2.0 Uses It |
|-----------------|---------------------|
| Schema versioning | Each write records the schema version in the snapshot metadata |
| Column ID tracking | Iceberg assigns stable IDs to columns — renames don't break reads |
| `merge-schema` write option | Bronze uses this to auto-evolve the table schema on write |
| `ALTER TABLE ADD COLUMNS` | SchemaEvolver uses this for explicit column additions |
| Snapshot isolation | Readers always see a consistent schema — no partial writes |
| Time travel | Query historical data with its original schema via `VERSION AS OF` |

---

## 13. End-to-End Execution Sequence

This is the exact sequence of operations when the `eastside_pipeline_job` is triggered in Dagster:

```
1. Dagster materialises bronze_asset
   │
   ├── For each table (8 tables):
   │   ├── Submit Dataproc job: bronze.py --table {table} --version v1
   │   │   ├── Read raw files from gs://eastside-lakehouse/landing/{table}/v1/
   │   │   ├── CDC reconstruction (if is_cdc=true)
   │   │   ├── Compute row_hash (SHA256)
   │   │   ├── Add metadata columns (_ingested_at, _source_file, _batch_id)
   │   │   ├── Run detective DQ policies → populate _dq_flags
   │   │   ├── SchemaEvolver(layer="bronze").apply() → accept all changes
   │   │   ├── Append to lkhouse_eastside.bronze.{table} (BLMS)
   │   │   └── Write watermark to GCS
   │   │
   │   └── Register BQ external table: eastside_bronze.{table} → BLMS bronze.{table}
   │
2. Dagster materialises silver_asset (depends on bronze_asset)
   │
   ├── For each table:
   │   ├── Submit Dataproc job: silver.py --table {table}
   │   │   ├── Read from lkhouse_eastside.bronze.{table}
   │   │   ├── Dedup by row_hash (left_anti join against existing silver)
   │   │   ├── Preventative DQ (reject NULL PKs, invalid values)
   │   │   ├── Strip non-printable characters
   │   │   ├── Standardise fields (trim, uppercase postcodes)
   │   │   ├── Apply masking (SHA256 on PII fields)
   │   │   ├── Late arrival check (quarantine if outside window)
   │   │   ├── SchemaEvolver(layer="silver").apply() → block drops/narrows
   │   │   └── SCD2 merge into lkhouse_eastside.silver.{table}
   │   │
   │   └── Register BQ external table: eastside_silver.{table} → BLMS silver.{table}
   │
3. Dagster materialises gold_asset (depends on silver_asset)
   │
   ├── For each table:
   │   ├── Submit Dataproc job: gold.py --table {table}
   │   │   ├── Read from lkhouse_eastside.silver.{table} WHERE is_current=true
   │   │   ├── Contract validation (required columns present, PK unique)
   │   │   ├── Project gold schema (drop internal columns)
   │   │   └── Write to BigQuery: eastside_dataproduct.{table} (native, overwrite)
   │   │
   │   └── Tag BQ columns with PII/PK metadata
   │
4. Pipeline complete
```

---

## 14. Alias Mapping (Column Rename Handling)

### Problem

Source systems rename columns without notice. Example: `customer_name` becomes `cust_name`. The engine detects this as an add + drop, which blocks silver.

### Solution

Declare aliases in the table config. The SchemaEvolver renames incoming columns to their canonical names before detection runs:

```yaml
schema_evolution:
  aliases:
    cust_name: customer_name
    txn_id: transaction_id
    txn_datetime: transaction_datetime
    sku: product_sku
```

**Behaviour:**
1. Incoming data has column `cust_name`
2. SchemaEvolver calls `apply_aliases()` → renames to `customer_name`
3. Detection sees no change (column exists with correct name)
4. Pipeline proceeds without failure

This eliminates manual intervention for known renames. Unknown renames still trigger the add + drop detection.

---

## 15. Externalised Type Widening Rules

### Problem

The original hardcoded widening map only covered 5 type pairs. Real-world sources (SAP, Salesforce, Oracle CDC) produce many more: `decimal(10,2) → decimal(20,2)`, `date → timestamp`, `int → decimal`.

### Solution

Type rules are defined in `config/type_rules.yaml` and loaded at runtime:

```yaml
widen:
  - "short -> int"
  - "int -> bigint"
  - "int -> long"
  - "int -> double"
  - "int -> decimal"
  - "bigint -> double"
  - "bigint -> decimal"
  - "float -> double"
  - "decimal(10,2) -> decimal(20,2)"
  - "decimal(18,2) -> decimal(38,2)"
  - "date -> timestamp"
  - "int -> string"
  - "bigint -> string"
```

Adding a new rule requires editing this YAML file. No code change needed.

---

## 16. Graceful Mode (Strict vs Available)

### Problem

Strict enforcement means a source dropping a column on Friday evening stops the entire data product until Monday.

### Solution

Two modes per layer, configured per table:

```yaml
schema_evolution:
  silver:
    allowed: [add_column, type_widen]
    blocked: [drop_column, type_narrow]
    on_drop: fail               # strict (default)
    on_narrow: fail             # strict (default)
```

Alternative:
```yaml
    on_drop: null_fill_and_alert    # graceful — NULL-fill, continue, send alert
    on_narrow: cast_and_alert       # graceful — cast, continue, send alert
```

**Strict mode (default):** Pipeline fails. Data product unavailable until resolved. Zero risk of silent data corruption.

**Graceful mode:** Pipeline continues. Missing column is NULL-filled. Alert fires immediately. Data product remains available but with degraded quality on the affected column.

The choice is per-table. Critical tables (financial, regulatory) use strict. Non-critical tables (marketing, analytics) can use graceful.

---

## 17. Schema Audit Table

### Problem

Logs are useful but difficult to query. No way to answer: "How many schema changes happened last month?" or "Which tables have the most drift?"

### Solution

Every schema change is written to a structured Iceberg audit table:

```
{catalog}.{namespace}.schema_change_audit
```

| Column | Type | Description |
|--------|------|-------------|
| `table_name` | string | Table that changed |
| `layer` | string | bronze / silver / gold |
| `change_type` | string | add_column / drop_column / type_widen / type_narrow |
| `column_name` | string | Affected column |
| `old_type` | string | Previous type (empty for adds) |
| `new_type` | string | New type (empty for drops) |
| `event_timestamp` | string | When the change was detected |
| `run_id` | string | Pipeline run identifier |
| `status` | string | applied / blocked / graceful_null_fill / graceful_cast |
| `_recorded_at` | timestamp | When the audit record was written |

Query examples:
```sql
-- Tables with most schema drift
SELECT table_name, COUNT(*) as changes
FROM schema_change_audit
WHERE event_timestamp > '2026-07-01'
GROUP BY table_name
ORDER BY changes DESC;

-- All blocked changes (requires investigation)
SELECT * FROM schema_change_audit
WHERE status = 'blocked'
ORDER BY event_timestamp DESC;
```

---

## 18. Schema Fingerprint (Performance Optimisation)

### Problem

For hundreds of tables, running `detect_changes()` on every execution is expensive — it reads the existing table schema from BLMS every time.

### Solution

After each successful run, persist a hash of the incoming schema:

```json
// gs://{bucket}/{layer}/_schema_fingerprints/{table}.json
{
  "fingerprint": "a3f2b8c1e9d04f7a",
  "columns": ["transaction_id", "store_id", "product_sku", ...],
  "updated_at": "2026-07-13T07:34:00"
}
```

On next run:
1. Compute fingerprint of incoming DataFrame
2. Compare against stored fingerprint
3. If identical → skip detection entirely (no BLMS read)
4. If different → run full detection

This reduces catalog lookups by ~90% for stable tables.

---

## 19. Schema Quarantine

### Problem

When silver blocks a schema change, the pipeline fails and the batch is lost. The only recovery is to fix the source and re-run. There's no record of what the offending data looked like.

### Solution

When a schema violation is detected, the offending batch is written to a quarantine table before the pipeline fails:

```
{catalog}.silver.{table}_schema_quarantine
```

Additional columns:
- `_schema_quarantine_reason` — e.g. "drop_column blocked: ['unit_price']"
- `_schema_diff` — JSON of the detected changes
- `_quarantined_at` — timestamp

This provides:
- Full record of what the source sent
- The exact schema diff that caused the failure
- Data available for replay once the issue is resolved

---

## 20. Gold Contract Versioning

### Problem

Gold schema is "contract-locked" but there's no formal versioning, no history, and no consumer notification process.

### Solution

Contracts are stored as versioned YAML files:

```
contracts/
  pos_transactions/
    v1.0.0.yaml
    v1.1.0.yaml    ← minor: column added
    v2.0.0.yaml    ← major: breaking change
```

Table config references the active version:
```yaml
contract_version: "1.0.0"
```

Contract file defines:
```yaml
contract:
  name: pos_transactions
  version: "1.0.0"
  status: active
  owner:
    team: retail_data
    data_steward: Chandra Prakash
  schema:
    primary_key: transaction_id
    required_columns:
      - name: transaction_id
        type: string
        nullable: false
      - name: unit_price
        type: double
        nullable: false
  consumers:
    - name: retail_dashboard
      team: bi_team
  changelog:
    - version: "1.0.0"
      date: "2026-07-09"
      change: "Initial contract"
```

**Versioning rules:**
- Patch (1.0.1): metadata change only (description, owner)
- Minor (1.1.0): non-breaking change (new optional column)
- Major (2.0.0): breaking change (column drop, type change, rename)

**Process for a breaking change:**
1. Create new contract version file
2. Update `contract_version` in table config
3. Notify consumers listed in the contract
4. Get approval from data steward
5. Deploy

---

## 21. Alerting

### Problem

Pipeline fails silently. No one knows until a consumer reports missing data.

### Solution

Dagster failure hooks send alerts on any asset failure:

```python
@failure_hook
def alert_on_failure(context: HookContext):
    # Categorise the failure
    if "Schema evolution BLOCKED" in error:
        category = "🚫 SCHEMA EVOLUTION BLOCKED"
    elif "contract violation" in error:
        category = "📋 CONTRACT VIOLATION"
    else:
        category = "❌ PIPELINE FAILURE"

    # Send to Slack / Google Chat / Email
    send_alert(category, asset_name, run_id, error)
```

Configured via environment variables on the Dagster VM:
```
ALERT_SLACK_WEBHOOK=https://hooks.slack.com/services/...
ALERT_GCHAT_WEBHOOK=https://chat.googleapis.com/v1/spaces/...
ALERT_EMAIL_TO=data-team@company.com
```

Alerts fire for:
- `drop_column` blocked
- `type_narrow` blocked
- Contract violation
- Dataproc job failure
- Timeout

---

## 22. Metadata Governance (Ownership)

Every table config declares ownership explicitly:

```yaml
owner:
  team: retail_data
  email: retail-data@company.com
data_steward: Chandra Prakash
```

This enables:
- Schema change alerts routed to the correct team
- Contract approval workflow knows who to ask
- Audit trail shows who owns the data

---

## 23. Data Protection (SHA256 vs KMS)

Two distinct mechanisms, configured per-column:

| Method | Config | Reversible | Use Case |
|--------|--------|------------|----------|
| SHA256 hash | `masking: {email: sha256}` | No | Analytics — field is used for joins/grouping but value is never revealed |
| KMS AES-256 | `encryption: {pan_number: aes256}` | Yes (with key access) | Authorised users can decrypt for fraud investigation, compliance |

Both are applied in the silver layer on write. Gold inherits the protected values.

---

## 24. Configuration Reference

Full table config with all schema evolution features:

```yaml
table: pos_transactions
description: "Point-of-sale line items from 50+ physical stores"
source_format: json
source_system: pos
domain: sales
business_application: retail_pos
is_cdc: false

owner:
  team: retail_data
  email: retail-data@company.com
data_steward: Chandra Prakash

contract_version: "1.0.0"

primary_key: transaction_id
hash_fields: [transaction_id, product_sku, transaction_datetime]

dq_rules:
  not_null: [transaction_id, store_id, product_sku, quantity, unit_price]
  positive: [quantity, unit_price]

pii_fields: []
masking: {}
encryption: {}

schema_evolution:
  aliases:
    txn_id: transaction_id
    txn_datetime: transaction_datetime
    sku: product_sku
  bronze:
    allowed: [add_column, type_widen, drop_column]
  silver:
    allowed: [add_column, type_widen]
    blocked: [drop_column, type_narrow]
    on_drop: fail               # fail | null_fill_and_alert
    on_narrow: fail             # fail | cast_and_alert
```

Valid values for `allowed` and `blocked`:
- `add_column` — new column appears in incoming data
- `drop_column` — existing column missing from incoming data
- `type_widen` — data type promoted to a wider type (int → bigint)
- `type_narrow` — data type demoted to a narrower type (bigint → int)

---

## 25. Technology Stack Summary

| Component | Technology | Purpose |
|-----------|------------|---------|
| Storage | GCS (`gs://eastside-lakehouse/`) | All data files (Parquet managed by Iceberg) |
| Table Format | Apache Iceberg | Schema evolution, time travel, snapshot isolation |
| Catalog | BigLake Metastore (BLMS) | Iceberg metadata management (schemas, snapshots, manifests) |
| Compute | Dataproc Serverless (PySpark) | Executes bronze.py, silver.py, gold.py |
| Orchestration | Dagster (GCE VM) | Job sequencing, BQ registration, column tagging, alerting |
| Gold Layer | BigQuery (native tables) | Consumption-optimised data products |
| Bronze/Silver Query | BigQuery (external tables via BigLake connection) | Zero-copy SQL access to Iceberg data |
| Encryption | Cloud KMS (`pii-encryption-key`) | AES-256 for reversible PII protection in silver |
| Alerting | Dagster hooks → Slack / Google Chat / Email | Failure notification |
| IaC | Terraform | Bucket, BLMS catalog, BQ datasets, IAM, Dagster VM |
| CI/CD | Cloud Build | Deployment automation |
