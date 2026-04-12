#!/usr/bin/env python3
"""从 CSV + XLSX 两个表格回填 BOSS 链接到 jobs_data.json
注：原始 CSV/XLSX 已清理，此脚本仅在文件存在时执行，否则安全跳过。"""
import sys, io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import csv, json, re, os
from pathlib import Path

BASE = str(Path(__file__).parent.parent)
CSV_PATH = f'{BASE}/AIPM4月岗位需求收集_数据表.csv'
XLSX_PATH = f'{BASE}/五期1组AIPM四月岗位收集.xlsx'
JSON_PATH = f'{BASE}/jobs_data.json'

if not os.path.exists(CSV_PATH) and not os.path.exists(XLSX_PATH):
    print('⏭️  CSV/XLSX 源文件不存在，跳过链接回填')
    exit(0)

import openpyxl

def norm(s):
    return re.sub(r'[\s\-_（(）)·/|，,]', '', s.lower())

def add_to_index(title, company, city, url, idx_tc, idx_tci, idx_t, idx_norm):
    if not url.startswith('http') or not title:
        return
    if company:
        idx_tc[f'{title}_{company}'] = url
    if city:
        for c in city.replace('/', ',').replace('、', ',').split(','):
            c = c.strip().rstrip('市').rstrip('省')
            if c:
                idx_tci[f'{title}_{c}'] = url
    idx_t[title] = url
    k = norm(title)
    if k not in idx_norm:
        idx_norm[k] = url
    if company:
        idx_norm[norm(title + company)] = url

idx_tc, idx_tci, idx_t, idx_norm = {}, {}, {}, {}

# 1. 读 CSV
with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))
for r in rows:
    title = (r.get('岗位名称') or '').strip()
    company = (r.get('公司名称（全称）') or '').strip()
    city = (r.get('所在城市') or '').strip()
    url = (r.get('BOSS链接') or '').strip().split('?')[0]
    add_to_index(title, company, city, url, idx_tc, idx_tci, idx_t, idx_norm)
print(f'CSV: {len(rows)} 行')

# 2. 读 XLSX
wb = openpyxl.load_workbook(XLSX_PATH, read_only=False)
ws = wb['数据表']
xlsx_count = 0
for row in ws.iter_rows(min_row=2, max_col=6, values_only=True):
    company = str(row[0] or '').strip()
    city = str(row[2] or '').strip()
    title = str(row[4] or '').strip()
    url = str(row[5] or '').strip().split('?')[0]
    add_to_index(title, company, city, url, idx_tc, idx_tci, idx_t, idx_norm)
    xlsx_count += 1
print(f'XLSX: {xlsx_count} 行')
print(f'合并索引: exact={len(idx_tc)}, city={len(idx_tci)}, title={len(idx_t)}, fuzzy={len(idx_norm)}')

# 2. 读 JSON 匹配
with open(JSON_PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)
jobs = data.get('jobs', [])

matched = 0
for j in jobs:
    t, co, ci = j.get('title',''), j.get('company',''), j.get('city','')
    url = (idx_tc.get(f'{t}_{co}') or idx_tci.get(f'{t}_{ci}') or idx_t.get(t)
           or idx_norm.get(norm(t + co)) or idx_norm.get(norm(t)))
    if url:
        j['url'] = url
        matched += 1

print(f'匹配: {matched}/{len(jobs)}')

# 3. 保存
data['jobs'] = jobs
with open(JSON_PATH, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print('已保存')
