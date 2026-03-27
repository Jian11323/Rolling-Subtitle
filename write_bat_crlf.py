# -*- coding: utf-8 -*-
"""Write .bat files with CRLF. Run: python write_bat_crlf.py"""
import os
CRLF = "\r\n"
D = os.path.dirname(os.path.abspath(__file__))
os.chdir(D)

onefile_bat = r"""@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "APP_VER=0.0.0"
for /f "delims=" %%i in ('python -c "from config import APP_VERSION; print(APP_VERSION)" 2^>nul') do set "APP_VER=%%i"

echo ========================================
echo 地震预警及情报实况栏 一键打包 - 单文件 exe V!APP_VER!
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python and add it to PATH.
    goto :error_exit
)

python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [WARN] PyInstaller not found. Installing...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller
        goto :error_exit
    )
)

echo [1/5] Checking dependencies...
if exist requirements.txt (
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        python -m pip install PyQt5 websockets requests Pillow
    )
) else (
    python -m pip install PyQt5 websockets requests Pillow
)

echo.
echo [2/5] Cleaning old output (单文件版)...
if exist "单文件版" rmdir /s /q "单文件版"

echo [3/5] Checking resources...
if not exist "fe_fix.txt" echo [WARN] fe_fix.txt not found
if not exist "SA、KMA-EEW-Fe Fix" echo [WARN] SA、KMA-EEW-Fe Fix not found
if not exist "logo\icon.ico" echo [WARN] logo\icon.ico not found

if not exist build mkdir build
if not exist build\build_lite_onefile mkdir build\build_lite_onefile

echo [4/5] Running PyInstaller onefile (output to 单文件版)...
python -m PyInstaller build_lite_onefile.spec --clean --distpath "单文件版"

if errorlevel 1 (
    echo [ERROR] Build failed. Check the output above.
    goto :error_exit
)

echo [5/5] Done.

echo.
echo ========================================
echo Output: 单文件版\地震预警及情报实况栏 V!APP_VER! (单文件).exe
echo ========================================
echo.
pause
exit /b 0

:error_exit
echo.
pause
exit /b 1
"""

onedir_bat = r"""@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "APP_VER=0.0.0"
for /f "delims=" %%i in ('python -c "from config import APP_VERSION; print(APP_VERSION)" 2^>nul') do set "APP_VER=%%i"

echo ========================================
echo 地震预警及情报实况栏 一键打包 V!APP_VER!
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python and add it to PATH.
    goto :error_exit
)

python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [WARN] PyInstaller not found. Installing...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller
        goto :error_exit
    )
)

echo [1/5] Checking dependencies...
if exist requirements.txt (
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        python -m pip install PyQt5 websockets requests Pillow
    )
) else (
    python -m pip install PyQt5 websockets requests Pillow
)

echo.
echo [2/5] Cleaning old output (非压缩版)...
if exist "非压缩版" rmdir /s /q "非压缩版"
if exist "build.spec" del /q "build.spec"

echo [3/5] Checking resources...
if not exist "fe_fix.txt" echo [WARN] fe_fix.txt not found
if not exist "SA、KMA-EEW-Fe Fix" echo [WARN] SA、KMA-EEW-Fe Fix not found
if not exist "logo\icon.ico" echo [WARN] logo\icon.ico not found

if not exist build mkdir build
if not exist build\build_lite mkdir build\build_lite

echo [4/5] Running PyInstaller (output to 非压缩版)...
python -m PyInstaller build_lite.spec --clean --distpath "非压缩版"

if errorlevel 1 (
    echo [ERROR] Build failed. Check the output above.
    goto :error_exit
)

echo [5/5] Done.

echo.
echo ========================================
echo Output: 非压缩版\地震预警及情报实况栏 V!APP_VER!\
echo ========================================
echo.
pause
exit /b 0

:error_exit
echo.
pause
exit /b 1
"""

def to_crlf(s):
    return s.replace("\r\n", "\n").replace("\n", CRLF)

for name, content in [("一键打包-单文件.bat", onefile_bat), ("一键打包.bat", onedir_bat)]:
    path = os.path.join(D, name)
    with open(path, "wb") as f:
        f.write(to_crlf(content).encode("utf-8"))
    print("Written (CRLF):", name)
