#!/bin/bash
# ============================================================
# GCP Infrastructure Inventory Script
# Generates a full list of services, SAs, APIs, resources
# used in the project for provisioning in a new environment.
#
# Usage (from Cloud Shell):
#   chmod +x eastside/scripts/inventory.sh
#   ./eastside/scripts/inventory.sh
#
# Output: inventory_report.md in current directory
# ============================================================

PROJECT_ID="${1:-bt-df-lkhouse}"
REGION="europe-west2"
OUTPUT="inventory_report.md"

echo "Scanning project: $PROJECT_ID"
echo "Output: $OUTPUT"
echo ""

cat > "$OUTPUT" << 'HEADER'
# GCP Infrastructure Inventory

**Purpose:** Full list of services, service accounts, APIs, and resources used in the POC. Use this to provision equivalent infrastructure in the BT environment.

HEADER

echo "**Project:** $PROJECT_ID" >> "$OUTPUT"
echo "**Region:** $REGION" >> "$OUTPUT"
echo "**Generated:** $(date -u '+%Y-%m-%d %H:%M UTC')" >> "$OUTPUT"
echo "" >> "$OUTPUT"

# ============================================================
echo "## 1. Enabled APIs" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo "Fetching enabled APIs..."
echo '```' >> "$OUTPUT"
gcloud services list --enabled --project="$PROJECT_ID" --format="value(config.name)" | sort >> "$OUTPUT"
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

# ============================================================
echo "## 2. Service Accounts" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo "Fetching service accounts..."
echo "| Email | Display Name |" >> "$OUTPUT"
echo "|-------|-------------|" >> "$OUTPUT"
gcloud iam service-accounts list --project="$PROJECT_ID" --format="csv[no-heading](email,displayName)" | while IFS=',' read -r email name; do
  echo "| $email | $name |" >> "$OUTPUT"
done
echo "" >> "$OUTPUT"

# IAM bindings per SA
echo "### Service Account IAM Roles" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
gcloud projects get-iam-policy "$PROJECT_ID" --format="table(bindings.role,bindings.members)" --flatten="bindings[].members" 2>/dev/null | grep -i "serviceAccount" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

# ============================================================
echo "## 3. GCS Buckets" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo "Fetching buckets..."
echo "| Bucket | Location | Storage Class |" >> "$OUTPUT"
echo "|--------|----------|---------------|" >> "$OUTPUT"
gsutil ls -p "$PROJECT_ID" 2>/dev/null | while read -r bucket; do
  bucket_name=$(echo "$bucket" | sed 's|gs://||;s|/||')
  info=$(gsutil ls -L -b "$bucket" 2>/dev/null)
  location=$(echo "$info" | grep "Location constraint:" | awk '{print $NF}')
  class=$(echo "$info" | grep "Storage class:" | awk '{print $NF}')
  echo "| $bucket_name | $location | $class |" >> "$OUTPUT"
done
echo "" >> "$OUTPUT"

# Bucket structure for main lakehouse bucket
echo "### Lakehouse Bucket Structure" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
gsutil ls "gs://eastside-lakehouse/" 2>/dev/null >> "$OUTPUT"
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

# ============================================================
echo "## 4. BigQuery Datasets" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo "Fetching BQ datasets..."
echo "| Dataset | Location | Description |" >> "$OUTPUT"
echo "|---------|----------|-------------|" >> "$OUTPUT"
bq ls --project_id="$PROJECT_ID" --format=json 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    for d in data:
        did = d.get('datasetReference',{}).get('datasetId','')
        loc = d.get('location','')
        desc = d.get('description','') or ''
        print(f'| {did} | {loc} | {desc} |')
except: pass
" >> "$OUTPUT"
echo "" >> "$OUTPUT"

