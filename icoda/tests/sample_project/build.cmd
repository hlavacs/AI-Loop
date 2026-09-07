@echo off
rem Configure, build and test one preset (default: debug). Usage: build.cmd [debug|release]
setlocal
cd /d "%~dp0"
set "PRESET=%~1"
if "%PRESET%"=="" set "PRESET=debug"
if exist "build\%PRESET%\CMakeCache.txt" (
    findstr /x /c:"CMAKE_HOME_DIRECTORY:INTERNAL=%CD:\=/%" "build\%PRESET%\CMakeCache.txt" >nul || (
        echo build.cmd: build\%PRESET% was configured for another source directory; removing it 1>&2
        rmdir /s /q "build\%PRESET%"
    )
)
cmake --preset %PRESET% || exit /b 1
cmake --build --preset %PRESET% || exit /b 1
ctest --preset %PRESET% || exit /b 1
