@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 ensure_deps.py
  if errorlevel 1 exit /b 1
  py -3 app.py
) else (
  python ensure_deps.py
  if errorlevel 1 exit /b 1
  python app.py
)
if errorlevel 1 (
  echo.
  echo 启动失败。请安装 Python 3.10 或更高版本，或检查 8765 端口是否被占用。
  pause
)
