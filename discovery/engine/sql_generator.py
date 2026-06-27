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


SYSTEM_PROMPT = """You are a SQL engineer for a BigQuery lakehouse. Generate a CREATE OR REPLACE TABLE statement for a Data Product.

Context:
- Project ID: {project_id}
- Source dataset (CCN layer): `{project_id}.lakehouse_ccn`
- Target dataset (Data Product): `{project_id}.lakehouse_dataproduct`
- All source tables are Iceberg tables exposed via BigQuery

Available source tables in lakehouse_ccn:
{available_tables}

Rules:
1. Output ONLY the SQL statement, no explanation
2. Always use `${{PROJECT_ID}}` placeholder for the project ID (not the actual ID)
3. Target table goes in `${{PROJECT_ID}}.lakehouse_dataproduct.<table_name>`
4. Source tables from `${{PROJECT_ID}}.lakehouse_ccn.<table_name>`
5. Use explicit column lists (no SELECT *)
6. Add appropriate JOINs based on common keys (customer_id, order_id, etc.)
7. Add a header comment with: table name, description, source tables
8. If business logic is described (CASE statements, aggregations), implement it exactly

Example output:
-- loan_eligibility_360.sql
-- Data Product: Loan Eligibility 360 view
-- Sources: customers, cibil_bureau_feed
CREATE OR REPLACE TABLE `${{PROJECT_ID}}.lakehouse_dataproduct.loan_eligibility_360` AS
SELECT ...
"""


class SQLGenerator:
    """Generates consumption SQL from natural language using Gemini."""

    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id or PROJECT_ID

    def generate(self, requirement: str, available_tables: list[str] = None) -> Optional[str]:
        """Generate SQL from a natural language requirement."""
        if available_tables is None:
            available_tables = self._get_available_tables()

        tables_desc = "\n".join([f"  - {t}" for t in available_tables])
        prompt = SYSTEM_PROMPT.format(
            project_id=self.project_id,
            available_tables=tables_desc,
        )

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
        """Use Vertex AI Gemini to generate SQL."""
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel

            vertexai.init(project=self.project_id, location=LOCATION)
            model = GenerativeModel("gemini-2.0-flash")

            response = model.generate_content(
                [system_prompt, f"Requirement: {requirement}"],
                generation_config={"temperature": 0.1, "max_output_tokens": 4096},
            )

            sql = response.text.strip()
            # Remove markdown code fences
            if sql.startswith("```"):
                lines = sql.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                sql = "\n".join(lines)

            return sql

        except Exception as e:
            print(f"[SQLGenerator] Gemini failed: {e}")
            return None

    def _get_available_tables(self) -> list[str]:
        """Get list of tables available in CCN layer."""
        # Try reading from GCS config
        if GCS_AVAILABLE:
            try:
                client = storage.Client(project=self.project_id)
                bucket = client.bucket(CONFIG_BUCKET)
                blobs = list(bucket.list_blobs(prefix="framework/config/tables/"))
                tables = []
                for blob in blobs:
                    if blob.name.endswith(".yaml"):
                        name = blob.name.split("/")[-1].replace(".yaml", "")
                        tables.append(name)
                if tables:
                    return tables
            except Exception:
                pass

        # Fallback: known tables
        return [
            "customers",
            "orders",
            "payments",
            "products",
            "clickstream",
            "cibil_bureau_feed",
            "pipeline_audit",
        ]

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
