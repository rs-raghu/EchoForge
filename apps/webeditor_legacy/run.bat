@echo off
setlocal
cd /d "%~dp0"

set "ECHOFORGE_ROOT=%~dp0..\.."
set "ECHOFORGE_PROJECTS_ROOT=%ECHOFORGE_ROOT%\projects"
set "ECHOFORGE_FONTS_DIR=%ECHOFORGE_ROOT%\assets\fonts"
set "ECHOFORGE_DEFAULT_LYRIC_FONT_SIZE=50"

echo =========================================
echo EchoForge WebEditor - Legacy UI Revived
echo =========================================
echo EF root: %ECHOFORGE_ROOT%
echo Projects: %ECHOFORGE_PROJECTS_ROOT%
echo.

if not exist backend\.venv (
  echo Creating Python virtual environment...
  py -3 -m venv backend\.venv
  if errorlevel 1 python -m venv backend\.venv
)

echo Installing backend requirements...
call backend\.venv\Scripts\python.exe -m pip install --upgrade pip
call backend\.venv\Scripts\pip.exe install -r backend\requirements.txt

echo Starting backend on http://127.0.0.1:8765 ...
start "EchoForge Legacy WebEditor Backend" cmd /k "cd /d %~dp0backend && set ECHOFORGE_ROOT=%ECHOFORGE_ROOT%&& set ECHOFORGE_PROJECTS_ROOT=%ECHOFORGE_PROJECTS_ROOT%&& set ECHOFORGE_FONTS_DIR=%ECHOFORGE_FONTS_DIR%&& .venv\Scripts\python.exe main.py"

echo.
echo Installing frontend packages if needed...
cd frontend
if not exist node_modules (
  call npm install
)

echo Starting frontend on http://localhost:5173 ...
start "EchoForge Legacy WebEditor Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

timeout /t 4 >nul
start "" "http://localhost:5173"

echo.
echo WebEditor is opening in your browser.
echo Keep the backend and frontend command windows open while editing.
echo.
pause
