#!/bin/bash
# Auto-shutdown Dataproc cluster after 30 minutes
# Run: bash scripts/shutdown_dataproc.sh
# Or background: nohup bash scripts/shutdown_dataproc.sh &

PROJECT_ID=bt-df-lkhouse
REGION=europe-west2
CLUSTER=lakehouse-cluster
DELAY=1800  # 30 minutes in seconds

echo "Dataproc cluster '${CLUSTER}' will stop in 30 minutes."
echo "Cancel with: kill $$"
echo ""

sleep ${DELAY}

echo "Stopping cluster: ${CLUSTER}..."
gcloud dataproc clusters stop ${CLUSTER} --region=${REGION} --project=${PROJECT_ID} --quiet

echo "Cluster stopped."
