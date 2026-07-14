@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Existing virtual environment not found.
  echo Run install_windows.bat first.
  pause
  exit /b 1
)

echo Installing ChaproNet Phase 5 Step 1 - Company Research Engine...
".venv\Scripts\python.exe" -m pip install -r requirements_phase5.txt
if errorlevel 1 (
  echo Phase 5 installation failed.
  pause
  exit /b 1
)

echo Checking Python files...
".venv\Scripts\python.exe" -m py_compile src\ai_intelligence.py
if errorlevel 1 (
  echo ai_intelligence.py has a syntax error.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m py_compile src\company_research.py
if errorlevel 1 (
  echo company_research.py has a syntax error.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m py_compile src\dashboard.py
if errorlevel 1 (
  echo dashboard.py has a syntax error.
  pause
  exit /b 1
)

echo.
echo Phase 5 Step 1 installation complete.
echo Run run_dashboard.bat and open a permit.
pause
endlocal
