#!/usr/bin/env python3
"""
全天候不间断爬取流程（Windows 版）

运行模式：
  1. 启动 → 环境预检（Chrome/网络/磁盘/Git/依赖）
  2. 登录检查
  3. 全量爬取 + 清洗 + Git 推送
  4. 冷却休息（默认 60 分钟，可配置）
  5. 回到步骤 1，无限循环

特性：
  - 全程防休眠（Windows SetThreadExecutionState）
  - 每轮开始前运行环境预检
  - 固定全量模式（不再轮换 quick/full）
  - 清洗日（每月 1/15）自动先执行老数据清洗
  - 超时保护、错误通知、执行记录
"""
import sys, io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import os
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

# 防休眠状态由 platform_utils 管理


def notify(title, msg):
    """系统通知（跨平台）"""
    try:
        from platform_utils import notify as _notify
        _notify(title, msg)
    except Exception:
        pass


def start_caffeinate():
    """启动防息屏 / 防休眠（跨平台）"""
    try:
        from platform_utils import start_keep_awake
        start_keep_awake()
    except Exception as e:
        logger.warning(f'防休眠启动失败: {e}')


def stop_caffeinate():
    """恢复正常休眠策略（跨平台）"""
    try:
        from platform_utils import stop_keep_awake
        stop_keep_awake()
    except Exception as e:
        logger.warning(f'防休眠恢复失败: {e}')


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


def preflight_check():
    """运行前环境预检，返回 (通过, 错误列表)"""
    import shutil
    errors = []

    # 1. Chrome 是否已安装
    chrome_paths = [
        Path(os.environ.get('PROGRAMFILES', '')) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe',
        Path(os.environ.get('PROGRAMFILES(X86)', '')) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe',
        Path(os.environ.get('LOCALAPPDATA', '')) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe',
    ]
    chrome_found = any(p.exists() for p in chrome_paths if str(p) != '.')
    if not chrome_found:
        # macOS / Linux fallback
        if shutil.which('google-chrome') or shutil.which('chromium'):
            chrome_found = True
    if not chrome_found:
        errors.append('Chrome 未安装或路径未找到')
    else:
        logger.info('✅ Chrome 已安装')

    # 2. Python 依赖
    for pkg in ['DrissionPage', 'openpyxl']:
        try:
            __import__(pkg)
            logger.info(f'✅ {pkg} 已安装')
        except ImportError:
            errors.append(f'Python 依赖缺失: {pkg}')

    # 3. 网络连通性
    try:
        import urllib.request
        urllib.request.urlopen('https://www.zhipin.com', timeout=10)
        logger.info('✅ 网络连通（zhipin.com 可达）')
    except Exception:
        errors.append('网络不通: 无法访问 zhipin.com')

    # 4. 磁盘空间
    try:
        disk = shutil.disk_usage(str(BASE_DIR))
        free_mb = disk.free / (1024 * 1024)
        if free_mb < 500:
            errors.append(f'磁盘空间不足: 仅剩 {free_mb:.0f}MB（需要 >500MB）')
        else:
            logger.info(f'✅ 磁盘空间充足: {free_mb:.0f}MB 可用')
    except Exception as e:
        errors.append(f'磁盘检查失败: {e}')

    # 5. Git 配置
    try:
        result = subprocess.run(['git', 'status'], cwd=str(BASE_DIR),
                                capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logger.info('✅ Git 仓库正常')
        else:
            errors.append(f'Git 异常: {result.stderr[:100]}')
    except FileNotFoundError:
        errors.append('Git 未安装')
    except Exception as e:
        errors.append(f'Git 检查失败: {e}')

    # 6. jobs_data.json 存在
    json_path = BASE_DIR / 'jobs_data.json'
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding='utf-8'))
            count = len(data.get('jobs', []))
            logger.info(f'✅ jobs_data.json 存在（{count} 条数据）')
        except Exception as e:
            errors.append(f'jobs_data.json 读取失败: {e}')
    else:
        errors.append('jobs_data.json 不存在')

    passed = len(errors) == 0
    if not passed:
        for e in errors:
            logger.error(f'❌ 预检失败: {e}')
    return passed, errors


