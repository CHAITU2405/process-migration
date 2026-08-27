@echo off
REM Double-click wrapper. All the real work lives in run.py.
setlocal
cd /d "%~dp0"

set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY python3 -c "import sys" >nul 2>&1 && set "PY=python3"

if not defined PY (
    echo.
    echo   Python was not found. Install Python 3.10 or newer from
    echo   https://python.org/downloads and tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

%PY% run.py %*
if errorlevel 1 pause
exit /b %errorlevel%
