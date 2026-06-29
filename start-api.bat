@echo off
echo Starting Semantic Discovery API (FastAPI) on port 8000...
cd /d "%~dp0"
python -m uvicorn discovery.api.main:app --reload --port 8000
