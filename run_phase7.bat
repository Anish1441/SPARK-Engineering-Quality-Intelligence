@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Phase 7 environment not found.
  echo Create it with: py -3.13 -m venv .venv
  exit /b 1
)
set SPARK_PIPELINE_ROOT=C:\Users\anish\OneDrive\Desktop\SPARK_PHASE1
rem Configure this only when the validated pipeline exposes the explicit contract:
rem set SPARK_PIPELINE_ENTRYPOINT=your_module:infer
".venv\Scripts\python.exe" app.py
endlocal
