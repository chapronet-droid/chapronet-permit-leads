@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Existing virtual environment not found.
  echo Run install_windows.bat first.
  pause
  exit /b 1
)

echo Installing ChaproNet Dashboard Phase 2...
".venv\Scripts\python.exe" -m pip install -r requirements_phase2.txt
if errorlevel 1 (
  echo Phase 2 installation failed.
  pause
  exit /b 1
)

echo.
echo Phase 2 installation complete.
echo Close any currently running dashboard window, then run run_dashboard.bat.
pause
endlocal
