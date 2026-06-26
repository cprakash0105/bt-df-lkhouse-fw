"""Create Business Glossary in Dataplex Knowledge Catalog.
The glossary is a flat dictionary of Business Data Element definitions.
No hierarchy here — just reusable definitions like a dictionary.

Run: python discovery/scripts/setup_glossary.py
"""
from google.cloud import dataplex_v1
from google.cloud.dataplex_v1 import BusinessGlossaryServiceClient

PROJECT_ID = "bt-df-lkhouse"
LOCATION = "europe-west2"
GLOSSARY_ID = "enterprise-data-glossary"

client = BusinessGlossaryServiceClient()
glossary_parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"
glossary_name = f"{glossary_parent}/glossaries/{GLOSSARY_ID}"

# Business Data Element definitions (the dictionary)
TERMS = [
    # --- Customer ---
    {
        "id": "customer_identifier",
        "name": "Customer Identifier",
        "definition": "Unique identifier assigned to a customer by the bank",
        "data_type": "string",
        "classification": "Internal",
        "dq_rules": "not_null, unique",
        "synonyms": "customer_id, cust_id, cust_no, client_id, subscriber_id",
    },
    {
        "id": "customer_name",
        "name": "Customer Name",
        "definition": "Full legal name of the customer as per KYC records",
        "data_type": "string",
        "classification": "PII",
        "dq_rules": "not_null",
        "synonyms": "name, cust_name, full_name, customer_nm, client_name",
    },
    {
        "id": "customer_email",
        "name": "Customer Email",
        "definition": "Primary email address of the customer",
        "data_type": "string",
        "classification": "PII",
        "dq_rules": "format: email",
        "synonyms": "email, email_addr, email_address, e_mail",
    },
    {
        "id": "customer_phone",
        "name": "Customer Phone",
        "definition": "Primary phone/mobile number of the customer",
        "data_type": "string",
        "classification": "PII",
        "dq_rules": "format: phone",
        "synonyms": "phone, mobile, tel, phone_number, mobile_no, phn_nbr, contact_number",
    },
    {
        "id": "date_of_birth",
        "name": "Date of Birth",
        "definition": "Customer's date of birth as per identity documents",
        "data_type": "date",
        "classification": "PII",
        "dq_rules": "not_null: false",
        "synonyms": "dob, birth_date, birthdate",
    },
    {
        "id": "pan_number",
        "name": "PAN Number",
        "definition": "Permanent Account Number issued by Income Tax Department of India",
        "data_type": "string",
        "classification": "PII",
        "dq_rules": "format: ^[A-Z]{5}[0-9]{4}[A-Z]$",
        "synonyms": "pan, pan_no, pan_card",
    },
    {
        "id": "aadhaar_number",
        "name": "Aadhaar Number",
        "definition": "12-digit unique identity number issued by UIDAI",
        "data_type": "string",
        "classification": "PII",
        "dq_rules": "format: ^[0-9]{12}$",
        "synonyms": "aadhaar, aadhar, aadhaar_no, uid",
    },
    {
        "id": "address",
        "name": "Address",
        "definition": "Physical or mailing address of the customer",
        "data_type": "string",
        "classification": "PII",
        "dq_rules": "",
        "synonyms": "addr, street, address_line, postal_address",
    },
    # --- Account ---
    {
        "id": "account_identifier",
        "name": "Account Identifier",
        "definition": "Unique identifier for a bank account",
        "data_type": "string",
        "classification": "Internal",
        "dq_rules": "not_null, unique",
        "synonyms": "account_id, acct_id, acct_no, account_number",
    },
    {
        "id": "account_balance",
        "name": "Account Balance",
        "definition": "Current monetary balance in a bank account",
        "data_type": "decimal",
        "classification": "Sensitive",
        "dq_rules": "not_null",
        "synonyms": "balance, bal_amt, current_balance, available_balance",
    },
    # --- Credit / Bureau ---
    {
        "id": "credit_score",
        "name": "Credit Score",
        "definition": "Credit score provided by a credit bureau (e.g., TransUnion CIBIL). Ranges from 300 to 900.",
        "data_type": "integer",
        "classification": "Sensitive",
        "dq_rules": "not_null, range: [300, 900]",
        "synonyms": "cibil_score, bureau_score, fico_score, risk_score",
    },
    {
        "id": "bureau_reference",
        "name": "Bureau Reference",
        "definition": "Unique reference ID for a bureau enquiry or report",
        "data_type": "string",
        "classification": "Internal",
        "dq_rules": "not_null, unique",
        "synonyms": "bureau_ref, bureau_id, enquiry_id, bureau_reference_id",
    },
    {
        "id": "loan_amount",
        "name": "Loan Amount",
        "definition": "Principal amount of a loan sanctioned or requested",
        "data_type": "decimal",
        "classification": "Sensitive",
        "dq_rules": "not_null, positive",
        "synonyms": "loan_amt, sanctioned_amount, loan_amount_requested, principal",
    },
    # --- Transaction / Payments ---
    {
        "id": "transaction_amount",
        "name": "Transaction Amount",
        "definition": "Monetary value of a financial transaction",
        "data_type": "decimal",
        "classification": "Internal",
        "dq_rules": "not_null, positive",
        "synonyms": "amount, amt, txn_amount, txn_amt, total_amount, bill_amt",
    },
    {
        "id": "transaction_date",
        "name": "Transaction Date",
        "definition": "Date and time when a financial transaction occurred",
        "data_type": "timestamp",
        "classification": "Internal",
        "dq_rules": "not_null",
        "synonyms": "txn_date, txn_dt, transaction_dt, value_date",
    },
    {
        "id": "payment_method",
        "name": "Payment Method",
        "definition": "Mode of payment used for a transaction",
        "data_type": "string",
        "classification": "Internal",
        "dq_rules": "accepted_values: [credit_card, debit_card, upi, net_banking, wallet, cod]",
        "synonyms": "pay_method, payment_type, pay_type, payment_mode",
    },
    {
        "id": "currency_code",
        "name": "Currency Code",
        "definition": "ISO 4217 currency code for a monetary value",
        "data_type": "string",
        "classification": "Internal",
        "dq_rules": "accepted_values: [INR, USD, GBP, EUR]",
        "synonyms": "currency, ccy, curr_cd",
    },
    # --- Order ---
    {
        "id": "order_identifier",
        "name": "Order Identifier",
        "definition": "Unique identifier for a customer order",
        "data_type": "string",
        "classification": "Internal",
        "dq_rules": "not_null, unique",
        "synonyms": "order_id, order_no, order_number, ord_id",
    },
    {
        "id": "order_status",
        "name": "Order Status",
        "definition": "Current lifecycle status of an order",
        "data_type": "string",
        "classification": "Internal",
        "dq_rules": "accepted_values: [delivered, shipped, processing, cancelled, returned]",
        "synonyms": "status, order_status, ord_status",
    },
    # --- Product ---
    {
        "id": "product_identifier",
        "name": "Product Identifier",
        "definition": "Unique identifier for a product or service",
        "data_type": "string",
        "classification": "Internal",
        "dq_rules": "not_null, unique",
        "synonyms": "product_id, prod_id, sku, item_id, product_code",
    },
    {
        "id": "product_name",
        "name": "Product Name",
        "definition": "Display name of a product or service",
        "data_type": "string",
        "classification": "Internal",
        "dq_rules": "not_null",
        "synonyms": "prod_name, item_name, product_title",
    },
    # --- KYC ---
    {
        "id": "kyc_status",
        "name": "KYC Status",
        "definition": "Current status of Know Your Customer verification",
        "data_type": "string",
        "classification": "Internal",
        "dq_rules": "accepted_values: [verified, pending, rejected, expired]",
        "synonyms": "kyc_status, verification_status, kyc_state",
    },
    # --- Digital ---
    {
        "id": "session_identifier",
        "name": "Session Identifier",
        "definition": "Unique identifier for a user session on digital channels",
        "data_type": "string",
        "classification": "Internal",
        "dq_rules": "not_null",
        "synonyms": "session_id, sess_id, visit_id",
    },
    {
        "id": "event_timestamp",
        "name": "Event Timestamp",
        "definition": "Date and time when an event occurred in a system",
        "data_type": "timestamp",
        "classification": "Internal",
        "dq_rules": "not_null",
        "synonyms": "event_ts, timestamp, ts, event_time, created_at, updated_at",
    },
    # --- Common ---
    {
        "id": "country_code",
        "name": "Country Code",
        "definition": "ISO 3166-1 alpha-2 country code",
        "data_type": "string",
        "classification": "Internal",
        "dq_rules": "accepted_values: [IN, GB, US, DE, FR, AU, SG]",
        "synonyms": "country, cntry_cd, country_cd, nation",
    },
    {
        "id": "region",
        "name": "Region",
        "definition": "Geographic region or territory",
        "data_type": "string",
        "classification": "Internal",
        "dq_rules": "",
        "synonyms": "region, area, zone, territory",
    },
]


