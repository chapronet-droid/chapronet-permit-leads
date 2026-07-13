@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found. Run install_windows.bat first.
  pause
  exit /b 1
)

echo Starting ChaproNet Lead Intelligence...
echo Your browser should open automatically.
echo Keep this window open while using the dashboard.
echo.
".venv\Scripts\python.exe" -m streamlit run "src\dashboard.py" --server.address localhost --server.port 8501
endlocal
