@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONPATH=%CD%\src;%PYTHONPATH%

python -m echoforge.main %*
exit /b %ERRORLEVEL%