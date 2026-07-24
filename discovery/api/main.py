"""Semantic Discovery API — FastAPI backend for React UI.
Wraps all engine capabilities as REST endpoints.
Runs alongside Chainlit (separate port)."""
import sys
from pathlib import Path

# Ensure discovery package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from logger import get_logger, flush_logs
_log = get_logger("discovery.api")

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

# Optional imports (may fail if deps not installed)
try:
    from discovery.engine.contract_generator import ContractGenerator
    contract_gen = ContractGenerator()
except Exception:
    contract_gen = None

try:
    from discovery.engine.scd_config_generator import SCDConfigGenerator
    scd_gen = SCDConfigGenerator()
except Exception:
    scd_gen = None

# Initialize engine
kg = KnowledgeGraph()
rules = RulesEngine()
embedder = Embedder(mode="local")
suggester = Suggester(knowledge_graph=kg, rules_engine=rules, embedder=embedder)
config_gen = ConfigGenerator()
nl_parser = NLParser()
profiler = Profiler()

# Approval handler (needs GCP deps)
try:
    approval_handler = ApprovalHandler()
except Exception:
    approval_handler = None

# KC Agent for catalog questions (must be after kg init)
try:
    from discovery.engine.kc_agent import KnowledgeCatalogAgent
    kc_agent = KnowledgeCatalogAgent(knowledge_graph=kg)
except Exception as e:
    print(f"[API] KC Agent init failed: {e}")
    kc_agent = None

# RAG Retriever
try:
    from discovery.engine.rag.retriever import get_retriever
    rag_retriever = get_retriever()
    print(f"[API] RAG retriever: {'ready' if rag_retriever.is_available else 'no index'}")
except Exception as e:
    print(f"[API] RAG init skipped: {e}")
    rag_retriever = None

# MCP Agent
try:
    from discovery.engine.mcp.agent import get_agent as get_mcp_agent
    mcp_agent = get_mcp_agent()
    print("[API] MCP agent ready")
except Exception as e:
    print(f"[API] MCP agent init skipped: {e}")
    mcp_agent = None

# Response Cache
try:
    from discovery.engine.rag import cache as response_cache
    print(f"[API] Response cache ready")
except Exception as e:
    print(f"[API] Response cache init skipped: {e}")
    response_cache = None

# Catalog Cache (Firestore)
try:
    from discovery.engine.catalog_cache import CatalogCache
    from discovery.engine.catalog_cache.sync import sync_from_glossary, sync_dataset_on_approval
    catalog_cache = CatalogCache()
    if catalog_cache.is_available():
        # Sync on startup if stale (>5 min since last sync)
        status = catalog_cache.get_sync_status()
        if not status.get("last_sync"):
            sync_from_glossary(catalog_cache)
            print("[API] Catalog cache synced from glossary")
    else:
        catalog_cache = None
except Exception as e:
    print(f"[API] Catalog cache init failed: {e}")
    catalog_cache = None

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

    # NOTE: SPA fallback is registered AFTER all API routes (at bottom of file)
    # Serve static assets (JS/CSS)
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static")

# Firestore-backed session (survives Cloud Run scale-to-zero)
import pickle, base64

_SESSION_DOC = "sessions/default"
_fs_client = None

def _get_fs():
    global _fs_client
    if _fs_client is None:
        try:
            from google.cloud import firestore
            _fs_client = firestore.Client()
        except Exception:
            pass
    return _fs_client

def _session_get(key):
    fs = _get_fs()
    if not fs:
        return _mem_session.get(key)
    try:
        doc = fs.document(_SESSION_DOC).get()
        if not doc.exists:
            return None
        raw = doc.to_dict().get(key)
        if raw is None:
            return None
        return pickle.loads(base64.b64decode(raw))
    except Exception as e:
        print(f"[Session] read error: {e}")
        return _mem_session.get(key)

def _session_set(key, value):
    _mem_session[key] = value  # always keep in-mem as fallback
    fs = _get_fs()
    if not fs:
        return
    try:
        raw = base64.b64encode(pickle.dumps(value)).decode()
        fs.document(_SESSION_DOC).set({key: raw}, merge=True)
    except Exception as e:
        print(f"[Session] write error: {e}")

_mem_session = {"suggestion": None, "profile": None}


# --- Request/Response Models ---

class DiscoverRequest(BaseModel):
    text: Optional[str] = None
    yaml_content: Optional[str] = None
    fields: Optional[list[dict]] = None
    name: Optional[str] = None
    # New: just provide dataset name, SD fetches schema from landing
    discover_from_landing: Optional[str] = None

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
    _log.info("Health check")
    return {"status": "ok", "glossary_terms": len(kg.terms)}


@app.post("/logs/flush")
def flush_app_logs():
    """Manually flush accumulated logs to GCS."""
    path = flush_logs("discovery")
    return {"status": "flushed", "gcs_path": path}


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


