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


SYSTEM_PROMPT = """You are a BigQuery SQL expert for the EastSide Apparel data platform.

Platform conventions:
- Silver tables: `silver.<table>` (Apache Iceberg via BigLake Metastore, catalog: lkhouse_eastside)
  All silver tables have SCD2 columns: valid_from, valid_to, is_current
  Always filter: WHERE is_current = true
- Output target: `eastside_dataproduct.<name>` (BigQuery)
- GCS bucket: eastside-lakehouse
- Dedup each source on its primary key before joining (keep latest by event date)
- Do NOT expose raw PII fields (first_name, last_name, email, phone, date_of_birth) in output
- Use CREATE OR REPLACE TABLE syntax
- Add a _gold_published_at = CURRENT_TIMESTAMP() column to every output
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
        return get_llm().generate(system=system_prompt, user=requirement, max_tokens=1024)

    def generate_dataproduct(self, spec: str) -> dict:
        """Generate a full data product: SQL + metadata from a free-text spec.
        Returns {sql, table_name, gcs_path}."""
        available_tables = self._get_available_tables()
        tables_desc = ", ".join(available_tables)
        system = SYSTEM_PROMPT.format(available_tables=tables_desc)
        sql = self._generate_with_gemini(system, spec)
        if not sql or sql == "__QUOTA_EXCEEDED__":
            return {"sql": None, "error": "LLM unavailable"}
        # Strip accidental markdown fences
        sql = sql.strip().lstrip("```sql").lstrip("```").rstrip("```").strip()
        table_name = self._extract_table_name(sql)
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
        # Look for lakehouse_dataproduct.<name>
        for part in sql.split("`"):
            if "lakehouse_dataproduct." in part:
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
