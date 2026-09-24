@echo off
setlocal EnableExtensions
rem ICODA launcher for Windows: checks Python, Tkinter, and the prepared environment, then starts icoda.py.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%" || exit /b 1
set "VENV_PY=%SCRIPT_DIR%.icoda-venv\Scripts\python.exe"

if not "%ICODA_PYTHON%"=="" (
    set "PYTHON_BIN=%ICODA_PYTHON%"
    goto have_python
)
for %%V in (3.14 3.13 3.12 3.11 3.10) do (
    py -%%V -c "import sys" >nul 2>nul && (
        set "PYTHON_BIN=py -%%V"
        goto have_python
    )
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && (
    set "PYTHON_BIN=python"
    goto have_python
)
echo icoda: no Python 3.10+ found. Run: winget install --id Python.Python.3.12 -e 1>&2
exit /b 1

:have_python
%PYTHON_BIN% -c "import tkinter" >nul 2>nul || (
    echo icoda: Tkinter is missing for %PYTHON_BIN%. 1>&2
    echo icoda: run: winget install --id Python.Python.3.12 -e 1>&2
    exit /b 1
)
where git >nul 2>nul || (
    echo icoda: git is required. Run: winget install --id Git.Git -e 1>&2
    exit /b 1
)
rem icoda.py initializes the Visual Studio environment before checking the build tools.

if not exist "%VENV_PY%" (
    echo icoda: .icoda-venv is missing. Run these commands from %SCRIPT_DIR%: 1>&2
    echo   %PYTHON_BIN% -m venv .icoda-venv 1>&2
    echo   .icoda-venv\Scripts\python.exe -m pip install -e ".[dev]" -c constraints.txt 1>&2
    exit /b 1
)
"%VENV_PY%" -c "from importlib.metadata import version; version('icoda'); import clang.cindex, jsonschema, networkx" >nul 2>nul || (
    echo icoda: the ICODA environment is incomplete. Run this command from %SCRIPT_DIR%: 1>&2
    echo   .icoda-venv\Scripts\python.exe -m pip install -e ".[dev]" -c constraints.txt 1>&2
    exit /b 1
)
"%VENV_PY%" icoda.py %*
exit /b %ERRORLEVEL%
