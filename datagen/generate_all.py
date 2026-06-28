"""Generate test data for ALL onboarding use cases.
Run: python datagen/generate_all.py --project=bt-df-lkhouse
"""
import argparse
import json
import random
from datetime import datetime, timedelta
from google.cloud import storage

random.seed(42)

# Shared data
FIRST_NAMES = ["Rahul", "Priya", "Amit", "Sneha", "Vikram", "Anita", "Rajesh", "Deepika",
               "Suresh", "Kavita", "Mohan", "Lakshmi", "Arun", "Meera", "Sanjay", "Pooja",
               "Kiran", "Neha", "Rohit", "Divya", "Arjun", "Swati", "Manoj", "Ritu"]
LAST_NAMES = ["Sharma", "Patel", "Kumar", "Singh", "Gupta", "Reddy", "Iyer", "Das",
              "Mehta", "Joshi", "Nair", "Verma", "Chauhan", "Yadav", "Mishra", "Bhat"]
DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com"]


def upload_jsonl(client, bucket_name, path, records):
    bucket = client.bucket(bucket_name)
    content = "\n".join(json.dumps(r) for r in records)
    blob_path = f"{path}/part-00000.jsonl"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(content, content_type="application/json")
    print(f"    -> gs://{bucket_name}/{blob_path} ({len(records):,} records)")


