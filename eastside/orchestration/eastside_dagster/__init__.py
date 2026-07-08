from dagster import Definitions, ScheduleDefinition, DefaultScheduleStatus, RunConfig
from .assets import bronze_asset, silver_asset, gold_asset, TableConfig
from .jobs import eastside_pipeline_job
from .resources import dataproc_resource

daily_schedule = ScheduleDefinition(
    job=eastside_pipeline_job,
    cron_schedule="0 6 * * *",  # 06:00 UTC = 11:30 IST daily
    default_status=DefaultScheduleStatus.RUNNING,
    run_config=RunConfig(
        ops={
            "bronze_asset": TableConfig(table="all"),
            "silver_asset": TableConfig(table="all"),
            "gold_asset": TableConfig(table="all"),
        }
    ),
)

defs = Definitions(
    assets=[bronze_asset, silver_asset, gold_asset],
    jobs=[eastside_pipeline_job],
    schedules=[daily_schedule],
    resources={"dataproc": dataproc_resource},
)
