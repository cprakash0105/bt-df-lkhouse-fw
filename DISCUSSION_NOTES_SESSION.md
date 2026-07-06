# Discussion Notes — Session Continuation Points

## Date: June 29, 2026

---

## 1. Amanda's Feedback (from GCP Native Discussion.vtt)

### Key Points from the Demo Call:

1. **Data sharing with LLM concern:**
   - Amanda worried about sharing actual data with LLM
   - Resolution: Only schema + profile info (patterns, ranges, top values) goes to LLM
   - Never record-level data
   - Self-hosted LLM (Gemma2 on Azure VM) — data doesn't leave our boundary

2. **DQ rules are too technical:**
   - Amanda noticed SD only suggests "not null" type rules
   - She wants BUSINESS-level DQ rules defined at the business term level
   - Rules should INHERIT downward to all TDEs using that BDE
   - Quote: "Define at conceptual level, push down — a handful of rules, not thousands"
   - Referenced how Ab Initio does it

3. **Knowledge Catalog limitations:**
   - Hierarchy doesn't show well in KC UI
   - `related` EntryLinks don't render visually
   - Only `definition` links show (BA → BDE as "Glossary Terms")
   - Acknowledged as a GCP limitation

4. **Schema evolution:** Confirmed working, Amanda satisfied

5. **SCD Types 1-6:** Noted as implemented

6. **Action items from Amanda:**
   - Create a presentation about the framework
   - Focus on what the framework does and how it's configured
   - Consider extending to include business-level DQ capabilities
   - Mentioned Great Expectations as a tool

7. **Chainlit UI:** Will change to React — Amanda agreed it's basic

---

## 2. DQ Inheritance Engine (BUILT & PUSHED)

### What Was Built:
- File: `discovery/engine/dq_inheritance.py`
- Integrated into: `discovery/engine/config_generator.py`

### How It Works:
```
Glossary BDE "Credit Score" → DQ: range [300, 900], not_null
    ↓ automatically applied to ALL tables using "Credit Score"
    → cibil_bureau_feed.cibil_score
    → credit_risk_model.bureau_score  
    → loan_eligibility.score
= 1 rule defined, applied everywhere
```

### Implementation:
- `DQInheritanceEngine` reads BDE definitions from glossary
- Each BDE has: dq_rules, classification, is_pii, reference_code_set, pattern
- When config generator runs, it calls `enrich_from_suggestion()`
- For each field matched to a BDE (confidence >= 0.5), inherits that BDE's DQ rules
- Merges with any field-level rules (field rules override BDE rules)

### What Gets Inherited:
- not_null (from BDE definition)
- positive (from BDE definition)
- unique (from BDE definition)
- range (from BDE definition, e.g., Credit Score [300, 900])
- format (from BDE pattern, e.g., PAN regex)
- accepted_values (from BDE reference_code_set)

### This Addresses Amanda's Feedback:
- Define DQ at business term level ✅
- Push down to all technical elements ✅
- Handful of rules, not thousands ✅

---

## 3. GE Profiling + LLM Plan (NOT YET BUILT)

### Proposed Architecture:
```
Data lands in Reservoir (Parquet)
        │
        ▼
Great Expectations profiles the data:
  - Value distributions
  - Null percentages
  - Cardinality
  - Min/max/mean
  - Pattern frequencies (regex matching)
  - Outlier detection
  - Uniqueness ratios
        │
        ▼
Profile summary (NOT raw data) sent to LLM:
  "Column 'cibil_score': integer, min=302, max=898, mean=701, 
   null_pct=0.1%, distinct=587, distribution=normal"
        │
        ▼
LLM generates:
  1. BDE definition: "Credit Score - score from bureau, range 300-900"
  2. DQ rules: range [300,900], not_null, positive
  3. BA suggestion: "Credit Risk & Lending"
  4. Business classification: "Sensitive" (financial score)
  5. SCD recommendation: Type 3 (track previous score)
```

### Why This Is Better:
- GE does the heavy lifting (statistical analysis) — deterministic, proven
- LLM only does reasoning (what does this pattern MEAN?) — semantic, contextual
- No raw data shared with LLM — only statistical summaries
- Addresses Amanda's concern about data sharing
- Generates BUSINESS-level rules, not just technical ones

