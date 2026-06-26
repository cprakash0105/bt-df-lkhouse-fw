# Semantic Discovery — Project Status

## What Has Been Built

### Core Engine (Working & Tested)

| Component | File | Status | Description |
|-----------|------|--------|-------------|
| Knowledge Graph | `engine/knowledge_graph.py` | DONE | Stores business terms, domains, applications, reference sets. Synonym-based search. Local YAML backend (Firestore-ready). |
| Rules Engine | `engine/rules_engine.py` | DONE | Deterministic pattern matching: naming conventions (*_id, *_amt, *_date), PII detection, FK heuristics, business application keyword matching. |
| Embedder | `engine/embedder.py` | DONE | Hybrid: Vertex AI text-embedding-005 (GCP) / sentence-transformers (local) / TF-IDF fallback (zero-dependency). Auto-detects best available. |
| Suggester | `engine/suggester.py` | DONE | Core orchestrator. Two modes: Full Discovery (new asset) and Delta Discovery (schema change). Combines KG + Rules + Embeddings. |
| Config Generator | `engine/config_generator.py` | DONE | Converts approved suggestions into `config/tables/*.yaml` compatible with bt_df_lkhouse_fw pipeline. Also generates catalog entry JSON. |

### Configuration

| File | Status | Description |
|------|--------|-------------|
| `config/seed_glossary.yaml` | DONE (minimal) | 27 business terms, 6 applications, 6 domains, 7 reference code sets. Covers basic customer, order, product, finance, bureau, digital domains. |
| `config/rules.yaml` | DONE | Naming rules, PII detection patterns, type inference, FK heuristics, business application keyword matching, schema evolution defaults. |
| `config/sample_cibil_feed.yaml` | DONE | Example input: 15-field CIBIL bureau feed for testing. |

### UI

| File | Status | Description |
|------|--------|-------------|
| `ui/app.py` | DONE | Chainlit conversational interface. Supports: paste YAML, full discovery, delta discovery, search glossary, approve suggestions, generate config. |

### Tests

| File | Status | Description |
|------|--------|-------------|
| `tests/test_discovery.py` | DONE & PASSING | End-to-end test: loads CIBIL sample, runs full discovery, prints results, generates config. Also tests delta discovery. |

### Documentation

| File | Status |
|------|--------|
| `DESIGN.md` | DONE — Full architecture, GCP service mapping, cost estimates, validation plan |
| `README.md` | DONE — Quick start, how it works, project structure |

---

## Test Results (Current — TF-IDF Fallback Embedder)

Running against CIBIL Bureau Feed (15 fields):

### High Confidence Matches (Correct)
- `customer_id` → Customer Identifier (95%) ✅
- `cibil_score` → Credit Score (95%) ✅
- `date_of_birth` → Date of Birth (95%) ✅
- `bureau_reference_id` → Bureau Reference (89%) ✅
- `email_address` → Customer Email (88%) ✅
- `mobile_number` → Customer Phone (65%) ✅
- `pan_number` → PAN Number (61%) ✅

### Correctly Identified
- PII fields: pan_number, mobile_number, email_address, date_of_birth ✅
- Business Application: Credit Risk & Lending ✅
- Primary Key: customer_id ✅
- New Term Proposed: credit_utilization_pct ✅

### Weak Matches (Need Better Embeddings or More Glossary Terms)
- `number_of_accounts` → Credit Score (42%) ❌ should be new term
- `account_type` → Country Code (49%) ❌ should be new term or "Account Type"
- `dpd_30_plus_count` → Country Code (44%) ❌ should be new term
- `score_date` → Order Date (62%) ⚠️ weak, should be "Score Date"
- `loan_amount_requested` → Transaction Amount (45%) ⚠️ close but should be "Loan Amount"

### Root Cause of Weak Matches
The TF-IDF character n-gram fallback embedder has limited semantic understanding. It matches based on character overlap, not meaning. Fix: use sentence-transformers or Vertex AI embeddings.

---

## What Needs To Be Done

### Priority 1: Enterprise-Scale Glossary

The current glossary has only 27 terms. A real bank needs 500-1000+ terms. Need to build:

**Business Applications (target: 20-30)**
- Retail Banking, Corporate Banking, Treasury, Wealth Management
- Credit Risk, Market Risk, Operational Risk, Fraud Detection
- Payments & Settlements, Cards & Acquiring
- Customer Onboarding, KYC/AML, Compliance & Regulatory
- Marketing & Campaigns, Digital Banking, Mobile Banking
- Lending (Secured/Unsecured), Collections & Recovery
- Insurance, Investments, Trade Finance

**Data Domains (target: 15-20)**
- Customer, Account, Transaction, Product, Channel
- Credit, Risk, Compliance, Document, Address
- Party, Instrument, Market Data, Reference Data
- Bureau, Payment, Loan, Card

**Business Terms (target: 500+)**
Per domain, need terms like:
- Customer: customer_id, name, dob, pan, aadhaar, email, phone, address, segment, risk_rating, kyc_status, occupation, income, nationality, gender, marital_status...
- Account: account_id, account_number, ifsc, branch, type, status, balance, opened_date, closed_date, dormant_flag...
- Transaction: txn_id, amount, date, type, channel, status, reference, narration, beneficiary, debit_credit_indicator...
- Credit/Bureau: cibil_score, credit_limit, utilization, dpd, npa_flag, loan_type, emi, tenure, collateral_value, ltv_ratio...
- Cards: card_number, expiry, cvv, card_type, billing_cycle, reward_points, transaction_limit...
- KYC/AML: kyc_status, risk_category, pep_flag, sanction_hit, source_of_funds, beneficial_owner...

