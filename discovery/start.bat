@echo off
REM Semantic Discovery — Start Chainlit UI
REM Run from: schema-evolution-gcp-native\discovery\

echo =======================================
echo  Semantic Discovery - Starting UI
echo =======================================
echo.

REM Check if virtual env exists
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate
    echo Installing dependencies...
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate
)

echo.
echo Starting Chainlit on http://localhost:8000
echo.

chainlit run ui/app.py --port 8000
