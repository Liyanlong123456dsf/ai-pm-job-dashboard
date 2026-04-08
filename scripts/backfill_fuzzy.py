#!/usr/bin/env python3
"""模糊匹配补全剩余岗位链接"""
import csv, json, re

CSV_PATH = '/Users/harry/Desktop/工作集合表/AIPM4月岗位需求收集_数据表.csv'
JSON_PATH = '/Users/harry/Desktop/工作集合表/jobs_data.json'

def norm(s):
    return re.sub(r'[\s\-_（(）)·/|，,]', '', s.lower())

with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

csv_idx = {}
for r in rows:
    title = (r.get('岗位名称') or '').strip()
    company = (r.get('公司名称（全称）') or '').strip()
    url = (r.get('BOSS链接') or '').strip().split('?')[0]
    if not url.startswith('http') or not title:
        continue
    k = norm(title)
    if k not in csv_idx:
        csv_idx[k] = url
    if company:
        csv_idx[norm(title + company)] = url

with open(JSON_PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)
jobs = data.get('jobs', [])

extra = 0
for j in jobs:
    if j.get('url'):
        continue
    t, co = j.get('title',''), j.get('company','')
    url = csv_idx.get(norm(t + co)) or csv_idx.get(norm(t))
    if url:
        j['url'] = url
        extra += 1

total_url = sum(1 for j in jobs if j.get('url'))
print(f'模糊匹配新增: {extra}, 总有链接: {total_url}/{len(jobs)}')

data['jobs'] = jobs
with open(JSON_PATH, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print('done')
