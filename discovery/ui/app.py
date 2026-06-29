"""Semantic Discovery — Chainlit Interactive UI.
Data stewards interact conversationally to discover, classify, and onboard data assets."""
import sys
import json
import re
import yaml
import chainlit as cl
from pathlib import Path
from typing import Optional

# Ensure discovery package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from discovery.engine.knowledge_graph import KnowledgeGraph
from discovery.engine.rules_engine import RulesEngine
from discovery.engine.embedder import Embedder
from discovery.engine.suggester import Suggester, DiscoverySuggestion
from discovery.engine.config_generator import ConfigGenerator
from discovery.engine.nl_parser import NLParser
from discovery.engine.approval_handler import ApprovalHandler
from discovery.engine.profiler import Profiler, format_profile_report
from discovery.engine.sql_generator import SQLGenerator
from discovery.engine.contract_generator import ContractGenerator
from discovery.engine.scd_config_generator import SCDConfigGenerator

# Try to import GE profiler (optional — needs great_expectations + pandas)
try:
    from discovery.engine.ge_profiler import GEProfiler, format_ge_profile_report
    from discovery.engine.llm_dq_generator import LLMDQGenerator
    GE_AVAILABLE = True
except ImportError:
    GE_AVAILABLE = False

# Initialize engine components
kg = KnowledgeGraph()
rules = RulesEngine()
embedder = Embedder(mode="local")
suggester = Suggester(knowledge_graph=kg, rules_engine=rules, embedder=embedder)
config_gen = ConfigGenerator()
nl_parser = NLParser()
approval_handler = ApprovalHandler()
profiler = Profiler()
sql_gen = SQLGenerator()
contract_gen = ContractGenerator()
scd_gen = SCDConfigGenerator()


WELCOME_MESSAGE = """
# 🔍 Semantic Discovery

Welcome! I help you **discover, classify, and onboard** data assets into the Data Fabric.

## What I can do:

1. **Full Discovery** — Analyse a new dataset definition and suggest:
   - Business Application & Domain
   - Business Term linkages for each field
   - PII/Sensitivity classification
   - Data Quality rules
   - Primary/Foreign key candidates
   - Schema evolution governance

2. **Delta Discovery** — Analyse schema changes on an existing dataset

3. **Search Glossary** — Find existing business terms

4. **Generate Config** — Create pipeline-ready YAML after you approve suggestions

## How to start:

- **Paste a YAML/JSON** with your asset definition (field names + types)
- Or type: `discover <asset_name>` and I'll ask for the fields
- Or type: `search <term>` to browse the glossary
- Or type: `help` for more options

---
*Example asset definition:*
```yaml
name: cibil_bureau_feed
fields:
  - name: customer_id
    type: string
  - name: pan_number
    type: string
  - name: cibil_score
    type: integer
  - name: enquiry_date
    type: date
  - name: loan_amount
    type: decimal
```
"""


@cl.on_chat_start
async def start():
    cl.user_session.set("current_suggestion", None)
    await cl.Message(content=WELCOME_MESSAGE).send()


@cl.on_message
async def handle_message(message: cl.Message):
    text = message.content.strip()

    # Check for file uploads
    if message.elements:
        for element in message.elements:
            if element.path:
                if element.path.endswith(".yaml") or element.path.endswith(".yml") or element.path.endswith(".json"):
                    content = Path(element.path).read_text(encoding="utf-8")
                    await _run_discovery(content)
                    return
                elif element.path.endswith(".csv"):
                    content = Path(element.path).read_text(encoding="utf-8")
                    await _profile_and_discover(content, "csv")
                    return

    # Command routing
    lower = text.lower()
    if lower.startswith("help"):
        await _show_help()
    elif lower.startswith("search "):
        query = text[7:].strip()
        await _search_glossary(query)
    elif lower.startswith("ge profile") or lower.startswith("ge_profile"):
        remainder = text[10:].strip() if lower.startswith("ge profile") else text[11:].strip()
        await _ge_profile(remainder)
    elif lower.startswith("profile"):
        # Format: "profile <dataset_name>\n<csv_data>" or just "profile\n<csv_data>"
        remainder = text[7:].strip()
        lines = remainder.split("\n", 1)
        dataset_name = None
        data = ""

        if len(lines) >= 2:
            first_line = lines[0].strip()
            # If first line doesn't contain commas, it's the dataset name
            if "," not in first_line and first_line:
                dataset_name = first_line.replace(" ", "_").lower()
                data = lines[1].strip()
            else:
                # First line IS the CSV header
                data = remainder
        elif len(lines) == 1 and "," in lines[0]:
            data = remainder

        if data:
            await _profile_and_discover(data, "csv", dataset_name=dataset_name)
        else:
            await cl.Message(content="""Usage:
```
profile <dataset_name>
<csv data with headers>
```

Example:
```
profile cibil_bureau_feed
customer_id,pan_number,cibil_score,enquiry_date
CUST001,ABCPD1234F,750,2024-01-15
```""").send()
    elif lower.startswith("discover domain ") or lower.startswith("onboard domain "):
        await _multi_feed_discovery(text)
    elif lower.startswith("discover "):
        asset_name = text[9:].strip()
        await _ask_for_fields(asset_name)
    elif lower == "approve" or lower == "approve all":
        await _approve_all()
    elif lower == "deploy sql":
        await _deploy_sql()
    elif lower.startswith("approve "):
        fields = [f.strip() for f in text[8:].split(",")]
        await _approve_fields(fields)
    elif lower == "generate" or lower == "gen config":
        await _generate_config()
    elif lower.startswith("delta "):
        await _handle_delta(text[6:].strip())
    elif lower == "glossary" or lower == "show glossary":
        await _show_glossary()
    elif lower == "domains" or lower == "show domains":
        await _show_domains()
    elif lower == "applications" or lower == "show applications":
        await _show_applications()
    elif lower.startswith("data product ") or lower.startswith("create data product") or lower.startswith("generate sql"):
        await _generate_data_product_sql(text)
    else:
        # Try to parse as YAML/JSON asset definition
        parsed = _try_parse_definition(text)
        if parsed:
            await _run_discovery_from_dict(parsed)
        else:
            # Check if it's a correction ("X is not PII", "remove X from not_null")
            correction = _try_parse_correction(text)
            if correction:
                await _apply_correction(correction)
            # Check if it looks like CSV data
            elif len(text.strip().split("\n")) >= 3 and "," in text.split("\n")[0]:
                lines_check = text.strip().split("\n")
                if all("," in l for l in lines_check[:3]):
                    await cl.Message(content="Detected CSV data. Profiling...").send()
                    await _profile_and_discover(text, "csv")
                else:
                    await _try_natural_language(text)
            else:
                await _try_natural_language(text)


