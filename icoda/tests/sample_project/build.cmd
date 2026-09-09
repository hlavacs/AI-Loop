@echo off
rem Configure/build and normally test one preset. Usage: build.cmd [debug|release] [build-only]
setlocal
cd /d "%~dp0"
set "PRESET=%~1"
if "%PRESET%"=="" set "PRESET=debug"
set "MODE=%~2"
if exist "build\%PRESET%\CMakeCache.txt" (
    findstr /x /c:"CMAKE_HOME_DIRECTORY:INTERNAL=%CD:\=/%" "build\%PRESET%\CMakeCache.txt" >nul || (
        echo build.cmd: build\%PRESET% was configured for another source directory; removing it 1>&2
        rmdir /s /q "build\%PRESET%"
    )
)
cmake --preset %PRESET% || exit /b 1
cmake --build --preset %PRESET% || exit /b 1
if /i "%MODE%"=="build-only" exit /b 0
ctest --preset %PRESET% || exit /b 1
