#!/bin/bash
# EastSide CDH 2.0 — Run Bronze Engine on Dataproc Serverless
# Usage: bash eastside/scripts/run_bronze.sh bt-df-lkhouse europe-west2 [all|table_name] [v1]

PROJECT=${1:-bt-df-lkhouse}
REGION=${2:-europe-west2}
TARGET=${3:-all}
VERSION=${4:-v1}
BUCKET="eastside-lakehouse"
CONFIG="gs://${BUCKET}/config/pipeline.yaml"

echo "============================================================"
echo "  EastSide Bronze — Dataproc Serverless"
echo "============================================================"
echo "  Project: ${PROJECT}"
echo "  Region:  ${REGION}"
echo "  Target:  ${TARGET}"
echo "  Version: ${VERSION}"
echo "  Config:  ${CONFIG}"
echo "============================================================"

# Upload engine to GCS
echo "Uploading engine..."
gcloud storage cp eastside/engine/*.py gs://${BUCKET}/engine/
gcloud storage cp eastside/config/pipeline.yaml gs://${BUCKET}/config/pipeline.yaml
gcloud storage cp eastside/config/tables/*.yaml gs://${BUCKET}/config/tables/

# Build args
if [ "$TARGET" == "all" ]; then
    TABLE_ARG="--all"
else
    TABLE_ARG="--table ${TARGET}"
fi

# Submit Dataproc Serverless batch
gcloud dataproc batches submit pyspark \
    gs://${BUCKET}/engine/bronze.py \
    --project=${PROJECT} \
    --region=${REGION} \
    --batch="eastside-bronze-$(date +%Y%m%d-%H%M%S)" \
    --deps-bucket=gs://${BUCKET}/deps \
    --py-files=gs://${BUCKET}/engine/base.py \
    --properties="spark.sql.catalog.eastside=org.apache.iceberg.spark.SparkCatalog,spark.sql.catalog.eastside.type=rest,spark.sql.catalog.eastside.uri=https://biglake.googleapis.com/v1,spark.sql.catalog.eastside.warehouse=gs://${BUCKET},spark.sql.catalog.eastside.gcp_project=${PROJECT},spark.sql.catalog.eastside.gcp_location=${REGION}" \
    -- \
    --config ${CONFIG} \
    ${TABLE_ARG} \
    --version ${VERSION} \
    --project ${PROJECT}

echo ""
echo "Done. Check logs: gs://${BUCKET}/logs/bronze/"
