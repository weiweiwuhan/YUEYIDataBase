@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0settings.bat"
"%COLLECTOR_PYTHON%" run_bossard_collector.py --mode resume
set "COLLECTOR_EXIT_CODE=%ERRORLEVEL%"
echo 退出码：%COLLECTOR_EXIT_CODE%。0表示正常返回，请检查采集报告；1表示采集执行失败；2表示访问受限或参数错误。
pause
exit /b %COLLECTOR_EXIT_CODE%
