#!/bin/bash
# ========================================================
# AI PM Job Dashboard - macOS 开发启动脚本
# 用法: 双击此文件 (需已安装 Node.js 和 Python 3.10+)
# ========================================================
set -e

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

echo ""
echo "============================================"
echo " AI PM Job Dashboard - Starting..."
echo "============================================"
echo ""

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo "[X] 未检测到 Node.js"
    echo "    请从 https://nodejs.org 下载安装 LTS 版，或运行:"
    echo "    brew install node"
    echo ""
    read -p "按任意键关闭..." -n 1
    exit 1
fi

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[!] 未检测到 Python3，爬取功能将不可用"
    echo "    请从 https://python.org 下载安装 3.10+，或运行:"
    echo "    brew install python"
    echo ""
fi

# 首次启动: npm install
if [ ! -d "node_modules" ]; then
    echo "[*] 首次启动，安装依赖中..."
    npm install
fi

# 检查 Python 依赖
if command -v python3 &> /dev/null; then
    if ! python3 -c "import DrissionPage" 2>/dev/null; then
        echo "[*] 安装 Python 依赖..."
        python3 -m pip install -r requirements.txt
    fi
fi

echo ""
echo "[OK] 启动桌面应用..."
echo ""
npm start
