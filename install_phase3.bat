@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Existing virtual environment not found.
  echo Run install_windows.bat first.
  pause
  exit /b 1
)

echo Installing ChaproNet Dashboard Phase 3...
".venv\Scripts\python.exe" -m pip install -r requirements_phase3.txt
if errorlevel 1 (
  echo Phase 3 installation failed.
  pause
  exit /b 1
)

echo.
echo Phase 3 installation complete.
echo Add the Confluence values to .env, then run run_dashboard.bat.
pause
endlocal