async def _run_discovery(content: str):
    """Parse file content and run discovery."""
    parsed = _try_parse_definition(content)
    if parsed:
        await _run_discovery_from_dict(parsed)
    else:
        await cl.Message(content="❌ Could not parse the file. Please provide a valid YAML or JSON asset definition.").send()


async def _run_discovery_from_dict(asset_def: dict):
    """Run full discovery on a parsed asset definition."""
    asset_name = asset_def.get("name", "unknown_asset")
    fields = asset_def.get("fields", [])

    if not fields:
        await cl.Message(content="❌ No fields found in the definition. Please include a `fields` list.").send()
        return

    # Show processing status
    msg = cl.Message(content=f"🔍 Running **Full Discovery** on `{asset_name}` ({len(fields)} fields)...\n\nAnalysing against Knowledge Graph ({len(kg.terms)} business terms)...")
    await msg.send()

    # Run discovery
    suggestion = suggester.full_discovery(asset_def)

    # LLM review — validate and correct suggestions
    try:
        from discovery.engine.llm_reviewer import LLMReviewer
        reviewer = LLMReviewer()
        await cl.Message(content="Validating suggestions with AI reviewer...").send()
        corrections = reviewer.review(suggestion)
        if corrections and (corrections.get("corrections") or corrections.get("accepted_values_override") or corrections.get("remove_pii") or corrections.get("remove_not_null")):
            suggestion = reviewer.apply_corrections(suggestion, corrections)
    except Exception as e:
        print(f"[LLMReviewer] Review skipped: {e}")

    cl.user_session.set("current_suggestion", suggestion)

    # Format results
    result = _format_suggestion(suggestion)
    await cl.Message(content=result).send()

    # Prompt for action
    await cl.Message(content="""## What would you like to do?

- `approve all` — Accept all suggestions and generate pipeline config
- `approve field1, field2, ...` — Accept specific fields only
- `generate` — Generate the pipeline YAML config
- Paste modified suggestions if you want to edit anything

*You can also ask me about specific fields or terms.*""").send()


