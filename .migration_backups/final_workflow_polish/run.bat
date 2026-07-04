@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
python scripts\echoforge_router.py %*
exit /b %ERRORLEVEL%
