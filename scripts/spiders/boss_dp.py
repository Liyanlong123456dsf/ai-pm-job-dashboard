#!/usr/bin/env python3
"""
BOSS直聘爬虫 - API拦截模式 + 强相关过滤
基于 boss-zp-main 的 API 拦截方案，速度快、数据完整

用法:
  python boss_dp.py --merge           # 全量抓取并合并到 Dashboard
  python boss_dp.py --quick --merge   # 快速模式(≈8分钟)
  python boss_dp.py --city 杭州       # 只抓指定城市
"""
import sys, io, os
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import json
import time
import random
import math
import logging
import argparse
import re
from pathlib import Path

logger = logging.getLogger('spider.boss_dp')

# ==================== 配置 ====================

CONFIG_DIR = Path(__file__).parent.parent.parent / 'config'
CONFIG_FILE = CONFIG_DIR / 'keywords.json'
# 持久化登录 Profile：支持通过环境变量 AI_PM_BOSS_PROFILE 切换账号
# - 绝对路径：直接使用
# - 相对路径：相对项目根目录
# - 未设置：回退到 .chrome_profile（单账号/兼容旧行为）
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_env_profile = os.environ.get('AI_PM_BOSS_PROFILE', '').strip()
if _env_profile:
    _p = Path(_env_profile)
    PROFILE_DIR = _p if _p.is_absolute() else (_PROJECT_ROOT / _p)
else:
    PROFILE_DIR = _PROJECT_ROOT / '.chrome_profile'

# Chrome 调试端口：不同账号需用不同端口，避免 DrissionPage 连到已有实例
CHROME_PORT = int(os.environ.get('AI_PM_CHROME_PORT', '9222'))

DEFAULT_KEYWORDS = [
    'AI产品经理', 'AIGC产品经理', '大模型产品经理', 'LLM产品经理', '智能体产品经理',
    'Agent产品经理', '多模态产品经理', 'NLP产品经理', '对话产品经理',
    'AI平台产品经理', 'AI工具产品经理', 'AI应用产品经理', 'AI交互产品经理', 'AI搜索产品经理', 'AI推荐产品经理',
    'AI策略产品经理', 'AI商业化产品经理', 'AI增长产品经理', 'AI数据产品经理', 'AI中台产品经理',
    'AI产品专家', '生成式AI产品经理', 'Copilot产品经理', 'RAG产品经理', 'AI助手产品经理',
    '智能客服产品经理', 'AI办公产品经理', 'AI教育产品经理', 'AI医疗产品经理', 'AI金融产品经理',
    'AI风控产品经理', 'AI电商产品经理', 'AI营销产品经理', 'AI内容产品经理', 'AI视频产品经理',
    'AI语音产品经理', 'AI视觉产品经理', 'AI机器人产品经理', '机器学习产品经理', '深度学习产品经理',
    '模型平台产品经理', 'AISaaS产品经理', 'ToB AI产品经理', '企业AI产品经理', '智能产品经理',
    '大模型应用产品经理', '智能体平台产品经理', 'AI工作流产品经理', 'AI解决方案产品经理', 'AI产品负责人',
]

DEFAULT_KEYWORD_SETTINGS = {
    'sample_min': 5,
    'sample_max': 8,
    'target_count': 50,
    'refresh_day': 1,
    'refresh_retry_hours': 6,
    'seed_queries': [
        'AI产品经理', 'AIGC产品经理', '大模型产品经理', '智能体产品经理', 'Agent产品经理',
        '多模态产品经理', '对话产品经理', 'AI商业化产品经理', 'AI平台产品经理',
        'AI交互产品经理',
        'AI工具产品经理', 'AI应用产品经理',
    ],
    'last_refreshed_at': '',
    'last_refreshed_month': '',
    'last_refresh_source_counts': {
        'suggestions': 0,
        'titles': 0,
        'final_keywords': 0,
    },
}

# 翻页与滚动
MAX_PAGES = 3           # 标准模式最多3页
MAX_SCROLLS_PER_PAGE = 2

# 防封参数 — 强硬省时版，在安全边界内压缩等待
MIN_DELAY, MAX_DELAY = 0.8, 1.8
KEYWORD_REST_MIN, KEYWORD_REST_MAX = 2, 5
CITY_REST_MIN, CITY_REST_MAX = 3, 8
DETAIL_DELAY_MIN, DETAIL_DELAY_MAX = 0.8, 1.5
DETAIL_BATCH_PAUSE = (3, 6)    # 每批详情后的短休息
DETAIL_BATCH_SIZE = 25         # 每批25个，减少批次间休息次数

# 强相关过滤：岗位名必须命中以下任一关键词才算"AI PM 强相关"
RELEVANT_KEYWORDS = [
    'AI', 'ai', 'AIGC', '人工智能', '大模型', 'LLM', 'GPT',
    '智能', '算法', 'NLP', '机器学习', 'ML', '深度学习',
    '产品经理', '产品负责人', '产品总监', '产品专家',
    '智能体', 'Agent',
]

# 扩展 AI 词库（用于 is_relevant 模糊匹配）
_AI_TERMS = [
    'AI', 'AIGC', 'AGI', '人工智能', '大模型', 'LLM', 'GPT', 'NLP',
    '智能', '算法', '机器学习', 'ML', '深度学习', 'DL', '智能体', 'AGENT',
    'CV', '计算机视觉', '自动驾驶', '机器人', 'ROBOTICS', '语音', 'TTS', 'ASR',
    '多模态', 'MULTIMODAL', '生成式', 'GENERATIVE', 'GENAI',
    'COPILOT', 'CHATBOT', 'RAG', 'MLOPS', 'FOUNDATION MODEL',
    '向量', 'EMBEDDING', 'TRANSFORMER', '预训练', '微调',
    '推荐', '搜索', '策略', '数据', '对话', '知识图谱',
]
_PM_TERMS = [
    '产品', 'PRODUCT', '产品经理', '产品负责', '产品总监', '产品专家',
    'PM', '产品策划', '产品运营',
]

_KEYWORD_DIRECTION_TERMS = [
    '大模型', 'AIGC', '生成式AI', 'LLM', '智能体', 'AGENT', '多模态', 'NLP', 'COPILOT', 'RAG',
    '平台', '工具', '商业化', '增长', '数据', '搜索', '推荐', '策略', '对话', '客服', '电商', '营销',
    '内容', '视频', '语音', '视觉', '机器人', '办公', '教育', '医疗', '金融', '风控', 'SAAS', '工作流', '解决方案',
]
_EXCLUDED_KEYWORD_TERMS = [
    '销售', '开发', '工程师', '测试', '实施', '运维', '实习', '兼职', '主播', '顾问', '助理', '管培',
]

