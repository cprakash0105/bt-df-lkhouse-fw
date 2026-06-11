#!/bin/bash
# Run AFTER terraform apply — creates BLMS-linked datasets in BigQuery
# (Terraform google provider doesn't natively support linked datasets on BLMS yet)
set -e

export PROJECT_ID=${1:-schema-evolution-poc}
export REGION=${2:-europe-west2}

echo "=== Creating BigQuery linked datasets ==="

# Silver linked dataset
bq mk --dataset \
  --external_table_definition="" \
  --linked_resource="projects/${PROJECT_ID}/locations/${REGION}/catalogs/schema_poc/databases/silver" \
  --location=${REGION} \
  ${PROJECT_ID}:silver_iceberg 2>/dev/null || echo "silver_iceberg already exists or BLMS not ready yet"

# Gold linked dataset
bq mk --dataset \
  --external_table_definition="" \
  --linked_resource="projects/${PROJECT_ID}/locations/${REGION}/catalogs/schema_poc/databases/gold" \
  --location=${REGION} \
  ${PROJECT_ID}:gold_iceberg 2>/dev/null || echo "gold_iceberg already exists or BLMS not ready yet"

echo "=== Done. Verify: ==="
echo "bq ls silver_iceberg"
echo "bq ls gold_iceberg"
