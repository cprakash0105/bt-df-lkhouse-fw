#!/bin/bash
# Deploy the pipeline orchestrator Cloud Function
# Run from: schema-evolution-gcp-native/

PROJECT_ID=bt-df-lkhouse
REGION=europe-west2
BUCKET=${PROJECT_ID}-lakehouse
FUNCTION_NAME=pipeline-orchestrator

echo "Deploying Cloud Function: ${FUNCTION_NAME}"
echo "Trigger: gs://${BUCKET}/framework/config/tables/*.yaml"

gcloud functions deploy ${FUNCTION_NAME} \
  --gen2 \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --runtime=python312 \
  --source=functions/ \
  --entry-point=pipeline_trigger \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=${BUCKET}" \
  --timeout=540 \
  --memory=1Gi \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},GCP_REGION=${REGION},CONFIG_BUCKET=${BUCKET}" \
  --service-account=${PROJECT_ID}@appspot.gserviceaccount.com

echo ""
echo "Done. The function will trigger when any .yaml lands in:"
echo "  gs://${BUCKET}/framework/config/tables/"
