"""EastSide — Generate all 8 datasets and upload to GCS landing zone.
Run from Cloud Shell:
    pip install google-cloud-storage
    python eastside/datagen/generate.py --project=bt-df-lkhouse
"""
import argparse
import json
import random
from datetime import datetime, timedelta
from google.cloud import storage

random.seed(42)

BUCKET = "eastside-lakehouse"

# --- Shared reference data ---
STORES = [f"STR{i:03d}" for i in range(1, 51)]
WAREHOUSES = ["WH-NORTH", "WH-SOUTH", "WH-MIDLANDS", "WH-EAST"]
CATEGORIES = ["menswear", "womenswear", "kidswear", "footwear", "accessories", "sportswear", "outerwear"]
SUB_CATEGORIES = {
    "menswear": ["shirts", "trousers", "suits", "knitwear", "t-shirts"],
    "womenswear": ["dresses", "tops", "skirts", "trousers", "blouses"],
    "kidswear": ["tops", "bottoms", "dresses", "school_uniform", "sleepwear"],
    "footwear": ["trainers", "boots", "sandals", "formal", "slippers"],
    "accessories": ["bags", "belts", "scarves", "hats", "jewellery"],
    "sportswear": ["leggings", "shorts", "sports_bras", "hoodies", "jackets"],
    "outerwear": ["coats", "jackets", "puffers", "raincoats", "gilets"],
}
BRANDS = ["EastSide Essentials", "Urban Edge", "Heritage Line", "Active Pro", "Little Stars", "Sole Street", "Nordic Knit"]
COLOURS = ["black", "white", "navy", "grey", "red", "blue", "green", "beige", "pink", "brown"]
SIZES = ["XS", "S", "M", "L", "XL", "XXL"]
SEASONS = ["SS24", "AW24", "SS25", "AW25"]
PAYMENT_METHODS = ["card", "cash", "contactless", "apple_pay", "google_pay", "gift_card"]
SHIPPING_METHODS = ["standard", "express", "next_day", "click_collect"]
ORDER_STATUSES = ["confirmed", "processing", "shipped", "delivered", "cancelled", "returned"]
RETURN_REASONS = ["too_small", "too_large", "wrong_item", "defective", "not_as_described", "changed_mind", "arrived_late"]
LOYALTY_TIERS = ["bronze", "silver", "gold", "platinum"]
DEPARTMENTS = ["sales_floor", "stockroom", "management", "visual_merchandising", "customer_service"]
ROLES = ["sales_associate", "senior_associate", "supervisor", "store_manager", "assistant_manager", "stockroom_operative"]
FIRST_NAMES = ["James", "Emma", "Oliver", "Sophie", "Harry", "Amelia", "Jack", "Isla", "George", "Mia",
               "Charlie", "Ava", "Leo", "Grace", "Oscar", "Lily", "Arthur", "Freya", "Noah", "Emily",
               "Alfie", "Poppy", "Theo", "Ella", "Archie", "Rosie", "Joshua", "Chloe", "Thomas", "Daisy"]
LAST_NAMES = ["Smith", "Jones", "Williams", "Taylor", "Brown", "Davies", "Wilson", "Evans", "Thomas", "Johnson",
              "Roberts", "Walker", "Wright", "Robinson", "Thompson", "White", "Hughes", "Edwards", "Green", "Hall"]
POSTCODES = ["SW1A 1AA", "EC2R 8AH", "M1 1AE", "B1 1BB", "LS1 1UR", "BS1 5TR", "EH1 1YZ", "CF10 1EP",
             "NE1 7RU", "G1 1XQ", "NG1 5FW", "SO14 7DU", "OX1 1BX", "CB2 1TN", "BN1 1AE"]