def _run_one_round(round_num):
    """执行一轮完整的爬取流程，返回 (成功, 错误信息)"""
    t0 = time.time()
    mode = 'full'
    mode_label = '全量'

    # ① 登录检查
    run_login_check()

    # ② 清洗日检查（每月 1/15）
    if is_cleanup_day():
        logger.info('📅 今天是清洗日，先执行老数据清洗')
        notify('AI 岗位爬取', '清洗日：先执行老数据清洗')
        run_stale_cleanup()

    # ③ 全量爬取
    success = False
    error_msg = ''
    try:
        success, error_msg = run_daily_update(quick=False)
    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f'❌ 执行异常: {e}')

    duration = round(time.time() - t0)
    mins = duration // 60
    secs = duration % 60

    # ④ 结果通知
    if success:
        try:
            status = json.loads((BASE_DIR / 'run_status.json').read_text(encoding='utf-8'))
            added = status.get('added', 0)
            total = status.get('total', 0)
            msg = f'✅ 第{round_num}轮 [{mode_label}] 新增 {added} 条，总计 {total} 条 | 耗时 {mins}分{secs}秒'
        except Exception:
            msg = f'✅ 第{round_num}轮 [{mode_label}] 执行完成 | 耗时 {mins}分{secs}秒'
        logger.info(msg)
        notify('AI 岗位爬取 — 自动完成', msg)
    else:
        msg = f'❌ 第{round_num}轮 [{mode_label}] 失败 | 耗时 {mins}分{secs}秒 | {error_msg[:80]}'
        logger.error(msg)
        notify('AI 岗位爬取 — 失败', msg[:100])

    # ⑤ 写入执行记录
    record = {
        'executed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'round': round_num,
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
        records = records[-50:]
        record_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass

    return success, error_msg


def main():
    """全天候不间断循环主入口"""
    logger.info('=' * 60)
    logger.info(f'🚀 全天候爬取流程启动 {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    logger.info('=' * 60)

    # 读取冷却间隔配置
    schedule = load_schedule()
    interval_min = schedule.get('interval_minutes', 60)
    logger.info(f'⚙️  模式: 全量 | 冷却间隔: {interval_min} 分钟 | 全天候循环')

    # 全程防休眠
    start_caffeinate()

    round_num = 0
    consecutive_failures = 0
    MAX_CONSECUTIVE_FAILURES = 5  # 连续失败 5 次加长休息

    try:
        while True:
            round_num += 1
            logger.info('')
            logger.info(f'{"=" * 40} 第 {round_num} 轮 {"=" * 40}')
            logger.info(f'⏰ 开始时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

            # ① 环境预检
            logger.info('🔍 运行环境预检...')
            passed, errors = preflight_check()
            if not passed:
                logger.error(f'❌ 环境预检失败（{len(errors)} 个问题），等待 5 分钟后重试...')
                notify('AI 岗位爬取 — 预检失败', f'{len(errors)} 个问题: {"; ".join(errors[:3])}')
                time.sleep(300)
                continue

            # ② 执行一轮爬取
            success, error_msg = _run_one_round(round_num)

            if success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1

            # ③ 冷却休息
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                cool_min = interval_min * 3  # 连续失败加长冷却
                logger.warning(f'⚠️ 连续失败 {consecutive_failures} 次，延长冷却到 {cool_min} 分钟')
                notify('AI 岗位爬取 — 异常', f'连续失败 {consecutive_failures} 次，冷却 {cool_min} 分钟')
            else:
                cool_min = interval_min

            logger.info(f'💤 第 {round_num} 轮结束，冷却 {cool_min} 分钟后开始下一轮...')
            logger.info(f'   预计下一轮: {(datetime.now() + timedelta(minutes=cool_min)).strftime("%H:%M:%S")}')

            time.sleep(cool_min * 60)

    except KeyboardInterrupt:
        logger.info('🛑 用户中断（Ctrl+C），停止全天候爬取')
        notify('AI 岗位爬取', '用户中断，已停止')
    except Exception as e:
        logger.error(f'💥 致命错误: {e}', exc_info=True)
        notify('AI 岗位爬取 — 致命错误', str(e)[:100])
    finally:
        stop_caffeinate()
        logger.info(f'🏁 全天候爬取已停止，共完成 {round_num} 轮')
        logger.info('=' * 60)


if __name__ == '__main__':
    main()
