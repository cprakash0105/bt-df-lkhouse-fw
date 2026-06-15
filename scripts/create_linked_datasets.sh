#!/bin/bash
# Create BigQuery linked datasets pointing to BLMS databases
set -e

export PROJECT_ID=${1:-schema-evolution-poc}
export REGION=${2:-europe-west2}

echo "=== Creating BigQuery linked datasets ==="

bq mk --dataset \
  --linked_resource="projects/${PROJECT_ID}/locations/${REGION}/catalogs/lakehouse/databases/reservoir" \
  --location=${REGION} \
  ${PROJECT_ID}:lakehouse_reservoir 2>/dev/null && echo "  ✅ lakehouse_reservoir" || echo "  ⚠️  lakehouse_reservoir exists"

bq mk --dataset \
  --linked_resource="projects/${PROJECT_ID}/locations/${REGION}/catalogs/lakehouse/databases/ccn" \
  --location=${REGION} \
  ${PROJECT_ID}:lakehouse_ccn 2>/dev/null && echo "  ✅ lakehouse_ccn" || echo "  ⚠️  lakehouse_ccn exists"

bq mk --dataset \
  --linked_resource="projects/${PROJECT_ID}/locations/${REGION}/catalogs/lakehouse/databases/dataproduct" \
  --location=${REGION} \
  ${PROJECT_ID}:lakehouse_dataproduct 2>/dev/null && echo "  ✅ lakehouse_dataproduct" || echo "  ⚠️  lakehouse_dataproduct exists"

echo ""
echo "=== Done ==="
echo ""
echo "Query examples:"
echo "  SELECT COUNT(*) FROM \`${PROJECT_ID}.lakehouse_reservoir.customers\`"
echo "  SELECT COUNT(*) FROM \`${PROJECT_ID}.lakehouse_ccn.orders\`"
echo "  SELECT * FROM \`${PROJECT_ID}.lakehouse_dataproduct.customer_360\` LIMIT 10"
