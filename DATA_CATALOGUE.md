# BT Data Fabric — Onboarded Dataset Catalogue

**Project**: `bt-df-lkhouse` | **Region**: `europe-west2`
**Platform**: Ontika / CDH 2.0 | **Last Updated**: July 2025

---

## How to Read This Document

Each dataset entry covers:
- **What it is** — the data and its source system
- **Business purpose** — why we hold it and who uses it
- **Domain / Business Application** — how it's classified in the glossary
- **Key fields** — primary identifiers and notable attributes
- **PII** — any personally identifiable information present
- **Landing path** — where raw data lands in GCS

---

## 1. E-Commerce / Retail Datasets

These were the original datasets used to build and validate the CDH 2.0 framework, schema evolution, and pipeline mechanics.

---

### 1.1 Customers
| Attribute | Value |
|---|---|
| Dataset name | `customers` |
| Source application | CRM |
| Domain | Customer |
| Business Application | Customer Management |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/customers/v1` |

**What it is**: Master customer records for all retail/e-commerce customers.

**Business purpose**: Single source of truth for customer identity. Used by marketing for segmentation, by billing for invoicing, and by compliance for KYC checks. V2 introduced `customer_segment` (Enterprise/SMB/Consumer) and a new `Diamond` loyalty tier — used to validate schema evolution (add column, enum expansion).

**Key fields**: `customer_id` (PK), `email` (PII), `phone` (PII), `address` (PII), `loyalty_tier`, `region`, `signup_date`

**PII**: name, email, phone, address

---

### 1.2 Products
| Attribute | Value |
|---|---|
| Dataset name | `products` |
| Source application | Product Catalog System |
| Domain | Product |
| Business Application | Product Catalog |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/products/v1` |

**What it is**: Product master — all items available for sale including pricing, SKU, supplier, and inventory status.

**Business purpose**: Reference data used by orders, payments, and marketing. Drives pricing rules and product availability checks in the pipeline.

**Key fields**: `product_id` (PK), `sku`, `product_name`, `category`, `price`, `cost_price`, `supplier`

**PII**: None

---

### 1.3 Orders
| Attribute | Value |
|---|---|
| Dataset name | `orders` |
| Source application | Order Management System |
| Domain | Order |
| Business Application | Order Management |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/orders/v1` |

**What it is**: All customer orders including status, amounts, channel, and region.

**Business purpose**: Core transactional dataset for revenue reporting, fulfilment tracking, and customer behaviour analysis. V2 introduced large order amounts exceeding INT max — used to validate type widening (int → bigint) in schema evolution, and a new `marketplace` channel value.

**Key fields**: `order_id` (PK), `customer_id` (FK), `order_date`, `status`, `total_amount`, `channel`, `region`

**PII**: None (customer_id is a reference, not PII itself)

---

### 1.4 Payments
| Attribute | Value |
|---|---|
| Dataset name | `payments` |
| Source application | Payments Gateway |
| Domain | Finance |
| Business Application | Billing & Finance |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/payments/v1` |

**What it is**: Payment transactions linked to orders — method, status, currency, and transaction reference.

**Business purpose**: Financial reconciliation, fraud detection, and revenue recognition. V2 added `payment_channel` (new column) and multi-currency support (GBP/EUR/USD) — used to validate schema evolution and accepted values expansion.

**Key fields**: `payment_id` (PK), `order_id` (FK), `amount`, `payment_method`, `status`, `currency`, `transaction_ref`

**PII**: None

---

### 1.5 Clickstream (Streaming)
| Attribute | Value |
|---|---|
| Dataset name | `clickstream` |
| Source application | Web / App Analytics |
| Domain | Digital & Clickstream |
| Business Application | Marketing & Campaigns |
| Landing path | Kafka topic → direct to CCN Iceberg (streaming) |

**What it is**: Real-time web and app interaction events — page views, clicks, product views, session data.

**Business purpose**: Powers real-time personalisation, funnel analysis, and campaign attribution. Ingested via Spark Structured Streaming from Confluent Kafka with micro-batch windowing.

**Key fields**: `event_id` (PK), `customer_id`, `event_type`, `page_url`, `session_id`, `device_type`, `event_timestamp`

**PII**: None directly, but `customer_id` links to PII in customers table

---

### 1.6 Transactions Stream (Streaming)
| Attribute | Value |
|---|---|
| Dataset name | `transactions_stream` |
| Source application | Payments Gateway (real-time) |
| Domain | Finance |
| Business Application | Billing & Finance |
| Landing path | Kafka topic → direct to CCN Iceberg (streaming) |

