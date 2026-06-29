"""Semantic Discovery API — FastAPI backend for React UI.
Wraps all engine capabilities as REST endpoints.
Runs alongside Chainlit (separate port)."""
import sys
from pathlib import Path

# Ensure discovery package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import json

from discovery.engine.knowledge_graph import KnowledgeGraph
from discovery.engine.rules_engine import RulesEngine
from discovery.engine.embedder import Embedder
from discovery.engine.suggester import Suggester
from discovery.engine.config_generator import ConfigGenerator
from discovery.engine.nl_parser import NLParser
from discovery.engine.approval_handler import ApprovalHandler
from discovery.engine.profiler import Profiler
from discovery.engine.contract_generator import ContractGenerator
from discovery.engine.scd_config_generator import SCDConfigGenerator

# Initialize engine
kg = KnowledgeGraph()
rules = RulesEngine()
embedder = Embedder(mode="local")
suggester = Suggester(knowledge_graph=kg, rules_engine=rules, embedder=embedder)
config_gen = ConfigGenerator()
nl_parser = NLParser()
approval_handler = ApprovalHandler()
profiler = Profiler()
contract_gen = ContractGenerator()
scd_gen = SCDConfigGenerator()

app = FastAPI(title="Semantic Discovery API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve React static build in production
import os
static_dir = Path(__file__).parent.parent.parent / "static"
if static_dir.exists():
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    @app.get("/")
    async def serve_index():
        return FileResponse(str(static_dir / "index.html"))

    # Serve static assets (JS/CSS)
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static")

    # SPA fallback — any unmatched GET returns index.html
    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        file_path = static_dir / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(static_dir / "index.html"))

# In-memory session store (single user POC)
_session = {"suggestion": None, "profile": None}


# --- Request/Response Models ---

class DiscoverRequest(BaseModel):
    text: Optional[str] = None
    yaml_content: Optional[str] = None
    fields: Optional[list[dict]] = None
    name: Optional[str] = None

class ProfileRequest(BaseModel):
    data: str
    format: str = "csv"  # csv or jsonl
    dataset_name: Optional[str] = None

class ApproveRequest(BaseModel):
    fields: Optional[list[str]] = None  # None = approve all

class CorrectionRequest(BaseModel):
    field: str
    action: str  # remove_pii, add_pii, remove_not_null, set_accepted_values, etc.
    values: Optional[list[str]] = None
    bde: Optional[str] = None

class SQLRequest(BaseModel):
    requirement: str

class MultiDiscoverRequest(BaseModel):
    text: str


# --- Endpoints ---

@app.get("/health")
def health():
    return {"status": "ok", "glossary_terms": len(kg.terms)}


@app.get("/glossary")
def get_glossary():
    """Get all business terms grouped by domain."""
    result = {}
    for domain in kg.domains.values():
        terms = kg.get_terms_by_domain(domain.id)
        result[domain.name] = [
            {
                "id": t.id, "name": t.name, "domain": t.domain,
                "is_pii": t.is_pii, "information_type": t.information_type,
                "synonyms": t.synonyms[:5], "dq_rules": t.dq_rules,
            }
            for t in terms
        ]
    return result


@app.get("/glossary/search")
def search_glossary(q: str):
    """Search business terms."""
    matches = kg.search_by_synonym(q)
    return [
        {"id": t.id, "name": t.name, "confidence": round(c, 2),
         "domain": t.domain, "is_pii": t.is_pii}
        for t, c in matches
    ]


@app.get("/applications")
def get_applications():
    return [
        {"id": a.id, "name": a.name, "description": a.description, "keywords": a.keywords[:5]}
        for a in kg.applications.values()
    ]


@app.get("/domains")
def get_domains():
    return [
        {"id": d.id, "name": d.name, "description": d.description,
         "term_count": len(kg.get_terms_by_domain(d.id))}
        for d in kg.domains.values()
    ]


@app.post("/discover")
def discover(req: DiscoverRequest):
    """Run full discovery on a dataset definition."""
    asset_def = None

    # Parse from natural language
    if req.text:
        asset_def = nl_parser.parse(req.text)
        if not asset_def or not asset_def.get("fields"):
            raise HTTPException(400, "Could not parse natural language input")

    # Parse from YAML
    elif req.yaml_content:
        import yaml
        try:
            asset_def = yaml.safe_load(req.yaml_content)
        except Exception:
            raise HTTPException(400, "Invalid YAML")

    # Direct fields
    elif req.fields and req.name:
        asset_def = {"name": req.name, "fields": req.fields}

    if not asset_def or not asset_def.get("fields"):
        raise HTTPException(400, "Provide text, yaml_content, or name+fields")

    suggestion = suggester.full_discovery(asset_def)

    # Try LLM review
    try:
        from discovery.engine.llm_reviewer import LLMReviewer
        reviewer = LLMReviewer()
        corrections = reviewer.review(suggestion)
        if corrections and any(corrections.get(k) for k in ["corrections", "accepted_values_override", "remove_pii", "remove_not_null"]):
            suggestion = reviewer.apply_corrections(suggestion, corrections)
    except Exception:
        pass

    _session["suggestion"] = suggestion
    return _serialize_suggestion(suggestion)


@app.post("/discover/multi")
def discover_multi(req: MultiDiscoverRequest):
    """Multi-feed domain onboarding."""
    datasets = nl_parser.parse_multi(req.text)
    if not datasets:
        # Fall back to single
        parsed = nl_parser.parse(req.text)
        if parsed and parsed.get("fields"):
            datasets = [parsed]
        else:
            raise HTTPException(400, "Could not parse multiple datasets from input")

    results = []
    for ds in datasets:
        suggestion = suggester.full_discovery(ds)
        results.append(_serialize_suggestion(suggestion))

    # Store first one as active
    if datasets:
        _session["suggestion"] = suggester.full_discovery(datasets[0])

    return {"datasets": results, "count": len(results)}


