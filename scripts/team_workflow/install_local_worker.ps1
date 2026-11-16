param(
    [string]$WorkerHome = (Join-Path $env:LOCALAPPDATA 'SentraWorker'),
    [string]$Python = 'python',
    [switch]$Start
)
$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$workerRepo = Join-Path $WorkerHome 'repo'
$runtimeRoot = Join-Path $WorkerHome 'runtime'
$workerState = Join-Path $WorkerHome 'state'
New-Item -ItemType Directory -Force -Path $WorkerHome, $runtimeRoot, $workerState | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $workerRepo '.git'))) {
    git clone --branch develop https://github.com/han33-dotcom/Sentra.git $workerRepo
    if ($LASTEXITCODE) { throw 'Could not clone the worker checkout.' }
}
$workerPython = Join-Path $WorkerHome 'venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $workerPython)) {
    & $Python -m venv (Join-Path $WorkerHome 'venv')
    if ($LASTEXITCODE) { throw 'Could not create Python environment.' }
}
& $workerPython -c 'import sys; assert sys.version_info[:2] == (3, 11), "Python 3.11 required"'
if ($LASTEXITCODE) { throw 'Use Python 3.11.' }
& $workerPython -m pip install -r (Join-Path $sourceRoot 'requirements-windows.txt') -r (Join-Path $sourceRoot 'requirements-api.txt') 'streamlit[auth]==1.65.0' 'Authlib==1.8.0' 'pglast>=7,<8' pytest httpx
if ($LASTEXITCODE) { throw 'Dependency installation failed.' }
& $workerPython -m pip install --no-deps -e $workerRepo
if ($LASTEXITCODE) { throw 'Sentra installation failed.' }
& $workerPython -m pip check
if ($LASTEXITCODE) { throw 'Dependency verification failed.' }
New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot 'scripts/team_workflow') | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot '*.py') -Destination (Join-Path $runtimeRoot 'scripts/team_workflow') -Force
$codexExecutable = (Get-Command codex -ErrorAction Stop).Source
# This launcher keeps its trusted coordinator separate from the job checkout.
$settings = @{ python = $workerPython; root = $workerRepo; runtime = $runtimeRoot; state = $workerState; codexDirectory = (Split-Path $codexExecutable) }
$settings | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $WorkerHome 'settings.json') -Encoding utf8
$launcher = @'
$ErrorActionPreference = 'Stop'
$settings = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'settings.json') -Raw | ConvertFrom-Json
$env:PYTHONPATH = $settings.runtime
$env:PATH = $settings.codexDirectory + ';' + $env:PATH
Set-Location -LiteralPath $settings.runtime
& $settings.python -u -m scripts.team_workflow.local_worker --root $settings.root --state-dir $settings.state *>> (Join-Path $settings.state 'worker.log')
'@
$launcherPath = Join-Path $WorkerHome 'run.ps1'
$launcher | Set-Content -LiteralPath $launcherPath -Encoding utf8
$taskName = 'Sentra local delivery'
$arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $launcherPath + '"'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$taskSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $taskSettings -Description 'Sentra local Codex subscription worker. Stop this task to pause delivery.' -Force | Out-Null
if ($Start) { Start-ScheduledTask -TaskName $taskName }
Write-Output "Worker installed at $WorkerHome. Scheduled task: $taskName. Started: $Start"