SUPPLIERS = [
    {"id": "SUP001", "name": "FabricFirst Ltd"},
    {"id": "SUP002", "name": "StitchCraft International"},
    {"id": "SUP003", "name": "SoleMakers Co"},
    {"id": "SUP004", "name": "ThreadLine Asia"},
    {"id": "SUP005", "name": "NorthWeave Textiles"},
    {"id": "SUP006", "name": "PackRight Accessories"},
    {"id": "SUP007", "name": "GreenCotton Org"},
    {"id": "SUP008", "name": "UrbanSource Ltd"},
]


def rand_date(start="2024-01-01", end="2025-06-30"):
    s = datetime.fromisoformat(start)
    e = datetime.fromisoformat(end)
    return (s + timedelta(seconds=random.randint(0, int((e - s).total_seconds())))).strftime("%Y-%m-%dT%H:%M:%S")


def rand_date_only(start="2024-01-01", end="2025-06-30"):
    s = datetime.fromisoformat(start)
    e = datetime.fromisoformat(end)
    return (s + timedelta(days=random.randint(0, (e - s).days))).strftime("%Y-%m-%d")


def rand_sku():
    cat = random.choice(["MEN", "WMN", "KID", "FTW", "ACC", "SPT", "OUT"])
    return f"{cat}-{random.randint(10000, 99999)}"


def upload_jsonl(client, bucket_name, path, records, timestamp):
    bucket = client.bucket(bucket_name)
    content = "\n".join(json.dumps(r) for r in records)
    blob_path = f"{path}/part-{timestamp}.jsonl"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(content, content_type="application/json")
    print(f"    -> gs://{bucket_name}/{blob_path} ({len(records):,} records)")


def upload_csv(client, bucket_name, path, records, fields, timestamp):
    bucket = client.bucket(bucket_name)
    lines = [",".join(fields)]
    for r in records:
        lines.append(",".join(str(r.get(f, "")) for f in fields))
    content = "\n".join(lines)
    blob_path = f"{path}/part-{timestamp}.csv"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(content, content_type="text/csv")
    print(f"    -> gs://{bucket_name}/{blob_path} ({len(records):,} records)")


# ============================================================
# 1. POS Transactions (JSON, 5000 records)
# ============================================================
def generate_pos_transactions(n=5000):
    print(f"\n[1/8] POS Transactions ({n} records)")
    records = []
    for i in range(n):
        basket_id = f"BKT{random.randint(100000, 999999)}"
        store = random.choice(STORES)
        txn_time = rand_date()
        customer_id = f"CUST{random.randint(1, 2000):06d}" if random.random() < 0.6 else None
        records.append({
            "transaction_id": f"POS{1000000 + i}",
            "basket_id": basket_id,
            "store_id": store,
            "till_id": f"{store}-T{random.randint(1, 8)}",
            "customer_id": customer_id,
            "product_sku": rand_sku(),
            "quantity": random.randint(1, 5),
            "unit_price": round(random.uniform(5.99, 199.99), 2),
            "discount_amount": round(random.uniform(0, 20.0), 2) if random.random() < 0.3 else 0.0,
            "payment_method": random.choice(PAYMENT_METHODS),
            "transaction_datetime": txn_time,
            "staff_id": f"EMP{random.randint(1, 200):04d}",
        })
    return records


# ============================================================
# 2. Online Orders (JSON, 3000 records)
# ============================================================
def generate_online_orders(n=3000):
    print(f"\n[2/8] Online Orders ({n} records)")
    records = []
    for i in range(n):
        order_date = rand_date()
        records.append({
            "order_id": f"ORD{2000000 + i}",
            "customer_id": f"CUST{random.randint(1, 2000):06d}",
            "order_date": order_date,
            "status": random.choice(ORDER_STATUSES),
            "total_amount": round(random.uniform(15.0, 450.0), 2),
            "shipping_method": random.choice(SHIPPING_METHODS),
            "delivery_postcode": random.choice(POSTCODES),
            "promo_code": f"PROMO{random.randint(10, 50)}" if random.random() < 0.25 else None,
            "channel": random.choice(["web", "app"]),
            "items_count": random.randint(1, 6),
            "shipping_cost": round(random.choice([0.0, 3.99, 5.99, 7.99]), 2),
        })
    return records


