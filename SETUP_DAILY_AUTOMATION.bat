@echo off
cd /d "%~dp0"
echo This will schedule ChaproNet Permit Leads every day at 7:00 AM.
echo Windows may ask for Administrator permission.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0schedule_daily_task.ps1" -RunTime "7:00AM"
if errorlevel 1 (
  echo.
  echo Scheduling failed. Right-click this file and choose Run as administrator.
  pause
)
