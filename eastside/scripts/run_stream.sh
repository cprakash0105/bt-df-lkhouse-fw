#!/bin/bash
# EastSide CDH 2.0 — Run Streaming Engine on Dataproc
# Usage: bash eastside/scripts/run_stream.sh bt-df-lkhouse europe-west2 pos_transactions

PROJECT=${1:-bt-df-lkhouse}
REGION=${2:-europe-west2}
TABLE=${3:-pos_transactions}
TRIGGER=${4:-"15 minutes"}
KAFKA_BOOTSTRAP=${5:-"localhost:9092"}
BUCKET="eastside-lakehouse"
CONFIG="gs://${BUCKET}/config/pipeline.yaml"

echo "============================================================"
echo "  EastSide Streaming — Dataproc"
echo "============================================================"
echo "  Project: ${PROJECT}"
echo "  Region:  ${REGION}"
echo "  Table:   ${TABLE}"
echo "  Trigger: ${TRIGGER}"
echo "  Kafka:   ${KAFKA_BOOTSTRAP}"
echo "============================================================"

gcloud dataproc batches submit pyspark \
    gs://${BUCKET}/engine/stream.py \
    --project=${PROJECT} \
    --region=${REGION} \
    --batch="eastside-stream-${TABLE}-$(date +%Y%m%d-%H%M%S)" \
    --deps-bucket=gs://${BUCKET}/deps \
    --py-files=gs://${BUCKET}/engine/base.py \
    --properties="spark.sql.catalog.eastside=org.apache.iceberg.spark.SparkCatalog,spark.sql.catalog.eastside.type=rest,spark.sql.catalog.eastside.uri=https://biglake.googleapis.com/v1,spark.sql.catalog.eastside.warehouse=gs://${BUCKET},spark.sql.catalog.eastside.gcp_project=${PROJECT},spark.sql.catalog.eastside.gcp_location=${REGION},spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions,spark.jars.packages=org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0" \
    -- \
    --config ${CONFIG} \
    --table ${TABLE} \
    --trigger-interval "${TRIGGER}" \
    --kafka-bootstrap ${KAFKA_BOOTSTRAP} \
    --project ${PROJECT}

echo ""
echo "Streaming job submitted. Monitor via Dataproc UI."