# ============================================================
# 3. Inventory Movements (CSV, 4000 records)
# ============================================================
def generate_inventory_movements(n=4000):
    print(f"\n[3/8] Inventory Movements ({n} records)")
    records = []
    for i in range(n):
        movement_type = random.choice(["receipt", "transfer_in", "transfer_out", "adjustment", "sale"])
        qty = random.randint(1, 500)
        if movement_type in ("transfer_out", "sale", "adjustment"):
            qty = -qty if random.random() < 0.7 else qty
        records.append({
            "movement_id": f"MOV{3000000 + i}",
            "product_sku": rand_sku(),
            "warehouse_id": random.choice(WAREHOUSES) if movement_type != "sale" else None,
            "store_id": random.choice(STORES) if movement_type in ("sale", "transfer_in", "transfer_out") else None,
            "movement_type": movement_type,
            "quantity": qty,
            "movement_date": rand_date_only(),
            "reference_id": f"REF{random.randint(100000, 999999)}",
            "reason_code": random.choice(["planned", "emergency", "return_to_stock", "damaged", "cycle_count"]) if movement_type == "adjustment" else None,
        })
    return records


# ============================================================
# 4. Customer Profiles (JSON, 2000 records)
# ============================================================
def generate_customer_profiles(n=2000):
    print(f"\n[4/8] Customer Profiles ({n} records)")
    records = []
    for i in range(n):
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        signup = rand_date_only("2019-01-01", "2025-06-30")
        records.append({
            "customer_id": f"CUST{i + 1:06d}",
            "first_name": first,
            "last_name": last,
            "email": f"{first.lower()}.{last.lower()}{random.randint(1, 99)}@{'gmail.com' if random.random() < 0.5 else 'outlook.com'}",
            "phone": f"07{random.randint(100000000, 999999999)}",
            "date_of_birth": rand_date_only("1960-01-01", "2005-12-31"),
            "postcode": random.choice(POSTCODES),
            "loyalty_tier": random.choices(LOYALTY_TIERS, weights=[40, 30, 20, 10])[0],
            "signup_date": signup,
            "marketing_opt_in": random.choice([True, False]),
            "preferred_store_id": random.choice(STORES),
            "total_spend_lifetime": round(random.uniform(50.0, 15000.0), 2),
        })
    return records


# ============================================================
# 5. Product Catalogue — CDC (JSON, 1000 records)
#    Simulates full load + partial updates
# ============================================================
def generate_product_catalogue(n=1000):
    print(f"\n[5/8] Product Catalogue — CDC ({n} records)")
    records = []
    for i in range(n):
        cat = random.choice(CATEGORIES)
        sub = random.choice(SUB_CATEGORIES[cat])
        sku = rand_sku()
        rrp = round(random.uniform(9.99, 299.99), 2)

        # 80% full records, 20% partial (CDC updates — only changed fields + PK)
        if random.random() < 0.8:
            records.append({
                "_cdc_operation": "INSERT",
                "product_sku": sku,
                "product_name": f"{random.choice(BRANDS)} {sub.replace('_', ' ').title()}",
                "category": cat,
                "sub_category": sub,
                "brand": random.choice(BRANDS),
                "colour": random.choice(COLOURS),
                "size_range": ",".join(random.sample(SIZES, k=random.randint(3, 6))),
                "rrp": rrp,
                "cost_price": round(rrp * random.uniform(0.3, 0.55), 2),
                "supplier_id": random.choice(SUPPLIERS)["id"],
                "season": random.choice(SEASONS),
                "status": "active",
            })
        else:
            # Partial update — e.g. price change or status change
            update_type = random.choice(["price_change", "status_change", "colour_add"])
            partial = {"_cdc_operation": "UPDATE", "product_sku": sku}
            if update_type == "price_change":
                partial["rrp"] = round(rrp * random.uniform(0.7, 0.9), 2)
            elif update_type == "status_change":
                partial["status"] = random.choice(["discontinued", "clearance"])
            else:
                partial["colour"] = random.choice(COLOURS)
            records.append(partial)
    return records


