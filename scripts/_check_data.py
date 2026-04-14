import json
from pathlib import Path

BASE = Path(r'e:\桌面\工作集合表')
d = json.load(open(BASE / 'jobs_data.json', 'r', encoding='utf-8'))
jobs = d.get('jobs', [])
meta = d.get('meta', {})

print(f"total={len(jobs)}")
print(f"meta={json.dumps(meta, ensure_ascii=False)}")

has_url = sum(1 for j in jobs if j.get('url'))
has_desc = sum(1 for j in jobs if j.get('description'))
no_url = len(jobs) - has_url
no_desc = len(jobs) - has_desc
print(f"has_url={has_url}  no_url={no_url}")
print(f"has_desc={has_desc}  no_desc={no_desc}")

if jobs:
    sample = jobs[0]
    print(f"sample_keys={list(sample.keys())}")

dates = sorted(set(j.get('crawl_date', '') for j in jobs if j.get('crawl_date')))
print(f"date_count={len(dates)}")
if dates:
    print(f"earliest={dates[0]}  latest={dates[-1]}")

# check dist
dist_file = BASE / 'dist' / 'jobs_data.json'
if dist_file.exists():
    dd = json.load(open(dist_file, 'r', encoding='utf-8'))
    dj = dd.get('jobs', [])
    print(f"dist_total={len(dj)}")
    dhas_url = sum(1 for j in dj if j.get('url'))
    dhas_desc = sum(1 for j in dj if j.get('description'))
    print(f"dist_has_url={dhas_url}  dist_has_desc={dhas_desc}")
