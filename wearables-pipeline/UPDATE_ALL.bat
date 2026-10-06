@echo off
rem Sync everyone, then rebuild processed outputs + etl (forced, even if nothing changed).
cd /d "%~dp0"
echo running sync, analysis and etl...
.venv\Scripts\python -m wp update --force > data\update_all.log 2>&1
echo DONE >> data\update_all.log
