@echo off
rem Run ICODA's complete verification gate and retain its evidence.
setlocal
cd /d "%~dp0"
set "PYTHON=.icoda-venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo verify: run icoda.cmd once to create .icoda-venv 1>&2
    exit /b 1
)
"%PYTHON%" -c "import coverage, PIL, pytest" >nul 2>nul || (
    echo verify: install development tools with .icoda-venv\Scripts\python.exe -m pip install -e ".[dev]" 1>&2
    exit /b 1
)
"%PYTHON%" tests\verify.py %*
exit /b %ERRORLEVEL%
