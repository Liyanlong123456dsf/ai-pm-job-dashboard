#!/usr/bin/env python3
"""
22:00 一体化自动流程 — 登录检查 + 防息屏 + 等待 + 爬取
设计原则：
  1. 22:00 由 launchd 触发
  2. 立即执行登录检查（引导用户扫码）
  3. 启动 caffeinate 防息屏（合盖后无效，但锁屏/息屏不休眠）
  4. 等待到 00:00 开始爬取
  5. 根据轮换策略选择 全量/快速 模式
  6. 爬取+清洗+上传完成后终止 caffeinate
  7. 异常兜底 — 超时保护、错误通知

轮换策略（rotation）：
  读取 config/keywords.json 中的 schedule.rotation 数组
  默认 ["full", "quick", "quick"] → 全量/快速/快速 三天一循环
  通过 logs/rotation_index.json 记录当前轮次
"""
import sys
import json
import time
import logging
import subprocess
import traceback
from pathlib import Path
from datetime import datetime, timedelta

SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)
CONFIG_FILE = BASE_DIR / 'config' / 'keywords.json'
ROTATION_FILE = LOG_DIR / 'rotation_index.json'

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

# 超时保护：180 分钟（全量模式可能需要更长）
MAX_RUNTIME_SEC = 180 * 60

# caffeinate 进程句柄
_caffeinate_proc = None


def notify(title, msg):
    """macOS 原生通知"""
    try:
        subprocess.run(['osascript', '-e',
            f'display notification "{msg}" with title "{title}" sound name "Glass"'], timeout=5)
    except Exception:
        pass


