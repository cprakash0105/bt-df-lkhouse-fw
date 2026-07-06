#!/bin/bash
# EastSide CDH 2.0 — Run Reconciliation on Dataproc Serverless
# Usage: bash eastside/scripts/run_reconcile.sh bt-df-lkhouse europe-west2 [all|table_name] [incremental|full]

PROJECT=${1:-bt-df-lkhouse}
REGION=${2:-europe-west2}
TARGET=${3:-all}
MODE=${4:-incremental}
BUCKET="eastside-lakehouse"
CONFIG="gs://${BUCKET}/config/pipeline.yaml"

echo "============================================================"
echo "  EastSide Reconciliation — Dataproc Serverless"
echo "============================================================"
echo "  Project: ${PROJECT}"
echo "  Region:  ${REGION}"
echo "  Target:  ${TARGET}"
echo "  Mode:    ${MODE}"
echo "============================================================"

if [ "$TARGET" == "all" ]; then
    TABLE_ARG="--all"
else
    TABLE_ARG="--table ${TARGET}"
fi

gcloud dataproc batches submit pyspark \
    gs://${BUCKET}/engine/reconcile.py \
    --project=${PROJECT} \
    --region=${REGION} \
    --batch="eastside-recon-$(date +%Y%m%d-%H%M%S)" \
    --deps-bucket=gs://${BUCKET}/deps \
    --py-files=gs://${BUCKET}/engine/base.py \
    --properties="spark.sql.catalog.eastside=org.apache.iceberg.spark.SparkCatalog,spark.sql.catalog.eastside.type=rest,spark.sql.catalog.eastside.uri=https://biglake.googleapis.com/v1,spark.sql.catalog.eastside.warehouse=gs://${BUCKET},spark.sql.catalog.eastside.gcp_project=${PROJECT},spark.sql.catalog.eastside.gcp_location=${REGION}" \
    -- \
    --config ${CONFIG} \
    ${TABLE_ARG} \
    --mode ${MODE} \
    --project ${PROJECT}

echo ""
echo "Done. Check: SELECT * FROM eastside.silver.reconciliation_log"
