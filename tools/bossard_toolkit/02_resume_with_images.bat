@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0settings.bat"
"%COLLECTOR_PYTHON%" run_bossard_collector.py --mode resume
set "COLLECTOR_EXIT_CODE=%ERRORLEVEL%"
echo 退出码：%COLLECTOR_EXIT_CODE%。0表示已返回，请继续检查 Excel 采集报告；2通常表示访问受限。
pause
exit /b %COLLECTOR_EXIT_CODE%
