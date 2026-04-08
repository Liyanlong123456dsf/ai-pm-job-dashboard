#!/usr/bin/env python3
"""导出统一格式总表：合并 CSV + XLSX + jobs_data.json 去重输出"""
import csv, json, re, openpyxl
from collections import OrderedDict

BASE = '/Users/harry/Desktop/工作集合表'
CSV_PATH = f'{BASE}/AIPM4月岗位需求收集_数据表.csv'
XLSX_PATH = f'{BASE}/五期1组AIPM四月岗位收集.xlsx'
JSON_PATH = f'{BASE}/jobs_data.json'
OUTPUT_CSV = f'{BASE}/AIPM总表_统一格式.csv'

HEADER = ['公司名称（全称）', '岗位名称', '所在城市', '薪资区间', 'BOSS链接',
          '年限要求', '学历要求', '方向分类', '关键词', '岗位描述', '数据来源']

def norm_key(title, company):
    s = re.sub(r'[\s\-_（(）)·/|，,]', '', f'{title}_{company}'.lower())
    return s

all_rows = OrderedDict()  # norm_key -> row dict

# 1. 读 CSV
with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        title = (r.get('岗位名称') or '').strip()
        company = (r.get('公司名称（全称）') or '').strip()
        if not title:
            continue
        k = norm_key(title, company)
        if k not in all_rows:
            all_rows[k] = {
                '公司名称（全称）': company,
                '岗位名称': title,
                '所在城市': (r.get('所在城市') or '').strip(),
                '薪资区间': (r.get('薪资区间') or '').strip(),
                'BOSS链接': (r.get('BOSS链接') or '').strip().split('?')[0],
                '年限要求': (r.get('年限要求') or '').strip(),
                '学历要求': (r.get('学历要求') or '').strip(),
                '方向分类': '',
                '关键词': '',
                '岗位描述': (r.get('岗位详情') or '').strip()[:500],
                '数据来源': 'CSV原表',
            }
print(f'CSV: {len(all_rows)} 条')

# 2. 读 XLSX
wb = openpyxl.load_workbook(XLSX_PATH, read_only=False)
ws = wb['数据表']
xlsx_add = 0
for row in ws.iter_rows(min_row=2, max_col=8, values_only=True):
    company = str(row[0] or '').strip()
    title = str(row[4] or '').strip()
    if not title:
        continue
    k = norm_key(title, company)
    if k not in all_rows:
        all_rows[k] = {
            '公司名称（全称）': company,
            '岗位名称': title,
            '所在城市': str(row[2] or '').strip(),
            '薪资区间': str(row[3] or '').strip(),
            'BOSS链接': str(row[5] or '').strip().split('?')[0] if row[5] else '',
            '年限要求': str(row[6] or '').strip() if len(row) > 6 and row[6] else '',
            '学历要求': str(row[7] or '').strip() if len(row) > 7 and row[7] else '',
            '方向分类': '',
            '关键词': '',
            '岗位描述': str(row[1] or '').strip()[:500],
            '数据来源': 'XLSX原表',
        }
        xlsx_add += 1
print(f'XLSX新增: {xlsx_add}, 累计: {len(all_rows)}')

# 3. 读 jobs_data.json (补入爬虫新增)
with open(JSON_PATH, 'r', encoding='utf-8') as f:
    jobs = json.load(f).get('jobs', [])
json_add = 0
for j in jobs:
    title = j.get('title', '')
    company = j.get('company', '')
    k = norm_key(title, company)
    if k not in all_rows:
        all_rows[k] = {
            '公司名称（全称）': company,
            '岗位名称': title,
            '所在城市': j.get('city', ''),
            '薪资区间': j.get('salary', ''),
            'BOSS链接': j.get('url', ''),
            '年限要求': j.get('exp', ''),
            '学历要求': j.get('edu', ''),
            '方向分类': '、'.join(j.get('cats', [])),
            '关键词': '、'.join(j.get('kw', [])),
            '岗位描述': (j.get('desc') or '')[:500],
            '数据来源': '爬虫新增',
        }
        json_add += 1
    else:
        # 补充已有记录的分类和链接
        existing = all_rows[k]
        if not existing['BOSS链接'] and j.get('url'):
            existing['BOSS链接'] = j['url']
        if not existing['方向分类'] and j.get('cats'):
            existing['方向分类'] = '、'.join(j['cats'])
        if not existing['关键词'] and j.get('kw'):
            existing['关键词'] = '、'.join(j['kw'])
        if not existing['岗位描述'] and j.get('desc'):
            existing['岗位描述'] = j['desc'][:500]

print(f'爬虫新增: {json_add}, 总计: {len(all_rows)}')

# 4. 输出
with open(OUTPUT_CSV, 'w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=HEADER)
    writer.writeheader()
    for row in all_rows.values():
        writer.writerow(row)

print(f'\n✅ 总表已导出: {OUTPUT_CSV}')
print(f'   总行数: {len(all_rows)}')
