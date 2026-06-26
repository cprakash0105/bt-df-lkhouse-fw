"""Data Profiler — Analyzes sample data for better SD recommendations.
Detects types, PII patterns, cardinality, uniqueness, value ranges.
Runs in-memory (Cloud Run) with ~100MB sample cap."""
import re
import csv
import io
from dataclasses import dataclass, field
from typing import Optional
from collections import Counter


# PII regex patterns
PII_PATTERNS = {
    "pan": re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$"),
    "aadhaar": re.compile(r"^\d{12}$"),
    "email": re.compile(r"^[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}$"),
    "phone": re.compile(r"^[+]?\d{10,13}$"),
    "credit_card": re.compile(r"^\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}$"),
    "ipv4": re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),
    "uuid": re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE),
}

# Date patterns
DATE_PATTERNS = [
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),  # YYYY-MM-DD
    re.compile(r"^\d{2}/\d{2}/\d{4}$"),  # DD/MM/YYYY
    re.compile(r"^\d{2}-\d{2}-\d{4}$"),  # DD-MM-YYYY
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"),  # ISO timestamp
]


@dataclass
class ColumnProfile:
    name: str
    total_rows: int = 0
    null_count: int = 0
    null_pct: float = 0.0
    distinct_count: int = 0
    cardinality_ratio: float = 0.0  # distinct/total
    inferred_type: str = "string"
    declared_type: Optional[str] = None
    min_value: Optional[str] = None
    max_value: Optional[str] = None
    mean_value: Optional[float] = None
    sample_values: list = field(default_factory=list)
    distinct_values: Optional[list] = None  # only if cardinality < 20
    detected_patterns: list = field(default_factory=list)  # e.g., ["pan", "email"]
    is_likely_pii: bool = False
    is_likely_identifier: bool = False
    is_likely_reference: bool = False
    suggested_dq: dict = field(default_factory=dict)


@dataclass
class DataProfile:
    row_count: int = 0
    column_count: int = 0
    columns: list = field(default_factory=list)  # list of ColumnProfile


