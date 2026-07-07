# Ontika — LLM Migration & Fix Log

## Date: July 2026

## Context
- Azure trial expired → Ollama on Azure VM (`4.242.19.167:11434`) dead
- EC2 Ollama attempt failed (segfault — CPU architecture incompatibility with AVX)
- Migrated to **AWS Bedrock Mantle** (`openai.gpt-oss-120b` — 120B parameter reasoning model)
- Cost: ~$3-5/month ($0.15/1M input, $0.60/1M output tokens)

---

## 1. LLM Client Migration (Bedrock Mantle)

**File:** `discovery/engine/llm_client.py`

- Rewrote from Ollama to Bedrock Mantle OpenAI-compatible endpoint
- Endpoint: `https://bedrock-mantle.eu-north-1.api.aws/v1`
- Model: `openai.gpt-oss-120b`
- Auth: Bearer token (API key from Bedrock console)
- **Key behavior:** This is a reasoning model — responses come in `reasoning` field when `content` is null. Client falls back: `content` → `reasoning` → empty string
- Needs sufficient `max_tokens` (≥150 for simple tasks, ≥500 for complex)
- Loads config from `.env` via `python-dotenv`

**File:** `discovery/.env`
```
LLM_PROVIDER=bedrock
LLM_MODEL=openai.gpt-oss-120b
LLM_BASE_URL=https://bedrock-mantle.eu-north-1.api.aws/v1
LLM_API_KEY=<bedrock-api-key>
LLM_PROJECT=default
AWS_REGION=eu-north-1
```

---

## 2. Embedder Migration

**File:** `discovery/engine/rag/embedder.py`

- Rewrote from Ollama to Bedrock Mantle `/embeddings` endpoint
- Model: `amazon.titan-embed-text-v2:0`
- Has hash-based TF-IDF fallback if Bedrock unavailable (zero-dependency)

---

## 3. Cloud Run Deployment (Secret Manager)

**File:** `cloudbuild-web.yaml`

- Uses `--set-secrets="LLM_API_KEY=bedrock-api-key:latest"` from GCP Secret Manager
- Env vars set via `--set-env-vars` (LLM_PROVIDER, LLM_BASE_URL, LLM_MODEL, etc.)
- Secret `bedrock-api-key` created in GCP Secret Manager (project `bt-df-lkhouse`)
- Service account `978009776592-compute@developer.gserviceaccount.com` granted `roles/secretmanager.secretAccessor`

**Deploy command:**
```bash
gcloud secrets add-iam-policy-binding bedrock-api-key \
  --member="serviceAccount:978009776592-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --project=bt-df-lkhouse

gcloud run services update sd-web \
  --region=europe-west2 \
  --project=bt-df-lkhouse \
  --set-env-vars="LLM_PROVIDER=bedrock,LLM_BASE_URL=https://bedrock-mantle.eu-north-1.api.aws/v1,LLM_MODEL=openai.gpt-oss-120b,LLM_PROJECT=default,AWS_REGION=eu-north-1,CONFIG_BUCKET=eastside-lakehouse" \
  --set-secrets="LLM_API_KEY=bedrock-api-key:latest"
```

---

## 4. LLM-First Classification (Replacing Keyword Matching)

**File:** `discovery/engine/suggester.py`

### Problem
- `_suggest_business_application()` and `_suggest_domain()` used pure keyword matching against `seed_glossary.yaml`
- `pos_transactions` matched "Billing & Finance" because keywords like `amount`, `payment` scored higher than anything retail
- Every new client/domain required manual glossary edits

### Fix
- Added `_llm_classify()` method — asks LLM to classify dataset into BA + domain given field names and available options
- `_suggest_business_application()` now calls LLM first, falls back to keyword matching only if LLM unavailable
- `_suggest_domain()` uses LLM hint from classification call
- LLM correctly returns `{"business_application": "retail_commerce", "data_domain": "retail"}` for pos_transactions

### Prompt used:
```
Dataset: {asset_name}
Fields: {field_names}

Available business applications:
{apps list}

Available data domains:
{domains list}

Pick the best business_application and data_domain for this dataset.
If none fit well, suggest a new one.
Return ONLY JSON: {"business_application": "id", "data_domain": "id"}
```

---

## 5. Seed Glossary — Retail Domain Added

**File:** `discovery/config/seed_glossary.yaml`

Added (no longer the authority for classification, but still useful for field-level BDE matching):

- **Business Application:** `retail_commerce` — "Retail & Commerce" with keywords: pos, transaction, retail, store, shop, purchase, sale, basket, receipt, till, checkout, online, ecommerce, apparel, fashion, etc.
- **Data Domain:** `retail` — "Retail & Sales"
- **Business Terms:** transaction_id, store_id, quantity, discount_amount, return_reason
- **Reference Code Set:** return_reasons: [wrong_size, defective, not_as_described, changed_mind, too_late, duplicate_order]

---

## 6. `/ask` Endpoint — MCP Agent Bypass

**File:** `discovery/api/main.py`

### Problem
- `/ask` endpoint used MCP agent first → huge system prompt (tool descriptions + RAG context)
- Reasoning model spent all tokens on `reasoning` field, `content` came back null
- MCP agent returned: "I'm unable to process that right now. The LLM service is unavailable."

