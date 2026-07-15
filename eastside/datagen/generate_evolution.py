"""Schema Evolution Demo — Production-Realistic Data Generator.

Maintains a state file (GCS or local) with the last transaction ID used.
Each run generates FRESH data with new IDs — no duplicates, no need to clear watermarks.
Simulates a real source system producing new batches over time.

Usage:
    # Generate all 3 versions in one go (for demo prep):
    python eastside/datagen/generate_evolution.py --project=bt-df-lkhouse --all

    # Generate one version at a time (for live demo):
    python eastside/datagen/generate_evolution.py --project=bt-df-lkhouse --version v1
    python eastside/datagen/generate_evolution.py --project=bt-df-lkhouse --version v2
    python eastside/datagen/generate_evolution.py --project=bt-df-lkhouse --version v3

    # Reset state (start fresh):
    python eastside/datagen/generate_evolution.py --project=bt-df-lkhouse --reset

    # Use local state (no GCS):
    python eastside/datagen/generate_evolution.py --local --all
"""
import argparse
import json
import os
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

BUCKET = "eastside-lakehouse"
STATE_GCS_PATH = "datagen/_state/pos_transactions.json"
STATE_LOCAL_PATH = Path(__file__).parent / "_state_pos_transactions.json"

# --- Reference data ---
STORES = [f"STR{i:03d}" for i in range(1, 51)]
PAYMENT_METHODS = ["card", "cash", "contactless", "apple_pay", "google_pay", "gift_card"]
FIRST_NAMES = ["James", "Emma", "Oliver", "Sophie", "Harry", "Amelia", "Jack", "Isla", "George", "Mia"]
LAST_NAMES = ["Smith", "Jones", "Williams", "Taylor", "Brown", "Davies", "Wilson", "Evans", "Thomas", "Johnson"]


def rand_date(start_dt, end_dt):
    delta = int((end_dt - start_dt).total_seconds())
    return (start_dt + timedelta(seconds=random.randint(0, max(delta, 1)))).strftime("%Y-%m-%dT%H:%M:%S")


def rand_sku():
    cat = random.choice(["MEN", "WMN", "KID", "FTW", "ACC", "SPT", "OUT"])
    return f"{cat}-{random.randint(10000, 99999)}"


# --- State Management ---

def load_state(client, bucket_name, local=False):
    """Load last-used ID from state file."""
    if local:
        if STATE_LOCAL_PATH.exists():
            return json.loads(STATE_LOCAL_PATH.read_text())
        return {"last_id": 0, "runs": []}

    try:
        blob = client.bucket(bucket_name).blob(STATE_GCS_PATH)
        if blob.exists():
            return json.loads(blob.download_as_text())
    except Exception as e:
        print(f"  [state] Could not read GCS state: {e}, starting fresh")
    return {"last_id": 0, "runs": []}


def save_state(client, bucket_name, state, local=False):
    """Persist state after generation."""
    if local:
        STATE_LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_LOCAL_PATH.write_text(json.dumps(state, indent=2))
        print(f"  [state] Saved locally: {STATE_LOCAL_PATH}")
        return

    try:
        blob = client.bucket(bucket_name).blob(STATE_GCS_PATH)
        blob.upload_from_string(json.dumps(state, indent=2), content_type="application/json")
        print(f"  [state] Saved to gs://{bucket_name}/{STATE_GCS_PATH}")
    except Exception as e:
        print(f"  [state] GCS save failed: {e}, saving locally as fallback")
        STATE_LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_LOCAL_PATH.write_text(json.dumps(state, indent=2))


def upload_jsonl(client, bucket_name, path, records):
    bucket = client.bucket(bucket_name)
    content = "\n".join(json.dumps(r) for r in records)
    blob_path = f"{path}/part-00000.jsonl"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(content, content_type="application/json")
    print(f"  → gs://{bucket_name}/{blob_path} ({len(records):,} records)")


# --- Generators ---

