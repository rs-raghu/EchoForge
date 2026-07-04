@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
python scripts\echoforge_router.py %*
exit /b %ERRORLEVEL%