### Fix
- `/ask` now uses **direct LLM call first** (small system prompt with just domains/apps list)
- Falls back to KC agent (rule-based) if LLM fails
- MCP agent still available for complex tool-calling via other routes, but NOT for simple Q&A

### New flow:
```
/ask → Direct LLM (small prompt, max_tokens=500) → KC Agent → 503
```

### Old flow (broken):
```
/ask → MCP Agent (huge prompt, tool calling) → RAG → KC Agent → 503
```

---

## 7. Frontend Fixes

**File:** `discovery/web/src/App.jsx`

- Added retail entities to `knownEntities` list: 'retail', 'commerce', 'pos', 'online orders', 'returns', 'inventory'
- Improved `_askLLM()` error handling: specific message for 503/unavailable errors with helpful suggestions
- Improved `_answerGlossaryQuestion()` error handling: same 503 treatment

---

## 8. Git Commits

```
cea8ca7 fix: add retail entities to UI, improve LLM error messages
ff68725 fix: /ask uses direct LLM first, skip MCP agent for simple questions
3f59d30 feat: LLM-first classification for BA/domain, remove keyword-only dependency
6abd427 fix: add retail domain/app to glossary, LLM fallback for /ask endpoint
8339183 fix: use Secret Manager for Bedrock API key instead of substitution
0d63c51 feat: migrate LLM from Azure Ollama to AWS Bedrock Mantle
```

---

## 9. Key Learnings — Reasoning Models

`openai.gpt-oss-120b` is a **reasoning model**. Key behaviors:

1. **`reasoning` vs `content` fields:** The model thinks in `reasoning` and answers in `content`. With low `max_tokens`, it spends everything on reasoning and `content` stays null.
2. **Minimum tokens:** Use ≥150 for simple classification, ≥500 for Q&A, ≥1024 for code/config generation.
3. **System prompt size matters:** Large system prompts (like MCP agent's tool descriptions) cause the model to reason extensively about what tools to use, consuming tokens before producing content.
4. **Temperature 0.0 works well** for classification/extraction tasks.
5. **JSON output:** The model reliably produces JSON when instructed, but wrap in try/except for safety.

---

## 10. Architecture After Fix

```
User (Ontika UI)
    │
    ├── "Onboard pos_transactions"
    │       → /discover → _resolve_from_text() → GCS landing schema
    │       → suggester.full_discovery()
    │           → _llm_classify() → LLM determines BA + domain
    │           → _process_field() → KG + Rules + Embeddings
    │           → LLMReviewer → validates/corrects suggestions
    │       → Response to UI
    │
    ├── "approve"
    │       → /approve → config_gen + approval_handler
    │       → Push config to GCS, create BDEs, link BA
    │
    ├── "why is it linked to Retail & Commerce?"
    │       → _isGlossaryQuestion() → true (has "linked")
    │       → api.askCatalog() → /ask
    │       → Direct LLM call (small prompt) → answer
    │
    └── "Create data product customer_value_score..."
            → /generate/sql → SQLGenerator → LLM
```

---

## 11. Pending / Future

- **RAG:** ChromaDB index not built on Cloud Run yet. Once built, `/ask` can use RAG for richer context.
- **MCP Agent:** Still available but not used for simple Q&A. Could be exposed via a separate `/agent` endpoint for complex multi-step operations.
- **Glossary growth:** As stewards approve discoveries, new BDEs are added to the glossary automatically. LLM classification improves as more context is available.
- **Profiler Service:** `PROFILER_SERVICE_URL` points to Dataproc cluster (`lakehouse-cluster`). Not always running — profiling falls back to local lightweight profiler.

---

## 12. How to Redeploy

```bash
# From GCP Cloud Shell
cd ~/bt-df-lkhouse-fw
git pull
gcloud builds submit --config cloudbuild-web.yaml --project bt-df-lkhouse
```

Service URL: `https://sd-web-978009776592.europe-west2.run.app`

---

## 13. How to Test LLM Locally

```bash
curl -s -X POST "https://bedrock-mantle.eu-north-1.api.aws/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <API_KEY>" \
  -H "OpenAI-Project: default" \
  -d '{"model":"openai.gpt-oss-120b","messages":[{"role":"user","content":"Say hello"}],"max_tokens":300}'
```

Expected: `{"content":"Hello! 👋","reasoning":"...thinking..."}` with `finish_reason: "stop"`

If `content` is null and `finish_reason` is "length" → increase `max_tokens`.

---

## 14. AWS Credentials

- **Account:** 241490787771 (Chandra Prakash)
- **Region:** eu-north-1 (Stockholm)
- **Bedrock API Key:** Starts with `ABSKTW...`, stored in GCP Secret Manager as `bedrock-api-key`
- **Local AWS config:** `C:\Users\615570417\.aws\credentials` and `config` (UTF-8, not UTF-16)

## 15. GCP Details

- **Project:** `bt-df-lkhouse` (ID: 978009776592)
- **Region:** europe-west2
- **Bucket:** `eastside-lakehouse`
- **Cloud Run:** `sd-web` at `https://sd-web-978009776592.europe-west2.run.app`
- **GitHub:** `cprakash0105/bt-df-lkhouse-fw`
- **Dataproc:** `lakehouse-cluster` (not always running)
