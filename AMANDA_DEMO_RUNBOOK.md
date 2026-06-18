# Amanda Demo Runbook

## Prerequisites
- Cloud Shell authenticated to `bt-df-lkhouse`
- Confluent Kafka cluster running (ecomm_cluster_0, us-east1)
- `confluent/kafka.yaml` populated with real credentials

---

## PART 1: Full Execution (Start to Finish)

### Step 0: Cancel any running jobs
```bash
cd ~/bt-df-lkhouse-fw

# Check for running jobs
gcloud dataproc batches list --region=europe-west2 --project=bt-df-lkhouse --filter="state=RUNNING"

# Cancel if any (replace BATCH_ID)
# gcloud dataproc batches cancel <BATCH_ID> --region=europe-west2 --project=bt-df-lkhouse
```

### Step 1: Clean slate (optional — only if you want fresh data)
```bash
# Delete existing data
gsutil -m rm -r gs://bt-df-lkhouse-lakehouse/landing/
gsutil -m rm -r gs://bt-df-lkhouse-lakehouse/reservoir/
gsutil -m rm -r gs://bt-df-lkhouse-lakehouse/ccn/
gsutil -m rm -r gs://bt-df-lkhouse-lakehouse/checkpoints/
gsutil -m rm -r gs://bt-df-lkhouse-lakehouse/logs/

# Drop BQ external tables
bq rm -f bt-df-lkhouse:lakehouse_ccn.customers
bq rm -f bt-df-lkhouse:lakehouse_ccn.orders
bq rm -f bt-df-lkhouse:lakehouse_ccn.payments
bq rm -f bt-df-lkhouse:lakehouse_ccn.products
bq rm -f bt-df-lkhouse:lakehouse_ccn.clickstream
bq rm -f bt-df-lkhouse:lakehouse_dataproduct.customer_360
```

### Step 2: Generate V1 batch data
```bash
cd ~/bt-df-lkhouse-fw/datagen
python generate.py --project=bt-df-lkhouse --version=v1
```

### Step 3: Run batch pipeline — Ingest (Landing → Reservoir)
```bash
cd ~/bt-df-lkhouse-fw
bash scripts/run_pipeline.sh bt-df-lkhouse europe-west2 ingest v1
```

### Step 4: Run batch pipeline — Curate (Reservoir → CCN Iceberg)
```bash
bash scripts/run_pipeline.sh bt-df-lkhouse europe-west2 curate v1
```

### Step 5: Register CCN tables in BigQuery
```bash
# Get latest metadata files
gsutil ls gs://bt-df-lkhouse-lakehouse/ccn/customers/metadata/*.metadata.json
gsutil ls gs://bt-df-lkhouse-lakehouse/ccn/orders/metadata/*.metadata.json
gsutil ls gs://bt-df-lkhouse-lakehouse/ccn/payments/metadata/*.metadata.json
gsutil ls gs://bt-df-lkhouse-lakehouse/ccn/products/metadata/*.metadata.json

# Create external tables (use the HIGHEST numbered file from each listing above)
bq query --use_legacy_sql=false \
"CREATE OR REPLACE EXTERNAL TABLE \`bt-df-lkhouse.lakehouse_ccn.customers\`
WITH CONNECTION \`projects/bt-df-lkhouse/locations/europe-west2/connections/biglake-conn\`
OPTIONS (format='ICEBERG', uris=['gs://bt-df-lkhouse-lakehouse/ccn/customers/metadata/<LATEST>.metadata.json'])"

bq query --use_legacy_sql=false \
"CREATE OR REPLACE EXTERNAL TABLE \`bt-df-lkhouse.lakehouse_ccn.orders\`
WITH CONNECTION \`projects/bt-df-lkhouse/locations/europe-west2/connections/biglake-conn\`
OPTIONS (format='ICEBERG', uris=['gs://bt-df-lkhouse-lakehouse/ccn/orders/metadata/<LATEST>.metadata.json'])"

bq query --use_legacy_sql=false \
"CREATE OR REPLACE EXTERNAL TABLE \`bt-df-lkhouse.lakehouse_ccn.payments\`
WITH CONNECTION \`projects/bt-df-lkhouse/locations/europe-west2/connections/biglake-conn\`
OPTIONS (format='ICEBERG', uris=['gs://bt-df-lkhouse-lakehouse/ccn/payments/metadata/<LATEST>.metadata.json'])"

bq query --use_legacy_sql=false \
"CREATE OR REPLACE EXTERNAL TABLE \`bt-df-lkhouse.lakehouse_ccn.products\`
WITH CONNECTION \`projects/bt-df-lkhouse/locations/europe-west2/connections/biglake-conn\`
OPTIONS (format='ICEBERG', uris=['gs://bt-df-lkhouse-lakehouse/ccn/products/metadata/<LATEST>.metadata.json'])"
```

