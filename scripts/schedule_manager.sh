#!/bin/bash
# AI 岗位爬取 — 定时任务管理器（一体化版）
# 用法:
#   bash schedule_manager.sh install   # 安装定时任务（22:00 一体化流程）
#   bash schedule_manager.sh uninstall # 卸载定时任务
#   bash schedule_manager.sh status    # 查看状态
#   bash schedule_manager.sh test      # 立即测试运行
#
# 流程: 22:00 登录检查 → caffeinate 防息屏 → 00:00 爬取 → 完成后终止 caffeinate
# 轮换: 全量 → 快速 → 快速 → 循环

AGENT_DIR="$HOME/Library/LaunchAgents"
DAILY_PLIST="com.aipm.autodaily"
PROJECT_DIR="$HOME/Desktop/工作集合表"

case "$1" in
    install)
        echo "📦 安装定时任务..."
        # 清理旧的 logincheck plist（已合并到 autodaily）
        launchctl unload "$AGENT_DIR/com.aipm.logincheck.plist" 2>/dev/null
        rm -f "$AGENT_DIR/com.aipm.logincheck.plist"
        # 确保 plist 权限正确
        chmod 644 "$AGENT_DIR/$DAILY_PLIST.plist"
        # 加载
        launchctl unload "$AGENT_DIR/$DAILY_PLIST.plist" 2>/dev/null
        launchctl load "$AGENT_DIR/$DAILY_PLIST.plist"
        echo "✅ 已安装:"
        echo "   • 22:00 一体化流程 ($DAILY_PLIST)"
        echo "     → 22:00 登录检查"
        echo "     → caffeinate 防息屏"
        echo "     → 00:00 开始爬取"
        echo "     → 完成后终止 caffeinate"
        echo ""
        echo "查看状态: bash $0 status"
        ;;
    uninstall)
        echo "🗑  卸载定时任务..."
        launchctl unload "$AGENT_DIR/$DAILY_PLIST.plist" 2>/dev/null
        launchctl unload "$AGENT_DIR/com.aipm.logincheck.plist" 2>/dev/null
        echo "✅ 已卸载所有定时任务"
        ;;
    status)
        echo "📋 定时任务状态:"
        echo ""
        echo "--- 22:00 一体化流程 ---"
        launchctl list | grep "$DAILY_PLIST" && echo "  ✅ 已加载" || echo "  ❌ 未加载"
        echo ""
        # caffeinate 状态
        if pgrep -x caffeinate > /dev/null; then
            echo "--- caffeinate ---"
            echo "  ☕ 正在运行（防息屏激活中）"
            echo ""
        fi
        # 轮换策略
        ROTATION="$PROJECT_DIR/logs/rotation_index.json"
        if [ -f "$ROTATION" ]; then
            echo "--- 轮换策略 ---"
            python3 -c "
import json
d = json.load(open('$ROTATION'))
print(f'  策略: {d.get(\"rotation\",[])}')
print(f'  上次: {d.get(\"last_date\",\"\")} → {d.get(\"last_mode\",\"\")}')
next_idx = d.get('index', 0)
rotation = d.get('rotation', ['full','quick','quick'])
print(f'  下次: → {rotation[next_idx % len(rotation)]}')
" 2>/dev/null
            echo ""
        fi
        # 最近执行记录
        RECORD="$PROJECT_DIR/logs/auto_daily_record.json"
        if [ -f "$RECORD" ]; then
            echo "--- 最近执行记录 ---"
            python3 -c "
import json
records = json.load(open('$RECORD'))
for r in records[-5:]:
    s = '✅' if r['success'] else '❌'
    d = r['duration_sec'] // 60
    mode = r.get('mode', '?')
    print(f'  {s} {r[\"executed_at\"]} [{mode}] ({d}分钟) {r.get(\"error\",\"\")[:50]}')
" 2>/dev/null
            echo ""
        fi
        # 登录状态
        LOGIN="$PROJECT_DIR/logs/login_status.json"
        if [ -f "$LOGIN" ]; then
            echo "--- 登录状态 ---"
            python3 -c "
import json
d = json.load(open('$LOGIN'))
s = '✅ 已登录' if d['logged_in'] else '❌ 未登录'
print(f'  {s} ({d[\"checked_at\"]}) {d[\"detail\"]}')
" 2>/dev/null
        fi
        ;;
    test)
        echo "🧪 测试运行一体化流程..."
        echo "⚠️  这会执行完整流程（登录检查 + 等待 + 爬取），确定吗？"
        echo "   如果只想测试登录: python3 $PROJECT_DIR/scripts/login_check.py"
        echo "   如果只想测试爬取: python3 $PROJECT_DIR/scripts/daily_update.py --quick --dry-run"
        echo ""
        read -p "输入 y 继续: " confirm
        if [ "$confirm" = "y" ]; then
            python3 "$PROJECT_DIR/scripts/auto_daily.py"
        fi
        ;;
    *)
        echo "用法: bash $0 {install|uninstall|status|test}"
        echo ""
        echo "  install   - 安装 22:00 一体化定时任务"
        echo "  uninstall - 卸载定时任务"
        echo "  status    - 查看当前状态、轮换策略、执行记录"
        echo "  test      - 测试运行完整流程"
        ;;
esac