def _format_suggestion(s: DiscoverySuggestion) -> str:
    """Format discovery suggestion for display."""
    lines = []
    lines.append(f"# 📋 Discovery Results: `{s.asset_name}`\n")
    lines.append(f"**Mode:** {s.mode.title()} Discovery")
    lines.append(f"**Discovered:** {s.discovered_at}\n")

    # Business Application
    lines.append("## 🏢 Business Application")
    if s.business_application_name:
        lines.append(f"**Suggested:** {s.business_application_name} (confidence: {s.app_confidence:.0%})")
    else:
        lines.append("**Suggested:** ⚠️ Could not determine — please specify manually")

    # Data Domain
    lines.append(f"\n## 📁 Data Domain")
    if s.data_domain:
        domain = kg.domains.get(s.data_domain)
        lines.append(f"**Suggested:** {domain.name if domain else s.data_domain}")
    else:
        lines.append("**Suggested:** ⚠️ Could not determine")

    # Primary Key
    lines.append(f"\n## 🔑 Primary Key")
    lines.append(f"**Suggested:** `{s.primary_key}`" if s.primary_key else "**Suggested:** ⚠️ None identified")

    # Field-level suggestions
    lines.append("\n## 📊 Field Suggestions\n")
    lines.append("| Field | Business Term | Type | PII | Classification | Confidence |")
    lines.append("|-------|--------------|------|-----|----------------|------------|")
    for f in s.fields:
        term_display = f.linked_term_name or "❓ NEW TERM"
        pii_icon = "🔴 Yes" if f.is_pii else "🟢 No"
        conf_display = f"{f.confidence:.0%}" if f.confidence > 0 else "—"
        lines.append(f"| `{f.field_name}` | {term_display} | {f.information_type or '—'} | {pii_icon} | {f.classification} | {conf_display} |")

    # DQ Rules Summary
    lines.append("\n## ✅ Suggested DQ Rules\n")
    for f in s.fields:
        if f.dq_rules:
            rules_str = ", ".join(f"{k}: {v}" for k, v in f.dq_rules.items())
            lines.append(f"- `{f.field_name}`: {rules_str}")

    # Foreign Keys
    if s.fk_candidates:
        lines.append("\n## 🔗 Foreign Key Candidates\n")
        for fk in s.fk_candidates:
            lines.append(f"- `{fk['field']}` → `{fk['references']}` (confidence: {fk['confidence']:.0%})")

    # New Term Proposals
    if s.new_term_proposals:
        lines.append("\n## 🆕 New Business Terms Proposed\n")
        lines.append("These fields had no match in the glossary. Consider creating new terms:\n")
        for prop in s.new_term_proposals:
            lines.append(f"- **{prop['suggested_term_name']}** (from field `{prop['field_name']}`, domain: {prop['suggested_domain']})")

    # Schema Evolution
    lines.append("\n## 🛡️ Schema Evolution Governance\n")
    if s.schema_evolution:
        lines.append(f"- **Allowed:** {s.schema_evolution.get('allowed', [])}")
        lines.append(f"- **Blocked:** {s.schema_evolution.get('blocked', [])}")

    # Reasoning (collapsible)
    lines.append("\n<details><summary>🧠 Detailed Reasoning (click to expand)</summary>\n")
    for f in s.fields:
        if f.reasoning:
            lines.append(f"**{f.field_name}:**")
            for r in f.reasoning:
                lines.append(f"  - {r}")
    lines.append("\n</details>")

    return "\n".join(lines)


async def _approve_all():
    """Approve all suggestions — write to Dataplex + push config to GCS."""
    suggestion = cl.user_session.get("current_suggestion")
    if not suggestion:
        await cl.Message(content="No active discovery to approve. Run a discovery first.").send()
        return

    # Generate config YAML
    config_yaml = config_gen.generate(suggestion)

    # Process approval — write to Dataplex + GCS
    await cl.Message(content="Processing approval — writing to Knowledge Catalog, generating contract, pushing config to GCS...").send()

    results = approval_handler.process_approval(suggestion, config_yaml=config_yaml)

    # Generate and push data contract
    contract_path = contract_gen.generate_and_push(suggestion)
    contract_yaml = contract_gen.generate(suggestion)

    # Generate and push SCD config
    business_intent = cl.user_session.get("business_intent") or ""
    scd_type = scd_gen.infer_scd_type(business_intent, suggestion.data_domain)
    scd_path = scd_gen.generate_and_push(suggestion, scd_type=scd_type, business_intent=business_intent)

    # Report what was done
    lines = ["## Approval Processed\n"]

    if results["new_terms_created"]:
        lines.append("### New BDEs Created in Glossary")
        for term in results["new_terms_created"]:
            lines.append(f"- {term}")
        lines.append("")

    if results["ba_linked"]:
        lines.append(f"### Dataset Linked to Business Application")
        lines.append(f"- {suggestion.asset_name} -> {results['ba_linked']}")
        lines.append("")

    if results["config_gcs_path"]:
        lines.append(f"### Pipeline Config Pushed to GCS")
        lines.append(f"- `{results['config_gcs_path']}`")
        lines.append("")

    if contract_path:
        lines.append(f"### Data Contract Generated")
        lines.append(f"- `{contract_path}`")
        lines.append(f"- Version: 1.0.0 (draft)")
        lines.append(f"- Pipeline will enforce DQ SLAs from this contract")
        lines.append("")

    if scd_path:
        lines.append(f"### SCD Dimension Config Generated")
        lines.append(f"- `{scd_path}`")
        lines.append(f"- SCD Type: {scd_gen.get_scd_description(scd_type)}")
        lines.append("")

    if results["policies_set"]:
        lines.append("### Policies Set")
        for p in results["policies_set"]:
            classification = p['classification']
            dq = p['dq_rules']
            lines.append(f"- `{p['field']}`: {classification}" + (f" | DQ: {dq}" if dq else ""))
        lines.append("")

    if results["errors"]:
        lines.append("### Warnings")
        for err in results["errors"]:
            lines.append(f"- {err}")
        lines.append("")

    await cl.Message(content="\n".join(lines)).send()


