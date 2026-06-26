# Semantic Discovery — Complete Build Journal

## What This Is

A GCP-native replacement for Ab Initio's Semantic Discovery (SD) tool. SD accelerates data onboarding by automatically classifying fields, matching them to business terms, detecting PII, suggesting DQ rules, and generating pipeline configurations — all from a conversational interface.

Built as part of the `schema-evolution-gcp-native` project (bt_df_lkhouse_fw), integrated with Google's Knowledge Catalog (Dataplex).

**Live URL:** https://semantic-discovery-5uk6wi2iwq-nw.a.run.app
**Repo:** https://github.com/cprakash0105/bt-df-lkhouse-fw
**GCP Project:** bt-df-lkhouse
**Region:** europe-west2

---

## The Business Problem

When onboarding new data sources into an enterprise data platform, teams spend weeks manually:
- Classifying fields (what does each column mean?)
- Detecting PII (which fields need masking/governance?)
- Defining DQ rules (what validation should apply?)
- Mapping to business terms (what does the business call this?)
- Writing pipeline configs (how does the pipeline process this?)

Ab Initio's Semantic Discovery automates this but costs £500K-£1M/year in licensing. We built an equivalent using GCP services for ~£50-100/month.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SEMANTIC DISCOVERY (Cloud Run)                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  Chainlit UI (conversational interface)                                   │
│       │                                                                   │
│       ├── Natural Language Parser (Vertex AI Gemini)                      │
│       │   "I have a new CIBIL feed with customer_id, pan_number..."      │
│       │   → Extracts structured definition                                │
│       │                                                                   │
│       ├── Suggester (core orchestrator)                                   │
│       │   ├── Layer 1: Knowledge Graph (synonym match against Glossary)  │
│       │   ├── Layer 2: Rules Engine (deterministic patterns)             │
│       │   ├── Layer 3: Embedder (Vertex AI semantic similarity)          │
│       │   └── Layer 4: Profiler (sample data analysis) [built, not yet  │
│       │       integrated into Cloud Run]                                  │
│       │                                                                   │
│       └── Approval Handler (on "approve all")                            │
│           ├── Creates new BDE terms in Dataplex Glossary                 │
│           ├── Registers dataset entry in Dataplex Catalog                │
│           └── Pushes pipeline config YAML to GCS                         │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
         │                              │                        │
         ▼                              ▼                        ▼
