#!/bin/bash
# Deploy self-hosted LLM (Ollama) on a GCP VM
# Provides an OpenAI-compatible API for SD — no rate limits, no API costs.
#
# Usage: bash scripts/deploy_llm_vm.sh
#
# After deployment:
#   LLM_BASE_URL=http://<VM_IP>:11434/v1
#   LLM_MODEL=gemma2
#   LLM_API_KEY=not-needed

set -e

PROJECT_ID=${PROJECT_ID:-bt-df-lkhouse}
ZONE=${ZONE:-europe-west2-a}
VM_NAME=llm-server
MACHINE_TYPE=e2-standard-4  # 4 vCPUs, 16GB RAM — enough for 7B/9B models

echo "============================================================"
echo "  Deploy Self-Hosted LLM (Ollama)"
echo "============================================================"
echo "  Project:  ${PROJECT_ID}"
echo "  Zone:     ${ZONE}"
echo "  VM:       ${VM_NAME} (${MACHINE_TYPE})"
echo "  Model:    gemma2 (9B params)"
echo "============================================================"
echo ""

# Step 1: Create VM
echo "[1/4] Creating VM..."
gcloud compute instances create ${VM_NAME} \
  --project=${PROJECT_ID} \
  --zone=${ZONE} \
  --machine-type=${MACHINE_TYPE} \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=50GB \
  --tags=llm-server \
  --metadata=startup-script='#!/bin/bash
    # Install Ollama
    curl -fsSL https://ollama.com/install.sh | sh
    
    # Start Ollama service
    systemctl enable ollama
    systemctl start ollama
    
    # Wait for Ollama to be ready
    sleep 10
    
    # Pull the model (gemma2 9B — fits in 16GB RAM)
    ollama pull gemma2
    
    # Configure to listen on all interfaces
    mkdir -p /etc/systemd/system/ollama.service.d
    cat > /etc/systemd/system/ollama.service.d/override.conf << EOF
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
EOF
    systemctl daemon-reload
    systemctl restart ollama
    
    echo "LLM server ready"
  '

echo ""
echo "[2/4] Creating firewall rule (internal only)..."
gcloud compute firewall-rules create allow-ollama-internal \
  --project=${PROJECT_ID} \
  --network=schema-poc-network \
  --allow=tcp:11434 \
  --source-ranges=10.0.0.0/8 \
  --target-tags=llm-server \
  --description="Allow internal access to Ollama LLM server" \
  2>/dev/null || echo "  Firewall rule already exists"

echo ""
echo "[3/4] Waiting for VM to start..."
sleep 30

# Get internal IP
INTERNAL_IP=$(gcloud compute instances describe ${VM_NAME} \
  --project=${PROJECT_ID} --zone=${ZONE} \
  --format="value(networkInterfaces[0].networkIP)")

echo "  Internal IP: ${INTERNAL_IP}"

echo ""
echo "[4/4] Waiting for model download (this takes 5-10 minutes)..."
echo "  You can monitor with: gcloud compute ssh ${VM_NAME} --zone=${ZONE} -- journalctl -u ollama -f"

echo ""
echo "============================================================"
echo "  LLM Server Deployment Started"
echo "============================================================"
echo ""
echo "  VM: ${VM_NAME} (${INTERNAL_IP})"
echo "  API: http://${INTERNAL_IP}:11434/v1"
echo "  Model: gemma2"
echo ""
echo "  To configure SD to use this LLM, set these env vars"
echo "  in Cloud Run:"
echo ""
echo "    LLM_BASE_URL=http://${INTERNAL_IP}:11434/v1"
echo "    LLM_MODEL=gemma2"
echo "    LLM_API_KEY=not-needed"
echo ""
echo "  To test:"
echo "    curl http://${INTERNAL_IP}:11434/v1/chat/completions \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"model\":\"gemma2\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hello\"}]}'"
echo ""
echo "  To update Cloud Run:"
echo "    gcloud run services update semantic-discovery \\"
echo "      --region=${ZONE%-*} --project=${PROJECT_ID} \\"
echo "      --set-env-vars='LLM_BASE_URL=http://${INTERNAL_IP}:11434/v1,LLM_MODEL=gemma2,LLM_API_KEY=not-needed'"
echo ""
echo "  Estimated cost: ~\$25/month (e2-standard-4, 24/7)"
echo "  To stop when not needed: gcloud compute instances stop ${VM_NAME} --zone=${ZONE}"
echo "============================================================"
