"""Knowledge Catalog Agent — LLM-powered Q&A over Dataplex Knowledge Catalog.

Uses LLM to:
1. Classify user intent (what are they asking about?)
2. Plan API calls (which KC endpoints to call?)
3. Execute and format response (natural language answer)

Supports questions about:
- Business Data Elements (glossary terms)
- Business Applications
- Domains
- Datasets (entries)
- EntryLinks (relationships)
- DQ rules (from BDE definitions)
- PII classifications
- Ownership and governance

Production patterns:
- Structured function calling (LLM returns JSON intent)
- Caching for glossary (doesn't change often)
- Graceful degradation (answers from local glossary if KC API fails)
- Audit trail (logs all queries)
"""
import os
import json
import time
import yaml
from typing import Optional
from pathlib import Path

from discovery.engine.llm_client import LLMClient, get_llm
from discovery.engine.knowledge_graph import KnowledgeGraph


# Intent classification prompt
INTENT_SYSTEM = """You are an intent classifier for a Data Catalog Q&A system.
Given a user question about their data estate, classify it into one of these intents:

- GLOSSARY_TERMS: questions about business terms/BDEs (what terms exist, term definitions, synonyms)
- DOMAIN_INFO: questions about data domains (list domains, what's in a domain)
- BA_INFO: questions about business applications (list BAs, what's in a BA, which BA owns what)
- DATASET_INFO: questions about specific datasets (schema, who owns it, when was it onboarded)
- DQ_RULES: questions about data quality rules (what rules apply, what DQ is defined)
- PII_INFO: questions about PII/sensitivity (which fields are PII, what's classified)
- RELATIONSHIP: questions about links between entities (what BDEs does a dataset use, what datasets use a BDE)
- SEARCH: general search across the catalog (find something by keyword)
- STATS: aggregate questions (how many, count, total)

Also extract:
- entity: the specific thing being asked about (domain name, dataset name, BDE name, etc.)
- filter: any filter criteria (e.g., "in Credit domain", "with PII")

Return JSON only:
{"intent": "<INTENT>", "entity": "<name or null>", "filter": "<filter or null>", "original_question": "<the question>"}
"""

# Response generation prompt
RESPONSE_SYSTEM = """You are a Data Catalog assistant. Given API results from the Knowledge Catalog,
format a clear, concise answer to the user's question. Use markdown formatting.
Be specific with numbers and names. If data is empty, say so clearly."""


