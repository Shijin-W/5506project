@echo off
setlocal
cd /d "%~dp0"

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8088 .*LISTENING"') do (
  taskkill /F /PID %%P >nul 2>nul
)

start "MultiCat Frontend Server" /min python -m http.server 8088 --bind 127.0.0.1
timeout /t 1 /nobreak >nul
start "" "http://127.0.0.1:8088/index.html?v=20260518-local-refresh"
endlocal