async def _approve_fields(field_names: list[str]):
    """Approve specific fields only."""
    suggestion = cl.user_session.get("current_suggestion")
    if not suggestion:
        await cl.Message(content="❌ No active discovery to approve. Run a discovery first.").send()
        return

    config_yaml = config_gen.generate(suggestion, approved_fields=field_names)
    await cl.Message(content=f"## ✅ Config Generated (partial approval)\n\nApproved fields: {field_names}\n\n```yaml\n{config_yaml}\n```").send()


async def _generate_config():
    """Generate pipeline YAML config from current suggestion."""
    suggestion = cl.user_session.get("current_suggestion")
    if not suggestion:
        await cl.Message(content="❌ No active discovery. Run a discovery first.").send()
        return

    config_yaml = config_gen.generate(suggestion)
    catalog_entry = config_gen.generate_catalog_entry(suggestion)

    await cl.Message(content=f"""## ✅ Pipeline Config Generated

### `config/tables/{suggestion.asset_name}.yaml`

```yaml
{config_yaml}
```

### 📚 Catalog Entry (for Dataplex/OpenMetadata)

```json
{json.dumps(catalog_entry, indent=2)}
```

---

**Next steps:**
1. Review the config above
2. Place it in `bt_df_lkhouse_fw/config/tables/{suggestion.asset_name}.yaml`
3. Run the pipeline: `python -m bt_df_lkhouse_fw.engine.ingest --table {suggestion.asset_name} --version v1`
""").send()


async def _search_glossary(query: str):
    """Search business terms by name/synonym."""
    matches = kg.search_by_synonym(query)
    if not matches:
        await cl.Message(content=f"No matches found for `{query}`. Try a different term or check `show glossary`.").send()
        return

    lines = [f"## 🔎 Search Results for `{query}`\n"]
    for term, confidence in matches:
        lines.append(f"### {term.name}")
        lines.append(f"- **Domain:** {term.domain}")
        lines.append(f"- **Type:** {term.information_type}")
        lines.append(f"- **PII:** {'Yes' if term.is_pii else 'No'}")
        lines.append(f"- **Synonyms:** {', '.join(term.synonyms)}")
        lines.append(f"- **Match confidence:** {confidence:.0%}")
        lines.append("")

    await cl.Message(content="\n".join(lines)).send()


async def _show_glossary():
    """Show all business terms grouped by domain."""
    lines = ["## 📖 Business Glossary\n"]
    for domain in kg.domains.values():
        terms = kg.get_terms_by_domain(domain.id)
        if terms:
            lines.append(f"### {domain.name}")
            for t in terms:
                pii = " 🔴PII" if t.is_pii else ""
                lines.append(f"- **{t.name}**{pii} ({t.information_type}) — synonyms: {', '.join(t.synonyms[:3])}")
            lines.append("")
    await cl.Message(content="\n".join(lines)).send()


async def _show_domains():
    """Show all data domains."""
    lines = ["## 📁 Data Domains\n"]
    for d in kg.domains.values():
        term_count = len(kg.get_terms_by_domain(d.id))
        lines.append(f"- **{d.name}** — {d.description} ({term_count} terms)")
    await cl.Message(content="\n".join(lines)).send()


async def _show_applications():
    """Show all business applications."""
    lines = ["## 🏢 Business Applications\n"]
    for app in kg.applications.values():
        lines.append(f"- **{app.name}** — {app.description}")
        lines.append(f"  Keywords: {', '.join(app.keywords[:5])}")
    await cl.Message(content="\n".join(lines)).send()


async def _ask_for_fields(asset_name: str):
    """Prompt user to provide field definitions."""
    await cl.Message(content=f"""## Define fields for `{asset_name}`

Please paste the fields in YAML or JSON format:

```yaml
name: {asset_name}
fields:
  - name: field1
    type: string
    description: optional description
  - name: field2
    type: integer
```

Or as JSON:
```json
{{"name": "{asset_name}", "fields": [{{"name": "field1", "type": "string"}}]}}
```
""").send()


async def _handle_delta(text: str):
    """Handle delta discovery for schema changes."""
    parsed = _try_parse_definition(text)
    if not parsed:
        await cl.Message(content="""## Delta Discovery

Provide the schema changes:
```yaml
asset_name: existing_table
new_fields:
  - name: new_field1
    type: string
removed_fields: [old_field]
changed_fields:
  - name: existing_field
    old_type: string
    new_type: integer
```""").send()
        return

    asset_name = parsed.get("asset_name", "unknown")
    new_fields = parsed.get("new_fields", [])
    removed = parsed.get("removed_fields", [])
    changed = parsed.get("changed_fields", [])

    suggestion = suggester.delta_discovery(asset_name, new_fields, removed, changed)
    cl.user_session.set("current_suggestion", suggestion)

    result = _format_suggestion(suggestion)
    await cl.Message(content=result).send()


