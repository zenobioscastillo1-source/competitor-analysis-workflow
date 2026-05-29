@echo off
REM Weekly competitor watch. Register this as a scheduled task (see the workflow
REM doc), or double-click to run on demand. Re-scrapes the watchlist, logs
REM meaningful changes to the tracker Sheet's "Changes" tab, advances baselines.
REM Set YOUR_SPREADSHEET_ID below to the id printed by:
REM   python tools/push_to_google_sheet.py --create "Competitor Tracker" ...
cd /d "%~dp0.."
echo ===== %date% %time% =====>> monitor\monitor.log
".venv\Scripts\python.exe" tools\monitor_competitors.py --watchlist monitor\watchlist.json --spreadsheet-id YOUR_SPREADSHEET_ID --sheet Changes>> monitor\monitor.log 2>&1
