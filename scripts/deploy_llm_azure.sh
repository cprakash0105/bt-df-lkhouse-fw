#!/bin/bash
# Deploy self-hosted LLM (Ollama) on Azure VM
# Uses Azure free credits. Provides OpenAI-compatible API for SD.
#
# Prerequisites: az CLI logged in (az login)
# Usage: bash scripts/deploy_llm_azure.sh
#
# After deployment, update Cloud Run:
#   LLM_BASE_URL=http://<VM_PUBLIC_IP>:11434/v1
#   LLM_MODEL=gemma2
#   LLM_API_KEY=not-needed

set -e

RESOURCE_GROUP=${RESOURCE_GROUP:-llm-server-rg}
LOCATION=${LOCATION:-uksouth}
VM_NAME=${VM_NAME:-llm-server}
VM_SIZE=${VM_SIZE:-Standard_B4ms}  # 4 vCPU, 16GB RAM

echo "============================================================"
echo "  Deploy Self-Hosted LLM (Ollama) on Azure"
echo "============================================================"
echo "  Resource Group: ${RESOURCE_GROUP}"
echo "  Location:       ${LOCATION}"
echo "  VM:             ${VM_NAME} (${VM_SIZE})"
echo "  Model:          gemma2 (9B)"
echo "============================================================"
echo ""

# Step 1: Create resource group
echo "[1/5] Creating resource group..."
az group create --name ${RESOURCE_GROUP} --location ${LOCATION} --output none

# Step 2: Create VM
echo "[2/5] Creating VM (${VM_SIZE})..."
az vm create \
  --resource-group ${RESOURCE_GROUP} \
  --name ${VM_NAME} \
  --image Debian:debian-12:12:latest \
  --size ${VM_SIZE} \
  --admin-username azureuser \
  --generate-ssh-keys \
  --public-ip-sku Standard \
  --output none

# Step 3: Open port 11434 for Ollama
echo "[3/5] Opening port 11434..."
az vm open-port \
  --resource-group ${RESOURCE_GROUP} \
  --name ${VM_NAME} \
  --port 11434 \
  --priority 1000 \
  --output none

# Step 4: Install Ollama and pull model
echo "[4/5] Installing Ollama and pulling gemma2 model..."
az vm run-command invoke \
  --resource-group ${RESOURCE_GROUP} \
  --name ${VM_NAME} \
  --command-id RunShellScript \
  --scripts '
    # Install Ollama
    curl -fsSL https://ollama.com/install.sh | sh

    # Configure to listen on all interfaces
    mkdir -p /etc/systemd/system/ollama.service.d
    cat > /etc/systemd/system/ollama.service.d/override.conf << EOF
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
EOF

    # Start Ollama
    systemctl daemon-reload
    systemctl enable ollama
    systemctl restart ollama

    # Wait for Ollama to be ready
    sleep 5

    # Pull model
    ollama pull gemma2
  '

# Step 5: Get public IP
echo ""
echo "[5/5] Getting VM public IP..."
PUBLIC_IP=$(az vm show \
  --resource-group ${RESOURCE_GROUP} \
  --name ${VM_NAME} \
  --show-details \
  --query publicIps \
  --output tsv)

echo ""
echo "============================================================"
echo "  LLM Server Ready!"
echo "============================================================"
echo ""
echo "  Public IP: ${PUBLIC_IP}"
echo "  API:       http://${PUBLIC_IP}:11434/v1"
echo "  Model:     gemma2"
echo ""
echo "  Test:"
echo "    curl http://${PUBLIC_IP}:11434/v1/chat/completions \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"model\":\"gemma2\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hello\"}]}'"
echo ""
echo "  Update SD (Cloud Run):"
echo "    gcloud run services update semantic-discovery \\"
echo "      --region=europe-west2 --project=bt-df-lkhouse \\"
echo "      --update-env-vars='LLM_BASE_URL=http://${PUBLIC_IP}:11434/v1,LLM_MODEL=gemma2,LLM_API_KEY=not-needed'"
echo ""
echo "  Cost: ~₹600/day (Standard_B4ms)"
echo "  Stop when not needed: az vm stop --resource-group ${RESOURCE_GROUP} --name ${VM_NAME}"
echo "  Start again: az vm start --resource-group ${RESOURCE_GROUP} --name ${VM_NAME}"
echo ""
echo "  Cleanup (delete everything):"
echo "    az group delete --name ${RESOURCE_GROUP} --yes"
echo "============================================================"
