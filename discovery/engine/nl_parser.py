"""Natural Language Parser — Converts conversational input into structured asset definitions.
Uses LLM to understand steward's natural language and extract field definitions.

Fixes from previous version:
- Single-word fields (channel, category, status, priority) now parsed
- "feed" suffix no longer added inconsistently
- Multi-feed support: parse one prompt describing multiple datasets in a domain
"""
import os
import json
import re
from typing import Optional


SYSTEM_PROMPT = """Extract dataset fields from text. Return JSON only.
Format: {"name":"snake_case_name","fields":[{"name":"x","type":"t"}]}
Types: string,integer,decimal,date,timestamp,boolean
Infer type from suffix: _id/_ref→string, _score/_count→integer, _amount/_amt→decimal, _date/_dt→date, _ts→timestamp, is_/has_→boolean. Default→string.
Extract ALL fields. No explanation."""

MULTI_FEED_SYSTEM = """Extract MULTIPLE dataset definitions from text. Return JSON array.
Format: [{"name":"snake_case_name","fields":[{"name":"x","type":"t"}]}, ...]
Types: string,integer,decimal,date,timestamp,boolean
Each dataset should have its own name and complete field list.
Infer types from names. No explanation. Return only the JSON array."""


class NLParser:
    """Parses natural language into structured asset definitions."""

    # Known single-word field names that are valid
    KNOWN_SINGLE_FIELDS = {
        "channel", "category", "status", "priority", "amount", "currency",
        "region", "tier", "type", "mode", "source", "description", "name",
        "email", "phone", "address", "score", "balance", "quantity", "price",
        "rating", "level", "grade", "rank", "role", "gender", "age",
        "city", "state", "country", "pincode", "zipcode",
    }

    # Suffixes to strip from dataset names
    STRIP_SUFFIXES = ["_feed", "_table", "_source", "_data", "_file"]

    def __init__(self, project_id: Optional[str] = None, region: str = "us-central1"):
        self.project_id = project_id or os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
        self.region = region

    def parse(self, text: str) -> Optional[dict]:
        """Parse natural language text into an asset definition dict.
        Tries local extraction first (free), LLM only if local fails."""
        result = self._parse_simple(text)
        if result and len(result.get("fields", [])) >= 2:
            return result

        # Local couldn't extract enough — use LLM
        result = self._parse_with_llm(text)
        if result:
            return result

        return self._parse_simple(text)

    def parse_multi(self, text: str) -> Optional[list[dict]]:
        """Parse text describing multiple datasets (domain-level onboarding).
        Returns list of asset definitions."""
        # Try local multi-feed extraction
        result = self._parse_multi_local(text)
        if result and len(result) >= 2:
            return result

        # Use LLM for multi-feed
        return self._parse_multi_llm(text)

    def _parse_with_llm(self, text: str) -> Optional[dict]:
        """Use LLM to parse NL."""
        from discovery.engine.llm_client import get_llm

        response_text = get_llm().generate(system=SYSTEM_PROMPT, user=text, max_tokens=512)
        if not response_text or response_text == "__QUOTA_EXCEEDED__":
            return None

        try:
            parsed = json.loads(response_text)
            if isinstance(parsed, dict) and "fields" in parsed:
                parsed["name"] = self._clean_name(parsed.get("name", ""))
                return parsed
        except Exception as e:
            print(f"[NLParser] Failed to parse LLM response: {e}")

        return None

    def _parse_multi_llm(self, text: str) -> Optional[list[dict]]:
        """Use LLM to parse multi-feed description."""
        from discovery.engine.llm_client import get_llm

        response_text = get_llm().generate(system=MULTI_FEED_SYSTEM, user=text, max_tokens=2048)
        if not response_text or response_text == "__QUOTA_EXCEEDED__":
            return None

        try:
            # Handle markdown fences
            clean = response_text.strip()
            if clean.startswith("```"):
                clean = "\n".join(l for l in clean.split("\n") if not l.strip().startswith("```"))
                if clean.startswith("json"):
                    clean = clean[4:]

            parsed = json.loads(clean.strip())
            if isinstance(parsed, list):
                for item in parsed:
                    item["name"] = self._clean_name(item.get("name", ""))
                return parsed
        except Exception as e:
            print(f"[NLParser] Failed to parse multi-feed LLM response: {e}")

        return None

    def _parse_multi_local(self, text: str) -> Optional[list[dict]]:
        """Try to extract multiple datasets from structured text locally.
        Looks for patterns like numbered lists or dataset headers."""
        datasets = []

        # Pattern: "1. motor_policy: field1, field2..." or "- motor_policy with field1, field2"
        # Split by numbered list or dashes that start a new dataset
        segments = re.split(r'\n\s*(?:\d+[\.\)]\s*|[-•]\s+)(?=[a-z_])', text)

        if len(segments) < 2:
            # Try splitting by "Dataset:" or similar headers
            segments = re.split(r'\n\s*(?:dataset|table|feed|source)\s*(?:\d+)?[:\-]\s*', text, flags=re.IGNORECASE)

        if len(segments) < 2:
            return None

        for segment in segments:
            if not segment.strip():
                continue
            result = self._parse_simple(segment.strip())
            if result and result.get("fields"):
                datasets.append(result)

        return datasets if len(datasets) >= 2 else None

    def _parse_simple(self, text: str) -> Optional[dict]:
        """Extract field names from text — handles both snake_case and single-word fields."""
        text_lower = text.lower()

        # Extract dataset name
        name = self._extract_name(text, text_lower)

        # Extract fields
        fields = self._extract_fields(text, text_lower, name)

        if fields:
            return {"name": name, "fields": fields}
        return None

    def _extract_name(self, text: str, text_lower: str) -> str:
        """Extract dataset name from text."""
        # Look for explicit snake_case name
        snake_match = re.search(r'\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b', text_lower)

        # Look for name after keywords
        name_patterns = [
            r'(?:new|onboard|discover|add)\s+([a-z][a-z0-9_\s]+?)(?:\s+(?:with|from|containing|has|fields|dataset|table))',
            r'(?:dataset|table|feed|source)\s*(?:named?|called?)?\s*[:\-]?\s*([a-z][a-z0-9_\s]+?)(?:\s+(?:with|from|containing|has|fields)|\s*$)',
        ]

        for pattern in name_patterns:
            m = re.search(pattern, text_lower)
            if m:
                candidate = m.group(1).strip()
                candidate = candidate.replace(" ", "_").replace("-", "_")
                candidate = re.sub(r'_+', '_', candidate).strip("_")
                if len(candidate) > 2:
                    return self._clean_name(candidate)

        # Use first snake_case word that looks like a dataset name
        if snake_match:
            candidate = snake_match.group(1)
            if len(candidate) > 4:
                return self._clean_name(candidate)

        return "unnamed_dataset"

    def _extract_fields(self, text: str, text_lower: str, dataset_name: str) -> list[dict]:
        """Extract field names — both snake_case and single-word."""
        fields = []
        seen = set()

        # Normalize separators
        text_cleaned = text.replace(" and ", ", ").replace(" & ", ", ")
        text_cleaned = text_cleaned.replace(";", ",")

        # Strategy 1: Find all snake_case words
        snake_words = re.findall(r'\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b', text_cleaned.lower())
        for word in snake_words:
            if word != dataset_name and word not in seen and len(word) > 2:
                # Skip common non-field words
                if word in ("not_null", "is_pii", "primary_key", "foreign_key", "data_type"):
                    continue
                seen.add(word)
                fields.append({"name": word, "type": self._infer_type(word)})

        # Strategy 2: Find single-word fields after "with" or in comma-separated lists
        # Look for the field list section (after "with", "fields:", "containing", etc.)
        field_section_match = re.search(
            r'(?:with|fields?|containing|has|columns?)[:\s]+(.+)',
            text_cleaned, re.IGNORECASE | re.DOTALL
        )

        if field_section_match:
            field_section = field_section_match.group(1)
        else:
            field_section = text_cleaned

        # Split the field section by commas and check each token
        chunks = field_section.split(",")
        for chunk in chunks:
            tokens = chunk.strip().split()
            for token in tokens:
                t = token.strip().lower().strip(".,;:'\"()[]")
                if not t or len(t) < 2:
                    continue
                # Already found as snake_case
                if t in seen:
                    continue
                # Skip if it's the dataset name
                if t == dataset_name or t in dataset_name.split("_"):
                    continue
                # Accept if it's a known single-word field
                if t in self.KNOWN_SINGLE_FIELDS:
                    seen.add(t)
                    fields.append({"name": t, "type": self._infer_type(t)})
                # Accept if preceded by field-indicating context
                elif self._is_likely_field_word(t, chunk):
                    seen.add(t)
                    fields.append({"name": t, "type": self._infer_type(t)})

        return fields

    def _is_likely_field_word(self, word: str, context: str) -> bool:
        """Determine if a single word is likely a field name from context."""
        # Must be a valid identifier (alphanumeric)
        if not re.match(r'^[a-z][a-z0-9]*$', word):
            return False
        # Skip common English words that aren't fields
        noise = {
            "the", "and", "for", "with", "from", "has", "have", "this", "that",
            "new", "all", "each", "its", "also", "like", "want", "need", "use",
            "can", "will", "should", "would", "could", "about", "into", "over",
            "such", "some", "any", "than", "then", "them", "these", "those",
            "been", "being", "which", "where", "when", "what", "who", "how",
            "not", "but", "yet", "only", "just", "more", "most", "very",
            "track", "monitor", "store", "feed", "data", "table", "field",
            "column", "dataset", "schema", "type", "string", "integer", "decimal",
            "date", "boolean", "timestamp", "domain", "system",
        }
        if word in noise:
            return False
        # Longer words in a comma-separated context are likely fields
        if len(word) >= 4:
            return True
        return False

    def _clean_name(self, name: str) -> str:
        """Clean dataset name — remove inconsistent suffixes."""
        name = name.strip().lower()
        name = re.sub(r'[^a-z0-9_]', '_', name)
        name = re.sub(r'_+', '_', name).strip("_")

        # Don't strip suffix if the name IS the suffix (e.g., user typed "cibil_feed" intentionally)
        # Only strip if it was appended by our parser
        # Actually, keep the name as-is — the user said it
        return name

    def _infer_type(self, field_name: str) -> str:
        """Infer field type from name."""
        name = field_name.lower()
        if any(s in name for s in ["_id", "_key", "_no", "_code", "_ref", "name", "email", "phone", "address", "status"]):
            return "string"
        if any(s in name for s in ["_amt", "_amount", "_price", "_cost", "_rate", "_pct", "_balance", "premium", "amount"]):
            return "decimal"
        if any(s in name for s in ["_count", "_num", "_score", "_qty", "score", "age", "quantity"]):
            return "integer"
        if any(s in name for s in ["_date", "_dt", "_dob", "date"]):
            return "date"
        if any(s in name for s in ["_ts", "_timestamp", "_time", "_at", "timestamp"]):
            return "timestamp"
        if any(s in name for s in ["is_", "has_", "_flag", "_ind"]):
            return "boolean"
        # Single-word type hints
        if name in ("amount", "price", "cost", "balance", "premium"):
            return "decimal"
        if name in ("score", "age", "count", "quantity", "rating"):
            return "integer"
        if name in ("date",):
            return "date"
        return "string"