### Implementation Plan:
1. Add `great_expectations` to requirements
2. Create `discovery/engine/ge_profiler.py` — runs GE on reservoir parquet
3. Create `discovery/engine/profile_to_llm.py` — formats GE output into compact LLM prompt
4. LLM returns structured JSON: {bde_name, bde_definition, dq_rules, classification, scd_type}
5. Integrate into the Cloud Function pipeline (run after ingest, before curate)

### Where It Runs:
- Option A: In the Cloud Function (Python, in-memory) — for small datasets
- Option B: On Dataproc cluster (Spark + GE) — for large datasets
- Option C: As a separate Cloud Function triggered after ingest completes

### Token Optimization for LLM:
- Send only: column_name, inferred_type, null_pct, distinct_count, min, max, mean, top_5_values, pattern_matches
- One prompt per dataset (not per column)
- ~200-500 tokens input per dataset
- ~500-1000 tokens output

---

## 4. Pending Items (From This Session)

### Immediate (before next demo):
- [ ] Deploy DQ inheritance (rebuild SD container)
- [ ] Fix loan_repayment_schedule (DQ accepted_values issue)
- [ ] Onboard customer_complaints successfully
- [ ] Generate insurance data and onboard at least motor_policy

### Short-term:
- [ ] Build GE profiling integration
- [ ] Multi-feed onboarding (one prompt for entire domain)
- [ ] Conversational corrections in SD ("due_date is not PII")
- [ ] Fix NL parser — single-word fields (channel, category, status) not parsed
- [ ] Fix dataset naming — NL parser adds "feed" to names inconsistently
- [ ] Link newly created BDEs to BA on approval (currently skipped for new terms)

### Medium-term:
- [ ] React UI (replace Chainlit)
- [ ] Presentation for Amanda
- [ ] Great Expectations integration
- [ ] Domain auto-creation on onboarding
- [ ] KC lineage visualization (needs OpenLineage or custom)

---

## 5. Current SD Issues (To Fix)

### NL Parser Issues:
1. Single-word fields not parsed by local fallback (channel, category, status, priority)
   - Cause: Local parser only looks for snake_case words (with underscores)
   - Fix: Also match words that appear after "with" in a comma-separated list

2. Dataset name inconsistency — sometimes adds "feed" suffix
   - Cause: LLM interprets "new X feed" and includes "feed" in the name
   - Fix: Post-process to strip common suffixes, or validate against landing folder names

3. LLM reviewer not catching all errors
   - Cause: Gemma2 on 4-core CPU is slow (~90s) and sometimes returns empty corrections
   - Fix: Improve prompt, or run reviewer only for specific fields (accepted_values, PII)

### DQ Issues:
1. `accepted_values` from wrong glossary term (order statuses applied to payment statuses)
   - NOW FIXED by: LLM reviewer + DQ inheritance from correct BDE
   - Fallback: Don't generate accepted_values unless profiler confirms actual values

2. `customer_id: unique` incorrectly set on non-customer tables
   - Fix: Only set unique if it's the primary key

3. `csat_score` matched to "Credit Score" (range [300, 900] wrong)
   - Fix: LLM reviewer should catch this. Also, add "CSAT Score" as a BDE with range [1, 5]

### EntryLinks Issues:
1. Newly created BDEs not linked to BA/dataset on approval
   - Cause: `field.linked_term` is None for new terms (not yet in glossary)
   - Fix: After creating the BDE term, use the new term's ID to create the EntryLink

---

## 6. Architecture Decisions Made

| Decision | Choice | Reason |
|----------|--------|--------|
| LLM hosting | Azure VM (Ollama + Gemma2 9B) | GCP trial can't run GPU VMs, Gemini has rate limits |
| Dataproc mode | Dedicated cluster (not Serverless) | Quota issues with Serverless on trial |
| DQ approach | BDE-level inheritance | Amanda's feedback — define once, apply everywhere |
| Data profiling | SD profiler (built-in) + GE (planned) | Don't share raw data with LLM |
| KC hierarchy | EntryLinks (definition type) | Only type KC renders visually |
| Pipeline automation | Cloud Function (GCS event trigger) | Cheapest, event-driven, no polling |
| SCD | Config-driven YAML | Steward declares intent, framework handles logic |
| Data masking | Policy Tags (needs BQ Enterprise) | Single table, role-based access |
| Contracts | Auto-generated on approval | Every dataset gets a contract — no exceptions |

