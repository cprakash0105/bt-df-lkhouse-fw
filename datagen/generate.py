"""Standalone Data Generator for Schema Evolution POC.

Generates realistic e-commerce data (JSONL) and uploads directly to GCS.
Completely independent of the pipeline framework — no Spark required.

V1: Baseline schema
V2: Schema drift (new columns, type widen, enum expansion)

Usage:
    pip install -r requirements.txt
    python generate.py --project=bt-df-lkhouse --version=v1
    python generate.py --project=bt-df-lkhouse --version=v2
"""
import argparse
import json
import random
from datetime import datetime, timedelta
from faker import Faker
from google.cloud import storage

fake = Faker("en_GB")
Faker.seed(42)
random.seed(42)

# ============================================================
# CONFIG
# ============================================================

REGIONS = ["North", "South", "Midlands", "London", "Scotland", "Wales", "East", "West"]
LOYALTY_TIERS_V1 = ["Bronze", "Silver", "Gold", "Platinum"]
LOYALTY_TIERS_V2 = ["Bronze", "Silver", "Gold", "Platinum", "Diamond"]
CUSTOMER_SEGMENTS = ["Enterprise", "SMB", "Consumer", "Government", "Education"]
PRODUCT_CATEGORIES = ["Electronics", "Clothing", "Home", "Sports", "Books", "Food", "Health", "Toys", "Auto", "Garden"]
PAYMENT_METHODS_V1 = ["Credit Card", "Debit Card", "PayPal", "Bank Transfer", "Apple Pay", "Google Pay"]
PAYMENT_METHODS_V2 = ["Credit Card", "Debit Card", "PayPal", "Bank Transfer", "Apple Pay", "Google Pay", "Crypto"]
PAYMENT_CHANNELS = ["online", "in-store", "phone", "partner-api"]
ORDER_STATUSES = ["delivered", "shipped", "processing", "cancelled", "returned"]

# Scale config
SCALE = {
    "v1": {"customers": 10_000, "products": 1_000, "orders": 10_000, "payments": 10_000},
    "v2": {"customers": 2_000, "products": 0, "orders": 5_000, "payments": 5_000},
}


# ============================================================
# GENERATORS
# ============================================================

def gen_customers_v1(n: int) -> list:
    print(f"  Generating {n:,} V1 customers...")
    return [
        {
            "customer_id": i,
            "name": fake.name(),
            "email": fake.email(),
            "phone": fake.phone_number(),
            "address": fake.address().replace("\n", ", "),
            "city": fake.city(),
            "postcode": fake.postcode(),
            "region": random.choice(REGIONS),
            "loyalty_tier": random.choice(LOYALTY_TIERS_V1),
            "signup_date": fake.date_between(start_date="-5y", end_date="today").isoformat(),
            "is_active": random.choices([True, False], weights=[90, 10])[0],
        }
        for i in range(1, n + 1)
    ]


def gen_customers_v2(n: int, offset: int = 100_001) -> list:
    print(f"  Generating {n:,} V2 customers (+ customer_segment, + Diamond tier)...")
    return [
        {
            "customer_id": offset + i,
            "name": fake.name(),
            "email": fake.email(),
            "phone": fake.phone_number(),
            "address": fake.address().replace("\n", ", "),
            "city": fake.city(),
            "postcode": fake.postcode(),
            "region": random.choice(REGIONS),
            "loyalty_tier": random.choice(LOYALTY_TIERS_V2),
            "customer_segment": random.choice(CUSTOMER_SEGMENTS),  # NEW COLUMN
            "signup_date": fake.date_between(start_date="-1y", end_date="today").isoformat(),
            "is_active": random.choices([True, False], weights=[95, 5])[0],
        }
        for i in range(n)
    ]


def gen_products_v1(n: int) -> list:
    print(f"  Generating {n:,} V1 products...")
    return [
        {
            "product_id": i,
            "product_name": f"{fake.word().capitalize()} {fake.word().capitalize()} {random.choice(PRODUCT_CATEGORIES)}",
            "category": random.choice(PRODUCT_CATEGORIES),
            "price": round(random.uniform(1.99, 999.99), 2),
            "cost_price": round(random.uniform(0.50, 500.00), 2),
            "supplier": fake.company(),
            "sku": fake.bothify(text="???-#####").upper(),
            "weight_kg": round(random.uniform(0.1, 50.0), 2),
            "is_active": random.choices([True, False], weights=[85, 15])[0],
            "created_date": fake.date_between(start_date="-3y", end_date="-6m").isoformat(),
        }
        for i in range(1, n + 1)
    ]