# ============================================================
# 6. Supplier Purchase Orders — CDC (CSV, 1500 records)
#    Simulates full load + partial status updates
# ============================================================
def generate_supplier_purchase_orders(n=1500):
    print(f"\n[6/8] Supplier Purchase Orders — CDC ({n} records)")
    records = []
    for i in range(n):
        supplier = random.choice(SUPPLIERS)
        order_date = rand_date_only("2024-01-01", "2025-06-30")
        expected = rand_date_only(order_date, (datetime.fromisoformat(order_date) + timedelta(days=60)).strftime("%Y-%m-%d"))

        if random.random() < 0.75:
            # Full record
            records.append({
                "_cdc_operation": "INSERT",
                "po_number": f"PO{4000000 + i}",
                "supplier_id": supplier["id"],
                "supplier_name": supplier["name"],
                "product_sku": rand_sku(),
                "quantity_ordered": random.randint(100, 5000),
                "unit_cost": round(random.uniform(3.0, 80.0), 2),
                "order_date": order_date,
                "expected_delivery_date": expected,
                "status": "confirmed",
                "warehouse_id": random.choice(WAREHOUSES),
            })
        else:
            # Partial — status update only
            records.append({
                "_cdc_operation": "UPDATE",
                "po_number": f"PO{4000000 + random.randint(0, i)}",
                "status": random.choice(["shipped", "received", "cancelled"]),
            })
    return records


# ============================================================
# 7. Returns & Exchanges (JSON, 1200 records)
# ============================================================
def generate_returns_exchanges(n=1200):
    print(f"\n[7/8] Returns & Exchanges ({n} records)")
    records = []
    for i in range(n):
        return_date = rand_date_only()
        has_exchange = random.random() < 0.3
        records.append({
            "return_id": f"RET{5000000 + i}",
            "order_id": f"ORD{2000000 + random.randint(0, 2999)}",
            "customer_id": f"CUST{random.randint(1, 2000):06d}",
            "product_sku": rand_sku(),
            "return_reason": random.choice(RETURN_REASONS),
            "return_date": return_date,
            "refund_amount": round(random.uniform(10.0, 200.0), 2),
            "exchange_sku": rand_sku() if has_exchange else None,
            "channel": random.choice(["online", "store"]),
            "condition": random.choice(["new_with_tags", "new_without_tags", "worn", "damaged"]),
            "refund_method": random.choice(["original_payment", "store_credit", "gift_card"]),
        })
    return records


