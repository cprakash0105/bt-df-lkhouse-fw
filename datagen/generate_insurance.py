"""Generate Motor Insurance domain test data — all 4 feeds.
Run: python datagen/generate_insurance.py --project=bt-df-lkhouse
"""
import argparse
import json
import random
from datetime import datetime, timedelta
from google.cloud import storage

random.seed(77)

VEHICLE_MAKES = ["Maruti", "Hyundai", "Tata", "Mahindra", "Honda", "Toyota", "Kia", "MG", "Skoda", "Volkswagen"]
VEHICLE_MODELS = {
    "Maruti": ["Swift", "Baleno", "Brezza", "Ertiga", "Alto"],
    "Hyundai": ["Creta", "Venue", "i20", "Verna", "Tucson"],
    "Tata": ["Nexon", "Punch", "Harrier", "Safari", "Altroz"],
    "Mahindra": ["XUV700", "Thar", "Scorpio", "XUV300", "Bolero"],
    "Honda": ["City", "Amaze", "Elevate", "WRV"],
    "Toyota": ["Fortuner", "Innova", "Glanza", "Urban Cruiser"],
    "Kia": ["Seltos", "Sonet", "Carens", "EV6"],
    "MG": ["Hector", "Astor", "ZS EV", "Gloster"],
    "Skoda": ["Kushaq", "Slavia", "Superb", "Kodiaq"],
    "Volkswagen": ["Taigun", "Virtus", "Tiguan"],
}
FUEL_TYPES = ["petrol", "diesel", "electric", "hybrid", "cng"]
POLICY_TYPES = ["comprehensive", "third_party", "own_damage"]
CLAIM_TYPES = ["accident", "theft", "natural_disaster", "third_party_injury", "windshield", "engine_damage"]
CLAIM_STATUSES = ["filed", "under_investigation", "approved", "rejected", "settled", "closed"]
STATES = ["MH", "DL", "KA", "TN", "GJ", "RJ", "UP", "WB", "KL", "TS"]
PAYMENT_MODES = ["upi", "net_banking", "credit_card", "debit_card", "auto_debit"]


def generate_vehicle_reg():
    state = random.choice(STATES)
    return f"{state}{random.randint(1,99):02d}{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{random.randint(1000,9999)}"


def generate_motor_policies(n, num_customers):
    print(f"\n[1/4] Motor Policies ({n} records)")
    records = []
    for i in range(1, n + 1):
        make = random.choice(VEHICLE_MAKES)
        model = random.choice(VEHICLE_MODELS[make])
        start_date = datetime(2023, 1, 1) + timedelta(days=random.randint(0, 900))
        records.append({
            "policy_id": f"POL{i:08d}",
            "customer_id": random.randint(1, num_customers),
            "vehicle_registration": generate_vehicle_reg(),
            "vehicle_make": make,
            "vehicle_model": model,
            "vehicle_year": random.randint(2015, 2026),
            "fuel_type": random.choice(FUEL_TYPES),
            "policy_type": random.choice(POLICY_TYPES),
            "sum_insured": random.choice([300000, 500000, 700000, 1000000, 1500000, 2000000]),
            "premium_amount": round(random.uniform(3000, 45000), 2),
            "policy_start_date": start_date.strftime("%Y-%m-%d"),
            "policy_end_date": (start_date + timedelta(days=365)).strftime("%Y-%m-%d"),
            "ncb_percentage": random.choice([0, 20, 25, 35, 45, 50]),
            "is_active": random.choices([True, False], weights=[80, 20])[0],
            "nominee_name": f"Nominee_{random.randint(1000,9999)}",
            "agent_code": f"AGT{random.randint(100, 999)}",
        })
    return records


