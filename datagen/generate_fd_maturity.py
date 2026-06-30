"""Generate Fixed Deposit Maturity Feed — 500 records."""
import json
import random
from datetime import date, timedelta

random.seed(42)

STATUSES = ["active", "matured", "premature_closed", "renewed"]
BRANCHES = ["BR001", "BR002", "BR003", "BR004", "BR005", "BR010", "BR015", "BR020"]
RATES = [5.5, 6.0, 6.25, 6.5, 6.75, 7.0, 7.25, 7.5]
TENURES = [3, 6, 12, 18, 24, 36, 60]

records = []
for i in range(500):
    cust_id = random.randint(1, 500)
    principal = round(random.choice([10000, 25000, 50000, 100000, 200000, 500000, 1000000]), 2)
    rate = random.choice(RATES)
    tenure = random.choice(TENURES)
    opening = date(2023, 1, 1) + timedelta(days=random.randint(0, 600))
    maturity = opening + timedelta(days=tenure * 30)
    maturity_amt = round(principal * (1 + rate / 100 * tenure / 12), 2)
    status = random.choices(STATUSES, weights=[50, 25, 10, 15])[0]

    record = {
        "fd_account_id": f"FD{100000 + i}",
        "customer_id": str(cust_id),
        "principal_amount": principal,
        "interest_rate": rate,
        "tenure_months": tenure,
        "opening_date": opening.isoformat(),
        "maturity_date": maturity.isoformat(),
        "maturity_amount": maturity_amt,
        "nomination_flag": random.choice([True, False]),
        "auto_renewal": random.choice([True, False]),
        "branch_code": random.choice(BRANCHES),
        "fd_status": status,
    }
    records.append(record)

# Write JSONL
output_path = "datagen/fd_maturity_feed.jsonl"
with open(output_path, "w") as f:
    for r in records:
        f.write(json.dumps(r) + "\n")

print(f"Generated {len(records)} FD records -> {output_path}")
print(f"Sample: {json.dumps(records[0], indent=2)}")