# Tables per dataset
echo "### Tables per Dataset" >> "$OUTPUT"
echo "" >> "$OUTPUT"
for ds in $(bq ls --project_id="$PROJECT_ID" --format=json 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    for d in data:
        print(d.get('datasetReference',{}).get('datasetId',''))
except: pass
"); do
  echo "**$ds:**" >> "$OUTPUT"
  echo '```' >> "$OUTPUT"
  bq ls --project_id="$PROJECT_ID" "$ds" 2>/dev/null >> "$OUTPUT"
  echo '```' >> "$OUTPUT"
  echo "" >> "$OUTPUT"
done

# ============================================================
echo "## 5. BigLake Metastore (BLMS) Catalogs" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo "Fetching BLMS catalogs..."
echo '```' >> "$OUTPUT"
gcloud biglake catalogs list --project="$PROJECT_ID" --location="$REGION" 2>/dev/null >> "$OUTPUT" || echo "No catalogs found or API not enabled" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

echo "### BLMS Databases" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
for catalog in $(gcloud biglake catalogs list --project="$PROJECT_ID" --location="$REGION" --format="value(name)" 2>/dev/null); do
  echo "Catalog: $catalog" >> "$OUTPUT"
  gcloud biglake databases list --catalog="$catalog" --project="$PROJECT_ID" --location="$REGION" 2>/dev/null >> "$OUTPUT"
done
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

# ============================================================
echo "## 6. Cloud Run Services" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo "Fetching Cloud Run services..."
echo "| Service | Region | URL | SA |" >> "$OUTPUT"
echo "|---------|--------|-----|-----|" >> "$OUTPUT"
gcloud run services list --project="$PROJECT_ID" --format="csv[no-heading](metadata.name,region,status.url,spec.template.spec.serviceAccountName)" 2>/dev/null | while IFS=',' read -r name region url sa; do
  echo "| $name | $region | $url | $sa |" >> "$OUTPUT"
done
echo "" >> "$OUTPUT"

# ============================================================
echo "## 7. Dataproc Clusters" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo "Fetching Dataproc clusters..."
echo '```' >> "$OUTPUT"
gcloud dataproc clusters list --project="$PROJECT_ID" --region="$REGION" --format="table(clusterName,status.state,config.masterConfig.machineTypeUri,config.workerConfig.machineTypeUri,config.workerConfig.numInstances)" 2>/dev/null >> "$OUTPUT" || echo "No clusters found" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

# ============================================================
echo "## 8. Compute Engine Instances" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo "Fetching VMs..."
echo "| Name | Zone | Machine Type | Status | IP |" >> "$OUTPUT"
echo "|------|------|-------------|--------|-----|" >> "$OUTPUT"
gcloud compute instances list --project="$PROJECT_ID" --format="csv[no-heading](name,zone.basename(),machineType.basename(),status,networkInterfaces[0].accessConfigs[0].natIP)" 2>/dev/null | while IFS=',' read -r name zone mt status ip; do
  echo "| $name | $zone | $mt | $status | $ip |" >> "$OUTPUT"
done
echo "" >> "$OUTPUT"

# ============================================================
echo "## 9. Cloud KMS Keys" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo "Fetching KMS keyrings..."
echo '```' >> "$OUTPUT"
for kr in $(gcloud kms keyrings list --project="$PROJECT_ID" --location="$REGION" --format="value(name)" 2>/dev/null); do
  echo "Keyring: $kr" >> "$OUTPUT"
  gcloud kms keys list --keyring="$kr" --location="$REGION" --project="$PROJECT_ID" --format="table(name.basename(),purpose,rotationPeriod,primaryState)" 2>/dev/null >> "$OUTPUT"
done
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

# ============================================================
echo "## 10. VPC Networks & Firewall" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo "Fetching networks..."
echo "### Networks" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
gcloud compute networks list --project="$PROJECT_ID" --format="table(name,subnetMode,autoCreateSubnetworks)" 2>/dev/null >> "$OUTPUT"
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

echo "### Subnets (${REGION})" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
gcloud compute networks subnets list --project="$PROJECT_ID" --regions="$REGION" --format="table(name,network.basename(),ipCidrRange,privateIpGoogleAccess)" 2>/dev/null >> "$OUTPUT"
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

echo "### Firewall Rules" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
gcloud compute firewall-rules list --project="$PROJECT_ID" --format="table(name,network.basename(),direction,allowed[].map().firewall_rule().list():label=ALLOW,sourceRanges.list():label=SRC)" 2>/dev/null >> "$OUTPUT"
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

# ============================================================
echo "## 11. Cloud NAT & Router" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
gcloud compute routers list --project="$PROJECT_ID" --regions="$REGION" --format="table(name,network.basename(),region.basename())" 2>/dev/null >> "$OUTPUT"
echo "" >> "$OUTPUT"
gcloud compute routers nats list --project="$PROJECT_ID" --region="$REGION" --router="$(gcloud compute routers list --project=$PROJECT_ID --regions=$REGION --format='value(name)' --limit=1 2>/dev/null)" 2>/dev/null >> "$OUTPUT" || echo "No NAT found" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

# ============================================================
echo "## 12. Cloud Functions" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo "Fetching Cloud Functions..."
echo "| Name | Region | Runtime | Trigger |" >> "$OUTPUT"
echo "|------|--------|---------|---------|" >> "$OUTPUT"
gcloud functions list --project="$PROJECT_ID" --format="csv[no-heading](name,region,runtime,eventTrigger.eventType)" 2>/dev/null | while IFS=',' read -r name region runtime trigger; do
  echo "| $name | $region | $runtime | $trigger |" >> "$OUTPUT"
done
echo "" >> "$OUTPUT"

# ============================================================
echo "## 13. Cloud Build Triggers" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
gcloud builds triggers list --project="$PROJECT_ID" --region="$REGION" --format="table(name,filename,triggerTemplate.branchName)" 2>/dev/null >> "$OUTPUT" || echo "No triggers found" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

# ============================================================
echo "## 14. Artifact Registry Repositories" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
gcloud artifacts repositories list --project="$PROJECT_ID" --location="$REGION" --format="table(name,format,mode)" 2>/dev/null >> "$OUTPUT" || echo "No repos found" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

# ============================================================
echo "## 15. BigQuery Connections (BigLake)" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
bq ls --connection --project_id="$PROJECT_ID" --location="$REGION" 2>/dev/null >> "$OUTPUT" || echo "No connections found" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

# ============================================================
echo "## 16. Dataplex Resources" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
gcloud dataplex lakes list --project="$PROJECT_ID" --location="$REGION" --format="table(name,state)" 2>/dev/null >> "$OUTPUT" || echo "No lakes found" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

# ============================================================
echo "## 17. Secret Manager Secrets" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo "| Secret Name | Created |" >> "$OUTPUT"
echo "|-------------|---------|" >> "$OUTPUT"
gcloud secrets list --project="$PROJECT_ID" --format="csv[no-heading](name,createTime)" 2>/dev/null | while IFS=',' read -r name created; do
  echo "| $name | $created |" >> "$OUTPUT"
done
echo "" >> "$OUTPUT"

# ============================================================
echo "## 18. IAM Custom Roles" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
gcloud iam roles list --project="$PROJECT_ID" --format="table(name,title,stage)" 2>/dev/null >> "$OUTPUT" || echo "No custom roles" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

# ============================================================
echo "## 19. Static External IPs" >> "$OUTPUT"
echo "" >> "$OUTPUT"
echo '```' >> "$OUTPUT"
gcloud compute addresses list --project="$PROJECT_ID" --format="table(name,address,status,region.basename())" 2>/dev/null >> "$OUTPUT"
echo '```' >> "$OUTPUT"
echo "" >> "$OUTPUT"

# ============================================================
echo "## 20. Summary — What to Provision" >> "$OUTPUT"
echo "" >> "$OUTPUT"
cat >> "$OUTPUT" << 'SUMMARY'
### Minimum Required Services
1. **GCS** — 1 bucket (lakehouse storage: landing, bronze, silver, gold, config, logs)
2. **BigQuery** — 3+ datasets (bronze external, silver external, gold native, dataproduct)
3. **BigLake Metastore** — 1 catalog, 2 databases (bronze, silver)
4. **BigLake Connection** — For BQ to read Iceberg tables on GCS
5. **Dataproc** — Managed cluster (Spark for bronze/silver/gold jobs)
6. **Cloud Run** — 2 services (Semantic Discovery UI+API, Profiler)
7. **Cloud KMS** — 1 keyring, 1 key (PII encryption, 90-day rotation)
8. **Compute Engine** — 1 VM (Dagster orchestrator, e2-small)
9. **Cloud Functions** — GCS event trigger (auto-run pipeline on file arrival)
10. **Artifact Registry** — Docker image storage for Cloud Run
11. **Cloud Build** — CI/CD pipelines
12. **VPC + NAT** — Private networking for Dataproc + Dagster
13. **Dataplex** — Knowledge Catalog (glossary, policy tags)
14. **Secret Manager** — API keys (LLM, etc.)

### Service Accounts Needed
| SA | Purpose | Key Roles |
|----|---------|-----------|
| eastside-dataproc | Spark jobs | Storage Admin, BigQuery Admin, BigLake Admin |
| eastside-dagster | Orchestration | Dataproc Editor, Storage Object Viewer |
| cloud-run-sa | SD API + UI | Storage Viewer, Firestore User, Secret Accessor |
| cloud-functions-sa | Pipeline trigger | Dataproc Editor, Storage Object Viewer |

### APIs to Enable
```
bigquery.googleapis.com
biglake.googleapis.com
cloudkms.googleapis.com
cloudresourcemanager.googleapis.com
compute.googleapis.com
dataproc.googleapis.com
run.googleapis.com
cloudbuild.googleapis.com
cloudfunctions.googleapis.com
artifactregistry.googleapis.com
dataplex.googleapis.com
secretmanager.googleapis.com
storage.googleapis.com
firestore.googleapis.com
```
SUMMARY

echo "" >> "$OUTPUT"
echo "---" >> "$OUTPUT"
echo "*Generated by inventory.sh on $(date -u '+%Y-%m-%d %H:%M UTC')*" >> "$OUTPUT"

echo ""
echo "============================================================"
echo "  DONE — Report saved to: $OUTPUT"
echo "============================================================"
echo ""
echo "  Share this file with the BT team for provisioning."
echo "  They can use it as a checklist + reference."
echo ""
