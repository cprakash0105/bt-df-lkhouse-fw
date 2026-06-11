#!/bin/bash
# Create BigQuery linked datasets pointing to BLMS databases
set -e

export PROJECT_ID=${1:-schema-evolution-poc}
export REGION=${2:-europe-west2}

echo "=== Creating BigQuery linked datasets ==="

bq mk --dataset \
  --linked_resource="projects/${PROJECT_ID}/locations/${REGION}/catalogs/lakehouse/databases/raw" \
  --location=${REGION} \
  ${PROJECT_ID}:lakehouse_raw 2>/dev/null && echo "  ✅ lakehouse_raw" || echo "  ⚠️  lakehouse_raw exists"

bq mk --dataset \
  --linked_resource="projects/${PROJECT_ID}/locations/${REGION}/catalogs/lakehouse/databases/curated" \
  --location=${REGION} \
  ${PROJECT_ID}:lakehouse_curated 2>/dev/null && echo "  ✅ lakehouse_curated" || echo "  ⚠️  lakehouse_curated exists"

bq mk --dataset \
  --linked_resource="projects/${PROJECT_ID}/locations/${REGION}/catalogs/lakehouse/databases/consumption" \
  --location=${REGION} \
  ${PROJECT_ID}:lakehouse_consumption 2>/dev/null && echo "  ✅ lakehouse_consumption" || echo "  ⚠️  lakehouse_consumption exists"

echo ""
echo "=== Done. Tables auto-appear after Spark jobs write to BLMS ==="
echo ""
echo "Query examples:"
echo "  SELECT COUNT(*) FROM \`${PROJECT_ID}.lakehouse_raw.customers\`"
echo "  SELECT COUNT(*) FROM \`${PROJECT_ID}.lakehouse_curated.orders\`"
echo "  SELECT * FROM \`${PROJECT_ID}.lakehouse_consumption.customer_360\` LIMIT 10"
