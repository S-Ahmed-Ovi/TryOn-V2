@echo off
rem ---------------------------------------------------------------
rem  One-time setup (Windows): creates .venv and installs everything.
rem  Needs Python 3.10 - 3.13 from https://www.python.org/downloads/
rem ---------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "PY="
for %%v in (3.12 3.11 3.10 3.13) do (
  if not defined PY (
    py -%%v -c "import sys" >nul 2>nul && set "PY=py -%%v"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<(3,14) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo  Python 3.10 - 3.13 was not found. Install Python 3.12 from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH", then run install.bat again.
  exit /b 1
)

echo Using: %PY%
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv || goto :fail
)
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
echo Installing packages (first time takes a few minutes)...
".venv\Scripts\python.exe" -m pip install -e . || goto :fail
echo.
".venv\Scripts\python.exe" -m tryon doctor
echo.
echo  Done.  Double-click run.bat to start the website.
exit /b 0

:fail
echo.
echo  Installation failed. If you see "Microsoft Visual C++" in the message above, install
echo  https://aka.ms/vs/17/release/vc_redist.x64.exe and run install.bat again.
exit /b 1