class CreateBDERequest(BaseModel):
    name: str
    domain: str
    synonyms: Optional[list[str]] = None
    data_type: str = "string"
    information_type: str = "Dimension"
    is_pii: bool = False
    is_key_candidate: bool = False
    classification: str = "Internal"
    pattern: Optional[str] = None
    reference_code_set: Optional[str] = None
    dq_rules: Optional[dict] = None


@app.post("/glossary")
def create_bde(req: CreateBDERequest):
    """Create a new Business Data Element in the glossary."""
    import re
    term_id = re.sub(r'[^a-z0-9_]', '_', req.name.lower().strip().replace(' ', '_'))
    term_id = re.sub(r'_+', '_', term_id).strip('_')

    if term_id in kg.terms:
        raise HTTPException(409, f"BDE '{term_id}' already exists")

    # Ensure domain exists
    if req.domain not in kg.domains:
        from discovery.engine.knowledge_graph import DataDomain
        kg.domains[req.domain] = DataDomain(
            id=req.domain,
            name=req.domain.replace('_', ' ').title(),
            description=f"Created with BDE '{req.name}'",
        )

    synonyms = req.synonyms or [req.name.lower(), term_id]
    from discovery.engine.knowledge_graph import BusinessTerm
    term = BusinessTerm(
        id=term_id,
        name=req.name,
        domain=req.domain,
        synonyms=synonyms,
        data_type=req.data_type,
        information_type=req.information_type,
        is_pii=req.is_pii,
        is_key_candidate=req.is_key_candidate,
        classification=req.classification,
        pattern=req.pattern,
        reference_code_set=req.reference_code_set,
        dq_rules=req.dq_rules or {},
    )

    # Add to in-memory KG
    kg.add_term(term)

    # Persist to Dataplex if available
    written = kg.write_term_to_catalog(term)

    # Update catalog cache if available
    if catalog_cache:
        try:
            catalog_cache.upsert_term(term_id, {
                "name": req.name,
                "domain": req.domain,
                "data_type": req.data_type,
                "information_type": req.information_type,
                "is_pii": req.is_pii,
                "classification": req.classification,
                "dq_rules": req.dq_rules or {},
                "synonyms": synonyms,
                "reference_code_set": req.reference_code_set,
                "is_key_candidate": req.is_key_candidate,
            })
        except Exception:
            pass

    # Re-initialize embedder with new term
    try:
        term_dicts = [
            {"id": t.id, "name": t.name, "synonyms": t.synonyms,
             "data_type": t.data_type, "information_type": t.information_type,
             "domain": t.domain}
            for t in kg.get_all_terms()
        ]
        embedder.initialize(term_dicts)
    except Exception:
        pass

    return {
        "status": "created",
        "id": term_id,
        "name": req.name,
        "domain": req.domain,
        "persisted_to_dataplex": written,
    }


@app.get("/glossary/hierarchy")
def get_glossary_hierarchy():
    """Get the full business hierarchy built from live KG state.
    Combines: hardcoded CFU shell + KC-loaded domains/apps/terms + anything
    created dynamically this session via approval."""
    from discovery.engine.catalog_cache.sync import CFUS, DOMAIN_TO_APPS

    # Build reverse map: app_id -> domain_id from both static mapping and kg
    app_to_domain = {}
    for domain_id, app_ids in DOMAIN_TO_APPS.items():
        for app_id in app_ids:
            app_to_domain[app_id] = domain_id

    # Also map any dynamically created apps (from approval) not in static mapping
    # by checking which domain they were linked to in kg
    for app in kg.applications.values():
        if app.id not in app_to_domain:
            # Try to find domain from kg terms
            for term in kg.terms.values():
                if term.domain and app.id in term.domain:
                    app_to_domain[app.id] = term.domain
                    break

    hierarchy = []

    # Track which domains and apps are placed
    placed_domains = set()
    placed_apps = set()

    # Build CFU nodes from static shell
    for cfu_id, cfu_data in CFUS.items():
        cfu_node = {"id": cfu_id, "name": cfu_data["name"], "type": "cfu", "children": []}
        for domain_id in cfu_data["domains"]:
            domain = kg.domains.get(domain_id)
            if not domain:
                continue
            placed_domains.add(domain_id)
            domain_terms = kg.get_terms_by_domain(domain_id)
            domain_node = {
                "id": domain_id,
                "name": domain.name,
                "type": "domain",
                "description": domain.description,
                "term_count": len(domain_terms),
                "children": [],
            }
            # Apps: static mapping first, then any dynamic apps linked to this domain
            app_ids = list(DOMAIN_TO_APPS.get(domain_id, []))
            for app in kg.applications.values():
                if app.id not in app_ids and app_to_domain.get(app.id) == domain_id:
                    app_ids.append(app.id)
            for app_id in app_ids:
                app = kg.applications.get(app_id)
                if not app:
                    continue
                placed_apps.add(app_id)
                app_terms = kg.get_terms_by_domain(domain_id)
                app_node = {
                    "id": app_id,
                    "name": app.name,
                    "type": "application",
                    "description": app.description,
                    "children": [
                        {"id": t.id, "name": t.name, "type": "term",
                         "is_pii": t.is_pii, "dq_rules": t.dq_rules,
                         "data_type": t.data_type, "information_type": t.information_type}
                        for t in app_terms
                    ],
                }
                domain_node["children"].append(app_node)
            cfu_node["children"].append(domain_node)
        hierarchy.append(cfu_node)

    # Append any domains not in any CFU (dynamically created)
    for domain_id, domain in kg.domains.items():
        if domain_id in placed_domains:
            continue
        domain_terms = kg.get_terms_by_domain(domain_id)
        domain_node = {
            "id": domain_id, "name": domain.name, "type": "domain",
            "description": domain.description, "term_count": len(domain_terms),
            "children": [],
        }
        for app in kg.applications.values():
            if app_to_domain.get(app.id) != domain_id or app.id in placed_apps:
                continue
            placed_apps.add(app.id)
            app_terms = kg.get_terms_by_domain(domain_id)
            domain_node["children"].append({
                "id": app.id, "name": app.name, "type": "application",
                "description": app.description,
                "children": [
                    {"id": t.id, "name": t.name, "type": "term",
                     "is_pii": t.is_pii, "dq_rules": t.dq_rules}
                    for t in app_terms
                ],
            })
        hierarchy.append(domain_node)

    # Append orphan terms (in KC but domain not in kg.domains)
    orphan_terms = [t for t in kg.terms.values() if t.domain not in kg.domains]
    if orphan_terms:
        hierarchy.append({
            "id": "_unclassified", "name": "Unclassified", "type": "domain",
            "description": "Terms pending domain assignment",
            "term_count": len(orphan_terms),
            "children": [
                {"id": t.id, "name": t.name, "type": "term",
                 "is_pii": t.is_pii, "dq_rules": t.dq_rules}
                for t in orphan_terms
            ],
        })

    return {"hierarchy": hierarchy}


