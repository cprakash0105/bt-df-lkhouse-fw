"""SQL Generator — Generates consumption SQL from natural language requirements.
Uses Vertex AI Gemini + knowledge of available CCN tables to produce
pipeline-ready SQL for the Data Product layer."""
import os
import json
from typing import Optional

try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False


PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "bt-df-lkhouse")
LOCATION = os.environ.get("GCP_REGION", "europe-west2")
CONFIG_BUCKET = os.environ.get("CONFIG_BUCKET", f"{PROJECT_ID}-lakehouse")


SYSTEM_PROMPT = """You are a BigQuery SQL expert for the EastSide data platform.

Platform conventions:
- Silver tables are BigQuery external tables in dataset `eastside_silver`: `eastside_silver.<table>`
  All silver tables have SCD2 columns: valid_from, valid_to, is_current
  Always filter: WHERE is_current = true
- Output target: `eastside_dataproduct.<name>` (BigQuery native table)
- Dedup each source on its primary key before joining (use QUALIFY ROW_NUMBER())
- Use LEFT JOIN for ALL dimension table joins
- Never drop dimensions or metrics from the spec — include every one in SELECT and GROUP BY
- Foreign keys added in later schema versions (e.g. device_id) may be NULL — use LEFT JOIN and COALESCE where needed
- Geographic columns (city, state, region) must come from location_master joined via cell_tower_id, NOT from subscriber_master
- Do NOT expose raw PII fields (first_name, last_name, email, phone, date_of_birth) in output
- Use CREATE OR REPLACE TABLE syntax
- Output ONLY valid BigQuery SQL. No explanation, no markdown fences.

Available silver tables: {available_tables}"""


