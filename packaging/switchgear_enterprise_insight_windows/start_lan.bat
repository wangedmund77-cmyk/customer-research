@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON_CMD=py -3"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PYTHON_CMD=python"
  )
)

if "%PYTHON_CMD%"=="" (
  echo Python was not found. Please install Python 3.11 or later and enable Add python.exe to PATH.
  echo https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

set "PYTHONPATH=%CD%\src"
echo Starting LAN shared server...
echo Local URL: http://127.0.0.1:8790/
echo LAN URL: http://YOUR-LAN-IP:8790/
echo Allow Python through Windows Firewall if prompted.
start "" "http://127.0.0.1:8790/"
%PYTHON_CMD% -m switchgear_customer_insight web --host 0.0.0.0 --port 8790

echo.
echo Server stopped.
pause