def start_caffeinate():
    """启动 caffeinate 防息屏（-i 防止系统idle休眠，-d 防止显示器休眠）"""
    global _caffeinate_proc
    try:
        _caffeinate_proc = subprocess.Popen(
            ['caffeinate', '-i', '-d'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info(f'☕ caffeinate 已启动 (PID: {_caffeinate_proc.pid})')
    except Exception as e:
        logger.warning(f'caffeinate 启动失败: {e}')


def stop_caffeinate():
    """终止 caffeinate"""
    global _caffeinate_proc
    if _caffeinate_proc and _caffeinate_proc.poll() is None:
        _caffeinate_proc.terminate()
        _caffeinate_proc.wait(timeout=5)
        logger.info('☕ caffeinate 已终止')
    _caffeinate_proc = None


def load_schedule():
    """读取调度配置"""
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        return config.get('schedule', {})
    except Exception:
        return {}


def is_cleanup_day():
    """判断今天是否是清洗日（默认每月 1/15）"""
    schedule = load_schedule()
    cleanup_days = schedule.get('cleanup_days', [1, 15])
    today_day = datetime.now().day
    return today_day in cleanup_days


def run_stale_cleanup():
    """执行老数据清洗（调用 stale_cleanup.py）"""
    script = SCRIPT_DIR / 'stale_cleanup.py'
    logger.info('🧹 开始月度老数据清洗...')
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(BASE_DIR),
            capture_output=True, text=True,
            timeout=7200,  # 2小时超时
        )
        if result.returncode == 0:
            logger.info('🧹 老数据清洗完成')
            if result.stdout:
                for line in result.stdout.strip().split('\n')[-5:]:
                    logger.info(f'  | {line}')
        else:
            logger.warning(f'🧹 老数据清洗异常（退出码 {result.returncode}）')
            if result.stderr:
                logger.warning(f'  stderr: {result.stderr[:200]}')
    except subprocess.TimeoutExpired:
        logger.warning('🧹 老数据清洗超时（2小时）')
    except Exception as e:
        logger.warning(f'🧹 老数据清洗异常: {e}')


def get_crawl_mode():
    """根据轮换策略确定今日模式：full 或 quick"""
    schedule = load_schedule()
    rotation = schedule.get('rotation', ['full', 'quick', 'quick'])

    # 读取当前轮次
    idx = 0
    if ROTATION_FILE.exists():
        try:
            data = json.loads(ROTATION_FILE.read_text(encoding='utf-8'))
            idx = data.get('index', 0)
        except Exception:
            pass

    mode = rotation[idx % len(rotation)]

    # 保存下一轮次
    next_idx = (idx + 1) % len(rotation)
    ROTATION_FILE.write_text(json.dumps({
        'index': next_idx,
        'last_mode': mode,
        'last_date': datetime.now().strftime('%Y-%m-%d'),
        'rotation': rotation,
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    logger.info(f'📋 轮换策略: {rotation} | 本次第 {idx+1}/{len(rotation)} 轮 → {mode}')
    return mode


def wait_until_crawl_time():
    """等待到配置的爬取时间（默认 00:00）"""
    schedule = load_schedule()
    target_hour = schedule.get('crawl_hour', 0)
    target_minute = schedule.get('crawl_minute', 0)

    now = datetime.now()
    target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)

    # 如果目标时间已过（比如 22:00 触发但目标是 00:00，需要等到明天凌晨）
    if target <= now:
        target += timedelta(days=1)

    wait_secs = (target - now).total_seconds()
    if wait_secs > 0:
        logger.info(f'⏰ 等待到 {target.strftime("%H:%M")} 开始爬取（还有 {wait_secs/60:.0f} 分钟）')
        notify('AI 岗位爬取', f'登录检查完成，{target.strftime("%H:%M")} 将自动开始爬取')
        time.sleep(wait_secs)
    else:
        logger.info('⏰ 已到爬取时间，立即开始')


def run_login_check():
    """执行登录检查（调用 login_check.py）"""
    script = SCRIPT_DIR / 'login_check.py'
    logger.info('🔑 开始登录检查...')
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(BASE_DIR),
            capture_output=True, text=True,
            timeout=600,  # 10分钟超时
        )
        if result.returncode == 0:
            logger.info('🔑 登录检查完成')
        else:
            logger.warning(f'🔑 登录检查异常（退出码 {result.returncode}）')
    except subprocess.TimeoutExpired:
        logger.warning('🔑 登录检查超时（10分钟）')
    except Exception as e:
        logger.warning(f'🔑 登录检查异常: {e}')


def run_daily_update(quick=False):
    """以子进程方式运行 daily_update.py，带超时保护"""
    script = SCRIPT_DIR / 'daily_update.py'
    cmd = [sys.executable, str(script)]
    if quick:
        cmd.append('--quick')

    mode_label = '快速' if quick else '全量'
    logger.info(f'🚀 启动 daily_update.py [{mode_label}模式] (超时 {MAX_RUNTIME_SEC // 60} 分钟)')

    proc = subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

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
    logger.info(f'🌙 22:00 一体化流程启动 {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    logger.info('=' * 50)

    try:
        # ① 启动 caffeinate 防息屏
        start_caffeinate()

        # ② 执行登录检查
        run_login_check()

        # ③ 检查是否为清洗日（1/15）
        cleanup_today = is_cleanup_day()

        if cleanup_today:
            # 清洗日：登录后立即执行，不等待 00:00
            logger.info('📅 今天是清洗日，登录后立即开始执行')
            notify('AI 岗位爬取', '今天是清洗日，立即开始老数据清洗 + 爬取')
            # ③a 先执行老数据清洗
            run_stale_cleanup()
        else:
            # 普通日：等待到 00:00
            wait_until_crawl_time()

        # ④ 确定今日模式（全量/快速）
        mode = get_crawl_mode()
        quick = (mode == 'quick')

        # ⑤ 运行每日更新（带超时保护）
        success = False
        error_msg = ''
        try:
            success, error_msg = run_daily_update(quick=quick)
        except Exception as e:
            error_msg = traceback.format_exc()
            logger.error(f'❌ 执行异常: {e}')

        duration = round(time.time() - t0)
        mins = duration // 60
        secs = duration % 60

        # ⑥ 结果通知
        mode_label = '快速' if quick else '全量'
        if success:
            try:
                status = json.loads((BASE_DIR / 'run_status.json').read_text(encoding='utf-8'))
                added = status.get('added', 0)
                total = status.get('total', 0)
                msg = f'✅ [{mode_label}] 新增 {added} 条，总计 {total} 条 | 耗时 {mins}分{secs}秒'
            except Exception:
                msg = f'✅ [{mode_label}] 执行完成 | 耗时 {mins}分{secs}秒'
            logger.info(msg)
            notify('AI 岗位爬取 — 自动完成', msg)
        else:
            msg = f'❌ [{mode_label}] 自动爬取失败 | 耗时 {mins}分{secs}秒 | {error_msg[:80]}'
            logger.error(msg)
            notify('AI 岗位爬取 — 失败', msg[:100])

        # ⑦ 写入自动执行记录
        record = {
            'executed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'mode': mode,
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
            records = records[-30:]
            record_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass

        logger.info(f'🌙 自动爬取结束，耗时 {mins}分{secs}秒')

    finally:
        # ⑧ 无论成功失败，终止 caffeinate
        stop_caffeinate()
        logger.info('=' * 50)


if __name__ == '__main__':
    main()