### Step 6: Build Data Product (BigQuery native)
```bash
python -m bt_df_lkhouse_fw.engine.consume --config bt_df_lkhouse_fw/config/pipeline.yaml --all --project bt-df-lkhouse
```

### Step 7: Verify V1 in BigQuery
```bash
bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM `bt-df-lkhouse.lakehouse_ccn.customers`'
bq query --use_legacy_sql=false 'SELECT * FROM `bt-df-lkhouse.lakehouse_dataproduct.customer_360` LIMIT 5'
```

### Step 8: Schema Evolution — Generate V2 data
```bash
cd ~/bt-df-lkhouse-fw/datagen
python generate.py --project=bt-df-lkhouse --version=v2
```

### Step 9: Run V2 pipeline (ingest + curate)
```bash
cd ~/bt-df-lkhouse-fw
bash scripts/run_pipeline.sh bt-df-lkhouse europe-west2 ingest v2
bash scripts/run_pipeline.sh bt-df-lkhouse europe-west2 curate v2
```

### Step 10: Update BQ external tables (new metadata after schema evolution)
```bash
# Get new latest metadata files and re-run CREATE OR REPLACE EXTERNAL TABLE
# (same as Step 5 but with the newer metadata file numbers)
```

### Step 11: Rebuild Data Product with new schema
```bash
bq query --use_legacy_sql=false \
"CREATE OR REPLACE TABLE \`bt-df-lkhouse.lakehouse_dataproduct.customer_360\` AS
SELECT
    c.customer_id, c.name, c.email, c.region, c.loyalty_tier,
    c.signup_date, c.is_active, c.customer_segment,
    COALESCE(o.total_orders, 0) AS total_orders,
    COALESCE(o.total_spend, 0.0) AS total_spend,
    COALESCE(o.avg_order_value, 0.0) AS avg_order_value,
    o.first_order_date, o.last_order_date,
    COALESCE(o.total_discounts, 0.0) AS total_discounts,
    COALESCE(p.total_payments, 0) AS total_payments,
    COALESCE(p.total_paid, 0.0) AS total_paid
FROM \`bt-df-lkhouse.lakehouse_ccn.customers\` c
LEFT JOIN (
    SELECT customer_id, COUNT(*) AS total_orders, SUM(total_amount) AS total_spend,
        AVG(total_amount) AS avg_order_value, MIN(order_date) AS first_order_date,
        MAX(order_date) AS last_order_date, SUM(discount_amount) AS total_discounts
    FROM \`bt-df-lkhouse.lakehouse_ccn.orders\` GROUP BY customer_id
) o ON c.customer_id = o.customer_id
LEFT JOIN (
    SELECT ord.customer_id, COUNT(*) AS total_payments, SUM(pay.amount) AS total_paid
    FROM \`bt-df-lkhouse.lakehouse_ccn.payments\` pay
    JOIN \`bt-df-lkhouse.lakehouse_ccn.orders\` ord ON pay.order_id = ord.order_id
    GROUP BY ord.customer_id
) p ON c.customer_id = p.customer_id"
```

### Step 12: Streaming — Start consumer
```bash
cd ~/bt-df-lkhouse-fw
bash scripts/run_stream.sh bt-df-lkhouse europe-west2 clickstream "30 seconds"
```

### Step 13: Streaming — Produce events (separate terminal)
```bash
cd ~/bt-df-lkhouse-fw/datagen
python stream_producer.py --config ../confluent/kafka.yaml --topic clickstream --rate 10 --total 500
```

### Step 14: Register clickstream in BigQuery
```bash
gsutil ls gs://bt-df-lkhouse-lakehouse/ccn/clickstream/metadata/*.metadata.json

bq query --use_legacy_sql=false \
"CREATE OR REPLACE EXTERNAL TABLE \`bt-df-lkhouse.lakehouse_ccn.clickstream\`
WITH CONNECTION \`projects/bt-df-lkhouse/locations/europe-west2/connections/biglake-conn\`
OPTIONS (format='ICEBERG', uris=['gs://bt-df-lkhouse-lakehouse/ccn/clickstream/metadata/<LATEST>.metadata.json'])"
```

### Step 15: Query streaming data
```bash
bq query --use_legacy_sql=false \
'SELECT event_type, COUNT(*) FROM `bt-df-lkhouse.lakehouse_ccn.clickstream` GROUP BY 1 ORDER BY 2 DESC'
```

### Step 16: STOP streaming job (saves money!)
```bash
gcloud dataproc batches list --region=europe-west2 --project=bt-df-lkhouse --filter="state=RUNNING"
gcloud dataproc batches cancel <BATCH_ID> --region=europe-west2 --project=bt-df-lkhouse
```

