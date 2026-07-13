"""Schema Evolution Demo — Generate v2 and v3 data for pos_transactions.

v2: Adds a new column `loyalty_points_earned` (integer) — simulates source adding a field.
v3: Drops `unit_price` column — simulates source removing a field.

Run from Cloud Shell:
    pip install google-cloud-storage
    python eastside/datagen/generate_schema_evolution_demo.py --project=bt-df-lkhouse

After running:
    1. Go to Dagster UI
    2. Materialise bronze_asset with config: {"table": "pos_transactions"} and version v2
    3. Verify in BQ (see queries at bottom of this file)
    4. Materialise bronze_asset with version v3
    5. Then materialise silver_asset — watch it FAIL on drop_column
"""
import argparse
import json
import random
from datetime import datetime, timedelta
from google.cloud import storage

random.seed(99)

BUCKET = "eastside-lakehouse"

STORES = [f"STR{i:03d}" for i in range(1, 51)]
PAYMENT_METHODS = ["card", "cash", "contactless", "apple_pay", "google_pay", "gift_card"]


def rand_date(start="2025-06-01", end="2025-07-09"):
    s = datetime.fromisoformat(start)
    e = datetime.fromisoformat(end)
    return (s + timedelta(seconds=random.randint(0, int((e - s).total_seconds())))).strftime("%Y-%m-%dT%H:%M:%S")


def rand_sku():
    cat = random.choice(["MEN", "WMN", "KID", "FTW", "ACC", "SPT", "OUT"])
    return f"{cat}-{random.randint(10000, 99999)}"


def upload_jsonl(client, bucket_name, path, records):
    bucket = client.bucket(bucket_name)
    content = "\n".join(json.dumps(r) for r in records)
    blob_path = f"{path}/part-00000.jsonl"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(content, content_type="application/json")
    print(f"  -> gs://{bucket_name}/{blob_path} ({len(records):,} records)")


# ============================================================
# V2: Same schema as v1 + new column `loyalty_points_earned`
# ============================================================
def generate_v2(n=2000):
    """POS transactions with an additional loyalty_points_earned column."""
    print(f"\n[V2] POS Transactions — NEW COLUMN: loyalty_points_earned ({n} records)")
    records = []
    for i in range(n):
        store = random.choice(STORES)
        records.append({
            "transaction_id": f"POS{3000000 + i}",
            "basket_id": f"BKT{random.randint(100000, 999999)}",
            "store_id": store,
            "till_id": f"{store}-T{random.randint(1, 8)}",
            "customer_id": f"CUST{random.randint(1, 2000):06d}" if random.random() < 0.6 else None,
            "product_sku": rand_sku(),
            "quantity": random.randint(1, 5),
            "unit_price": round(random.uniform(5.99, 199.99), 2),
            "discount_amount": round(random.uniform(0, 20.0), 2) if random.random() < 0.3 else 0.0,
            "payment_method": random.choice(PAYMENT_METHODS),
            "transaction_datetime": rand_date(),
            "staff_id": f"EMP{random.randint(1, 200):04d}",
            # --- NEW COLUMN ---
            "loyalty_points_earned": random.randint(10, 500) if random.random() < 0.6 else 0,
        })
    return records


# ============================================================
# V3: Drops `unit_price` column — simulates source removing a field
# ============================================================
def generate_v3(n=1000):
    """POS transactions WITHOUT unit_price — simulates column drop."""
    print(f"\n[V3] POS Transactions — DROPPED COLUMN: unit_price ({n} records)")
    records = []
    for i in range(n):
        store = random.choice(STORES)
        records.append({
            "transaction_id": f"POS{5000000 + i}",
            "basket_id": f"BKT{random.randint(100000, 999999)}",
            "store_id": store,
            "till_id": f"{store}-T{random.randint(1, 8)}",
            "customer_id": f"CUST{random.randint(1, 2000):06d}" if random.random() < 0.6 else None,
            "product_sku": rand_sku(),
            "quantity": random.randint(1, 5),
            # unit_price is MISSING — this is the breaking change
            "discount_amount": round(random.uniform(0, 20.0), 2) if random.random() < 0.3 else 0.0,
            "payment_method": random.choice(PAYMENT_METHODS),
            "transaction_datetime": rand_date(),
            "staff_id": f"EMP{random.randint(1, 200):04d}",
            "loyalty_points_earned": random.randint(10, 500) if random.random() < 0.6 else 0,
        })
    return records


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Schema Evolution Demo — v2 and v3 data")
    parser.add_argument("--project", default="bt-df-lkhouse")
    parser.add_argument("--bucket", default=BUCKET)
    args = parser.parse_args()

    client = storage.Client(project=args.project)

    print("=" * 60)
    print("  SCHEMA EVOLUTION DEMO — Data Generation")
    print("=" * 60)
    print(f"  Project: {args.project}")
    print(f"  Bucket:  gs://{args.bucket}/")

    # V2: new column
    v2_data = generate_v2()
    upload_jsonl(client, args.bucket, "landing/pos_transactions/v2", v2_data)

    # V3: dropped column
    v3_data = generate_v3()
    upload_jsonl(client, args.bucket, "landing/pos_transactions/v3", v3_data)

    print(f"\n{'=' * 60}")
    print("  DATA GENERATED")
    print("=" * 60)
    print(f"""
  Landing zones populated:
    landing/pos_transactions/v2/  (2,000 records)  — has new column: loyalty_points_earned
    landing/pos_transactions/v3/  (1,000 records)  — missing column: unit_price

  DEMO STEPS:
  ───────────
  Step 1: Run bronze for v2 from Dagster (or Dataproc)
          → Expected: SchemaEvolver adds loyalty_points_earned to Iceberg table
          → BQ external table auto-reflects new column

  Step 2: Run silver for pos_transactions from Dagster
          → Expected: New column accepted (add_column in silver.allowed)
          → SCD2 merge succeeds

  Step 3: Run bronze for v3 from Dagster
          → Expected: SchemaEvolver NULL-fills unit_price (bronze accepts drops)
          → Bronze succeeds

  Step 4: Run silver for pos_transactions from Dagster
          → Expected: PIPELINE FAILS
          → Error: "Schema evolution BLOCKED on 'pos_transactions' (silver):
                    drop_column blocked. Missing: ['unit_price']"

  VERIFICATION QUERIES (run in BigQuery):
  ───────────────────────────────────────
""")

    print_verification_queries()
    print("=" * 60)