@app.get("/applications")
def get_applications():
    from discovery.engine.catalog_cache.sync import DOMAIN_TO_APPS
    # Enrich with domain info
    app_to_domain = {}
    for domain_id, app_ids in DOMAIN_TO_APPS.items():
        for app_id in app_ids:
            app_to_domain[app_id] = domain_id
    return [
        {"id": a.id, "name": a.name, "description": a.description,
         "keywords": a.keywords[:5], "domain": app_to_domain.get(a.id)}
        for a in kg.applications.values()
    ]


@app.get("/domains")
def get_domains():
    return [
        {"id": d.id, "name": d.name, "description": d.description,
         "term_count": len(kg.get_terms_by_domain(d.id))}
        for d in kg.domains.values()
    ]


@app.post("/ask")
def ask_catalog(req: SQLRequest):
    """Ask any question about the data catalog. ALWAYS goes to LLM.
    Priority: Cache → MCP Agent (data queries) → LLM (general) → KC Agent fallback."""
    _log.info("Ask request", question=req.requirement[:200])
    # 1. Check cache (exact hash + semantic similarity)
    if response_cache:
        cached = response_cache.get(req.requirement)
        if cached:
            return {"answer": cached, "cached": True}

    # 2. MCP Agent for data-access questions (query, pull, show, count, top N, stats)
    if mcp_agent and _needs_data_access(req.requirement):
        try:
            print(f"[ASK] Routing to MCP agent: {req.requirement[:80]}")
            result = mcp_agent.run(req.requirement)
            if result and "unable to process" not in result.lower() and "unable to retrieve" not in result.lower() and "error" not in result.lower()[:50]:
                # Check if result contains tabular data for charting
                response = {"answer": result}
                chart = _extract_chart_data(result, req.requirement)
                if chart:
                    response["chart"] = chart
                if response_cache:
                    response_cache.put(req.requirement, result)
                return response
        except Exception as e:
            print(f"[ASK] MCP agent failed: {e}")

    # 3. LLM with full catalog context
    try:
        from discovery.engine.llm_client import get_llm
        llm = get_llm()
        domains = [d.name for d in kg.domains.values()]
        apps = [a.name for a in kg.applications.values()]
        terms_sample = [t.name for t in list(kg.terms.values())[:30]]
        system = (
            f"You are Ontika, a data catalog assistant. "
            f"Available domains: {domains}. "
            f"Available business applications: {apps}. "
            f"Sample glossary terms: {terms_sample}. "
            f"Answer the user's question using this context. "
            f"If the question is about data you don't have, say so clearly and suggest what IS available. "
            f"Never say 'no results found' — always give a helpful, conversational answer."
        )
        print(f"[ASK] Calling LLM: base_url={llm.base_url}, model={llm.model}, has_key={bool(llm.api_key)}")
        answer = llm.generate(system=system, user=req.requirement, max_tokens=500)
        print(f"[ASK] LLM response: {repr(answer[:100]) if answer else 'None'}")
        if answer and answer != "__QUOTA_EXCEEDED__":
            if response_cache:
                response_cache.put(req.requirement, answer)
            return {"answer": answer}
    except Exception as e:
        print(f"[ASK] LLM call failed: {e}")

    # 4. Fallback: KC agent (rule-based) — but never return dead-end search results
    if kc_agent:
        answer = kc_agent.answer(req.requirement)
        if answer and "No results found" not in answer:
            if response_cache:
                response_cache.put(req.requirement, answer)
            return {"answer": answer}
        return {"answer": (
            f"I don't have data about that topic. "
            f"The datasets I can help with include: {', '.join(d.name for d in kg.domains.values())}. "
            f"Try asking about one of these, or say **onboard** to add new data."
        )}
    _log.error("LLM service unavailable", question=req.requirement[:100])
    raise HTTPException(503, "LLM service is unavailable")


