@echo off
setlocal
cd /d "%~dp0"
py -3 --version >nul 2>&1
if not errorlevel 1 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Installed. Run START.cmd. Microsoft Edge is required for Steam login.
pause
exit /b 0
:failed
echo Installation failed. Install Python 3.11+ from python.org and retry.
pause
exit /b 1
