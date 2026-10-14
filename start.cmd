@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run setup.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import flask, reportlab" >nul 2>&1
if errorlevel 1 (
  echo The environment is incomplete. Please run setup.cmd again.
  pause
  exit /b 1
)
echo.
echo Keep this window open while using the app.
echo Wait for 'Running on http://127.0.0.1:5000'.
echo Then open http://127.0.0.1:5000 in your browser.
echo Press Ctrl+C here to stop the app.
echo.
".venv\Scripts\python.exe" run.py
if errorlevel 1 pause
