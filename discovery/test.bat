@echo off
REM Quick test — runs discovery engine without Chainlit/sentence-transformers
echo Running Semantic Discovery Engine Test...
echo.
cd /d "%~dp0.."
python -m discovery.tests.test_discovery
pause