@app.post("/profile")
def profile_data(req: ProfileRequest):
    """Profile sample data."""
    if req.format == "csv":
        profile = profiler.profile_csv(req.data)
    else:
        profile = profiler.profile_jsonl(req.data)

    if not profile.columns:
        raise HTTPException(400, "Could not parse data")

    _session["profile"] = profile
    return _serialize_profile(profile)


@app.post("/approve")
def approve(req: ApproveRequest):
    """Approve current suggestion."""
    suggestion = _session.get("suggestion")
    if not suggestion:
        raise HTTPException(400, "No active discovery to approve")

    config_yaml = config_gen.generate(suggestion, approved_fields=req.fields)
    results = approval_handler.process_approval(suggestion, config_yaml=config_yaml)

    # Contract
    contract_yaml = contract_gen.generate(suggestion)
    contract_path = contract_gen.generate_and_push(suggestion)

    # SCD
    scd_type = scd_gen.infer_scd_type("", suggestion.data_domain)
    scd_path = scd_gen.generate_and_push(suggestion, scd_type=scd_type)

    return {
        "status": "approved",
        "new_terms_created": results["new_terms_created"],
        "ba_linked": results["ba_linked"],
        "config_gcs_path": results["config_gcs_path"],
        "contract_path": contract_path,
        "scd_path": scd_path,
        "errors": results["errors"],
        "config_yaml": config_yaml,
    }


@app.post("/correct")
def correct(req: CorrectionRequest):
    """Apply a correction to the current suggestion."""
    suggestion = _session.get("suggestion")
    if not suggestion:
        raise HTTPException(400, "No active discovery to correct")

    target = next((f for f in suggestion.fields if f.field_name == req.field), None)
    if not target:
        raise HTTPException(404, f"Field '{req.field}' not found")

    if req.action == "remove_pii":
        target.is_pii = False
        target.classification = "Internal"
    elif req.action == "add_pii":
        target.is_pii = True
        target.classification = "PII"
    elif req.action == "remove_not_null":
        target.dq_rules.pop("not_null", None)
    elif req.action == "add_not_null":
        target.dq_rules["not_null"] = True
    elif req.action == "remove_unique":
        target.dq_rules.pop("unique", None)
    elif req.action == "add_unique":
        target.dq_rules["unique"] = True
    elif req.action == "set_accepted_values" and req.values:
        target.dq_rules["accepted_values"] = req.values
        target.accepted_values = req.values
    elif req.action == "set_bde" and req.bde:
        target.linked_term = req.bde
        target.linked_term_name = req.bde.replace("_", " ").title()
    else:
        raise HTTPException(400, f"Unknown action: {req.action}")

    _session["suggestion"] = suggestion
    return {"status": "corrected", "field": req.field, "action": req.action}


@app.get("/suggestion")
def get_current_suggestion():
    """Get current active suggestion."""
    suggestion = _session.get("suggestion")
    if not suggestion:
        raise HTTPException(404, "No active discovery")
    return _serialize_suggestion(suggestion)


@app.post("/generate/config")
def generate_config():
    """Generate pipeline YAML from current suggestion."""
    suggestion = _session.get("suggestion")
    if not suggestion:
        raise HTTPException(400, "No active discovery")
    return {"yaml": config_gen.generate(suggestion)}


@app.post("/generate/sql")
def generate_sql(req: SQLRequest):
    """Generate consumption SQL from NL requirement."""
    from discovery.engine.sql_generator import SQLGenerator
    sql_gen = SQLGenerator()
    sql = sql_gen.generate(req.requirement)
    if not sql or sql == "__QUOTA_EXCEEDED__":
        raise HTTPException(503, "LLM unavailable")
    return {"sql": sql}


# --- Helpers ---

def _serialize_suggestion(s) -> dict:
    return {
        "asset_name": s.asset_name,
        "mode": s.mode,
        "discovered_at": s.discovered_at,
        "business_application": s.business_application_name,
        "app_confidence": round(s.app_confidence, 2),
        "data_domain": s.data_domain,
        "primary_key": s.primary_key,
        "schema_evolution": s.schema_evolution,
        "fields": [
            {
                "name": f.field_name,
                "type": f.field_type,
                "linked_term": f.linked_term,
                "linked_term_name": f.linked_term_name,
                "confidence": round(f.confidence, 2),
                "information_type": f.information_type,
                "classification": f.classification,
                "is_pii": f.is_pii,
                "is_key": f.is_key_candidate,
                "dq_rules": f.dq_rules,
                "new_term": f.new_term_proposed,
                "reasoning": f.reasoning,
            }
            for f in s.fields
        ],
        "new_term_proposals": s.new_term_proposals,
        "fk_candidates": s.fk_candidates,
    }


def _serialize_profile(p) -> dict:
    return {
        "row_count": p.row_count,
        "column_count": p.column_count,
        "columns": [
            {
                "name": col.name,
                "type": col.inferred_type,
                "null_pct": col.null_pct,
                "distinct_count": col.distinct_count,
                "cardinality_ratio": col.cardinality_ratio,
                "is_pii": col.is_likely_pii,
                "is_key": col.is_likely_identifier,
                "is_reference": col.is_likely_reference,
                "patterns": col.detected_patterns,
                "sample_values": col.sample_values[:3],
                "distinct_values": col.distinct_values,
                "suggested_dq": col.suggested_dq,
            }
            for col in p.columns
        ],
    }