---

## PART 2: Iceberg Capabilities Queries

### Schema Evolution — New columns appear, old rows have NULL
```sql
-- V2 added 'customer_segment' — old V1 customers have NULL
SELECT
  customer_id,
  name,
  loyalty_tier,
  customer_segment
FROM `bt-df-lkhouse.lakehouse_ccn.customers`
ORDER BY customer_id
LIMIT 10;

-- Count populated vs NULL (proves schema evolution without rewrite)
SELECT
  COUNT(*) AS total_rows,
  COUNTIF(customer_segment IS NOT NULL) AS has_segment,
  COUNTIF(customer_segment IS NULL) AS no_segment,
  ROUND(COUNTIF(customer_segment IS NOT NULL) / COUNT(*) * 100, 1) AS pct_populated
FROM `bt-df-lkhouse.lakehouse_ccn.customers`;

-- New enum value (Diamond) only in V2 data
SELECT loyalty_tier, COUNT(*) AS cnt
FROM `bt-df-lkhouse.lakehouse_ccn.customers`
GROUP BY 1
ORDER BY cnt DESC;
```

### Schema Evolution — Payments got new column
```sql
-- V2 added 'payment_channel'
SELECT
  payment_channel,
  COUNT(*) AS cnt
FROM `bt-df-lkhouse.lakehouse_ccn.payments`
GROUP BY 1
ORDER BY cnt DESC;

-- Shows NULL for V1 rows, populated for V2 rows
SELECT
  COUNTIF(payment_channel IS NOT NULL) AS v2_rows,
  COUNTIF(payment_channel IS NULL) AS v1_rows
FROM `bt-df-lkhouse.lakehouse_ccn.payments`;
```

### Iceberg Metadata — Snapshots (Time Travel proof)
```sql
-- View Iceberg snapshot history (shows each write as a snapshot)
-- Run via Spark (not BQ) — demonstrates time-travel capability:
-- spark.sql("SELECT * FROM lakehouse.ccn.customers.snapshots")
-- spark.sql("SELECT * FROM lakehouse.ccn.customers.history")

-- In BigQuery, you can see the metadata versions in GCS:
-- gsutil ls gs://bt-df-lkhouse-lakehouse/ccn/customers/metadata/
-- Each .metadata.json = one schema version
-- 00000 = V1 create
-- 00001 = V1 createOrReplace (curate)
-- 00002 = V2 schema evolution (ADD COLUMN)
-- 00003 = V2 createOrReplace (curate with new data)
```

### Data Freshness — Streaming vs Batch
```sql
-- Streaming data is near real-time
SELECT
  MIN(ingestion_ts) AS earliest,
  MAX(ingestion_ts) AS latest,
  COUNT(*) AS total_events
FROM `bt-df-lkhouse.lakehouse_ccn.clickstream`;

-- Batch data shows ingestion timestamps
SELECT
  MIN(ingestion_ts) AS earliest_ingest,
  MAX(ingestion_ts) AS latest_ingest,
  COUNT(*) AS total
FROM `bt-df-lkhouse.lakehouse_ccn.customers`;
```

### Data Product — Aggregated view
```sql
-- Top customers by spend
SELECT customer_id, name, loyalty_tier, customer_segment,
       total_orders, total_spend, avg_order_value
FROM `bt-df-lkhouse.lakehouse_dataproduct.customer_360`
ORDER BY total_spend DESC
LIMIT 10;

-- Spend by loyalty tier
SELECT loyalty_tier,
       COUNT(*) AS customers,
       ROUND(AVG(total_spend), 2) AS avg_spend,
       ROUND(SUM(total_spend), 2) AS total_spend
FROM `bt-df-lkhouse.lakehouse_dataproduct.customer_360`
GROUP BY 1
ORDER BY total_spend DESC;

-- Spend by segment (V2 column — shows NULL for V1 customers)
SELECT customer_segment,
       COUNT(*) AS customers,
       ROUND(AVG(total_spend), 2) AS avg_spend
FROM `bt-df-lkhouse.lakehouse_dataproduct.customer_360`
GROUP BY 1
ORDER BY avg_spend DESC;
```

### Streaming Analytics
```sql
-- Events by type
SELECT event_type, COUNT(*) AS cnt
FROM `bt-df-lkhouse.lakehouse_ccn.clickstream`
GROUP BY 1 ORDER BY cnt DESC;

-- Funnel analysis
SELECT
  COUNTIF(event_type = 'page_view') AS page_views,
  COUNTIF(event_type = 'product_view') AS product_views,
  COUNTIF(event_type = 'add_to_cart') AS add_to_cart,
  COUNTIF(event_type = 'checkout_start') AS checkout_start,
  COUNTIF(event_type = 'purchase') AS purchases,
  ROUND(COUNTIF(event_type = 'purchase') / COUNTIF(event_type = 'page_view') * 100, 2) AS conversion_rate_pct
FROM `bt-df-lkhouse.lakehouse_ccn.clickstream`;
```

