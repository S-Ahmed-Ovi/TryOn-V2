@echo off
rem Starts the website and opens it in your browser. Close this window (or press Ctrl+C) to stop.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Not installed yet. Run install.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m tryon run %*
if errorlevel 1 pause
