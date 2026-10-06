@echo off
cd /d "%~dp0"
.venv\Scripts\python -m wp process --source live > data\process.log 2>&1
