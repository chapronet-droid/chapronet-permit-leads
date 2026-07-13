@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found. Run install_windows.bat first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" "src\permit_leads.py" --config "config.yaml"
if errorlevel 1 (
  echo.
  echo The lead job failed. Review the error above.
  pause
  exit /b 1
)

echo.
echo Reports created in: %CD%\output
endlocal
