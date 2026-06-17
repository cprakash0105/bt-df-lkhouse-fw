"""Event Producer — publishes clickstream and transaction events to Confluent Kafka.

Generates realistic e-commerce events and streams them to Kafka.
Run locally — completely independent of GCP.

Usage:
    pip install confluent-kafka faker pyyaml
    python stream_producer.py --config ../confluent/kafka.yaml --topic clickstream --rate 10 --duration 60
    python stream_producer.py --config ../confluent/kafka.yaml --topic transactions --rate 5 --duration 60
"""
import argparse
import json
import random
import time
import yaml
from datetime import datetime
from faker import Faker
from confluent_kafka import Producer

fake = Faker("en_GB")
random.seed(42)

# --- Clickstream config ---
EVENT_TYPES = ["page_view", "product_view", "add_to_cart", "remove_from_cart", "search", "checkout_start", "purchase"]
PAGES = ["/home", "/products", "/category/electronics", "/category/clothing", "/cart", "/checkout", "/account", "/deals"]
DEVICES = ["desktop", "mobile", "tablet"]
BROWSERS = ["Chrome", "Safari", "Firefox", "Edge"]
REFERRERS = ["google", "direct", "facebook", "instagram", "email", "affiliate", None]

# --- Transactions config ---
TXN_TYPES = ["payment", "refund", "chargeback", "pre_auth", "capture"]
TXN_STATUSES = ["success", "failed", "pending", "reversed"]
PAYMENT_METHODS = ["Credit Card", "Debit Card", "PayPal", "Bank Transfer", "Apple Pay", "Google Pay"]
CURRENCIES = ["GBP", "EUR", "USD"]


def load_kafka_config(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def create_producer(config: dict) -> Producer:
    return Producer({
        "bootstrap.servers": config["bootstrap_servers"],
        "security.protocol": config["security_protocol"],
        "sasl.mechanism": config["sasl_mechanism"],
        "sasl.username": config["sasl_username"],
        "sasl.password": config["sasl_password"],
    })


# ============================================================
# CLICKSTREAM GENERATORS
# ============================================================

def gen_clickstream_v1(seq: int) -> dict:
    return {
        "event_id": f"EVT-{seq:010d}",
        "customer_id": random.randint(1, 10_000),
        "event_type": random.choices(EVENT_TYPES, weights=[30, 25, 15, 5, 10, 8, 7])[0],
        "page_url": random.choice(PAGES),
        "product_id": random.randint(1, 1000) if random.random() > 0.3 else None,
        "event_timestamp": datetime.utcnow().isoformat() + "Z",
        "session_id": f"SES-{random.randint(1, 50000):08d}",
    }


def gen_clickstream_v2(seq: int) -> dict:
    event = gen_clickstream_v1(seq)
    event["device_type"] = random.choice(DEVICES)
    event["browser"] = random.choice(BROWSERS)
    event["referrer"] = random.choice(REFERRERS)
    return event


# ============================================================
# TRANSACTION GENERATORS
# ============================================================

def gen_transaction_v1(seq: int) -> dict:
    return {
        "transaction_id": f"TXN-{seq:010d}",
        "order_id": random.randint(1, 10_000),
        "customer_id": random.randint(1, 10_000),
        "amount": round(random.uniform(1.0, 500.0), 2),
        "currency": "GBP",
        "transaction_type": random.choices(TXN_TYPES, weights=[60, 15, 5, 10, 10])[0],
        "status": random.choices(TXN_STATUSES, weights=[75, 10, 10, 5])[0],
        "payment_method": random.choice(PAYMENT_METHODS),
        "event_timestamp": datetime.utcnow().isoformat() + "Z",
    }


def gen_transaction_v2(seq: int) -> dict:
    txn = gen_transaction_v1(seq)
    txn["currency"] = random.choice(CURRENCIES)  # multi-currency
    txn["risk_score"] = round(random.uniform(0.0, 1.0), 4)  # NEW COLUMN
    txn["gateway"] = random.choice(["stripe", "adyen", "worldpay", "checkout.com"])  # NEW COLUMN
    return txn


# ============================================================
# MAIN
# ============================================================

GENERATORS = {
    "clickstream": {"v1": gen_clickstream_v1, "v2": gen_clickstream_v2},
    "transactions": {"v1": gen_transaction_v1, "v2": gen_transaction_v2},
}


def delivery_report(err, msg):
    if err:
        print(f"  ❌ Delivery failed: {err}")


def main():
    parser = argparse.ArgumentParser(description="Event Producer (Clickstream / Transactions)")
    parser.add_argument("--config", required=True, help="Path to kafka.yaml")
    parser.add_argument("--topic", required=True, choices=["clickstream", "transactions"], help="Which topic to produce to")
    parser.add_argument("--rate", type=int, default=10, help="Events per second")
    parser.add_argument("--duration", type=int, default=60, help="Seconds to run (0=infinite)")
    parser.add_argument("--version", default="v1", choices=["v1", "v2"], help="Schema version")
    parser.add_argument("--total", type=int, default=0, help="Total events (overrides duration)")
    args = parser.parse_args()

    config = load_kafka_config(args.config)
    producer = create_producer(config)
    kafka_topic = config["topics"][args.topic]
    gen_func = GENERATORS[args.topic][args.version]

    print(f"""
╔════════════════════════════════════════════════════════════╗
║  Event Producer                                            ║
║  Topic: {kafka_topic:<49}║
║  Type:  {args.topic:<49}║
║  Rate:  {args.rate} events/sec  |  Schema: {args.version}                    ║
╚════════════════════════════════════════════════════════════╝
""")

    if args.version == "v2":
        if args.topic == "clickstream":
            print("  Schema drift: + device_type, browser, referrer\n")
        else:
            print("  Schema drift: + risk_score, gateway, multi-currency\n")

    seq = 0
    start_time = time.time()
    interval = 1.0 / args.rate

    try:
        while True:
            seq += 1
            event = gen_func(seq)
            producer.produce(
                kafka_topic,
                key=event.get("event_id") or event.get("transaction_id"),
                value=json.dumps(event),
                callback=delivery_report,
            )

            if seq % args.rate == 0:
                producer.flush()
                elapsed = time.time() - start_time
                print(f"  ⚡ {seq:,} events sent ({elapsed:.0f}s elapsed)")

            if args.total > 0 and seq >= args.total:
                break
            if args.duration > 0 and (time.time() - start_time) >= args.duration:
                break

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n  Interrupted.")

    producer.flush()
    elapsed = time.time() - start_time
    print(f"\n  ✅ Done: {seq:,} events in {elapsed:.1f}s ({seq/elapsed:.0f} events/sec)")


if __name__ == "__main__":
    main()
