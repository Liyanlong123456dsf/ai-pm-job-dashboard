#!/usr/bin/env python3
"""从 CSV 表格回填 BOSS 链接到 jobs_data.json"""
import csv, json

CSV_PATH = '/Users/harry/Desktop/工作集合表/AIPM4月岗位需求收集_数据表.csv'
JSON_PATH = '/Users/harry/Desktop/工作集合表/jobs_data.json'

# 1. 读 CSV 构建索引
with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

idx_tc, idx_tci, idx_t = {}, {}, {}
for r in rows:
    title = (r.get('岗位名称') or '').strip()
    company = (r.get('公司名称（全称）') or '').strip()
    city = (r.get('所在城市') or '').strip()
    url = (r.get('BOSS链接') or '').strip().split('?')[0]
    if not url.startswith('http') or not title:
        continue
    if company:
        idx_tc[f'{title}_{company}'] = url
    if city:
        for c in city.replace('/', ',').replace('、', ',').split(','):
            c = c.strip().rstrip('市').rstrip('省')
            if c:
                idx_tci[f'{title}_{c}'] = url
    idx_t[title] = url

print(f'CSV索引: title+company={len(idx_tc)}, title+city={len(idx_tci)}, title={len(idx_t)}')

# 2. 读 JSON 匹配
with open(JSON_PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)
jobs = data.get('jobs', [])

matched = 0
for j in jobs:
    t, co, ci = j.get('title',''), j.get('company',''), j.get('city','')
    url = idx_tc.get(f'{t}_{co}') or idx_tci.get(f'{t}_{ci}') or idx_t.get(t)
    if url:
        j['url'] = url
        matched += 1

print(f'匹配: {matched}/{len(jobs)}')

# 3. 保存
data['jobs'] = jobs
with open(JSON_PATH, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print('已保存')
