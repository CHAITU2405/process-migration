@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title AppMigrate

REM ============================================================
REM  AppMigrate launcher
REM
REM    run.bat              menu
REM    run.bat controller   laptop 1 - the one you sit at
REM    run.bat agent [name] laptop 2 - the one that does the work
REM    run.bat check [host] inspect the link between the laptops
REM    run.bat install      install dependencies
REM ============================================================

REM ---- locate a working Python -------------------------------
REM The Windows Store build reports itself as python3.13.exe, so try the
REM py launcher first: it resolves the real interpreter either way.
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY python3 -c "import sys" >nul 2>&1 && set "PY=python3"

if not defined PY (
    echo.
    echo   Python was not found on this machine.
    echo.
    echo   Install Python 3.10 or newer from https://python.org/downloads
    echo   and tick "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%V in ('%PY% --version 2^>^&1') do set "PYVER=%%V"

REM ---- dispatch on argument ----------------------------------
if /i "%~1"=="controller" goto :controller
if /i "%~1"=="agent"      goto :agent
if /i "%~1"=="check"      goto :check
if /i "%~1"=="install"    goto :install
if not "%~1"=="" (
    echo Unknown option "%~1".
    echo Use: run.bat [controller^|agent^|check^|install]
    exit /b 1
)

REM ---- menu --------------------------------------------------
:menu
cls
echo.
echo   ================================================
echo     AppMigrate     Python %PYVER%
echo   ================================================
echo.
echo     Move a running app to the other laptop and
echo     keep its window on this screen.
echo.
echo     [1]  Controller     this laptop  (laptop 1)
echo     [2]  Agent          target       (laptop 2)
echo     [3]  Check link     what cable / network is up
echo     [4]  Install dependencies
echo     [5]  Exit
echo.
set "CHOICE="
set /p "CHOICE=  Select 1-5: "

if "%CHOICE%"=="1" goto :controller
if "%CHOICE%"=="2" goto :agent
if "%CHOICE%"=="3" goto :check
if "%CHOICE%"=="4" goto :install
if "%CHOICE%"=="5" exit /b 0
goto :menu

REM ---- dependency check --------------------------------------
:ensure_deps
%PY% -c "import PySide6, psutil, PIL" >nul 2>&1
if not errorlevel 1 exit /b 0
echo.
echo   Dependencies are missing. Installing them now...
echo.
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo   Install failed. Try running this window as Administrator,
    echo   or enable Long Path support if pip complained about path length:
    echo     https://pip.pypa.io/warnings/enable-long-paths
    echo.
    pause
    exit /b 1
)
echo.
echo   Dependencies installed.
echo.
exit /b 0

REM ---- controller (laptop 1) ---------------------------------
:controller
call :ensure_deps || exit /b 1
echo.
echo   Starting the controller.
echo   Connect to the other laptop on the Connection page, then pick an app.
echo.
%PY% run_controller.py
if errorlevel 1 (
    echo.
    echo   The controller exited with an error.
    pause
)
exit /b 0

REM ---- agent (laptop 2) --------------------------------------
:agent
call :ensure_deps || exit /b 1
set "AGENTNAME=%~2"
if "%AGENTNAME%"=="" if "%~1"=="" (
    echo.
    set /p "AGENTNAME=  Name for this laptop (blank uses %COMPUTERNAME%): "
)
echo.
echo   Starting the agent. Leave this window open.
echo   Press Ctrl+C to stop it.
echo.
if "%AGENTNAME%"=="" (
    %PY% run_agent.py
) else (
    %PY% run_agent.py --name "%AGENTNAME%"
)
if errorlevel 1 (
    echo.
    echo   The agent exited with an error.
    pause
)
exit /b 0

REM ---- link check --------------------------------------------
:check
call :ensure_deps || exit /b 1
echo.
if not "%~2"=="" (
    %PY% check_link.py %~2
) else (
    %PY% check_link.py
    echo.
    echo   To watch for a cable being plugged in:  run.bat check --watch
    echo   To test the other laptop:               run.bat check 169.254.1.5
)
echo.
pause
exit /b 0

REM ---- install -----------------------------------------------
:install
echo.
%PY% -m pip install -r requirements.txt
echo.
pause
exit /b 0
