#!/usr/bin/env python3
"""
凌晨 3:00 自动执行 — 全自动无人值守每日爬取
设计原则：
  1. 不需要人确认 — 3 点你已经睡了
  2. 进度弹窗仍会弹出（醒来可以看到结果）
  3. 异常兜底 — 超时保护、失败重试、错误通知
  4. 登录状态检查 — 读取 22:00 的 login_status.json
  5. 完成后发送 macOS 通知（醒来看横幅就知道结果）

流程：
  ① 检查 login_status.json（22:00 写入的）
  ② 如果未登录，仍尝试运行（持久化 Profile 可能还有效）
  ③ 调用 daily_update.py main()
  ④ 超时保护：最长 120 分钟
  ⑤ 异常时发 macOS 通知 + 写入日志
"""
import sys
import json
import time
import signal
import logging
import subprocess
import traceback
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)
LOGIN_STATUS_FILE = LOG_DIR / 'login_status.json'

# 日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [auto_daily] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'auto_daily.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('auto_daily')

# 超时保护：120 分钟
MAX_RUNTIME_SEC = 120 * 60


class TimeoutError(Exception):
    pass


def timeout_handler(signum, frame):
    raise TimeoutError(f'执行超时（超过 {MAX_RUNTIME_SEC // 60} 分钟）')


def notify(title, msg):
    """macOS 原生通知 — 即使屏幕锁定/睡眠，醒来后也能看到"""
    try:
        subprocess.run(['osascript', '-e',
            f'display notification "{msg}" with title "{title}" sound name "Glass"'], timeout=5)
    except Exception:
        pass


def check_login_status():
    """读取 22:00 的登录检查结果"""
    if not LOGIN_STATUS_FILE.exists():
        logger.warning('未找到 login_status.json（22:00 检查未运行？）')
        return None

    try:
        data = json.loads(LOGIN_STATUS_FILE.read_text(encoding='utf-8'))
        checked_at = data.get('checked_at', '')
        logged_in = data.get('logged_in', False)
        detail = data.get('detail', '')
        logger.info(f'登录状态（{checked_at}）: {"✅" if logged_in else "❌"} {detail}')
        return logged_in
    except Exception as e:
        logger.warning(f'读取 login_status.json 失败: {e}')
        return None


def run_daily_update():
    """以子进程方式运行 daily_update.py，带超时保护"""
    script = SCRIPT_DIR / 'daily_update.py'
    logger.info(f'启动 daily_update.py (超时 {MAX_RUNTIME_SEC // 60} 分钟)')

    proc = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    # 实时输出到日志
    output_lines = []
    start = time.time()
    try:
        while True:
            line = proc.stdout.readline()
            if line:
                line = line.rstrip()
                logger.info(f'  | {line}')
                output_lines.append(line)
            elif proc.poll() is not None:
                break

            # 超时检查
            if time.time() - start > MAX_RUNTIME_SEC:
                logger.error(f'⏰ 超时！已运行 {MAX_RUNTIME_SEC // 60} 分钟，强制终止')
                proc.kill()
                proc.wait()
                return False, '超时终止'
    except Exception as e:
        proc.kill()
        proc.wait()
        return False, str(e)

    rc = proc.returncode
    if rc == 0:
        return True, '正常完成'
    else:
        last_lines = '\n'.join(output_lines[-5:])
        return False, f'退出码 {rc}: {last_lines}'


def main():
    t0 = time.time()
    logger.info('=' * 50)
    logger.info(f'🌙 凌晨自动爬取启动 {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    logger.info('=' * 50)

    # ① 检查登录状态
    login_ok = check_login_status()
    if login_ok is False:
        logger.warning('⚠️ 22:00 检查显示未登录，仍尝试运行（Profile 可能有效）')
        notify('AI 岗位爬取 ⚠️', '登录状态异常，尝试自动运行...')
    elif login_ok is None:
        logger.warning('⚠️ 未找到登录检查记录，直接尝试运行')
    else:
        logger.info('✅ 登录状态正常')

    # ② 运行每日更新（带超时保护）
    success = False
    error_msg = ''
    try:
        success, error_msg = run_daily_update()
    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f'❌ 执行异常: {e}')

    duration = round(time.time() - t0)
    mins = duration // 60
    secs = duration % 60

    # ③ 结果通知
    if success:
        # 读取最终结果
        try:
            status = json.loads((BASE_DIR / 'run_status.json').read_text(encoding='utf-8'))
            added = status.get('added', 0)
            total = status.get('total', 0)
            msg = f'✅ 新增 {added} 条，总计 {total} 条 | 耗时 {mins}分{secs}秒'
        except Exception:
            msg = f'✅ 执行完成 | 耗时 {mins}分{secs}秒'
        logger.info(msg)
        notify('AI 岗位爬取 — 自动完成', msg)
    else:
        msg = f'❌ 自动爬取失败 | 耗时 {mins}分{secs}秒 | {error_msg[:80]}'
        logger.error(msg)
        notify('AI 岗位爬取 — 失败', msg[:100])

    # ④ 写入自动执行记录
    record = {
        'executed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'success': success,
        'duration_sec': duration,
        'error': error_msg if not success else '',
    }
    record_file = LOG_DIR / 'auto_daily_record.json'
    try:
        if record_file.exists():
            records = json.loads(record_file.read_text(encoding='utf-8'))
        else:
            records = []
        records.append(record)
        # 只保留最近 30 天
        records = records[-30:]
        record_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass

    logger.info(f'🌙 自动爬取结束，耗时 {mins}分{secs}秒')
    logger.info('=' * 50)


if __name__ == '__main__':
    main()
