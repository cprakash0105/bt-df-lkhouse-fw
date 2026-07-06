#!/bin/bash
# Auto-shutdown Azure LLM VM after 30 minutes
# Run: bash scripts/shutdown_azure_vm.sh
# Or background: nohup bash scripts/shutdown_azure_vm.sh &

RESOURCE_GROUP=llm-server-rg
VM_NAME=llm-server
DELAY=1800  # 30 minutes in seconds

echo "Azure VM '${VM_NAME}' will deallocate in 30 minutes."
echo "Cancel with: kill $$"
echo ""

sleep ${DELAY}

echo "Deallocating VM: ${VM_NAME}..."
az vm deallocate --resource-group ${RESOURCE_GROUP} --name ${VM_NAME} --no-wait

echo "VM deallocation initiated."