---

## PART 3: Governance Demo — Breaking vs Non-Breaking Changes

### 3.1 SAFE: Add a nullable column (pipeline will handle it)

Generate V2 data (which has new columns), then re-run pipeline.
The schema evolver logs will show:
```
✅ ALLOWED: Adding column 'customer_segment' (string)
✅ ALLOWED: Adding column 'payment_channel' (string)
```

This is already demonstrated by running V2 above.

### 3.2 SAFE: New enum values (no schema change needed)

V2 introduces `loyalty_tier = 'Diamond'` and `channel = 'marketplace'`.
No schema change required — Iceberg just stores new values:
```sql
-- Diamond only appears in V2 data
SELECT loyalty_tier, COUNT(*) FROM `bt-df-lkhouse.lakehouse_ccn.customers`
GROUP BY 1 ORDER BY 2 DESC;

-- marketplace channel only in V2
SELECT channel, COUNT(*) FROM `bt-df-lkhouse.lakehouse_ccn.orders`
GROUP BY 1 ORDER BY 2 DESC;
```

### 3.3 BLOCKED: Drop a column (pipeline will FAIL)

To demonstrate governance blocking a dangerous change:

Edit `bt_df_lkhouse_fw/config/tables/customers.yaml` and temporarily remove
a column from the V2 landing data (simulate source dropping a field).

The pipeline config says:
```yaml
schema_evolution:
  blocked: [drop_column, type_narrow]
```

When the schema evolver detects a column that exists in Iceberg but is
missing from the incoming data, it will raise:
```
🚫 BLOCKED: Cannot drop columns ['email']
RuntimeError: Schema change BLOCKED on 'customers': drop_column blocked.
```

**To simulate this without changing data**, you can manually test via Spark:
```python
# This would fail if you tried to write data missing the 'email' column
# The governance engine prevents it before any data is corrupted
```

### 3.4 BLOCKED: Type narrowing (pipeline will FAIL)

If source sent `amount` as INT (was DOUBLE), the pipeline would detect:
```
🚫 BLOCKED: Type narrowing 'amount' (double → int)
RuntimeError: Schema change BLOCKED on 'payments': Type narrowing on 'amount'
```

This is configured per table:
```yaml
schema_evolution:
  allowed: [add_column, type_widen]  # INT→BIGINT is fine
  blocked: [drop_column, type_narrow] # DOUBLE→INT is blocked
```

### 3.5 Show the governance config

```bash
# Each table has its own governance rules
cat bt_df_lkhouse_fw/config/tables/customers.yaml
cat bt_df_lkhouse_fw/config/tables/payments.yaml
```

Key talking point:
> "The governance is declarative — defined in YAML per table.
> The framework enforces it automatically. No human in the loop for safe changes.
> Breaking changes abort the pipeline immediately — no data corruption."

---

## PART 4: Architecture Talking Points

### Why three layers with different technology?

| Layer | Tech | Why |
|-------|------|-----|
| Reservoir | Parquet on GCS | Fast ingest, no catalog overhead, schema-on-read |
| CCN | Iceberg via BLMS | Governed: schema evolution, time-travel, ACID |
| Data Product | BigQuery native | Optimised for consumers, BQ-native features |

### Why not all Iceberg?
> "Reservoir doesn't need governance — it's raw data. Adding catalog overhead
> there slows down ingestion for no benefit. CCN is where governance lives."

### Why not all BigQuery?
> "CCN needs time-travel, schema evolution metadata, and ACID transactions.
> Iceberg gives us that with zero lock-in. Data Product is BigQuery because
> that's where consumers live — they get optimised tables, not raw Iceberg."

### How is this like Databricks?
> "Same medallion pattern. Databricks has Bronze/Silver/Gold with Delta Lake.
> We have Reservoir/CCN/Data Product with Iceberg. Same governance model,
> same schema evolution, but on GCP-native managed services."

---

## Cost Reminder

After the demo:
```bash
# Cancel any streaming jobs
gcloud dataproc batches list --region=europe-west2 --project=bt-df-lkhouse --filter="state=RUNNING"
gcloud dataproc batches cancel <BATCH_ID> --region=europe-west2 --project=bt-df-lkhouse

# Data at rest costs ~$1-2/day (mostly Cloud NAT)
# To fully stop costs: terraform destroy (nuclear option)
```
