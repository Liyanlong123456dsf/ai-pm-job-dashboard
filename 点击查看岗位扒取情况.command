#!/bin/bash
# 双击此文件查看最近一次执行状态（横幅通知 + 弹窗 + 浏览器报告）
cd "$(dirname "$0")"

if [ ! -f "run_status.json" ]; then
    osascript -e 'display notification "尚未执行过每日更新" with title "AI 岗位扒取情况" sound name "Basso"'
    osascript -e 'display dialog "尚未执行过每日更新。\n\n请先运行一次：\npython3 scripts/daily_update.py --quick" with title "AI 岗位扒取情况" buttons {"好的"} default button 1 with icon caution'
    exit 0
fi

# 三合一通知：横幅 + 弹窗 + 浏览器报告
python3 -c "
import json, sys
sys.path.insert(0, 'scripts')
from daily_update import _popup_report
s = json.load(open('run_status.json', encoding='utf-8'))
_popup_report(s)
"
