from dagster import Definitions, ScheduleDefinition, DefaultScheduleStatus, RunConfig
from .assets import bronze_asset, silver_asset, gold_asset, BronzeConfig, SilverConfig, GoldConfig
from .jobs import eastside_pipeline_job, bronze_job, silver_job, gold_job
from .sensors import landing_sensor
from .resources import dataproc_resource


# Daily full pipeline schedule (06:00 UTC)
# Processes all unprocessed versions for all tables
daily_full_pipeline = ScheduleDefinition(
    job=eastside_pipeline_job,
    cron_schedule="0 6 * * *",
    default_status=DefaultScheduleStatus.STOPPED,  # Enable when ready for prod
    run_config=RunConfig(
        ops={
            "bronze_asset": BronzeConfig(table="all", version="auto"),
            "silver_asset": SilverConfig(table="all"),
            "gold_asset": GoldConfig(table="all"),
        }
    ),
    description="Daily 06:00 UTC — full pipeline for all tables (auto-detect versions).",
    tags={"trigger": "schedule", "cadence": "daily"},
)


defs = Definitions(
    assets=[bronze_asset, silver_asset, gold_asset],
    jobs=[eastside_pipeline_job, bronze_job, silver_job, gold_job],
    schedules=[daily_full_pipeline],
    sensors=[landing_sensor],
    resources={"dataproc": dataproc_resource},
)