async def _show_help():
    await cl.Message(content="""## 📖 Commands

| Command | Description |
|---------|-------------|
| *paste YAML/JSON* | Run Full Discovery on an asset definition |
| `discover <name>` | Start discovery (I'll ask for fields) |
| `delta <yaml>` | Run Delta Discovery on schema changes |
| `search <term>` | Search the business glossary |
| `approve all` | Approve all suggestions |
| `approve field1, field2` | Approve specific fields |
| `generate` | Generate pipeline YAML config |
| `glossary` | Show all business terms |
| `domains` | Show all data domains |
| `applications` | Show all business applications |
| `help` | Show this message |
""").send()


def _try_parse_correction(text: str) -> Optional[dict]:
    """Parse conversational corrections like 'due_date is not PII' or 'remove status from accepted_values'."""
    lower = text.lower().strip()

    # Pattern: "X is not PII"
    m = re.match(r'[`]?([\w]+)[`]?\s+is\s+not\s+pii', lower)
    if m:
        return {"action": "remove_pii", "field": m.group(1)}

    # Pattern: "X is PII"
    m = re.match(r'[`]?([\w]+)[`]?\s+is\s+pii', lower)
    if m:
        return {"action": "add_pii", "field": m.group(1)}

    # Pattern: "remove X from not_null" / "X should be nullable"
    m = re.match(r'(?:remove\s+)?[`]?([\w]+)[`]?\s+(?:should be|is)\s+nullable', lower)
    if m:
        return {"action": "remove_not_null", "field": m.group(1)}
    m = re.match(r'remove\s+[`]?([\w]+)[`]?\s+from\s+not_null', lower)
    if m:
        return {"action": "remove_not_null", "field": m.group(1)}

    # Pattern: "X accepted values should be [a, b, c]" / "X values are a, b, c"
    m = re.match(r'[`]?([\w]+)[`]?\s+(?:accepted\s+)?values?\s+(?:should be|are)\s+(.+)', lower)
    if m:
        vals = [v.strip().strip("[]'\"") for v in m.group(2).split(",")]
        return {"action": "set_accepted_values", "field": m.group(1), "values": vals}

    # Pattern: "X is not unique" / "X is unique"
    m = re.match(r'[`]?([\w]+)[`]?\s+is\s+not\s+unique', lower)
    if m:
        return {"action": "remove_unique", "field": m.group(1)}
    m = re.match(r'[`]?([\w]+)[`]?\s+is\s+unique', lower)
    if m:
        return {"action": "add_unique", "field": m.group(1)}

    # Pattern: "X should map to BDE_NAME"
    m = re.match(r'[`]?([\w]+)[`]?\s+(?:should map to|maps to|is)\s+[`]?([\w_]+)[`]?', lower)
    if m:
        field, bde = m.group(1), m.group(2)
        # Only treat as BDE mapping if it's not one of the above patterns
        if bde not in ("pii", "nullable", "unique", "not"):
            return {"action": "set_bde", "field": field, "bde": bde}

    return None


async def _apply_correction(correction: dict):
    """Apply a conversational correction to current suggestion."""
    suggestion = cl.user_session.get("current_suggestion")
    if not suggestion:
        await cl.Message(content="No active discovery to correct. Run a discovery first.").send()
        return

    field_name = correction["field"]
    action = correction["action"]

    # Find the field
    target = None
    for f in suggestion.fields:
        if f.field_name == field_name:
            target = f
            break

    if not target:
        await cl.Message(content=f"Field `{field_name}` not found in current suggestion.").send()
        return

    # Apply correction
    if action == "remove_pii":
        target.is_pii = False
        target.classification = "Internal"
        msg = f"`{field_name}` marked as **not PII**."
    elif action == "add_pii":
        target.is_pii = True
        target.classification = "PII"
        msg = f"`{field_name}` marked as **PII**."
    elif action == "remove_not_null":
        target.dq_rules.pop("not_null", None)
        msg = f"`{field_name}` removed from not_null rules."
    elif action == "remove_unique":
        target.dq_rules.pop("unique", None)
        msg = f"`{field_name}` removed from unique rules."
    elif action == "add_unique":
        target.dq_rules["unique"] = True
        msg = f"`{field_name}` marked as unique."
    elif action == "set_accepted_values":
        target.dq_rules["accepted_values"] = correction["values"]
        msg = f"`{field_name}` accepted values set to: {correction['values']}"
    elif action == "set_bde":
        target.linked_term = correction["bde"]
        target.linked_term_name = correction["bde"].replace("_", " ").title()
        msg = f"`{field_name}` mapped to BDE `{correction['bde']}`."
    else:
        msg = f"Unknown correction action: {action}"

    cl.user_session.set("current_suggestion", suggestion)
    await cl.Message(content=f"✅ Correction applied: {msg}").send()


