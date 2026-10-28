@echo off
REM Windows: runs the screener with Moomoo OpenD data. Schedule it with Task Scheduler (see README).
REM OpenD must already be running and logged in.
cd /d "%~dp0\.."
call .venv\Scripts\activate.bat
if not exist logs mkdir logs
set DATA_SOURCE=moomoo
python screener.py >> logs\screener.log 2>&1
