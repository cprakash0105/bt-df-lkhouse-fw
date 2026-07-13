import time
from typing import ClassVar
from dagster import ConfigurableResource, get_dagster_logger
from google.cloud import dataproc_v1


class DataprocResource(ConfigurableResource):
    project: str = "bt-df-lkhouse"
    region: str = "europe-west2"
    bucket: str = "eastside-lakehouse"

    PY_FILES: ClassVar[list] = [
        "gs://eastside-lakehouse/engine/base.py",
        "gs://eastside-lakehouse/engine/schema_evolver.py",
    ]
    JARS: ClassVar[list] = [
        "gs://bt-df-lkhouse-lakehouse/spark/iceberg-spark-runtime.jar",
        "gs://bt-df-lkhouse-lakehouse/spark/biglake-catalog.jar",
    ]
    SPARK_PROPS: ClassVar[dict] = {
        "spark.sql.catalog.lkhouse_eastside": "org.apache.iceberg.spark.SparkCatalog",
        "spark.sql.catalog.lkhouse_eastside.catalog-impl": "org.apache.iceberg.gcp.biglake.BigLakeCatalog",
        "spark.sql.catalog.lkhouse_eastside.gcp_project": "bt-df-lkhouse",
        "spark.sql.catalog.lkhouse_eastside.gcp_location": "europe-west2",
        "spark.sql.catalog.lkhouse_eastside.blms_catalog": "lkhouse_eastside",
        "spark.sql.catalog.lkhouse_eastside.warehouse": "gs://eastside-lakehouse",
        "spark.sql.extensions": "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
    }

    def submit_and_wait(self, stage: str, table: str, version: str = None,
                        timeout: int = 900) -> str:
        """Submit a PySpark job to Dataproc and wait for completion.

        Args:
            stage: Pipeline stage (bronze, silver, gold, reconcile)
            table: Table name to process
            version: Landing version (required for bronze, ignored for others)
            timeout: Max wait time in seconds (default 15 min)

        Returns:
            Job ID on success

        Raises:
            RuntimeError on job failure or timeout
        """
        logger = get_dagster_logger()
        client = dataproc_v1.JobControllerClient(
            client_options={"api_endpoint": f"{self.region}-dataproc.googleapis.com:443"}
        )

        job_id = f"eastside-{stage}-{table}-{int(time.time()) % 100000}"

        args = [
            "--config", f"gs://{self.bucket}/config/pipeline.yaml",
            "--table", table,
            "--project", self.project,
        ]
        if stage == "bronze":
            if not version:
                raise ValueError("version is required for bronze stage")
            args += ["--version", version]

        job = {
            "placement": {"cluster_name": "lakehouse-cluster"},
            "reference": {"job_id": job_id},
            "pyspark_job": {
                "main_python_file_uri": f"gs://{self.bucket}/engine/{stage}.py",
                "python_file_uris": self.PY_FILES,
                "jar_file_uris": list(self.JARS),
                "args": args,
                "properties": self.SPARK_PROPS,
            },
        }

        logger.info(f"Submitting {stage} job: {job_id} (table={table}, version={version})")
        client.submit_job(project_id=self.project, region=self.region, job=job)

        # Poll for completion
        start = time.time()
        while time.time() - start < timeout:
            result = client.get_job(project_id=self.project, region=self.region, job_id=job_id)
            state = result.status.state.name
            if state == "DONE":
                logger.info(f"Job {job_id} completed successfully")
                return job_id
            if state in ("ERROR", "CANCELLED"):
                error_msg = result.status.details or "No details"
                raise RuntimeError(f"Job {job_id} {state}: {error_msg}")
            time.sleep(10)

        raise RuntimeError(f"Job {job_id} timed out after {timeout}s")


dataproc_resource = DataprocResource()
