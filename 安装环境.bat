@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY=%%~fD\python.exe"
if not defined PY for /d %%D in ("C:\Program Files\Python3*") do if exist "%%D\python.exe" set "PY=%%~fD\python.exe"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
    echo 没找到 Python。请先安装 Python 3.10 或更高版本，安装时勾选 Add python.exe to PATH。
    pause
    exit /b 1
)
echo 使用解释器：%PY%
"%PY%" -m venv --system-site-packages .venv
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --no-deps rapidocr-onnxruntime tqdm pillow
".venv\Scripts\python.exe" -c "from rapidocr_onnxruntime import RapidOCR" 2>nul
if errorlevel 1 (
    echo 精简安装失败，改为完整安装依赖...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check rapidocr-onnxruntime tqdm pillow
)
".venv\Scripts\python.exe" -c "import tkinter, numpy, cv2, onnxruntime; print('环境就绪')"
pause