@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 ensure_deps.py
  if errorlevel 1 exit /b 1
  py -3 app.py --no-browser --host 0.0.0.0 --port 8765
) else (
  python ensure_deps.py
  if errorlevel 1 exit /b 1
  python app.py --no-browser --host 0.0.0.0 --port 8765
)
pause
