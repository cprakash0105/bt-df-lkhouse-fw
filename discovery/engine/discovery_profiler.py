"""Discovery Profiler — Lightweight profiling with fingerprinting and composite confidence.

No pandas or GE dependency — works with stdlib only.
Integrates into Suggester to auto-profile landing data and enhance confidence.

Implements Ab Initio's approach:
1. Profile → statistical analysis of values
2. Fingerprint → compare values against ALL reference code sets
3. Composite Score → weighted combination of keyword, pattern, fingerprint, stat signals
4. Persist → save profile to GCS for audit trail

Outputs FieldSignals with breakdown that's shown in the UI.
"""
import json
import re
import csv
import io
import os
import yaml
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
from collections import Counter


@dataclass
class FieldSignals:
    """All signals collected for a single field — for composite scoring."""
    field_name: str
    keyword_score: float = 0.0
    keyword_match: Optional[str] = None
    pattern_score: float = 0.0
    detected_pattern: Optional[str] = None
    fingerprint_score: float = 0.0
    fingerprint_set: Optional[str] = None
    stat_score: float = 0.0
    composite_score: float = 0.0
    information_type: str = "Dimension"


@dataclass
class FieldProfile:
    """Profile of a single field from actual data."""
    name: str
    row_count: int = 0
    null_count: int = 0
    null_pct: float = 0.0
    distinct_count: int = 0
    distinct_pct: float = 0.0
    inferred_type: str = "string"
    min_val: Optional[str] = None
    max_val: Optional[str] = None
    mean_val: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    # Low cardinality: all distinct values
    distinct_values: Optional[list] = None
    # Top values with counts
    top_values: list = field(default_factory=list)
    # Detections
    is_pii: bool = False
    is_key: bool = False
    is_reference: bool = False
    detected_patterns: list = field(default_factory=list)
    # Signals (composite confidence)
    signals: Optional[FieldSignals] = None
    # Fingerprint result
    fingerprint_set: Optional[str] = None
    fingerprint_ratio: float = 0.0
    fingerprint_unmatched: list = field(default_factory=list)


@dataclass
class DatasetProfile:
    """Full profile of a dataset."""
    dataset_name: str = ""
    row_count: int = 0
    column_count: int = 0
    source_path: str = ""
    fields: list = field(default_factory=list)


# Weights for composite confidence
WEIGHTS = {"keyword": 0.30, "pattern": 0.25, "fingerprint": 0.25, "stat": 0.20}

# PII patterns
PII_PATTERNS = {
    "pan": re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$"),
    "aadhaar": re.compile(r"^\d{12}$"),
    "email": re.compile(r"^[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}$"),
    "phone": re.compile(r"^[+]?\d{10,13}$"),
    "credit_card": re.compile(r"^\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}$"),
}

DATE_PATTERNS = [
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    re.compile(r"^\d{2}/\d{2}/\d{4}$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"),
]


