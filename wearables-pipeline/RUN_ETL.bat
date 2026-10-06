@echo off
cd /d "%~dp0"
.venv\Scripts\python -m wp etl > data\etl.log 2>&1
