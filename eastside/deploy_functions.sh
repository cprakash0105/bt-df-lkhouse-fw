#!/bin/bash
# Deploy EastSide Cloud Functions (Gen2)
# Two functions form the event chain:
#   1. discovery_trigger: data lands → profile → LLM → config pushed
#   2. pipeline_trigger:  config lands → Bronze → Silver → Gold
#
# Usage: bash eastside/deploy_functions.sh

set -e

PROJECT_ID=${PROJECT_ID:-bt-df-lkhouse}
REGION=${REGION:-europe-west2}
BUCKET="eastside-lakehouse"

echo "============================================================"
echo "  EastSide — Deploy Cloud Functions"
echo "============================================================"
echo "  Project: ${PROJECT_ID}"
echo "  Region:  ${REGION}"
echo "  Bucket:  gs://${BUCKET}/"
echo "============================================================"
echo ""

# --- Function 1: Discovery Trigger ---
echo "[1/2] Deploying discovery_trigger..."
echo "  Trigger: gs://${BUCKET}/landing/** (object finalize)"

gcloud functions deploy eastside-discovery-trigger \
  --gen2 \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --runtime=python312 \
  --source=functions/ \
  --entry-point=discovery_trigger \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=${BUCKET}" \
  --trigger-event-filters-path-pattern="name=landing/**" \
  --memory=512Mi \
  --timeout=540s \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},CONFIG_BUCKET=${BUCKET},LLM_BASE_URL=${LLM_BASE_URL},LLM_API_KEY=${LLM_API_KEY},LLM_MODEL=${LLM_MODEL},LLM_PROJECT=${LLM_PROJECT},AWS_REGION=${AWS_REGION}"

echo "  ✅ discovery_trigger deployed"
echo ""

# --- Function 2: Pipeline Trigger ---
echo "[2/2] Deploying pipeline_trigger..."
echo "  Trigger: gs://${BUCKET}/config/tables/** (object finalize)"

gcloud functions deploy eastside-pipeline-trigger \
  --gen2 \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --runtime=python312 \
  --source=functions/ \
  --entry-point=pipeline_trigger \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=${BUCKET}" \
  --trigger-event-filters-path-pattern="name=config/tables/**" \
  --memory=1Gi \
  --timeout=540s \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},GCP_REGION=${REGION},CONFIG_BUCKET=${BUCKET}"

echo "  ✅ pipeline_trigger deployed"
echo ""

echo "============================================================"
echo "  DEPLOYMENT COMPLETE"
echo "============================================================"
echo ""
echo "  Event chain:"
echo "    Data lands in gs://${BUCKET}/landing/{dataset}/"
echo "      → discovery_trigger fires"
echo "      → Profiles data, calls LLM, generates config"
echo "      → Pushes config to gs://${BUCKET}/config/tables/{dataset}.yaml"
echo "        → pipeline_trigger fires"
echo "        → Submits Bronze/Silver/Gold jobs to Dataproc"
echo ""
echo "  Test:"
echo "    python eastside/datagen/generate.py --project=${PROJECT_ID}"
echo "    (then watch Cloud Functions logs)"
echo ""
echo "  Logs:"
echo "    gcloud functions logs read eastside-discovery-trigger --region=${REGION} --project=${PROJECT_ID}"
echo "    gcloud functions logs read eastside-pipeline-trigger --region=${REGION} --project=${PROJECT_ID}"
echo "============================================================"