class DiscoveryProfiler:
    """Profiles data and computes composite confidence scores with fingerprinting."""

    def __init__(self, glossary_path: Optional[str] = None):
        self.glossary_path = glossary_path or str(
            Path(__file__).parent.parent / "config" / "seed_glossary.yaml"
        )
        self._load_glossary()

    def _load_glossary(self):
        with open(self.glossary_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self.business_terms = {t["id"]: t for t in data.get("business_terms", [])}
        self.reference_sets = data.get("reference_code_sets", {})

        # synonym -> term_id
        self.synonym_map = {}
        for term in data.get("business_terms", []):
            tid = term["id"]
            for syn in term.get("synonyms", []):
                self.synonym_map[syn.lower()] = tid
            self.synonym_map[tid.lower()] = tid

    def profile_from_gcs(self, dataset_name: str, bucket_name: str = None) -> Optional[DatasetProfile]:
        """Fetch landing data from GCS and profile it."""
        bucket_name = bucket_name or os.environ.get("CONFIG_BUCKET", "bt-df-lkhouse-lakehouse")
        prefix = f"landing/{dataset_name}/"

        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blobs = list(bucket.list_blobs(prefix=prefix, max_results=5))

            if not blobs:
                print(f"[DiscoveryProfiler] No data at gs://{bucket_name}/{prefix}")
                return None

            blob = blobs[0]
            content = blob.download_as_text()
            if not content.strip():
                return None

            source_path = f"gs://{bucket_name}/{blob.name}"

            if blob.name.endswith(".csv"):
                profile = self.profile_csv(content, dataset_name)
            else:
                profile = self.profile_jsonl(content, dataset_name)

            profile.source_path = source_path
            return profile

        except ImportError:
            print("[DiscoveryProfiler] google-cloud-storage not installed")
            return None
        except Exception as e:
            print(f"[DiscoveryProfiler] GCS profile failed: {e}")
            return None

    def profile_csv(self, content: str, dataset_name: str = "") -> DatasetProfile:
        """Profile CSV content."""
        reader = csv.DictReader(io.StringIO(content))
        rows = []
        for i, row in enumerate(reader):
            if i >= 10000:
                break
            rows.append(row)

        if not rows:
            return DatasetProfile(dataset_name=dataset_name)

        columns = list(rows[0].keys())
        return self._profile_rows(rows, columns, dataset_name)

    def profile_jsonl(self, content: str, dataset_name: str = "") -> DatasetProfile:
        """Profile JSONL content."""
        rows = []
        for line in content.strip().split("\n"):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
            if len(rows) >= 10000:
                break

        if not rows:
            return DatasetProfile(dataset_name=dataset_name)

        columns = list(rows[0].keys())
        return self._profile_rows(rows, columns, dataset_name)

    def _profile_rows(self, rows: list, columns: list, dataset_name: str) -> DatasetProfile:
        profile = DatasetProfile(
            dataset_name=dataset_name,
            row_count=len(rows),
            column_count=len(columns),
        )

        for col in columns:
            fp = self._profile_field(col, rows)
            profile.fields.append(fp)

        return profile

    def _profile_field(self, col_name: str, rows: list) -> FieldProfile:
        """Profile a single field with all signals."""
        values = [row.get(col_name, "") for row in rows]
        total = len(values)
        non_null = [str(v).strip() for v in values if v and str(v).strip() and str(v).lower() not in ("null", "none", "na", "")]
        null_count = total - len(non_null)

        fp = FieldProfile(
            name=col_name.strip(),
            row_count=total,
            null_count=null_count,
            null_pct=round(null_count / total, 3) if total > 0 else 0,
        )

        # Distinct values
        distinct = set(non_null)
        fp.distinct_count = len(distinct)
        fp.distinct_pct = round(fp.distinct_count / total, 3) if total > 0 else 0

        # Low cardinality → store all values
        if 0 < fp.distinct_count <= 20:
            fp.distinct_values = sorted(list(distinct))

        # Top values
        if non_null:
            counter = Counter(non_null)
            fp.top_values = counter.most_common(5)

        # Type inference
        fp.inferred_type = self._infer_type(non_null)

        # Numeric stats
        if fp.inferred_type in ("integer", "decimal"):
            nums = []
            for v in non_null:
                try:
                    nums.append(float(v.replace(",", "")))
                except (ValueError, TypeError):
                    pass
            if nums:
                fp.min_val = str(min(nums))
                fp.max_val = str(max(nums))
                fp.mean_val = round(sum(nums) / len(nums), 2)

        # String length stats
        if fp.inferred_type == "string" and non_null:
            lengths = [len(v) for v in non_null]
            fp.min_length = min(lengths)
            fp.max_length = max(lengths)

        # PII pattern detection
        fp.detected_patterns = self._detect_patterns(non_null)
        if any(p in fp.detected_patterns for p in ["pan", "aadhaar", "email", "phone", "credit_card"]):
            fp.is_pii = True

        # Key detection
        if fp.distinct_pct > 0.95 and fp.null_pct < 0.01:
            fp.is_key = True

        # Reference detection
        if 0 < fp.distinct_count <= 15 and fp.distinct_pct < 0.05:
            fp.is_reference = True

        # --- Composite Confidence Scoring ---
        signals = FieldSignals(field_name=col_name)

        # 1. Keyword signal
        signals.keyword_score, signals.keyword_match = self._keyword_signal(col_name)

        # 2. Pattern signal
        if fp.detected_patterns:
            signals.pattern_score = 0.9
            signals.detected_pattern = fp.detected_patterns[0]

        # 3. Fingerprint signal (compare values against ALL reference sets)
        fp_set, fp_ratio, fp_unmatched = self._fingerprint(non_null)
        signals.fingerprint_score = fp_ratio
        signals.fingerprint_set = fp_set
        fp.fingerprint_set = fp_set
        fp.fingerprint_ratio = fp_ratio
        fp.fingerprint_unmatched = fp_unmatched

        # 4. Stat signal (type + distribution alignment with matched BDE)
        signals.stat_score = self._stat_signal(fp, signals.keyword_match)

        # Composite
        signals.composite_score = round(
            WEIGHTS["keyword"] * signals.keyword_score
            + WEIGHTS["pattern"] * signals.pattern_score
            + WEIGHTS["fingerprint"] * signals.fingerprint_score
            + WEIGHTS["stat"] * signals.stat_score,
            3,
        )

        # Information type
        signals.information_type = self._classify_info_type(fp, signals)
        fp.signals = signals

        return fp

    def _infer_type(self, values: list) -> str:
        if not values:
            return "string"
        sample = values[:100]
        counts = Counter()
        for v in sample:
            try:
                int(v.replace(",", ""))
                counts["integer"] += 1
                continue
            except (ValueError, TypeError):
                pass
            try:
                float(v.replace(",", ""))
                counts["decimal"] += 1
                continue
            except (ValueError, TypeError):
                pass
            if any(p.match(v) for p in DATE_PATTERNS):
                counts["date"] += 1
                continue
            counts["string"] += 1

        if not counts:
            return "string"
        total = sum(counts.values())
        for dtype, count in counts.most_common():
            if count / total >= 0.7:
                return dtype
        return "string"

    def _detect_patterns(self, values: list) -> list:
        if not values:
            return []
        sample = values[:200]
        detected = []
        for pname, pattern in PII_PATTERNS.items():
            matches = sum(1 for v in sample if pattern.match(v))
            if matches / len(sample) >= 0.7:
                detected.append(pname)
        return detected

    def _keyword_signal(self, col_name: str) -> tuple:
        col_lower = col_name.lower().strip()
        if col_lower in self.synonym_map:
            return 1.0, self.synonym_map[col_lower]

        best_score, best_term = 0.0, None
        for syn, tid in self.synonym_map.items():
            if syn in col_lower or col_lower in syn:
                score = len(syn) / max(len(col_lower), len(syn))
                if score > best_score:
                    best_score = score
                    best_term = tid
        return round(best_score, 3), best_term

    def _fingerprint(self, values: list) -> tuple:
        """Compare values against ALL reference code sets. Returns (set_name, ratio, unmatched)."""
        if not values:
            return None, 0.0, []

        value_set = set(v.lower().strip() for v in values)
        best_ratio, best_set = 0.0, None

        for set_name, ref_values in self.reference_sets.items():
            ref_lower = set(str(v).lower() for v in ref_values)
            if not ref_lower:
                continue
            matched = value_set & ref_lower
            ratio = len(matched) / len(value_set) if value_set else 0
            if ratio > best_ratio:
                best_ratio = ratio
                best_set = set_name

        if best_ratio >= 0.3:
            ref_lower = set(str(v).lower() for v in self.reference_sets.get(best_set, []))
            unmatched = list(value_set - ref_lower)[:5]
            return best_set, round(best_ratio, 3), unmatched

        return None, 0.0, []

    def _stat_signal(self, fp: FieldProfile, matched_bde: Optional[str]) -> float:
        if not matched_bde or matched_bde not in self.business_terms:
            return 0.0

        bde = self.business_terms[matched_bde]
        score = 0.0

        # Type alignment
        type_map = {"string": "string", "integer": "integer", "double": "decimal",
                    "decimal": "decimal", "date": "date", "timestamp": "date"}
        expected = type_map.get(bde.get("data_type", "string"), "string")
        if fp.inferred_type == expected:
            score += 0.5

        # Range check
        dq = bde.get("dq_rules", {})
        if "range" in dq and fp.min_val is not None:
            try:
                exp_min, exp_max = dq["range"]
                if float(fp.min_val) >= exp_min * 0.8 and float(fp.max_val) <= exp_max * 1.2:
                    score += 0.3
            except (ValueError, TypeError):
                pass

        # Uniqueness for keys
        if bde.get("is_key_candidate") and fp.is_key:
            score += 0.2

        # Reference set match
        if bde.get("reference_code_set") and fp.is_reference:
            score += 0.3

        return min(round(score, 3), 1.0)

    def _classify_info_type(self, fp: FieldProfile, signals: FieldSignals) -> str:
        if signals.keyword_match and signals.keyword_match in self.business_terms:
            return self.business_terms[signals.keyword_match].get("information_type", "Dimension")
        if fp.is_key:
            return "Identifier"
        if fp.inferred_type in ("integer", "decimal") and fp.distinct_pct > 0.3:
            return "Measure"
        if fp.inferred_type == "date":
            return "Temporal"
        if fp.is_reference:
            return "Reference"
        return "Dimension"

    def persist_profile(self, profile: DatasetProfile, bucket_name: str = None) -> Optional[str]:
        """Save profile to GCS for audit trail."""
        bucket_name = bucket_name or os.environ.get("CONFIG_BUCKET", "bt-df-lkhouse-lakehouse")
        path = f"profiles/{profile.dataset_name}/latest.json"

        profile_dict = {
            "dataset_name": profile.dataset_name,
            "row_count": profile.row_count,
            "column_count": profile.column_count,
            "source_path": profile.source_path,
            "fields": [],
        }
        for fp in profile.fields:
            field_dict = {
                "name": fp.name,
                "type": fp.inferred_type,
                "null_pct": fp.null_pct,
                "distinct_count": fp.distinct_count,
                "distinct_pct": fp.distinct_pct,
                "is_pii": fp.is_pii,
                "is_key": fp.is_key,
                "is_reference": fp.is_reference,
                "detected_patterns": fp.detected_patterns,
                "fingerprint_set": fp.fingerprint_set,
                "fingerprint_ratio": fp.fingerprint_ratio,
            }
            if fp.signals:
                field_dict["signals"] = {
                    "keyword": fp.signals.keyword_score,
                    "keyword_match": fp.signals.keyword_match,
                    "pattern": fp.signals.pattern_score,
                    "fingerprint": fp.signals.fingerprint_score,
                    "stat": fp.signals.stat_score,
                    "composite": fp.signals.composite_score,
                    "information_type": fp.signals.information_type,
                }
            if fp.distinct_values:
                field_dict["distinct_values"] = fp.distinct_values
            if fp.min_val is not None:
                field_dict["stats"] = {"min": fp.min_val, "max": fp.max_val, "mean": fp.mean_val}
            profile_dict["fields"].append(field_dict)

        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(path)
            blob.upload_from_string(json.dumps(profile_dict, indent=2), content_type="application/json")
            gcs_path = f"gs://{bucket_name}/{path}"
            print(f"[DiscoveryProfiler] Profile persisted: {gcs_path}")
            return gcs_path
        except Exception as e:
            print(f"[DiscoveryProfiler] Failed to persist profile: {e}")
            return None