┌─────────────────┐    ┌──────────────────────┐    ┌────────────────────┐
│ Dataplex Catalog │    │ Vertex AI            │    │ GCS Bucket         │
│ • Glossary (BDEs)│    │ • Embeddings         │    │ • Pipeline configs │
│ • Entry Types    │    │ • Gemini (NL parse)  │    │ • Landing data     │
│ • Entries (BA)   │    │                      │    │                    │
└─────────────────┘    └──────────────────────┘    └────────────────────┘
```

---

## What's in Dataplex Knowledge Catalog

### Glossary: `enterprise-data-glossary`
A flat dictionary of 26 Business Data Element (BDE) definitions. Each term has:
- Display Name (e.g., "Credit Score")
- Description with structured metadata:
  - Definition (human-readable)
  - Data Type (string, integer, decimal, date, timestamp)
  - Classification (PII, Sensitive, Internal)
  - DQ Rules (not_null, range, format, accepted_values)
  - Synonyms (alternative field names that map to this term)

Terms include: Customer Identifier, Customer Name, Customer Email, Customer Phone, Date of Birth, PAN Number, Aadhaar Number, Address, Account Identifier, Account Balance, Credit Score, Bureau Reference, Loan Amount, Transaction Amount, Transaction Date, Payment Method, Currency Code, Order Identifier, Order Status, Product Identifier, Product Name, KYC Status, Session Identifier, Event Timestamp, Country Code, Region.

### Entry Types (Custom)
- `cfu` — Customer Facing Unit
- `domain` — Business Domain
- `business-application` — Business Application
- `dataset` — Dataset registered via SD (auto-created on approval)

### Entry Group: `enterprise-hierarchy`
Contains the organisational structure:

**CFUs:**
- Consumer Banking
- Wholesale Banking

**Domains:**
- Credit, Customer Management, Payments, Digital Banking, Trade Finance

**Business Applications:**
- Loan Origination System (Owner: Credit Risk Team)
- Credit Bureau Integration (Owner: Bureau Data Team)
- Customer Relationship Management (Owner: Customer Data Team)
- KYC & Onboarding System (Owner: KYC Operations)
- Payments Hub (Owner: Payments Engineering)
- Mobile Banking Application (Owner: Digital Products Team)
- Trade Finance System (Owner: Trade Operations)

**Datasets (registered by SD on approval):**
- cibil_bureau_feed_from_transunion (linked to Credit Risk & Lending)

---

## Engine Components (Code)

### `discovery/engine/knowledge_graph.py`
- Loads business terms from local YAML (seed_glossary.yaml + banking catalog)
- Attempts to overlay with Dataplex Glossary on startup (graceful fallback)
- Provides synonym-based search for field → term matching
- Provides keyword-based search for business application suggestion

### `discovery/engine/rules_engine.py`
- Deterministic pattern matching (no ML needed)
- Naming rules: `*_id` → Identifier, `*_amt` → Measure, `*_date` → Temporal
- PII rules: `*email*`, `*phone*`, `*pan*`, `*aadhaar*`, `*name*`, `*addr*` → PII
- FK rules: `customer_id` → FK to customers table
- Business application rules: keyword matching against dataset/field names
- Schema evolution defaults: PII datasets get strict governance

### `discovery/engine/embedder.py`
- Hybrid embedder with 3 backends:
  1. **Vertex AI text-embedding-005** (GCP — best quality)
  2. **sentence-transformers** (local — good quality, needs PyTorch)
  3. **TF-IDF character n-grams** (zero-dependency fallback)
- Auto-detects best available backend
- Pre-computes embeddings for all glossary terms on startup
- Cosine similarity search for semantic field matching

### `discovery/engine/suggester.py`
- Core orchestrator combining all layers
- **Full Discovery mode**: new dataset, processes all fields
- **Delta Discovery mode**: existing dataset with schema changes, only processes changes
- Primary key detection: matches against asset name, prefers non-customer_id for non-customer tables
- Foreign key detection: heuristic based on `*_id` patterns
- Business application suggestion: keyword + KG matching
- New term proposal: when confidence < 0.4, proposes creating a new BDE

### `discovery/engine/nl_parser.py`
- Converts natural language to structured asset definition
- Uses Vertex AI Gemini 2.0 Flash for parsing
- Fallback: regex-based extraction of snake_case field names
- Example: "I have a new CIBIL feed with customer_id, pan_number, cibil_score" → `{"name": "cibil_feed", "fields": [...]}`

### `discovery/engine/approval_handler.py`
- Executes post-approval actions:
  1. Creates new BDE terms in Dataplex Glossary
  2. Registers dataset as a Custom Entry (type: `dataset`) in the hierarchy
  3. Pushes pipeline config YAML to GCS: `gs://bt-df-lkhouse-lakehouse/framework/config/tables/{name}.yaml`
- Uses BusinessGlossaryServiceClient for glossary operations
- Uses CatalogServiceClient for entry operations
- Uses google-cloud-storage for GCS writes

### `discovery/engine/config_generator.py`
- Converts approved suggestions into `config/tables/*.yaml` format
- Compatible with bt_df_lkhouse_fw pipeline (ingest.py, curate.py, consume.py)
- Includes: table name, source, primary_key, dedup_order, dq_rules, pii_fields, type_overrides, schema_evolution

### `discovery/engine/profiler.py`
- Analyses sample data (CSV, JSONL, pasted tabular)
- Per-column analysis: nulls, distinct count, cardinality ratio, type inference
- PII detection from VALUES (not just names): PAN regex, Aadhaar regex, email, phone, credit card
- Identifies PK candidates (high uniqueness + low nulls)
- Identifies reference/enum fields (low cardinality, <15 distinct values)
- Suggests DQ rules from data: range, accepted_values, format, positive
- 100MB / 10K row cap for Cloud Run
- **Status: Built but not yet deployed in the container (needs rebuild)**

### `discovery/engine/catalog_reader.py`
- Reads terms from Dataplex Glossary via BusinessGlossaryServiceClient
- Parses structured metadata from term descriptions
- Writes approved terms back to Dataplex
- Graceful fallback if Dataplex unavailable

### `discovery/ui/app.py`
- Chainlit conversational interface
- Commands: help, search, discover, approve all, approve (fields), generate, glossary, domains, applications, profile
- Accepts: YAML, JSON, natural language, CSV (file upload or pasted)
- Shows: field suggestions table, DQ rules, PII flags, business app, schema evolution governance, reasoning

---

## Configuration Files

### `discovery/config/seed_glossary.yaml`
- 27 business terms with full metadata (synonyms, types, PII flags, DQ rules)
- 6 business applications with keywords
- 6 data domains
- 7 reference code sets (loyalty tiers, regions, order statuses, channels, etc.)
- 5 data classifications (PII, PHI, Sensitive, Internal, Public)

