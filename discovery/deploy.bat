@echo off
REM Deploy Semantic Discovery to GCP
REM Prerequisites: gcloud CLI authenticated, Docker installed
REM Usage: deploy.bat

set PROJECT_ID=bt-df-lkhouse
set REGION=europe-west2
set REPO=semantic-discovery
set IMAGE=%REGION%-docker.pkg.dev/%PROJECT_ID%/%REPO%/ui:latest

echo ==========================================
echo  Semantic Discovery - GCP Deployment
echo ==========================================
echo.
echo Project: %PROJECT_ID%
echo Region:  %REGION%
echo Image:   %IMAGE%
echo.

REM Step 1: Ensure APIs are enabled
echo [1/5] Enabling APIs...
call gcloud services enable ^
    run.googleapis.com ^
    artifactregistry.googleapis.com ^
    firestore.googleapis.com ^
    aiplatform.googleapis.com ^
    cloudbuild.googleapis.com ^
    --project=%PROJECT_ID%

REM Step 2: Create Artifact Registry repo (if not exists)
echo.
echo [2/5] Creating Artifact Registry...
call gcloud artifacts repositories create %REPO% ^
    --repository-format=docker ^
    --location=%REGION% ^
    --project=%PROJECT_ID% 2>nul
call gcloud auth configure-docker %REGION%-docker.pkg.dev --quiet

REM Step 3: Build and push container
echo.
echo [3/5] Building container image...
docker build -t %IMAGE% -f Dockerfile.discovery .
echo.
echo Pushing to Artifact Registry...
docker push %IMAGE%

REM Step 4: Deploy to Cloud Run
echo.
echo [4/5] Deploying to Cloud Run...
call gcloud run deploy semantic-discovery ^
    --image=%IMAGE% ^
    --region=%REGION% ^
    --project=%PROJECT_ID% ^
    --platform=managed ^
    --allow-unauthenticated ^
    --port=8000 ^
    --memory=512Mi ^
    --cpu=1 ^
    --min-instances=0 ^
    --max-instances=2 ^
    --set-env-vars="GCP_PROJECT_ID=%PROJECT_ID%,GCP_REGION=%REGION%,EMBEDDER_MODE=vertex"

REM Step 5: Get URL
echo.
echo [5/5] Getting service URL...
call gcloud run services describe semantic-discovery ^
    --region=%REGION% ^
    --project=%PROJECT_ID% ^
    --format="value(status.url)"

echo.
echo ==========================================
echo  Deployment Complete!
echo ==========================================
