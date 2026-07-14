@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Existing virtual environment not found.
  echo Run install_windows.bat first.
  pause
  exit /b 1
)

echo Installing ChaproNet Phase 4 AI Intelligence...
".venv\Scripts\python.exe" -m pip install -r requirements_phase4.txt
if errorlevel 1 (
  echo Phase 4 installation failed.
  pause
  exit /b 1
)

echo.
echo Phase 4 installation complete.
echo Add OPENAI_API_KEY to .env, then run run_dashboard.bat.
pause
endlocal