---

## 7. Current Infrastructure State

| Component | Status | Location |
|-----------|--------|----------|
| SD (Cloud Run) | ✅ Running | https://semantic-discovery-978009776592.europe-west2.run.app |
| LLM (Azure VM) | ✅ Running | http://4.242.19.167:11434 (Gemma2 9B) |
| Dataproc Cluster | ✅ Running | lakehouse-cluster (europe-west2) |
| Cloud Function | ✅ Deployed | pipeline-orchestrator |
| Dataplex Glossary | ✅ 26+ BDEs | enterprise-data-glossary |
| Dataplex Hierarchy | ✅ Linked | 7 Domain→BA + 32 BA→BDE links |
| BigQuery | ✅ Data loaded | cibil, ekyc, upi + SCD dimensions |
| GCS Bucket | ✅ All layers | landing, reservoir, ccn, contracts, configs |

### Cost Warning:
- Azure VM: ~$5/day (stop when not using: `az vm deallocate --resource-group llm-server-rg --name llm-server`)
- Dataproc cluster: ~$3/day (stop: `gcloud dataproc clusters stop lakehouse-cluster --region=europe-west2`)
- Cloud Run: scales to zero (free when idle)
- Cloud Function: free tier

### Stop Everything:
```bash
# Azure VM
az vm deallocate --resource-group llm-server-rg --name llm-server

# Dataproc
gcloud dataproc clusters stop lakehouse-cluster --region=europe-west2 --project=bt-df-lkhouse
```

### Start Everything:
```bash
# Azure VM
az vm start --resource-group llm-server-rg --name llm-server

# Dataproc
gcloud dataproc clusters start lakehouse-cluster --region=europe-west2 --project=bt-df-lkhouse

# Verify LLM is up (IP might change after restart)
az vm show --resource-group llm-server-rg --name llm-server --show-details --query publicIps --output tsv
# Then update SD if IP changed:
gcloud run services update semantic-discovery --region=europe-west2 --project=bt-df-lkhouse --update-env-vars="LLM_BASE_URL=http://<NEW_IP>:11434/v1"
```

---

## 8. Files Modified This Session

| File | Change |
|------|--------|
| `discovery/engine/dq_inheritance.py` | NEW — BDE-level DQ rule inheritance |
| `discovery/engine/config_generator.py` | Updated — integrates DQ inheritance |
| `discovery/engine/scd_config_generator.py` | NEW — auto-generates SCD configs from business intent |
| `discovery/engine/llm_reviewer.py` | NEW — validates/corrects SD suggestions per dataset |
| `discovery/scripts/link_catalog.py` | Updated — added CFU→Domain links, fixed underscore/hyphen |
| `bt_df_lkhouse_fw/config/consumption/scd_onboarded.yaml` | NEW — SCD configs for loaded datasets |
| `bt_df_lkhouse_fw/engine/scd.py` | Fixed — prev_/current_ column types inherit from source |
| `datagen/generate_insurance.py` | NEW — 4 insurance feeds (3400 records) |
| `functions/main.py` | Updated — record counts, column security |
| `functions/monitor.py` | Updated — counts after ingest/curate |
| `Dockerfile.discovery` | Fixed — removed chainlit config, removed google-generativeai |
| `WHITE_PAPER.md` | NEW — full white paper with ASCII diagrams |
| `VALIDATION_RUNDOWN.md` | NEW — 10 validation tests |
| `discovery/KC_DESIGN_UPDATE.md` | NEW — KC limitations and recommendations |

---

## 9. For Next Session — Priority Order

1. **Build GE profiling** → LLM generates business DQ rules from statistical profiles
2. **Fix NL parser** → handle single-word fields, fix naming
3. **Multi-feed onboarding** → one prompt for entire domain (Insurance use case)
4. **Conversational corrections** → "due_date is not PII" updates suggestions
5. **Presentation** → for Amanda, framework overview + demo script
6. **React UI** → replace Chainlit