def _try_parse_definition(text: str) -> dict | None:
    """Try to parse text as YAML or JSON."""
    # Strip markdown code fences if present
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        clean = "\n".join(lines)

    # Try YAML first (superset of JSON)
    try:
        parsed = yaml.safe_load(clean)
        if isinstance(parsed, dict) and ("fields" in parsed or "new_fields" in parsed):
            return parsed
    except Exception:
        pass

    # Try JSON
    try:
        parsed = json.loads(clean)
        if isinstance(parsed, dict) and ("fields" in parsed or "new_fields" in parsed):
            return parsed
    except Exception:
        pass

    return None


async def _try_natural_language(text: str):
    """Try to parse natural language input using LLM."""
    await cl.Message(content="Interpreting your request...").send()

    parsed = nl_parser.parse(text)

    if isinstance(parsed, str) and parsed == "__QUOTA_EXCEEDED__":
        await cl.Message(content="LLM quota exceeded. Please paste YAML/JSON instead, or wait for quota to reset.").send()
        return

    if parsed and parsed.get("fields"):
        # Show what we understood
        fields_display = "\n".join([f"  - {f['name']} ({f['type']})" for f in parsed['fields']])
        await cl.Message(content=f"""I understood this as:

**Dataset:** `{parsed.get('name', 'unnamed')}`
**Fields:**
{fields_display}

Running discovery...""").send()

        # Store original text as business intent for SCD inference
        cl.user_session.set("business_intent", text)
        await _run_discovery_from_dict(parsed)
    else:
        await cl.Message(content="""I couldn't extract a dataset definition from that. You can:

- **Describe naturally:** "I have a new CIBIL feed with customer_id, pan_number, cibil_score, enquiry_date and loan_amount. Track score changes over time."
- **Paste YAML/JSON** with field definitions
- **Paste CSV data** or upload a .csv file for profiling
- Type `help` for all commands""").send()


async def _profile_and_discover(content: str, format: str = "csv", dataset_name: str = None):
    """Profile sample data then run discovery with profile evidence."""
    name_display = f" for `{dataset_name}`" if dataset_name else ""
    await cl.Message(content=f"Profiling sample data{name_display}...").send()

    if format == "csv":
        profile = profiler.profile_csv(content)
    else:
        profile = profiler.profile_pasted(content)

    if not profile.columns:
        await cl.Message(content="Could not parse the data. Ensure it has headers and at least a few rows.").send()
        return

    # Show profile report
    report = format_profile_report(profile)
    await cl.Message(content=report).send()

    # Convert profile to asset definition for SD
    asset_def = _profile_to_asset_def(profile, dataset_name)
    cl.user_session.set("current_profile", profile)

    # Run discovery with profile enhancement
    await cl.Message(content=f"Running Semantic Discovery on `{asset_def['name']}` ({len(asset_def['fields'])} fields) with profile evidence...").send()

    suggestion = suggester.full_discovery(asset_def)

    # Enhance suggestions with profile evidence
    _enhance_with_profile(suggestion, profile)

    cl.user_session.set("current_suggestion", suggestion)
    result = _format_suggestion(suggestion)
    await cl.Message(content=result).send()
    await cl.Message(content="""## What would you like to do?

- `approve all` - Accept all suggestions and write to catalog
- `generate` - Generate pipeline YAML config
- Ask me about specific fields""").send()


async def _handle_profile(text: str):
    """Handle pasted data for profiling."""
    if text.startswith("gs://"):
        await cl.Message(content="GCS profiling not yet supported in this POC. Please paste CSV data directly or upload a .csv file.").send()
        return

    # Try to profile pasted data
    profile = profiler.profile_pasted(text)
    if profile.columns:
        report = format_profile_report(profile)
        await cl.Message(content=report).send()

        asset_def = _profile_to_asset_def(profile)
        await cl.Message(content=f"""Profile complete. Run discovery on this?

Paste `discover` to run SD on the profiled data, or paste a YAML definition to override.""").send()
        cl.user_session.set("current_profile", profile)
    else:
        await cl.Message(content="""Could not parse the data. Try:
- Pasting CSV with headers
- Uploading a .csv file
- Using comma, tab, or pipe as delimiter""").send()


def _profile_to_asset_def(profile, dataset_name: str = None) -> dict:
    """Convert a DataProfile into an asset definition dict."""
    fields = []
    for col in profile.columns:
        fields.append({
            "name": col.name,
            "type": col.inferred_type,
        })

    name = dataset_name or "profiled_dataset"
    return {"name": name, "fields": fields}