class KnowledgeCatalogAgent:
    """LLM-powered agent that answers questions about the data catalog."""

    def __init__(self, knowledge_graph: Optional[KnowledgeGraph] = None):
        self.kg = knowledge_graph or KnowledgeGraph()
        self.llm = get_llm()
        self._cache = {}
        self._cache_ttl = 300  # 5 min cache

    def answer(self, question: str) -> str:
        """Answer any question about the data catalog."""
        # Step 1: Classify intent
        intent = self._classify_intent(question)
        if not intent:
            return self._fallback_answer(question)

        # Step 2: Execute the right handler
        handler_map = {
            "GLOSSARY_TERMS": self._handle_glossary,
            "DOMAIN_INFO": self._handle_domains,
            "BA_INFO": self._handle_business_apps,
            "DATASET_INFO": self._handle_dataset,
            "DQ_RULES": self._handle_dq_rules,
            "PII_INFO": self._handle_pii,
            "RELATIONSHIP": self._handle_relationships,
            "SEARCH": self._handle_search,
            "STATS": self._handle_stats,
        }

        handler = handler_map.get(intent.get("intent"), self._fallback_answer)
        try:
            raw_data = handler(intent)
        except Exception as e:
            return f"Error querying catalog: {str(e)}"

        # Step 3: Format response with LLM (or directly if simple)
        if isinstance(raw_data, str):
            return raw_data

        return self._format_response(question, raw_data)

    def _classify_intent(self, question: str) -> Optional[dict]:
        """Use LLM to classify the user's intent."""
        response = self.llm.generate(
            system=INTENT_SYSTEM,
            user=question,
            max_tokens=200,
            temperature=0.0,
        )

        if not response or response == "__QUOTA_EXCEEDED__":
            # Fallback: rule-based intent detection
            return self._rule_based_intent(question)

        try:
            # Clean response
            text = response.strip()
            if text.startswith("```"):
                text = "\n".join(l for l in text.split("\n") if not l.strip().startswith("```"))
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        except json.JSONDecodeError:
            return self._rule_based_intent(question)

    def _rule_based_intent(self, question: str) -> dict:
        """Fallback: detect intent from keywords when LLM unavailable."""
        import re
        q = question.lower()
        intent = {"original_question": question, "entity": None, "filter": None}

        # Extract filter first ("in X domain", "for X", "of X")
        filter_match = re.search(r'(?:in|for|under|of)\s+(?:the\s+)?([a-z\s]+?)\s*(?:domain|area|$)', q)
        if filter_match:
            intent["filter"] = filter_match.group(1).strip()

        # Priority: BA > domain ("business applications in Credit domain" = BA_INFO, not DOMAIN_INFO)
        if "business app" in q or "business application" in q:
            intent["intent"] = "BA_INFO"
        elif any(w in q for w in ["bde", "term", "glossary", "business data element"]):
            intent["intent"] = "GLOSSARY_TERMS"
        elif any(w in q for w in ["dq", "quality", "rule", "validation"]):
            intent["intent"] = "DQ_RULES"
        elif any(w in q for w in ["pii", "sensitive", "classification", "personal"]):
            intent["intent"] = "PII_INFO"
        elif any(w in q for w in ["dataset", "table", "feed", "source"]):
            intent["intent"] = "DATASET_INFO"
        elif any(w in q for w in ["link", "relationship", "connected", "uses", "linked"]):
            intent["intent"] = "RELATIONSHIP"
        elif any(w in q for w in ["how many", "count", "total", "number of"]):
            # Check what they're counting
            if "business app" in q or "application" in q:
                intent["intent"] = "BA_INFO"
            elif "term" in q or "bde" in q:
                intent["intent"] = "GLOSSARY_TERMS"
            else:
                intent["intent"] = "STATS"
        elif "domain" in q:
            intent["intent"] = "DOMAIN_INFO"
        else:
            intent["intent"] = "SEARCH"

        # Try to extract entity (quoted terms)
        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', question)
        if quoted:
            intent["entity"] = quoted[0][0] or quoted[0][1]

        return intent

    # --- Intent Handlers ---

    def _handle_glossary(self, intent: dict) -> dict:
        """Handle glossary/BDE questions."""
        entity = intent.get("entity")
        filter_domain = intent.get("filter")

        if entity:
            # Specific term lookup
            matches = self.kg.search_by_synonym(entity)
            if matches:
                term, confidence = matches[0]
                return {
                    "type": "term_detail",
                    "term": {
                        "name": term.name, "id": term.id, "domain": term.domain,
                        "data_type": term.data_type, "information_type": term.information_type,
                        "is_pii": term.is_pii, "classification": term.classification,
                        "synonyms": term.synonyms, "dq_rules": term.dq_rules,
                        "reference_code_set": term.reference_code_set,
                    },
                    "confidence": confidence,
                }

        # List terms (optionally filtered by domain)
        if filter_domain:
            terms = self.kg.get_terms_by_domain(filter_domain)
        else:
            terms = self.kg.get_all_terms()

        return {
            "type": "term_list",
            "domain_filter": filter_domain,
            "count": len(terms),
            "terms": [
                {"name": t.name, "domain": t.domain, "type": t.information_type,
                 "is_pii": t.is_pii, "dq_rules": list(t.dq_rules.keys())}
                for t in terms
            ],
        }

    def _handle_domains(self, intent: dict) -> dict:
        """Handle domain questions."""
        entity = intent.get("entity")

        if entity:
            # Specific domain
            domain = None
            for d in self.kg.domains.values():
                if entity.lower() in d.name.lower() or entity.lower() == d.id.lower():
                    domain = d
                    break
            if domain:
                terms = self.kg.get_terms_by_domain(domain.id)
                return {
                    "type": "domain_detail",
                    "domain": {"name": domain.name, "id": domain.id, "description": domain.description},
                    "term_count": len(terms),
                    "terms": [{"name": t.name, "type": t.information_type, "is_pii": t.is_pii} for t in terms],
                }

        # List all domains
        domains = []
        for d in self.kg.domains.values():
            term_count = len(self.kg.get_terms_by_domain(d.id))
            domains.append({"name": d.name, "id": d.id, "description": d.description, "term_count": term_count})

        return {"type": "domain_list", "count": len(domains), "domains": domains}

    def _handle_business_apps(self, intent: dict) -> dict:
        """Handle business application questions."""
        entity = intent.get("entity")
        filter_val = intent.get("filter")

        apps = list(self.kg.applications.values())

        if filter_val:
            # Filter apps by keyword matching ("credit" matches credit_risk BA via keywords)
            filter_lower = filter_val.lower()
            filtered = []
            for app in apps:
                if any(filter_lower in kw.lower() for kw in app.keywords) or \
                   filter_lower in app.name.lower() or \
                   filter_lower in app.id.lower() or \
                   filter_lower in app.description.lower():
                    filtered.append(app)
            apps = filtered

        if entity:
            # Specific app
            for app in self.kg.applications.values():
                if entity.lower() in app.name.lower() or entity.lower() == app.id.lower():
                    return {
                        "type": "app_detail",
                        "app": {"name": app.name, "id": app.id, "description": app.description, "keywords": app.keywords},
                    }

        return {
            "type": "app_list",
            "filter": filter_val,
            "count": len(apps),
            "apps": [{"name": a.name, "id": a.id, "description": a.description, "keywords": a.keywords[:5]} for a in apps],
        }

    def _handle_dataset(self, intent: dict) -> str:
        """Handle dataset questions — requires KC API (or GCS lookup)."""
        entity = intent.get("entity")
        if entity:
            # Try to find in GCS profiles
            profile_path = f"profiles/{entity.replace(' ', '_').lower()}/latest.json"
            try:
                from google.cloud import storage
                client = storage.Client()
                bucket = client.bucket(os.environ.get("CONFIG_BUCKET", "bt-df-lkhouse-lakehouse"))
                blob = bucket.blob(profile_path)
                if blob.exists():
                    profile = json.loads(blob.download_as_text())
                    fields = profile.get("fields", [])
                    return (
                        f"**Dataset: {entity}**\n\n"
                        f"• Rows: {profile.get('row_count', '?')}\n"
                        f"• Columns: {profile.get('column_count', '?')}\n"
                        f"• Source: {profile.get('source_path', '?')}\n\n"
                        f"**Fields:**\n" +
                        "\n".join(f"• `{f['name']}` ({f['inferred_type']})" +
                                 (" 🔴PII" if f.get('is_pii') else "") +
                                 (" 🔑KEY" if f.get('is_key') else "")
                                 for f in fields)
                    )
            except Exception:
                pass

        return "Dataset information requires a prior discovery or profiling run. Try: \"Onboard <dataset_name>\" first, then I can tell you about it."

    def _handle_dq_rules(self, intent: dict) -> dict:
        """Handle DQ rule questions."""
        entity = intent.get("entity")
        filter_domain = intent.get("filter")

        if entity:
            # DQ rules for a specific term/field
            matches = self.kg.search_by_synonym(entity)
            if matches:
                term, _ = matches[0]
                return {
                    "type": "dq_detail",
                    "term": term.name,
                    "dq_rules": term.dq_rules,
                    "reference_code_set": term.reference_code_set,
                    "explanation": f"These rules are inherited by every table field linked to '{term.name}'",
                }

        # List all terms that have DQ rules
        terms_with_dq = [t for t in self.kg.get_all_terms() if t.dq_rules]
        if filter_domain:
            terms_with_dq = [t for t in terms_with_dq if t.domain == filter_domain]

        return {
            "type": "dq_list",
            "count": len(terms_with_dq),
            "terms": [
                {"name": t.name, "domain": t.domain, "rules": t.dq_rules}
                for t in terms_with_dq
            ],
        }

    def _handle_pii(self, intent: dict) -> dict:
        """Handle PII/classification questions."""
        filter_domain = intent.get("filter")

        pii_terms = [t for t in self.kg.get_all_terms() if t.is_pii]
        if filter_domain:
            pii_terms = [t for t in pii_terms if t.domain == filter_domain]

        return {
            "type": "pii_list",
            "count": len(pii_terms),
            "terms": [
                {"name": t.name, "domain": t.domain, "classification": t.classification, "synonyms": t.synonyms[:3]}
                for t in pii_terms
            ],
        }

    def _handle_relationships(self, intent: dict) -> str:
        """Handle relationship questions."""
        entity = intent.get("entity")
        if entity:
            matches = self.kg.search_by_synonym(entity)
            if matches:
                term, _ = matches[0]
                return (
                    f"**{term.name}** (BDE):\n\n"
                    f"• Domain: {term.domain}\n"
                    f"• Synonyms: {', '.join(term.synonyms)}\n"
                    f"• Any table with a field matching these synonyms will be linked to this BDE.\n"
                    f"• DQ rules ({', '.join(term.dq_rules.keys()) or 'none'}) are inherited by all linked fields.\n\n"
                    f"To see which datasets actually use this BDE, check the Knowledge Catalog EntryLinks."
                )
        return "Specify a BDE or dataset name to see its relationships."

    def _handle_search(self, intent: dict) -> dict:
        """Handle general search."""
        entity = intent.get("entity") or intent.get("original_question", "")
        matches = self.kg.search_by_synonym(entity)

        if matches:
            return {
                "type": "search_results",
                "query": entity,
                "count": len(matches),
                "results": [
                    {"name": t.name, "domain": t.domain, "confidence": round(c, 2),
                     "type": t.information_type, "is_pii": t.is_pii}
                    for t, c in matches[:10]
                ],
            }
        return {"type": "search_results", "query": entity, "count": 0, "results": []}

    def _handle_stats(self, intent: dict) -> dict:
        """Handle aggregate/count questions."""
        filter_domain = intent.get("filter")
        q = intent.get("original_question", "").lower()

        all_terms = self.kg.get_all_terms()
        all_domains = list(self.kg.domains.values())
        all_apps = list(self.kg.applications.values())

        stats = {
            "type": "stats",
            "total_terms": len(all_terms),
            "total_domains": len(all_domains),
            "total_applications": len(all_apps),
            "pii_terms": len([t for t in all_terms if t.is_pii]),
            "terms_with_dq": len([t for t in all_terms if t.dq_rules]),
        }

        if filter_domain:
            domain_terms = self.kg.get_terms_by_domain(filter_domain)
            stats["filtered_domain"] = filter_domain
            stats["domain_term_count"] = len(domain_terms)
            # Count BAs related to this domain
            domain_apps = [a for a in all_apps if filter_domain in a.keywords or
                          any(filter_domain in kw for kw in a.keywords)]
            stats["domain_app_count"] = len(domain_apps)
            stats["domain_apps"] = [a.name for a in domain_apps]

        if "business app" in q or "application" in q:
            if filter_domain:
                domain_apps = [a for a in all_apps if filter_domain in a.keywords or
                              any(filter_domain in kw for kw in a.keywords)]
                stats["answer_focus"] = "apps_in_domain"
                stats["domain_apps"] = [{"name": a.name, "description": a.description} for a in domain_apps]
            else:
                stats["answer_focus"] = "total_apps"

        return stats

    def _format_response(self, question: str, data: dict) -> str:
        """Use LLM to format raw API data into a natural answer."""
        # For simple structured data, format directly (faster, no LLM needed)
        data_type = data.get("type", "")

        if data_type == "term_detail":
            t = data["term"]
            lines = [f"**{t['name']}** (BDE)\n"]
            lines.append(f"• Domain: {t['domain']}")
            lines.append(f"• Data Type: {t['data_type']}")
            lines.append(f"• Information Type: {t['information_type']}")
            lines.append(f"• PII: {'Yes 🔴' if t['is_pii'] else 'No 🟢'}")
            if t.get('dq_rules'):
                lines.append(f"• DQ Rules: {json.dumps(t['dq_rules'])}")
            if t.get('synonyms'):
                lines.append(f"• Synonyms: {', '.join(t['synonyms'][:5])}")
            if t.get('reference_code_set'):
                lines.append(f"• Reference Set: {t['reference_code_set']}")
            return "\n".join(lines)

        if data_type == "term_list":
            domain = data.get("domain_filter")
            header = f"**BDEs in {domain} domain**" if domain else "**All BDEs in Glossary**"
            lines = [f"{header} ({data['count']} terms):\n"]
            for t in data["terms"][:20]:
                pii = " 🔴" if t["is_pii"] else ""
                dq = f" [{', '.join(t['dq_rules'])}]" if t["dq_rules"] else ""
                lines.append(f"• **{t['name']}**{pii} ({t['type']}){dq}")
            if data["count"] > 20:
                lines.append(f"\n... and {data['count'] - 20} more")
            return "\n".join(lines)

        if data_type == "domain_list":
            lines = [f"**Data Domains** ({data['count']}):\n"]
            for d in data["domains"]:
                lines.append(f"• **{d['name']}** — {d['description']} ({d['term_count']} terms)")
            return "\n".join(lines)

        if data_type == "domain_detail":
            d = data["domain"]
            lines = [f"**{d['name']}** domain\n"]
            lines.append(f"• Description: {d['description']}")
            lines.append(f"• Terms: {data['term_count']}\n")
            for t in data["terms"][:15]:
                pii = " 🔴" if t["is_pii"] else ""
                lines.append(f"  • {t['name']}{pii} ({t['type']})")
            return "\n".join(lines)

        if data_type == "app_list":
            filt = f" (filtered: {data['filter']})" if data.get("filter") else ""
            lines = [f"**Business Applications**{filt} ({data['count']}):\n"]
            for a in data["apps"]:
                lines.append(f"• **{a['name']}** — {a['description']}")
                lines.append(f"  Keywords: {', '.join(a['keywords'])}")
            return "\n".join(lines)

        if data_type == "app_detail":
            a = data["app"]
            return (f"**{a['name']}**\n\n"
                    f"• Description: {a['description']}\n"
                    f"• Keywords: {', '.join(a['keywords'])}")

        if data_type == "dq_detail":
            lines = [f"**DQ Rules for: {data['term']}**\n"]
            for k, v in data["dq_rules"].items():
                lines.append(f"• {k}: {v}")
            if data.get("reference_code_set"):
                lines.append(f"• Reference set: {data['reference_code_set']}")
            lines.append(f"\n_{data['explanation']}_")
            return "\n".join(lines)

        if data_type == "dq_list":
            lines = [f"**BDEs with DQ Rules** ({data['count']}):\n"]
            for t in data["terms"][:15]:
                rules = ", ".join(f"{k}={v}" if not isinstance(v, bool) else k for k, v in t["rules"].items())
                lines.append(f"• **{t['name']}** [{t['domain']}]: {rules}")
            return "\n".join(lines)

        if data_type == "pii_list":
            lines = [f"**PII Fields** ({data['count']} BDEs classified as PII):\n"]
            for t in data["terms"]:
                lines.append(f"• **{t['name']}** [{t['domain']}] — {t['classification']}")
                lines.append(f"  Synonyms: {', '.join(t['synonyms'])}")
            return "\n".join(lines)

        if data_type == "search_results":
            if data["count"] == 0:
                return f"No results found for \"{data['query']}\". Try a different term or check the glossary."
            lines = [f"**Search results for \"{data['query']}\"** ({data['count']} matches):\n"]
            for r in data["results"]:
                pii = " 🔴" if r["is_pii"] else ""
                lines.append(f"• **{r['name']}**{pii} [{r['domain']}] ({r['type']}) — {r['confidence']*100:.0f}% match")
            return "\n".join(lines)

        if data_type == "stats":
            lines = []
            if data.get("answer_focus") == "apps_in_domain":
                apps = data.get("domain_apps", [])
                lines.append(f"**{len(apps)} business application(s)** in the {data.get('filtered_domain', '?')} domain:\n")
                for a in apps:
                    lines.append(f"• **{a['name']}** — {a['description']}")
                if not apps:
                    lines.append("No business applications found for this domain.")
            elif data.get("filtered_domain"):
                lines.append(f"**Stats for {data['filtered_domain']} domain:**\n")
                lines.append(f"• BDEs: {data.get('domain_term_count', '?')}")
                lines.append(f"• Business Apps: {data.get('domain_app_count', '?')}")
                if data.get("domain_apps"):
                    lines.append(f"• Apps: {', '.join(data['domain_apps'])}")
            else:
                lines.append("**Catalog Statistics:**\n")
                lines.append(f"• Total BDEs: {data['total_terms']}")
                lines.append(f"• Domains: {data['total_domains']}")
                lines.append(f"• Business Applications: {data['total_applications']}")
                lines.append(f"• PII terms: {data['pii_terms']}")
                lines.append(f"• Terms with DQ rules: {data['terms_with_dq']}")
            return "\n".join(lines)

        # Fallback: dump as formatted JSON
        return f"```json\n{json.dumps(data, indent=2, default=str)}\n```"

    def _fallback_answer(self, question) -> str:
        """When intent can't be determined."""
        if isinstance(question, dict):
            question = question.get("original_question", str(question))
        return (
            "I can answer questions about:\n"
            "• **Glossary**: \"What BDEs are in the Customer domain?\"\n"
            "• **Domains**: \"Show me all domains\" or \"How many terms in Credit?\"\n"
            "• **Business Apps**: \"How many BAs are in the Credit domain?\"\n"
            "• **DQ Rules**: \"What DQ rules apply to Credit Score?\"\n"
            "• **PII**: \"Which fields are PII?\"\n"
            "• **Relationships**: \"What datasets use Customer ID?\"\n"
            "• **Search**: \"Find terms related to payment\"\n\n"
            "Or onboard data: \"Onboard customer complaints\""
        )
