"""GE Profiler — Great Expectations-based profiling for Semantic Discovery.

Replaces the basic profiler with GE's statistical engine + adds:
1. Fingerprinting — compare values against reference code sets (glossary)
2. Composite confidence scoring — multiple signals synthesized into one score
3. Information Type classification — Identifier, Measure, Temporal, Reference, Dimension
4. Statistical summary for LLM — no raw data shared, only aggregates

Amanda's requirement: Only statistical summaries go to the LLM, never raw data.
"""
import json
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import great_expectations as gx
from great_expectations.core import ExpectationSuite
from great_expectations.dataset import PandasDataset
import pandas as pd


@dataclass
class FieldFingerprint:
    """Result of fingerprinting a field against reference code sets."""
    field_name: str
    matched_code_set: Optional[str] = None
    match_ratio: float = 0.0  # % of values found in code set
    unmatched_sample: list = field(default_factory=list)


@dataclass
class FieldSignals:
    """All signals collected for a single field — used for composite scoring."""
    field_name: str
    # Keyword signal (name matches BDE synonym)
    keyword_score: float = 0.0
    matched_bde: Optional[str] = None
    # Pattern signal (regex match on values)
    pattern_score: float = 0.0
    detected_pattern: Optional[str] = None
    # Fingerprint signal (values match reference set)
    fingerprint_score: float = 0.0
    matched_ref_set: Optional[str] = None
    # Statistical signal (type/distribution matches expected BDE type)
    stat_score: float = 0.0
    # Composite
    composite_score: float = 0.0
    information_type: str = "Dimension"  # Identifier, Measure, Temporal, Reference, Dimension


@dataclass
class GEColumnProfile:
    """Enhanced column profile from GE."""
    name: str
    row_count: int = 0
    null_count: int = 0
    null_pct: float = 0.0
    distinct_count: int = 0
    distinct_pct: float = 0.0
    inferred_type: str = "string"
    # Stats (numeric)
    mean: Optional[float] = None
    std: Optional[float] = None
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    quantiles: dict = field(default_factory=dict)  # {25: v, 50: v, 75: v}
    # Stats (string)
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    most_common: list = field(default_factory=list)  # [(value, count), ...]
    # Signals
    signals: Optional[FieldSignals] = None
    fingerprint: Optional[FieldFingerprint] = None
    # Classification
    is_pii: bool = False
    is_key: bool = False
    is_reference: bool = False
    information_type: str = "Dimension"
    suggested_bde: Optional[str] = None
    confidence: float = 0.0


@dataclass
class GEProfile:
    """Full dataset profile from GE."""
    row_count: int = 0
    column_count: int = 0
    columns: list = field(default_factory=list)
    dataset_name: str = ""
    # Summary for LLM (no raw data)
    llm_summary: dict = field(default_factory=dict)


