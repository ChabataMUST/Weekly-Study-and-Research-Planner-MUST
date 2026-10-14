@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
if errorlevel 1 (
  echo.
  echo Setup failed. See the message above or docs for help.
) else (
  echo.
  echo Setup complete. Double-click start.cmd next.
)
pause
