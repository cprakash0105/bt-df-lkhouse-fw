#!/bin/bash
# EastSide CDH 2.0 — Run Reconciliation on Dataproc (lakehouse-cluster)
# Usage: bash eastside/scripts/run_reconcile.sh [all|table_name] [incremental|full]

PROJECT="bt-df-lkhouse"
REGION="europe-west2"
CLUSTER="lakehouse-cluster"
BUCKET="eastside-lakehouse"
TARGET=${1:-all}
MODE=${2:-incremental}
CONFIG="gs://${BUCKET}/config/pipeline.yaml"

echo "============================================================"
echo "  EastSide Reconciliation — lakehouse-cluster"
echo "  Target: ${TARGET} | Mode: ${MODE}"
echo "============================================================"

if [ "$TARGET" == "all" ]; then
    TABLE_ARG="--all"
else
    TABLE_ARG="--table ${TARGET}"
fi

gcloud dataproc jobs submit pyspark gs://${BUCKET}/engine/reconcile.py \
    --cluster=${CLUSTER} \
    --project=${PROJECT} \
    --region=${REGION} \
    --py-files=gs://${BUCKET}/engine/base.py,gs://${BUCKET}/engine/schema_evolver.py \
    --jars=gs://bt-df-lkhouse-lakehouse/spark/iceberg-spark-runtime.jar,gs://bt-df-lkhouse-lakehouse/spark/biglake-catalog.jar \
    --properties="\
spark.sql.catalog.eastside=org.apache.iceberg.spark.SparkCatalog,\
spark.sql.catalog.eastside.catalog-impl=org.apache.iceberg.gcp.biglake.BigLakeCatalog,\
spark.sql.catalog.eastside.gcp_project=${PROJECT},\
spark.sql.catalog.eastside.gcp_location=${REGION},\
spark.sql.catalog.eastside.blms_catalog=eastside,\
spark.sql.catalog.eastside.warehouse=gs://${BUCKET}" \
    -- \
    --config ${CONFIG} \
    ${TABLE_ARG} \
    --mode ${MODE} \
    --project ${PROJECT}
