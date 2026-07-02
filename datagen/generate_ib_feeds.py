"""Generate 5 Investment Banking feeds and upload to GCS landing zone."""
import json
import random
import os
from datetime import date, timedelta

BUCKET = os.environ.get("CONFIG_BUCKET", "bt-df-lkhouse-lakehouse")
NUM_RECORDS = 300

random.seed(42)

def rand_date(start="2023-01-01", end="2024-12-31"):
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    return str(s + timedelta(days=random.randint(0, (e - s).days)))

def rand_future_date(from_date, days_min=30, days_max=730):
    d = date.fromisoformat(from_date)
    return str(d + timedelta(days=random.randint(days_min, days_max)))

# --- 1. Trade Blotter ---
INSTRUMENT_TYPES = ["equity", "bond", "derivative", "etf", "fx_spot", "fx_forward"]
DESKS = ["equities", "fixed_income", "derivatives", "fx", "structured_products"]
CURRENCIES = ["GBP", "USD", "EUR", "JPY", "CHF"]
TRADE_STATUSES = ["executed", "pending", "cancelled", "settled", "failed"]

def gen_trade_blotter(n):
    records = []
    for i in range(n):
        trade_date = rand_date()
        records.append({
            "trade_id": f"TRD{100000 + i}",
            "trader_id": f"TDR{random.randint(1, 50):03d}",
            "desk_code": random.choice(DESKS),
            "instrument_type": random.choice(INSTRUMENT_TYPES),
            "isin": f"GB{random.randint(1000000000, 9999999999)}",
            "quantity": random.randint(100, 100000),
            "trade_price": round(random.uniform(1.0, 5000.0), 4),
            "trade_date": trade_date,
            "settlement_date": rand_future_date(trade_date, 1, 5),
            "counterparty_id": f"CP{random.randint(1, 100):03d}",
            "buy_sell_flag": random.choice(["B", "S"]),
            "currency": random.choice(CURRENCIES),
            "status": random.choice(TRADE_STATUSES),
        })
    return records

# --- 2. Portfolio Holdings ---
ASSET_CLASSES = ["equity", "fixed_income", "cash", "alternative", "real_estate", "commodity"]
SECTORS = ["financials", "technology", "healthcare", "energy", "consumer", "industrials", "utilities"]
COUNTRIES = ["GB", "US", "DE", "FR", "JP", "CH", "SG"]

def gen_portfolio_holdings(n):
    records = []
    for i in range(n):
        records.append({
            "portfolio_id": f"PF{random.randint(1, 50):03d}",
            "fund_manager_id": f"FM{random.randint(1, 20):03d}",
            "isin": f"GB{random.randint(1000000000, 9999999999)}",
            "asset_class": random.choice(ASSET_CLASSES),
            "position_quantity": random.randint(100, 500000),
            "market_value": round(random.uniform(10000.0, 50000000.0), 2),
            "cost_basis": round(random.uniform(9000.0, 48000000.0), 2),
            "valuation_date": rand_date(),
            "currency": random.choice(CURRENCIES),
            "country_of_risk": random.choice(COUNTRIES),
            "sector_code": random.choice(SECTORS),
        })
    return records

# --- 3. Client KYC (Institutional) ---
KYC_STATUSES = ["approved", "pending", "under_review", "expired", "rejected"]
RISK_RATINGS = ["low", "medium", "high", "very_high"]
ENTITY_TYPES = ["bank", "hedge_fund", "pension_fund", "insurance", "asset_manager", "corporate"]

def gen_client_kyc(n):
    records = []
    for i in range(n):
        onboarding_date = rand_date("2020-01-01", "2023-12-31")
        records.append({
            "client_id": f"CLI{100000 + i}",
            "legal_entity_name": f"Entity_{random.randint(1000, 9999)} {random.choice(ENTITY_TYPES).title()} Ltd",
            "lei_code": f"{''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=20))}",
            "incorporation_country": random.choice(COUNTRIES),
            "kyc_status": random.choice(KYC_STATUSES),
            "risk_rating": random.choice(RISK_RATINGS),
            "onboarding_date": onboarding_date,
            "review_due_date": rand_future_date(onboarding_date, 365, 730),
            "relationship_manager_id": f"RM{random.randint(1, 30):03d}",
            "aml_cleared_flag": random.choice([True, False]),
        })
    return records

