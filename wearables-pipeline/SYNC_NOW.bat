@echo off
cd /d "%~dp0"
.venv\Scripts\python -m wp sync > data\sync_now.log 2>&1
.venv\Scripts\python -m wp accounts >> data\sync_now.log 2>&1