def generate_v1(start_id, n=3000):
    """V1: Baseline schema — 12 fields. Simulates normal daily POS batch."""
    now = datetime.now()
    batch_start = now - timedelta(hours=random.randint(6, 24))
    batch_end = now

    records = []
    for i in range(n):
        store = random.choice(STORES)
        records.append({
            "transaction_id": f"POS{start_id + i}",
            "basket_id": f"BKT{random.randint(100000, 999999)}",
            "store_id": store,
            "till_id": f"{store}-T{random.randint(1, 8)}",
            "customer_id": f"CUST{random.randint(1, 5000):06d}" if random.random() < 0.6 else None,
            "product_sku": rand_sku(),
            "quantity": random.randint(1, 5),
            "unit_price": round(random.uniform(5.99, 199.99), 2),
            "discount_amount": round(random.uniform(0, 20.0), 2) if random.random() < 0.3 else 0.0,
            "payment_method": random.choice(PAYMENT_METHODS),
            "transaction_datetime": rand_date(batch_start, batch_end),
            "staff_id": f"EMP{random.randint(1, 200):04d}",
        })
    return records


def generate_v2(start_id, n=2000):
    """V2: Schema ADD — new column `loyalty_points_earned`.
    Simulates: source system deployed loyalty integration overnight."""
    now = datetime.now()
    batch_start = now - timedelta(hours=random.randint(2, 12))
    batch_end = now

    records = []
    for i in range(n):
        store = random.choice(STORES)
        records.append({
            "transaction_id": f"POS{start_id + i}",
            "basket_id": f"BKT{random.randint(100000, 999999)}",
            "store_id": store,
            "till_id": f"{store}-T{random.randint(1, 8)}",
            "customer_id": f"CUST{random.randint(1, 5000):06d}" if random.random() < 0.7 else None,
            "product_sku": rand_sku(),
            "quantity": random.randint(1, 5),
            "unit_price": round(random.uniform(5.99, 199.99), 2),
            "discount_amount": round(random.uniform(0, 20.0), 2) if random.random() < 0.3 else 0.0,
            "payment_method": random.choice(PAYMENT_METHODS),
            "transaction_datetime": rand_date(batch_start, batch_end),
            "staff_id": f"EMP{random.randint(1, 200):04d}",
            # --- NEW COLUMN (schema evolution: add_column) ---
            "loyalty_points_earned": random.randint(10, 500) if random.random() < 0.65 else 0,
        })
    return records


