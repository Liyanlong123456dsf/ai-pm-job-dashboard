#!/usr/bin/env python3
"""
月度老数据清洗 — 检查超期岗位链接有效性
每月 1/15 日自动执行（由 auto_daily.py 调用）

流程：
  1. 读取 jobs_data.json
  2. 筛选 _date 超过 N 天 且 有 url 的岗位
  3. DrissionPage 逐条访问 url
  4. 判定岗位是否下架：
     - 页面含"已关闭/停止招聘/不存在" → 删除
     - 页面正常 → _date 更新为今天
     - 访问异常 → 跳过
  5. 保存更新后的 jobs_data.json
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
PROFILE_DIR = BASE_DIR / '.chrome_profile'
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)
CHECKPOINT_FILE = LOG_DIR / 'cleanup_checkpoint.json'

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


def main():
    parser = argparse.ArgumentParser(description='月度老数据清洗')
    parser.add_argument('--dry-run', action='store_true', help='只检查不修改')
    parser.add_argument('--limit', type=int, default=0, help='限制本次最多检查N条（0=不限）')
    parser.add_argument('--max-age', type=int, default=0, help='覆盖最大天数（0=用配置）')
    args = parser.parse_args()

    config = load_config()
    max_age = args.max_age if args.max_age > 0 else config['max_age_days']

    # 读取数据
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    jobs = data.get('jobs', [])
    today = date.today()
    cutoff = (today - timedelta(days=max_age)).isoformat()
    today_str = today.isoformat()

    # 筛选需要检查的岗位
    stale_indices = []
    for i, job in enumerate(jobs):
        job_date = job.get('_date', '9999-99-99')
        has_url = bool(job.get('url'))
        if has_url and job_date < cutoff:
            stale_indices.append(i)

    total_stale = len(stale_indices)
    if args.limit > 0:
        stale_indices = stale_indices[:args.limit]

    logger.info(f'总岗位: {len(jobs)}, 超过 {max_age} 天且有链接: {total_stale}, 本次检查: {len(stale_indices)}')

    if not stale_indices:
        logger.info('✅ 无需清洗，所有岗位都在有效期内')
        return

    if args.dry_run:
        logger.info('[DRY RUN] 仅列出需要检查的岗位:')
        for idx in stale_indices[:20]:
            j = jobs[idx]
            logger.info(f'  {j.get("title")} | {j.get("company")} | _date={j.get("_date")} | url={j.get("url","")[:60]}')
        if total_stale > 20:
            logger.info(f'  ... 还有 {total_stale - 20} 条')
        return

    # 启动浏览器
    from DrissionPage import ChromiumPage, ChromiumOptions
    co = ChromiumOptions()
    co.set_user_data_path(str(PROFILE_DIR))
    co.set_argument('--no-first-run')
    page = ChromiumPage(co)
    logger.info('✓ 浏览器已启动')

    # 加载断点 checkpoint（已检查过的 _key 集合）
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
        return

    refreshed = 0
    removed = 0
    skipped = 0
    remove_set = set()  # 记录要删除的索引

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
                logger.info(f'  ✗ [{check_idx}/{len(stale_indices)}] 已下架: {title} @ {company}')
                remove_set.add(job_idx)
                removed += 1
            else:
                jobs[job_idx]['_date'] = today_str
                logger.info(f'  ✓ [{check_idx}/{len(stale_indices)}] 仍有效，刷新日期: {title} @ {company}')
                refreshed += 1

        except Exception as e:
            logger.warning(f'  ? [{check_idx}/{len(stale_indices)}] 访问异常，跳过: {title} @ {company} | {e}')
            skipped += 1

        # 记录已检查
        if key:
            checked_keys.add(key)

        # 每 10 条中间保存 jobs_data.json + checkpoint
        if check_idx % 10 == 0:
            logger.info(f'  进度: {check_idx}/{len(stale_indices)} (刷新 {refreshed}, 删除 {removed}, 跳过 {skipped})')
            _save_checkpoint(checked_keys)
            _save_jobs(data, jobs, remove_set)

        # 防封策略
        if check_idx % 20 == 0:
            for _ in range(random.randint(1, 3)):
                page.scroll.down(random.randint(100, 300))
                time.sleep(random.uniform(0.3, 0.8))
            time.sleep(random.uniform(2, 4))
        else:
            random_delay(0.5, 1.2)

    page.quit()

    # 删除已下架岗位
    if remove_set:
        jobs = [j for i, j in enumerate(jobs) if i not in remove_set]

    # 最终保存
    data['jobs'] = jobs
    data['meta']['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    data['meta']['total'] = len(jobs)
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

    # 清理 checkpoint（全部完成）
    _clear_checkpoint()

    logger.info('=' * 50)
    logger.info(f'✅ 清洗完成!')
    logger.info(f'   检查: {len(stale_indices)} 条')
    logger.info(f'   刷新日期: {refreshed} 条')
    logger.info(f'   删除下架: {removed} 条')
    logger.info(f'   跳过异常: {skipped} 条')
    logger.info(f'   剩余总计: {len(jobs)} 条')
    logger.info('=' * 50)

    # 写入清洗记录
    record = {
        'date': today_str,
        'checked': len(stale_indices),
        'refreshed': refreshed,
        'removed': removed,
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


if __name__ == '__main__':
    main()