async def _generate_data_product_sql(text: str):
    """Generate consumption SQL from natural language requirement."""
    # Strip command prefix
    requirement = text
    for prefix in ["data product ", "create data product ", "generate sql "]:
        if requirement.lower().startswith(prefix):
            requirement = requirement[len(prefix):]
            break

    await cl.Message(content=f"Generating Data Product SQL from your requirement...\n\nLooking up available tables in CCN layer...").send()

    sql = sql_gen.generate(requirement)

    if sql == "__QUOTA_EXCEEDED__":
        await cl.Message(content="""## LLM Quota Exceeded

The AI token quota has been exhausted. Options:

1. **Wait 1 minute** and try again (per-minute quota resets)
2. **Wait until tomorrow** if daily quota is exceeded
3. **Write the SQL manually** and use `deploy sql` to push it

You can also create the SQL file directly and upload it to:
`gs://bt-df-lkhouse-lakehouse/framework/config/consumption/<name>.sql`""").send()
        return

    if not sql:
        await cl.Message(content="Failed to generate SQL. Please try rephrasing your requirement.").send()
        return

    # Extract table name
    table_name = sql_gen._extract_table_name(sql)

    # Show the generated SQL
    await cl.Message(content=f"""## Generated Data Product SQL: `{table_name}`

```sql
{sql}
```

## What would you like to do?

- Type `deploy sql` to push this to GCS and make it available for the pipeline
- Type `edit` to modify the requirement
- Paste a revised version if you want to change anything""").send()

    # Store for deployment
    cl.user_session.set("pending_sql", sql)
    cl.user_session.set("pending_sql_table", table_name)


def _enhance_with_profile(suggestion, profile):
    """Enhance SD suggestions with profiling evidence."""
    profile_map = {col.name: col for col in profile.columns}

    for field_sug in suggestion.fields:
        col_profile = profile_map.get(field_sug.field_name)
        if not col_profile:
            continue

        # Override PII detection with profile evidence
        if col_profile.is_likely_pii and not field_sug.is_pii:
            field_sug.is_pii = True
            field_sug.classification = "PII"
            field_sug.reasoning.append(
                f"PROFILE: PII detected from values (pattern: {', '.join(col_profile.detected_patterns)})"
            )

        # Override key candidate with profile evidence
        if col_profile.is_likely_identifier:
            field_sug.is_key_candidate = True
            field_sug.reasoning.append(
                f"PROFILE: Likely PK (cardinality: {col_profile.cardinality_ratio:.0%}, nulls: {col_profile.null_pct:.0%})"
            )

        # Add reference set from profile
        if col_profile.is_likely_reference and col_profile.distinct_values:
            field_sug.accepted_values = col_profile.distinct_values
            field_sug.reasoning.append(
                f"PROFILE: Low cardinality ({col_profile.distinct_count} values) -> reference set"
            )

        # Merge DQ rules from profile
        for k, v in col_profile.suggested_dq.items():
            if k not in field_sug.dq_rules:
                field_sug.dq_rules[k] = v

        # Boost confidence if profile confirms the match
        if col_profile.detected_patterns:
            if field_sug.confidence > 0:
                field_sug.confidence = min(field_sug.confidence + 0.1, 0.99)


async def _multi_feed_discovery(text: str):
    """Handle multi-feed onboarding — one prompt for entire domain."""
    await cl.Message(content="Parsing multi-dataset description...").send()

    datasets = nl_parser.parse_multi(text)

    if not datasets or len(datasets) < 2:
        # Fall back to single parse
        parsed = nl_parser.parse(text)
        if parsed and parsed.get("fields"):
            await _run_discovery_from_dict(parsed)
        else:
            await cl.Message(content="""I couldn't extract multiple datasets. Try this format:

```
discover domain Insurance:
1. motor_policy: policy_id, customer_id, vehicle_reg, premium_amount, start_date, end_date, status, coverage_type
2. motor_claims: claim_id, policy_id, claim_date, claim_amount, status, description, settlement_date
3. vehicle_master: vehicle_id, make, model, year, registration_number, engine_type, owner_id
4. premium_payments: payment_id, policy_id, amount, payment_date, payment_method, status
```""").send()
        return

    # Show what we parsed
    lines = [f"## Parsed {len(datasets)} Datasets\n"]
    for ds in datasets:
        field_names = [f['name'] for f in ds['fields']]
        truncated = ', '.join(field_names[:8]) + ('...' if len(field_names) > 8 else '')
        lines.append(f"**`{ds['name']}`** — {len(ds['fields'])} fields: {truncated}")
    lines.append(f"\nRunning discovery on all {len(datasets)} datasets...")
    await cl.Message(content="\n".join(lines)).send()

    # Run discovery on each
    all_suggestions = []
    for ds in datasets:
        suggestion = suggester.full_discovery(ds)
        all_suggestions.append(suggestion)

    # Store all suggestions
    cl.user_session.set("multi_suggestions", all_suggestions)
    cl.user_session.set("current_suggestion", all_suggestions[0])  # first one active

    # Display combined results
    combined_lines = [f"# Domain Onboarding — {len(all_suggestions)} Datasets\n"]
    for i, s in enumerate(all_suggestions):
        combined_lines.append(f"## {i+1}. `{s.asset_name}` ({len(s.fields)} fields)")
        combined_lines.append(f"- **Business Application:** {s.business_application_name or '?'}")
        combined_lines.append(f"- **Domain:** {s.data_domain or '?'}")
        combined_lines.append(f"- **Primary Key:** `{s.primary_key or '?'}`")
        combined_lines.append("")
        combined_lines.append("| Field | BDE Match | PII | Confidence |")
        combined_lines.append("|-------|-----------|-----|------------|")
        for f in s.fields:
            term = f.linked_term_name or "NEW"
            pii = "🔴" if f.is_pii else "🟢"
            conf = f"{f.confidence:.0%}" if f.confidence > 0 else "-"
            combined_lines.append(f"| `{f.field_name}` | {term} | {pii} | {conf} |")
        combined_lines.append("")

    combined_lines.append("---")
    combined_lines.append("Type `approve all` to approve all datasets, or `approve 1` / `approve 2` for individual ones.")

    await cl.Message(content="\n".join(combined_lines)).send()


