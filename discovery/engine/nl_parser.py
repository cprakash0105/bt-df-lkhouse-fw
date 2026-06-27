"""Natural Language Parser — Converts conversational input into structured asset definitions.
Uses Vertex AI Gemini to understand steward's natural language and extract field definitions."""
import os
import json
from typing import Optional


SYSTEM_PROMPT = """Extract dataset fields from text. Return JSON only.
Format: {"name":"snake_case_name","fields":[{"name":"x","type":"t"}]}
Types: string,integer,decimal,date,timestamp,boolean
Infer type from suffix: _id/_ref→string, _score/_count→integer, _amount/_amt→decimal, _date/_dt→date, _ts→timestamp, is_/has_→boolean. Default→string.
Extract ALL fields. No explanation."""


class NLParser:
    """Parses natural language into structured asset definitions using Vertex AI Gemini."""

    def __init__(self, project_id: Optional[str] = None, region: str = "us-central1"):
        self.project_id = project_id or os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
        self.region = region
        self._model = None

    def parse(self, text: str) -> Optional[dict]:
        """Parse natural language text into an asset definition dict.
        Tries local extraction first (free), LLM only if local fails."""
        # Try local extraction first — zero token cost
        result = self._parse_simple(text)
        if result and len(result.get("fields", [])) >= 2:
            return result

        # Local couldn't extract enough fields — use LLM
        result = self._parse_with_gemini(text)
        if result:
            return result

        # Return whatever local found (even if partial)
        return self._parse_simple(text)

    def _parse_with_gemini(self, text: str) -> Optional[dict]:
        """Use LLM to parse NL."""
        from discovery.engine.llm_client import get_llm

        response_text = get_llm().generate(system=SYSTEM_PROMPT, user=text, max_tokens=512)
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
