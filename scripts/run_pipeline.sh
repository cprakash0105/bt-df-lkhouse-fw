#!/bin/bash
# Run Lakehouse Pipeline: Landing → Raw → Curated → Consumption
set -e

export PROJECT_ID=${1:-schema-evolution-poc}
export REGION=${2:-europe-west2}
export STAGE=${3:-all}  # landing_to_raw, raw_to_curated, curated_to_consumption, or all
export BUCKET="${PROJECT_ID}-lakehouse"
export SA_EMAIL="schema-poc-spark@${PROJECT_ID}.iam.gserviceaccount.com"
export SUBNET="projects/${PROJECT_ID}/regions/${REGION}/subnetworks/schema-poc-network"

ICEBERG_PROPS="^::^spark.jars.packages=org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.9.1::spark.sql.catalog.lakehouse=org.apache.iceberg.spark.SparkCatalog::spark.sql.catalog.lakehouse.catalog-impl=org.apache.iceberg.gcp.biglake.BigLakeCatalog::spark.sql.catalog.lakehouse.gcp_project=${PROJECT_ID}::spark.sql.catalog.lakehouse.gcp_location=${REGION}::spark.sql.catalog.lakehouse.blms_catalog=lakehouse::spark.sql.catalog.lakehouse.warehouse=gs://${BUCKET}"

echo "=== Uploading Spark jobs ==="
gsutil -q cp spark/*.py gs://${BUCKET}/spark/

if [[ "$STAGE" == "all" || "$STAGE" == "landing_to_raw" ]]; then
  echo ""
  echo "=== Stage 1: Landing → Raw ==="
  gcloud dataproc batches submit pyspark \
    gs://${BUCKET}/spark/landing_to_raw.py \
    --project=${PROJECT_ID} --region=${REGION} \
    --service-account=${SA_EMAIL} --subnet=${SUBNET} \
    --version=2.2 \
    --jars=gs://spark-lib/biglake/biglake-catalog-iceberg1.9.1-0.1.3-with-dependencies.jar \
    --deps-bucket=gs://${BUCKET} \
    --properties="${ICEBERG_PROPS}" \
    -- --project=${PROJECT_ID}
fi

if [[ "$STAGE" == "all" || "$STAGE" == "raw_to_curated" ]]; then
  echo ""
  echo "=== Stage 2: Raw → Curated ==="
  gcloud dataproc batches submit pyspark \
    gs://${BUCKET}/spark/raw_to_curated.py \
    --project=${PROJECT_ID} --region=${REGION} \
    --service-account=${SA_EMAIL} --subnet=${SUBNET} \
    --version=2.2 \
    --jars=gs://spark-lib/biglake/biglake-catalog-iceberg1.9.1-0.1.3-with-dependencies.jar \
    --deps-bucket=gs://${BUCKET} \
    --properties="${ICEBERG_PROPS}" \
    -- --project=${PROJECT_ID}
fi

if [[ "$STAGE" == "all" || "$STAGE" == "curated_to_consumption" ]]; then
  echo ""
  echo "=== Stage 3: Curated → Consumption ==="
  gcloud dataproc batches submit pyspark \
    gs://${BUCKET}/spark/curated_to_consumption.py \
    --project=${PROJECT_ID} --region=${REGION} \
    --service-account=${SA_EMAIL} --subnet=${SUBNET} \
    --version=2.2 \
    --jars=gs://spark-lib/biglake/biglake-catalog-iceberg1.9.1-0.1.3-with-dependencies.jar \
    --deps-bucket=gs://${BUCKET} \
    --properties="${ICEBERG_PROPS}" \
    -- --project=${PROJECT_ID}
fi

echo ""
echo "=== Pipeline complete ==="
echo ""
echo "BigQuery datasets:"
echo "  lakehouse_raw.*          — raw ingested data"
echo "  lakehouse_curated.*      — cleansed, validated, deduped"
echo "  lakehouse_consumption.*  — customer_360 reporting table"
