"""Generate e-KYC Provider Feed test data and upload to GCS.
Run in Cloud Shell: python datagen/generate_ekyc.py --project=bt-df-lkhouse
"""
import argparse
import json
import random
from datetime import datetime, timedelta
from google.cloud import storage

random.seed(99)

FIRST_NAMES = ["Rahul", "Priya", "Amit", "Sneha", "Vikram", "Anita", "Rajesh", "Deepika",
               "Suresh", "Kavita", "Mohan", "Lakshmi", "Arun", "Meera", "Sanjay", "Pooja"]
LAST_NAMES = ["Sharma", "Patel", "Kumar", "Singh", "Gupta", "Reddy", "Iyer", "Das",
              "Mehta", "Joshi", "Nair", "Verma", "Chauhan", "Yadav", "Mishra", "Bhat"]
KYC_STATUSES = ["verified", "pending", "rejected", "expired"]
VERIFICATION_MODES = ["video", "otp", "biometric", "offline"]
STATES = ["Maharashtra", "Delhi", "Karnataka", "Tamil Nadu", "Gujarat", "Rajasthan",
          "Uttar Pradesh", "West Bengal", "Kerala", "Telangana"]
CITIES = ["Mumbai", "Delhi", "Bangalore", "Chennai", "Ahmedabad", "Jaipur",
          "Lucknow", "Kolkata", "Kochi", "Hyderabad"]


def generate_aadhaar():
    return "".join([str(random.randint(0, 9)) for _ in range(12)])


def generate_records(n, num_customers):
    print(f"  Generating {n:,} e-KYC records...")
    records = []
    for i in range(1, n + 1):
        customer_id = random.randint(1, num_customers)
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        city = random.choice(CITIES)
        state = random.choice(STATES)
        verified_date = datetime(2024, 1, 1) + timedelta(days=random.randint(0, 540))

        records.append({
            "customer_id": customer_id,
            "aadhaar_number": generate_aadhaar(),
            "kyc_status": random.choices(KYC_STATUSES, weights=[60, 20, 10, 10])[0],
            "kyc_verified_date": verified_date.strftime("%Y-%m-%d"),
            "verification_mode": random.choice(VERIFICATION_MODES),
            "full_name": f"{first} {last}",
            "address": f"{random.randint(1, 999)}, {random.choice(['MG Road', 'Station Road', 'Park Street', 'Ring Road', 'Main Street'])}, {city}, {state} - {random.randint(100000, 999999)}",
            "photo_url": f"https://storage.bank.com/kyc-photos/{customer_id}/{random.randint(1000,9999)}.jpg",
            "consent_timestamp": (verified_date - timedelta(minutes=random.randint(5, 60))).strftime("%Y-%m-%dT%H:%M:%S"),
            "provider_reference_id": f"EKYC{random.randint(100000000, 999999999)}",
        })
    return records


def upload_jsonl(client, bucket_name, path, records):
    bucket = client.bucket(bucket_name)
    content = "\n".join(json.dumps(r) for r in records)
    blob_path = f"{path}/part-00000.jsonl"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(content, content_type="application/json")
    print(f"    -> {blob_path} ({len(records):,} records)")


def main():
    parser = argparse.ArgumentParser(description="Generate e-KYC Provider Feed test data")
    parser.add_argument("--project", default="bt-df-lkhouse")
    parser.add_argument("--records", type=int, default=800)
    parser.add_argument("--customers", type=int, default=500)
    args = parser.parse_args()

    bucket_name = f"{args.project}-lakehouse"
    gcs_client = storage.Client(project=args.project)

    print(f"\n  e-KYC Provider Feed — Data Generator")
    print(f"  Records: {args.records}, Customers: {args.customers}")
    print(f"  Target: gs://{bucket_name}/landing/ekyc_provider_feed/v1/\n")

    records = generate_records(args.records, args.customers)
    upload_jsonl(gcs_client, bucket_name, "landing/ekyc_provider_feed/v1", records)

    print(f"\n  Done! Now go to SD and onboard 'ekyc_provider_feed'")
    print(f"  The Cloud Function will trigger the pipeline automatically on approval.\n")


if __name__ == "__main__":
    main()
