@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUNBUFFERED=1"
set "PYTHONUTF8=1"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -u main.py
) else (
  python -u main.py
)
set "EXIT_CODE=%ERRORLEVEL%"
if not "%PAT_NONINTERACTIVE%"=="1" pause
exit /b %EXIT_CODE%