### `discovery/config/rules.yaml`
- Naming rules (identifiers, temporal, measures, flags, references)
- PII rules (high/medium/low confidence patterns)
- Type rules (infer info type from data type)
- FK rules (pattern matching for foreign keys)
- Business application rules (keyword → app mapping)
- Schema evolution defaults (by classification level)

### `discovery/config/business_applications.yaml`
- 8 banking applications (CBS, Payments Hub, Card Management, LOS, LMS, CRM, AML, Risk Engine)
- From Copilot-generated banking catalog

### `discovery/config/business_glossary.yaml`
- 6 high-level business terms (Customer, KYC Status, Account, Balance, Transaction, Loan)

### `discovery/config/business_data_elements.yaml`
- 4 data elements mapped to business terms

### `discovery/config/dataset_definitions.yaml`
- 4 dataset definitions with source applications

### `discovery/config/governance_rules.yaml`
- 2 governance rules (txn_amount positive, customer_id not null)

### `discovery/config/enterprise_hierarchy.yaml`
- Full CFU → Domain → BA → BDE hierarchy (auto-generated by setup script)

### `discovery/config/sample_cibil_feed.yaml`
- Example input for testing: 15-field CIBIL bureau feed

---

## Scripts

### `discovery/scripts/setup_glossary.py`
- Creates the Dataplex glossary with 26 BDE terms
- Each term has structured description (definition, type, classification, DQ, synonyms)
- Uses BusinessGlossaryServiceClient
- Idempotent (skips existing terms)

### `discovery/scripts/setup_hierarchy.py`
- Prints the CFU → Domain → BA hierarchy
- Exports to `config/enterprise_hierarchy.yaml`
- Entry types and entries created separately (see below)

### `discovery/scripts/import_to_dataplex.py`
- Original import script (deprecated — use setup_glossary.py instead)
- Had multiple API issues (documented below)

---

## Deployment

### Dockerfile (`Dockerfile.discovery`)
```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install pyyaml numpy chainlit google-cloud-aiplatform google-cloud-firestore
    google-cloud-storage google-cloud-dataplex vertexai
COPY discovery/ /app/discovery/
EXPOSE 8000
CMD ["chainlit", "run", "discovery/ui/app.py", "--port", "8000", "--host", "0.0.0.0"]
```

### Cloud Build (`cloudbuild.yaml`)
- Builds Docker image → pushes to Artifact Registry → deploys to Cloud Run
- Tag: `v1` (static, for manual builds)
- Substitutions: `_REGION=europe-west2`, `_TAG=v1`

### Deploy command (Cloud Shell):
```bash
cd ~/bt-df-lkhouse-fw
git pull
gcloud builds submit --config=cloudbuild.yaml --project=bt-df-lkhouse
```

### Cloud Run Service
- Name: `semantic-discovery`
- Region: `europe-west2`
- Image: `europe-west2-docker.pkg.dev/bt-df-lkhouse/semantic-discovery/ui:v1`
- Service Account: `978009776592-compute@developer.gserviceaccount.com` (default compute)
- Memory: 512Mi, CPU: 1
- Min instances: 0, Max: 2
- Public access: enabled (allUsers → roles/run.invoker)
- Env vars: GCP_PROJECT_ID=bt-df-lkhouse, GCP_REGION=europe-west2, EMBEDDER_MODE=vertex

### IAM Permissions Required
- `978009776592-compute@developer.gserviceaccount.com` needs:
  - `roles/dataplex.admin` (glossary + catalog operations)
  - `roles/storage.objectAdmin` (push configs to GCS) — likely already has via default compute SA
  - `roles/aiplatform.user` (Vertex AI embeddings + Gemini)

---

## Dataplex API Learnings (Issues We Hit)

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| `CatalogServiceClient has no attribute create_glossary` | Wrong client | Use `BusinessGlossaryServiceClient` |
| `Unknown field: glossary_category` | Wrong field name in request | Use `category` and `category_id` |
| `Unknown field: glossary_term` | Wrong field name | Use `term` and `term_id` |
| `Category.parent field should be...` | Empty parent on proto object | Set `parent=glossary_name` on GlossaryCategory object |
| `Unknown field for GlossaryCategory: result` | `.result()` on non-operation | `create_glossary_category` returns directly, not an operation |
| `Malformed collection name: glossaries/categories/terms` | Terms cannot be nested under categories | Terms go flat under glossary only. Categories are separate groupings. |
| `Glossary with children can't be deleted` | Must delete terms/categories first | Delete terms, then categories, then glossary |
| `Entry FQN invalid` | Wrong FQN format | Must be `system:path` format, e.g., `custom:dataset/name` |
| `Failed to link to BA` (from Cloud Run) | `google-cloud-dataplex` not in Dockerfile | Added to Dockerfile, rebuild required |
| `create_glossary` returns operation | Different from category/term | Use `op.result()` for glossary creation |

