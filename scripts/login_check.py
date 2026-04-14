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
import sys, io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
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


def save_status(logged_in: bool, detail: str = '', status: str = '', retry_after_sec: int = 0, needs_user: bool = False):
    """保存登录状态到 JSON"""
    data = {
        'checked_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'logged_in': logged_in,
        'status': status or ('logged_in' if logged_in else 'needs_login'),
        'detail': detail,
        'retry_after_sec': retry_after_sec,
        'needs_user': needs_user,
    }
    STATUS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info(f'登录状态已保存: {"✅ 已登录" if logged_in else "❌ 未登录"} [{data["status"]}] — {detail}')


def notify(title, msg):
    """系统通知（跨平台）"""
    try:
        from platform_utils import notify as _notify
        _notify(title, msg)
    except Exception:
        pass


def check_login():
    """启动浏览器，检测登录状态"""
    logger.info('=' * 40)
    logger.info('开始登录状态检查')

    try:
        try:
            from platform_utils import is_unattended_mode
            unattended = is_unattended_mode()
        except Exception:
            unattended = False
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
        verify_seen = False
        last_title = ''
        for attempt in range(6):
            try:
                title = page.run_js('return document.title || ""')
                if title:
                    last_title = str(title)
                has_jobs = page.run_js(
                    'return document.querySelectorAll("li[class*=job-card]").length > 0'
                )
                if has_jobs:
                    logged_in = True
                    break
                is_verify = ('安全' in last_title) or ('验证' in last_title)
                if is_verify:
                    verify_seen = True
                    logger.info(f'安全验证页面，等待... ({attempt+1}/6)')
            except Exception:
                pass
            time.sleep(3)

        if logged_in:
            # ✅ 已登录
            save_status(True, '检测到岗位列表，Cookie 有效', status='logged_in')
            notify('AI 岗位爬取 ✅', '登录状态正常，将自动执行每日爬取')
            from platform_utils import show_login_status_dialog
            show_login_status_dialog(
                'AI 岗位爬取 — 登录检查',
                '✅ BOSS 直聘登录状态正常\n\n'
                'Cookie 有效，将自动执行每日爬取。\n'
                '无需任何操作。',
                logged_in=True
            )
            logger.info('✅ 登录正常，用户已确认')
            return 'logged_in'
        else:
            # ❌ 未登录 — 引导用户登录
            detail = f'未检测到岗位列表，标题={last_title or "(空)"}'
            if verify_seen:
                save_status(False, detail, status='verify_page', retry_after_sec=900, needs_user=False)
                notify('AI 岗位爬取 ⚠️', '检测到 BOSS 安全验证页，将稍后自动重试')
                logger.warning('检测到安全验证页面，无人值守下不阻塞，等待下轮重试')
                if unattended:
                    return 'verify_page'
            else:
                save_status(False, detail, status='needs_login', retry_after_sec=3600, needs_user=True)
            notify('AI 岗位爬取 ⚠️', '需要登录 BOSS 直聘！请在 Chrome 中登录')
            from platform_utils import activate_chrome, show_login_recheck_dialog, show_login_status_dialog
            if unattended:
                logger.warning('无人值守模式：跳过登录交互，等待后续轮次重试')
                return 'needs_login'
            activate_chrome()
            choice = show_login_recheck_dialog(
                'AI 岗位爬取 — 需要登录',
                '⚠️ BOSS 直聘需要登录\n\n'
                '请在已打开的 Chrome 窗口中完成登录。\n'
                '登录后点击「是」，系统将重新验证。\n\n'
                '如果不登录，自动爬取可能失败。'
            )

            if choice == 'login':
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
                    save_status(True, '用户手动登录后验证通过', status='logged_in')
                    notify('AI 岗位爬取 ✅', '登录验证通过！将自动执行')
                    show_login_status_dialog(
                        'AI 岗位爬取',
                        '✅ 登录验证通过！\n\n将自动执行每日爬取。',
                        logged_in=True
                    )
                    return 'logged_in'
                else:
                    save_status(False, '用户确认登录但验证未通过', status='recheck_failed', retry_after_sec=1800, needs_user=True)
                    notify('AI 岗位爬取 ❌', '登录验证失败，爬取可能异常')
                    show_login_status_dialog(
                        'AI 岗位爬取',
                        '❌ 登录验证未通过\n\n'
                        '请确保在 Chrome 中能看到岗位列表。\n'
                        '自动爬取可能会失败。',
                        logged_in=False
                    )
                    return 'recheck_failed'
            else:
                save_status(False, '用户选择跳过登录', status='skipped_login', retry_after_sec=3600, needs_user=True)
                logger.info('用户选择跳过登录')
                return 'skipped_login'

    except Exception as e:
        logger.error(f'登录检查异常: {e}', exc_info=True)
        save_status(False, f'检查异常: {e}', status='error', retry_after_sec=600, needs_user=False)
        notify('AI 岗位爬取 ❌', f'登录检查异常: {str(e)[:50]}')
        return 'error'
    finally:
        # 不关闭浏览器 — 保持 Profile 活跃，让用户可以手动登录
        logger.info('登录检查完成（浏览器保持打开，Cookie 会自动保存）')


if __name__ == '__main__':
    result = check_login()
    exit_code = 0 if result == 'logged_in' else (2 if result in {'needs_login', 'verify_page', 'recheck_failed', 'skipped_login'} else 1)
    sys.exit(exit_code)