# ============================================================
# 1. CIBIL Bureau Feed
# ============================================================
def generate_cibil(n, num_customers):
    print(f"\n[1/5] CIBIL Bureau Feed ({n} records)")
    records = []
    for i in range(n):
        customer_id = random.randint(1, num_customers)
        score = max(300, min(900, int(random.gauss(700, 100))))
        enquiry_date = datetime(2024, 1, 1) + timedelta(days=random.randint(0, 540))
        records.append({
            "customer_id": customer_id,
            "pan_number": "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=5)) + "".join(random.choices("0123456789", k=4)) + random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
            "cibil_score": score,
            "score_date": (enquiry_date - timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d"),
            "enquiry_date": enquiry_date.strftime("%Y-%m-%d"),
            "loan_amount_requested": round(random.choice([random.uniform(50000, 500000), random.uniform(500000, 5000000)]), 2),
            "number_of_accounts": random.randint(1, 15),
            "overdue_amount": round(random.uniform(0, 50000), 2) if random.random() < 0.3 else 0.0,
            "credit_utilization_pct": round(random.uniform(5, 95), 1),
            "account_type": random.choice(["home_loan", "personal_loan", "credit_card", "auto_loan", "business_loan"]),
            "dpd_30_plus_count": random.choices([0, 1, 2, 3, 4, 5], weights=[60, 15, 10, 8, 5, 2])[0],
            "bureau_reference_id": f"BUR{random.randint(100000000, 999999999)}",
            "mobile_number": f"{random.choice(['9','8','7','6'])}{random.randint(100000000, 999999999)}",
            "email_address": f"{random.choice(FIRST_NAMES).lower()}.{random.choice(LAST_NAMES).lower()}{random.randint(1,99)}@{random.choice(DOMAINS)}",
            "date_of_birth": (datetime.now() - timedelta(days=random.randint(7300, 21900))).strftime("%Y-%m-%d"),
        })
    return records


# ============================================================
# 2. e-KYC Provider Feed
# ============================================================
def generate_ekyc(n, num_customers):
    print(f"\n[2/5] e-KYC Provider Feed ({n} records)")
    records = []
    for i in range(n):
        customer_id = random.randint(1, num_customers)
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        city = random.choice(["Mumbai", "Delhi", "Bangalore", "Chennai", "Ahmedabad", "Jaipur", "Kolkata", "Hyderabad"])
        verified_date = datetime(2024, 1, 1) + timedelta(days=random.randint(0, 540))
        records.append({
            "customer_id": customer_id,
            "aadhaar_number": "".join([str(random.randint(0, 9)) for _ in range(12)]),
            "kyc_status": random.choices(["verified", "pending", "rejected", "expired"], weights=[60, 20, 10, 10])[0],
            "kyc_verified_date": verified_date.strftime("%Y-%m-%d"),
            "verification_mode": random.choice(["video", "otp", "biometric", "offline"]),
            "full_name": f"{first} {last}",
            "address": f"{random.randint(1, 999)}, {random.choice(['MG Road', 'Station Road', 'Park Street', 'Ring Road'])}, {city} - {random.randint(100000, 999999)}",
            "photo_url": f"https://storage.bank.com/kyc-photos/{customer_id}/{random.randint(1000,9999)}.jpg",
            "consent_timestamp": (verified_date - timedelta(minutes=random.randint(5, 60))).strftime("%Y-%m-%dT%H:%M:%S"),
            "provider_reference_id": f"EKYC{random.randint(100000000, 999999999)}",
        })
    return records


# ============================================================
# 3. UPI Transactions
# ============================================================
def generate_upi(n, num_customers):
    print(f"\n[3/5] UPI Transactions ({n} records)")
    records = []
    for i in range(n):
        txn_date = datetime(2024, 1, 1) + timedelta(days=random.randint(0, 540), hours=random.randint(0, 23), minutes=random.randint(0, 59))
        customer_id = random.randint(1, num_customers)
        records.append({
            "transaction_id": f"UPI{random.randint(100000000000, 999999999999)}",
            "payer_vpa": f"user{customer_id}@{random.choice(['okaxis', 'oksbi', 'paytm', 'ybl', 'ibl'])}",
            "payee_vpa": f"merchant{random.randint(1,5000)}@{random.choice(['okaxis', 'oksbi', 'paytm', 'ybl'])}",
            "amount": round(random.choice([random.uniform(10, 500), random.uniform(500, 5000), random.uniform(5000, 50000)]), 2),
            "transaction_date": txn_date.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": random.choices(["success", "failed", "pending", "declined"], weights=[85, 8, 5, 2])[0],
            "remitter_account": f"ACC{customer_id:08d}",
            "beneficiary_account": f"ACC{random.randint(1, 100000):08d}",
            "mcc_code": random.choice(["5411", "5812", "4121", "5912", "5311", "5999", "6011", "7011"]),
            "device_id": f"DEV{random.randint(10000000, 99999999)}",
        })
    return records


# ============================================================
# 4. Loan Repayment Schedule
# ============================================================
def generate_loan_repayment(n, num_customers):
    print(f"\n[4/5] Loan Repayment Schedule ({n} records)")
    records = []
    loan_counter = 0
    for i in range(n):
        if i % 12 == 0:
            loan_counter += 1
            loan_start = datetime(2022, 1, 1) + timedelta(days=random.randint(0, 1000))
            emi_amt = round(random.uniform(5000, 80000), 2)
            principal_ratio = random.uniform(0.4, 0.7)

        emi_number = (i % 12) + 1
        due_date = loan_start + timedelta(days=30 * emi_number)
        is_paid = random.random() < 0.85
        dpd = 0 if is_paid else random.choices([0, 15, 30, 60, 90, 180], weights=[10, 20, 30, 20, 15, 5])[0]

        records.append({
            "loan_id": f"LN{loan_counter:08d}",
            "customer_id": random.randint(1, num_customers),
            "emi_number": emi_number,
            "due_date": due_date.strftime("%Y-%m-%d"),
            "emi_amount": emi_amt,
            "principal_component": round(emi_amt * principal_ratio, 2),
            "interest_component": round(emi_amt * (1 - principal_ratio), 2),
            "payment_status": "paid" if is_paid else random.choice(["overdue", "partial", "waived"]),
            "payment_date": (due_date + timedelta(days=dpd)).strftime("%Y-%m-%d") if is_paid or dpd > 0 else None,
            "dpd_days": dpd,
            "penalty_amount": round(emi_amt * 0.02 * (dpd / 30), 2) if dpd > 0 else 0.0,
        })
    return records


# ============================================================
# 5. Customer Complaints
# ============================================================
def generate_complaints(n, num_customers):
    print(f"\n[5/5] Customer Complaints ({n} records)")
    categories = ["account", "card", "loan", "digital", "branch_service", "fraud"]
    sub_categories = {
        "account": ["balance_mismatch", "statement_error", "closure_issue", "nominee_update"],
        "card": ["unauthorized_txn", "card_blocked", "reward_points", "annual_fee"],
        "loan": ["emi_error", "foreclosure", "interest_dispute", "document_issue"],
        "digital": ["app_crash", "login_failed", "payment_stuck", "otp_not_received"],
        "branch_service": ["long_wait", "rude_staff", "wrong_info", "form_rejected"],
        "fraud": ["phishing", "unauthorized_access", "sim_swap", "fake_call"],
    }
    records = []
    for i in range(n):
        category = random.choice(categories)
        complaint_date = datetime(2024, 1, 1) + timedelta(days=random.randint(0, 540))
        is_resolved = random.random() < 0.7
        records.append({
            "complaint_id": f"CMP{random.randint(10000000, 99999999)}",
            "customer_id": random.randint(1, num_customers),
            "complaint_date": complaint_date.strftime("%Y-%m-%d"),
            "channel": random.choice(["app", "email", "phone", "branch", "social_media"]),
            "category": category,
            "sub_category": random.choice(sub_categories[category]),
            "description": f"Customer reported issue with {category} - {random.choice(sub_categories[category])}",
            "priority": random.choices(["low", "medium", "high", "critical"], weights=[20, 40, 30, 10])[0],
            "assigned_to": f"agent_{random.randint(100, 999)}",
            "resolution_date": (complaint_date + timedelta(days=random.randint(1, 15))).strftime("%Y-%m-%d") if is_resolved else None,
            "status": random.choice(["resolved", "closed"]) if is_resolved else random.choice(["open", "in_progress", "escalated"]),
            "csat_score": random.randint(1, 5) if is_resolved else None,
        })
    return records


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Generate ALL test data for onboarding use cases")
    parser.add_argument("--project", default="bt-df-lkhouse")
    parser.add_argument("--customers", type=int, default=500)
    args = parser.parse_args()

    bucket_name = f"{args.project}-lakehouse"
    gcs_client = storage.Client(project=args.project)
    nc = args.customers

    print("=" * 60)
    print("  Generate ALL Use Case Data")
    print("=" * 60)
    print(f"  Project: {args.project}")
    print(f"  Bucket: gs://{bucket_name}/")
    print(f"  Customers: {nc}")

    # Generate and upload each dataset
    data = generate_cibil(1000, nc)
    upload_jsonl(gcs_client, bucket_name, "landing/cibil_bureau_feed/v1", data)

    data = generate_ekyc(800, nc)
    upload_jsonl(gcs_client, bucket_name, "landing/ekyc_provider_feed/v1", data)

    data = generate_upi(5000, nc)
    upload_jsonl(gcs_client, bucket_name, "landing/upi_transactions/v1", data)

    data = generate_loan_repayment(2400, nc)
    upload_jsonl(gcs_client, bucket_name, "landing/loan_repayment_schedule/v1", data)

    data = generate_complaints(600, nc)
    upload_jsonl(gcs_client, bucket_name, "landing/customer_complaints/v1", data)

    print(f"\n{'=' * 60}")
    print("  ALL DATA GENERATED")
    print("=" * 60)
    print(f"\n  Landing zones populated:")
    print(f"    landing/cibil_bureau_feed/v1/       (1,000 records)")
    print(f"    landing/ekyc_provider_feed/v1/      (800 records)")
    print(f"    landing/upi_transactions/v1/        (5,000 records)")
    print(f"    landing/loan_repayment_schedule/v1/ (2,400 records)")
    print(f"    landing/customer_complaints/v1/     (600 records)")
    print(f"\n  Total: 9,800 records across 5 datasets")
    print(f"\n  Next: Onboard each via SD → approve → pipeline runs automatically")
    print("=" * 60)


if __name__ == "__main__":
    main()