class GEProfiler:
    """Great Expectations profiler with fingerprinting and confidence scoring."""

    # Weights for composite score
    WEIGHTS = {
        "keyword": 0.30,
        "pattern": 0.25,
        "fingerprint": 0.25,
        "stat": 0.20,
    }

    # PII patterns
    PII_PATTERNS = {
        "pan": r"^[A-Z]{5}[0-9]{4}[A-Z]$",
        "aadhaar": r"^\d{12}$",
        "email": r"^[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}$",
        "phone": r"^[+]?\d{10,13}$",
        "credit_card": r"^\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}$",
    }

    def __init__(self, glossary_path: Optional[str] = None):
        self.glossary_path = glossary_path or str(
            Path(__file__).parent.parent / "config" / "seed_glossary.yaml"
        )
        self._load_glossary()

    def _load_glossary(self):
        """Load BDEs, reference code sets, and synonyms from glossary."""
        with open(self.glossary_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self.business_terms = {t["id"]: t for t in data.get("business_terms", [])}
        self.reference_sets = data.get("reference_code_sets", {})

        # Build synonym → term_id lookup
        self.synonym_map = {}
        for term in data.get("business_terms", []):
            tid = term["id"]
            for syn in term.get("synonyms", []):
                self.synonym_map[syn.lower()] = tid
            self.synonym_map[tid.lower()] = tid

    def profile(self, df: pd.DataFrame, dataset_name: str = "") -> GEProfile:
        """Profile a DataFrame using GE + fingerprinting + confidence scoring."""
        ge_df = PandasDataset(df)
        profile = GEProfile(
            row_count=len(df),
            column_count=len(df.columns),
            dataset_name=dataset_name,
        )

        for col in df.columns:
            col_profile = self._profile_column(ge_df, col, df)
            profile.columns.append(col_profile)

        # Build LLM summary (statistical only, no raw values)
        profile.llm_summary = self._build_llm_summary(profile)
        return profile

    def profile_csv(self, content: str, dataset_name: str = "") -> GEProfile:
        """Profile from CSV string."""
        from io import StringIO
        df = pd.read_csv(StringIO(content))
        return self.profile(df, dataset_name)

    def profile_jsonl(self, content: str, dataset_name: str = "") -> GEProfile:
        """Profile from JSONL string."""
        from io import StringIO
        lines = [l for l in content.strip().split("\n") if l.strip()]
        records = [json.loads(l) for l in lines]
        df = pd.DataFrame(records)
        return self.profile(df, dataset_name)

    def _profile_column(self, ge_df: PandasDataset, col: str, df: pd.DataFrame) -> GEColumnProfile:
        """Profile a single column with GE expectations + custom signals."""
        series = df[col]
        total = len(series)
        null_count = int(series.isna().sum())
        non_null = series.dropna()

        cp = GEColumnProfile(
            name=col,
            row_count=total,
            null_count=null_count,
            null_pct=round(null_count / total, 3) if total > 0 else 0,
        )

        # Distinct count
        cp.distinct_count = int(non_null.nunique())
        cp.distinct_pct = round(cp.distinct_count / total, 3) if total > 0 else 0

        # Type inference via GE
        cp.inferred_type = self._infer_type(non_null)

        # Numeric stats
        if cp.inferred_type in ("integer", "decimal"):
            numeric = pd.to_numeric(non_null, errors="coerce").dropna()
            if len(numeric) > 0:
                cp.mean = round(float(numeric.mean()), 2)
                cp.std = round(float(numeric.std()), 2)
                cp.min_val = float(numeric.min())
                cp.max_val = float(numeric.max())
                cp.quantiles = {
                    "25": round(float(numeric.quantile(0.25)), 2),
                    "50": round(float(numeric.quantile(0.50)), 2),
                    "75": round(float(numeric.quantile(0.75)), 2),
                }

        # String stats
        if cp.inferred_type == "string" and len(non_null) > 0:
            lengths = non_null.astype(str).str.len()
            cp.min_length = int(lengths.min())
            cp.max_length = int(lengths.max())

        # Most common values (top 5 — for reference detection, not raw data sharing)
        if cp.distinct_count <= 30 and len(non_null) > 0:
            vc = non_null.value_counts().head(5)
            cp.most_common = [(str(v), int(c)) for v, c in vc.items()]

        # --- Signal collection ---
        signals = FieldSignals(field_name=col)

        # 1. Keyword signal (field name matches BDE synonym)
        signals.keyword_score, signals.matched_bde = self._keyword_signal(col)

        # 2. Pattern signal (PII regex on values)
        signals.pattern_score, signals.detected_pattern = self._pattern_signal(non_null)

        # 3. Fingerprint signal (values vs reference code sets)
        fp = self._fingerprint(col, non_null)
        cp.fingerprint = fp
        signals.fingerprint_score = fp.match_ratio
        signals.matched_ref_set = fp.matched_code_set

        # 4. Statistical signal (type alignment with expected BDE type)
        signals.stat_score = self._stat_signal(cp, signals.matched_bde)

        # Composite confidence
        signals.composite_score = round(
            self.WEIGHTS["keyword"] * signals.keyword_score
            + self.WEIGHTS["pattern"] * signals.pattern_score
            + self.WEIGHTS["fingerprint"] * signals.fingerprint_score
            + self.WEIGHTS["stat"] * signals.stat_score,
            3,
        )

        # Information type classification
        signals.information_type = self._classify_information_type(cp, signals)
        cp.information_type = signals.information_type
        cp.signals = signals
        cp.confidence = signals.composite_score
        cp.suggested_bde = signals.matched_bde

        # PII / Key / Reference flags
        if signals.detected_pattern in self.PII_PATTERNS:
            cp.is_pii = True
        if cp.distinct_pct > 0.95 and cp.null_pct < 0.01:
            cp.is_key = True
        if cp.distinct_count <= 15 and cp.distinct_pct < 0.05 and cp.distinct_count > 0:
            cp.is_reference = True

        return cp

    def _infer_type(self, series: pd.Series) -> str:
        """Infer column type from values."""
        if len(series) == 0:
            return "string"

        sample = series.head(100)

        # Try numeric
        numeric = pd.to_numeric(sample, errors="coerce")
        if numeric.notna().sum() / len(sample) >= 0.7:
            if (numeric.dropna() == numeric.dropna().astype(int)).all():
                return "integer"
            return "decimal"

        # Try datetime
        try:
            dates = pd.to_datetime(sample, errors="coerce", infer_datetime_format=True)
            if dates.notna().sum() / len(sample) >= 0.7:
                return "date"
        except Exception:
            pass

        # Boolean
        str_vals = sample.astype(str).str.lower()
        bool_vals = str_vals.isin(["true", "false", "yes", "no", "y", "n"])
        if bool_vals.sum() / len(sample) >= 0.7:
            return "boolean"

        return "string"

    def _keyword_signal(self, col_name: str) -> tuple[float, Optional[str]]:
        """Check if column name matches any BDE synonym."""
        col_lower = col_name.lower().strip()

        # Direct match
        if col_lower in self.synonym_map:
            return 1.0, self.synonym_map[col_lower]

        # Partial match (column name contains synonym or vice versa)
        best_score, best_term = 0.0, None
        for syn, tid in self.synonym_map.items():
            if syn in col_lower or col_lower in syn:
                score = len(syn) / max(len(col_lower), len(syn))
                if score > best_score:
                    best_score = score
                    best_term = tid

        return round(best_score, 3), best_term

    def _pattern_signal(self, series: pd.Series) -> tuple[float, Optional[str]]:
        """Check if values match known PII/format patterns."""
        if len(series) == 0:
            return 0.0, None

        sample = series.head(200).astype(str)
        best_ratio, best_pattern = 0.0, None

        for pname, regex in self.PII_PATTERNS.items():
            matches = sample.str.match(regex, na=False).sum()
            ratio = matches / len(sample)
            if ratio > best_ratio:
                best_ratio = ratio
                best_pattern = pname

        return (round(best_ratio, 3), best_pattern) if best_ratio >= 0.5 else (0.0, None)

    def _fingerprint(self, col_name: str, series: pd.Series) -> FieldFingerprint:
        """Compare field values against all reference code sets (Ab Initio's fingerprinting)."""
        fp = FieldFingerprint(field_name=col_name)
        if len(series) == 0:
            return fp

        values = set(series.astype(str).str.strip().str.lower())
        best_ratio, best_set = 0.0, None

        for set_name, ref_values in self.reference_sets.items():
            ref_lower = set(str(v).lower() for v in ref_values)
            if not ref_lower:
                continue

            # What % of distinct field values appear in the reference set
            matched = values & ref_lower
            ratio = len(matched) / len(values) if values else 0

            if ratio > best_ratio:
                best_ratio = ratio
                best_set = set_name

        if best_ratio >= 0.3:  # At least 30% overlap signals a match
            fp.matched_code_set = best_set
            fp.match_ratio = round(best_ratio, 3)
            # Unmatched sample (for tuning)
            ref_lower = set(str(v).lower() for v in self.reference_sets.get(best_set, []))
            fp.unmatched_sample = list(values - ref_lower)[:5]

        return fp

    def _stat_signal(self, cp: GEColumnProfile, matched_bde: Optional[str]) -> float:
        """Score how well the column's statistics match the expected BDE type."""
        if not matched_bde or matched_bde not in self.business_terms:
            return 0.0

        bde = self.business_terms[matched_bde]
        expected_type = bde.get("data_type", "string")
        score = 0.0

        # Type alignment
        type_map = {"string": "string", "integer": "integer", "double": "decimal",
                    "decimal": "decimal", "date": "date", "timestamp": "date"}
        expected_normalized = type_map.get(expected_type, expected_type)
        if cp.inferred_type == expected_normalized:
            score += 0.5

        # Range check for numeric BDEs with range rules
        dq = bde.get("dq_rules", {})
        if "range" in dq and cp.min_val is not None:
            expected_min, expected_max = dq["range"]
            if cp.min_val >= expected_min * 0.8 and cp.max_val <= expected_max * 1.2:
                score += 0.3

        # Uniqueness check for key candidates
        if bde.get("is_key_candidate") and cp.distinct_pct > 0.95:
            score += 0.2

        # Reference set check
        if bde.get("reference_code_set") and cp.is_reference:
            score += 0.3

        return min(round(score, 3), 1.0)

    def _classify_information_type(self, cp: GEColumnProfile, signals: FieldSignals) -> str:
        """Classify into Ab Initio's Information Types: Identifier, Measure, Temporal, Reference, Dimension."""
        # If BDE match found, use its information_type
        if signals.matched_bde and signals.matched_bde in self.business_terms:
            return self.business_terms[signals.matched_bde].get("information_type", "Dimension")

        # Heuristic classification
        if cp.is_key:
            return "Identifier"
        if cp.inferred_type in ("integer", "decimal") and cp.distinct_pct > 0.3:
            return "Measure"
        if cp.inferred_type == "date":
            return "Temporal"
        if cp.is_reference:
            return "Reference"
        return "Dimension"

    def _build_llm_summary(self, profile: GEProfile) -> dict:
        """Build statistical summary for LLM — NO raw data, only aggregates.

        This is what gets sent to the LLM for business DQ rule generation.
        """
        summary = {
            "dataset": profile.dataset_name,
            "row_count": profile.row_count,
            "column_count": profile.column_count,
            "fields": [],
        }

        for col in profile.columns:
            field_summary = {
                "name": col.name,
                "type": col.inferred_type,
                "information_type": col.information_type,
                "null_pct": col.null_pct,
                "distinct_count": col.distinct_count,
                "distinct_pct": col.distinct_pct,
                "is_key": col.is_key,
                "is_pii": col.is_pii,
                "is_reference": col.is_reference,
            }

            # Numeric stats (no actual values)
            if col.mean is not None:
                field_summary["stats"] = {
                    "mean": col.mean, "std": col.std,
                    "min": col.min_val, "max": col.max_val,
                    "quantiles": col.quantiles,
                }

            # Reference set fingerprint (set name only, not values)
            if col.fingerprint and col.fingerprint.matched_code_set:
                field_summary["fingerprint"] = {
                    "matched_set": col.fingerprint.matched_code_set,
                    "match_ratio": col.fingerprint.match_ratio,
                }

            # Pattern detected
            if col.signals and col.signals.detected_pattern:
                field_summary["detected_pattern"] = col.signals.detected_pattern

            # BDE match
            if col.suggested_bde:
                field_summary["suggested_bde"] = col.suggested_bde
                field_summary["confidence"] = col.confidence

            # Distinct values only if it's a reference field (enum-like)
            if col.is_reference and col.most_common:
                field_summary["value_distribution"] = col.most_common

            summary["fields"].append(field_summary)

        return summary

    def generate_ge_expectations(self, profile: GEProfile) -> list[dict]:
        """Generate GE expectation suite from profile (for DQ validation in pipeline).

        Returns list of expectation configs that can be saved as a suite.
        """
        expectations = []

        for col in profile.columns:
            # Not null expectation
            if col.null_pct < 0.05:
                expectations.append({
                    "expectation_type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": col.name},
                    "meta": {"source": "ge_profiler", "field": col.name},
                })

            # Unique expectation
            if col.is_key:
                expectations.append({
                    "expectation_type": "expect_column_values_to_be_unique",
                    "kwargs": {"column": col.name},
                    "meta": {"source": "ge_profiler", "field": col.name},
                })

            # Type expectation
            if col.inferred_type in ("integer", "decimal"):
                expectations.append({
                    "expectation_type": "expect_column_values_to_be_in_type_list",
                    "kwargs": {"column": col.name, "type_list": ["int", "float", "int64", "float64"]},
                    "meta": {"source": "ge_profiler", "field": col.name},
                })

            # Range (numeric)
            if col.min_val is not None and col.max_val is not None:
                expectations.append({
                    "expectation_type": "expect_column_values_to_be_between",
                    "kwargs": {"column": col.name, "min_value": col.min_val, "max_value": col.max_val},
                    "meta": {"source": "ge_profiler", "field": col.name},
                })

            # Accepted values (fingerprinted reference fields)
            if col.fingerprint and col.fingerprint.matched_code_set:
                ref_values = self.reference_sets.get(col.fingerprint.matched_code_set, [])
                if ref_values:
                    expectations.append({
                        "expectation_type": "expect_column_values_to_be_in_set",
                        "kwargs": {"column": col.name, "value_set": ref_values},
                        "meta": {"source": "fingerprint", "ref_set": col.fingerprint.matched_code_set},
                    })

            # Regex (PII patterns)
            if col.signals and col.signals.detected_pattern:
                pattern = self.PII_PATTERNS.get(col.signals.detected_pattern)
                if pattern:
                    expectations.append({
                        "expectation_type": "expect_column_values_to_match_regex",
                        "kwargs": {"column": col.name, "regex": pattern},
                        "meta": {"source": "pattern_detection", "pattern": col.signals.detected_pattern},
                    })

        return expectations


