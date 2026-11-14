@echo off
rem Registers a daily Windows task that runs run_daily.bat at 18:00 local time.
rem Run this yourself, once, after "autopost.py check" says READY and your first live post looked right.
rem Remove it again with:  schtasks /Delete /TN "NotRealVera autopost" /F
schtasks /Create /TN "NotRealVera autopost" /SC DAILY /ST 18:00 /TR "\"%~dp0run_daily.bat\"" /F
if errorlevel 1 (
    echo Could not create the task.
) else (
    echo Task created. It schedules one approved episode per day. Log: %~dp0logs\autopost.log
)
pause