def gen_orders_v1(n: int, num_customers: int) -> list:
    print(f"  Generating {n:,} V1 orders...")
    start_date = datetime(2023, 1, 1)
    orders = []
    for i in range(1, n + 1):
        order_date = start_date + timedelta(days=random.randint(0, 900))
        num_items = random.randint(1, 5)
        item_total = round(random.uniform(5.0, 500.0) * num_items, 2)
        orders.append({
            "order_id": i,
            "customer_id": random.randint(1, num_customers),
            "order_date": order_date.strftime("%Y-%m-%d"),
            "status": random.choice(ORDER_STATUSES),
            "num_items": num_items,
            "subtotal": item_total,
            "tax": round(item_total * 0.20, 2),
            "total_amount": round(item_total * 1.20, 2),
            "shipping_cost": round(random.uniform(0, 15.99), 2),
            "discount_amount": round(random.uniform(0, item_total * 0.2), 2) if random.random() > 0.7 else 0.0,
            "channel": random.choice(["web", "mobile", "store", "phone"]),
            "region": random.choice(REGIONS),
        })
        if i % 200000 == 0:
            print(f"    {i:,} orders...")
    return orders


def gen_orders_v2(n: int, offset: int = 1_000_001) -> list:
    print(f"  Generating {n:,} V2 orders (large amounts + marketplace channel)...")
    start_date = datetime(2025, 6, 1)
    orders = []
    for i in range(n):
        order_date = start_date + timedelta(days=random.randint(0, 180))
        num_items = random.randint(1, 10)
        # 5% have amounts exceeding INT max → forces type widening
        if random.random() < 0.05:
            item_total = round(random.uniform(2_500_000_000, 5_000_000_000), 2)
        else:
            item_total = round(random.uniform(10.0, 2000.0) * num_items, 2)
        orders.append({
            "order_id": offset + i,
            "customer_id": random.randint(1, 120_000),
            "order_date": order_date.strftime("%Y-%m-%d"),
            "status": random.choice(ORDER_STATUSES),
            "num_items": num_items,
            "subtotal": item_total,
            "tax": round(item_total * 0.20, 2),
            "total_amount": round(item_total * 1.20, 2),
            "shipping_cost": round(random.uniform(0, 25.99), 2),
            "discount_amount": round(random.uniform(0, item_total * 0.15), 2) if random.random() > 0.6 else 0.0,
            "channel": random.choice(["web", "mobile", "store", "phone", "marketplace"]),  # NEW VALUE
            "region": random.choice(REGIONS),
        })
        if (i + 1) % 50000 == 0:
            print(f"    {i + 1:,} orders...")
    return orders


def gen_payments_v1(n: int, num_orders: int) -> list:
    print(f"  Generating {n:,} V1 payments...")
    payments = []
    for i in range(1, n + 1):
        payment_date = datetime(2023, 1, 1) + timedelta(days=random.randint(0, 900))
        payments.append({
            "payment_id": i,
            "order_id": random.randint(1, num_orders),
            "payment_date": payment_date.strftime("%Y-%m-%d"),
            "amount": round(random.uniform(1.0, 600.0), 2),
            "payment_method": random.choice(PAYMENT_METHODS_V1),
            "status": random.choices(["completed", "pending", "failed", "refunded"], weights=[80, 10, 5, 5])[0],
            "currency": "GBP",
            "transaction_ref": fake.uuid4()[:12],
        })
        if i % 2000000 == 0:
            print(f"    {i:,} payments...")
    return payments


