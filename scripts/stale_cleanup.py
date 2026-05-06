#!/usr/bin/env python3
"""
定期数据清洗 — 清理失效/停招岗位，保持数据库最新有效
每 3 天自动执行（由 auto_daily.py 或控制面板触发）

流程：
  1. 读取 jobs_data.json
  2. 筛选 _date 超过 7 天没被爬虫重新抓到 且 有 url 的岗位
  3. DrissionPage 逐条访问 url
  4. 判定岗位是否下架：
     - 链接失效 / 页面含"停止招聘/已关闭/不存在" → 删除
     - 页面正常 → 保留不动（等爬虫下次抓到时自然刷新）
     - 访问异常 → 跳过
  5. 保存更新后的 jobs_data.json
  6. 同步数据：导出总表 → 生成知识库 → 飞书同步 → Git 推送
"""
import sys, io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import json
import time
import random
import logging
import argparse
from pathlib import Path
from datetime import datetime, date, timedelta

SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
JSON_PATH = BASE_DIR / 'jobs_data.json'
CONFIG_PATH = BASE_DIR / 'config' / 'keywords.json'
# Profile：优先读 AI_PM_BOSS_PROFILE 环境变量，回退默认
import os as _os
_env_profile = _os.environ.get('AI_PM_BOSS_PROFILE', '').strip()
if _env_profile:
    _p = Path(_env_profile)
    PROFILE_DIR = _p if _p.is_absolute() else (BASE_DIR / _p)
else:
    PROFILE_DIR = BASE_DIR / '.chrome_profile'
# Chrome 调试端口：避免与爬虫(9222)和登录(9222/9223)冲突
CHROME_PORT = int(_os.environ.get('AI_PM_CHROME_PORT', '9224'))
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)
CHECKPOINT_FILE = LOG_DIR / 'cleanup_checkpoint.json'
PROGRESS_FILE = LOG_DIR / 'progress.json'


def _write_progress(pct, phase, detail='', steps=None, done=False):
    """写入进度 JSON，与 daily_update.py 共享同一文件，供看板展示"""
    data = {
        'pct': min(100, max(0, int(pct))),
        'phase': phase,
        'detail': detail,
        'steps': steps or [],
        'done': done,
        'task_type': 'cleanup',
        'ts': datetime.now().strftime('%H:%M:%S'),
    }
    try:
        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [stale_cleanup] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'stale_cleanup.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('stale_cleanup')

# 下架判定关键词
REMOVED_MARKERS = [
    '已关闭', '已下架', '停止招聘', '该职位已停止招聘',
    '该职位不存在', '职位已下线', '页面不存在', '404',
    '职位已关闭', '抱歉', '岗位已关闭',
]


def load_config():
    """读取清洗配置"""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        schedule = cfg.get('schedule', {})
        return {
            'max_age_days': schedule.get('cleanup_max_age_days', 30),
            'cleanup_days': schedule.get('cleanup_days', [1, 15]),
        }
    except Exception:
        return {'max_age_days': 30, 'cleanup_days': [1, 15]}


def random_delay(lo=0.8, hi=1.8):
    time.sleep(random.uniform(lo, hi))


