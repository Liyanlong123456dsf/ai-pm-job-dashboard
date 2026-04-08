"""数据清洗 & 标准化管道：将爬虫原始数据转为 Dashboard 格式"""
import re
import json
import hashlib
import logging
from pathlib import Path

logger = logging.getLogger('pipeline')

CONFIG_PATH = Path(__file__).parent.parent / 'config' / 'keywords.json'

with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    _cfg = json.load(f)

CAT_RULES = _cfg.get('cat_rules', {})


def parse_salary(s: str) -> float:
    if not s:
        return 0
    s = str(s).strip()
    m = re.search(r'(\d+)-(\d+)K', s)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        bonus = re.search(r'(\d+)薪', s)
        months = int(bonus.group(1)) if bonus else 12
        return round((lo + hi) / 2 * months / 12, 1)
    m2 = re.search(r'(\d+)-(\d+)元/天', s)
    if m2:
        lo, hi = int(m2.group(1)), int(m2.group(2))
        return round((lo + hi) / 2 * 22 / 1000, 1)
    m3 = re.search(r'(\d+)-(\d+)元/月', s)
    if m3:
        lo, hi = int(m3.group(1)), int(m3.group(2))
        return round((lo + hi) / 2 / 1000, 1)
    return 0


def classify(text: str) -> tuple:
    cats = []
    matched_kw = []
    text_lower = text.lower()
    for cat_name, keywords in CAT_RULES.items():
        hits = [k for k in keywords if k.lower() in text_lower]
        if hits:
            cats.append(cat_name)
            matched_kw.extend(hits)
    return cats, list(set(matched_kw))


def salary_tier(avg: float) -> str:
    if avg >= 50:
        return '50K+'
    elif avg >= 30:
        return '30-50K'
    elif avg >= 15:
        return '15-30K'
    elif avg >= 8:
        return '8-15K'
    else:
        return '<8K'


def clean_desc(desc) -> str:
    if isinstance(desc, list):
        desc = ' '.join(str(x) for x in desc)
    desc = str(desc or '')
    for noise in ['BOSS直聘', 'kanzhun', 'boss', '直聘', '来自BOSS直聘',
                  '微信扫码分享举报', '微信扫码分享', '举报', '职位描述']:
        desc = desc.replace(noise, '')
    return re.sub(r'\s+', ' ', desc).strip()


def norm_city(city: str) -> str:
    city = str(city or '').strip()
    city = re.sub(r'[市省]$', '', city)
    city = city.split('·')[0]
    return city


def dedup_key(job: dict) -> str:
    raw = f"{job.get('company','')}{job.get('title','')}{norm_city(job.get('city',''))}"
    return hashlib.md5(raw.encode()).hexdigest()


def process_one(raw: dict) -> dict:
    title = str(raw.get('title') or '')[:40]
    company = str(raw.get('company') or '')[:25]
    city = norm_city(raw.get('city') or raw.get('_city_name', ''))
    salary = str(raw.get('salary') or '')
    exp = str(raw.get('exp') or '')
    edu = str(raw.get('edu') or '')
    desc = clean_desc(raw.get('desc', ''))

    if not title or not company:
        return None

    text = f'{company} {title} {desc}'
    cats, kw = classify(text)

    # AI PM 岗位即使没匹配到电商/视频/新媒体关键词也保留
    # 但需要标题包含 AI / 产品 相关词
    ai_related = any(w in title for w in ['AI', 'ai', 'AIGC', '大模型', '智能', '算法'])
    if not cats and not ai_related:
        return None

    avg = parse_salary(salary)
    tier = salary_tier(avg)

    url = str(raw.get('url') or '').strip()

    result = {
        'title': title,
        'company': company,
        'city': city,
        'salary': salary,
        'avg': avg,
        'tier': tier,
        'exp': exp,
        'edu': edu,
        'cats': cats if cats else ['AI通用'],
        'kw': kw,
        'desc': desc,
        '_key': dedup_key({'title': title, 'company': company, 'city': city}),
        '_date': __import__('datetime').date.today().isoformat(),
    }
    if url:
        result['url'] = url
    return result


def process_batch(raw_list: list) -> list:
    results = []
    seen = set()
    for raw in raw_list:
        job = process_one(raw)
        if job and job['_key'] not in seen:
            seen.add(job['_key'])
            results.append(job)
    logger.info(f'Pipeline: {len(raw_list)} raw -> {len(results)} cleaned')
    return results
