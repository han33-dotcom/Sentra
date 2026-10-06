@echo off
rem Pull the latest code from GitHub (main) and refresh Python packages. Data and secrets are untouched.
cd /d "%~dp0\.."
git pull --ff-only || (echo git pull failed - commit or stash your local changes first & pause & exit /b 1)
cd /d "%~dp0"
.venv\Scripts\python -m pip install -q -r requirements.txt
echo Code is up to date.
pause
