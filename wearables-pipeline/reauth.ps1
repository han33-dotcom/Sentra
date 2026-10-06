# Weekly re-sign-in (Google Testing mode expires access after 7 days).
# Double-click REAUTH.bat. Pick who, tap Allow in the browser, paste the google.com address back.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
$py = Join-Path $here ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Run SETUP_WINDOWS.bat first." }

& $py -m wp accounts
$label = Read-Host "`nWho is signing in? (mohamad / friend1) [mohamad]"
if (-not $label) { $label = "mohamad" }
$link = & $py -m wp link $label
if ($label -eq "mohamad") {
    Start-Process $link
    Write-Host "`nBrowser opened: pick your account -> Continue -> Allow, then copy the whole google.com address." -ForegroundColor Cyan
} else {
    Set-Clipboard $link
    Write-Host "`nLink copied to clipboard. Send it to $label; they tap Allow and send back the google.com address they land on (use it within a few minutes):" -ForegroundColor Cyan
    Write-Host $link
}
$landed = Read-Host "`nPaste the google.com address"
& $py -m wp connect $label --code $landed
if ($LASTEXITCODE -ne 0) { throw "sign-in failed - run again (codes expire after a few minutes)" }
& $py -m wp sync
& $py -m wp accounts
