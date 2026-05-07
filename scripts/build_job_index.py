#!/usr/bin/env python3
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_FILE = BASE_DIR / 'jobs_data.json'
INDEX_FILE = BASE_DIR / 'jobs_index.json'
DESC_SHORT_LEN = 180
INDEX_FIELDS = [
    'title', 'company', 'city', 'salary', 'avg', 'exp', 'edu', 'cats', 'kw',
    'url', '_key', '_date', '_crawled_at', 'is_new', 'tier', 'months', 'direction',
]


def _short_desc(value, limit=DESC_SHORT_LEN):
    text = ' '.join(str(value or '').split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + '…'


def build_index_payload(data):
    jobs = data.get('jobs', data if isinstance(data, list) else [])
    jobs = [j for j in jobs if isinstance(j, dict)]
    light_jobs = []
    for job in jobs:
        item = {k: job.get(k) for k in INDEX_FIELDS if k in job}
        item['desc_short'] = _short_desc(job.get('desc'))
        light_jobs.append(item)
    meta = dict(data.get('meta', {}) if isinstance(data, dict) else {})
    meta['total'] = len(light_jobs)
    meta['light'] = True
    meta['source'] = 'jobs_data.json'
    meta['desc_short_len'] = DESC_SHORT_LEN
    return {'meta': meta, 'jobs': light_jobs}


def build_index(data_file=DATA_FILE, index_file=INDEX_FILE):
    data_file = Path(data_file)
    index_file = Path(index_file)
    data = json.loads(data_file.read_text(encoding='utf-8'))
    payload = build_index_payload(data)
    index_file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return payload


def main():
    payload = build_index()
    print(f"Saved {len(payload.get('jobs', []))} light jobs to {INDEX_FILE}")


if __name__ == '__main__':
    main()