**Reference Code Sets (target: 30-50)**
- Account types, transaction types, card types, loan types
- KYC statuses, risk ratings, NPA classifications
- Industry codes (NIC), occupation codes
- State codes, city codes, branch codes
- Currency codes, country codes

**Approach**: Create a Python generator script that builds the full glossary YAML programmatically. Can use banking domain knowledge + RBI/SEBI data standards as reference.

### Priority 2: Better Embeddings

Install sentence-transformers for immediate accuracy improvement:
```bash
pip install sentence-transformers
```

This alone will fix most of the weak matches above. The `all-MiniLM-L6-v2` model understands that "loan_amount_requested" is semantically close to "Loan Amount" even if the characters don't overlap perfectly.

For GCP deployment, switch to Vertex AI `text-embedding-005` (set `GCP_PROJECT_ID` env var).

### Priority 3: Confidence Thresholds & New Term Detection

Current threshold for "propose new term" is 0.4. With a richer glossary + better embeddings:
- Raise threshold to 0.6 or 0.7
- Fields like `number_of_accounts`, `dpd_30_plus_count` will correctly fall below threshold and be proposed as new terms
- Reduces false-positive matches

### Priority 4: Chainlit UI Polish

- Test the Chainlit UI end-to-end
- Add ability to edit suggestions before approval
- Add "create new term" flow directly in the UI (steward creates term, it goes into glossary)
- Show reasoning in a cleaner expandable format
- Add file upload support (drag & drop YAML/JSON)

### Priority 5: Glossary Persistence (Firestore)

Currently the glossary is YAML-only (reloads from file each time). For production:
- Move to Firestore (knowledge_graph.py already has the structure for this)
- When steward approves a new term, persist to Firestore
- Graph grows over time with each onboarding
- Support multi-user concurrent access

### Priority 6: Delta Discovery Integration with SchemaEvolver

Connect SD's delta discovery to the existing `schema_evolver.py`:
- When SchemaEvolver detects `add_column`, route through SD before allowing
- SD classifies the new column (PII? what term? what DQ?)
- Update the table YAML config with new field's metadata
- Then SchemaEvolver proceeds with the ALTER TABLE

### Priority 7: GCP Deployment

| Component | Target |
|-----------|--------|
| Knowledge Graph | Firestore |
| Embeddings | Vertex AI text-embedding-005 |
| Vector Search | Vertex AI Vector Search (Matching Engine) |
| API | Cloud Run (FastAPI) |
| UI | Cloud Run (Chainlit) |
| Orchestration | Cloud Composer (trigger SD on new catalog entry) |
| Audit | BigQuery `discovery_audit` dataset |

Terraform for all of the above to be added to `discovery/terraform/discovery.tf`.

### Priority 8: Validation & Accuracy Measurement

- Run SD against all existing `config/tables/*.yaml` files (customers, orders, products, payments, clickstream, transactions_stream)
- Measure: what % of the manually-written config does SD reproduce correctly?
- Target: 80%+ field-level accuracy
- Document accuracy per field type (Identifiers should be ~95%, Measures ~85%, References ~75%)

---

## File Structure (Final Target)

```
discovery/
├── config/
│   ├── rules.yaml                    # DONE
│   ├── seed_glossary.yaml            # DONE (minimal)
│   ├── enterprise_glossary.yaml      # TODO — 500+ terms
│   └── sample_cibil_feed.yaml        # DONE
├── engine/
│   ├── __init__.py                   # DONE
│   ├── knowledge_graph.py            # DONE
│   ├── rules_engine.py               # DONE
│   ├── embedder.py                   # DONE
│   ├── suggester.py                  # DONE
│   └── config_generator.py           # DONE
├── api/
│   ├── main.py                       # TODO — FastAPI for Cloud Run
│   ├── routes.py                     # TODO
│   └── Dockerfile                    # TODO
├── ui/
│   ├── .chainlit/config.toml         # DONE
│   └── app.py                        # DONE
├── terraform/
│   └── discovery.tf                  # TODO — Firestore, Vertex AI, Cloud Run
├── scripts/
│   └── generate_enterprise_glossary.py  # TODO — builds full glossary
├── tests/
│   ├── __init__.py                   # DONE
│   └── test_discovery.py             # DONE & PASSING
├── __init__.py                       # DONE
├── DESIGN.md                         # DONE
├── README.md                         # DONE
├── requirements.txt                  # DONE
├── start.bat                         # DONE
└── test.bat                          # DONE
```

---

## Cost Summary

| Phase | Monthly Cost | What You Get |
|-------|-------------|-------------|
| Local dev (now) | £0 | Engine works with TF-IDF fallback |
| With sentence-transformers | £0 | Much better accuracy, still local |
| GCP POC | ~£15-30/month | Vertex AI embeddings, Firestore, Cloud Run |
| GCP Production | ~£200-400/month | Vector Search, scaled, multi-user |

Your remaining credits (~₹28,600 / ~£270) cover the full POC and 2+ months of production easily.
