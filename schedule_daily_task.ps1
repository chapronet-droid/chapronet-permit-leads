param(
    [string]$TaskName = "ChaproNet Chicago Permit Leads",
    [string]$RunTime = "7:00AM"
)

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatchFile = Join-Path $ProjectDir "run_daily.bat"
if (-not (Test-Path $BatchFile)) { throw "run_daily.bat was not found at $BatchFile" }

$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$BatchFile`""
$Trigger = New-ScheduledTaskTrigger -Daily -At $RunTime
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Pull, score and export Chicago permit leads for ChaproNet." -Force
Write-Host "Scheduled '$TaskName' to run daily at $RunTime."
Read-Host "Press Enter to close"