_CANONICAL_KEYWORD_RULES = [
    ('AI产品经理', ['AI产品经理', 'AI 产品经理', 'AI方向', 'AI NATIVE', 'AI C 端', 'AI服务', '产品经理(AI', '产品经理-AI']),
    ('智能体平台产品经理', ['智能体平台']),
    ('模型平台产品经理', ['模型平台']),
    ('大模型应用产品经理', ['大模型应用']),
    ('RAG产品经理', ['RAG']),
    ('Copilot产品经理', ['COPILOT']),
    ('AI工作流产品经理', ['工作流', 'WORKFLOW']),
    ('AI解决方案产品经理', ['解决方案']),
    ('AI搜索产品经理', ['搜索', '搜推']),
    ('AI推荐产品经理', ['推荐', '归因']),
    ('AI策略产品经理', ['策略']),
    ('AI商业化产品经理', ['商业化']),
    ('AI增长产品经理', ['增长', '流量']),
    ('AI数据产品经理', ['数据']),
    ('AI中台产品经理', ['中台']),
    ('智能客服产品经理', ['客服', '坐席', '呼叫']),
    ('对话产品经理', ['对话', '聊天', 'CHATBOT', '问答', '陪伴', 'CHATGPT', '智能对话']),
    ('AI营销产品经理', ['营销', '广告', '投放']),
    ('AI电商产品经理', ['电商', '淘宝', '天猫', '京东', '拼多多', '亚马逊', 'SHOPEE', '独立站']),
    ('AI内容产品经理', ['内容', '文案', '创作']),
    ('AI视频产品经理', ['视频', '短视频', '短剧', '直播', '影像']),
    ('AI语音产品经理', ['语音', 'TTS', 'ASR', '音乐', '写歌']),
    ('AI视觉产品经理', ['视觉', '图像', 'CV']),
    ('AI机器人产品经理', ['机器人', '具身']),
    ('AI办公产品经理', ['办公', '效率', '协同']),
    ('AI教育产品经理', ['教育']),
    ('AI医疗产品经理', ['医疗']),
    ('AI金融产品经理', ['金融']),
    ('AI风控产品经理', ['风控']),
    ('AISaaS产品经理', ['SAAS']),
    ('ToB AI产品经理', ['TOB', 'B端']),
    ('企业AI产品经理', ['企业']),
    ('AI平台产品经理', ['平台']),
    ('AI工具产品经理', ['工具']),
    ('AI应用产品经理', ['应用', 'APP']),
    ('AI交互产品经理', ['AI交互', '智能交互', '多模态交互']),
    ('AI助手产品经理', ['助手']),
    ('大模型产品经理', ['大模型', '语言模型', '基座模型', 'FOUNDATION MODEL']),
    ('LLM产品经理', ['LLM']),
    ('AIGC产品经理', ['AIGC', '生成式AI', 'GENERATIVE', 'GENAI', 'GPT']),
    ('智能体产品经理', ['智能体']),
    ('Agent产品经理', ['AGENT']),
    ('多模态产品经理', ['多模态']),
    ('机器学习产品经理', ['机器学习', 'ML']),
    ('深度学习产品经理', ['深度学习', 'DL']),
    ('AI产品负责人', ['产品负责人', '产品总监']),
    ('AI产品专家', ['产品专家']),
    ('智能产品经理', ['智能产品', '智能硬件']),
]

def _safe_int(value, default):
    try:
        return int(value)
    except Exception:
        return default

def _normalize_keyword_source_text(text):
    text = str(text or '').replace('\u3000', ' ').strip()
    if not text:
        return ''
    text = text.split('\n', 1)[0].strip()
    text = text.replace('（', '(').replace('）', ')').replace('【', '[').replace('】', ']')
    text = re.sub(r'\s+', ' ', text)
    replacements = [
        (r'(?i)(?<![A-Za-z])aigc(?![A-Za-z])', 'AIGC'),
        (r'(?i)(?<![A-Za-z])ai(?![A-Za-z])', 'AI'),
        (r'(?i)(?<![A-Za-z])llm(?![A-Za-z])', 'LLM'),
        (r'(?i)(?<![A-Za-z])nlp(?![A-Za-z])', 'NLP'),
        (r'(?i)(?<![A-Za-z])rag(?![A-Za-z])', 'RAG'),
        (r'(?i)(?<![A-Za-z])agent(?![A-Za-z])', 'Agent'),
        (r'(?i)(?<![A-Za-z])copilot(?![A-Za-z])', 'Copilot'),
        (r'(?i)(?<![A-Za-z])saas(?![A-Za-z])', 'SaaS'),
        (r'(?i)(?<![A-Za-z])tob(?![A-Za-z])', 'ToB'),
        (r'(?i)(?<![A-Za-z])gpt(?![A-Za-z])', 'GPT'),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text)
    text = re.sub(r'\s*\(\s*', '(', text)
    text = re.sub(r'\s*\)\s*', ')', text)
    text = re.sub(r'\s*/\s*', '/', text)
    text = re.sub(r'\s*-\s*', '-', text)
    text = text.replace('[', '').replace(']', '')
    text = re.sub(r'^(招聘|诚聘|急聘)\s*', '', text)
    text = re.sub(r'\s*(招聘|诚聘)$', '', text)
    return text.strip('·-|_/,:：;；,.，、[]【】')

def _clean_keyword(text):
    text = _normalize_keyword_source_text(text)
    if not text:
        return ''
    if 2 <= len(text) <= 24:
        return text
    return ''

def _merge_unique_terms(*groups):
    merged = []
    seen = set()
    for group in groups:
        for item in group or []:
            term = _clean_keyword(item)
            if term and term not in seen:
                seen.add(term)
                merged.append(term)
    return merged

def _keyword_settings(config):
    settings = dict(DEFAULT_KEYWORD_SETTINGS)
    settings.update(config.get('keyword_settings') or {})
    settings['sample_min'] = max(1, _safe_int(settings.get('sample_min'), DEFAULT_KEYWORD_SETTINGS['sample_min']))
    settings['sample_max'] = max(settings['sample_min'], _safe_int(settings.get('sample_max'), DEFAULT_KEYWORD_SETTINGS['sample_max']))
    settings['target_count'] = max(10, _safe_int(settings.get('target_count'), DEFAULT_KEYWORD_SETTINGS['target_count']))
    settings['refresh_day'] = min(28, max(1, _safe_int(settings.get('refresh_day'), DEFAULT_KEYWORD_SETTINGS['refresh_day'])))
    settings['refresh_retry_hours'] = max(1, _safe_int(settings.get('refresh_retry_hours'), DEFAULT_KEYWORD_SETTINGS['refresh_retry_hours']))
    settings['seed_queries'] = _merge_unique_terms(settings.get('seed_queries') or [], DEFAULT_KEYWORD_SETTINGS['seed_queries'])
    settings['last_refreshed_at'] = str(settings.get('last_refreshed_at') or '')
    settings['last_refreshed_month'] = str(settings.get('last_refreshed_month') or '')
    counts = settings.get('last_refresh_source_counts') or {}
    settings['last_refresh_source_counts'] = {
        'suggestions': max(0, _safe_int(counts.get('suggestions'), 0)),
        'titles': max(0, _safe_int(counts.get('titles'), 0)),
        'final_keywords': max(0, _safe_int(counts.get('final_keywords'), 0)),
    }
    return settings

