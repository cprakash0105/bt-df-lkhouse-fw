import time
from typing import ClassVar
from dagster import ConfigurableResource
from google.cloud import dataproc_v1


class DataprocResource(ConfigurableResource):
    project: str = "bt-df-lkhouse"
    region: str = "europe-west2"
    cluster: str = "lakehouse-cluster"
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
        "spark.sql.catalog.lkhouse_eastside.gcp_location": "us-east1",
        "spark.sql.catalog.lkhouse_eastside.blms_catalog": "lkhouse_eastside",
        "spark.sql.catalog.lkhouse_eastside.warehouse": "gs://eastside-lakehouse",
        "spark.sql.extensions": "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
    }

    def submit_and_wait(self, stage: str, table: str, extra_jars: list = None) -> str:
        client = dataproc_v1.JobControllerClient(
            client_options={"api_endpoint": f"{self.region}-dataproc.googleapis.com:443"}
        )
        job_id = f"eastside-{stage}-{table}-{int(time.time()) % 100000}"
        jars = list(self.JARS) + (extra_jars or [])

        args = ["--config", f"gs://{self.bucket}/config/pipeline.yaml",
                "--table", table, "--project", self.project]
        if stage == "bronze":
            args += ["--version", "v1"]

        job = {
            "placement": {"cluster_name": self.cluster},
            "reference": {"job_id": job_id},
            "pyspark_job": {
                "main_python_file_uri": f"gs://{self.bucket}/engine/{stage}.py",
                "python_file_uris": self.PY_FILES,
                "jar_file_uris": jars,
                "args": args,
                "properties": self.SPARK_PROPS,
            },
        }

        client.submit_job(project_id=self.project, region=self.region, job=job)

        # Wait for completion
        timeout = 600
        start = time.time()
        while time.time() - start < timeout:
            result = client.get_job(project_id=self.project, region=self.region, job_id=job_id)
            state = result.status.state.name
            if state == "DONE":
                return job_id
            if state in ("ERROR", "CANCELLED"):
                raise RuntimeError(f"Job {job_id} {state}: {result.status.details}")
            time.sleep(10)
        raise RuntimeError(f"Job {job_id} timed out after {timeout}s")


dataproc_resource = DataprocResource()
