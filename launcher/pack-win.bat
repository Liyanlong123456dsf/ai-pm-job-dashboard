@echo off
REM 打包 Windows 版本 (生成 .exe)
chcp 65001 > nul
cd /d "%~dp0\.."

echo ============================================
echo  Packing Windows Installer (.exe)
echo ============================================
echo.

if not exist "node_modules\" (
    call npm install
)

call npm run pack:win
if %errorlevel% neq 0 (
    echo [X] 打包失败
    pause
    exit /b 1
)

echo.
echo [OK] 打包完成，查看 release\ 目录
start "" "release"
pause
