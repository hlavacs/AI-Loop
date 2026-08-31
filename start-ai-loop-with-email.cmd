@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%" || exit /b 1

call :choose_python
if errorlevel 1 exit /b 1

"%PYTHON_BIN%" "%SCRIPT_DIR%start_ai_loop_with_email.py" %*
exit /b %ERRORLEVEL%

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
