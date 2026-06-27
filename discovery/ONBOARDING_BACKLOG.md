# Data Onboarding Backlog — Banking Use Cases

## Context

With the Semantic Discovery platform operational and the end-to-end pipeline proven (CIBIL bureau feed), these are the next datasets to onboard. Each represents a real banking data source that feeds into a business-critical data product.

---

## Use Case 1: e-KYC Provider Feed

**Domain:** Customer Management
**Business Application:** KYC & Onboarding System
**Priority:** HIGH — completes the "instant loan" mobile app feature
**Source System:** DigiLocker / NSDL e-KYC gateway

### Schema

```yaml
name: ekyc_provider_feed
fields:
  - name: customer_id
    type: string
  - name: aadhaar_number
    type: string
  - name: kyc_status
    type: string
  - name: kyc_verified_date
    type: date
  - name: verification_mode
    type: string
  - name: full_name
    type: string
  - name: address
    type: string
  - name: consent_timestamp
    type: timestamp
  - name: provider_reference_id
    type: string
```

### Expected SD Outcome

| Field | BDE | PII | DQ |
|-------|-----|-----|----|
| customer_id | Customer Identifier | No | not_null, unique |
| aadhaar_number | Aadhaar Number | YES | format: aadhaar |
| kyc_status | KYC Status | No | accepted_values: [verified, pending, rejected, expired] |
| full_name | Customer Name | YES | not_null |
| address | Address | YES | — |
| provider_reference_id | (new term) | No | not_null, unique |

### Data Product It Enables

**`loan_eligibility_360` (v2)** — adds KYC status to the existing CIBIL-based eligibility:

```sql
SELECT
    c.customer_id, c.name, c.region,
    b.cibil_score,
    k.kyc_status, k.verification_mode,
    CASE
        WHEN b.cibil_score >= 750 AND k.kyc_status = 'verified' THEN 'pre_approved'
        WHEN b.cibil_score >= 650 AND k.kyc_status = 'verified' THEN 'eligible'
        WHEN b.cibil_score >= 650 AND k.kyc_status = 'pending' THEN 'kyc_required'
        ELSE 'not_eligible'
    END AS loan_eligibility_status
FROM customers c
JOIN cibil_bureau_feed b ON c.customer_id = b.customer_id
JOIN ekyc_provider_feed k ON c.customer_id = k.customer_id
```

---

## Use Case 2: UPI Transactions

**Domain:** Payments
**Business Application:** Payments Hub
**Priority:** HIGH — high volume, enables spend analytics
**Source System:** NPCI UPI switch / Payment gateway

### Schema

```yaml
name: upi_transactions
fields:
  - name: transaction_id
    type: string
  - name: payer_vpa
    type: string
  - name: payee_vpa
    type: string
  - name: amount
    type: decimal
  - name: transaction_date
    type: timestamp
  - name: status
    type: string
  - name: remitter_account
    type: string
  - name: beneficiary_account
    type: string
  - name: mcc_code
    type: string
  - name: device_id
    type: string
```

### Expected SD Outcome

| Field | BDE | PII | DQ |
|-------|-----|-----|----|
| transaction_id | (new: UPI Transaction ID) | No | not_null, unique |
| payer_vpa | (new: VPA) | YES (PII) | not_null |
| payee_vpa | (new: VPA) | YES (PII) | not_null |
| amount | Transaction Amount | No | not_null, positive |
| transaction_date | Transaction Date | No | not_null |
| status | (new: UPI Status) | No | accepted_values: [success, failed, pending, declined] |
| remitter_account | Account Identifier | YES | — |
| beneficiary_account | Account Identifier | YES | — |
| device_id | (new: Device Identifier) | Sensitive | — |

### Data Product It Enables

**`customer_spend_360`** — spend patterns by category, merchant, time:

```sql
SELECT
    c.customer_id, c.name, c.region, c.loyalty_tier,
    COUNT(u.transaction_id) AS total_txns,
    SUM(u.amount) AS total_spend,
    AVG(u.amount) AS avg_txn_value,
    COUNT(DISTINCT u.payee_vpa) AS unique_merchants,
    MAX(u.transaction_date) AS last_txn_date
FROM customers c
JOIN upi_transactions u ON c.customer_id = u.remitter_account
WHERE u.status = 'success'
GROUP BY 1, 2, 3, 4
```

