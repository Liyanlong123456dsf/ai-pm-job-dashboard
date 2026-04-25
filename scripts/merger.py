"""增量合并：将新抓取的岗位与现有数据去重合并"""
import json
import logging
import datetime
from pathlib import Path

logger = logging.getLogger('merger')

BASE_DIR = Path(__file__).parent.parent
DATA_FILE = BASE_DIR / 'jobs_data.json'
HISTORY_DIR = BASE_DIR / 'history'


def load_existing() -> tuple:
    if not DATA_FILE.exists():
        return {}, []
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    jobs = data.get('jobs', data if isinstance(data, list) else [])
    # Build key index
    key_set = set()
    for j in jobs:
        if '_key' in j:
            key_set.add(j['_key'])
        else:
            # Backward compat: generate key for old data
            from pipeline import dedup_key
            k = dedup_key(j)
            j['_key'] = k
            key_set.add(k)
    return key_set, jobs


def merge(existing_jobs: list, existing_keys: set, new_jobs: list) -> tuple:
    added = []
    refreshed = 0
    today_str = datetime.date.today().isoformat()

    # 建立 existing key -> index 映射，用于快速查找重复
    key_to_idx = {}
    for i, ej in enumerate(existing_jobs):
        k = ej.get('_key')
        if k:
            key_to_idx[k] = i

    for job in new_jobs:
        key = job.get('_key', '')
        if key and key not in existing_keys:
            existing_keys.add(key)
            job['_new'] = True  # mark as new for Dashboard
            added.append(job)
        elif key and key in key_to_idx:
            # 重复岗位：刷新日期（证明还在招），但保留首次爬取时间
            idx = key_to_idx[key]
            existing_jobs[idx]['_date'] = today_str
            # 如果旧数据没有 _crawled_at，从新数据补全
            if not existing_jobs[idx].get('_crawled_at') and job.get('_crawled_at'):
                existing_jobs[idx]['_crawled_at'] = job['_crawled_at']
            refreshed += 1

    merged = existing_jobs + added
    # Sort by avg salary descending
    merged.sort(key=lambda x: -x.get('avg', 0))

    logger.info(f'Merge: {len(existing_jobs)} existing + {len(added)} new = {len(merged)} total (refreshed {refreshed} dates)')
    return merged, len(added)


def save(jobs: list):
    meta = {
        'updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'total': len(jobs),
    }
    # Clean internal fields for frontend, but keep _key and _date for dedup
    KEEP = {'_key', '_date', '_crawled_at'}
    frontend_jobs = []
    for j in jobs:
        # 过滤 _ 前缀字段（除 KEEP），同时显式丢弃旧的 is_new 标记，避免历史 is_new 累积
        fj = {
            k: v for k, v in j.items()
            if k != 'is_new' and (not k.startswith('_') or k in KEEP)
        }
        if j.get('_new'):
            fj['is_new'] = True
        frontend_jobs.append(fj)

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump({'meta': meta, 'jobs': frontend_jobs}, f, ensure_ascii=False)

    logger.info(f'Saved {len(jobs)} jobs to {DATA_FILE}')


def save_snapshot(new_jobs: list):
    today = datetime.date.today().isoformat()
    snap_file = HISTORY_DIR / f'{today}.json'
    with open(snap_file, 'w', encoding='utf-8') as f:
        json.dump(new_jobs, f, ensure_ascii=False)
    logger.info(f'Snapshot saved: {snap_file} ({len(new_jobs)} jobs)')
