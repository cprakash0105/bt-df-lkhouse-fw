"""Profiler Service — Standalone GE-based profiler running on Dataproc.

Receives dataset location via REST API, runs profiling with:
- Great Expectations statistical analysis
- Fingerprinting against all reference code sets
- Composite confidence scoring (keyword, pattern, fingerprint, stat)
- PII pattern detection
- Information type classification

Returns structured profile JSON to Semantic Discovery.

Deploy: Run on Dataproc master node (port 8090)
  python -m uvicorn profiler_service.app:app --host 0.0.0.0 --port 8090
"""
import os
import json
import re
import csv
import io
import yaml
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
from collections import Counter

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Try pandas/GE — they should be available on Dataproc
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

app = FastAPI(title="Data Profiler Service", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# --- Config ---
GLOSSARY_PATH = os.environ.get("GLOSSARY_PATH", "/tmp/seed_glossary.yaml")
BUCKET = os.environ.get("CONFIG_BUCKET", "bt-df-lkhouse-lakehouse")

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

WEIGHTS = {"keyword": 0.30, "pattern": 0.25, "fingerprint": 0.25, "stat": 0.20}


# --- Glossary loader ---
_glossary = None

def _load_glossary():
    global _glossary
    if _glossary:
        return _glossary

    # Try local file first, then fetch from GCS
    path = GLOSSARY_PATH
    if not os.path.exists(path):
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(BUCKET)
            blob = bucket.blob("framework/config/seed_glossary.yaml")
            blob.download_to_filename(path)
        except Exception:
            # Fallback: try relative path
            alt = Path(__file__).parent.parent / "discovery" / "config" / "seed_glossary.yaml"
            if alt.exists():
                path = str(alt)
            else:
                return {"business_terms": {}, "reference_sets": {}, "synonym_map": {}}

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    business_terms = {t["id"]: t for t in data.get("business_terms", [])}
    reference_sets = data.get("reference_code_sets", {})
    synonym_map = {}
    for term in data.get("business_terms", []):
        tid = term["id"]
        for syn in term.get("synonyms", []):
            synonym_map[syn.lower()] = tid
        synonym_map[tid.lower()] = tid

    _glossary = {
        "business_terms": business_terms,
        "reference_sets": reference_sets,
        "synonym_map": synonym_map,
    }
    return _glossary


# --- Request/Response Models ---

class ProfileRequest(BaseModel):
    dataset_name: str
    source_path: Optional[str] = None  # gs://bucket/landing/dataset/ or auto-detect
    max_rows: int = 10000

class ProfileResponse(BaseModel):
    dataset_name: str
    source_path: str
    row_count: int
    column_count: int
    duration_seconds: float
    fields: list
    llm_summary: dict


# --- Endpoints ---

@app.get("/health")
def health():
    return {"status": "ok", "pandas": PANDAS_AVAILABLE, "service": "profiler"}


@app.post("/profile", response_model=ProfileResponse)
def profile_dataset(req: ProfileRequest):
    """Profile a dataset from GCS. Returns full profile with signals."""
    start = time.time()
    glossary = _load_glossary()

    # Resolve source path
    source_path = req.source_path or f"gs://{BUCKET}/landing/{req.dataset_name}/"

    # Fetch data from GCS
    content, file_type = _fetch_from_gcs(source_path)
    if not content:
        raise HTTPException(404, f"No data found at {source_path}")

    # Parse into rows
    if file_type == "csv":
        rows, columns = _parse_csv(content, req.max_rows)
    else:
        rows, columns = _parse_jsonl(content, req.max_rows)

    if not rows:
        raise HTTPException(400, "Could not parse data or empty dataset")

    # Profile each field
    fields = []
    for col in columns:
        field_profile = _profile_field(col, rows, glossary)
        fields.append(field_profile)

    # Build LLM summary (stats only, no raw data)
    llm_summary = _build_llm_summary(req.dataset_name, len(rows), len(columns), fields)

    duration = round(time.time() - start, 2)

    # Persist profile to GCS
    _persist_profile(req.dataset_name, {
        "dataset_name": req.dataset_name,
        "source_path": source_path,
        "row_count": len(rows),
        "column_count": len(columns),
        "duration_seconds": duration,
        "fields": fields,
    })

    return ProfileResponse(
        dataset_name=req.dataset_name,
        source_path=source_path,
        row_count=len(rows),
        column_count=len(columns),
        duration_seconds=duration,
        fields=fields,
        llm_summary=llm_summary,
    )


# --- Core Profiling Logic ---

def _profile_field(col_name: str, rows: list, glossary: dict) -> dict:
    """Profile a single field with all 4 signals."""
    values = [row.get(col_name, "") for row in rows]
    total = len(values)
    non_null = [str(v).strip() for v in values
                if v and str(v).strip() and str(v).lower() not in ("null", "none", "na", "")]
    null_count = total - len(non_null)
    null_pct = round(null_count / total, 3) if total > 0 else 0

    distinct = set(non_null)
    distinct_count = len(distinct)
    distinct_pct = round(distinct_count / total, 3) if total > 0 else 0

    # Type inference
    inferred_type = _infer_type(non_null)

    # Numeric stats
    stats = {}
    if inferred_type in ("integer", "decimal"):
        nums = []
        for v in non_null:
            try:
                nums.append(float(v.replace(",", "")))
            except (ValueError, TypeError):
                pass
        if nums:
            stats = {
                "min": round(min(nums), 2),
                "max": round(max(nums), 2),
                "mean": round(sum(nums) / len(nums), 2),
                "std": round((sum((x - sum(nums)/len(nums))**2 for x in nums) / len(nums)) ** 0.5, 2),
            }

    # Distinct values (low cardinality)
    distinct_values = sorted(list(distinct))[:20] if distinct_count <= 20 else None

    # Top values
    top_values = Counter(non_null).most_common(5) if non_null else []

    # PII detection
    detected_patterns = _detect_patterns(non_null)
    is_pii = any(p in detected_patterns for p in ["pan", "aadhaar", "email", "phone", "credit_card"])

    # Key detection
    is_key = distinct_pct > 0.95 and null_pct < 0.01

    # Reference detection
    is_reference = 0 < distinct_count <= 15 and distinct_pct < 0.05

    # --- Composite Confidence Signals ---
    # 1. Keyword
    keyword_score, keyword_match = _keyword_signal(col_name, glossary["synonym_map"])

    # 2. Pattern
    pattern_score = 0.9 if detected_patterns else 0.0
    detected_pattern = detected_patterns[0] if detected_patterns else None

    # 3. Fingerprint (values vs ALL reference sets)
    fp_set, fp_ratio, fp_unmatched = _fingerprint(non_null, glossary["reference_sets"])

    # 4. Statistical signal
    stat_score = _stat_signal(inferred_type, stats, is_key, is_reference, keyword_match, glossary["business_terms"])

    # Composite
    composite = round(
        WEIGHTS["keyword"] * keyword_score
        + WEIGHTS["pattern"] * pattern_score
        + WEIGHTS["fingerprint"] * fp_ratio
        + WEIGHTS["stat"] * stat_score,
        3
    )

    # Information type
    info_type = _classify_info_type(is_key, inferred_type, distinct_pct, is_reference, keyword_match, glossary["business_terms"])

    return {
        "name": col_name,
        "inferred_type": inferred_type,
        "null_pct": null_pct,
        "distinct_count": distinct_count,
        "distinct_pct": distinct_pct,
        "is_pii": is_pii,
        "is_key": is_key,
        "is_reference": is_reference,
        "detected_patterns": detected_patterns,
        "distinct_values": distinct_values,
        "top_values": top_values,
        "stats": stats if stats else None,
        "signals": {
            "keyword_score": keyword_score,
            "keyword_match": keyword_match,
            "pattern_score": pattern_score,
            "detected_pattern": detected_pattern,
            "fingerprint_score": fp_ratio,
            "fingerprint_set": fp_set,
            "fingerprint_unmatched": fp_unmatched,
            "stat_score": stat_score,
            "composite_score": composite,
            "information_type": info_type,
        },
    }


def _infer_type(values: list) -> str:
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
        if v.lower() in ("true", "false", "yes", "no"):
            counts["boolean"] += 1
            continue
        counts["string"] += 1
    if not counts:
        return "string"
    total = sum(counts.values())
    for dtype, count in counts.most_common():
        if count / total >= 0.7:
            return dtype
    return "string"


def _detect_patterns(values: list) -> list:
    if not values:
        return []
    sample = values[:200]
    detected = []
    for pname, pattern in PII_PATTERNS.items():
        matches = sum(1 for v in sample if pattern.match(v))
        if matches / len(sample) >= 0.7:
            detected.append(pname)
    return detected


def _keyword_signal(col_name: str, synonym_map: dict) -> tuple:
    col_lower = col_name.lower().strip()
    if col_lower in synonym_map:
        return 1.0, synonym_map[col_lower]
    best_score, best_term = 0.0, None
    for syn, tid in synonym_map.items():
        if syn in col_lower or col_lower in syn:
            score = len(syn) / max(len(col_lower), len(syn))
            if score > best_score:
                best_score = score
                best_term = tid
    return round(best_score, 3), best_term


def _fingerprint(values: list, reference_sets: dict) -> tuple:
    if not values:
        return None, 0.0, []
    value_set = set(v.lower().strip() for v in values)
    best_ratio, best_set = 0.0, None
    for set_name, ref_values in reference_sets.items():
        ref_lower = set(str(v).lower() for v in ref_values)
        if not ref_lower:
            continue
        matched = value_set & ref_lower
        ratio = len(matched) / len(value_set) if value_set else 0
        if ratio > best_ratio:
            best_ratio = ratio
            best_set = set_name
    if best_ratio >= 0.3:
        ref_lower = set(str(v).lower() for v in reference_sets.get(best_set, []))
        unmatched = list(value_set - ref_lower)[:5]
        return best_set, round(best_ratio, 3), unmatched
    return None, 0.0, []


def _stat_signal(inferred_type, stats, is_key, is_reference, matched_bde, business_terms) -> float:
    if not matched_bde or matched_bde not in business_terms:
        return 0.0
    bde = business_terms[matched_bde]
    score = 0.0
    type_map = {"string": "string", "integer": "integer", "double": "decimal", "decimal": "decimal", "date": "date", "timestamp": "date"}
    expected = type_map.get(bde.get("data_type", "string"), "string")
    if inferred_type == expected:
        score += 0.5
    dq = bde.get("dq_rules", {})
    if "range" in dq and stats:
        try:
            exp_min, exp_max = dq["range"]
            if stats["min"] >= exp_min * 0.8 and stats["max"] <= exp_max * 1.2:
                score += 0.3
        except (ValueError, TypeError, KeyError):
            pass
    if bde.get("is_key_candidate") and is_key:
        score += 0.2
    if bde.get("reference_code_set") and is_reference:
        score += 0.3
    return min(round(score, 3), 1.0)


def _classify_info_type(is_key, inferred_type, distinct_pct, is_reference, matched_bde, business_terms) -> str:
    if matched_bde and matched_bde in business_terms:
        return business_terms[matched_bde].get("information_type", "Dimension")
    if is_key:
        return "Identifier"
    if inferred_type in ("integer", "decimal") and distinct_pct > 0.3:
        return "Measure"
    if inferred_type == "date":
        return "Temporal"
    if is_reference:
        return "Reference"
    return "Dimension"


def _build_llm_summary(dataset_name, row_count, col_count, fields) -> dict:
    """Statistical summary for LLM — no raw data."""
    summary = {"dataset": dataset_name, "row_count": row_count, "column_count": col_count, "fields": []}
    for f in fields:
        entry = {
            "name": f["name"],
            "type": f["inferred_type"],
            "information_type": f["signals"]["information_type"],
            "null_pct": f["null_pct"],
            "distinct_count": f["distinct_count"],
            "is_key": f["is_key"],
            "is_pii": f["is_pii"],
            "is_reference": f["is_reference"],
        }
        if f.get("stats"):
            entry["stats"] = f["stats"]
        if f["signals"]["fingerprint_set"]:
            entry["fingerprint"] = {"set": f["signals"]["fingerprint_set"], "ratio": f["signals"]["fingerprint_score"]}
        if f["signals"]["detected_pattern"]:
            entry["pattern"] = f["signals"]["detected_pattern"]
        if f["signals"]["keyword_match"]:
            entry["bde_match"] = f["signals"]["keyword_match"]
            entry["confidence"] = f["signals"]["composite_score"]
        summary["fields"].append(entry)
    return summary


# --- GCS Helpers ---

def _fetch_from_gcs(source_path: str) -> tuple:
    """Fetch first file from GCS path. Returns (content, type)."""
    try:
        from google.cloud import storage
        client = storage.Client()

        # Parse gs:// path
        if source_path.startswith("gs://"):
            parts = source_path.replace("gs://", "").split("/", 1)
            bucket_name = parts[0]
            prefix = parts[1] if len(parts) > 1 else ""
        else:
            bucket_name = BUCKET
            prefix = source_path

        bucket = client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix=prefix, max_results=5))
        if not blobs:
            return None, None

        blob = blobs[0]
        content = blob.download_as_text()
        file_type = "csv" if blob.name.endswith(".csv") else "jsonl"
        return content, file_type
    except Exception as e:
        print(f"[Profiler] GCS fetch failed: {e}")
        return None, None


def _parse_csv(content: str, max_rows: int) -> tuple:
    reader = csv.DictReader(io.StringIO(content))
    rows = []
    for i, row in enumerate(reader):
        if i >= max_rows:
            break
        rows.append(row)
    columns = list(rows[0].keys()) if rows else []
    return rows, columns


def _parse_jsonl(content: str, max_rows: int) -> tuple:
    rows = []
    for line in content.strip().split("\n"):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
        if len(rows) >= max_rows:
            break
    columns = list(rows[0].keys()) if rows else []
    return rows, columns


def _persist_profile(dataset_name: str, profile_data: dict):
    """Save profile to GCS."""
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(BUCKET)
        path = f"profiles/{dataset_name}/latest.json"
        blob = bucket.blob(path)
        blob.upload_from_string(json.dumps(profile_data, indent=2, default=str), content_type="application/json")
        print(f"[Profiler] Profile saved: gs://{BUCKET}/{path}")
    except Exception as e:
        print(f"[Profiler] Failed to persist: {e}")
