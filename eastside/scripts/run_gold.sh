#!/bin/bash
# EastSide CDH 2.0 — Run Gold Engine on Dataproc Serverless
# Usage: bash eastside/scripts/run_gold.sh bt-df-lkhouse europe-west2 [all|table_name]

PROJECT=${1:-bt-df-lkhouse}
REGION=${2:-europe-west2}
TARGET=${3:-all}
BUCKET="eastside-lakehouse"
CONFIG="gs://${BUCKET}/config/pipeline.yaml"

echo "============================================================"
echo "  EastSide Gold — Dataproc Serverless"
echo "============================================================"
echo "  Project: ${PROJECT}"
echo "  Region:  ${REGION}"
echo "  Target:  ${TARGET}"
echo "  Config:  ${CONFIG}"
echo "============================================================"

if [ "$TARGET" == "all" ]; then
    TABLE_ARG="--all"
else
    TABLE_ARG="--table ${TARGET}"
fi

gcloud dataproc batches submit pyspark \
    gs://${BUCKET}/engine/gold.py \
    --project=${PROJECT} \
    --region=${REGION} \
    --batch="eastside-gold-$(date +%Y%m%d-%H%M%S)" \
    --deps-bucket=gs://${BUCKET}/deps \
    --py-files=gs://${BUCKET}/engine/base.py \
    --jars=gs://spark-lib/bigquery/spark-bigquery-with-dependencies_2.12-0.36.1.jar \
    --properties="spark.sql.catalog.eastside=org.apache.iceberg.spark.SparkCatalog,spark.sql.catalog.eastside.type=rest,spark.sql.catalog.eastside.uri=https://biglake.googleapis.com/v1,spark.sql.catalog.eastside.warehouse=gs://${BUCKET},spark.sql.catalog.eastside.gcp_project=${PROJECT},spark.sql.catalog.eastside.gcp_location=${REGION}" \
    -- \
    --config ${CONFIG} \
    ${TABLE_ARG} \
    --project ${PROJECT}

echo ""
echo "Done. Check BigQuery dataset: ${PROJECT}.eastside_dataproduct"
