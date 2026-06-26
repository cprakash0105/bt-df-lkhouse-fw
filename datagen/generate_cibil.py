"""Generate CIBIL Bureau Feed test data and upload to GCS.
Run in Cloud Shell: python datagen/generate_cibil.py --project=bt-df-lkhouse

This generates realistic CIBIL bureau data matching the schema
discovered and approved through Semantic Discovery.
"""
import argparse
import json
import random
from datetime import datetime, timedelta
from google.cloud import storage

random.seed(42)

# Realistic Indian data patterns
FIRST_NAMES = ["Rahul", "Priya", "Amit", "Sneha", "Vikram", "Anita", "Rajesh", "Deepika",
               "Suresh", "Kavita", "Mohan", "Lakshmi", "Arun", "Meera", "Sanjay", "Pooja"]
LAST_NAMES = ["Sharma", "Patel", "Kumar", "Singh", "Gupta", "Reddy", "Iyer", "Das",
              "Mehta", "Joshi", "Nair", "Verma", "Chauhan", "Yadav", "Mishra", "Bhat"]
DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com"]
STATUSES = ["approved", "pending", "rejected"]
ACCOUNT_TYPES = ["home_loan", "personal_loan", "credit_card", "auto_loan", "business_loan"]


def generate_pan():
    """Generate realistic PAN number: ABCDE1234F"""
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return (
        "".join(random.choices(letters, k=5))
        + "".join(random.choices("0123456789", k=4))
        + random.choice(letters)
    )


def generate_phone():
    """Generate Indian mobile number."""
    return f"{random.choice(['9', '8', '7', '6'])}{random.randint(100000000, 999999999)}"


def generate_email(first, last):
    return f"{first.lower()}.{last.lower()}{random.randint(1, 99)}@{random.choice(DOMAINS)}"


def generate_cibil_records(n: int, num_customers: int) -> list:
    """Generate n CIBIL bureau feed records."""
    print(f"  Generating {n:,} CIBIL bureau records...")
    records = []

    for i in range(1, n + 1):
        customer_id = random.randint(1, num_customers)
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        # CIBIL score distribution: most between 600-800
        score = int(random.gauss(700, 100))
        score = max(300, min(900, score))

        enquiry_date = datetime(2024, 1, 1) + timedelta(days=random.randint(0, 540))

        records.append({
            "customer_id": customer_id,
            "pan_number": generate_pan(),
            "cibil_score": score,
            "score_date": (enquiry_date - timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d"),
            "enquiry_date": enquiry_date.strftime("%Y-%m-%d"),
            "loan_amount_requested": round(random.choice([
                random.uniform(50000, 500000),      # personal loan
                random.uniform(500000, 5000000),    # home loan
                random.uniform(200000, 1500000),    # auto loan
            ]), 2),
            "number_of_accounts": random.randint(1, 15),
            "overdue_amount": round(random.uniform(0, 50000), 2) if random.random() < 0.3 else 0.0,
            "credit_utilization_pct": round(random.uniform(5, 95), 1),
            "account_type": random.choice(ACCOUNT_TYPES),
            "dpd_30_plus_count": random.choices([0, 1, 2, 3, 4, 5], weights=[60, 15, 10, 8, 5, 2])[0],
            "bureau_reference_id": f"BUR{random.randint(100000000, 999999999)}",
            "mobile_number": generate_phone(),
            "email_address": generate_email(first, last),
            "date_of_birth": (datetime.now() - timedelta(days=random.randint(7300, 21900))).strftime("%Y-%m-%d"),
        })

    return records


def upload_jsonl(client, bucket_name: str, path: str, records: list, batch_size: int = 10000):
    """Upload records as JSONL to GCS."""
    bucket = client.bucket(bucket_name)
    file_num = 0
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        content = "\n".join(json.dumps(r) for r in batch)
        blob_path = f"{path}/part-{file_num:05d}.jsonl"
        blob = bucket.blob(blob_path)
        blob.upload_from_string(content, content_type="application/json")
        file_num += 1
        print(f"    -> {blob_path} ({len(batch):,} records)")


def main():
    parser = argparse.ArgumentParser(description="Generate CIBIL Bureau Feed test data")
    parser.add_argument("--project", default="bt-df-lkhouse")
    parser.add_argument("--bucket", help="GCS bucket (default: {project}-lakehouse)")
    parser.add_argument("--records", type=int, default=1000, help="Number of records to generate")
    parser.add_argument("--customers", type=int, default=500, help="Number of unique customers")
    args = parser.parse_args()

    bucket_name = args.bucket or f"{args.project}-lakehouse"
    gcs_client = storage.Client(project=args.project)

    print(f"""
============================================================
  CIBIL Bureau Feed — Data Generator
============================================================
  Project:   {args.project}
  Bucket:    gs://{bucket_name}/
  Records:   {args.records:,}
  Customers: {args.customers:,}
  Target:    landing/cibil_bureau_feed/v1/
============================================================
""")

    records = generate_cibil_records(args.records, args.customers)

    print(f"\n  Uploading to GCS...")
    upload_jsonl(gcs_client, bucket_name, "landing/cibil_bureau_feed/v1", records)

    # Print sample
    print(f"\n  Sample record:")
    print(f"  {json.dumps(records[0], indent=2)}")

    print(f"""
============================================================
  Done! {args.records:,} records uploaded.
  Location: gs://{bucket_name}/landing/cibil_bureau_feed/v1/

  Next steps:
  1. Copy SD-generated config from GCS:
     gs://{bucket_name}/framework/config/tables/cibil_bureau_feed.yaml

  2. Run pipeline:
     python -m bt_df_lkhouse_fw.engine.ingest --table cibil_bureau_feed --version v1
     python -m bt_df_lkhouse_fw.engine.curate --table cibil_bureau_feed
     python -m bt_df_lkhouse_fw.engine.consume --all
============================================================
""")


if __name__ == "__main__":
    main()
