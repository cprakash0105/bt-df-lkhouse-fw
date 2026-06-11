#!/bin/bash
# Submit Spark jobs to Dataproc Serverless: Landing → Bronze → Silver → Gold
set -e

export PROJECT_ID=${1:-schema-evolution-poc}
export REGION=${2:-europe-west2}
export STAGE=${3:-all}  # landing_to_bronze, bronze_to_silver, silver_to_gold, or all
export BUCKET="${PROJECT_ID}-lakehouse"
export SA_EMAIL="schema-poc-spark@${PROJECT_ID}.iam.gserviceaccount.com"
export SUBNET="projects/${PROJECT_ID}/regions/${REGION}/subnetworks/schema-poc-network"

# Common Spark properties for Iceberg + BLMS
ICEBERG_PROPS="^::^spark.jars.packages=org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.9.1::spark.sql.catalog.lakehouse=org.apache.iceberg.spark.SparkCatalog::spark.sql.catalog.lakehouse.catalog-impl=org.apache.iceberg.gcp.biglake.BigLakeCatalog::spark.sql.catalog.lakehouse.gcp_project=${PROJECT_ID}::spark.sql.catalog.lakehouse.gcp_location=${REGION}::spark.sql.catalog.lakehouse.blms_catalog=schema_poc::spark.sql.catalog.lakehouse.warehouse=gs://${BUCKET}"

echo "=== Uploading Spark jobs to GCS ==="
gsutil -q cp spark/*.py gs://${BUCKET}/spark/

# Stage 1: Landing → Bronze
if [[ "$STAGE" == "all" || "$STAGE" == "landing_to_bronze" ]]; then
  echo ""
  echo "=== Stage 1: Landing → Bronze ==="
  gcloud dataproc batches submit pyspark \
    gs://${BUCKET}/spark/landing_to_bronze.py \
    --project=${PROJECT_ID} \
    --region=${REGION} \
    --service-account=${SA_EMAIL} \
    --subnet=${SUBNET} \
    --version=2.2 \
    --deps-bucket=gs://${BUCKET} \
    -- --project=${PROJECT_ID} --region=${REGION}
fi

# Stage 2: Bronze → Silver (requires Iceberg + BLMS)
if [[ "$STAGE" == "all" || "$STAGE" == "bronze_to_silver" ]]; then
  echo ""
  echo "=== Stage 2: Bronze → Silver ==="
  gcloud dataproc batches submit pyspark \
    gs://${BUCKET}/spark/bronze_to_silver.py \
    --project=${PROJECT_ID} \
    --region=${REGION} \
    --service-account=${SA_EMAIL} \
    --subnet=${SUBNET} \
    --version=2.2 \
    --jars=gs://spark-lib/biglake/biglake-catalog-iceberg1.9.1-0.1.3-with-dependencies.jar \
    --deps-bucket=gs://${BUCKET} \
    --properties="${ICEBERG_PROPS}" \
    -- --project=${PROJECT_ID} --region=${REGION}
fi

# Stage 3: Silver → Gold (requires Iceberg + BLMS)
if [[ "$STAGE" == "all" || "$STAGE" == "silver_to_gold" ]]; then
  echo ""
  echo "=== Stage 3: Silver → Gold ==="
  gcloud dataproc batches submit pyspark \
    gs://${BUCKET}/spark/silver_to_gold.py \
    --project=${PROJECT_ID} \
    --region=${REGION} \
    --service-account=${SA_EMAIL} \
    --subnet=${SUBNET} \
    --version=2.2 \
    --jars=gs://spark-lib/biglake/biglake-catalog-iceberg1.9.1-0.1.3-with-dependencies.jar \
    --deps-bucket=gs://${BUCKET} \
    --properties="${ICEBERG_PROPS}" \
    -- --project=${PROJECT_ID} --region=${REGION}
fi

echo ""
echo "=== Pipeline complete ==="
echo "Validate in BigQuery:"
echo "  bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM \`${PROJECT_ID}.silver_dataset.customers\`'"
echo "  bq query --use_legacy_sql=false 'SELECT * FROM \`${PROJECT_ID}.gold_dataset.customer_order_summary\` LIMIT 10'"
