#!/bin/bash
# Deploy Profiler Service to Dataproc master node
# Run this from Cloud Shell or local machine with gcloud access

CLUSTER=lakehouse-cluster
REGION=europe-west2
PROJECT=bt-df-lkhouse
BUCKET=bt-df-lkhouse-lakehouse

echo "=== Uploading profiler service to GCS ==="
gsutil cp profiler-service/app.py gs://$BUCKET/profiler-service/app.py
gsutil cp profiler-service/requirements.txt gs://$BUCKET/profiler-service/requirements.txt
gsutil cp discovery/config/seed_glossary.yaml gs://$BUCKET/framework/config/seed_glossary.yaml

echo "=== Installing on Dataproc master ==="
gcloud compute ssh $CLUSTER-m --zone=${REGION}-a --project=$PROJECT -- \
  "sudo pip install fastapi uvicorn pyyaml pandas google-cloud-storage && \
   gsutil cp gs://$BUCKET/profiler-service/app.py /tmp/profiler_app.py && \
   gsutil cp gs://$BUCKET/framework/config/seed_glossary.yaml /tmp/seed_glossary.yaml && \
   export GLOSSARY_PATH=/tmp/seed_glossary.yaml && \
   export CONFIG_BUCKET=$BUCKET && \
   nohup python -m uvicorn profiler_app:app --host 0.0.0.0 --port 8090 > /tmp/profiler.log 2>&1 &"

echo "=== Profiler service started on port 8090 ==="
echo "Internal IP: gcloud compute instances describe $CLUSTER-m --zone=${REGION}-a --format='get(networkInterfaces[0].networkIP)'"
