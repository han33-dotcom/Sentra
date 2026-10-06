@echo off
rem Double-click me. Runs the one-shot setup in a PowerShell window.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows.ps1"
echo.
pause
