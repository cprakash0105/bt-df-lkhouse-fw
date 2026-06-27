"""Natural Language Parser — Converts conversational input into structured asset definitions.
Uses Vertex AI Gemini to understand steward's natural language and extract field definitions."""
import os
import json
from typing import Optional


SYSTEM_PROMPT = """You are a data catalog assistant. Extract a structured dataset definition from the user's natural language.

Rules:
1. Extract ALL field/column names mentioned by the user
2. Infer a snake_case dataset name from context
3. Infer data types for each field based on naming conventions:
   - Fields ending in _id, _key, _no, _ref, or containing name/email/phone/address/number → string
   - Fields ending in _score, _count, _qty → integer  
   - Fields ending in _amount, _amt, _price, _cost, _rate → decimal
   - Fields ending in _date, _dt → date
   - Fields ending in _ts, _timestamp, _time, _at → timestamp
   - Fields with is_, has_, _flag → boolean
   - Default → string

Return ONLY a valid JSON object with this exact structure:
{"name": "dataset_name", "fields": [{"name": "field_name", "type": "data_type"}, ...]}

Do NOT include any explanation, markdown, or text outside the JSON.

Example input: "I have a new customer feed with customer_id, name, email and signup_date"
Example output: {"name": "customer_feed", "fields": [{"name": "customer_id", "type": "string"}, {"name": "name", "type": "string"}, {"name": "email", "type": "string"}, {"name": "signup_date", "type": "date"}]}

IMPORTANT: Extract EVERY field mentioned. Do not skip any."""


class NLParser:
    """Parses natural language into structured asset definitions using Vertex AI Gemini."""

    def __init__(self, project_id: Optional[str] = None, region: str = "us-central1"):
        self.project_id = project_id or os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
        self.region = region
        self._model = None

    def parse(self, text: str) -> Optional[dict]:
        """Parse natural language text into an asset definition dict."""
        # Try Vertex AI Gemini first
        result = self._parse_with_gemini(text)
        if result:
            return result

        # Fallback: simple keyword extraction (no LLM)
        return self._parse_simple(text)

    def _parse_with_gemini(self, text: str) -> Optional[dict]:
        """Use LLM to parse NL."""
        from discovery.engine.llm_client import get_llm

        response_text = get_llm().generate(system=SYSTEM_PROMPT, user=text, max_tokens=1024)
        if not response_text:
            return None

        try:
            parsed = json.loads(response_text)
            if isinstance(parsed, dict) and "fields" in parsed:
                return parsed
        except Exception as e:
            print(f"[NLParser] Failed to parse LLM response: {e}")

        return None

    def _parse_simple(self, text: str) -> Optional[dict]:
        """Fallback: extract field names from text without LLM."""
        text_lower = text.lower()

        # Try to extract dataset name
        name = None
        # Look for patterns like "new CIBIL bureau feed" or "cibil_bureau_feed"
        name_indicators = ["new ", "onboard ", "feed ", "dataset ", "table ", "source "]
        for indicator in name_indicators:
            if indicator in text_lower:
                idx = text_lower.index(indicator) + len(indicator)
                # Grab the next few words until "with", "from", "containing" etc
                remaining = text[idx:]
                stop_words = [" with ", " from ", " containing ", " has ", " fields "]
                for sw in stop_words:
                    if sw in remaining.lower():
                        remaining = remaining[:remaining.lower().index(sw)]
                        break
                name_candidate = remaining.strip().split("\n")[0].strip()
                if name_candidate and len(name_candidate) > 2:
                    name = name_candidate.replace(" ", "_").replace("-", "_").lower()
                    name = name.strip(".,;:'\"")
                    break

        if not name:
            # Look for snake_case words as dataset name
            words = text.replace(",", " ").split()
            for w in words:
                if "_" in w and len(w) > 5 and "feed" in w.lower() or "table" in w.lower():
                    name = w.lower().strip(".,;:'\"")
                    break

        if not name:
            name = "unnamed_dataset"

        # Extract field names - look for snake_case words or words with underscores
        fields = []
        # Split on common separators
        text_cleaned = text.replace(" and ", ", ").replace(" & ", ", ")
        words = text_cleaned.replace(";", ",").split(",")

        for chunk in words:
            # Find snake_case tokens in each chunk
            tokens = chunk.strip().split()
            for token in tokens:
                t = token.strip().lower().strip(".,;:'\"")
                if "_" in t and len(t) > 2 and t != name:
                    field_type = self._infer_type(t)
                    fields.append({"name": t, "type": field_type})

        if fields:
            return {"name": name, "fields": fields}

        return None

    def _infer_type(self, field_name: str) -> str:
        """Infer field type from name."""
        name = field_name.lower()
        if any(s in name for s in ["_id", "_key", "_no", "_code", "_ref", "name", "email", "phone", "address", "status"]):
            return "string"
        if any(s in name for s in ["_amt", "_amount", "_price", "_cost", "_rate", "_pct", "_balance"]):
            return "decimal"
        if any(s in name for s in ["_count", "_num", "_score", "_qty"]):
            return "integer"
        if any(s in name for s in ["_date", "_dt", "_dob"]):
            return "date"
        if any(s in name for s in ["_ts", "_timestamp", "_time", "_at"]):
            return "timestamp"
        if any(s in name for s in ["is_", "has_", "_flag", "_ind"]):
            return "boolean"
        return "string"
