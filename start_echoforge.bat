@echo off
title EchoForge - Run All
cd /d "D:\Hello World\Automations\EchoForge"

echo ==========================================
echo        EchoForge - Full Workflow
echo ==========================================
echo.

call run.bat all

echo.
echo ==========================================
echo EchoForge stopped or finished.
echo Press any key to close this window.
echo ==========================================
pause >nul