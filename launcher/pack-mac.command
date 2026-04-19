#!/bin/bash
# 打包 macOS 版本 (生成 .dmg)
set -e
cd "$(dirname "$0")/.."

echo "============================================"
echo " Packing macOS Installer (.dmg)"
echo "============================================"
echo ""

if [ ! -d "node_modules" ]; then
    npm install
fi

npm run pack:mac

echo ""
echo "[OK] 打包完成，查看 release/ 目录"
open release/ 2>/dev/null || true