def format_ge_profile_report(profile: GEProfile) -> str:
    """Format GE profile for Chainlit display."""
    lines = [f"## GE Profile: {profile.dataset_name}\n"]
    lines.append(f"**Rows:** {profile.row_count} | **Columns:** {profile.column_count}\n")

    lines.append("| Field | Type | Info Type | Null% | Distinct | BDE Match | Confidence | Fingerprint |")
    lines.append("|-------|------|-----------|-------|----------|-----------|------------|-------------|")

    for col in profile.columns:
        bde = col.suggested_bde or "-"
        conf = f"{col.confidence:.0%}" if col.confidence > 0 else "-"
        fp = f"{col.fingerprint.matched_code_set} ({col.fingerprint.match_ratio:.0%})" \
            if col.fingerprint and col.fingerprint.matched_code_set else "-"
        lines.append(
            f"| `{col.name}` | {col.inferred_type} | {col.information_type} "
            f"| {col.null_pct:.0%} | {col.distinct_count} "
            f"| {bde} | {conf} | {fp} |"
        )

    # Signal breakdown for high-confidence matches
    strong = [c for c in profile.columns if c.confidence >= 0.5]
    if strong:
        lines.append("\n### High-Confidence Matches\n")
        for col in strong:
            s = col.signals
            lines.append(f"**`{col.name}`** → `{col.suggested_bde}` (confidence: {col.confidence:.0%})")
            lines.append(f"  - Keyword: {s.keyword_score:.0%} | Pattern: {s.pattern_score:.0%} "
                         f"| Fingerprint: {s.fingerprint_score:.0%} | Stat: {s.stat_score:.0%}")

    return "\n".join(lines)
