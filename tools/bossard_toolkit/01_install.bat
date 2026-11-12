@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0settings.bat"
"%COLLECTOR_PYTHON%" --version
if errorlevel 1 goto failed
"%COLLECTOR_PYTHON%" -m pip install -r collector_requirements.txt
if errorlevel 1 goto failed
"%COLLECTOR_PYTHON%" -m playwright install chromium
if errorlevel 1 goto failed
echo 安装完成。下一步运行 03_images_only.bat，或 02_resume_with_images.bat。
pause
exit /b 0
:failed
echo 安装失败。请检查 settings.bat 的 Python 路径、Python版本和网络，然后查看上面的报错。
pause
exit /b 1
