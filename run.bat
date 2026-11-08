@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONPATH=%CD%\src;%PYTHONPATH%

if "%~1"=="" (
    python scripts\run_router.py all
) else (
    python scripts\run_router.py %*
)
exit /b %ERRORLEVEL%