def generate_motor_claims(n, num_policies):
    print(f"\n[2/4] Motor Claims ({n} records)")
    records = []
    for i in range(1, n + 1):
        claim_date = datetime(2023, 6, 1) + timedelta(days=random.randint(0, 700))
        claim_type = random.choice(CLAIM_TYPES)
        claim_amount = round(random.uniform(5000, 500000), 2)
        status = random.choice(CLAIM_STATUSES)
        records.append({
            "claim_id": f"CLM{i:08d}",
            "policy_id": f"POL{random.randint(1, num_policies):08d}",
            "customer_id": random.randint(1, 500),
            "claim_date": claim_date.strftime("%Y-%m-%d"),
            "claim_type": claim_type,
            "claim_amount": claim_amount,
            "approved_amount": round(claim_amount * random.uniform(0.5, 1.0), 2) if status in ["approved", "settled", "closed"] else 0,
            "claim_status": status,
            "incident_date": (claim_date - timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d"),
            "incident_location": f"{random.choice(['NH', 'SH', 'City Road', 'Highway', 'Parking'])}-{random.randint(1,100)}",
            "police_report_filed": random.choices([True, False], weights=[60, 40])[0],
            "surveyor_name": f"Surveyor_{random.randint(100, 500)}",
            "settlement_date": (claim_date + timedelta(days=random.randint(15, 90))).strftime("%Y-%m-%d") if status in ["settled", "closed"] else None,
            "rejection_reason": random.choice(["policy_lapsed", "excluded_event", "fraud_suspected", "insufficient_docs"]) if status == "rejected" else None,
        })
    return records


def generate_vehicle_master(n):
    print(f"\n[3/4] Vehicle Master ({n} records)")
    records = []
    for i in range(1, n + 1):
        make = random.choice(VEHICLE_MAKES)
        model = random.choice(VEHICLE_MODELS[make])
        reg_date = datetime(2015, 1, 1) + timedelta(days=random.randint(0, 3650))
        records.append({
            "vehicle_registration": generate_vehicle_reg(),
            "chassis_number": f"CH{''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=17))}",
            "engine_number": f"EN{''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=12))}",
            "vehicle_make": make,
            "vehicle_model": model,
            "manufacturing_year": random.randint(2015, 2026),
            "fuel_type": random.choice(FUEL_TYPES),
            "body_type": random.choice(["sedan", "suv", "hatchback", "mpv", "coupe"]),
            "seating_capacity": random.choice([4, 5, 7, 8]),
            "registration_date": reg_date.strftime("%Y-%m-%d"),
            "registration_state": random.choice(STATES),
            "owner_name": f"Owner_{random.randint(1000, 9999)}",
            "hypothecation": random.choices(["none", "bank_loan", "nbfc_loan"], weights=[40, 40, 20])[0],
        })
    return records


def generate_premium_payments(n, num_policies):
    print(f"\n[4/4] Premium Payments ({n} records)")
    records = []
    for i in range(1, n + 1):
        payment_date = datetime(2023, 1, 1) + timedelta(days=random.randint(0, 900))
        records.append({
            "payment_id": f"PAY{i:08d}",
            "policy_id": f"POL{random.randint(1, num_policies):08d}",
            "customer_id": random.randint(1, 500),
            "payment_date": payment_date.strftime("%Y-%m-%d"),
            "amount": round(random.uniform(3000, 45000), 2),
            "payment_mode": random.choice(PAYMENT_MODES),
            "transaction_reference": f"TXN{random.randint(100000000, 999999999)}",
            "payment_status": random.choices(["success", "failed", "pending", "refunded"], weights=[85, 8, 5, 2])[0],
            "gst_amount": round(random.uniform(500, 8000), 2),
            "receipt_number": f"RCP{random.randint(10000000, 99999999)}",
            "payment_for": random.choice(["new_policy", "renewal", "endorsement"]),
        })
    return records


def upload_jsonl(client, bucket_name, path, records):
    bucket = client.bucket(bucket_name)
    content = "\n".join(json.dumps(r) for r in records)
    blob_path = f"{path}/part-00000.jsonl"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(content, content_type="application/json")
    print(f"    -> gs://{bucket_name}/{blob_path} ({len(records):,} records)")


def main():
    parser = argparse.ArgumentParser(description="Generate Motor Insurance test data")
    parser.add_argument("--project", default="bt-df-lkhouse")
    parser.add_argument("--customers", type=int, default=500)
    args = parser.parse_args()

    bucket_name = f"{args.project}-lakehouse"
    gcs_client = storage.Client(project=args.project)

    print("=" * 60)
    print("  Motor Insurance Domain — Data Generator")
    print("=" * 60)
    print(f"  Project: {args.project}")
    print(f"  Bucket: gs://{bucket_name}/")

    policies = generate_motor_policies(1000, args.customers)
    upload_jsonl(gcs_client, bucket_name, "landing/motor_policy/v1", policies)

    claims = generate_motor_claims(400, 1000)
    upload_jsonl(gcs_client, bucket_name, "landing/motor_claims/v1", claims)

    vehicles = generate_vehicle_master(800)
    upload_jsonl(gcs_client, bucket_name, "landing/vehicle_master/v1", vehicles)

    payments = generate_premium_payments(1200, 1000)
    upload_jsonl(gcs_client, bucket_name, "landing/premium_payments/v1", payments)

    print(f"\n{'=' * 60}")
    print("  ALL INSURANCE DATA GENERATED")
    print("=" * 60)
    print(f"\n  Landing zones populated:")
    print(f"    landing/motor_policy/v1/         (1,000 records)")
    print(f"    landing/motor_claims/v1/         (400 records)")
    print(f"    landing/vehicle_master/v1/       (800 records)")
    print(f"    landing/premium_payments/v1/     (1,200 records)")
    print(f"\n  Total: 3,400 records across 4 datasets")
    print(f"\n  Next: Onboard each via SD:")
    print(f"    1. motor_policy (track policy status changes - SCD Type 2)")
    print(f"    2. motor_claims (track claim lifecycle - SCD Type 2)")
    print(f"    3. vehicle_master (overwrite - SCD Type 1)")
    print(f"    4. premium_payments (append only)")
    print("=" * 60)


if __name__ == "__main__":
    main()
