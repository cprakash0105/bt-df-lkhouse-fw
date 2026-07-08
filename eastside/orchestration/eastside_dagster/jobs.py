from dagster import define_asset_job, AssetSelection

eastside_pipeline_job = define_asset_job(
    name="eastside_pipeline_job",
    selection=AssetSelection.groups("eastside"),
)