class SQLGenerator:
    """Generates consumption SQL from natural language using Gemini."""

    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id or PROJECT_ID

    def generate(self, requirement: str, available_tables: list[str] = None) -> Optional[str]:
        """Generate SQL from a natural language requirement."""
        if available_tables is None:
            available_tables = self._get_available_tables()

        tables_desc = ", ".join(available_tables)
        prompt = SYSTEM_PROMPT.format(available_tables=tables_desc)

        sql = self._generate_with_gemini(prompt, requirement)
        if sql:
            return sql

        return None

    def generate_and_push(self, requirement: str, table_name: str = None,
                          available_tables: list[str] = None) -> Optional[str]:
        """Generate SQL and push to GCS for the pipeline to pick up."""
        sql = self.generate(requirement, available_tables)
        if not sql:
            return None

        # Extract table name from SQL if not provided
        if not table_name:
            table_name = self._extract_table_name(sql)

        # Push to GCS
        gcs_path = self._push_to_gcs(table_name, sql)
        return gcs_path

    def _generate_with_gemini(self, system_prompt: str, requirement: str) -> Optional[str]:
        """Use LLM to generate SQL."""
        from discovery.engine.llm_client import get_llm
        return get_llm().generate(system=system_prompt, user=requirement, max_tokens=3000)

    def generate_dataproduct(self, spec: str) -> dict:
        """Generate a full data product: SQL + metadata from a free-text or YAML spec.
        Returns {sql, table_name, gcs_path}."""
        import re, yaml as _yaml

        available_tables = self._get_available_tables()
        tables_desc = ", ".join(available_tables)

        # Extract product name and clean spec if it's a YAML data_product spec
        product_name = None
        clean_spec = spec
        source_tables = []
        try:
            parsed = _yaml.safe_load(spec)
            if isinstance(parsed, dict) and "data_product" in parsed:
                dp = parsed["data_product"]
                product_name = dp.get("name")
                source_tables = dp.get("source_datasets", [])
                metrics = [m.get("name") if isinstance(m, dict) else m for m in dp.get("metrics", [])]
                metric_exprs = [
                    f"{m.get('name')}: {m.get('expression')}" if isinstance(m, dict) else str(m)
                    for m in dp.get("metrics", [])
                ]
                dimensions = dp.get("dimensions", [])
                filters = dp.get("filters", [])
                grain = dp.get("grain", "")
                output_table = dp.get("output_table", f"eastside_dataproduct.{product_name}")
                clean_spec = (
                    f"Build a BigQuery data product called {product_name}.\n"
                    f"Output table: {output_table}\n"
                    f"Source silver tables (prefix with silver.): {', '.join(str(s) for s in source_tables)}\n"
                    f"Metrics (include ALL of these):\n" +
                    "\n".join(f"  - {e}" for e in metric_exprs) + "\n"
                    f"Dimensions to include: {', '.join(str(d) for d in dimensions)}\n"
                    f"Filters: {', '.join(str(f) for f in filters)}\n"
                    f"Grain: {grain}\n"
                    f"Join all source tables together using the correct join keys from the source schemas provided.\n"
                    f"Use LEFT JOIN for all dimension tables.\n"
                    f"For foreign keys that may be NULL (added in later schema versions like device_id), use LEFT JOIN and handle NULLs gracefully.\n"
                    f"city, state, region must come from location_master joined via cell_tower_id, NOT from subscriber_master.\n"
                    f"Always include ALL dimensions from the spec in both SELECT and GROUP BY.\n"
                    f"Never drop a dimension or metric from the spec — if a column may be NULL use COALESCE or LEFT JOIN.\n"
                    f"Dedup each source using QUALIFY ROW_NUMBER() OVER (PARTITION BY <pk> ORDER BY event_timestamp DESC) = 1.\n"
                    f"Filter is_current = true on all silver tables.\n"
                    f"Do NOT expose PII fields (first_name, last_name, email, phone, date_of_birth).\n"
                    f"Add _gold_published_at = CURRENT_TIMESTAMP() to output.\n"
                )
        except Exception:
            pass

        # Fetch schemas of source datasets from GCS landing — union of all versions
        source_schemas = {}
        if source_tables and GCS_AVAILABLE:
            try:
                import csv as _csv
                from io import StringIO as _StringIO
                gcs_client = storage.Client(project=self.project_id)
                for ds in source_tables:
                    all_columns = set()
                    for bucket_name in ("eastside-lakehouse", CONFIG_BUCKET):
                        try:
                            blobs = list(gcs_client.bucket(bucket_name).list_blobs(
                                prefix=f"landing/{ds}/", max_results=20))
                            for blob in blobs:
                                if not blob.size or blob.size == 0 or blob.name.endswith("/"):
                                    continue
                                try:
                                    content = blob.download_as_text()
                                    if blob.name.endswith(".csv"):
                                        reader = _csv.DictReader(_StringIO(content))
                                        row = next(reader, None)
                                        if row:
                                            all_columns.update(row.keys())
                                    else:
                                        import json as _json
                                        record = _json.loads(content.strip().split("\n")[0])
                                        all_columns.update(record.keys())
                                except Exception:
                                    continue
                            if all_columns:
                                source_schemas[ds] = sorted(all_columns)
                                break
                        except Exception:
                            continue
            except Exception:
                pass

        schema_context = ""
        if source_schemas:
            schema_context = "\nSource dataset schemas (use these exact column names for joins and SELECT):\n"
            for ds, cols in source_schemas.items():
                schema_context += f"  {ds}: {', '.join(cols)}\n"

            # Map each dimension to its source table so LLM knows exactly where each column comes from
            dim_source_map = {}
            for dim in dimensions:
                for ds, cols in source_schemas.items():
                    if str(dim) in cols:
                        dim_source_map.setdefault(str(dim), [])
                        dim_source_map[str(dim)].append(ds)
            if dim_source_map:
                schema_context += "\nDimension to source table mapping (every dimension MUST appear in SELECT and GROUP BY):\n"
                for dim, sources in dim_source_map.items():
                    schema_context += f"  {dim} → found in: {', '.join(sources)}\n"
            # Flag dimensions not found in any schema
            missing_from_schema = [d for d in dimensions if str(d) not in dim_source_map]
            if missing_from_schema:
                schema_context += f"\nDimensions not found in landing schemas (may be derived): {missing_from_schema}\n"

        # Use source tables from spec if available, otherwise fall back to discovered tables
        if source_tables:
            tables_desc = ", ".join(str(s) for s in source_tables)

        system = SYSTEM_PROMPT.format(available_tables=tables_desc)

        import sys
        print(f"[SQLGenerator] source_schemas keys: {list(source_schemas.keys())}", flush=True, file=sys.stderr)
        print(f"[SQLGenerator] dim_source_map: {dim_source_map if source_schemas else 'empty'}", flush=True, file=sys.stderr)
        print(f"[SQLGenerator] schema_context length: {len(schema_context)}", flush=True, file=sys.stderr)
        print(f"[SQLGenerator] missing_dims check will run on dimensions: {dimensions}", flush=True, file=sys.stderr)

        sql = self._generate_with_gemini(system, clean_spec + schema_context)
        if not sql or sql == "__QUOTA_EXCEEDED__":
            return {"sql": None, "error": "LLM unavailable"}

        # Strip accidental markdown fences
        sql = re.sub(r"^```[a-z]*\n?", "", sql.strip(), flags=re.MULTILINE)
        sql = re.sub(r"```$", "", sql.strip()).strip()

        # Validate all dimensions are in SELECT as standalone columns
        def _dim_in_select(dim, sql):
            return bool(re.search(
                rf'(?:,|SELECT)\s*\n?\s*[\w.]*{re.escape(str(dim))}(?:\s+AS\s+\w+)?\s*[,\n]',
                sql, re.IGNORECASE
            ))

        missing_dims = [d for d in dimensions if not _dim_in_select(str(d), sql)]
        if missing_dims:
            fix_prompt = (
                f"This SQL is missing these dimensions as standalone SELECT columns: {missing_dims}.\n"
                f"Every dimension must appear as its own SELECT column AND in GROUP BY.\n"
                f"Use the dimension-to-source mapping below to find the correct table and column.\n"
                f"{schema_context}\n"
                f"Return ONLY the complete corrected SQL, no explanation, no markdown.\n\n{sql}"
            )
            fixed = self._generate_with_gemini(system, fix_prompt)
            if fixed and fixed != "__QUOTA_EXCEEDED__":
                fixed = re.sub(r"^```[a-z]*\n?", "", fixed.strip(), flags=re.MULTILINE)
                fixed = re.sub(r"```$", "", fixed.strip()).strip()
                sql = fixed

        table_name = product_name or self._extract_table_name(sql)
        gcs_path = self._push_to_gcs_eastside(table_name, sql)
        return {"sql": sql, "table_name": table_name, "gcs_path": gcs_path}

    def _push_to_gcs_eastside(self, table_name: str, sql: str) -> str | None:
        """Push SQL to EastSide GCS bucket."""
        if not GCS_AVAILABLE:
            return None
        blob_name = f"config/consumption/{table_name}.sql"
        try:
            client = storage.Client(project=self.project_id)
            bucket = client.bucket("eastside-lakehouse")
            bucket.blob(blob_name).upload_from_string(sql, content_type="text/plain")
            path = f"gs://eastside-lakehouse/{blob_name}"
            print(f"[SQLGenerator] Pushed to: {path}")
            return path
        except Exception as e:
            print(f"[SQLGenerator] Failed to push to EastSide GCS: {e}")
            return None

    def _get_available_tables(self) -> list[str]:
        """Get list of tables available in silver layer (EastSide bucket first)."""
        if GCS_AVAILABLE:
            for bucket_name, prefix in [
                ("eastside-lakehouse", "config/tables/"),
                (CONFIG_BUCKET, "framework/config/tables/"),
            ]:
                try:
                    client = storage.Client(project=self.project_id)
                    blobs = list(client.bucket(bucket_name).list_blobs(prefix=prefix))
                    tables = [b.name.split("/")[-1].replace(".yaml", "") for b in blobs if b.name.endswith(".yaml")]
                    if tables:
                        return tables
                except Exception:
                    pass
        return ["customer_profiles", "pos_transactions", "online_orders", "returns_exchanges",
                "inventory_movements", "loyalty_members", "staff", "products"]

    def _extract_table_name(self, sql: str) -> str:
        """Extract target table name from SQL."""
        import re
        # Match CREATE OR REPLACE TABLE `dataset.table` or dataset.table
        m = re.search(r'CREATE\s+OR\s+REPLACE\s+TABLE\s+`?[\w-]+\.([\w]+)`?', sql, re.IGNORECASE)
        if m:
            return m.group(1)
        # Fallback: look for known dataset prefixes
        for part in sql.split("`"):
            for prefix in ("eastside_dataproduct.", "lakehouse_dataproduct."):
                if prefix in part:
                    return part.split(".")[-1]
        return "unnamed_data_product"

    def _push_to_gcs(self, table_name: str, sql: str) -> Optional[str]:
        """Push SQL to GCS for pipeline consumption."""
        if not GCS_AVAILABLE:
            return None

        gcs_path = f"gs://{CONFIG_BUCKET}/framework/config/consumption/{table_name}.sql"
        blob_name = f"framework/config/consumption/{table_name}.sql"

        try:
            client = storage.Client(project=self.project_id)
            bucket = client.bucket(CONFIG_BUCKET)
            blob = bucket.blob(blob_name)
            blob.upload_from_string(sql, content_type="text/plain")
            print(f"[SQLGenerator] Pushed to: {gcs_path}")
            return gcs_path
        except Exception as e:
            print(f"[SQLGenerator] Failed to push to GCS: {e}")
            return None