**What it is**: Real-time payment transaction events streamed from the payments gateway — mirrors the batch payments dataset but at event granularity with risk scoring.

**Business purpose**: Real-time fraud detection and payment monitoring. Includes `risk_score` and `gateway` fields not present in the batch payments feed.

**Key fields**: `transaction_id` (PK), `order_id`, `customer_id`, `amount`, `status`, `risk_score`, `gateway`, `event_timestamp`

**PII**: None

---

## 2. Banking / Financial Services Datasets

These datasets represent the BT Data Fabric banking use case — onboarded to demonstrate the framework's capability with regulated financial data.

---

### 2.1 CIBIL Bureau Feed
| Attribute | Value |
|---|---|
| Dataset name | `cibil_bureau_feed` |
| Source application | TransUnion CIBIL (external bureau) |
| Domain | Bureau & External |
| Business Application | Credit Risk & Lending |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/cibil_bureau_feed/v1` |

**What it is**: Credit bureau data pulled from TransUnion CIBIL — credit scores, loan history, enquiry records, and delinquency indicators per customer.

**Business purpose**: Used by the loan origination system to assess creditworthiness before approving loans. Also feeds the risk engine for PD (probability of default) modelling. Highly regulated — PAN number and date of birth are PII and must be masked in silver.

**Key fields**: `customer_id`, `pan_number` (PII), `cibil_score`, `score_date`, `enquiry_date`, `loan_amount_requested`, `dpd_30_plus_count`, `bureau_reference_id`, `date_of_birth` (PII)

**PII**: pan_number, date_of_birth, mobile_number, email_address

---

### 2.2 CIBIL Bureau Feed (TransUnion variant)
| Attribute | Value |
|---|---|
| Dataset name | `cibil_bureau_feed_from_transunion` |
| Source application | TransUnion (alternate feed) |
| Domain | Bureau & External |
| Business Application | Credit Risk & Lending |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/cibil_bureau_feed_from_transunion/v1` |

**What it is**: A second variant of the CIBIL bureau feed from TransUnion with slightly different field naming conventions — used to test the framework's ability to handle multiple feeds from the same source with schema differences.

**Business purpose**: Same as CIBIL Bureau Feed above. The dual-feed setup validates the framework's deduplication and merge logic when two feeds cover overlapping customer populations.

**PII**: Same as above

---

### 2.3 e-KYC Provider Feed
| Attribute | Value |
|---|---|
| Dataset name | `ekyc_provider_feed` |
| Source application | e-KYC Provider (external) |
| Domain | Customer |
| Business Application | Customer Management |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/ekyc_provider_feed/v1` |

**What it is**: Digital KYC verification records — Aadhaar-based identity verification, verification mode (video/OTP/biometric), consent timestamps, and KYC status per customer.

**Business purpose**: Regulatory requirement for customer onboarding. KYC status drives whether a customer can transact. Consent timestamp is critical for audit and GDPR compliance. Aadhaar number is highly sensitive PII.

**Key fields**: `customer_id`, `aadhaar_number` (PII), `kyc_status`, `kyc_verified_date`, `verification_mode`, `full_name` (PII), `address` (PII), `consent_timestamp`

**PII**: aadhaar_number, full_name, address, photo_url

---

### 2.4 UPI Transactions
| Attribute | Value |
|---|---|
| Dataset name | `upi_transactions` |
| Source application | Payments Hub (UPI) |
| Domain | Payments |
| Business Application | Payments Hub |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/upi_transactions/v1` |

**What it is**: UPI (Unified Payments Interface) transaction records — payer/payee VPAs, amounts, merchant category codes, device IDs, and transaction status.

**Business purpose**: Payment reconciliation, fraud detection, and merchant analytics. VPA (Virtual Payment Address) is PII as it can identify an individual. MCC codes are used for spend categorisation and AML monitoring.

**Key fields**: `transaction_id` (PK), `payer_vpa` (PII), `payee_vpa`, `amount`, `transaction_date`, `status`, `mcc_code`, `device_id`

**PII**: payer_vpa (links to individual identity)

---

