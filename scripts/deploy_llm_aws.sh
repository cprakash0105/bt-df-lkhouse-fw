#!/bin/bash
# Deploy self-hosted LLM (Ollama) on AWS EC2
# Like-for-like replacement for the Azure VM deployment.
#
# Prerequisites: aws CLI configured (aws configure)
# Usage: bash scripts/deploy_llm_aws.sh
#
# After deployment, update Cloud Run:
#   LLM_BASE_URL=http://<EC2_PUBLIC_IP>:11434/v1
#   LLM_MODEL=gemma2
#   LLM_API_KEY=not-needed

set -e

REGION=${AWS_REGION:-eu-west-2}
INSTANCE_TYPE=${INSTANCE_TYPE:-t3.xlarge}  # 4 vCPU, 16GB RAM (~$0.17/hr)
KEY_NAME=${KEY_NAME:-llm-server-key}
SG_NAME="llm-server-sg"
INSTANCE_NAME="llm-server"

echo "============================================================"
echo "  Deploy Self-Hosted LLM (Ollama) on AWS EC2"
echo "============================================================"
echo "  Region:   ${REGION}"
echo "  Instance: ${INSTANCE_TYPE} (4 vCPU, 16GB)"
echo "  Model:    gemma2 (9B)"
echo "  Cost:     ~\$0.17/hr on-demand (~\$4/day)"
echo "============================================================"
echo ""

# Step 1: Create key pair (if not exists)
echo "[1/6] Creating key pair..."
if ! aws ec2 describe-key-pairs --key-names ${KEY_NAME} --region ${REGION} 2>/dev/null; then
  aws ec2 create-key-pair \
    --key-name ${KEY_NAME} \
    --region ${REGION} \
    --query 'KeyMaterial' \
    --output text > ${KEY_NAME}.pem
  chmod 400 ${KEY_NAME}.pem
  echo "  Key saved to ${KEY_NAME}.pem"
else
  echo "  Key pair already exists"
fi

# Step 2: Create security group
echo "[2/6] Creating security group..."
VPC_ID=$(aws ec2 describe-vpcs --region ${REGION} --filters "Name=isDefault,Values=true" --query 'Vpcs[0].VpcId' --output text)

SG_ID=$(aws ec2 describe-security-groups --region ${REGION} --filters "Name=group-name,Values=${SG_NAME}" --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")

if [ "$SG_ID" = "None" ] || [ -z "$SG_ID" ]; then
  SG_ID=$(aws ec2 create-security-group \
    --group-name ${SG_NAME} \
    --description "LLM server - Ollama" \
    --vpc-id ${VPC_ID} \
    --region ${REGION} \
    --query 'GroupId' \
    --output text)

  # Allow SSH
  aws ec2 authorize-security-group-ingress \
    --group-id ${SG_ID} --region ${REGION} \
    --protocol tcp --port 22 --cidr 0.0.0.0/0

  # Allow Ollama API
  aws ec2 authorize-security-group-ingress \
    --group-id ${SG_ID} --region ${REGION} \
    --protocol tcp --port 11434 --cidr 0.0.0.0/0

  echo "  Created SG: ${SG_ID}"
else
  echo "  Using existing SG: ${SG_ID}"
fi

# Step 3: Get latest Debian 12 AMI
echo "[3/6] Finding Debian 12 AMI..."
AMI_ID=$(aws ec2 describe-images \
  --region ${REGION} \
  --owners 136693071363 \
  --filters "Name=name,Values=debian-12-amd64-*" "Name=state,Values=available" \
  --query 'sort_by(Images, &CreationDate)[-1].ImageId' \
  --output text)
echo "  AMI: ${AMI_ID}"

# Step 4: Launch instance
echo "[4/6] Launching EC2 instance..."
INSTANCE_ID=$(aws ec2 run-instances \
  --region ${REGION} \
  --image-id ${AMI_ID} \
  --instance-type ${INSTANCE_TYPE} \
  --key-name ${KEY_NAME} \
  --security-group-ids ${SG_ID} \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":30,"VolumeType":"gp3"}}]' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${INSTANCE_NAME}}]" \
  --query 'Instances[0].InstanceId' \
  --output text)
echo "  Instance: ${INSTANCE_ID}"

# Step 5: Wait for instance and get IP
echo "[5/6] Waiting for instance to be running..."
aws ec2 wait instance-running --instance-ids ${INSTANCE_ID} --region ${REGION}

PUBLIC_IP=$(aws ec2 describe-instances \
  --instance-ids ${INSTANCE_ID} \
  --region ${REGION} \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text)
echo "  Public IP: ${PUBLIC_IP}"

# Step 6: Install Ollama and pull model
echo "[6/6] Installing Ollama (waiting 30s for SSH to be ready)..."
sleep 30

ssh -o StrictHostKeyChecking=no -i ${KEY_NAME}.pem admin@${PUBLIC_IP} << 'EOF'
  # Install Ollama
  curl -fsSL https://ollama.com/install.sh | sh

  # Configure to listen on all interfaces
  sudo mkdir -p /etc/systemd/system/ollama.service.d
  sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null << CONF
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
CONF

  sudo systemctl daemon-reload
  sudo systemctl enable ollama
  sudo systemctl restart ollama

  # Wait for Ollama to be ready
  sleep 5

  # Pull model
  ollama pull gemma2
EOF

echo ""
echo "============================================================"
echo "  LLM Server Ready!"
echo "============================================================"
echo ""
echo "  Instance:  ${INSTANCE_ID}"
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
echo "  Cost: ~\$4/day (t3.xlarge on-demand)"
echo "  Stop when not needed: aws ec2 stop-instances --instance-ids ${INSTANCE_ID} --region ${REGION}"
echo "  Start again:          aws ec2 start-instances --instance-ids ${INSTANCE_ID} --region ${REGION}"
echo "  (IP changes on restart — use Elastic IP if needed)"
echo ""
echo "  Cleanup (terminate):"
echo "    aws ec2 terminate-instances --instance-ids ${INSTANCE_ID} --region ${REGION}"
echo "============================================================"
