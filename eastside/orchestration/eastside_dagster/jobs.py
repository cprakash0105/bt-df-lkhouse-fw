from dagster import define_asset_job, AssetSelection

# Full pipeline: bronze → silver → gold (all tables)
eastside_pipeline_job = define_asset_job(
    name="eastside_pipeline_job",
    selection=AssetSelection.groups("eastside"),
    description="Full pipeline: bronze → silver → gold for all tables.",
    tags={"pipeline": "eastside", "scope": "full"},
)

# Per-layer jobs (for independent execution and sensor triggers)
bronze_job = define_asset_job(
    name="bronze_job",
    selection=AssetSelection.assets("bronze_asset"),
    description="Bronze only: ingest landing files into Iceberg. Triggered by landing_sensor or manually.",
    tags={"pipeline": "eastside", "layer": "bronze"},
)

silver_job = define_asset_job(
    name="silver_job",
    selection=AssetSelection.assets("silver_asset"),
    description="Silver only: curate bronze into silver with DQ, dedup, SCD2.",
    tags={"pipeline": "eastside", "layer": "silver"},
)

gold_job = define_asset_job(
    name="gold_job",
    selection=AssetSelection.assets("gold_asset"),
    description="Gold only: publish silver to BigQuery data products.",
    tags={"pipeline": "eastside", "layer": "gold"},
)