# ============================================================
# 8. Store Staff — CDC (CSV, 400 records)
# ============================================================
def generate_store_staff(n=400):
    print(f"\n[8/8] Store Staff — CDC ({n} records)")
    records = []
    for i in range(n):
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        start_date = rand_date_only("2018-01-01", "2025-03-31")

        if random.random() < 0.8:
            # Full record
            records.append({
                "_cdc_operation": "INSERT",
                "staff_id": f"EMP{i + 1:04d}",
                "first_name": first,
                "last_name": last,
                "email": f"{first.lower()}.{last.lower()}@eastside.co.uk",
                "store_id": random.choice(STORES),
                "role": random.choice(ROLES),
                "department": random.choice(DEPARTMENTS),
                "start_date": start_date,
                "hourly_rate": round(random.uniform(10.50, 28.00), 2),
                "status": "active",
            })
        else:
            # Partial — role/store change or termination
            update = random.choice(["transfer", "promotion", "termination"])
            partial = {"_cdc_operation": "UPDATE", "staff_id": f"EMP{random.randint(1, i + 1):04d}"}
            if update == "transfer":
                partial["store_id"] = random.choice(STORES)
            elif update == "promotion":
                partial["role"] = random.choice(ROLES)
                partial["hourly_rate"] = round(random.uniform(15.0, 32.0), 2)
            else:
                partial["status"] = "terminated"
            records.append(partial)
    return records


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="EastSide — Generate all datasets to GCS landing")
    parser.add_argument("--project", default="bt-df-lkhouse")
    parser.add_argument("--bucket", default=BUCKET)
    parser.add_argument("--version", default="v2", help="Landing version folder (e.g. v2, v3)")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    client = storage.Client(project=args.project)
    version = args.version

    print("=" * 60)
    print("  EastSide — Data Generation")
    print("=" * 60)
    print(f"  Project:   {args.project}")
    print(f"  Bucket:    gs://{args.bucket}/")
    print(f"  Version:   {version}")
    print(f"  Timestamp: {timestamp}")

    # JSON datasets
    data = generate_pos_transactions()
    upload_jsonl(client, args.bucket, f"landing/pos_transactions/{version}", data, timestamp)

    data = generate_online_orders()
    upload_jsonl(client, args.bucket, f"landing/online_orders/{version}", data, timestamp)

    data = generate_customer_profiles()
    upload_jsonl(client, args.bucket, f"landing/customer_profiles/{version}", data, timestamp)

    data = generate_product_catalogue()
    upload_jsonl(client, args.bucket, f"landing/product_catalogue/{version}", data, timestamp)

    data = generate_returns_exchanges()
    upload_jsonl(client, args.bucket, f"landing/returns_exchanges/{version}", data, timestamp)

    # CSV datasets
    inv = generate_inventory_movements()
    upload_csv(client, args.bucket, f"landing/inventory_movements/{version}", inv,
               ["movement_id", "product_sku", "warehouse_id", "store_id", "movement_type",
                "quantity", "movement_date", "reference_id", "reason_code"], timestamp)

    po = generate_supplier_purchase_orders()
    upload_csv(client, args.bucket, f"landing/supplier_purchase_orders/{version}", po,
               ["_cdc_operation", "po_number", "supplier_id", "supplier_name", "product_sku",
                "quantity_ordered", "unit_cost", "order_date", "expected_delivery_date",
                "status", "warehouse_id"], timestamp)

    staff = generate_store_staff()
    upload_csv(client, args.bucket, f"landing/store_staff/{version}", staff,
               ["_cdc_operation", "staff_id", "first_name", "last_name", "email",
                "store_id", "role", "department", "start_date", "hourly_rate", "status"], timestamp)

    print(f"\n{'=' * 60}")
    print("  ALL DATA GENERATED")
    print("=" * 60)
    print(f"\n  Landing zones populated (version={version}, ts={timestamp}):")
    print(f"    landing/pos_transactions/{version}/part-{timestamp}.jsonl          (5,000)  JSON")
    print(f"    landing/online_orders/{version}/part-{timestamp}.jsonl             (3,000)  JSON")
    print(f"    landing/inventory_movements/{version}/part-{timestamp}.csv         (4,000)  CSV")
    print(f"    landing/customer_profiles/{version}/part-{timestamp}.jsonl         (2,000)  JSON")
    print(f"    landing/product_catalogue/{version}/part-{timestamp}.jsonl         (1,000)  JSON  [CDC]")
    print(f"    landing/supplier_purchase_orders/{version}/part-{timestamp}.csv    (1,500)  CSV   [CDC]")
    print(f"    landing/returns_exchanges/{version}/part-{timestamp}.jsonl         (1,200)  JSON")
    print(f"    landing/store_staff/{version}/part-{timestamp}.csv                 (400)    CSV   [CDC]")
    print(f"\n  Total: 18,100 records across 8 datasets")
    print(f"\n  To process: spark-submit bronze.py --config gs://eastside-lakehouse/config/pipeline.yaml --all --version {version}")
    print("=" * 60)


if __name__ == "__main__":
    main()
