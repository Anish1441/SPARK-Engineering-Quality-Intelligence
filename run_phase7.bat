@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo SPARK Phase 7 - Engineering Quality Intelligence 7.3
echo Data Trust + Engineering Safety + Original Module A/B
echo ============================================================

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Local .venv not found in:
  echo         %CD%
  echo.
  echo Create it with:
  echo   py -3.13 -m venv .venv
  echo   call .venv\Scripts\activate.bat
  echo   python -m pip install --upgrade pip
  echo   python -m pip install -r requirements.txt
  exit /b 1
)

echo [INFO] Using local environment:
".venv\Scripts\python.exe" -c "import sys; print(sys.executable)"

echo [INFO] scikit-learn runtime:
".venv\Scripts\python.exe" -c "import sklearn; print(sklearn.__version__)"

echo [INFO] Resolved Phase-1 pipeline root:
".venv\Scripts\python.exe" -c "from core.config import load_settings; print(load_settings().pipeline_root)"

echo [INFO] Running tests...
".venv\Scripts\python.exe" -m pytest -q
if errorlevel 1 (
  echo [ERROR] Tests failed. Application was not started.
  exit /b 1
)

echo [INFO] Dual-module pipeline status:
".venv\Scripts\python.exe" -c "from core.config import load_settings; from core.pipeline_adapter import PipelineAdapter; import pprint; pprint.pp(PipelineAdapter(load_settings().pipeline_root).status())"

echo [INFO] Starting SPARK...
".venv\Scripts\python.exe" app.py
endlocal
