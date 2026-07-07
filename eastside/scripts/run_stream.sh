#!/bin/bash
# EastSide CDH 2.0 — Run Streaming Engine on Dataproc (lakehouse-cluster)
# Usage: bash eastside/scripts/run_stream.sh [table_name] [trigger_interval] [kafka_bootstrap]

PROJECT="bt-df-lkhouse"
REGION="europe-west2"
CLUSTER="lakehouse-cluster"
BUCKET="eastside-lakehouse"
TABLE=${1:-pos_transactions}
TRIGGER=${2:-"15 minutes"}
KAFKA_BOOTSTRAP=${3:-"localhost:9092"}
CONFIG="gs://${BUCKET}/config/pipeline.yaml"

echo "============================================================"
echo "  EastSide Streaming — lakehouse-cluster"
echo "  Table: ${TABLE} | Trigger: ${TRIGGER}"
echo "============================================================"

gcloud dataproc jobs submit pyspark gs://${BUCKET}/engine/stream.py \
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
spark.sql.catalog.eastside.warehouse=gs://${BUCKET},\
spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions,\
spark.jars.packages=org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0" \
    -- \
    --config ${CONFIG} \
    --table ${TABLE} \
    --trigger-interval "${TRIGGER}" \
    --kafka-bootstrap ${KAFKA_BOOTSTRAP} \
    --project ${PROJECT}