class Profiler:
    """Profiles sample data to enhance SD recommendations."""

    def __init__(self, max_rows: int = 10000):
        self.max_rows = max_rows

    def profile_csv(self, content: str) -> DataProfile:
        """Profile CSV content (string)."""
        reader = csv.DictReader(io.StringIO(content))
        rows = []
        for i, row in enumerate(reader):
            if i >= self.max_rows:
                break
            rows.append(row)

        if not rows:
            return DataProfile()

        columns = list(rows[0].keys())
        return self._profile_rows(rows, columns)

    def profile_jsonl(self, content: str) -> DataProfile:
        """Profile JSONL content (string)."""
        import json
        rows = []
        for line in content.strip().split("\n"):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
            if len(rows) >= self.max_rows:
                break

        if not rows:
            return DataProfile()

        columns = list(rows[0].keys())
        return self._profile_rows(rows, columns)

    def profile_pasted(self, content: str) -> DataProfile:
        """Profile pasted tabular data (auto-detect delimiter)."""
        lines = content.strip().split("\n")
        if not lines:
            return DataProfile()

        # Detect delimiter
        first_line = lines[0]
        if "\t" in first_line:
            delimiter = "\t"
        elif "|" in first_line:
            delimiter = "|"
        elif "," in first_line:
            delimiter = ","
        else:
            # Try CSV parsing
            return self.profile_csv(content)

        reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
        rows = []
        for i, row in enumerate(reader):
            if i >= self.max_rows:
                break
            rows.append(row)

        if not rows:
            return DataProfile()

        columns = list(rows[0].keys())
        return self._profile_rows(rows, columns)

    def _profile_rows(self, rows: list[dict], columns: list[str]) -> DataProfile:
        """Core profiling logic."""
        profile = DataProfile(row_count=len(rows), column_count=len(columns))

        for col in columns:
            col_profile = self._profile_column(col, rows)
            profile.columns.append(col_profile)

        return profile

    def _profile_column(self, col_name: str, rows: list[dict]) -> ColumnProfile:
        """Profile a single column."""
        values = [row.get(col_name, "") for row in rows]
        total = len(values)

        # Null analysis
        non_null = [v for v in values if v and str(v).strip() and str(v).lower() not in ("null", "none", "na", "")]
        null_count = total - len(non_null)
        null_pct = null_count / total if total > 0 else 0

        # Distinct values
        distinct = set(str(v).strip() for v in non_null)
        distinct_count = len(distinct)
        cardinality_ratio = distinct_count / total if total > 0 else 0

        cp = ColumnProfile(
            name=col_name.strip(),
            total_rows=total,
            null_count=null_count,
            null_pct=round(null_pct, 3),
            distinct_count=distinct_count,
            cardinality_ratio=round(cardinality_ratio, 3),
        )

        # Sample values (first 5 non-null)
        cp.sample_values = [str(v) for v in non_null[:5]]

        # Low cardinality → list all distinct values
        if distinct_count <= 20 and distinct_count > 0:
            cp.distinct_values = sorted(list(distinct))[:20]

        # Type inference
        cp.inferred_type = self._infer_type(non_null)

        # Numeric stats
        if cp.inferred_type in ("integer", "decimal"):
            numeric_vals = []
            for v in non_null:
                try:
                    numeric_vals.append(float(str(v).replace(",", "")))
                except (ValueError, TypeError):
                    pass
            if numeric_vals:
                cp.min_value = str(min(numeric_vals))
                cp.max_value = str(max(numeric_vals))
                cp.mean_value = round(sum(numeric_vals) / len(numeric_vals), 2)

        # Pattern detection (PII)
        detected = self._detect_patterns(non_null)
        cp.detected_patterns = detected
        if any(p in detected for p in ["pan", "aadhaar", "email", "phone", "credit_card"]):
            cp.is_likely_pii = True

        # Identifier detection
        if cardinality_ratio > 0.95 and null_pct < 0.01:
            cp.is_likely_identifier = True

        # Reference/enum detection
        if 0 < distinct_count <= 15 and cardinality_ratio < 0.05:
            cp.is_likely_reference = True

        # Suggest DQ rules
        cp.suggested_dq = self._suggest_dq(cp)

        return cp

    def _infer_type(self, values: list) -> str:
        """Infer the actual data type from values."""
        if not values:
            return "string"

        sample = values[:100]
        type_counts = Counter()

        for v in sample:
            s = str(v).strip()
            if not s:
                continue

            # Integer
            try:
                int(s.replace(",", ""))
                type_counts["integer"] += 1
                continue
            except (ValueError, TypeError):
                pass

            # Decimal
            try:
                float(s.replace(",", ""))
                type_counts["decimal"] += 1
                continue
            except (ValueError, TypeError):
                pass

            # Boolean
            if s.lower() in ("true", "false", "yes", "no", "y", "n", "1", "0"):
                type_counts["boolean"] += 1
                continue

            # Date
            if any(p.match(s) for p in DATE_PATTERNS):
                type_counts["date"] += 1
                continue

            type_counts["string"] += 1

        if not type_counts:
            return "string"

        # Majority type wins (with 70% threshold)
        total_checked = sum(type_counts.values())
        for dtype, count in type_counts.most_common():
            if count / total_checked >= 0.7:
                return dtype

        return "string"

    def _detect_patterns(self, values: list) -> list[str]:
        """Detect PII and other patterns in values."""
        if not values:
            return []

        sample = [str(v).strip() for v in values[:200]]
        detected = []

        for pattern_name, pattern in PII_PATTERNS.items():
            matches = sum(1 for v in sample if pattern.match(v))
            match_ratio = matches / len(sample)
            if match_ratio >= 0.7:
                detected.append(pattern_name)

        # Date detection
        date_matches = sum(1 for v in sample if any(p.match(v) for p in DATE_PATTERNS))
        if date_matches / len(sample) >= 0.7:
            detected.append("date")

        return detected

    def _suggest_dq(self, cp: ColumnProfile) -> dict:
        """Suggest DQ rules based on profile."""
        dq = {}

        # Not null (if current data has <5% nulls)
        if cp.null_pct < 0.05:
            dq["not_null"] = True

        # Unique (if likely identifier)
        if cp.is_likely_identifier:
            dq["unique"] = True

        # Positive (if numeric and all values > 0)
        if cp.inferred_type in ("integer", "decimal") and cp.min_value:
            if float(cp.min_value) >= 0:
                dq["positive"] = True

        # Range (if numeric)
        if cp.inferred_type in ("integer", "decimal") and cp.min_value and cp.max_value:
            dq["range"] = [float(cp.min_value), float(cp.max_value)]

        # Accepted values (if low cardinality)
        if cp.is_likely_reference and cp.distinct_values:
            dq["accepted_values"] = cp.distinct_values

        # Format (if pattern detected)
        if "pan" in cp.detected_patterns:
            dq["format"] = "pan"
        elif "email" in cp.detected_patterns:
            dq["format"] = "email"
        elif "aadhaar" in cp.detected_patterns:
            dq["format"] = "aadhaar"

        return dq


def format_profile_report(profile: DataProfile) -> str:
    """Format profile results for display in Chainlit."""
    lines = [f"## Data Profile Report\n"]
    lines.append(f"**Rows:** {profile.row_count} | **Columns:** {profile.column_count}\n")

    lines.append("| Column | Type | Nulls | Distinct | PII | Pattern | Key? |")
    lines.append("|--------|------|-------|----------|-----|---------|------|")

    for col in profile.columns:
        pii = "YES" if col.is_likely_pii else "-"
        pattern = ", ".join(col.detected_patterns) if col.detected_patterns else "-"
        key = "PK" if col.is_likely_identifier else ("REF" if col.is_likely_reference else "-")
        lines.append(
            f"| `{col.name}` | {col.inferred_type} | {col.null_pct:.0%} "
            f"| {col.distinct_count} ({col.cardinality_ratio:.0%}) "
            f"| {pii} | {pattern} | {key} |"
        )

    # Details for interesting columns
    interesting = [c for c in profile.columns if c.is_likely_pii or c.is_likely_reference or c.detected_patterns]
    if interesting:
        lines.append("\n### Notable Findings\n")
        for col in interesting:
            lines.append(f"**`{col.name}`**")
            if col.is_likely_pii:
                lines.append(f"  - Likely PII (pattern: {', '.join(col.detected_patterns)})")
            if col.is_likely_reference and col.distinct_values:
                lines.append(f"  - Reference values: {col.distinct_values}")
            if col.sample_values:
                lines.append(f"  - Sample: {col.sample_values[:3]}")
            if col.suggested_dq:
                lines.append(f"  - Suggested DQ: {col.suggested_dq}")
            lines.append("")

    return "\n".join(lines)
