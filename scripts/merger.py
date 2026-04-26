"""增量合并：将新抓取的岗位与现有数据去重合并"""
import json
import logging
import datetime
import re
from pathlib import Path

logger = logging.getLogger('merger')

BASE_DIR = Path(__file__).parent.parent
DATA_FILE = BASE_DIR / 'jobs_data.json'
HISTORY_DIR = BASE_DIR / 'history'


JOB_DETAIL_RE = re.compile(r'^https://www\.zhipin\.com/job_detail/[A-Za-z0-9_.-]+\.html$')


def _norm_text(value) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _valid_job_url(url: str) -> bool:
    return bool(JOB_DETAIL_RE.match(str(url or '').strip()))


def _job_identity(job: dict) -> tuple:
    url = _norm_text(job.get('url') or job.get('link'))
    if _valid_job_url(url):
        return ('url', url)
    return (
        'text',
        _norm_text(job.get('title')).lower(),
        _norm_text(job.get('company')).lower(),
        _norm_text(job.get('city')).lower(),
        _norm_text(job.get('salary')).lower(),
    )


def _job_score(job: dict) -> tuple:
    url = _norm_text(job.get('url') or job.get('link'))
    desc = _norm_text(job.get('desc'))
    return (
        1 if _valid_job_url(url) else 0,
        1 if _norm_text(job.get('company')) else 0,
        1 if _norm_text(job.get('salary')) else 0,
        len(desc),
        _norm_text(job.get('_date')),
        _norm_text(job.get('_crawled_at')),
    )


def clean_jobs(jobs: list) -> tuple:
    cleaned_by_key = {}
    removed_invalid = 0
    removed_duplicate = 0
    stripped_bad_url = 0

    for raw in jobs:
        if not isinstance(raw, dict):
            removed_invalid += 1
            continue

        job = dict(raw)
        title = _norm_text(job.get('title'))
        company = _norm_text(job.get('company'))
        city = _norm_text(job.get('city'))
        salary = _norm_text(job.get('salary'))
        url = _norm_text(job.get('url') or job.get('link'))

        if url and not _valid_job_url(url):
            job.pop('url', None)
            job.pop('link', None)
            stripped_bad_url += 1
            url = ''

        if not title or not company or not city or not salary or not url:
            removed_invalid += 1
            continue

        job['title'] = title
        job['city'] = city
        job['salary'] = salary
        if company:
            job['company'] = company
        if url:
            job['url'] = url

        identity = _job_identity(job)
        existing = cleaned_by_key.get(identity)
        if existing is None:
            cleaned_by_key[identity] = job
        elif _job_score(job) > _job_score(existing):
            cleaned_by_key[identity] = job
            removed_duplicate += 1
        else:
            removed_duplicate += 1

    cleaned = list(cleaned_by_key.values())
    cleaned.sort(key=lambda x: -float(x.get('avg') or 0))
    stats = {
        'input': len(jobs),
        'output': len(cleaned),
        'removed_invalid': removed_invalid,
        'removed_duplicate': removed_duplicate,
        'stripped_bad_url': stripped_bad_url,
    }
    return cleaned, stats


def load_existing() -> tuple:
    if not DATA_FILE.exists():
        return {}, []
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    jobs = data.get('jobs', data if isinstance(data, list) else [])
    jobs, clean_stats = clean_jobs(jobs)
    if clean_stats['input'] != clean_stats['output'] or clean_stats['stripped_bad_url']:
        logger.info(f'Loaded and cleaned existing jobs: {clean_stats}')
    # Build key index
    key_set = set()
    for j in jobs:
        key_set.add(_job_identity(j))
    return key_set, jobs


def merge(existing_jobs: list, existing_keys: set, new_jobs: list) -> tuple:
    added = []
    refreshed = 0
    today_str = datetime.date.today().isoformat()

    # 建立 existing key -> index 映射，用于快速查找重复
    key_to_idx = {}
    for i, ej in enumerate(existing_jobs):
        key_to_idx[_job_identity(ej)] = i

    for job in new_jobs:
        key = _job_identity(job)
        if key not in existing_keys:
            existing_keys.add(key)
            job['_new'] = True  # mark as new for Dashboard
            added.append(job)
        elif key in key_to_idx:
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
    jobs, clean_stats = clean_jobs(jobs)
    meta = {
        'updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'total': len(jobs),
        'cleaned': clean_stats,
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

    logger.info(f'Saved {len(jobs)} cleaned jobs to {DATA_FILE} ({clean_stats})')


def save_snapshot(new_jobs: list):
    today = datetime.date.today().isoformat()
    snap_file = HISTORY_DIR / f'{today}.json'
    with open(snap_file, 'w', encoding='utf-8') as f:
        json.dump(new_jobs, f, ensure_ascii=False)
    logger.info(f'Snapshot saved: {snap_file} ({len(new_jobs)} jobs)')
