#!/bin/bash
# bt-df-lkhouse-fw: Run Lakehouse Pipeline via Dataproc Serverless
# Landing → Reservoir → CCN → Data Product
set -e

export PROJECT_ID=${1:-bt-df-lkhouse}
export REGION=${2:-europe-west2}
export STAGE=${3:-all}  # ingest, curate, consume, or all
export VERSION=${4:-v1}
export BUCKET="${PROJECT_ID}-lakehouse"
export SA_EMAIL="schema-poc-spark@${PROJECT_ID}.iam.gserviceaccount.com"
export SUBNET="projects/${PROJECT_ID}/regions/${REGION}/subnetworks/schema-poc-network"

ICEBERG_PROPS="^::^spark.jars.packages=org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.9.1::spark.sql.catalog.lakehouse=org.apache.iceberg.spark.SparkCatalog::spark.sql.catalog.lakehouse.catalog-impl=org.apache.iceberg.gcp.biglake.BigLakeCatalog::spark.sql.catalog.lakehouse.gcp_project=${PROJECT_ID}::spark.sql.catalog.lakehouse.gcp_location=${REGION}::spark.sql.catalog.lakehouse.blms_catalog=lakehouse::spark.sql.catalog.lakehouse.warehouse=gs://${BUCKET}"

CONFIG_PATH="gs://${BUCKET}/framework/config/pipeline.yaml"

echo "=== bt-df-lkhouse-fw ==="
echo "Project: ${PROJECT_ID} | Region: ${REGION} | Version: ${VERSION}"
echo ""

echo "=== Uploading framework to GCS ==="
gsutil -q -m cp -r bt_df_lkhouse_fw/* gs://${BUCKET}/framework/

if [[ "$STAGE" == "all" || "$STAGE" == "ingest" ]]; then
  echo ""
  echo "=== Stage 1: Landing → Reservoir ==="
  gcloud dataproc batches submit pyspark \
    gs://${BUCKET}/framework/engine/ingest.py \
    --project=${PROJECT_ID} --region=${REGION} \
    --service-account=${SA_EMAIL} --subnet=${SUBNET} \
    --version=2.2 \
    --jars=gs://spark-lib/biglake/biglake-catalog-iceberg1.9.1-0.1.3-with-dependencies.jar \
    --deps-bucket=gs://${BUCKET} \
    --py-files=gs://${BUCKET}/framework/ \
    --properties="${ICEBERG_PROPS}" \
    -- --config=${CONFIG_PATH} --all --version=${VERSION}
fi

if [[ "$STAGE" == "all" || "$STAGE" == "curate" ]]; then
  echo ""
  echo "=== Stage 2: Reservoir → CCN ==="
  gcloud dataproc batches submit pyspark \
    gs://${BUCKET}/framework/engine/curate.py \
    --project=${PROJECT_ID} --region=${REGION} \
    --service-account=${SA_EMAIL} --subnet=${SUBNET} \
    --version=2.2 \
    --jars=gs://spark-lib/biglake/biglake-catalog-iceberg1.9.1-0.1.3-with-dependencies.jar \
    --deps-bucket=gs://${BUCKET} \
    --py-files=gs://${BUCKET}/framework/ \
    --properties="${ICEBERG_PROPS}" \
    -- --config=${CONFIG_PATH} --all
fi

if [[ "$STAGE" == "all" || "$STAGE" == "consume" ]]; then
  echo ""
  echo "=== Stage 3: CCN → Data Product ==="
  gcloud dataproc batches submit pyspark \
    gs://${BUCKET}/framework/engine/consume.py \
    --project=${PROJECT_ID} --region=${REGION} \
    --service-account=${SA_EMAIL} --subnet=${SUBNET} \
    --version=2.2 \
    --jars=gs://spark-lib/biglake/biglake-catalog-iceberg1.9.1-0.1.3-with-dependencies.jar \
    --deps-bucket=gs://${BUCKET} \
    --py-files=gs://${BUCKET}/framework/ \
    --properties="${ICEBERG_PROPS}" \
    -- --config=${CONFIG_PATH} --all
fi

echo ""
echo "=== Pipeline complete ==="
echo ""
echo "BigQuery:"
echo "  lakehouse_reservoir.*     — raw ingested data"
echo "  lakehouse_ccn.*           — cleansed, validated, deduped"
echo "  lakehouse_dataproduct.*   — customer_360"