def _needs_data_access(text: str) -> bool:
    """Detect if the question needs actual data access (MCP agent with tools)."""
    lower = text.lower()
    data_keywords = [
        'pull', 'fetch', 'query', 'select', 'show me records', 'show me data',
        'top ', 'bottom ', 'count ', 'how many records', 'how many rows',
        'from the table', 'from bigquery', 'from bq',
        'get records', 'get data', 'get rows',
        'run a query', 'execute', 'sql',
        'average', 'sum of', 'total of', 'max ', 'min ',
        'group by', 'aggregate', 'breakdown',
        'chart', 'graph', 'plot', 'visuali', 'distribution',
        'top 3', 'top 5', 'top 10', 'top 20', 'top 50', 'top 100',
        'categories', 'spend by', 'revenue by', 'sales by',
    ]
    # Also match "top N" pattern
    import re
    if re.search(r'top\s+\d+', lower):
        return True
    return any(kw in lower for kw in data_keywords)


def _extract_chart_data(result: str, question: str) -> Optional[dict]:
    """If the result contains tabular/aggregate data, extract chart-ready format."""
    lower = question.lower()
    chart_triggers = ['top', 'chart', 'graph', 'plot', 'visuali', 'breakdown',
                      'distribution', 'by category', 'by region', 'spend',
                      'categories', 'compare']
    if not any(t in lower for t in chart_triggers):
        return None

    # Try to parse JSON data from the result (MCP agent returns structured data)
    try:
        import re
        # Look for JSON array in the result
        json_match = re.search(r'\[\s*\{.*?\}\s*\]', result, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            if data and len(data) >= 2:
                keys = list(data[0].keys())
                # First string column = labels, first numeric column = values
                label_col = next((k for k in keys if isinstance(data[0][k], str)), keys[0])
                value_col = next((k for k in keys if isinstance(data[0][k], (int, float)) and k != label_col), None)
                if value_col:
                    return {
                        "type": "bar",
                        "title": question,
                        "labels": [row.get(label_col, '') for row in data[:20]],
                        "values": [row.get(value_col, 0) for row in data[:20]],
                        "label_axis": label_col,
                        "value_axis": value_col,
                    }
    except Exception:
        pass

    # Try to extract from markdown table in the response
    try:
        import re
        lines = result.split('\n')
        table_lines = [l for l in lines if '|' in l and not l.strip().startswith('|-')]
        if len(table_lines) >= 3:  # header + separator + at least 1 row
            headers = [h.strip() for h in table_lines[0].split('|') if h.strip()]
            rows = []
            for line in table_lines[1:]:
                if set(line.strip().replace('|', '').replace('-', '').replace(' ', '')) == set():
                    continue
                cells = [c.strip() for c in line.split('|') if c.strip()]
                if len(cells) == len(headers):
                    rows.append(dict(zip(headers, cells)))
            if rows and len(rows) >= 2:
                label_col = headers[0]
                value_col = headers[-1]
                # Try to parse numeric values
                values = []
                for r in rows:
                    try:
                        v = float(re.sub(r'[^\d.]', '', r[value_col]))
                        values.append(v)
                    except (ValueError, KeyError):
                        values.append(0)
                if any(v > 0 for v in values):
                    return {
                        "type": "bar",
                        "title": question,
                        "labels": [r.get(label_col, '') for r in rows[:20]],
                        "values": values[:20],
                        "label_axis": label_col,
                        "value_axis": value_col,
                    }
    except Exception:
        pass

    return None


@app.get("/cache/stats")
def cache_stats():
    """Get response cache statistics."""
    if not response_cache:
        return {"status": "disabled"}
    return response_cache.stats()


@app.post("/cache/clear")
def cache_clear():
    """Clear the response cache."""
    if not response_cache:
        raise HTTPException(503, "Cache not available")
    count = response_cache.invalidate()
    return {"status": "cleared", "entries_removed": count}


@app.get("/debug/llm")
def debug_llm():
    """Test LLM connectivity directly."""
    from discovery.engine.llm_client import get_llm
    llm = get_llm()
    info = {
        "provider": llm.provider,
        "model": llm.model,
        "base_url": llm.base_url,
        "has_api_key": bool(llm.api_key),
        "api_key_prefix": llm.api_key[:8] + "..." if llm.api_key else "NONE",
        "project": llm.project,
    }
    # Try a simple call
    try:
        result = llm.generate(system="Say hello.", user="Hi", max_tokens=20)
        info["test_response"] = result
        info["status"] = "connected" if result else "no_response"
    except Exception as e:
        info["status"] = "error"
        info["error"] = str(e)
    return info


@app.post("/rag/index")
def rebuild_rag_index():
    """Rebuild the RAG knowledge index from configs, glossary, and docs."""
    try:
        from discovery.engine.rag.indexer import build_index
        count = build_index(
            config_dir="discovery/config",
            glossary_path="discovery/config/seed_glossary.yaml",
            docs_paths=["DATA_CATALOGUE.md", "eastside/docs/DESIGN.md",
                        "eastside/docs/OPERATIONAL_GUIDE.md"],
            gcs_bucket=os.environ.get("CONFIG_BUCKET", "bt-df-lkhouse-lakehouse"),
        )
        return {"status": "indexed", "chunks": count}
    except Exception as e:
        raise HTTPException(500, f"Index build failed: {str(e)}")


@app.get("/mcp/tools")
def list_mcp_tools():
    """List available MCP tools the agent can call."""
    try:
        from discovery.engine.mcp.tools import get_tool_definitions
        return {"tools": get_tool_definitions()}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/catalog/tree")
def get_catalog_tree():
    """Get the full catalog hierarchy for interactive tree rendering."""
    if not catalog_cache:
        raise HTTPException(503, "Catalog cache not available")
    return {"hierarchy": catalog_cache.get_hierarchy()}


@app.get("/catalog/flat")
def get_catalog_flat():
    """Get all catalog entities in flat structure."""
    if not catalog_cache:
        raise HTTPException(503, "Catalog cache not available")
    return catalog_cache.get_full_tree()


@app.get("/catalog/search")
def search_catalog(q: str):
    """Search across all catalog entities."""
    if not catalog_cache:
        raise HTTPException(503, "Catalog cache not available")
    results = catalog_cache.search(q)
    return {"query": q, "count": len(results), "results": results}


@app.post("/catalog/sync")
def trigger_catalog_sync():
    """Manually trigger a catalog sync from glossary."""
    if not catalog_cache:
        raise HTTPException(503, "Catalog cache not available")
    counts = sync_from_glossary(catalog_cache)
    return {"status": "synced", "counts": counts}


@app.post("/discover")
def discover(req: DiscoverRequest):
    """Run full discovery on a dataset definition.
    Supports: dataset name, natural language, YAML, or direct fields."""
    _log.info("Discover request", text=req.text[:200] if req.text else None,
              name=req.name, discover_from_landing=req.discover_from_landing)
    asset_def = None

    # Mode 1: Explicit discover from landing
    if req.discover_from_landing:
        asset_def = _fetch_schema_from_landing(req.discover_from_landing)
        if not asset_def:
            raise HTTPException(404, f"No landing data found for '{req.discover_from_landing}'")

    # Mode 2: Natural language / conversational
    elif req.text:
        asset_def = _resolve_from_text(req.text)
        if not asset_def:
            raise HTTPException(400, "Could not understand the request. Try a dataset name or describe what you want to onboard.")

    # Mode 3: Parse from YAML
    elif req.yaml_content:
        import yaml
        try:
            asset_def = yaml.safe_load(req.yaml_content)
        except Exception:
            raise HTTPException(400, "Invalid YAML")

    # Mode 4: Direct fields
    elif req.fields and req.name:
        asset_def = {"name": req.name, "fields": req.fields}

    if not asset_def or not asset_def.get("fields"):
        raise HTTPException(400, "Provide text, yaml_content, name+fields, or discover_from_landing")

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

    _session_set("suggestion", suggestion)
    _log.info("Discovery complete", asset_name=suggestion.asset_name,
              fields=len(suggestion.fields), domain=suggestion.data_domain,
              business_app=suggestion.business_application_name)
    flush_logs("discovery")
    return _serialize_suggestion(suggestion)


@app.get("/landing/datasets")
def list_landing_datasets():
    """List all datasets available in the landing zone."""
    datasets = _list_landing_datasets()
    return {"datasets": datasets, "count": len(datasets)}


@app.post("/discover/all")
def discover_all_landing():
    """Discover all datasets in landing zone. Returns list of suggestions."""
    datasets = _list_landing_datasets()
    results = []
    for ds_name in datasets:
        asset_def = _fetch_schema_from_landing(ds_name)
        if asset_def and asset_def.get("fields"):
            suggestion = suggester.full_discovery(asset_def)
            results.append(_serialize_suggestion(suggestion))
    return {"datasets": results, "count": len(results)}


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
        _session_set("suggestion", suggester.full_discovery(datasets[0]))

    return {"datasets": results, "count": len(results)}


@app.post("/profile")
def profile_data(req: ProfileRequest):
    """Profile sample data (pasted)."""
    if req.format == "csv":
        profile = profiler.profile_csv(req.data)
    else:
        profile = profiler.profile_jsonl(req.data)

    if not profile.columns:
        raise HTTPException(400, "Could not parse data")

    _session_set("profile", profile)
    return _serialize_profile(profile)


class DatasetProfileRequest(BaseModel):
    dataset_name: str

@app.post("/profile/dataset")
def profile_dataset_from_landing(req: DatasetProfileRequest):
    """Profile a dataset by calling the Profiler Service."""
    import urllib.request
    profiler_url = os.environ.get("PROFILER_SERVICE_URL", "")
    if not profiler_url:
        raise HTTPException(503, "Profiler service URL not configured")

    try:
        url = f"{profiler_url}/profile"
        payload = json.dumps({"dataset_name": req.dataset_name}).encode()
        http_req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(http_req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
        return result
    except Exception as e:
        raise HTTPException(502, f"Profiler service error: {str(e)}")


@app.post("/approve")
def approve(req: ApproveRequest):
    """Approve current suggestion."""
    suggestion = _session_get("suggestion")
    if not suggestion:
        raise HTTPException(400, "No active discovery to approve")
    _log.info("Approval request", asset_name=suggestion.asset_name,
              approved_fields=req.fields)

    config_yaml = config_gen.generate(suggestion, approved_fields=req.fields)

    if not approval_handler:
        return {"status": "approved", "config_yaml": config_yaml, "errors": ["Approval handler not available (GCP deps missing)"]}

    results = approval_handler.process_approval(suggestion, config_yaml=config_yaml)

    # Update in-memory knowledge graph with new BA/domain/terms
    if suggestion.business_application and suggestion.business_application not in kg.applications:
        from discovery.engine.knowledge_graph import BusinessApplication
        kg.applications[suggestion.business_application] = BusinessApplication(
            id=suggestion.business_application,
            name=suggestion.business_application_name or suggestion.business_application.replace("_", " ").title(),
            description=f"Created during onboarding of {suggestion.asset_name}",
            keywords=suggestion.asset_name.replace("_", " ").split(),
        )
    if suggestion.data_domain and suggestion.data_domain not in kg.domains:
        from discovery.engine.knowledge_graph import DataDomain
        kg.domains[suggestion.data_domain] = DataDomain(
            id=suggestion.data_domain,
            name=suggestion.data_domain.replace("_", " ").title(),
            description=f"Created during onboarding of {suggestion.asset_name}",
        )
    # Add newly created BDE terms to in-memory KG so hierarchy reflects them immediately
    from discovery.engine.knowledge_graph import BusinessTerm
    for field in suggestion.fields:
        if field.linked_term and field.linked_term not in kg.terms:
            kg.terms[field.linked_term] = BusinessTerm(
                id=field.linked_term,
                name=field.linked_term_name or field.linked_term.replace("-", " ").title(),
                domain=suggestion.data_domain or "",
                synonyms=[field.field_name, field.linked_term],
                data_type=field.field_type,
                information_type=field.information_type or "Dimension",
                is_pii=field.is_pii,
                classification=field.classification,
                dq_rules=field.dq_rules,
            )

    # Update catalog cache immediately
    if catalog_cache:
        try:
            sync_dataset_on_approval(catalog_cache, suggestion)
        except Exception as e:
            results.setdefault("errors", []).append(f"Cache update failed: {e}")

    # Contract
    contract_path = None
    if contract_gen:
        contract_path = contract_gen.generate_and_push(suggestion)

    # SCD
    scd_path = None
    if scd_gen:
        scd_type = scd_gen.infer_scd_type("", suggestion.data_domain)
        scd_path = scd_gen.generate_and_push(suggestion, scd_type=scd_type)

    # Trigger first pipeline run via Dagster (EastSide datasets only)
    dagster_run_id = None
    if results.get("config_gcs_path") and "eastside-lakehouse" in (results["config_gcs_path"] or ""):
        dagster_run_id = _trigger_dagster_job(suggestion.asset_name)
        if dagster_run_id:
            _log.info("Dagster job triggered", run_id=dagster_run_id, table=suggestion.asset_name)

    _log.info("Approval complete", asset_name=suggestion.asset_name,
              new_terms=results["new_terms_created"], ba_linked=results["ba_linked"],
              config_path=results["config_gcs_path"], errors=results["errors"])
    flush_logs("approval")
    return {
        "status": "approved",
        "new_terms_created": results["new_terms_created"],
        "ba_linked": results["ba_linked"],
        "config_gcs_path": results["config_gcs_path"],
        "contract_path": contract_path,
        "scd_path": scd_path,
        "dagster_run_id": dagster_run_id,
        "errors": results["errors"],
        "config_yaml": config_yaml,
    }


@app.post("/correct")
def correct(req: CorrectionRequest):
    """Apply a correction to the current suggestion."""
    suggestion = _session_get("suggestion")
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

    _session_set("suggestion", suggestion)
    return {"status": "corrected", "field": req.field, "action": req.action}


@app.get("/suggestion")
def get_current_suggestion():
    """Get current active suggestion."""
    suggestion = _session_get("suggestion")
    if not suggestion:
        raise HTTPException(404, "No active discovery")
    return _serialize_suggestion(suggestion)


@app.post("/generate/config")
def generate_config():
    """Generate pipeline YAML from current suggestion."""
    suggestion = _session_get("suggestion")
    if not suggestion:
        raise HTTPException(400, "No active discovery")
    return {"yaml": config_gen.generate(suggestion)}


@app.post("/generate/dataproduct")
def generate_dataproduct(req: SQLRequest):
    """Generate a data product SQL from a free-text spec and push to GCS."""
    from discovery.engine.sql_generator import SQLGenerator
    result = SQLGenerator().generate_dataproduct(req.requirement)
    if result.get("error"):
        raise HTTPException(503, result["error"])
    return result


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

DAGSTER_URL = os.environ.get("DAGSTER_URL", "http://34.89.76.230")


def _trigger_dagster_job(table_name: str) -> Optional[str]:
    """Trigger the eastside_pipeline_job on Dagster for a specific table."""
    import urllib.request
    graphql_url = f"{DAGSTER_URL}/graphql"
    query = """
    mutation($executionParams: ExecutionParams!) {
      launchRun(executionParams: $executionParams) {
        __typename
        ... on LaunchRunSuccess { run { runId } }
        ... on PythonError { message }
        ... on InvalidSubsetError { message }
        ... on RunConfigValidationInvalid { errors { message } }
      }
    }
    """
    variables = {
        "executionParams": {
            "selector": {
                "repositoryLocationName": "eastside_dagster",
                "repositoryName": "__repository__",
                "jobName": "eastside_pipeline_job",
            },
            "runConfigData": json.dumps({
                "ops": {
                    "bronze_asset": {"config": {"table": table_name}},
                    "silver_asset": {"config": {"table": table_name}},
                    "gold_asset": {"config": {"table": table_name}},
                }
            }),
        }
    }
    payload = json.dumps({"query": query, "variables": variables}).encode()
    try:
        req = urllib.request.Request(graphql_url, data=payload,
                                    headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
        launch = result.get("data", {}).get("launchRun", {})
        if launch.get("__typename") == "LaunchRunSuccess":
            return launch["run"]["runId"]
        print(f"[API] Dagster launch failed: {launch}")
    except Exception as e:
        print(f"[API] Dagster trigger failed: {e}")
    return None


def _list_landing_datasets() -> list[str]:
    """List all dataset folders in GCS landing zones (both default and EastSide)."""
    import os
    buckets = [
        os.environ.get("CONFIG_BUCKET", "bt-df-lkhouse-lakehouse"),
        "eastside-lakehouse",
    ]
    datasets = []
    try:
        from google.cloud import storage as gcs_storage
        client = gcs_storage.Client()
        for bucket_name in buckets:
            try:
                bucket = client.bucket(bucket_name)
                blobs = client.list_blobs(bucket, prefix="landing/", delimiter="/")
                list(blobs)  # consume to get prefixes
                for prefix in blobs.prefixes:
                    name = prefix.replace("landing/", "").strip("/")
                    if name and name not in datasets:
                        datasets.append(name)
            except Exception as e:
                print(f"[API] Failed to list landing in {bucket_name}: {e}")
        return sorted(datasets)
    except Exception as e:
        print(f"[API] Failed to list landing datasets: {e}")
        return []


def _resolve_from_text(text: str) -> Optional[dict]:
    """Resolve natural language input to an asset definition.
    Strategy:
    1. Check if text matches or fuzzy-matches a landing dataset name
    2. Use LLM to extract dataset name from conversational input
    3. Fall back to NL parser for field extraction
    """
    import re
    text_clean = text.strip()
    text_lower = text_clean.lower()

    # Get available landing datasets
    available = _list_landing_datasets()
    available_lower = {d.lower(): d for d in available}

    # Strategy 1: Direct name match (user typed exact name)
    if text_lower.replace(' ', '_') in available_lower:
        name = available_lower[text_lower.replace(' ', '_')]
        return _fetch_schema_from_landing(name)

    # Strategy 2: Extract name from common patterns
    patterns = [
        r"(?:onboard|discover|load|process|ingest|profile|check)\s+(?:the\s+)?(.+?)(?:\s+(?:dataset|feed|table|source))?\s*$",
        r"(?:i want to|please|can you|let'?s)\s+(?:onboard|discover|load|process)\s+(?:the\s+)?(.+?)(?:\s+(?:dataset|feed|table))?\s*$",
        r"(?:new|add)\s+(.+?)(?:\s+(?:dataset|feed|table))?\s*$",
        r"(?:what about|how about|try)\s+(?:the\s+)?(.+?)(?:\s+(?:dataset|feed))?\s*$",
    ]

    extracted_name = None
    for pattern in patterns:
        m = re.search(pattern, text_lower)
        if m:
            extracted_name = m.group(1).strip()
            break

    if not extracted_name:
        extracted_name = text_lower

    # Clean and try to match against available datasets
    extracted_clean = extracted_name.replace(' ', '_').replace('-', '_')
    extracted_clean = re.sub(r'[^a-z0-9_]', '', extracted_clean)

    # Exact match after cleaning
    if extracted_clean in available_lower:
        return _fetch_schema_from_landing(available_lower[extracted_clean])

    # Fuzzy match: find best matching landing dataset
    best_match, best_score = None, 0
    for ds_name in available:
        ds_lower = ds_name.lower()
        # Check if extracted name is a substring or vice versa
        if extracted_clean in ds_lower or ds_lower in extracted_clean:
            score = len(extracted_clean) / max(len(ds_lower), len(extracted_clean))
            if score > best_score:
                best_score = score
                best_match = ds_name
        # Check word overlap (including partial word matches)
        else:
            words_input = set(extracted_clean.split('_'))
            words_ds = set(ds_lower.split('_'))
            # Full word overlap
            overlap = words_input & words_ds
            # Also check if any input word is a prefix of a ds word or vice versa
            for wi in words_input:
                for wd in words_ds:
                    if wi.startswith(wd) or wd.startswith(wi) and len(min(wi, wd, key=len)) >= 2:
                        overlap.add(wi)
            if overlap:
                score = len(overlap) / max(len(words_input), len(words_ds))
                if score > best_score:
                    best_score = score
                    best_match = ds_name

    if best_match and best_score >= 0.25:
        print(f"[API] Fuzzy matched '{text_clean}' → '{best_match}' (score: {best_score:.0%})")
        return _fetch_schema_from_landing(best_match)

    # Strategy 3: Use LLM to resolve dataset name from available list
    if available:
        try:
            from discovery.engine.llm_client import get_llm
            prompt = (
                f"The user said: \"{text_clean}\"\n"
                f"Available datasets in landing zone: {available}\n"
                f"Which dataset name does the user want to onboard? "
                f"Return ONLY the exact dataset name from the list, nothing else. "
                f"If multiple match, return the most likely one. If none match, return NONE."
            )
            response = get_llm().generate(
                system="You match user requests to dataset names. Return only the dataset name from the list. If none match return NONE.",
                user=prompt,
                max_tokens=50,
                temperature=0.0,
            )
            if response and response != "__QUOTA_EXCEEDED__":
                llm_name = response.strip().strip('"\' ')
                if llm_name in available:
                    print(f"[API] LLM resolved '{text_clean}' → '{llm_name}'")
                    return _fetch_schema_from_landing(llm_name)
                # Try case-insensitive
                for ds in available:
                    if ds.lower() == llm_name.lower():
                        return _fetch_schema_from_landing(ds)
        except Exception as e:
            print(f"[API] LLM resolution failed: {e}")

    # Strategy 4: Fall back to NL parser (extracts fields from text)
    parsed = nl_parser.parse(text)
    if parsed and parsed.get("fields"):
        return parsed

    return None


def _fetch_schema_from_landing(dataset_name: str) -> Optional[dict]:
    """Fetch schema from landing data in GCS. Checks both default and EastSide buckets."""
    import os
    buckets = [
        os.environ.get("CONFIG_BUCKET", "bt-df-lkhouse-lakehouse"),
        "eastside-lakehouse",
    ]
    prefix = f"landing/{dataset_name}/"

    try:
        from google.cloud import storage as gcs_storage
        client = gcs_storage.Client()

        blobs = None
        for bucket_name in buckets:
            bucket = client.bucket(bucket_name)
            found = list(bucket.list_blobs(prefix=prefix, max_results=5))
            if found:
                blobs = found
                break

        if not blobs:
            return None

        # Read first actual file (skip folder markers)
        blob = next((b for b in blobs if b.size and b.size > 0 and not b.name.endswith('/')), None)
        if not blob:
            return None
        content = blob.download_as_text()
        if not content.strip():
            return None

        # Parse to get field names
        import json
        import csv
        from io import StringIO

        if blob.name.endswith(".csv"):
            source_format = "csv"
            reader = csv.DictReader(StringIO(content))
            row = next(reader, None)
            if not row:
                return None
            fields = [{"name": k.strip(), "type": "string"} for k in row.keys()]
        else:
            source_format = "json"
            # JSONL
            first_line = content.strip().split("\n")[0]
            record = json.loads(first_line)
            fields = [{"name": k, "type": "string"} for k in record.keys()]

        if not fields:
            return None

        print(f"[API] Fetched schema from landing/{dataset_name}/: {len(fields)} fields ({source_format})")
        return {"name": dataset_name, "fields": fields, "source_format": source_format}

    except ImportError:
        print("[API] google-cloud-storage not available")
        return None
    except Exception as e:
        print(f"[API] Failed to fetch schema from landing: {e}")
        return None


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
                "accepted_values": f.accepted_values,
                "reference_code_set": f.reference_code_set,
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


# --- SPA Fallback (must be LAST — after all API routes) ---
if static_dir.exists():
    from fastapi.responses import FileResponse

    @app.get("/")
    async def serve_index():
        return FileResponse(str(static_dir / "index.html"))

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        # Don't catch API paths
        if path.startswith(("health", "glossary", "applications", "domains",
                           "ask", "discover", "landing", "profile", "approve",
                           "correct", "suggestion", "generate", "catalog",
                           "cache", "debug", "rag", "mcp", "logs")):
            raise HTTPException(404, "Not found")
        file_path = static_dir / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(static_dir / "index.html"))
