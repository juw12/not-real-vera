@echo off
rem Schedules the next approved episode to YouTube, Instagram and TikTok through Buffer.
rem Sends nothing unless: the episode is approved, its video link is public, and all three channels are connected.
rem The Buffer key is read from BUFFER_API_KEY or %USERPROFILE%\.notrealvera\buffer_key.txt.
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
set PYTHONIOENCODING=utf-8
if "%NRV_PYTHON%"=="" set NRV_PYTHON=python
echo ==== %date% %time% ==== >> logs\autopost.log
"%NRV_PYTHON%" pipeline\autopost.py post --live --count 1 >> logs\autopost.log 2>&1
echo exit %errorlevel% >> logs\autopost.log
endlocal
