@echo off
REM AI Update Monitor - Scheduled execution script
REM Runs the monitor once with fallback mode enabled

cd /d "C:\Users\longs\Projects\tools\ai-update-monitor"

REM Create logs directory if not exists
if not exist "logs" mkdir "logs"

REM Generate timestamped log filename
for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set DATESTAMP=%%a%%b%%c
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set TIMESTAMP=%%a%%b

REM Run the monitor and append output to log
"C:\Users\longs\AppData\Local\Programs\Python\Python313\python.exe" -m app --fallback >> "logs\monitor_%DATESTAMP%.log" 2>&1

REM Keep only last 7 days of logs
forfiles /P "logs" /M "monitor_*.log" /D -7 /C "cmd /c del @path" 2>nul

exit /b 0
