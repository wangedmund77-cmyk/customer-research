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
  echo 未找到 Python。请安装 Python 3.9 或更高版本，并勾选 Add python.exe to PATH。
  echo 下载地址: https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

set "PYTHONPATH=%CD%\src"
echo 正在以局域网共享模式启动...
echo 本机访问: http://127.0.0.1:8790/
echo 其他电脑访问: http://本机IP:8790/
echo 如 Windows 防火墙提示，请允许 Python 访问网络。
start "" "http://127.0.0.1:8790/"
%PYTHON_CMD% -m switchgear_customer_insight web --host 0.0.0.0 --port 8790

echo.
echo 服务已停止。
pause
