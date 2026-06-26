"""Natural Language Parser — Converts conversational input into structured asset definitions.
Uses Vertex AI Gemini to understand steward's natural language and extract field definitions."""
import os
import json
from typing import Optional


SYSTEM_PROMPT = """You are a data catalog assistant. Your job is to extract a structured asset definition from the user's natural language description.

Extract:
- name: a snake_case name for the dataset
- fields: list of fields with name (snake_case) and type (string, integer, decimal, date, timestamp, boolean)

Return ONLY valid JSON, no explanation. Example output:
{"name": "cibil_bureau_feed", "fields": [{"name": "customer_id", "type": "string"}, {"name": "cibil_score", "type": "integer"}]}

If the user mentions a field but not its type, infer the most likely type:
- IDs, names, codes, references → string
- Scores, counts, numbers → integer
- Amounts, prices, rates, percentages → decimal
- Dates → date
- Timestamps, times → timestamp
- Flags, indicators → boolean

If the user doesn't give a dataset name, infer one from context."""


class NLParser:
    """Parses natural language into structured asset definitions using Vertex AI Gemini."""

    def __init__(self, project_id: Optional[str] = None, region: str = "europe-west2"):
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
        """Use Vertex AI Gemini to parse NL."""
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel

            vertexai.init(project=self.project_id, location=self.region)
            model = GenerativeModel("gemini-2.0-flash")

            response = model.generate_content(
                [SYSTEM_PROMPT, f"User input: {text}"],
                generation_config={"temperature": 0.1, "max_output_tokens": 2048},
            )

            # Extract JSON from response
            response_text = response.text.strip()
            # Remove markdown code fences if present
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                response_text = "\n".join(lines)

            parsed = json.loads(response_text)
            if isinstance(parsed, dict) and "fields" in parsed:
                return parsed

        except ImportError:
            pass
        except Exception as e:
            print(f"[NLParser] Gemini failed: {e}")

        return None

    def _parse_simple(self, text: str) -> Optional[dict]:
        """Fallback: basic keyword extraction without LLM."""
        text_lower = text.lower()

        # Try to extract dataset name
        name = None
        name_indicators = ["new feed", "new dataset", "new source", "onboard", "table called", "dataset called"]
        for indicator in name_indicators:
            if indicator in text_lower:
                # Try to find the name after the indicator
                idx = text_lower.index(indicator) + len(indicator)
                remaining = text[idx:].strip().split()[0] if idx < len(text) else None
                if remaining:
                    name = remaining.strip(".,;:'\"").replace(" ", "_").lower()
                    break

        if not name:
            # Try to find something that looks like a dataset name
            words = text.replace(",", " ").replace(".", " ").split()
            for w in words:
                if "_" in w and len(w) > 3:
                    name = w.lower()
                    break

        if not name:
            name = "unnamed_dataset"

        # Extract field names (look for things that look like column names)
        fields = []
        # Common patterns: "with fields X, Y, Z" or "columns: X, Y, Z"
        field_indicators = ["fields", "columns", "with", "containing", "has"]

        # Simple approach: find words that look like field names (snake_case or technical)
        words = text.replace(",", " ").replace(".", " ").replace(";", " ").split()
        for word in words:
            w = word.strip().lower()
            if "_" in w and len(w) > 2 and w != name:
                # Looks like a field name
                field_type = self._infer_type(w)
                fields.append({"name": w, "type": field_type})

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
