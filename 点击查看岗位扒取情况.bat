@echo off
chcp 65001 >nul
REM 双击此文件查看最近一次执行状态（弹窗 + 浏览器报告）
cd /d "%~dp0"

if not exist "run_status.json" (
    echo 尚未执行过每日更新。
    echo 请先运行一次：python scripts\daily_update.py --quick
    pause
    exit /b 0
)

REM 弹窗通知 + 浏览器报告
python -c "import json, sys; sys.path.insert(0, 'scripts'); from daily_update import _popup_report; s = json.load(open('run_status.json', encoding='utf-8')); _popup_report(s)"
