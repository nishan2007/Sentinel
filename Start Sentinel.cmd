@echo off
setlocal
cd /d "%~dp0sentinel-controller"
if not exist ".venv\Scripts\python.exe" (
  echo Sentinel's Python environment is missing. Follow the Windows setup in README.md.
  pause
  exit /b 1
)
if not defined SENTINEL_HOST set "SENTINEL_HOST=0.0.0.0"
if not defined SENTINEL_PORT set "SENTINEL_PORT=8088"
echo Dashboard: http://localhost:%SENTINEL_PORT%/dashboard
echo Other devices: http://THIS-PC-IP:%SENTINEL_PORT%/dashboard
echo Press Ctrl+C to stop Sentinel.
".venv\Scripts\python.exe" -m app.server --host "%SENTINEL_HOST%" --port "%SENTINEL_PORT%"
if errorlevel 1 pause
