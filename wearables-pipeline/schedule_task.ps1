$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyw = Join-Path $here ".venv\Scripts\pythonw.exe"
schtasks /Change /TN FitbitHealthSync /DISABLE 2>$null | Out-Null
$action   = New-ScheduledTaskAction -Execute $pyw -Argument "`"$here\run_sync.py`"" -WorkingDirectory $here
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(45) -RepetitionInterval (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName FYPWearablesSync -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Get-ScheduledTask -TaskName FYPWearablesSync | Get-ScheduledTaskInfo | Format-List TaskName,NextRunTime | Out-File -Encoding utf8 (Join-Path $here "data\schedule.log")
(Get-ScheduledTask -TaskName FitbitHealthSync -ErrorAction SilentlyContinue).State | Out-File -Append -Encoding utf8 (Join-Path $here "data\schedule.log")