def gen_payments_v2(n: int, offset: int = 10_000_001) -> list:
    print(f"  Generating {n:,} V2 payments (+ payment_channel, + Crypto, multi-ccy)...")
    payments = []
    for i in range(n):
        payment_date = datetime(2025, 6, 1) + timedelta(days=random.randint(0, 180))
        payments.append({
            "payment_id": offset + i,
            "order_id": random.randint(1, 1_200_000),
            "payment_date": payment_date.strftime("%Y-%m-%d"),
            "amount": round(random.uniform(1.0, 3000.0), 2),
            "payment_method": random.choice(PAYMENT_METHODS_V2),  # + Crypto
            "status": random.choices(["completed", "pending", "failed", "refunded"], weights=[75, 12, 8, 5])[0],
            "currency": random.choice(["GBP", "EUR", "USD"]),  # Multi-currency
            "transaction_ref": fake.uuid4()[:12],
            "payment_channel": random.choice(PAYMENT_CHANNELS),  # NEW COLUMN
        })
        if (i + 1) % 500000 == 0:
            print(f"    {i + 1:,} payments...")
    return payments


# ============================================================
# GCS UPLOAD
# ============================================================

def upload_jsonl(client, bucket_name: str, path: str, records: list, batch_size: int = 50000):
    """Upload records as JSONL to GCS in batches."""
    bucket = client.bucket(bucket_name)
    file_num = 0
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        content = "\n".join(json.dumps(r) for r in batch)
        blob_path = f"{path}/part-{file_num:05d}.jsonl"
        blob = bucket.blob(blob_path)
        blob.upload_from_string(content, content_type="application/json")
        file_num += 1
        print(f"    ↑ {blob_path} ({len(batch):,} records)")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Schema Evolution POC — Data Generator")
    parser.add_argument("--project", required=True, help="GCP project ID")
    parser.add_argument("--version", default="v1", choices=["v1", "v2"], help="Data version")
    parser.add_argument("--bucket", help="GCS bucket (default: {project}-lakehouse)")
    parser.add_argument("--scale", type=float, default=1.0, help="Scale factor (0.01 = 1%% for testing)")
    args = parser.parse_args()

    bucket_name = args.bucket or f"{args.project}-lakehouse"
    client = storage.Client(project=args.project)
    scale = args.scale

    print(f"""
╔════════════════════════════════════════════════════════════╗
║  Schema Evolution POC — Data Generator                    ║
║  Version: {args.version}  |  Scale: {scale}x                            ║
║  Bucket: gs://{bucket_name}/                       ║
╚════════════════════════════════════════════════════════════╝
""")

    counts = {k: max(1, int(v * scale)) for k, v in SCALE[args.version].items()}

    if args.version == "v1":
        print("Schema: baseline (V1)")
        print(f"  customers: {counts['customers']:,}")
        print(f"  products:  {counts['products']:,}")
        print(f"  orders:    {counts['orders']:,}")
        print(f"  payments:  {counts['payments']:,}")
        print()

        customers = gen_customers_v1(counts["customers"])
        products = gen_products_v1(counts["products"])
        orders = gen_orders_v1(counts["orders"], counts["customers"])
        payments = gen_payments_v1(counts["payments"], counts["orders"])

        print("\n  Uploading to GCS...")
        upload_jsonl(client, bucket_name, "landing/customers/v1", customers)
        upload_jsonl(client, bucket_name, "landing/products/v1", products)
        upload_jsonl(client, bucket_name, "landing/orders/v1", orders)
        upload_jsonl(client, bucket_name, "landing/payments/v1", payments, batch_size=100000)

    elif args.version == "v2":
        print("Schema drift (V2):")
        print("  • customers: + customer_segment (new column), + Diamond tier")
        print("  • orders:    order_amount > INT_MAX (type widen), + marketplace channel")
        print("  • payments:  + payment_channel (new column), + Crypto, multi-currency")
        print()
        print(f"  customers: {counts['customers']:,}")
        print(f"  orders:    {counts['orders']:,}")
        print(f"  payments:  {counts['payments']:,}")
        print()

        customers = gen_customers_v2(counts["customers"])
        orders = gen_orders_v2(counts["orders"])
        payments = gen_payments_v2(counts["payments"])

        print("\n  Uploading to GCS...")
        upload_jsonl(client, bucket_name, "landing/customers/v2", customers)
        upload_jsonl(client, bucket_name, "landing/orders/v2", orders)
        upload_jsonl(client, bucket_name, "landing/payments/v2", payments, batch_size=100000)

    print(f"""
╔════════════════════════════════════════════════════════════╗
║  ✅ Done                                                   ║
║  Data uploaded to: gs://{bucket_name}/landing/    ║
║                                                            ║
║  Next: bash scripts/run_pipeline.sh {args.project} europe-west2 all {args.version}  ║
╚════════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()