def _keyword_variants_from_raw(raw):
    source = _normalize_keyword_source_text(raw)
    if not source:
        return []
    upper = source.upper()
    has_ai = any(kw.upper() in upper for kw in _AI_TERMS)
    has_pm = any(kw.upper() in upper for kw in _PM_TERMS)
    if not (has_ai or has_pm):
        return []
    variants = []
    for canonical, tokens in _CANONICAL_KEYWORD_RULES:
        if any(token.upper() in upper for token in tokens):
            variants.append(canonical)
    if not variants and source in DEFAULT_KEYWORDS:
        cleaned = _clean_keyword(source)
        if cleaned and _looks_like_search_keyword(cleaned):
            variants.append(cleaned)
    if not variants and has_ai and has_pm:
        variants.append('AI产品经理')
    return _merge_unique_terms(variants[:4])

def sanitize_keyword_library(terms, target_count=50):
    cleaned = []
    for raw in terms or []:
        variants = _keyword_variants_from_raw(raw)
        if variants:
            cleaned.extend(variants)
    cleaned = _merge_unique_terms(cleaned)
    if len(cleaned) < target_count:
        for term in DEFAULT_KEYWORDS:
            if term not in cleaned:
                cleaned.append(term)
            if len(cleaned) >= target_count:
                break
    return cleaned[:target_count]

def _looks_like_search_keyword(term):
    term = _clean_keyword(term)
    if not term:
        return False
    upper = term.upper()
    if any(bad.upper() in upper for bad in _EXCLUDED_KEYWORD_TERMS):
        return False
    has_ai = any(kw.upper() in upper for kw in _AI_TERMS)
    has_pm = any(kw.upper() in upper for kw in _PM_TERMS)
    has_direction = any(kw.upper() in upper for kw in _KEYWORD_DIRECTION_TERMS)
    return has_ai and (has_pm or has_direction)

def _keyword_rank(term, entry):
    upper = term.upper()
    score = entry.get('score', 0)
    if '产品经理' in term:
        score += 10
    elif '产品负责人' in term or '产品专家' in term:
        score += 8
    elif '产品' in term:
        score += 5
    for token in ['大模型', 'AIGC', '生成式AI', 'LLM', 'AGENT', '智能体', '多模态', 'NLP', 'COPILOT', 'RAG', 'AI']:
        if token.upper() in upper:
            score += 2
    for token in ['平台', '工具', '商业化', '增长', '数据', '搜索', '推荐', '策略', '对话', '客服', '电商', '营销', '内容', '视频', '语音', '视觉', '机器人', '办公', '教育', '医疗', '金融', '风控', 'SAAS', '工作流', '解决方案']:
        if token.upper() in upper:
            score += 1
    if entry.get('suggestion'):
        score += 3
    if entry.get('title'):
        score += 2
    if len(term) <= 14:
        score += 1
    return score

def build_keyword_library(suggestion_terms, title_terms, base_terms=None, target_count=50):
    candidates = {}

    def add_terms(terms, source, weight):
        for raw in terms or []:
            variants = _keyword_variants_from_raw(raw)
            if not variants:
                continue
            for idx, term in enumerate(variants):
                entry = candidates.setdefault(term, {'score': 0, 'suggestion': False, 'title': False, 'base': False})
                entry['score'] += max(1, weight - idx)
                entry[source] = True

    add_terms(base_terms or DEFAULT_KEYWORDS, 'base', 1)
    add_terms(suggestion_terms, 'suggestion', 5)
    add_terms(title_terms, 'title', 4)

    ranked = sorted(
        candidates.items(),
        key=lambda item: (-_keyword_rank(item[0], item[1]), -int(item[1].get('suggestion')), -int(item[1].get('title')), len(item[0]), item[0])
    )
    keywords = [term for term, _ in ranked[:max(1, target_count)]]
    if len(keywords) < target_count:
        for term in _merge_unique_terms(base_terms or [], DEFAULT_KEYWORDS):
            if term not in keywords and _looks_like_search_keyword(term):
                keywords.append(term)
            if len(keywords) >= target_count:
                break
    return sanitize_keyword_library(keywords, target_count=target_count)

def load_config():
    """加载 keywords.json 全量配置"""
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
    config['keyword_settings'] = _keyword_settings(config)
    config['keywords'] = sanitize_keyword_library(
        config.get('keywords') or DEFAULT_KEYWORDS,
        target_count=config['keyword_settings']['target_count'],
    )
    return config

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def load_cities():
    return load_config()['cities']

def load_keywords(quick=False):
    """加载关键词：每轮随机抽取 5-8 个搜索词"""
    config = load_config()
    settings = config['keyword_settings']
    all_kw = _merge_unique_terms(config.get('keywords') or [], DEFAULT_KEYWORDS)
    if not all_kw:
        return []
    low = min(settings['sample_min'], len(all_kw))
    high = min(settings['sample_max'], len(all_kw))
    pick_count = random.randint(low, max(low, high))
    selected = random.sample(all_kw, min(pick_count, len(all_kw)))
    mode_label = '快速模式' if quick else '全量模式'
    logger.info(f'[{mode_label}] 词库 {len(all_kw)} 个，本轮随机抽取 {len(selected)} 个关键词: {selected}')
    return selected

def random_delay(lo=MIN_DELAY, hi=MAX_DELAY):
    """高斯分布延迟，偶尔出现较长停顿（模拟走神/看手机）"""
    mean = (lo + hi) / 2
    std = (hi - lo) / 4
    delay = max(lo * 0.8, random.gauss(mean, std))
    # 3% 概率出现一次「走神」短停顿
    if random.random() < 0.03:
        delay += random.uniform(1, 3)
    time.sleep(delay)

def is_relevant(job_name: str, skills: str = '') -> bool:
    """判断岗位是否与 AI 产品经理强相关（扩展词库 + 不区分大小写）"""
    text = f'{job_name} {skills}'.upper()
    has_ai = any(kw.upper() in text for kw in _AI_TERMS)
    has_pm = any(kw.upper() in text for kw in _PM_TERMS)
    return has_ai and has_pm

