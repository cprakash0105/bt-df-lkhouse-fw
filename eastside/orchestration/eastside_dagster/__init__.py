from dagster import Definitions, ScheduleDefinition
from .assets import bronze_asset, silver_asset, gold_asset
from .jobs import eastside_pipeline_job
from .resources import dataproc_resource

daily_schedule = ScheduleDefinition(
    job=eastside_pipeline_job,
    cron_schedule="0 6 * * *",  # 06:00 UTC daily
    default_status="RUNNING",
)

defs = Definitions(
    assets=[bronze_asset, silver_asset, gold_asset],
    jobs=[eastside_pipeline_job],
    schedules=[daily_schedule],
    resources={"dataproc": dataproc_resource},
)
