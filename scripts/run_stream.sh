#!/bin/bash
# bt-df-lkhouse-fw: Start Streaming Job (Kafka → CCN Iceberg)
# Runs as a long-lived Dataproc Serverless batch
set -e

export PROJECT_ID=${1:-bt-df-lkhouse}
export REGION=${2:-europe-west2}
export TABLE=${3:-clickstream}
export TRIGGER=${4:-"30 seconds"}
export BUCKET="${PROJECT_ID}-lakehouse"
export SA_EMAIL="schema-poc-spark@${PROJECT_ID}.iam.gserviceaccount.com"
export SUBNET="projects/${PROJECT_ID}/regions/${REGION}/subnetworks/schema-poc-network"

ICEBERG_PROPS="^::^spark.jars.packages=org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.9.1,org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1::spark.sql.catalog.lakehouse=org.apache.iceberg.spark.SparkCatalog::spark.sql.catalog.lakehouse.catalog-impl=org.apache.iceberg.gcp.biglake.BigLakeCatalog::spark.sql.catalog.lakehouse.gcp_project=${PROJECT_ID}::spark.sql.catalog.lakehouse.gcp_location=${REGION}::spark.sql.catalog.lakehouse.blms_catalog=lakehouse::spark.sql.catalog.lakehouse.warehouse=gs://${BUCKET}"

CONFIG_PATH="gs://${BUCKET}/framework/config/pipeline.yaml"
KAFKA_CONFIG_PATH="gs://${BUCKET}/framework/confluent/kafka.yaml"
PY_FILES="gs://${BUCKET}/framework/bt_df_lkhouse_fw.zip"

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  bt-df-lkhouse-fw — Streaming Job                         ║"
echo "║  Table: ${TABLE}                                           ║"
echo "║  Kafka → CCN Iceberg (Spark Structured Streaming)          ║"
echo "║  Trigger: ${TRIGGER}                                       ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Package and upload
echo "=== Packaging framework → GCS ==="
cd "$(dirname "$0")/.."
zip -r /tmp/bt_df_lkhouse_fw.zip bt_df_lkhouse_fw/
gsutil -q cp /tmp/bt_df_lkhouse_fw.zip gs://${BUCKET}/framework/bt_df_lkhouse_fw.zip
gsutil -q -m cp -r bt_df_lkhouse_fw/config/* gs://${BUCKET}/framework/config/
gsutil -q -m cp -r bt_df_lkhouse_fw/engine/* gs://${BUCKET}/framework/engine/

# Upload Kafka config (must exist locally at confluent/kafka.yaml)
if [ -f confluent/kafka.yaml ]; then
  gsutil -q cp confluent/kafka.yaml gs://${BUCKET}/framework/confluent/kafka.yaml
  echo "  ✅ Kafka config uploaded"
else
  echo "  ⚠️  confluent/kafka.yaml not found — make sure it's already on GCS"
fi

echo ""
echo "=== Submitting streaming batch ==="
gcloud dataproc batches submit pyspark \
  gs://${BUCKET}/framework/engine/stream.py \
  --project=${PROJECT_ID} --region=${REGION} \
  --service-account=${SA_EMAIL} --subnet=${SUBNET} \
  --version=2.2 \
  --jars=gs://spark-lib/biglake/biglake-catalog-iceberg1.9.1-0.1.3-with-dependencies.jar \
  --deps-bucket=gs://${BUCKET} \
  --py-files=${PY_FILES} \
  --properties="${ICEBERG_PROPS}::spark.executor.instances=2::spark.dynamicAllocation.enabled=false" \
  -- --config=${CONFIG_PATH} \
     --kafka-config=${KAFKA_CONFIG_PATH} \
     --table=${TABLE} \
     --trigger-interval="${TRIGGER}" \
     --project=${PROJECT_ID}

echo ""
echo "=== Streaming job submitted ==="
echo "Monitor: https://console.cloud.google.com/dataproc/batches?project=${PROJECT_ID}"
echo "Stop:    gcloud dataproc batches cancel <batch-id> --project=${PROJECT_ID} --region=${REGION}"