---

## Use Case 3: Card Transactions

**Domain:** Cards
**Business Application:** Card Management System
**Priority:** MEDIUM — enables fraud detection
**Source System:** Card switch / Visa/Mastercard network

### Schema

```yaml
name: card_transactions
fields:
  - name: transaction_id
    type: string
  - name: card_number_masked
    type: string
  - name: customer_id
    type: string
  - name: merchant_name
    type: string
  - name: merchant_category
    type: string
  - name: amount
    type: decimal
  - name: currency
    type: string
  - name: transaction_datetime
    type: timestamp
  - name: is_international
    type: boolean
  - name: pos_entry_mode
    type: string
  - name: response_code
    type: string
```

### Expected SD Outcome

| Field | BDE | PII | DQ |
|-------|-----|-----|----|
| transaction_id | (new: Card Transaction ID) | No | not_null, unique |
| card_number_masked | (new: Masked Card Number) | Sensitive | not_null |
| customer_id | Customer Identifier | No | not_null |
| merchant_name | (new: Merchant Name) | No | — |
| amount | Transaction Amount | No | not_null, positive |
| currency | Currency Code | No | accepted_values |
| is_international | (new: International Flag) | No | — |
| pos_entry_mode | (new: POS Entry Mode) | No | accepted_values: [chip, swipe, contactless, ecommerce, manual] |

### Data Product It Enables

**`fraud_risk_indicators`** — flags for the fraud engine:

```sql
SELECT
    customer_id,
    COUNT(*) AS txn_count_24h,
    COUNT(DISTINCT merchant_category) AS unique_categories_24h,
    SUM(CASE WHEN is_international THEN 1 ELSE 0 END) AS international_txns,
    MAX(amount) AS max_amount_24h,
    SUM(amount) AS total_amount_24h,
    CASE
        WHEN COUNT(*) > 10 AND SUM(amount) > 100000 THEN 'HIGH'
        WHEN COUNT(DISTINCT merchant_category) > 5 THEN 'MEDIUM'
        ELSE 'LOW'
    END AS risk_level
FROM card_transactions
WHERE transaction_datetime > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY customer_id
```

---

## Use Case 4: Loan Repayment Schedule

**Domain:** Credit / Lending
**Business Application:** Loan Management System
**Priority:** MEDIUM — enables collections prioritisation
**Source System:** LMS (Loan Management System)
**SCD Type:** Type 2 (track payment_status changes over time)

### Schema

```yaml
name: loan_repayment_schedule
fields:
  - name: loan_id
    type: string
  - name: customer_id
    type: string
  - name: emi_number
    type: integer
  - name: due_date
    type: date
  - name: emi_amount
    type: decimal
  - name: principal_component
    type: decimal
  - name: interest_component
    type: decimal
  - name: payment_status
    type: string
  - name: payment_date
    type: date
  - name: dpd_days
    type: integer
  - name: penalty_amount
    type: decimal
```

### Expected SD Outcome

| Field | BDE | PII | DQ |
|-------|-----|-----|----|
| loan_id | (new: Loan Identifier) | No | not_null |
| customer_id | Customer Identifier | No | not_null |
| emi_amount | (new: EMI Amount) | No | not_null, positive |
| payment_status | (new: Payment Status) | No | accepted_values: [paid, overdue, partial, waived] |
| dpd_days | (new: Days Past Due) | No | range: [0, 365] |

### SCD Type 2 Config

```yaml
dim_loan_repayment:
  table: dim_loan_repayment
  scd_type: 2
  primary_key: loan_id
  source_query: |
    SELECT * FROM `${PROJECT_ID}.lakehouse_ccn.loan_repayment_schedule`
  tracked_columns:
    - payment_status
    - dpd_days
    - penalty_amount
```

### Data Product It Enables

**`collections_priority`** — who to call first:

```sql
SELECT
    r.customer_id,
    c.name, c.phone,
    r.loan_id,
    r.emi_amount,
    r.dpd_days,
    r.penalty_amount,
    CASE
        WHEN r.dpd_days > 90 THEN 'NPA'
        WHEN r.dpd_days > 60 THEN 'CRITICAL'
        WHEN r.dpd_days > 30 THEN 'HIGH'
        WHEN r.dpd_days > 0 THEN 'MEDIUM'
        ELSE 'CURRENT'
    END AS collection_priority
FROM loan_repayment_schedule r
JOIN customers c ON r.customer_id = c.customer_id
WHERE r.payment_status = 'overdue'
ORDER BY r.dpd_days DESC
```

