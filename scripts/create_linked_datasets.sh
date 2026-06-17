#!/bin/bash
# Create BigQuery linked dataset for CCN layer (Iceberg via BLMS)
# Data Product layer is native BQ — created by Terraform
set -e

export PROJECT_ID=${1:-bt-df-lkhouse}
export REGION=${2:-europe-west2}

echo "=== Creating BigQuery linked dataset (CCN) ==="
echo ""
echo "Note: lakehouse_dataproduct is a native BQ dataset (created by Terraform)"
echo "      lakehouse_ccn is a linked dataset pointing to BLMS Iceberg tables"
echo ""

bq mk --dataset \
  --linked_resource="projects/${PROJECT_ID}/locations/${REGION}/catalogs/lakehouse/databases/ccn" \
  --location=${REGION} \
  ${PROJECT_ID}:lakehouse_ccn 2>/dev/null && echo "  ✅ lakehouse_ccn (linked)" || echo "  ⚠️  lakehouse_ccn already exists"

echo ""
echo "=== Done ==="
echo ""
echo "Layers:"
echo "  Reservoir:    gs://${PROJECT_ID}-lakehouse/reservoir/*  (Parquet — no BQ access)"
echo "  CCN:          ${PROJECT_ID}.lakehouse_ccn.*  (Iceberg via BLMS linked dataset)"
echo "  Data Product: ${PROJECT_ID}.lakehouse_dataproduct.*  (native BigQuery tables)"
echo ""
echo "Query examples:"
echo "  SELECT COUNT(*) FROM \`${PROJECT_ID}.lakehouse_ccn.customers\`"
echo "  SELECT * FROM \`${PROJECT_ID}.lakehouse_dataproduct.customer_360\` LIMIT 10"