# --- 4. Corporate Actions ---
ACTION_TYPES = ["dividend", "stock_split", "rights_issue", "merger", "spin_off", "buyback", "bonus_issue"]
ACTION_STATUSES = ["announced", "confirmed", "processed", "cancelled", "pending"]

def gen_corporate_actions(n):
    records = []
    for i in range(n):
        announcement_date = rand_date("2023-01-01", "2024-06-30")
        ex_date = rand_future_date(announcement_date, 7, 30)
        record_date = rand_future_date(ex_date, 1, 3)
        payment_date = rand_future_date(record_date, 5, 30)
        records.append({
            "action_id": f"CA{100000 + i}",
            "isin": f"GB{random.randint(1000000000, 9999999999)}",
            "action_type": random.choice(ACTION_TYPES),
            "announcement_date": announcement_date,
            "ex_date": ex_date,
            "record_date": record_date,
            "payment_date": payment_date,
            "ratio": round(random.uniform(0.01, 5.0), 4) if random.random() > 0.4 else None,
            "cash_amount": round(random.uniform(0.01, 50.0), 4) if random.random() > 0.4 else None,
            "currency": random.choice(CURRENCIES),
            "status": random.choice(ACTION_STATUSES),
        })
    return records

# --- 5. Deal Pipeline (M&A) ---
DEAL_TYPES = ["acquisition", "merger", "ipo", "secondary_offering", "divestiture", "lbo", "joint_venture"]
DEAL_STAGES = ["origination", "pitch", "mandate", "due_diligence", "negotiation", "signing", "closed", "terminated"]
SECTORS_MA = ["technology", "healthcare", "financials", "energy", "consumer", "telecom", "real_estate"]

def gen_deal_pipeline(n):
    records = []
    for i in range(n):
        origination_date = rand_date("2022-01-01", "2024-06-30")
        records.append({
            "deal_id": f"DEAL{10000 + i}",
            "deal_name": f"Project_{random.choice(['Alpha','Beta','Gamma','Delta','Sigma','Omega','Titan','Atlas'])}{random.randint(10,99)}",
            "client_id": f"CLI{random.randint(100000, 100299)}",
            "deal_type": random.choice(DEAL_TYPES),
            "target_company": f"Target_Corp_{random.randint(100, 999)}",
            "deal_value": round(random.uniform(1000000.0, 5000000000.0), 2),
            "currency": random.choice(CURRENCIES),
            "stage": random.choice(DEAL_STAGES),
            "origination_date": origination_date,
            "expected_close_date": rand_future_date(origination_date, 90, 730),
            "lead_banker_id": f"BNK{random.randint(1, 40):03d}",
            "sector": random.choice(SECTORS_MA),
            "confidentiality_flag": random.choice([True, False]),
        })
    return records


FEEDS = {
    "trade_blotter": gen_trade_blotter,
    "portfolio_holdings": gen_portfolio_holdings,
    "ib_client_kyc": gen_client_kyc,
    "corporate_actions": gen_corporate_actions,
    "deal_pipeline": gen_deal_pipeline,
}


def write_local(name, records):
    path = f"datagen/{name}.jsonl"
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"  Written {len(records)} records -> {path}")
    return path


def upload_to_gcs(local_path, name):
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(BUCKET)
        gcs_path = f"landing/{name}/v1/{name}.jsonl"
        blob = bucket.blob(gcs_path)
        blob.upload_from_filename(local_path)
        print(f"  Uploaded -> gs://{BUCKET}/{gcs_path}")
    except Exception as e:
        print(f"  GCS upload skipped (run locally or missing creds): {e}")


if __name__ == "__main__":
    import sys
    upload = "--upload" in sys.argv

    for name, gen_fn in FEEDS.items():
        print(f"\nGenerating {name}...")
        records = gen_fn(NUM_RECORDS)
        local_path = write_local(name, records)
        if upload:
            upload_to_gcs(local_path, name)

    print("\nDone. To upload to GCS run:")
    print("  python datagen/generate_ib_feeds.py --upload")
    print("\nOr manually:")
    for name in FEEDS:
        print("  gsutil cp datagen/{}.jsonl gs://{}/landing/{}/v1/{}.jsonl".format(name, BUCKET, name, name))
