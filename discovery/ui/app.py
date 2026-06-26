"""Semantic Discovery — Chainlit Interactive UI.
Data stewards interact conversationally to discover, classify, and onboard data assets."""
import sys
import json
import yaml
import chainlit as cl
from pathlib import Path

# Ensure discovery package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from discovery.engine.knowledge_graph import KnowledgeGraph
from discovery.engine.rules_engine import RulesEngine
from discovery.engine.embedder import Embedder
from discovery.engine.suggester import Suggester, DiscoverySuggestion
from discovery.engine.config_generator import ConfigGenerator
from discovery.engine.nl_parser import NLParser
from discovery.engine.approval_handler import ApprovalHandler

# Initialize engine components
kg = KnowledgeGraph()
rules = RulesEngine()
embedder = Embedder(mode="local")
suggester = Suggester(knowledge_graph=kg, rules_engine=rules, embedder=embedder)
config_gen = ConfigGenerator()
nl_parser = NLParser()
approval_handler = ApprovalHandler()


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
            if element.path and (element.path.endswith(".yaml") or element.path.endswith(".yml") or element.path.endswith(".json")):
                content = Path(element.path).read_text(encoding="utf-8")
                await _run_discovery(content)
                return

    # Command routing
    lower = text.lower()
    if lower.startswith("help"):
        await _show_help()
    elif lower.startswith("search "):
        query = text[7:].strip()
        await _search_glossary(query)
    elif lower.startswith("discover "):
        asset_name = text[9:].strip()
        await _ask_for_fields(asset_name)
    elif lower == "approve" or lower == "approve all":
        await _approve_all()
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
    else:
        # Try to parse as YAML/JSON asset definition
        parsed = _try_parse_definition(text)
        if parsed:
            await _run_discovery_from_dict(parsed)
        else:
            # Try natural language parsing
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
    """Approve all suggestions — write to Dataplex + generate config."""
    suggestion = cl.user_session.get("current_suggestion")
    if not suggestion:
        await cl.Message(content="No active discovery to approve. Run a discovery first.").send()
        return

    # Process approval — write to Dataplex
    await cl.Message(content="Processing approval — writing to Knowledge Catalog...").send()

    results = approval_handler.process_approval(suggestion)

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

    # Generate config
    await _generate_config()


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
    """Try to parse natural language input using Gemini."""
    await cl.Message(content="Interpreting your request...").send()

    parsed = nl_parser.parse(text)
    if parsed and parsed.get("fields"):
        # Show what we understood
        fields_display = "\n".join([f"  - {f['name']} ({f['type']})" for f in parsed['fields']])
        await cl.Message(content=f"""I understood this as:

**Dataset:** `{parsed.get('name', 'unnamed')}`
**Fields:**
{fields_display}

Running discovery...""").send()

        await _run_discovery_from_dict(parsed)
    else:
        await cl.Message(content="""I couldn't extract a dataset definition from that. You can:

- **Describe naturally:** "I have a new CIBIL feed with customer_id, pan_number, cibil_score, enquiry_date and loan_amount"
- **Paste YAML/JSON** with field definitions
- Type `help` for all commands""").send()