### 2.5 Loan Repayment Schedule
| Attribute | Value |
|---|---|
| Dataset name | `loan_repayment_schedule` |
| Source application | Loan Management System |
| Domain | Lending |
| Business Application | Loan Management System |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/loan_repayment_schedule/v1` |

**What it is**: EMI-level repayment schedule for all active loans — due dates, payment status, DPD (days past due), principal/interest split, and penalty amounts.

**Business purpose**: Core dataset for loan servicing, collections, and NPA (non-performing asset) classification. DPD is the key metric for regulatory reporting (RBI). Used by the risk engine to update PD models with actual repayment behaviour.

**Key fields**: `loan_id` (PK), `customer_id`, `emi_number`, `due_date`, `emi_amount`, `payment_status`, `dpd_days`, `penalty_amount`

**PII**: None directly (customer_id is a reference)

---

### 2.6 Customer Complaints
| Attribute | Value |
|---|---|
| Dataset name | `customer_complaints` |
| Source application | CRM |
| Domain | Customer |
| Business Application | Customer Relationship Management |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/customer_complaints/v1` |

**What it is**: Customer complaint records across all channels (app, email, phone, branch, social media) — category, sub-category, priority, assigned agent, resolution date, and CSAT score.

**Business purpose**: Regulatory reporting (RBI mandates complaint resolution SLAs), customer experience management, and agent performance tracking. CSAT scores feed into NPS calculations.

**Key fields**: `complaint_id` (PK), `customer_id`, `complaint_date`, `channel`, `category`, `priority`, `status`, `resolution_date`, `csat_score`

**PII**: None directly

---

### 2.7 FD Maturity Feed
| Attribute | Value |
|---|---|
| Dataset name | `fd_maturity_feed` |
| Source application | Core Banking System |
| Domain | Banking & Deposits |
| Business Application | Core Banking System |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/fd_maturity_feed/v1` |

**What it is**: Fixed deposit maturity records — FD account details, principal, interest rate, tenure, maturity date, and renewal instructions.

**Business purpose**: Treasury management and customer notification workflows. Maturing FDs trigger renewal or payout processes. Also used for liquidity forecasting and interest expense reporting.

**Key fields**: `fd_account_id` (PK), `customer_id`, `principal_amount`, `interest_rate`, `tenure_months`, `maturity_date`, `renewal_flag`

**PII**: None directly

---

## 3. Investment Banking Datasets

These five feeds represent the Investment Banking (IB) domain, onboarded to extend the framework into capital markets data. All generated with 300 records each.

---

### 3.1 Trade Blotter
| Attribute | Value |
|---|---|
| Dataset name | `trade_blotter` |
| Source application | Trading Desk System |
| Domain | Investment Banking |
| Business Application | Investment Banking |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/trade_blotter/v1` |

**What it is**: Daily trade execution records across all IB desks — equities, fixed income, derivatives, FX, and structured products. Each record represents a single executed (or pending/failed) trade.

**Business purpose**: Front-office trade capture and back-office settlement. Feeds into P&L reporting, position management, and regulatory trade reporting (MiFID II). Settlement date drives the T+2 settlement cycle. Counterparty ID links to the KYC register.

**Key fields**: `trade_id` (PK), `trader_id`, `desk_code`, `instrument_type`, `isin`, `quantity`, `trade_price`, `trade_date`, `settlement_date`, `counterparty_id`, `buy_sell_flag`, `currency`, `status`

**PII**: None (institutional data)

---

### 3.2 Portfolio Holdings
| Attribute | Value |
|---|---|
| Dataset name | `portfolio_holdings` |
| Source application | Portfolio Management System |
| Domain | Investment Banking |
| Business Application | Investment Banking |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/portfolio_holdings/v1` |

**What it is**: End-of-day portfolio positions — holdings by portfolio, fund manager, asset class, sector, and country of risk. Includes market value and cost basis for P&L calculation.

**Business purpose**: Daily NAV (Net Asset Value) calculation, risk exposure reporting, and regulatory capital adequacy reporting. Market value vs cost basis drives unrealised P&L. Country of risk is used for geographic concentration limits.

**Key fields**: `portfolio_id`, `fund_manager_id`, `isin`, `asset_class`, `position_quantity`, `market_value`, `cost_basis`, `valuation_date`, `currency`, `country_of_risk`, `sector_code`

**PII**: None (institutional data)

---

### 3.3 IB Client KYC
| Attribute | Value |
|---|---|
| Dataset name | `ib_client_kyc` |
| Source application | Client Onboarding / AML System |
| Domain | Investment Banking |
| Business Application | Investment Banking / AML System |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/ib_client_kyc/v1` |

**What it is**: Institutional client KYC records — legal entity details, LEI (Legal Entity Identifier) codes, risk ratings, KYC status, review due dates, and AML clearance flags.

