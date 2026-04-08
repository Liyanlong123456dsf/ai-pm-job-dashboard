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
    for job in new_jobs:
        key = job.get('_key', '')
        if key and key not in existing_keys:
            existing_keys.add(key)
            job['_new'] = True  # mark as new for Dashboard
            added.append(job)

    merged = existing_jobs + added
    # Sort by avg salary descending
    merged.sort(key=lambda x: -x.get('avg', 0))

    logger.info(f'Merge: {len(existing_jobs)} existing + {len(added)} new = {len(merged)} total')
    return merged, len(added)


def save(jobs: list):
    meta = {
        'updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'total': len(jobs),
    }
    # Clean internal fields for frontend
    frontend_jobs = []
    for j in jobs:
        fj = {k: v for k, v in j.items() if not k.startswith('_')}
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