def simulate_human(page):
    """模拟真人浏览：滚动、停顿、鼠标移动、阅读"""
    actions = random.randint(2, 4)
    for _ in range(actions):
        act = random.choices(
            ['down', 'up', 'pause', 'mouse', 'read'],
            weights=[30, 15, 20, 20, 15], k=1
        )[0]
        if act == 'down':
            total = random.randint(200, 600)
            steps = random.randint(2, 4)
            for i in range(steps):
                chunk = int(total * random.uniform(0.15, 0.45))
                page.scroll.down(chunk)
                time.sleep(random.uniform(0.05, 0.2))
            time.sleep(random.uniform(0.3, 0.8))
        elif act == 'up':
            page.scroll.up(random.randint(80, 250))
            time.sleep(random.uniform(0.3, 0.7))
        elif act == 'mouse':
            try:
                x = random.randint(100, 900)
                y = random.randint(200, 600)
                page.run_js(f'document.elementFromPoint({x},{y})')
            except:
                pass
            time.sleep(random.uniform(0.2, 0.5))
        elif act == 'read':
            time.sleep(random.uniform(1.0, 3.0))
        else:
            time.sleep(random.uniform(0.4, 1.2))

# 详情页 API（通过 securityId 获取完整职位描述）
DETAIL_API = 'https://www.zhipin.com/wapi/zpgeek/job/detail.json'

def extract_jobs_from_api(json_data):
    """从 BOSS API 响应中提取岗位数据"""
    jobs = []
    try:
        job_list = json_data.get('zpData', {}).get('jobList', [])
        for item in job_list:
            jobs.append({
                'job_name': item.get('jobName', ''),
                'salary': item.get('salaryDesc', ''),
                'company': item.get('brandName', ''),
                'city': item.get('cityName', ''),
                'area': item.get('areaDistrict', ''),
                'business': item.get('businessDistrict', ''),
                'experience': item.get('jobExperience', ''),
                'degree': item.get('jobDegree', ''),
                'industry': item.get('brandIndustry', ''),
                'skills': ' '.join(item.get('skills', [])),
                'welfare': ' '.join(item.get('welfareList', [])),
                'security_id': item.get('securityId', ''),
                'encrypt_job_id': item.get('encryptJobId', ''),
                'url': f"https://www.zhipin.com/job_detail/{item.get('encryptJobId', '')}.html" if item.get('encryptJobId') else '',
            })
    except Exception as e:
        logger.warning(f'解析API数据出错: {e}')
    return jobs

def collect_api_responses(dp, timeout=5):
    """收集监听到的 API 响应"""
    all_api_jobs = []
    while True:
        try:
            r = dp.listen.wait(timeout=timeout)
            if r and r.response and r.response.body:
                body = r.response.body
                if isinstance(body, str):
                    body = json.loads(body)
                jobs = extract_jobs_from_api(body)
                all_api_jobs.extend(jobs)
            else:
                break
        except:
            break
    return all_api_jobs