async def _ge_profile(text: str):
    """Run GE-based profiling with fingerprinting, confidence scoring, and LLM DQ generation."""
    if not GE_AVAILABLE:
        await cl.Message(content="Great Expectations not installed. Run `pip install great-expectations pandas` to enable.").send()
        return

    # Parse: "ge profile <dataset_name>\n<csv_data>" or just csv data
    lines = text.split("\n", 1)
    dataset_name = None
    data = ""

    if len(lines) >= 2:
        first_line = lines[0].strip()
        if "," not in first_line and first_line:
            dataset_name = first_line.replace(" ", "_").lower()
            data = lines[1].strip()
        else:
            data = text
    elif len(lines) == 1 and "," in lines[0]:
        data = text

    if not data:
        await cl.Message(content="""Usage:
```
ge profile <dataset_name>
<csv data with headers>
```""").send()
        return

    await cl.Message(content=f"Running **GE Profile** with fingerprinting and composite confidence scoring...").send()

    ge = GEProfiler()
    profile = ge.profile_csv(data, dataset_name=dataset_name or "dataset")

    # Show GE profile report
    report = format_ge_profile_report(profile)
    await cl.Message(content=report).send()

    # Generate GE expectations
    expectations = ge.generate_ge_expectations(profile)
    await cl.Message(content=f"Generated **{len(expectations)} GE expectations** for DQ validation.").send()

    # Send to LLM for business DQ generation
    await cl.Message(content="Sending statistical summary to LLM for business DQ rule generation (no raw data shared)...").send()

    dq_gen = LLMDQGenerator()
    llm_result = dq_gen.generate(profile.llm_summary)

    if "error" in llm_result:
        await cl.Message(content=f"LLM DQ generation skipped: {llm_result['error']}. Using GE profile signals only.").send()
    else:
        # Merge LLM + GE results
        merged = dq_gen.merge_with_profile(profile, llm_result)

        lines_out = ["## LLM-Generated Business DQ Rules\n"]
        lines_out.append(f"**Business Application:** {merged.get('business_application', '?')}")
        lines_out.append(f"**Domain:** {merged.get('domain', '?')}\n")
        lines_out.append("| Field | BDE | Info Type | DQ Rules | Sources |")
        lines_out.append("|-------|-----|-----------|----------|---------|")

        for f in merged.get("fields", []):
            dq_str = ", ".join(f"{k}={v}" for k, v in f.get("dq_rules", {}).items())
            src_str = "; ".join(f.get("sources", [])[:3])
            lines_out.append(
                f"| `{f['name']}` | {f.get('bde_name', '-')} | {f.get('information_type', '-')} "
                f"| {dq_str or '-'} | {src_str or '-'} |"
            )

        await cl.Message(content="\n".join(lines_out)).send()

    # Now run SD on the profiled fields
    asset_def = {
        "name": dataset_name or "ge_profiled_dataset",
        "fields": [{"name": col.name, "type": col.inferred_type} for col in profile.columns],
    }
    await cl.Message(content="Running Semantic Discovery with GE evidence...").send()
    await _run_discovery_from_dict(asset_def)


async def _deploy_sql():
    """Deploy pending SQL to GCS."""
    sql = cl.user_session.get("pending_sql")
    table_name = cl.user_session.get("pending_sql_table")

    if not sql:
        await cl.Message(content="No pending SQL to deploy. Use `data product <requirement>` first.").send()
        return

    gcs_path = sql_gen._push_to_gcs(table_name, sql)

    if gcs_path:
        await cl.Message(content=f"""## SQL Deployed

- **Table:** `{table_name}`
- **GCS Path:** `{gcs_path}`
- **Status:** Ready for pipeline

**Next:** Run the consume step:
```bash
python3 -m bt_df_lkhouse_fw.engine.consume --config gs://bt-df-lkhouse-lakehouse/framework/config/pipeline.yaml --target {table_name} --project bt-df-lkhouse
```""").send()
    else:
        await cl.Message(content="Failed to deploy SQL to GCS.").send()

    cl.user_session.set("pending_sql", None)
    cl.user_session.set("pending_sql_table", None)
