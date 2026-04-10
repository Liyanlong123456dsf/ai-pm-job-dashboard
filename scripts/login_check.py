#!/usr/bin/env python3
"""
每晚 22:00 自动运行 — 检查 BOSS 直聘登录状态
- 启动 Chrome（持久化 Profile）
- 访问 BOSS 直聘，检测是否已登录
- 弹窗告知用户状态：
  ✅ 已登录 → 显示确认，无需操作
  ❌ 未登录 → 把 Chrome 带到前台，弹窗引导登录
- 写入 login_status.json 供凌晨 3 点脚本检查
"""
import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
PROFILE_DIR = BASE_DIR / '.chrome_profile'
STATUS_FILE = BASE_DIR / 'logs' / 'login_status.json'
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# 简单日志
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [login_check] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'login_check.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('login_check')


def save_status(logged_in: bool, detail: str = ''):
    """保存登录状态到 JSON"""
    data = {
        'checked_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'logged_in': logged_in,
        'detail': detail,
    }
    STATUS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info(f'登录状态已保存: {"✅ 已登录" if logged_in else "❌ 未登录"} — {detail}')


def notify(title, msg):
    """macOS 原生通知"""
    try:
        subprocess.run(['osascript', '-e',
            f'display notification "{msg}" with title "{title}" sound name "Glass"'], timeout=5)
    except Exception:
        pass


def check_login():
    """启动浏览器，检测登录状态"""
    logger.info('=' * 40)
    logger.info('开始登录状态检查')

    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from spiders.boss_dp import BossDPSpider

        spider = BossDPSpider()
        spider.start_browser(headless=False)
        page = spider.page

        # 访问 BOSS 直聘
        test_url = 'https://www.zhipin.com/web/geek/job?query=AI产品经理&city=101010100'
        page.get(test_url)
        time.sleep(5)

        # 检测登录
        logged_in = False
        for attempt in range(6):
            try:
                has_jobs = page.run_js(
                    'return document.querySelectorAll("li[class*=job-card]").length > 0'
                )
                if has_jobs:
                    logged_in = True
                    break
                is_verify = page.run_js(
                    'return document.title.includes("安全") || document.title.includes("验证")'
                )
                if is_verify:
                    logger.info(f'安全验证页面，等待... ({attempt+1}/6)')
            except Exception:
                pass
            time.sleep(3)

        if logged_in:
            # ✅ 已登录
            save_status(True, '检测到岗位列表，Cookie 有效')
            notify('AI 岗位爬取 ✅', '登录状态正常，凌晨 3 点将自动执行')
            # 弹窗确认（不阻塞太久）
            subprocess.run(['osascript', '-e',
                'display dialog "✅ BOSS 直聘登录状态正常\n\n'
                'Cookie 有效，凌晨 3:00 将自动执行每日爬取。\n'
                '无需任何操作，安心睡觉即可 😴" '
                'with title "AI 岗位爬取 — 登录检查" '
                'buttons {"好的"} default button 1 with icon note '
                'giving up after 60'], timeout=120)
            logger.info('✅ 登录正常，用户已确认')
        else:
            # ❌ 未登录 — 引导用户登录
            save_status(False, '未检测到岗位列表，需要登录')
            notify('AI 岗位爬取 ⚠️', '需要登录 BOSS 直聘！请在 Chrome 中登录')
            # 把 Chrome 带到前台
            subprocess.run(['osascript', '-e',
                'tell application "Google Chrome" to activate'], timeout=5)
            # 弹窗等待用户登录
            result = subprocess.run(['osascript', '-e',
                'display dialog "⚠️ BOSS 直聘需要登录\n\n'
                '请在已打开的 Chrome 窗口中完成登录。\n'
                '登录后点击「已登录」，系统将重新验证。\n\n'
                '如果不登录，凌晨 3 点的自动爬取可能失败。" '
                'with title "AI 岗位爬取 — 需要登录" '
                'buttons {"跳过（明天再说）", "已登录"} default button 2 with icon caution'],
                capture_output=True, text=True, timeout=600)

            if '已登录' in result.stdout:
                # 用户说已登录，重新验证
                logger.info('用户点击已登录，重新验证...')
                time.sleep(3)
                page.get(test_url)
                time.sleep(5)
                try:
                    has_jobs = page.run_js(
                        'return document.querySelectorAll("li[class*=job-card]").length > 0')
                except Exception:
                    has_jobs = False

                if has_jobs:
                    save_status(True, '用户手动登录后验证通过')
                    notify('AI 岗位爬取 ✅', '登录验证通过！凌晨 3 点将自动执行')
                    subprocess.run(['osascript', '-e',
                        'display dialog "✅ 登录验证通过！\n\n凌晨 3:00 将自动执行。" '
                        'with title "AI 岗位爬取" '
                        'buttons {"好的"} default button 1 with icon note '
                        'giving up after 30'], timeout=60)
                else:
                    save_status(False, '用户确认登录但验证未通过')
                    notify('AI 岗位爬取 ❌', '登录验证失败，凌晨爬取可能异常')
                    subprocess.run(['osascript', '-e',
                        'display dialog "❌ 登录验证未通过\n\n'
                        '请确保在 Chrome 中能看到岗位列表。\n'
                        '凌晨 3 点的自动爬取可能会失败。" '
                        'with title "AI 岗位爬取" '
                        'buttons {"知道了"} default button 1 with icon stop '
                        'giving up after 30'], timeout=60)
            else:
                save_status(False, '用户选择跳过登录')
                logger.info('用户选择跳过登录')

    except Exception as e:
        logger.error(f'登录检查异常: {e}', exc_info=True)
        save_status(False, f'检查异常: {e}')
        notify('AI 岗位爬取 ❌', f'登录检查异常: {str(e)[:50]}')
    finally:
        # 不关闭浏览器 — 保持 Profile 活跃，让用户可以手动登录
        logger.info('登录检查完成（浏览器保持打开，Cookie 会自动保存）')


if __name__ == '__main__':
    check_login()