def print_verification_queries():
    queries = """
-- ============================================================
-- QUERY 1: Check v1 data (before schema evolution)
-- Expect: loyalty_points_earned column does NOT exist yet
-- ============================================================
SELECT *
FROM `bt-df-lkhouse.eastside_bronze.pos_transactions`
WHERE transaction_id LIKE 'POS1%'
LIMIT 10;


-- ============================================================
-- QUERY 2: After v2 bronze run — verify new column exists
-- Expect: loyalty_points_earned column appears
--         Old v1 rows have NULL for this column
--         New v2 rows have integer values
-- ============================================================
SELECT
  transaction_id,
  unit_price,
  loyalty_points_earned,
  _ingested_at
FROM `bt-df-lkhouse.eastside_bronze.pos_transactions`
ORDER BY _ingested_at DESC
LIMIT 20;


-- ============================================================
-- QUERY 3: Prove old rows have NULL for new column
-- Expect: All v1 rows (POS1xxxxxx) have loyalty_points_earned = NULL
-- ============================================================
SELECT
  CASE
    WHEN transaction_id LIKE 'POS1%' THEN 'v1'
    WHEN transaction_id LIKE 'POS3%' THEN 'v2'
    WHEN transaction_id LIKE 'POS5%' THEN 'v3'
  END AS version,
  COUNT(*) AS record_count,
  COUNT(loyalty_points_earned) AS has_loyalty_points,
  COUNT(unit_price) AS has_unit_price
FROM `bt-df-lkhouse.eastside_bronze.pos_transactions`
GROUP BY 1
ORDER BY 1;


-- ============================================================
-- QUERY 4: After v3 bronze run — verify unit_price is NULL-filled
-- Expect: v3 rows (POS5xxxxxx) have unit_price = NULL
--         v1 and v2 rows still have unit_price populated
-- ============================================================
SELECT
  transaction_id,
  unit_price,
  loyalty_points_earned,
  _ingested_at
FROM `bt-df-lkhouse.eastside_bronze.pos_transactions`
WHERE transaction_id LIKE 'POS5%'
LIMIT 10;


-- ============================================================
-- QUERY 5: Check silver table — should NOT have v3 data
-- (because silver pipeline fails on drop_column)
-- Expect: Only v1 and v2 transaction_ids present
-- ============================================================
SELECT
  CASE
    WHEN transaction_id LIKE 'POS1%' THEN 'v1'
    WHEN transaction_id LIKE 'POS3%' THEN 'v2'
    WHEN transaction_id LIKE 'POS5%' THEN 'v3'
  END AS version,
  COUNT(*) AS record_count
FROM `bt-df-lkhouse.eastside_silver.pos_transactions`
WHERE is_current = true
GROUP BY 1
ORDER BY 1;


-- ============================================================
-- QUERY 6: Schema evolution proof — count columns over time
-- Run this after each version to see schema growing
-- ============================================================
SELECT
  column_name,
  data_type
FROM `bt-df-lkhouse.eastside_bronze.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'pos_transactions'
ORDER BY ordinal_position;


-- ============================================================
-- QUERY 7: Time travel — query bronze at a specific snapshot
-- (Get snapshot ID from Iceberg metadata or BLMS)
-- Expect: Querying old snapshot shows schema WITHOUT loyalty_points_earned
-- ============================================================
-- Note: Time travel via BQ external tables uses the latest snapshot.
-- For point-in-time queries, use Spark SQL:
--   SELECT * FROM lkhouse_eastside.bronze.pos_transactions VERSION AS OF <snapshot_id>
"""
    print(queries)


if __name__ == "__main__":
    main()
