#!/bin/bash
# bt-df-lkhouse-fw v2: Run Lakehouse Pipeline
# Reservoir(Parquet) → CCN(Iceberg/BLMS) → Data Product(BigQuery)
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

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  bt-df-lkhouse-fw v2 — Pipeline Runner                    ║"
echo "║  Project: ${PROJECT_ID}                                    ║"
echo "║  Region:  ${REGION}                                        ║"
echo "║  Version: ${VERSION}                                       ║"
echo "║  Stage:   ${STAGE}                                         ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# === Package and upload framework to GCS ===
echo "=== Packaging framework → GCS ==="
cd "$(dirname "$0")/.."
zip -r /tmp/bt_df_lkhouse_fw.zip bt_df_lkhouse_fw/
gsutil -q cp /tmp/bt_df_lkhouse_fw.zip gs://${BUCKET}/framework/bt_df_lkhouse_fw.zip
gsutil -q -m cp -r bt_df_lkhouse_fw/config/* gs://${BUCKET}/framework/config/
gsutil -q -m cp -r bt_df_lkhouse_fw/engine/* gs://${BUCKET}/framework/engine/
echo "  ✅ Framework uploaded"

PY_FILES="gs://${BUCKET}/framework/bt_df_lkhouse_fw.zip"

# === Stage 1: Landing → Reservoir (Parquet) ===
if [[ "$STAGE" == "all" || "$STAGE" == "ingest" ]]; then
  echo ""
  echo "=== Stage 1: Landing (JSONL) → Reservoir (Parquet) ==="
  gcloud dataproc batches submit pyspark \
    gs://${BUCKET}/framework/engine/ingest.py \
    --project=${PROJECT_ID} --region=${REGION} \
    --service-account=${SA_EMAIL} --subnet=${SUBNET} \
    --version=2.2 \
    --deps-bucket=gs://${BUCKET} \
    --py-files=${PY_FILES} \
    --properties="spark.jars.packages=org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.9.1,spark.executor.instances=2,spark.driver.cores=2,spark.executor.cores=2,spark.driver.memory=2g,spark.executor.memory=2g" \
    -- --config=${CONFIG_PATH} --all --version=${VERSION} --project=${PROJECT_ID}
fi

# === Stage 2: Reservoir (Parquet) → CCN (Iceberg/BLMS) ===
if [[ "$STAGE" == "all" || "$STAGE" == "curate" ]]; then
  echo ""
  echo "=== Stage 2: Reservoir (Parquet) → CCN (Iceberg/BLMS) ==="
  gcloud dataproc batches submit pyspark \
    gs://${BUCKET}/framework/engine/curate.py \
    --project=${PROJECT_ID} --region=${REGION} \
    --service-account=${SA_EMAIL} --subnet=${SUBNET} \
    --version=2.2 \
    --jars=gs://spark-lib/biglake/biglake-catalog-iceberg1.9.1-0.1.3-with-dependencies.jar \
    --deps-bucket=gs://${BUCKET} \
    --py-files=${PY_FILES} \
    --properties="${ICEBERG_PROPS}::spark.executor.instances=2::spark.driver.cores=2::spark.executor.cores=2::spark.driver.memory=2g::spark.executor.memory=2g" \
    -- --config=${CONFIG_PATH} --all --project=${PROJECT_ID}
fi

# === Stage 3: CCN (Iceberg) → Data Product (BigQuery native) ===
if [[ "$STAGE" == "all" || "$STAGE" == "consume" ]]; then
  echo ""
  echo "=== Stage 3: CCN (Iceberg) → Data Product (BigQuery) ==="
  # Consume runs as pure Python (BigQuery client) — no Spark needed
  python3 -m bt_df_lkhouse_fw.engine.consume \
    --config=bt_df_lkhouse_fw/config/pipeline.yaml \
    --all --project=${PROJECT_ID}
fi

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  ✅ Pipeline complete                                      ║"
echo "╠════════════════════════════════════════════════════════════╣"
echo "║  Reservoir: gs://${BUCKET}/reservoir/*  (Parquet)          ║"
echo "║  CCN:       lakehouse_ccn.*  (Iceberg via BLMS linked DS)  ║"
echo "║  DP:        lakehouse_dataproduct.*  (BigQuery native)     ║"
echo "╚════════════════════════════════════════════════════════════╝"
