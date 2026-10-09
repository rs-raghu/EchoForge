@echo off
title EchoForge - Run All
cd /d "%~dp0"

echo ==========================================
echo        EchoForge - Full Workflow
echo ==========================================
echo.

call "%~dp0run.bat" all

echo.
echo ==========================================
echo EchoForge stopped or finished.
echo Press any key to close this window.
echo ==========================================
pause >nul