def _save_checkpoint(checked_keys: set):
    """保存断点：已检查过的 _key 集合"""
    try:
        CHECKPOINT_FILE.write_text(json.dumps({
            'checked_keys': list(checked_keys),
            'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def _clear_checkpoint():
    """清除断点文件（完成时调用）"""
    try:
        if CHECKPOINT_FILE.exists():
            CHECKPOINT_FILE.unlink()
            logger.info('📌 断点文件已清除')
    except Exception:
        pass


def _save_jobs(data: dict, jobs: list, remove_set: set):
    """中间保存 jobs_data.json（不删除，仅更新日期）"""
    try:
        # 中间保存时不真正删除，只更新已刷新的日期
        data['jobs'] = jobs
        data['meta']['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M')
        with open(JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f'中间保存失败: {e}')


def is_job_removed(page) -> bool:
    """检测当前页面是否显示岗位已下架"""
    try:
        # 获取页面文本
        text = page.run_js('return document.body?.innerText || ""')
        if not text:
            return False
        # 检查下架标记
        for marker in REMOVED_MARKERS:
            if marker in text:
                return True
        # 额外检查：页面标题
        title = page.run_js('return document.title || ""')
        for marker in ['已关闭', '不存在', '404']:
            if marker in title:
                return True
        return False
    except Exception:
        return False


def _build_options():
    """构建 Chrome 选项：反检测 + 端口隔离 + 持久化 Profile"""
    from DrissionPage import ChromiumOptions
    import platform as _plat
    PROFILE_DIR.mkdir(exist_ok=True)
    co = ChromiumOptions()
    # 反指纹检测（与 boss_dp.py 保持一致）
    co.set_argument('--disable-blink-features=AutomationControlled')
    minor = random.randint(0, 99)
    if _plat.system() == 'Windows':
        co.set_user_agent(
            f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            f'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.{minor} Safari/537.36'
        )
    else:
        co.set_user_agent(
            f'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            f'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.{minor} Safari/537.36'
        )
    co.set_pref('excludeSwitches', ['enable-automation'])
    co.set_pref('useAutomationExtension', False)
    co.set_argument('--no-first-run')
    co.set_argument('--lang=zh-CN')
    w = random.choice([1440, 1512, 1680, 1920]) + random.randint(-20, 20)
    h = random.choice([900, 1080, 1050]) + random.randint(-20, 20)
    co.set_argument(f'--window-size={w},{h}')
    co.set_user_data_path(str(PROFILE_DIR))
    co.set_local_port(CHROME_PORT)
    return co


def _check_login(page) -> bool:
    """访问 BOSS 首页检查登录状态，避免未登录导致误判"""
    try:
        page.get('https://www.zhipin.com/web/geek/job?query=AI&city=101010100')
        time.sleep(4)
        has_jobs = page.run_js(
            'return document.querySelectorAll("li[class*=job-card]").length > 0'
        )
        if has_jobs:
            logger.info('✅ BOSS 登录状态正常')
            return True
        title = page.run_js('return document.title || ""')
        if '安全' in title or '验证' in title:
            logger.warning('⚠️ 触发安全验证页面，跳过本次清洗')
            return False
        logger.warning(f'⚠️ 未检测到岗位列表（标题={title}），可能未登录')
        return False
    except Exception as e:
        logger.warning(f'⚠️ 登录检查异常: {e}')
        return False


def main():
    parser = argparse.ArgumentParser(description='定期老数据清洗')
    parser.add_argument('--dry-run', action='store_true', help='只检查不修改')
    parser.add_argument('--limit', type=int, default=None, help='本次最多检查N条（默认100；--all 默认不限；0=不限）')
    parser.add_argument('--max-age', type=int, default=0, help='覆盖最大天数（0=用配置）')
    parser.add_argument('--all', action='store_true', help='检查全部有链接岗位，不按 _date 过滤')
    parser.add_argument('--normalize-first', action='store_true', help='在线验证前先对全量数据规范化、去重并过滤17K以下')
    args = parser.parse_args()

    config = load_config()
    max_age = args.max_age if args.max_age > 0 else config['max_age_days']
    _steps = []

    def _step(name, ok, detail=''):
        _steps.append({'name': name, 'ok': ok, 'detail': detail, 'time': datetime.now().strftime('%H:%M:%S')})

    _write_progress(0, '🧹 数据清洗启动中...', '')

    # 读取数据
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    jobs = data.get('jobs', [])
    today = date.today()
    cutoff = (today - timedelta(days=max_age)).isoformat()
    today_str = today.isoformat()

    if args.normalize_first:
        try:
            from merger import clean_jobs
            before_normalize = len(jobs)
            jobs, clean_stats = clean_jobs(jobs)
            salary_filtered = []
            removed_below_salary = 0
            for job in jobs:
                try:
                    avg = float(job.get('avg') or 0)
                except Exception:
                    avg = 0
                if avg >= 17:
                    salary_filtered.append(job)
                else:
                    removed_below_salary += 1
            jobs = salary_filtered
            clean_stats['removed_below_salary'] = removed_below_salary
            clean_stats['input_before_salary'] = clean_stats.get('output', len(jobs) + removed_below_salary)
            clean_stats['output'] = len(jobs)
            data['jobs'] = jobs
            data.setdefault('meta', {})
            data['meta']['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M')
            data['meta']['total'] = len(jobs)
            data['meta']['cleaned'] = clean_stats
            with open(JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            logger.info(f'🧽 全量规范化完成: {before_normalize} → {len(jobs)} ({clean_stats})')
            _step('全量规范化', True, f'{before_normalize} → {len(jobs)} 条')
        except Exception as e:
            logger.error(f'全量规范化失败: {e}', exc_info=True)
            _step('全量规范化', False, str(e)[:200])
            _write_progress(100, '❌ 清洗中止', f'全量规范化失败: {e}', _steps, done=True)
            return

    # === 第一阶段：清理无 URL 的超期岗位（无法验证，直接删除） ===
    no_url_removed = 0
    keep_jobs = []
    for job in jobs:
        has_url = bool(job.get('url'))
        if not has_url and _os.environ.get('AI_PM_REMOVE_NO_URL_STALE') == '1':
            # 用 _date（最后活跃日期）判断过期
            job_date = job.get('_date', '') or job.get('_crawled_at', '9999-99-99')
            if job_date[:10] < cutoff:
                no_url_removed += 1
                continue  # 跳过 = 删除
        keep_jobs.append(job)
    if no_url_removed:
        logger.info(f'🗑️ 清理 {no_url_removed} 条无链接超期岗位')
        jobs = keep_jobs
        data['jobs'] = jobs

    # === 第二阶段：筛选有 URL 的超期岗位（用 _date 最后活跃日期判断） ===
    stale_indices = []
    for i, job in enumerate(jobs):
        job_date = job.get('_date', '') or job.get('_crawled_at', '9999-99-99')
        has_url = bool(job.get('url'))
        if has_url and (args.all or job_date[:10] < cutoff):
            stale_indices.append(i)

    total_stale = len(stale_indices)
    if args.limit is None:
        limit = len(stale_indices) if args.all else 100
    else:
        limit = args.limit if args.limit > 0 else len(stale_indices)
    stale_indices = stale_indices[:limit]

    scope_label = '全部有链接' if args.all else f'超过 {max_age} 天且有链接'
    logger.info(f'总岗位: {len(jobs)}, {scope_label}: {total_stale}, 本次检查: {len(stale_indices)}')
    if no_url_removed:
        _step('清理无链接岗位', True, f'删除 {no_url_removed} 条')
    _write_progress(5, '🧹 筛选完成', f'待检查 {len(stale_indices)} 条', _steps)

    if not stale_indices and not no_url_removed:
        logger.info('✅ 无需清洗，所有岗位都在有效期内')
        _write_progress(100, '✅ 无需清洗', '所有岗位都在有效期内', _steps, done=True)
        return

    if not stale_indices:
        # 只清理了无 URL 岗位，保存后退出
        _final_save(data, jobs, today_str, 0, 0, 0, 0, no_url_removed)
        return

    if args.dry_run:
        logger.info(f'[DRY RUN] 仅列出需要检查的岗位（前20条）:')
        for idx in stale_indices[:20]:
            j = jobs[idx]
            logger.info(f'  {j.get("title")} | {j.get("company")} | _date={j.get("_date")} | url={j.get("url","")[:60]}')
        if total_stale > 20:
            logger.info(f'  ... 还有 {total_stale - 20} 条')
        return

    # === 启动浏览器（反检测 + 端口隔离） ===
    from DrissionPage import ChromiumPage
    co = _build_options()
    page = ChromiumPage(addr_or_opts=co)
    # 设置页面加载超时，避免单条卡住
    try:
        page.set.timeouts(base=15, page_load=15, script=10)
    except Exception:
        pass
    # 注入反检测 JS
    try:
        page.run_js('''
            Object.defineProperty(navigator, "webdriver", {get: () => undefined});
            Object.defineProperty(navigator, "plugins", {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, "languages", {get: () => ["zh-CN","zh","en"]});
            window.chrome = {runtime: {}, loadTimes: () => ({}), csi: () => ({})};
        ''')
    except Exception:
        pass
    logger.info(f'✓ 浏览器已启动 (Profile: {PROFILE_DIR}, Port: {CHROME_PORT})')
    _step('启动浏览器', True)
    _write_progress(10, '🧹 检查登录状态...', '', _steps)

    # === 登录校验 ===
    if not _check_login(page):
        logger.error('❌ BOSS 未登录或触发验证，中止清洗（避免误判）')
        _step('登录校验', False, '未登录或触发验证')
        _write_progress(100, '❌ 清洗中止', '登录校验失败', _steps, done=True)
        try:
            page.quit()
        except Exception:
            pass
        # 即使中止，也保存无 URL 清理结果
        if no_url_removed:
            _final_save(data, jobs, today_str, 0, 0, 0, 0, no_url_removed, _steps)
        return

    _step('登录校验', True, '已登录')
    _write_progress(15, '🧹 开始在线验证...', f'共 {len(stale_indices)} 条', _steps)

    # === 加载断点 checkpoint ===
    checked_keys = set()
    if CHECKPOINT_FILE.exists():
        try:
            cp = json.loads(CHECKPOINT_FILE.read_text(encoding='utf-8'))
            checked_keys = set(cp.get('checked_keys', []))
            logger.info(f'📌 检测到断点记录，已检查 {len(checked_keys)} 条，将从断点继续')
        except Exception:
            pass

    # 过滤掉已检查过的
    before_filter = len(stale_indices)
    stale_indices = [i for i in stale_indices if jobs[i].get('_key') not in checked_keys]
    if before_filter != len(stale_indices):
        logger.info(f'📌 跳过已检查 {before_filter - len(stale_indices)} 条，本次还需检查 {len(stale_indices)} 条')

    if not stale_indices:
        logger.info('✅ 所有超期岗位已检查完毕（断点续传完成）')
        _clear_checkpoint()
        try:
            page.quit()
        except Exception:
            pass
        if no_url_removed:
            _final_save(data, jobs, today_str, 0, 0, 0, 0, no_url_removed)
        return

    # === 逐条检查 ===
    refreshed = 0
    removed = 0
    skipped = 0
    remove_set = set()

    for check_idx, job_idx in enumerate(stale_indices, 1):
        job = jobs[job_idx]
        url = job['url']
        key = job.get('_key', '')
        title = job.get('title', '?')
        company = job.get('company', '?')

        try:
            page.get(url)
            random_delay(1.5, 3.0)

            if is_job_removed(page):
                logger.info(f'  ✗ [{check_idx}/{len(stale_indices)}] 已下架/停招: {title} @ {company}')
                remove_set.add(job_idx)
                removed += 1
            else:
                # 仍有效 → 保留不动，等爬虫下次抓到时自然刷新 _date
                logger.info(f'  ✓ [{check_idx}/{len(stale_indices)}] 仍有效: {title} @ {company}')
                refreshed += 1

        except Exception as e:
            logger.warning(f'  ? [{check_idx}/{len(stale_indices)}] 访问异常，跳过: {title} @ {company} | {e}')
            skipped += 1

        # 记录已检查
        if key:
            checked_keys.add(key)

        # 每 10 条中间保存 jobs_data.json + checkpoint + 进度
        if check_idx % 10 == 0:
            logger.info(f'  进度: {check_idx}/{len(stale_indices)} (有效 {refreshed}, 删除 {removed}, 跳过 {skipped})')
            _save_checkpoint(checked_keys)
            _save_jobs(data, jobs, remove_set)
            pct = 15 + int(70 * check_idx / len(stale_indices))
            _write_progress(pct, f'🧹 验证中 {check_idx}/{len(stale_indices)}',
                            f'删除 {removed} · 有效 {refreshed} · 跳过 {skipped}', _steps)

        # 防封策略
        if check_idx % 20 == 0:
            for _ in range(random.randint(1, 3)):
                page.scroll.down(random.randint(100, 300))
                time.sleep(random.uniform(0.3, 0.8))
            time.sleep(random.uniform(2, 4))
        else:
            random_delay(0.5, 1.2)

    try:
        page.quit()
    except Exception:
        pass

    # 删除已下架岗位
    if remove_set:
        jobs = [j for i, j in enumerate(jobs) if i not in remove_set]

    _step('在线验证', True, f'检查 {len(stale_indices)} 条 · 删除 {removed} · 有效 {refreshed}')
    _final_save(data, jobs, today_str, len(stale_indices), refreshed, removed, skipped, no_url_removed, _steps)


def _final_save(data, jobs, today_str, checked, refreshed, removed, skipped, no_url_removed, steps=None):
    """最终保存 + 写记录 + 飞书通知"""
    steps = steps if steps is not None else []
    data['jobs'] = jobs
    data['meta']['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    data['meta']['total'] = len(jobs)
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

    _clear_checkpoint()

    total_removed = removed + no_url_removed
    logger.info('=' * 50)
    logger.info(f'✅ 清洗完成!')
    logger.info(f'   在线检查: {checked} 条')
    logger.info(f'   刷新日期: {refreshed} 条')
    logger.info(f'   删除下架: {removed} 条')
    logger.info(f'   删除无链接超期: {no_url_removed} 条')
    logger.info(f'   跳过异常: {skipped} 条')
    logger.info(f'   剩余总计: {len(jobs)} 条')
    logger.info('=' * 50)

    # 写入清洗记录
    record = {
        'date': today_str,
        'checked': checked,
        'refreshed': refreshed,
        'removed': total_removed,
        'removed_stale': removed,
        'removed_no_url': no_url_removed,
        'skipped': skipped,
        'remaining': len(jobs),
    }
    record_file = LOG_DIR / 'cleanup_record.json'
    try:
        if record_file.exists():
            records = json.loads(record_file.read_text(encoding='utf-8'))
        else:
            records = []
        records.append(record)
        records = records[-20:]
        record_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass

    steps.append({'name': '保存数据', 'ok': True, 'detail': f'删除 {total_removed} 条', 'time': datetime.now().strftime('%H:%M:%S')})

    # === 同步数据管线（与爬取完成后一致） ===
    if total_removed > 0:
        _post_cleanup_sync(checked, total_removed, removed, no_url_removed, refreshed, len(jobs), steps)
    else:
        _write_progress(100, '✅ 清洗完成', f'无改动 · 剩余 {len(jobs)} 条', steps, done=True)


def _post_cleanup_sync(checked, total_removed, removed, no_url_removed, refreshed, remaining, steps=None):
    """清洗后同步：导出总表 → 生成知识库 → 飞书同步 → Git 推送"""
    import subprocess
    steps = steps if steps is not None else []

    def _append(name, ok, detail=''):
        steps.append({'name': name, 'ok': ok, 'detail': detail, 'time': datetime.now().strftime('%H:%M:%S')})

    # 1. 导出总表
    _write_progress(88, '📊 导出总表...', '', steps)
    try:
        subprocess.run([sys.executable, str(SCRIPT_DIR / 'export_total.py')],
                       cwd=str(BASE_DIR), check=True, timeout=900)
        logger.info('✅ 统一总表已导出')
        _append('导出总表', True)
    except Exception as e:
        logger.warning(f'总表导出失败(非致命): {e}')
        _append('导出总表', False, str(e)[:80])

    # 2. 生成知识库
    _write_progress(91, '📚 生成知识库...', '', steps)
    try:
        subprocess.run([sys.executable, str(SCRIPT_DIR / 'gen_knowledge.py')],
                       cwd=str(BASE_DIR), check=True, timeout=900)
        logger.info('✅ 知识库已重新生成')
        _append('生成知识库', True)
    except Exception as e:
        logger.warning(f'知识库生成失败(非致命): {e}')
        _append('生成知识库', False, str(e)[:80])

    # 3. 飞书同步
    _write_progress(94, '📤 飞书同步...', '', steps)
    sync_ok = False
    try:
        for _try in range(3):
            result = subprocess.run([sys.executable, str(SCRIPT_DIR / 'sync_feishu.py')],
                                    cwd=str(BASE_DIR), capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=600)
            if result.returncode == 0:
                sync_ok = True
                break
            logger.warning(f'飞书同步第{_try+1}次失败: {(result.stderr or "")[:200]}')
            time.sleep(10 * (_try + 1))
        if sync_ok:
            logger.info('✅ 知识库已同步到飞书云文档')
            _append('飞书同步', True)
        else:
            logger.warning('飞书同步 3 次均失败')
            _append('飞书同步', False, '3 次重试失败')
    except Exception as e:
        logger.warning(f'飞书同步失败(非致命): {e}')
        _append('飞书同步', False, str(e)[:80])

    # 4. 飞书告警通知
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from feishu_alert import send_alert
        msg = (f'🧹 数据清洗完成\n'
               f'检查 {checked} 条 · 删除 {total_removed} 条'
               f'{"(下架"+str(removed)+"/无链接"+str(no_url_removed)+")" if no_url_removed else ""}'
               f' · 有效 {refreshed} 条 · 剩余 {remaining} 条')
        send_alert(msg, key='cleanup_report', throttle_sec=0)
    except Exception as e:
        logger.debug(f'飞书通知跳过: {e}')

    # 5. Git 提交 + 推送
    _write_progress(97, '🔀 Git 推送中...', '', steps)
    try:
        # 检测本地代理
        import socket
        _proxy_set = False
        for _pport in [7897, 7890, 7891, 10808, 10809, 1080]:
            try:
                with socket.create_connection(('127.0.0.1', _pport), timeout=1):
                    pass
                subprocess.run(['git', 'config', '--global', 'http.proxy', f'http://127.0.0.1:{_pport}'],
                               capture_output=True, timeout=5)
                subprocess.run(['git', 'config', '--global', 'https.proxy', f'http://127.0.0.1:{_pport}'],
                               capture_output=True, timeout=5)
                logger.info(f'检测到本地代理 127.0.0.1:{_pport}')
                _proxy_set = True
                break
            except (OSError, socket.timeout):
                continue

        from datetime import datetime as _dt
        today = _dt.now().strftime('%Y-%m-%d')
        subprocess.run(['git', 'add', '-A'], cwd=str(BASE_DIR), check=True, timeout=120)
        diff_ret = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=str(BASE_DIR), timeout=60)
        if diff_ret.returncode == 0:
            logger.info('✅ 无文件变更，跳过 Git 提交')
            _append('Git 推送', True, '无变更，跳过')
        else:
            subprocess.run(['git', 'commit', '-m',
                            f'cleanup: {today} 删除{total_removed}条失效岗位 剩余{remaining}条'],
                           cwd=str(BASE_DIR), check=True, timeout=120)
            push_ok = False
            for _try in range(5):
                try:
                    ret = subprocess.run(['git', 'push', 'origin', 'main'],
                                          cwd=str(BASE_DIR), capture_output=True, text=True,
                                          encoding='utf-8', errors='replace', timeout=180)
                    if ret.returncode == 0:
                        push_ok = True
                        break
                except subprocess.TimeoutExpired:
                    pass
                logger.warning(f'Git push 第{_try+1}次失败，重试...')
                time.sleep(5 * (_try + 1))
            if push_ok:
                logger.info('✅ Git 推送完成')
                _append('Git 推送', True, f'cleanup: {today}')
            else:
                logger.warning('Git push 5次均失败，下次爬取时会一起推送')
                _append('Git 推送', False, '5 次重试失败')
    except Exception as e:
        logger.warning(f'Git 推送失败(非致命): {e}')
        _append('Git 推送', False, str(e)[:80])

    _write_progress(100, '✅ 清洗完成',
                    f'删除 {total_removed} 条 · 剩余 {remaining} 条', steps, done=True)


if __name__ == '__main__':
    main()