def build_description(term: dict) -> str:
    """Build a structured description for the glossary term."""
    parts = [term["definition"]]
    parts.append(f"\nData Type: {term['data_type']}")
    parts.append(f"Classification: {term['classification']}")
    if term.get("dq_rules"):
        parts.append(f"DQ Rules: {term['dq_rules']}")
    if term.get("synonyms"):
        parts.append(f"Synonyms: {term['synonyms']}")
    return "\n".join(parts)


def main():
    print("=" * 60)
    print("  Setup Business Glossary")
    print("=" * 60)

    # Step 1: Create glossary
    print("\n[1/2] Creating glossary...")
    glossary = dataplex_v1.Glossary(
        description="Enterprise Business Data Element Dictionary. "
                    "Reusable definitions of business data elements across the organisation."
    )
    req = dataplex_v1.CreateGlossaryRequest(
        parent=glossary_parent, glossary=glossary, glossary_id=GLOSSARY_ID
    )
    try:
        op = client.create_glossary(request=req)
        if hasattr(op, 'result'):
            op.result()
        print(f"  [OK] Glossary created: {GLOSSARY_ID}")
    except Exception as e:
        if "ALREADY_EXISTS" in str(e):
            print(f"  [OK] Glossary already exists")
        else:
            raise

    # Step 2: Create terms
    print(f"\n[2/2] Creating {len(TERMS)} business data elements...")
    success = 0
    for t in TERMS:
        desc = build_description(t)
        term = dataplex_v1.GlossaryTerm(
            description=desc,
            display_name=t["name"],
            parent=glossary_name,
        )
        req = dataplex_v1.CreateGlossaryTermRequest(
            parent=glossary_name, term=term, term_id=t["id"]
        )
        try:
            client.create_glossary_term(request=req)
            print(f"  [OK] {t['name']}")
            success += 1
        except Exception as e:
            if "ALREADY_EXISTS" in str(e):
                print(f"  [EXISTS] {t['name']}")
                success += 1
            else:
                print(f"  [FAIL] {t['name']}: {e}")

    print(f"\n{'=' * 60}")
    print(f"  Glossary Setup Complete: {success}/{len(TERMS)} terms")
    print(f"{'=' * 60}")
    print(f"\n  View: https://console.cloud.google.com/dataplex/glossaries?project={PROJECT_ID}")


if __name__ == "__main__":
    main()