---

## Use Case 5: Customer Complaints

**Domain:** Customer Management
**Business Application:** CRM
**Priority:** LOW — enables customer health scoring
**Source System:** CRM / ServiceNow / Freshdesk

### Schema

```yaml
name: customer_complaints
fields:
  - name: complaint_id
    type: string
  - name: customer_id
    type: string
  - name: complaint_date
    type: date
  - name: channel
    type: string
  - name: category
    type: string
  - name: sub_category
    type: string
  - name: description
    type: string
  - name: priority
    type: string
  - name: assigned_to
    type: string
  - name: resolution_date
    type: date
  - name: status
    type: string
  - name: csat_score
    type: integer
```

### Expected SD Outcome

| Field | BDE | PII | DQ |
|-------|-----|-----|----|
| complaint_id | (new: Complaint Identifier) | No | not_null, unique |
| customer_id | Customer Identifier | No | not_null |
| channel | (new: Complaint Channel) | No | accepted_values: [app, email, phone, branch, social_media] |
| category | (new: Complaint Category) | No | — |
| priority | (new: Priority Level) | No | accepted_values: [low, medium, high, critical] |
| status | (new: Complaint Status) | No | accepted_values: [open, in_progress, resolved, escalated, closed] |
| csat_score | (new: CSAT Score) | No | range: [1, 5] |

### Data Product It Enables

**`customer_health_score`** — churn prediction input:

```sql
SELECT
    c.customer_id, c.name, c.loyalty_tier,
    COUNT(comp.complaint_id) AS total_complaints,
    AVG(comp.csat_score) AS avg_csat,
    SUM(CASE WHEN comp.status = 'escalated' THEN 1 ELSE 0 END) AS escalations,
    MAX(comp.complaint_date) AS last_complaint_date,
    CASE
        WHEN AVG(comp.csat_score) < 2 AND COUNT(*) > 3 THEN 'AT_RISK'
        WHEN AVG(comp.csat_score) < 3 THEN 'MONITOR'
        ELSE 'HEALTHY'
    END AS health_status
FROM customers c
LEFT JOIN customer_complaints comp ON c.customer_id = comp.customer_id
GROUP BY 1, 2, 3
```

---

## Onboarding Summary

| # | Dataset | Domain | SCD | Data Product | Priority |
|---|---------|--------|-----|-------------|----------|
| 1 | ekyc_provider_feed | Customer | Type 1 | loan_eligibility_360 v2 | HIGH |
| 2 | upi_transactions | Payments | Type 1 | customer_spend_360 | HIGH |
| 3 | card_transactions | Cards | Type 1 | fraud_risk_indicators | MEDIUM |
| 4 | loan_repayment_schedule | Credit | Type 2 | collections_priority | MEDIUM |
| 5 | customer_complaints | Customer | Type 1 | customer_health_score | LOW |

---

## How to Onboard Each

For each dataset:

1. **Talk to SD** — paste the YAML or describe naturally
2. **SD discovers** — suggests BDEs, PII, DQ, Business Application
3. **Approve** — SD creates BDEs in glossary, pushes config to GCS
4. **Cloud Function triggers** — pipeline runs automatically
5. **Data appears in BigQuery** — ready for consumers

Once the Cloud Function is deployed, steps 4-5 are fully automated. The adoption team only does steps 1-3.

---

## New Business Terms Created (from these onboardings)

After all 5 feeds are onboarded, the glossary will grow by ~25 new terms:

- UPI Transaction ID, VPA, UPI Status, Device Identifier
- Card Transaction ID, Masked Card Number, Merchant Name, POS Entry Mode, International Flag
- Loan Identifier, EMI Amount, Payment Status, Days Past Due
- Complaint Identifier, Complaint Channel, Complaint Category, Priority Level, Complaint Status, CSAT Score
- Verification Mode, Provider Reference ID

Each one enriches the Knowledge Catalog for the NEXT onboarding — the learning loop.
