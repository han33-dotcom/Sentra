@echo off
rem Double-click when a sign-in reminder pops up.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0reauth.ps1"
echo.
pause