def generate_v3(start_id, n=1500):
    """V3: Schema DROP — `unit_price` removed.
    Simulates: source team refactored POS, moved pricing to a separate feed.
    Bronze will NULL-fill. Silver will BLOCK."""
    now = datetime.now()
    batch_start = now - timedelta(hours=random.randint(1, 6))
    batch_end = now

    records = []
    for i in range(n):
        store = random.choice(STORES)
        records.append({
            "transaction_id": f"POS{start_id + i}",
            "basket_id": f"BKT{random.randint(100000, 999999)}",
            "store_id": store,
            "till_id": f"{store}-T{random.randint(1, 8)}",
            "customer_id": f"CUST{random.randint(1, 5000):06d}" if random.random() < 0.7 else None,
            "product_sku": rand_sku(),
            "quantity": random.randint(1, 5),
            # unit_price REMOVED — this is the breaking change
            "discount_amount": round(random.uniform(0, 20.0), 2) if random.random() < 0.3 else 0.0,
            "payment_method": random.choice(PAYMENT_METHODS),
            "transaction_datetime": rand_date(batch_start, batch_end),
            "staff_id": f"EMP{random.randint(1, 200):04d}",
            "loyalty_points_earned": random.randint(10, 500) if random.random() < 0.65 else 0,
        })
    return records


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Schema Evolution Demo — Production-Realistic Generator")
    parser.add_argument("--project", default="bt-df-lkhouse")
    parser.add_argument("--bucket", default=BUCKET)
    parser.add_argument("--version", choices=["v1", "v2", "v3"], help="Generate a single version")
    parser.add_argument("--all", action="store_true", help="Generate all 3 versions")
    parser.add_argument("--local", action="store_true", help="Use local state file (no GCS)")
    parser.add_argument("--reset", action="store_true", help="Reset state to 0")
    parser.add_argument("--v1-count", type=int, default=3000, help="Records for v1 (default: 3000)")
    parser.add_argument("--v2-count", type=int, default=2000, help="Records for v2 (default: 2000)")
    parser.add_argument("--v3-count", type=int, default=1500, help="Records for v3 (default: 1500)")
    args = parser.parse_args()

    if args.local:
        client = None
    else:
        from google.cloud import storage
        client = storage.Client(project=args.project)

    print("=" * 60)
    print("  SCHEMA EVOLUTION — Production Data Generator")
    print("=" * 60)
    print(f"  Project: {args.project}")
    print(f"  Bucket:  gs://{args.bucket}/")
    print(f"  State:   {'local' if args.local else 'GCS'}")

    # Reset
    if args.reset:
        state = {"last_id": 0, "runs": []}
        save_state(client, args.bucket, state, local=args.local)
        print("\n  ✅ State reset to 0")
        return

    # Load state
    state = load_state(client, args.bucket, local=args.local)
    print(f"  Last ID: {state['last_id']}")
    print(f"  Prior runs: {len(state.get('runs', []))}")

    versions_to_generate = []
    if args.all:
        versions_to_generate = ["v1", "v2", "v3"]
    elif args.version:
        versions_to_generate = [args.version]
    else:
        print("\n  ERROR: Specify --version v1|v2|v3 or --all")
        return

    counts = {"v1": args.v1_count, "v2": args.v2_count, "v3": args.v3_count}

    for version in versions_to_generate:
        n = counts[version]
        start_id = state["last_id"] + 1

        print(f"\n{'─' * 60}")
        print(f"  Generating {version.upper()} — IDs: POS{start_id} to POS{start_id + n - 1}")
        print(f"{'─' * 60}")

        if version == "v1":
            records = generate_v1(start_id, n)
            desc = "Baseline (12 fields)"
        elif version == "v2":
            records = generate_v2(start_id, n)
            desc = "+loyalty_points_earned (add_column)"
        else:
            records = generate_v3(start_id, n)
            desc = "−unit_price (drop_column)"

        # Upload
        landing_path = f"landing/pos_transactions/{version}"
        if args.local:
            # Write locally for testing
            out_dir = Path(__file__).parent / "_output" / f"pos_transactions/{version}"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / "part-00000.jsonl"
            out_file.write_text("\n".join(json.dumps(r) for r in records))
            print(f"  → {out_file} ({len(records):,} records)")
        else:
            upload_jsonl(client, args.bucket, landing_path, records)

        # Update state
        state["last_id"] = start_id + n - 1
        state["runs"].append({
            "version": version,
            "start_id": start_id,
            "end_id": start_id + n - 1,
            "count": n,
            "description": desc,
            "generated_at": datetime.now().isoformat(),
        })

    # Save state
    save_state(client, args.bucket, state, local=args.local)

    # Summary
    print(f"\n{'=' * 60}")
    print("  GENERATION COMPLETE")
    print("=" * 60)
    print(f"\n  State: last_id = {state['last_id']}")
    print(f"\n  Generated this run:")
    for run in state["runs"][-len(versions_to_generate):]:
        print(f"    {run['version']}: POS{run['start_id']} → POS{run['end_id']} ({run['count']} records) [{run['description']}]")

    print(f"""
  DEMO STEPS:
  ───────────
  1. bronze_asset (table=pos_transactions, version=v1)
     → Baseline table created with 12 columns
     → Verify: SELECT COUNT(*) FROM eastside_bronze.pos_transactions

  2. silver_asset (table=pos_transactions)
     → SCD2 merge succeeds
     → Verify: SELECT COUNT(*) FROM eastside_silver.pos_transactions WHERE is_current=true

  3. bronze_asset (table=pos_transactions, version=v2)
     → SchemaEvolver auto-adds loyalty_points_earned ✅
     → Old rows have NULL for new column (Iceberg schema evolution)
     → Verify: SELECT loyalty_points_earned, COUNT(*) FROM eastside_bronze.pos_transactions GROUP BY 1

  4. silver_asset (table=pos_transactions)
     → New column accepted as nullable ✅

  5. bronze_asset (table=pos_transactions, version=v3)
     → unit_price NULL-filled (bronze accepts drops) ✅
     → Verify: SELECT unit_price, COUNT(*) FROM eastside_bronze.pos_transactions WHERE transaction_id LIKE 'POS{state["runs"][-1]["start_id"] if versions_to_generate[-1] == "v3" else "..."}%' GROUP BY 1

  6. silver_asset (table=pos_transactions)
     → ❌ FAILS: "Schema evolution BLOCKED: drop_column blocked. Missing: ['unit_price']"
     → This proves Silver governance works!
""")
    print("=" * 60)


if __name__ == "__main__":
    main()
