#!/bin/bash
# Upload Dagster orchestration code to GCS.
# Run this after code changes — the VM pulls from GCS on startup/redeploy.

set -e

BUCKET="eastside-lakehouse"
PREFIX="orchestration"

echo "Uploading orchestration code to gs://$BUCKET/$PREFIX/ ..."

gsutil cp eastside/orchestration/workspace.yaml gs://$BUCKET/$PREFIX/
gsutil cp eastside/orchestration/setup.py gs://$BUCKET/$PREFIX/
gsutil -m cp -r eastside/orchestration/eastside_dagster/ gs://$BUCKET/$PREFIX/

echo "Done. To pick up changes on the VM:"
echo "  gcloud compute ssh eastside-dagster -- 'sudo systemctl restart dagster-daemon dagster-webserver'"
