@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Existing virtual environment not found.
  echo Run install_windows.bat first.
  pause
  exit /b 1
)

echo Installing the ChaproNet dashboard...
".venv\Scripts\python.exe" -m pip install -r requirements_dashboard.txt
if errorlevel 1 (
  echo Dashboard installation failed.
  pause
  exit /b 1
)

echo.
echo Dashboard installation complete.
echo Double-click run_dashboard.bat to open it.
pause
endlocal