---

## Validation Results (Local — TF-IDF Fallback)

Ran against 6 scenarios + delta discovery:

| Metric | Result |
|--------|--------|
| Overall accuracy | **94%** (16/17 checks) |
| PII detection | **100%** (zero missed) |
| Primary key detection | **100%** |
| Business application | **83%** (1 borderline case) |
| New term proposals | **100%** |
| Delta discovery | **100%** |

With Vertex AI embeddings (production), accuracy is higher for semantic matching.

---

## Full Approval Flow (What Happens on "approve all")

```
1. Config YAML generated from suggestions
2. New BDE terms created in Dataplex Glossary (if any proposed)
3. Dataset entry registered in Dataplex Catalog (type: dataset, linked to BA)
4. Config YAML pushed to gs://bt-df-lkhouse-lakehouse/framework/config/tables/{name}.yaml
5. Summary displayed to steward
```

The pipeline (bt_df_lkhouse_fw) can then:
- Pick up the new config from GCS
- Run: Landing → Reservoir → CCN (Iceberg) → Data Product (BigQuery)
- SchemaEvolver enforces the governance rules from the config

---

## Known Issues / Things to Fix

| Issue | Severity | Notes |
|-------|----------|-------|
| `enquiry_date` flagged as PII | Low | Rules engine `*date*` pattern too broad. Should exclude `*_date` suffix. |
| Dataset name from NL includes "from_transunion" | Low | Gemini extracts too much. Could post-process to trim source system names. |
| Terms can't be nested under categories in Dataplex | Design | Dataplex limitation. Categories are visual groupings only, terms are flat. |
| Profiler not yet in deployed container | Medium | Code exists, integrated in UI, needs rebuild to test on Cloud Run. |
| No GCS-based profiling yet | Low | Currently only supports pasted/uploaded CSV. GCS path support is TODO. |
| Dataplex read-back on startup | Low | KnowledgeGraph tries to read from Dataplex but may silently fall back to YAML if client not configured. |

---

## What's Next (Prioritised)

### 1. Data Profiling (Cloud Run)
- Already built (`profiler.py`) and integrated in UI
- Needs rebuild to deploy
- Allows: paste CSV, upload file → SD profiles values → better PII detection + DQ suggestions
- Key value: detects PII from VALUES even when field names are cryptic

### 2. Pipeline ↔ Catalog Connection
- After pipeline runs and creates physical table in BigQuery/Iceberg
- Post-pipeline step tags physical columns with their BDE glossary terms
- Completes the TDE → BDE linking in Dataplex
- Enables full lineage: Source → Landing → CCN → Data Product → Consumer

### 3. Enterprise Glossary Expansion
- Current: 26 terms
- Target: 200+ terms covering all banking domains
- More terms = better matching accuracy = fewer "NEW TERM" proposals
- Can be done incrementally as stewards approve discoveries (learning loop)

### 4. PII Rule Tuning
- Fix `*date*` false positive (exclude `_date` suffix from PII patterns)
- Add more PII patterns: IFSC codes, VPA (UPI), etc.
- Consider confidence thresholds per pattern

### 5. React UI (Future)
- Chainlit works for POC but limited for multi-persona use
- React UI with: dashboard view, approval workflows, glossary browser, lineage viz
- Chainlit stays as the "quick interaction" mode

---

## Cost (Actual — First Month)

| Service | Usage | Cost |
|---------|-------|------|
| Cloud Run (SD) | ~50 requests | < ₹10 |
| Vertex AI Embeddings | ~500 embeddings | < ₹5 |
| Vertex AI Gemini | ~20 NL parses | < ₹5 |
| Cloud Build | 5 builds | < ₹10 |
| Artifact Registry | 1 image | < ₹5 |
| Dataplex Catalog | Glossary + entries | Free |
| GCS | Config files | < ₹1 |
| **Total** | | **< ₹40 (~$0.50)** |

Well within the ₹28,600 remaining credits (valid till Sep 13, 2026).

---

## How to Resume Work

1. Open Cloud Shell: https://shell.cloud.google.com
2. `cd ~/bt-df-lkhouse-fw && git pull`
3. Make changes locally (this machine) or in Cloud Shell
4. Push: `git push` (Cloud Shell) or via PAT (local)
5. Rebuild: `gcloud builds submit --config=cloudbuild.yaml --project=bt-df-lkhouse`
6. Test: https://semantic-discovery-5uk6wi2iwq-nw.a.run.app

Local testing (no cloud needed):
```bash
cd schema-evolution-gcp-native
python -m discovery.tests.test_discovery
python -m discovery.tests.validate_all
```
