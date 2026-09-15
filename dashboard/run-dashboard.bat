@echo off
rem Launches the dashboard and appends its output to run.log. Kept as a
rem separate, argument-free script (rather than inlining the command into
rem the Scheduled Task action) so the task registration never has to deal
rem with nested quoting around the python path and script path - cmd.exe's
rem quote parsing for "/c" with embedded quotes is fragile enough to be
rem worth avoiding entirely rather than getting right by luck.
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if not errorlevel 1 (
    python server.py >> run.log 2>&1
    exit /b %errorlevel%
)

where py >nul 2>nul
if not errorlevel 1 (
    py server.py >> run.log 2>&1
    exit /b %errorlevel%
)

echo %date% %time% - ERROR: no 'python' or 'py' found on PATH >> run.log
exit /b 1
