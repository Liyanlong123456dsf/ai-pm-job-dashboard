#!/bin/bash
# AI 岗位爬取 — 定时任务管理器
# 用法:
#   bash schedule_manager.sh install   # 安装定时任务
#   bash schedule_manager.sh uninstall # 卸载定时任务
#   bash schedule_manager.sh status    # 查看状态
#   bash schedule_manager.sh test      # 立即测试运行

AGENT_DIR="$HOME/Library/LaunchAgents"
LOGIN_PLIST="com.aipm.logincheck"
DAILY_PLIST="com.aipm.autodaily"

case "$1" in
    install)
        echo "📦 安装定时任务..."
        # 确保 plist 权限正确
        chmod 644 "$AGENT_DIR/$LOGIN_PLIST.plist"
        chmod 644 "$AGENT_DIR/$DAILY_PLIST.plist"
        # 加载
        launchctl unload "$AGENT_DIR/$LOGIN_PLIST.plist" 2>/dev/null
        launchctl unload "$AGENT_DIR/$DAILY_PLIST.plist" 2>/dev/null
        launchctl load "$AGENT_DIR/$LOGIN_PLIST.plist"
        launchctl load "$AGENT_DIR/$DAILY_PLIST.plist"
        echo "✅ 已安装:"
        echo "   • 22:00 登录检查 ($LOGIN_PLIST)"
        echo "   • 03:00 自动爬取 ($DAILY_PLIST)"
        echo ""
        echo "查看状态: bash $0 status"
        ;;
    uninstall)
        echo "🗑  卸载定时任务..."
        launchctl unload "$AGENT_DIR/$LOGIN_PLIST.plist" 2>/dev/null
        launchctl unload "$AGENT_DIR/$DAILY_PLIST.plist" 2>/dev/null
        echo "✅ 已卸载所有定时任务"
        ;;
    status)
        echo "📋 定时任务状态:"
        echo ""
        echo "--- 22:00 登录检查 ---"
        launchctl list | grep "$LOGIN_PLIST" && echo "  ✅ 已加载" || echo "  ❌ 未加载"
        echo ""
        echo "--- 03:00 自动爬取 ---"
        launchctl list | grep "$DAILY_PLIST" && echo "  ✅ 已加载" || echo "  ❌ 未加载"
        echo ""
        # 最近执行记录
        RECORD="$HOME/Desktop/工作集合表/logs/auto_daily_record.json"
        if [ -f "$RECORD" ]; then
            echo "--- 最近执行记录 ---"
            python3 -c "
import json
records = json.load(open('$RECORD'))
for r in records[-5:]:
    s = '✅' if r['success'] else '❌'
    d = r['duration_sec'] // 60
    print(f'  {s} {r[\"executed_at\"]} ({d}分钟) {r.get(\"error\",\"\")[:50]}')
" 2>/dev/null
        fi
        # 登录状态
        LOGIN="$HOME/Desktop/工作集合表/logs/login_status.json"
        if [ -f "$LOGIN" ]; then
            echo ""
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
        echo "🧪 测试运行登录检查..."
        python3 "$HOME/Desktop/工作集合表/scripts/login_check.py"
        ;;
    *)
        echo "用法: bash $0 {install|uninstall|status|test}"
        echo ""
        echo "  install   - 安装 22:00 + 03:00 定时任务"
        echo "  uninstall - 卸载所有定时任务"
        echo "  status    - 查看当前状态和执行记录"
        echo "  test      - 立即测试运行登录检查"
        ;;
esac
