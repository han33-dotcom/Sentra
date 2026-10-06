# One-shot setup on Windows. Run from this folder in PowerShell:
#     powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
# Safe to re-run: every step skips itself if already done.

param(
    [string]$MyEmail = $env:WP_MY_EMAIL,          # your Google account (pre-selected on the consent page)
    [string]$FriendEmail = $env:WP_FRIEND_EMAIL   # second account to invite, optional
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
$py  = Join-Path $here ".venv\Scripts\python.exe"
$pyw = Join-Path $here ".venv\Scripts\pythonw.exe"

Write-Host "`n[1/6] Python environment" -ForegroundColor Cyan
if (-not (Test-Path $py)) {
    # needs Python 3.10+; prefer the py launcher, fall back to python on PATH
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv } else { python -m venv .venv }
}
& $py -c "import sys; assert sys.version_info >= (3, 10), sys.version; print('Python', sys.version.split()[0])"
if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ needed. Delete .venv, install Python 3.12, re-run." }
& $py -m pip install -q --upgrade pip
& $py -m pip install -q -r requirements.txt

Write-Host "`n[2/6] OAuth client" -ForegroundColor Cyan
if (-not (Test-Path "secrets\client_secret.json")) {
    New-Item -ItemType Directory -Force secrets | Out-Null
    Copy-Item "$env:USERPROFILE\Desktop\fitbit\credentials.json" "secrets\client_secret.json"
}

Write-Host "`n[3/6] Import the history you already pulled (Aug 6 - Sep 27)" -ForegroundColor Cyan
if (-not (Test-Path "data\wearables.db")) {
    & $py -m wp import-export "$env:USERPROFILE\Desktop\fitbit" mohamad
}

if (-not $MyEmail) { $MyEmail = Read-Host "Your Google account email" }
Write-Host "`n[4/6] Sign in: mohamad ($MyEmail)" -ForegroundColor Cyan
Write-Host "A browser tab opens. Pick $MyEmail -> 'Continue' on the unverified-app screen -> Allow."
Write-Host "You land on google.com. Copy the WHOLE address bar and paste it here within a few minutes."
$link = & $py -m wp link mohamad --email $MyEmail
Start-Process $link
$landed = Read-Host "Paste the google.com address"
& $py -m wp connect mohamad --code $landed --email $MyEmail
if ($LASTEXITCODE -ne 0) { throw "sign-in failed - re-run this script" }

Write-Host "`n[5/6] First sync (pulls ~60 days incl. second-by-second heart rate; can take 15-30 min)" -ForegroundColor Cyan
$env:WP_BACKFILL_DAYS = "60"
& $py -m wp sync
Remove-Item Env:\WP_BACKFILL_DAYS
& $py -m wp accounts

Write-Host "`n[6/6] Hourly background sync + sign-in reminders" -ForegroundColor Cyan
schtasks /Change /TN FitbitHealthSync /DISABLE 2>$null | Out-Null   # old Desktop\fitbit job
$action   = New-ScheduledTaskAction -Execute $pyw -Argument "`"$here\run_sync.py`"" -WorkingDirectory $here
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName FYPWearablesSync -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Task FYPWearablesSync runs every hour. Log: data\logs\sync.log"

if ($FriendEmail) {
Write-Host "`nFriend: once their Gmail is a test user, send them this link:" -ForegroundColor Yellow
& $py -m wp link friend1 --email $FriendEmail
}
Write-Host "When he sends back the google.com address, run:"
Write-Host "  double-click REAUTH.bat -> type friend1 -> paste his address" -ForegroundColor Yellow
Write-Host "`nFrom now on: a Windows notification appears ~2 days before anyone's sign-in expires. Double-click REAUTH.bat." -ForegroundColor Green
