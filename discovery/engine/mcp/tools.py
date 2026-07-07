"""MCP Tools — Functions the LLM can invoke to interact with the data platform.

Each tool has:
    - name: unique identifier
    - description: what it does (shown to LLM)
    - parameters: JSON schema of inputs
    - handler: Python function that executes it

Tools are grouped by capability:
    - Query: read data from Iceberg/BigQuery
    - Config: read/list table configurations
    - Status: pipeline health, reconciliation, DQ reports
    - Action: trigger pipeline runs (with guardrails)
"""
import os
import json
import yaml
from typing import Dict, Any, List, Optional
from datetime import datetime


# ============================================================
# TOOL REGISTRY
# ============================================================

TOOLS: List[Dict] = []


def tool(name: str, description: str, parameters: Dict):
    """Decorator to register a tool."""
    def decorator(func):
        TOOLS.append({
            "name": name,
            "description": description,
            "parameters": parameters,
            "handler": func,
        })
        return func
    return decorator


def get_tool_definitions() -> List[Dict]:
    """Return tool definitions in OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
        }
        for t in TOOLS
    ]


def execute_tool(name: str, arguments: Dict) -> str:
    """Execute a tool by name with given arguments."""
    for t in TOOLS:
        if t["name"] == name:
            try:
                result = t["handler"](**arguments)
                return json.dumps(result, default=str) if isinstance(result, (dict, list)) else str(result)
            except Exception as e:
                return f"Error executing {name}: {str(e)}"
    return f"Unknown tool: {name}"


# ============================================================
# QUERY TOOLS
# ============================================================

@tool(
    name="query_table",
    description="Execute a SQL query against a BigQuery table or Iceberg table. Returns actual rows (up to 100). Use this for any 'show me data', 'pull records', 'top N', 'count' requests.",
    parameters={
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "Full SQL query to execute. Use project bt-df-lkhouse, datasets: eastside_dataproduct (gold), lakehouse_dataproduct (original). Example: SELECT * FROM `bt-df-lkhouse.eastside_dataproduct.loan_eligibility_360` LIMIT 10"},
        },
        "required": ["sql"],
    }
)
def query_table(sql: str) -> Dict:
    """Execute SQL against BigQuery and return results."""
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=os.environ.get("PROJECT_ID", "bt-df-lkhouse"))

        # Safety: enforce LIMIT
        sql_upper = sql.strip().upper()
        if "LIMIT" not in sql_upper:
            sql = sql.rstrip(";") + " LIMIT 100"

        # Safety: block destructive operations
        if any(kw in sql_upper for kw in ["DROP", "DELETE", "TRUNCATE", "INSERT", "UPDATE", "ALTER", "CREATE"]):
            return {"error": "Only SELECT queries are allowed."}

        query_job = client.query(sql)
        results = query_job.result()

        rows = []
        columns = [field.name for field in results.schema]
        for row in results:
            rows.append({col: row[col] for col in columns})

        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "sql": sql,
        }
    except Exception as e:
        return {"error": str(e), "sql": sql}


@tool(
    name="get_table_stats",
    description="Get row count, column count, and latest ingestion time for a table.",
    parameters={
        "type": "object",
        "properties": {
            "layer": {"type": "string", "enum": ["bronze", "silver", "gold"]},
            "table_name": {"type": "string", "description": "Table name"},
        },
        "required": ["layer", "table_name"],
    }
)
def get_table_stats(layer: str, table_name: str) -> Dict:
    """Get basic stats for a table."""
    try:
        if layer == "gold":
            from google.cloud import bigquery
            client = bigquery.Client()
            project = os.environ.get("PROJECT_ID", "bt-df-lkhouse")
            dataset = "eastside_dataproduct"
            table_ref = f"{project}.{dataset}.{table_name}"
            table = client.get_table(table_ref)
            return {
                "table": table_ref,
                "row_count": table.num_rows,
                "column_count": len(table.schema),
                "size_bytes": table.num_bytes,
                "last_modified": str(table.modified),
                "columns": [f.name for f in table.schema],
            }
        else:
            # For Iceberg tables, read metadata from GCS
            from google.cloud import storage
            bucket_name = os.environ.get("EASTSIDE_BUCKET", "eastside-lakehouse")
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            prefix = f"{layer}/{table_name}/metadata/"
            blobs = list(bucket.list_blobs(prefix=prefix, max_results=5))
            return {
                "table": f"eastside.{layer}.{table_name}",
                "metadata_files": len(blobs),
                "layer": layer,
                "status": "exists" if blobs else "not_found",
            }
    except Exception as e:
        return {"error": str(e), "table": f"eastside.{layer}.{table_name}"}


# ============================================================
# CONFIG TOOLS
# ============================================================

@tool(
    name="get_table_config",
    description="Read the full YAML configuration for a table (DQ rules, schema evolution, PII fields, etc).",
    parameters={
        "type": "object",
        "properties": {
            "table_name": {"type": "string", "description": "Table name"},
            "bucket": {"type": "string", "description": "GCS bucket (default: eastside-lakehouse)"},
        },
        "required": ["table_name"],
    }
)
def get_table_config(table_name: str, bucket: str = "eastside-lakehouse") -> Dict:
    """Read table config from GCS."""
    try:
        from google.cloud import storage
        client = storage.Client()
        b = client.bucket(bucket)
        blob = b.blob(f"config/tables/{table_name}.yaml")
        if blob.exists():
            config = yaml.safe_load(blob.download_as_text())
            return {"table": table_name, "config": config}
        else:
            return {"error": f"Config not found: config/tables/{table_name}.yaml"}
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="list_tables",
    description="List all configured tables with their domain and source format.",
    parameters={
        "type": "object",
        "properties": {
            "bucket": {"type": "string", "description": "GCS bucket (default: eastside-lakehouse)"},
        },
    }
)
def list_tables(bucket: str = "eastside-lakehouse") -> Dict:
    """List all table configs from GCS."""
    try:
        from google.cloud import storage
        client = storage.Client()
        b = client.bucket(bucket)
        blobs = list(b.list_blobs(prefix="config/tables/"))
        tables = []
        for blob in blobs:
            if blob.name.endswith(".yaml"):
                config = yaml.safe_load(blob.download_as_text())
                tables.append({
                    "table": config.get("table"),
                    "domain": config.get("domain"),
                    "source_format": config.get("source_format"),
                    "is_cdc": config.get("is_cdc", False),
                    "business_application": config.get("business_application"),
                })
        return {"count": len(tables), "tables": tables}
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# STATUS TOOLS
# ============================================================

@tool(
    name="get_reconciliation_status",
    description="Get the latest reconciliation results for a table (source↔bronze, bronze↔silver counts and pass/fail).",
    parameters={
        "type": "object",
        "properties": {
            "table_name": {"type": "string", "description": "Table name (or 'all' for summary)"},
        },
        "required": ["table_name"],
    }
)
def get_reconciliation_status(table_name: str) -> Dict:
    """Read latest reconciliation from GCS logs."""
    try:
        from google.cloud import storage
        bucket_name = os.environ.get("EASTSIDE_BUCKET", "eastside-lakehouse")
        client = storage.Client()
        bucket = client.bucket(bucket_name)

        # Find latest recon log
        blobs = list(bucket.list_blobs(prefix="logs/reconcile/"))
        if not blobs:
            return {"status": "no_reconciliation_runs_found"}

        latest = max(blobs, key=lambda b: b.time_created)
        content = latest.download_as_text()
        lines = [json.loads(l) for l in content.strip().split("\n") if l.strip()]

        if table_name == "all":
            return {"run": latest.name, "entries": len(lines), "log": lines[-20:]}

        # Filter for specific table
        table_lines = [l for l in lines if table_name in l.get("msg", "")]
        return {"table": table_name, "run": latest.name, "log": table_lines[-10:]}
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="get_dq_report",
    description="Get a DQ (data quality) flag summary for a table in bronze — shows which flags were triggered and how many records affected.",
    parameters={
        "type": "object",
        "properties": {
            "table_name": {"type": "string", "description": "Table name"},
        },
        "required": ["table_name"],
    }
)
def get_dq_report(table_name: str) -> Dict:
    """Summarise DQ flags from bronze layer."""
    # This would query the Iceberg table's _dq_flags column
    # For now, return from latest log
    try:
        from google.cloud import storage
        bucket_name = os.environ.get("EASTSIDE_BUCKET", "eastside-lakehouse")
        client = storage.Client()
        bucket = client.bucket(bucket_name)

        blobs = list(bucket.list_blobs(prefix="logs/bronze/"))
        if not blobs:
            return {"status": "no_bronze_runs_found"}

        latest = max(blobs, key=lambda b: b.time_created)
        content = latest.download_as_text()
        lines = [json.loads(l) for l in content.strip().split("\n") if l.strip()]

        # Find DQ-related log lines for this table
        dq_lines = [l for l in lines if "dq" in l.get("stage", "").lower()
                    and table_name in l.get("msg", "")]
        return {"table": table_name, "run": latest.name, "dq_log": dq_lines}
    except Exception as e:
        return {"error": str(e)}


@tool(
    name="get_pipeline_history",
    description="Get recent pipeline run history (last N runs) for a specific stage (bronze/silver/gold).",
    parameters={
        "type": "object",
        "properties": {
            "stage": {"type": "string", "enum": ["bronze", "silver", "gold", "reconcile"]},
            "limit": {"type": "integer", "description": "Number of recent runs (default 5)"},
        },
        "required": ["stage"],
    }
)
def get_pipeline_history(stage: str, limit: int = 5) -> Dict:
    """List recent pipeline runs for a stage."""
    try:
        from google.cloud import storage
        bucket_name = os.environ.get("EASTSIDE_BUCKET", "eastside-lakehouse")
        client = storage.Client()
        bucket = client.bucket(bucket_name)

        blobs = list(bucket.list_blobs(prefix=f"logs/{stage}/"))
        blobs.sort(key=lambda b: b.time_created, reverse=True)
        runs = []
        for blob in blobs[:limit]:
            runs.append({
                "file": blob.name,
                "timestamp": str(blob.time_created),
                "size_bytes": blob.size,
            })
        return {"stage": stage, "runs": runs, "total_runs": len(blobs)}
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# ACTION TOOLS (with guardrails)
# ============================================================

@tool(
    name="trigger_pipeline",
    description="Trigger a pipeline run for a specific layer and table. Requires confirmation. Returns the command to execute (does not auto-execute for safety).",
    parameters={
        "type": "object",
        "properties": {
            "layer": {"type": "string", "enum": ["bronze", "silver", "gold", "reconcile"]},
            "table_name": {"type": "string", "description": "Table name (or 'all')"},
            "version": {"type": "string", "description": "Data version (default: v1)"},
        },
        "required": ["layer", "table_name"],
    }
)
def trigger_pipeline(layer: str, table_name: str, version: str = "v1") -> Dict:
    """Generate the pipeline trigger command (does NOT auto-execute)."""
    project = os.environ.get("PROJECT_ID", "bt-df-lkhouse")
    region = os.environ.get("REGION", "europe-west2")
    table_arg = "--all" if table_name == "all" else f"--table {table_name}"

    commands = {
        "bronze": f"bash eastside/scripts/run_bronze.sh {project} {region} {table_name} {version}",
        "silver": f"bash eastside/scripts/run_silver.sh {project} {region} {table_name}",
        "gold": f"bash eastside/scripts/run_gold.sh {project} {region} {table_name}",
        "reconcile": f"bash eastside/scripts/run_reconcile.sh {project} {region} {table_name}",
    }

    return {
        "action": "trigger_pipeline",
        "layer": layer,
        "table": table_name,
        "command": commands.get(layer, "unknown"),
        "status": "READY_TO_EXECUTE",
        "note": "This command is ready to run. Copy and execute in Cloud Shell, or say 'execute' to confirm.",
    }


@tool(
    name="refresh_rag_index",
    description="Rebuild the RAG knowledge index from latest configs, glossary, and logs.",
    parameters={"type": "object", "properties": {}},
)
def refresh_rag_index() -> Dict:
    """Trigger RAG index rebuild."""
    try:
        from discovery.engine.rag.indexer import build_index
        count = build_index(
            config_dir="eastside/config",
            glossary_path="discovery/config/seed_glossary.yaml",
            docs_paths=[
                "DATA_CATALOGUE.md",
                "eastside/docs/DESIGN.md",
                "eastside/docs/OPERATIONAL_GUIDE.md",
            ],
            gcs_bucket="eastside-lakehouse",
        )
        return {"status": "success", "chunks_indexed": count}
    except Exception as e:
        return {"error": str(e)}
