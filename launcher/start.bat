@echo off
REM ========================================================
REM AI PM Job Dashboard - Windows 开发启动脚本
REM 用法: 双击此文件 (需已安装 Node.js 和 Python 3.10+)
REM ========================================================
chcp 65001 > nul
title AI PM Job Dashboard

cd /d "%~dp0\.."

echo.
echo ============================================
echo  AI PM Job Dashboard - Starting...
echo ============================================
echo.

REM 检查 Node.js
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] 未检测到 Node.js
    echo     请从 https://nodejs.org 下载安装 LTS 版
    echo.
    pause
    exit /b 1
)

REM 检查 Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% neq 0 (
        echo [!] 未检测到 Python，爬取功能将不可用
        echo     请从 https://python.org 下载安装 3.10+
        echo.
    )
)

REM 检查 node_modules
if not exist "node_modules\" (
    echo [*] 首次启动，安装依赖中...
    echo.
    call npm install
    if %errorlevel% neq 0 (
        echo [X] 依赖安装失败
        pause
        exit /b 1
    )
)

REM 检查 Python 依赖
python -c "import DrissionPage" 2>nul
if %errorlevel% neq 0 (
    echo [*] 安装 Python 依赖...
    python -m pip install -r requirements.txt
)

echo.
echo [OK] 启动桌面应用...
echo.
call npm start
