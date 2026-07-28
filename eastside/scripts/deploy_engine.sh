#!/bin/bash
# deploy_engine.sh — Copy engine code and configs to GCS after git pull
# Run from repo root: bash eastside/scripts/deploy_engine.sh

set -e

BUCKET="eastside-lakehouse"

echo "=== Deploying EastSide engine to gs://${BUCKET} ==="

# Engine code (Dataproc reads from here)
echo "Copying engine code..."
gsutil -m cp eastside/engine/*.py gs://${BUCKET}/engine/

# Pipeline config
echo "Copying pipeline config..."
gsutil cp eastside/config/pipeline.yaml gs://${BUCKET}/config/pipeline.yaml

# Table configs
echo "Copying table configs..."
gsutil -m cp eastside/config/tables/*.yaml gs://${BUCKET}/config/tables/

echo ""
echo "=== Deploy complete ==="
echo "Engine : gs://${BUCKET}/engine/"
echo "Config : gs://${BUCKET}/config/pipeline.yaml"
echo "Tables : gs://${BUCKET}/config/tables/"
