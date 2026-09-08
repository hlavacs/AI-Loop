@echo off
setlocal EnableExtensions
rem ICODA launcher for Windows: checks Python and Tkinter, keeps .icoda-venv current, starts icoda.py.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%" || exit /b 1
set "VENV_PY=%SCRIPT_DIR%.icoda-venv\Scripts\python.exe"
set "STAMP=%SCRIPT_DIR%.icoda-venv\.installed-from"

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
echo icoda: no Python 3.10+ found. Install it from python.org with the tcl/tk option. 1>&2
exit /b 1

:have_python
%PYTHON_BIN% -c "import tkinter" >nul 2>nul || (
    echo icoda: Tkinter is missing for %PYTHON_BIN%. Reinstall Python with the tcl/tk option. 1>&2
    exit /b 1
)
where git >nul 2>nul || (
    echo icoda: git is required ^(winget install Git.Git^). 1>&2
    exit /b 1
)
where cmake >nul 2>nul || echo icoda: cmake not found ^(winget install Kitware.CMake^); building projects will not work. 1>&2
where ninja >nul 2>nul || echo icoda: ninja not found ^(winget install Ninja-build.Ninja^); building projects will not work. 1>&2
where clang-cl >nul 2>nul || echo icoda: clang-cl not found; install the "C++ Clang tools for Windows" component of Visual Studio. 1>&2
if "%VCPKG_ROOT%"=="" echo icoda: VCPKG_ROOT is not set; library installation will be unavailable. 1>&2

if not exist "%VENV_PY%" (
    echo icoda: creating virtual environment .icoda-venv 1>&2
    %PYTHON_BIN% -m venv "%SCRIPT_DIR%.icoda-venv" || exit /b 1
)
set "NEED_INSTALL=0"
if not exist "%STAMP%" set "NEED_INSTALL=1"
if exist "%STAMP%" for /f %%A in ('powershell -NoProfile -Command "if ((Get-Item pyproject.toml).LastWriteTime -gt (Get-Item '%STAMP%').LastWriteTime) { 1 } else { 0 }"') do set "NEED_INSTALL=%%A"
if "%NEED_INSTALL%"=="1" (
    echo icoda: installing Python dependencies 1>&2
    "%VENV_PY%" -m pip install --quiet --upgrade pip || exit /b 1
    "%VENV_PY%" -m pip uninstall --quiet --yes libclang >nul 2>nul
    "%VENV_PY%" -m pip install --quiet -e . || exit /b 1
    echo installed > "%STAMP%"
)
"%VENV_PY%" icoda.py %*
exit /b %ERRORLEVEL%
