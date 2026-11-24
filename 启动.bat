@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo 首次运行，正在准备运行环境，需要联网、约 1 分钟...
    call "安装环境.bat"
)
if not exist ".venv\Scripts\pythonw.exe" (
    echo 环境没装好，请看上面的提示。
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "main.py"