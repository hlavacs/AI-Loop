@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "EMAIL_LAUNCHER=%SCRIPT_DIR%start-ai-loop-with-email.cmd"
set "EMAIL_CONFIG=%SCRIPT_DIR%..\start-ai-loop-with-email.json"

rem Delegate once to the checked-in email launcher when private parent config exists.
if "%AI_LOOP_PARENT_LAUNCHER_ACTIVE%"=="1" goto local_launcher
if "%AI_LOOP_EMAIL_CONFIG%"=="" goto default_email_config
set "EMAIL_CONFIG=%AI_LOOP_EMAIL_CONFIG%"
if not exist "%EMAIL_CONFIG%" (
    echo AI_LOOP_EMAIL_CONFIG points to a missing file: %EMAIL_CONFIG% 1>&2
    exit /b 1
)
goto email_launcher

:default_email_config
if not exist "%EMAIL_CONFIG%" goto local_launcher

:email_launcher
if not exist "%EMAIL_LAUNCHER%" (
    echo AI-Loop email launcher not found at %EMAIL_LAUNCHER% 1>&2
    exit /b 1
)
call "%EMAIL_LAUNCHER%" %*
set "LAUNCHER_ERROR=%ERRORLEVEL%"
exit /b %LAUNCHER_ERROR%

:local_launcher
cd /d "%SCRIPT_DIR%" || exit /b 1

call :choose_python
if errorlevel 1 exit /b 1

"%PYTHON_BIN%" -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo ai-loop GUI: Tkinter is missing for %PYTHON_BIN%. 1>&2
    echo Usual manual fix: install Python with Tcl/Tk support, then verify with: %PYTHON_BIN% -m tkinter 1>&2
    exit /b 1
)

git --version >nul 2>nul
if errorlevel 1 (
    echo ai-loop GUI: Git is missing or not on PATH. 1>&2
    echo Usual manual fix: install Git for Windows, then verify with: git --version 1>&2
    exit /b 1
)

call :check_redis
if errorlevel 1 exit /b 1

"%PYTHON_BIN%" ai_loop_gui.py %*
exit /b %ERRORLEVEL%

:check_redis
redis-server --version >nul 2>nul
if not errorlevel 1 exit /b 0

if /i not "%OS%"=="Windows_NT" (
    echo ai-loop GUI: redis-server is missing or not on PATH. 1>&2
    echo Usual manual fix: install Redis or a Redis-compatible service that provides redis-server, then verify with: redis-server --version 1>&2
    exit /b 1
)

redis-cli ping >nul 2>nul
if not errorlevel 1 exit /b 0

memurai-cli ping >nul 2>nul
if not errorlevel 1 exit /b 0

echo ai-loop GUI: redis-server is missing or not on PATH. 1>&2
echo Windows note: opening the GUI anyway; starting jobs still requires Redis or a compatible service reachable at REDIS_URL. 1>&2
echo Usual manual fix: install Memurai, Docker/WSL Redis, or another Redis-compatible service on localhost:6379. 1>&2
exit /b 0

:choose_python
if not "%AI_LOOP_PYTHON%"=="" (
    call :python_can_run "%AI_LOOP_PYTHON%"
    if errorlevel 1 (
        echo AI_LOOP_PYTHON does not run as Python 3.10 or newer: %AI_LOOP_PYTHON% 1>&2
        exit /b 1
    )
    set "PYTHON_BIN=%AI_LOOP_PYTHON%"
    exit /b 0
)

for %%P in (
    "%SCRIPT_DIR%.venv\Scripts\python.exe"
    "%SCRIPT_DIR%.gui-venv\Scripts\python.exe"
    python3.14
    python3.12
    python3.11
    python3.10
    python
    py
) do (
    call :python_can_run "%%~P"
    if not errorlevel 1 (
        set "PYTHON_BIN=%%~P"
        exit /b 0
    )
)

echo could not find a runnable Python 3.10 or newer interpreter 1>&2
echo Usual manual fix: install Python 3.10 or newer and make it available on PATH. 1>&2
exit /b 1

:python_can_run
set "candidate=%~1"
if "%candidate%"=="" exit /b 1
if exist "%candidate%" goto run_python_candidate
where.exe "%candidate%" >nul 2>nul || exit /b 1

:run_python_candidate
"%candidate%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
exit /b %ERRORLEVEL%