**Business purpose**: Regulatory compliance (FCA, MiFID II). No trade can be executed with a client whose KYC is expired or rejected. AML clearance flag gates onboarding. Review due date drives the periodic KYC refresh workflow. LEI is the global standard identifier for legal entities.

**Key fields**: `client_id` (PK), `legal_entity_name`, `lei_code`, `incorporation_country`, `kyc_status`, `risk_rating`, `onboarding_date`, `review_due_date`, `relationship_manager_id`, `aml_cleared_flag`

**PII**: legal_entity_name (institutional, not personal PII but commercially sensitive)

---

### 3.4 Corporate Actions
| Attribute | Value |
|---|---|
| Dataset name | `corporate_actions` |
| Source application | Corporate Actions Processing System |
| Domain | Investment Banking |
| Business Application | Investment Banking |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/corporate_actions/v1` |

**What it is**: Corporate action events affecting securities held in portfolios — dividends, stock splits, rights issues, mergers, spin-offs, buybacks, and bonus issues. Includes announcement, ex-date, record date, and payment date.

**Business purpose**: Portfolio holdings must be adjusted when corporate actions occur (e.g. a stock split doubles position quantity and halves price). Dividend payments generate cash flows. Mergers trigger position substitutions. Failure to process corporate actions correctly leads to incorrect P&L and NAV.

**Key fields**: `action_id` (PK), `isin`, `action_type`, `announcement_date`, `ex_date`, `record_date`, `payment_date`, `ratio`, `cash_amount`, `currency`, `status`

**PII**: None

---

### 3.5 Deal Pipeline
| Attribute | Value |
|---|---|
| Dataset name | `deal_pipeline` |
| Source application | M&A / Investment Banking CRM |
| Domain | Investment Banking |
| Business Application | Investment Banking |
| Landing path | `gs://bt-df-lkhouse-lakehouse/landing/deal_pipeline/v1` |

**What it is**: M&A and capital markets deal pipeline — all live and historical deals tracked from origination through to close or termination. Covers acquisitions, mergers, IPOs, secondary offerings, divestitures, LBOs, and joint ventures.

**Business purpose**: Revenue forecasting (deal fees are recognised on close), resource allocation across deal teams, and conflict checking (a bank cannot advise both sides of a deal). `confidentiality_flag` marks deals under NDA — these must be ring-fenced from other parts of the bank (Chinese wall). Deal value drives league table rankings.

**Key fields**: `deal_id` (PK), `deal_name`, `client_id`, `deal_type`, `target_company`, `deal_value`, `currency`, `stage`, `origination_date`, `expected_close_date`, `lead_banker_id`, `sector`, `confidentiality_flag`

**PII**: None (institutional data, but `confidentiality_flag=true` records are commercially sensitive)

---

## Summary

| # | Dataset | Domain | Business Application | Records | PII |
|---|---|---|---|---|---|
| 1 | customers | Customer | Customer Management | 10,000 | Yes |
| 2 | products | Product | Product Catalog | 1,000 | No |
| 3 | orders | Order | Order Management | 10,000 | No |
| 4 | payments | Finance | Billing & Finance | 10,000 | No |
| 5 | clickstream | Digital & Clickstream | Marketing & Campaigns | Streaming | No |
| 6 | transactions_stream | Finance | Billing & Finance | Streaming | No |
| 7 | cibil_bureau_feed | Bureau & External | Credit Risk & Lending | 1,000 | Yes |
| 8 | cibil_bureau_feed_from_transunion | Bureau & External | Credit Risk & Lending | 1,000 | Yes |
| 9 | ekyc_provider_feed | Customer | Customer Management | 800 | Yes |
| 10 | upi_transactions | Payments | Payments Hub | 5,000 | Yes |
| 11 | loan_repayment_schedule | Lending | Loan Management System | 2,400 | No |
| 12 | customer_complaints | Customer | CRM | 600 | No |
| 13 | fd_maturity_feed | Banking & Deposits | Core Banking System | 300 | No |
| 14 | trade_blotter | Investment Banking | Investment Banking | 300 | No |
| 15 | portfolio_holdings | Investment Banking | Investment Banking | 300 | No |
| 16 | ib_client_kyc | Investment Banking | Investment Banking / AML | 300 | Sensitive |
| 17 | corporate_actions | Investment Banking | Investment Banking | 300 | No |
| 18 | deal_pipeline | Investment Banking | Investment Banking | 300 | Sensitive |