class BossDPSpider:
    """API拦截模式抓取 BOSS直聘 AI PM 强相关岗位"""

    def __init__(self):
        self.page = None
        self.all_jobs = {}    # key -> raw job
        self.skipped = 0      # 被过滤掉的非相关岗位
        self._progress_cb = None  # 进度回调: (combo_idx, total, kw, city, job_count)
        self._keyword_done_cb = None  # 关键词完成回调: (kw, raw_count, total_so_far)

    def _browser_alive(self) -> bool:
        """检测浏览器是否仍然存活"""
        try:
            _ = self.page.title
            return True
        except Exception:
            return False

    def _safe_listen_start(self, target):
        """安全启动 listen，浏览器断连时返回 False"""
        try:
            self.page.listen.start(target)
            return True
        except Exception:
            return False

    def _safe_listen_stop(self):
        """安全停止 listen"""
        try:
            self.page.listen.stop()
        except Exception:
            pass

    def _build_options(self, headless=False):
        from DrissionPage import ChromiumOptions
        PROFILE_DIR.mkdir(exist_ok=True)
        co = ChromiumOptions()
        # --- 反指纹检测 ---
        co.set_argument('--disable-blink-features=AutomationControlled')
        # 现代 Chrome UA，随机小版本
        minor = random.randint(0, 99)
        import platform as _plat
        if _plat.system() == 'Windows':
            co.set_user_agent(
                f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                f'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.{minor} Safari/537.36'
            )
        else:
            co.set_user_agent(
                f'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                f'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.{minor} Safari/537.36'
            )
        co.set_pref('excludeSwitches', ['enable-automation'])
        co.set_pref('useAutomationExtension', False)
        # 随机 viewport 尺寸（常见分辨率附近浮动）
        w = random.choice([1440, 1512, 1680, 1920]) + random.randint(-20, 20)
        h = random.choice([900, 1080, 1050]) + random.randint(-20, 20)
        co.set_argument(f'--window-size={w},{h}')
        # 语言与地区
        co.set_argument('--lang=zh-CN')
        co.set_user_data_path(str(PROFILE_DIR))
        co.set_local_port(CHROME_PORT)
        if headless:
            co.set_argument('--headless=new')
        return co

    def start_browser(self, headless=False):
        from DrissionPage import ChromiumPage
        from DrissionPage.common import Settings
        Settings.set_singleton_tab_obj(False)

        self._headless_requested = headless
        co = self._build_options(headless=False)
        self.page = ChromiumPage(addr_or_opts=co)
        # 设置显式超时，避免页面卡死导致爬虫无限等待
        try:
            self.page.set.timeouts(base=30, page_load=30, script=20)
        except Exception:
            pass
        # 注入反检测 JS（隐藏 webdriver 特征）
        try:
            self.page.run_js('''
                Object.defineProperty(navigator, "webdriver", {get: () => undefined});
                Object.defineProperty(navigator, "plugins", {get: () => [1,2,3,4,5]});
                Object.defineProperty(navigator, "languages", {get: () => ["zh-CN","zh","en"]});
                window.chrome = {runtime: {}, loadTimes: () => ({}), csi: () => ({})};
            ''')
        except:
            pass
        print('✓ 浏览器已启动 (Profile:', PROFILE_DIR, ')')

    def ensure_login(self, city_code):
        """检测登录状态，未登录则弹窗提示用户登录"""
        from platform_utils import activate_chrome, notify, show_login_dialog
        url = f'https://www.zhipin.com/web/geek/job?query=AI产品经理&city={city_code}'
        self.page.get(url)
        time.sleep(5)

        # 检测是否已登录
        for attempt in range(8):
            try:
                has_jobs = self.page.run_js(
                    'return document.querySelectorAll("li[class*=job-card]").length > 0'
                )
                if has_jobs:
                    print('✓ 已登录，检测到岗位列表')
                    return True
                is_verify = self.page.run_js(
                    'return document.title.includes("安全") || document.title.includes("验证")'
                )
                if is_verify:
                    print(f'  等待安全验证通过... ({attempt+1}/8)')
            except:
                pass
            time.sleep(3)

        # 未登录 — 弹出 Chrome 到前台 + 弹窗通知
        activate_chrome()
        notify('AI 岗位爬取', '请在 Chrome 中登录 BOSS 直聘')
        confirmed = show_login_dialog(
            'AI 岗位爬取 - 登录',
            '需要登录 BOSS 直聘\n\n'
            '请在已打开的 Chrome 窗口中完成登录，\n'
            '登录成功后点击「是」继续爬取。\n\n'
            'Cookie 会自动保存，下次无需再登录。'
        )
        if not confirmed:
            print('⚠ 用户取消登录')
            return False
        print('✓ 用户确认已登录')
        time.sleep(2)
        return True

    def collect_search_suggestions(self, keyword: str, city_code: str) -> list:
        url = f'https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}'
        self.page.get(url)
        random_delay(1.0, 1.6)
        try:
            self.page.run_js(f'''
                const seed = {json.dumps(keyword, ensure_ascii=False)};
                const input = document.querySelector('input[name="query"]')
                    || document.querySelector('input[placeholder*="搜索"]')
                    || document.querySelector('input[type="text"]');
                if (input) {{
                    input.focus();
                    input.value = '';
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    input.value = seed;
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    input.dispatchEvent(new KeyboardEvent('keyup', {{ key: 'g', bubbles: true }}));
                }}
            ''')
        except Exception:
            pass
        time.sleep(1.2)
        try:
            terms = self.page.run_js('''
                const texts = new Set();
                const selectors = [
                    '[class*="suggest"] a', '[class*="suggest"] li', '[class*="suggest"] span',
                    '[class*="association"] a', '[class*="association"] li',
                    '[class*="recommend"] a', '[class*="recommend"] li',
                    '[class*="related"] a', '[class*="related"] li',
                    'a[href*="query="]', '[data-query]'
                ];
                for (const selector of selectors) {
                    document.querySelectorAll(selector).forEach(el => {
                        const text = (el.innerText || el.textContent || el.getAttribute('data-query') || '').trim();
                        if (text) texts.add(text);
                        const href = el.getAttribute('href') || '';
                        if (href.includes('query=')) {
                            try {
                                const url = new URL(href, location.origin);
                                const query = decodeURIComponent(url.searchParams.get('query') || '').trim();
                                if (query) texts.add(query);
                            } catch (e) {}
                        }
                    });
                }
                return Array.from(texts);
            ''') or []
        except Exception:
            terms = []
        return _merge_unique_terms(terms)

    def collect_job_title_candidates(self, keyword: str, city_code: str) -> list:
        url = f'https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}'
        titles = []
        try:
            self.page.listen.start('wapi/zpgeek/search/joblist.json')
            self.page.get(url)
            random_delay(1.0, 1.8)
            api_jobs = collect_api_responses(self.page, timeout=6)
            titles.extend([job.get('job_name', '') for job in api_jobs if job.get('job_name')])
        except Exception:
            pass
        finally:
            try:
                self.page.listen.stop()
            except Exception:
                pass
        if not titles:
            try:
                dom_titles = self.page.run_js('''
                    const selectors = [
                        'li[class*="job-card"] [class*="job-name"]',
                        'li[class*="job-card"] [class*="title"]',
                        '.job-name',
                        '.job-card-body a'
                    ];
                    const texts = new Set();
                    for (const selector of selectors) {
                        document.querySelectorAll(selector).forEach(el => {
                            const text = (el.innerText || el.textContent || '').trim();
                            if (text) texts.add(text);
                        });
                    }
                    return Array.from(texts);
                ''') or []
                titles.extend(dom_titles)
            except Exception:
                pass
        return _merge_unique_terms(titles)

    def _add_jobs(self, api_jobs):
        """添加岗位（带强相关过滤和去重）
        返回: (new_count, existing_count, relevant_count)
        为兼容旧调用方，int() 取 new_count 即可
        """
        new_count = 0
        existing_count = 0
        relevant_count = 0
        for job in api_jobs:
            name = job.get('job_name', '')
            skills = job.get('skills', '')

            if not is_relevant(name, skills):
                self.skipped += 1
                continue

            relevant_count += 1
            key = f"{name}_{job.get('company', '')}"
            if key in self.all_jobs:
                existing_count += 1
            elif name:
                self.all_jobs[key] = job
                new_count += 1
        return new_count, existing_count, relevant_count

    def scrape_keyword(self, keyword: str, city_code: str) -> int:
        """用 API 拦截 + 翻页模式抓取一个关键词"""
        keyword_new = 0
        no_new_pages = 0

        for page_num in range(1, MAX_PAGES + 1):
            if not self._safe_listen_start('wapi/zpgeek/search/joblist.json'):
                break

            if page_num == 1:
                # 首页：正常导航
                url = f'https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}'
                self.page.get(url)
            else:
                # 后续页：尝试点击「下一页」按钮，更像真人
                try:
                    next_btn = self.page.ele('css:.ui-icon-arrow-right', timeout=3)
                    if next_btn:
                        next_btn.click()
                    else:
                        url = f'https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}&page={page_num}'
                        self.page.get(url)
                except:
                    url = f'https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}&page={page_num}'
                    self.page.get(url)

            # 页面加载后等待（模拟阅读）
            random_delay(0.8, 1.8)
            # 10% 概率模拟浏览行为
            if random.random() < 0.1:
                simulate_human(self.page)

            # 收集翻页触发的 API
            page_jobs = collect_api_responses(self.page, timeout=8)
            page_new, _, _ = self._add_jobs(page_jobs)
            keyword_new += page_new

            if len(page_jobs) == 0:
                self._safe_listen_stop()
                break

            # 滚动触发更多加载
            scroll_no_new = 0
            for scroll_i in range(MAX_SCROLLS_PER_PAGE):
                # 非匀速滚动：模拟手指滑动
                dist = random.randint(300, 700)
                steps = random.randint(2, 3)
                for _ in range(steps):
                    self.page.scroll.down(dist // steps + random.randint(-30, 30))
                    time.sleep(random.uniform(0.08, 0.25))
                random_delay(0.8, 2.0)

                # 30% 概率模拟人类行为
                if random.random() < 0.3:
                    simulate_human(self.page)

                scroll_jobs = collect_api_responses(self.page, timeout=2)
                if scroll_jobs:
                    sn, _, _ = self._add_jobs(scroll_jobs)
                    keyword_new += sn
                    scroll_no_new = 0 if sn > 0 else scroll_no_new + 1
                else:
                    scroll_no_new += 1

                if scroll_no_new >= 2:
                    break

            self._safe_listen_stop()

            if page_new == 0:
                no_new_pages += 1
                if no_new_pages >= 2:
                    break
            else:
                no_new_pages = 0

            # 翻页间延迟
            random_delay(1.5, 3.5)

        return keyword_new

    def scrape_keyword_greedy(self, keyword: str, city_code: str, city_name: str = '') -> int:
        """贪婪模式：翻到底为止（连续2页0新增判定翻到底）"""
        keyword_new = 0
        page_num = 0
        consecutive_zero = 0
        MAX_CONSECUTIVE_ZERO = 2

        while True:
            page_num += 1
            if not self._safe_listen_start('wapi/zpgeek/search/joblist.json'):
                break

            if page_num == 1:
                url = f'https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}'
                self.page.get(url)
            else:
                try:
                    next_btn = self.page.ele('css:.ui-icon-arrow-right', timeout=3)
                    if next_btn:
                        next_btn.click()
                    else:
                        url = f'https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}&page={page_num}'
                        self.page.get(url)
                except:
                    url = f'https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}&page={page_num}'
                    self.page.get(url)

            random_delay(1.5, 3.0)
            if random.random() < 0.2:
                simulate_human(self.page)

            page_jobs = collect_api_responses(self.page, timeout=8)

            if len(page_jobs) == 0:
                self._safe_listen_stop()
                logger.info(f'    ↳ 第{page_num}页: API返回空，停止')
                break

            page_new, page_existing, page_relevant = self._add_jobs(page_jobs)
            keyword_new += page_new

            logger.info(f'    ↳ 第{page_num}页: +{page_new}新 / {page_relevant}相关 / {page_existing}重复 (原始{len(page_jobs)}条)')

            if page_new == 0:
                consecutive_zero += 1
                if consecutive_zero >= MAX_CONSECUTIVE_ZERO:
                    self._safe_listen_stop()
                    logger.info(f'    ↳ 连续{MAX_CONSECUTIVE_ZERO}页无新增，判定已翻到底（共{page_num}页）')
                    break
            else:
                consecutive_zero = 0

            # 滚动加载（精简版）
            for scroll_i in range(2):
                dist = random.randint(300, 600)
                self.page.scroll.down(dist)
                time.sleep(random.uniform(0.3, 0.8))
                scroll_jobs = collect_api_responses(self.page, timeout=2)
                if scroll_jobs:
                    sn, _, _ = self._add_jobs(scroll_jobs)
                    keyword_new += sn

            self._safe_listen_stop()
            random_delay(0.8, 1.8)

        return keyword_new

    def run_keyword(self, keyword: str, cities: dict, greedy: bool = False) -> list:
        """爬取单个关键词×所有城市，获取详情，返回标准化结果"""
        if not self._browser_alive():
            logger.warning(f'浏览器已断连，跳过关键词 {keyword}')
            return []

        kw_before = len(self.all_jobs)
        city_items = list(cities.items())
        random.shuffle(city_items)

        for city_i, (city_name, city_code) in enumerate(city_items):
            if not self._browser_alive():
                logger.warning(f'浏览器已断连，停止关键词 {keyword} (城市 {city_i}/{len(city_items)})')
                break

            n = self.scrape_keyword_greedy(keyword, city_code, city_name) if greedy else self.scrape_keyword(keyword, city_code)
            print(f'  → {keyword} @ {city_name}: +{n} | 累计 {len(self.all_jobs)} (过滤 {self.skipped})')

            # 进度回调
            if self._progress_cb:
                try:
                    combo_idx = kw_before + city_i + 1
                    total_combos = len(cities)
                    self._progress_cb(combo_idx, total_combos, keyword, city_name, len(self.all_jobs))
                except:
                    pass

            # 城市间休息
            if city_i < len(city_items) - 1:
                random_delay(KEYWORD_REST_MIN, KEYWORD_REST_MAX)

        # 获取该关键词下所有新岗位的详情
        kw_new_keys = {k for k, j in self.all_jobs.items() if k not in self._processed_keys}
        if kw_new_keys:
            self._fetch_keyword_details(kw_new_keys)
            self._processed_keys.update(kw_new_keys)

        # 标准化该关键词的结果
        results = []
        for key in kw_new_keys:
            if key in self.all_jobs:
                job = self.all_jobs[key]
                city = job.get('city', '')
                desc = job.get('full_desc', '') or job.get('skills', '')
                results.append({
                    'title': job.get('job_name', ''),
                    'company': job.get('company', ''),
                    'city': city,
                    'salary': job.get('salary', ''),
                    'exp': job.get('experience', ''),
                    'edu': job.get('degree', ''),
                    'desc': desc,
                    'url': job.get('url', ''),
                    '_source': 'boss_dp',
                })

        kw_raw = len(self.all_jobs) - kw_before
        logger.info(f'关键词 [{keyword}] 完成: 原始 {kw_raw} 条 → 标准化 {len(results)} 条')
        return results

    def _fetch_keyword_details(self, new_keys: set):
        """获取指定 key 集合的岗位详情（增量版 fetch_all_details）"""
        jobs_needing_detail = [
            (k, j) for k, j in self.all_jobs.items()
            if k in new_keys and j.get('security_id') and not j.get('full_desc')
        ]
        if not jobs_needing_detail:
            return

        total = len(jobs_needing_detail)
        success = 0
        fail = 0
        consecutive_fail = 0

        for idx, (key, job) in enumerate(jobs_needing_detail, 1):
            if not self._browser_alive():
                logger.warning(f'  ⚠ 浏览器已断连，停止详情获取 (已完成 {idx-1}/{total})')
                break

            sid = job['security_id']
            try:
                eid = job.get('encrypt_job_id', '')
                got_desc = False

                if eid:
                    detail_page_url = f'https://www.zhipin.com/job_detail/{eid}.html'
                    if not self._safe_listen_start('wapi/zpgeek/job/detail.json'):
                        fail += 1
                        continue
                    self.page.get(detail_page_url)
                    random_delay(1.0, 2.0)

                    try:
                        r = self.page.listen.wait(timeout=4)
                        if r and r.response and r.response.body:
                            body = r.response.body
                            if isinstance(body, str):
                                body = json.loads(body)
                            desc = body.get('zpData', {}).get('jobInfo', {}).get('postDescription', '')
                            if desc:
                                job['full_desc'] = desc
                                success += 1
                                got_desc = True
                    except:
                        pass
                    self._safe_listen_stop()

                    if not got_desc:
                        try:
                            desc_text = self.page.run_js(
                                'return document.querySelector(".job-sec-text")?.innerText || '
                                'document.querySelector(".job-detail-section .text")?.innerText || ""'
                            )
                            if desc_text and len(desc_text) > 20:
                                job['full_desc'] = desc_text
                                success += 1
                                got_desc = True
                        except:
                            pass

                    if got_desc and random.random() < 0.1:
                        simulate_human(self.page)

                if not got_desc and not job.get('full_desc'):
                    try:
                        detail_url = f'{DETAIL_API}?securityId={sid}'
                        if not self._safe_listen_start('wapi/zpgeek/job/detail.json'):
                            fail += 1
                            continue
                        self.page.get(detail_url)
                        r = self.page.listen.wait(timeout=5)
                        if r and r.response and r.response.body:
                            body = r.response.body
                            if isinstance(body, str):
                                body = json.loads(body)
                            desc = body.get('zpData', {}).get('jobInfo', {}).get('postDescription', '')
                            if desc:
                                job['full_desc'] = desc
                                success += 1
                                got_desc = True
                        self._safe_listen_stop()
                    except Exception:
                        self._safe_listen_stop()

                if not job.get('full_desc'):
                    fail += 1
                    consecutive_fail += 1
                else:
                    consecutive_fail = 0

                if consecutive_fail >= 5:
                    print(f'  ⚠ 连续 {consecutive_fail} 次失败，休息 10s...')
                    time.sleep(random.uniform(8, 12))
                    consecutive_fail = 0

                if idx % 20 == 0:
                    print(f'  详情进度: {idx}/{total} (成功 {success}, 失败 {fail})')

                random_delay(DETAIL_DELAY_MIN, DETAIL_DELAY_MAX)

                if idx % DETAIL_BATCH_SIZE == 0:
                    pause = random.uniform(*DETAIL_BATCH_PAUSE)
                    print(f'  ☕ 批次休息 {pause:.0f}s...')
                    simulate_human(self.page)
                    time.sleep(pause)

            except Exception as e:
                logger.warning(f'获取详情失败 [{key}]: {e}')
                fail += 1
                self._safe_listen_stop()

        print(f'  ✅ 详情获取完成: 成功 {success}/{total}, 失败 {fail}')

    def run(self, keywords: list, cities: dict, headless: bool = False, greedy: bool = False) -> list:
        """完整抓取流程（兼容旧接口，内部按关键词逐个调用 run_keyword）"""
        self.start_browser(headless=headless)
        first_city = list(cities.values())[0]
        if not self.ensure_login(first_city):
            self.page.quit()
            return []

        # 登录确认后，如果原始请求 headless，重启为后台模式节省资源
        if headless and self._headless_requested:
            print('↻ 登录完成，切换为后台模式运行...')
            self.page.quit()
            from DrissionPage import ChromiumPage
            co = self._build_options(headless=True)
            self.page = ChromiumPage(addr_or_opts=co)

        self._processed_keys = set()  # 跟踪已处理详情的 key

        mode_label = '贪婪' if greedy else '标准'
        total_kws = len(keywords)
        print(f'\n📊 [{mode_label}] {total_kws} 关键词 × {len(cities)} 城市')
        print(f'⏱  预计 {max(1, total_kws * len(cities) * 15 // 60)}-{total_kws * len(cities) * 25 // 60} 分钟\n')

        # 随机打乱关键词顺序
        kw_list = list(keywords)
        random.shuffle(kw_list)

        all_results = []
        t_start = time.time()

        for kw_idx, kw in enumerate(kw_list, 1):
            if not self._browser_alive():
                logger.warning(f'浏览器已断连，停止爬取 (已完成 {kw_idx-1}/{total_kws} 关键词)')
                break

            elapsed = time.time() - t_start
            print(f'\n[{kw_idx}/{total_kws}] 关键词: {kw}  (已用{elapsed/60:.1f}分)')

            try:
                kw_results = self.run_keyword(kw, cities, greedy=greedy)
                all_results.extend(kw_results)
            except Exception as e:
                logger.error(f'关键词 [{kw}] 爬取失败: {e}')

            # 关键词完成回调
            if self._keyword_done_cb:
                try:
                    self._keyword_done_cb(kw, len(all_results), kw_idx, total_kws)
                except:
                    pass

            # 关键词间休息
            if kw_idx < total_kws:
                rest = random.uniform(CITY_REST_MIN, CITY_REST_MAX)
                print(f'  ☕ 关键词切换休息 {rest:.0f}s...')
                simulate_human(self.page)
                time.sleep(rest)

        elapsed_total = (time.time() - t_start) / 60
        try:
            self.page.quit()
        except Exception:
            pass
        print(f'\n✅ 完成! 耗时 {elapsed_total:.1f} 分钟')
        print(f'   强相关岗位: {len(all_results)} 条 | 过滤非相关: {self.skipped} 条')
        return all_results

    def fetch_all_details(self):
        """批量获取所有岗位的完整职位描述"""
        jobs_needing_detail = [
            (k, j) for k, j in self.all_jobs.items()
            if j.get('security_id') and not j.get('full_desc')
        ]
        if not jobs_needing_detail:
            return

        total = len(jobs_needing_detail)
        print(f'\n📝 开始获取 {total} 个岗位的完整描述...')
        success = 0
        fail = 0
        consecutive_fail = 0

        # 随机打乱详情获取顺序
        random.shuffle(jobs_needing_detail)

        for idx, (key, job) in enumerate(jobs_needing_detail, 1):
            if not self._browser_alive():
                logger.warning(f'  ⚠ 浏览器已断连，停止详情获取 (已完成 {idx-1}/{total})')
                break

            sid = job['security_id']
            try:
                # 通过详情页获取（更像真人浏览行为）
                eid = job.get('encrypt_job_id', '')
                got_desc = False

                if eid:
                    detail_page_url = f'https://www.zhipin.com/job_detail/{eid}.html'
                    if not self._safe_listen_start('wapi/zpgeek/job/detail.json'):
                        fail += 1
                        continue
                    self.page.get(detail_page_url)
                    random_delay(1.0, 2.0)

                    # 先尝试 API 拦截
                    try:
                        r = self.page.listen.wait(timeout=4)
                        if r and r.response and r.response.body:
                            body = r.response.body
                            if isinstance(body, str):
                                body = json.loads(body)
                            desc = body.get('zpData', {}).get('jobInfo', {}).get('postDescription', '')
                            if desc:
                                job['full_desc'] = desc
                                success += 1
                                got_desc = True
                    except:
                        pass
                    self._safe_listen_stop()

                    # API 失败则从页面 DOM 抓取
                    if not got_desc:
                        try:
                            desc_text = self.page.run_js(
                                'return document.querySelector(".job-sec-text")?.innerText || '
                                'document.querySelector(".job-detail-section .text")?.innerText || ""'
                            )
                            if desc_text and len(desc_text) > 20:
                                job['full_desc'] = desc_text
                                success += 1
                                got_desc = True
                        except:
                            pass

                    # 10% 概率模拟阅读
                    if got_desc and random.random() < 0.1:
                        simulate_human(self.page)

                if not got_desc and not job.get('full_desc'):
                    # 回退：直接用 API
                    try:
                        detail_url = f'{DETAIL_API}?securityId={sid}'
                        if not self._safe_listen_start('wapi/zpgeek/job/detail.json'):
                            fail += 1
                            continue
                        self.page.get(detail_url)
                        r = self.page.listen.wait(timeout=5)
                        if r and r.response and r.response.body:
                            body = r.response.body
                            if isinstance(body, str):
                                body = json.loads(body)
                            desc = body.get('zpData', {}).get('jobInfo', {}).get('postDescription', '')
                            if desc:
                                job['full_desc'] = desc
                                success += 1
                                got_desc = True
                        self._safe_listen_stop()
                    except Exception:
                        self._safe_listen_stop()

                if not job.get('full_desc'):
                    fail += 1
                    consecutive_fail += 1
                else:
                    consecutive_fail = 0

                # 连续失败过多，可能被封了，长休息
                if consecutive_fail >= 5:
                    print(f'  ⚠ 连续 {consecutive_fail} 次失败，休息 10s...')
                    time.sleep(random.uniform(8, 12))
                    consecutive_fail = 0

                if idx % 20 == 0:
                    print(f'  详情进度: {idx}/{total} (成功 {success}, 失败 {fail})')

                # 每条之间的延迟
                random_delay(DETAIL_DELAY_MIN, DETAIL_DELAY_MAX)

                # 每批详情后较长休息
                if idx % DETAIL_BATCH_SIZE == 0:
                    pause = random.uniform(*DETAIL_BATCH_PAUSE)
                    print(f'  ☕ 批次休息 {pause:.0f}s...')
                    simulate_human(self.page)
                    time.sleep(pause)

            except Exception as e:
                logger.warning(f'获取详情失败 [{key}]: {e}')
                fail += 1
                self._safe_listen_stop()

        print(f'  ✅ 详情获取完成: 成功 {success}/{total}, 失败 {fail}')

    def _normalize_all(self) -> list:
        """标准化为 pipeline 格式"""
        results = []
        for key, job in self.all_jobs.items():
            city = job.get('city', '')
            # 优先使用完整描述，回退到 skills
            desc = job.get('full_desc', '') or job.get('skills', '')
            results.append({
                'title': job.get('job_name', ''),
                'company': job.get('company', ''),
                'city': city,
                'salary': job.get('salary', ''),
                'exp': job.get('experience', ''),
                'edu': job.get('degree', ''),
                'desc': desc,
                'url': job.get('url', ''),
                '_source': 'boss_dp',
            })
        return results

def refresh_keyword_library_from_boss(city_code=None, seed_queries=None):
    config = load_config()
    settings = config['keyword_settings']
    cities = config.get('cities') or {}
    city_code = city_code or next(iter(cities.values()), '101010100')
    seed_queries = _merge_unique_terms(seed_queries or [], settings.get('seed_queries') or [], DEFAULT_KEYWORD_SETTINGS['seed_queries'])
    spider = BossDPSpider()
    suggestion_terms = []
    title_terms = []
    try:
        spider.start_browser(headless=False)
        if not spider.ensure_login(city_code):
            return {'ok': False, 'error': 'BOSS 未登录，无法刷新关键词词库'}
        for seed in seed_queries:
            logger.info(f'[关键词词库月更] 采集候选词: {seed}')
            suggestion_terms.extend(spider.collect_search_suggestions(seed, city_code))
            title_terms.extend(spider.collect_job_title_candidates(seed, city_code))
            random_delay(0.8, 1.5)
        merged_suggestions = _merge_unique_terms(suggestion_terms)
        merged_titles = _merge_unique_terms(title_terms)
        keywords = build_keyword_library(
            merged_suggestions,
            merged_titles,
            base_terms=config.get('keywords') or DEFAULT_KEYWORDS,
            target_count=settings['target_count'],
        )
        if len(keywords) < min(10, settings['target_count']):
            return {
                'ok': False,
                'error': f'有效关键词不足: suggestions={len(merged_suggestions)}, titles={len(merged_titles)}, keywords={len(keywords)}',
            }
        settings['last_refreshed_at'] = datetime_now = time.strftime('%Y-%m-%d %H:%M:%S')
        settings['last_refreshed_month'] = time.strftime('%Y-%m')
        settings['last_refresh_source_counts'] = {
            'suggestions': len(merged_suggestions),
            'titles': len(merged_titles),
            'final_keywords': len(keywords),
        }
        config['keywords'] = keywords
        config['keyword_settings'] = settings
        save_config(config)
        return {
            'ok': True,
            'keywords': keywords,
            'suggestions': len(merged_suggestions),
            'titles': len(merged_titles),
            'final_keywords': len(keywords),
            'refreshed_at': datetime_now,
        }
    except Exception as e:
        logger.exception(f'刷新关键词词库失败: {e}')
        return {'ok': False, 'error': str(e)}
    finally:
        try:
            if spider.page:
                spider.page.quit()
        except Exception:
            pass

def main():
    """独立运行入口"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    parser = argparse.ArgumentParser(description='BOSS直聘 AI PM 强相关岗位采集')
    parser.add_argument('--city', type=str, help='只抓指定城市')
    parser.add_argument('--quick', action='store_true', help='快速模式（随机抽取关键词）')
    parser.add_argument('--greedy', action='store_true', help='贪婪模式（翻到底，连续5页无新增停止）')
    parser.add_argument('--merge', action='store_true', help='自动合并到 Dashboard')
    parser.add_argument('--login', action='store_true', help='仅登录保存Cookie（首次使用）')
    parser.add_argument('--headless', action='store_true', help='无头模式（定时任务用）')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(name)s] %(message)s')

    cities = load_cities()
    keywords = load_keywords(quick=args.quick)

    if args.city:
        cities = {k: v for k, v in cities.items() if k == args.city}
        if not cities:
            print(f'未找到城市: {args.city}')
            return

    spider = BossDPSpider()

    # 仅登录模式
    if args.login:
        spider.start_browser(headless=False)
        first_city = list(cities.values())[0]
        spider.ensure_login(first_city)
        print('✅ 登录完成，Cookie 已保存到持久化 Profile')
        print('   以后自动运行无需再登录')
        spider.page.quit()
        return

    raw_jobs = spider.run(keywords, cities, headless=args.headless, greedy=args.greedy)

    if args.merge and raw_jobs:
        from pipeline import process_batch
        from merger import load_existing, merge, save, save_snapshot

        cleaned = process_batch(raw_jobs)
        print(f'清洗后: {len(cleaned)} 条')

        existing_keys, existing_jobs = load_existing()
        merged, added = merge(existing_jobs, existing_keys, cleaned)
        save(merged)
        save_snapshot(cleaned)
        print(f'🔄 已合并到 Dashboard: 新增 {added} 条，总计 {len(merged)} 条')
    elif raw_jobs:
        print(f'\n抓取到 {len(raw_jobs)} 条强相关岗位:')
        for j in raw_jobs[:10]:
            print(f'  {j["title"]} | {j["company"]} | {j["city"]} | {j["salary"]}')
        if len(raw_jobs) > 10:
            print(f'  ... 还有 {len(raw_jobs)-10} 条')
    else:
        print('⚠ 未抓取到任何数据')


if __name__ == '__main__':
    main()
