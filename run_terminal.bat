@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" main.py
) else (
  python main.py
)
set "EXIT_CODE=%ERRORLEVEL%"
if not "%PAT_NONINTERACTIVE%"=="1" pause
exit /b %EXIT_CODE%
