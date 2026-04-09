#!/usr/bin/env python3
"""
BOSS直聘爬虫 - API拦截模式 + 强相关过滤
基于 boss-zp-main 的 API 拦截方案，速度快、数据完整

用法:
  python3 boss_dp.py --merge           # 全量抓取并合并到 Dashboard
  python3 boss_dp.py --quick --merge   # 快速模式(≈8分钟)
  python3 boss_dp.py --city 杭州       # 只抓指定城市
"""
import sys
import json
import time
import random
import math
import logging
import argparse
import tempfile
import shutil
import hashlib
import re
import datetime as _dt
from pathlib import Path

logger = logging.getLogger('spider.boss_dp')

# ==================== 配置 ====================

# 全量: 5关键词×10城市 ≈ 12分钟
SEARCH_KEYWORDS = [
    'AI产品经理',
    'AIGC产品经理',
    '大模型产品经理',
    '智能产品经理',
    '算法产品经理',
    'NLP产品经理',
    'Agent产品经理',
    '对话产品经理',
    '多模态产品经理',
]

# 快速: 2关键词×5城市 ≈ 5分钟
QUICK_KEYWORDS = ['AI产品经理', 'AIGC产品经理']

CONFIG_DIR = Path(__file__).parent.parent.parent / 'config'
PROFILE_DIR = Path(__file__).parent.parent.parent / '.chrome_profile'  # 持久化登录

# 真实 Chrome UA 池（macOS + Windows 混合，降低指纹唯一性）
_UA_POOL = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.{v} Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.{v} Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.{v} Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.{v} Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.{v} Safari/537.36',
]

def _random_ua():
    tpl = random.choice(_UA_POOL)
    return tpl.format(v=random.randint(0, 200))

# 翻页与滚动
MAX_SCROLLS_PER_PAGE = 3

# 策略P: 自适应翻页数 — 按城市规模分级
_TIER1_CITIES = {'北京', '上海', '深圳', '杭州', '广州'}   # 大城市: 岗位多
_TIER2_CITIES = {'成都', '南京', '武汉', '苏州', '长沙'}   # 中城市
# 其余为 Tier3 小城市

def _max_pages_for_city(city_name: str) -> int:
    """策略P: 根据城市规模返回最大翻页数"""
    if city_name in _TIER1_CITIES:
        return 4
    elif city_name in _TIER2_CITIES:
        return 3
    else:
        return 2

# 防封参数 — 加大间隔，模拟真人节奏
MIN_DELAY, MAX_DELAY = 2.5, 5.0
KEYWORD_REST_MIN, KEYWORD_REST_MAX = 8, 20
CITY_REST_MIN, CITY_REST_MAX = 15, 35
DETAIL_DELAY_MIN, DETAIL_DELAY_MAX = 2.0, 4.5
DETAIL_BATCH_PAUSE = (15, 30)   # 每批详情后的长休息
DETAIL_BATCH_SIZE = 10           # 更小批次更安全

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


def load_cities():
    cfg_file = CONFIG_DIR / 'keywords.json'
    with open(cfg_file, 'r', encoding='utf-8') as f:
        return json.load(f)['cities']


def _load_existing_keys() -> set:
    """加载已有数据的去重 key 集合（MD5(公司+岗位+城市)），用于爬取时实时比对"""
    data_file = CONFIG_DIR.parent / 'jobs_data.json'
    if not data_file.exists():
        return set()
    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        jobs = data.get('jobs', data if isinstance(data, list) else [])
        keys = set()
        for j in jobs:
            if '_key' in j:
                keys.add(j['_key'])
            else:
                # 兼容旧数据：用相同算法生成 key
                raw = f"{j.get('company','')}{j.get('title','')}{_norm_city(j.get('city',''))}"
                keys.add(hashlib.md5(raw.encode()).hexdigest())
        return keys
    except Exception as e:
        logger.warning(f'加载已有数据失败: {e}')
        return set()


def _norm_city(city: str) -> str:
    """城市名标准化（与 pipeline.norm_city 保持一致）"""
    city = str(city or '').strip()
    city = re.sub(r'[市省]$', '', city)
    city = city.split('·')[0]
    return city


def _make_dedup_key(job_name: str, company: str, city: str) -> str:
    """生成与 pipeline.dedup_key 完全一致的去重 key"""
    raw = f"{company}{job_name}{_norm_city(city)}"
    return hashlib.md5(raw.encode()).hexdigest()


# === 策略J: 关键词×城市 组合缓存 ===
_COMBO_CACHE_FILE = CONFIG_DIR / 'combo_cache.json'


def _load_combo_cache() -> dict:
    """加载组合缓存。格式: {"kw@city": {"zero_days": 2, "last_zero": "2026-04-09", "skip_until": "2026-04-12"}}"""
    if not _COMBO_CACHE_FILE.exists():
        return {}
    try:
        with open(_COMBO_CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_combo_cache(cache: dict):
    """保存组合缓存"""
    try:
        with open(_COMBO_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f'保存组合缓存失败: {e}')


def _should_skip_combo(cache: dict, kw: str, city: str) -> bool:
    """策略J+K: 连续2天零新增 → 跳过，3天后自动恢复查询"""
    key = f"{kw}@{city}"
    entry = cache.get(key)
    if not entry:
        return False
    today = _dt.date.today().isoformat()
    skip_until = entry.get('skip_until', '')
    if skip_until and today < skip_until:
        return True  # 还在跳过期内
    return False


def _update_combo_cache(cache: dict, kw: str, city: str, new_count: int):
    """更新组合缓存记录"""
    key = f"{kw}@{city}"
    today = _dt.date.today().isoformat()
    entry = cache.get(key, {})

    if new_count > 0:
        # 有新增 → 重置计数器
        cache[key] = {'zero_days': 0, 'last_zero': '', 'skip_until': ''}
        return

    # 零新增
    last_zero = entry.get('last_zero', '')
    if last_zero == today:
        return  # 同一天不重复计数

    zero_days = entry.get('zero_days', 0) + 1
    skip_until = ''
    if zero_days >= 2:
        # 连续2天零新增 → 跳过3天
        resume_date = _dt.date.today() + _dt.timedelta(days=3)
        skip_until = resume_date.isoformat()

    cache[key] = {
        'zero_days': zero_days,
        'last_zero': today,
        'skip_until': skip_until,
    }


def random_delay(lo=MIN_DELAY, hi=MAX_DELAY):
    """高斯分布延迟，偶尔出现较长停顿（模拟走神/看手机）"""
    mean = (lo + hi) / 2
    std = (hi - lo) / 4
    delay = max(lo * 0.8, random.gauss(mean, std))
    # 5% 概率出现一次「走神」长停顿
    if random.random() < 0.05:
        delay += random.uniform(2, 6)
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
                'last_modify_time': item.get('lastModifyTime', ''),
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
        self.skipped_existing = 0  # 已存在于数据库中被跳过的
        self._progress_cb = None  # 进度回调: (combo_idx, total, kw, city, job_count)
        self._seen_job_ids = set()  # 策略B: 跨关键词 encrypt_job_id 去重
        self._consecutive_stale = 0  # 策略F: 连续旧数据计数器
        # 启动时加载已有数据 key 集合，用于实时去重
        self._existing_keys = _load_existing_keys()
        if self._existing_keys:
            print(f'📦 已加载 {len(self._existing_keys)} 条已有数据用于去重')

    def _build_options(self, headless=False, fresh_profile=False):
        from DrissionPage import ChromiumOptions
        co = ChromiumOptions()
        # --- 反指纹检测 ---
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--disable-infobars')
        co.set_argument('--no-first-run')
        co.set_argument('--no-default-browser-check')
        # 随机真实 UA
        co.set_user_agent(_random_ua())
        co.set_pref('excludeSwitches', ['enable-automation'])
        co.set_pref('useAutomationExtension', False)
        # 随机 viewport 尺寸（常见分辨率附近浮动）
        w = random.choice([1440, 1512, 1680, 1920]) + random.randint(-30, 30)
        h = random.choice([900, 1050, 1080]) + random.randint(-30, 30)
        co.set_argument(f'--window-size={w},{h}')
        # 语言与地区
        co.set_argument('--lang=zh-CN')
        # 每次用全新临时 profile，避免被指纹关联到之前被标记的会话
        if fresh_profile:
            self._tmp_profile = tempfile.mkdtemp(prefix='boss_chrome_')
            co.set_user_data_path(self._tmp_profile)
            logger.info(f'使用临时 Profile: {self._tmp_profile}')
        else:
            PROFILE_DIR.mkdir(exist_ok=True)
            co.set_user_data_path(str(PROFILE_DIR))
        if headless:
            co.set_argument('--headless=new')
        return co

    def start_browser(self, headless=False):
        from DrissionPage import ChromiumPage
        from DrissionPage.common import Settings
        Settings.set_singleton_tab_obj(False)

        self._headless_requested = headless
        self._tmp_profile = None
        # 使用持久化 Profile 保存登录状态，避免每次重新登录
        co = self._build_options(headless=headless, fresh_profile=False)
        self.page = ChromiumPage(addr_or_opts=co)
        # 注入反检测 JS（隐藏 webdriver 特征）
        self._inject_stealth()
        print('✓ 浏览器已启动 (持久化 Profile, 登录状态已保存)')

    def _inject_stealth(self):
        """注入反检测 JS，隐藏自动化特征"""
        try:
            self.page.run_js('''
                Object.defineProperty(navigator, "webdriver", {get: () => undefined});
                Object.defineProperty(navigator, "plugins", {
                    get: () => [1,2,3,4,5].map(() => ({}))
                });
                Object.defineProperty(navigator, "languages", {get: () => ["zh-CN","zh","en"]});
                window.chrome = {runtime: {}, loadTimes: () => ({}), csi: () => ({})};
                // 覆盖 permissions.query 防止检测
                const origQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (params) => {
                    if (params.name === 'notifications')
                        return Promise.resolve({state: Notification.permission});
                    return origQuery(params);
                };
                // 隐藏 Headless 特征
                Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
                Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
            ''')
        except:
            pass

    def ensure_login(self, city_code):
        """检测登录状态，已有登录态直接通过，否则提示用户登录"""
        # 先访问首页预热，更像真人
        self.page.get('https://www.zhipin.com/')
        time.sleep(random.uniform(2, 4))
        self._inject_stealth()

        url = f'https://www.zhipin.com/web/geek/job?query=AI产品经理&city={city_code}'
        self.page.get(url)
        time.sleep(random.uniform(4, 7))

        # 先快速检测：持久化 Profile 可能已有登录态
        try:
            has_jobs = self.page.run_js(
                'return document.querySelectorAll("li[class*=job-card]").length > 0'
            )
            if has_jobs:
                print('✓ 已检测到登录态（持久化 Profile），直接开始爬取')
                return True
        except:
            pass

        # 未登录 → 提示用户登录
        print('\n' + '='*50)
        print('⏳ 请在已打开的 Chrome 窗口中登录 BOSS 直聘')
        print('   首次登录后，登录状态将被保存，后续自动跳过')
        print('='*50)

        # 发送通知提醒
        import subprocess
        try:
            subprocess.run(['osascript', '-e',
                'display notification "请在 Chrome 中登录 BOSS 直聘，首次登录后自动保存" '
                'with title "AI 岗位爬取" sound name "Basso"'], timeout=5)
        except:
            pass

        max_wait = 180  # 最长等 3 分钟
        check_interval = 5
        waited = 0
        while waited < max_wait:
            try:
                has_jobs = self.page.run_js(
                    'return document.querySelectorAll("li[class*=job-card]").length > 0'
                )
                if has_jobs:
                    print('✓ 已登录，检测到岗位列表')
                    return True
            except:
                pass

            # 检查是否在安全验证页
            try:
                is_verify = self.page.run_js(
                    'return document.title.includes("安全") || document.title.includes("验证")'
                )
                if is_verify:
                    print(f'  等待安全验证通过... (已等 {waited}s)')
            except:
                pass

            waited += check_interval
            if waited % 30 == 0:
                print(f'  ⏳ 等待登录中... ({waited}s/{max_wait}s)')
                # 刷新页面重新检测
                try:
                    self.page.get(url)
                    time.sleep(3)
                except:
                    pass
            time.sleep(check_interval)

        print('⚠ 等待超时，但继续尝试...')
        return True

    def _add_jobs(self, api_jobs):
        """合并去重，返回 (new_count, existing_count, relevant_total, id_dup_count, old_time_count)
        old_time_count: 策略R — 最近修改时间超过7天的岗位数"""
        new_count = 0
        existing_count = 0
        relevant_total = 0
        id_dup_count = 0
        old_time_count = 0
        _stale_days = 7  # 策略R: 超过7天视为旧岗位
        for job in api_jobs:
            name = job.get('job_name', '')
            company = job.get('company', '')
            city = job.get('city', '')
            skills = job.get('skills', '')
            eid = job.get('encrypt_job_id', '')

            if not name:
                continue

            if not is_relevant(name, skills):
                self.skipped += 1
                continue

            relevant_total += 1

            # 策略R: 检查最近修改时间
            lmt = job.get('last_modify_time', '')
            if lmt:
                try:
                    now = _dt.datetime.now()
                    job_date = None
                    if isinstance(lmt, (int, float)) and lmt > 1000000000:
                        # 时间戳格式（秒或毫秒）
                        job_date = _dt.datetime.fromtimestamp(lmt / 1000 if lmt > 1e12 else lmt)
                    elif isinstance(lmt, str):
                        # 字符串格式: "发布于04月08日" 或 "发布于昨天" 或 "发布于3天前"
                        m = re.search(r'(\d{1,2})月(\d{1,2})日', lmt)
                        if m:
                            month, day = int(m.group(1)), int(m.group(2))
                            year = now.year
                            job_date = _dt.datetime(year, month, day)
                            if job_date > now:
                                job_date = _dt.datetime(year - 1, month, day)
                        elif '昨天' in lmt:
                            job_date = now - _dt.timedelta(days=1)
                        elif '前天' in lmt:
                            job_date = now - _dt.timedelta(days=2)
                        else:
                            dm = re.search(r'(\d+)\s*天前', lmt)
                            if dm:
                                job_date = now - _dt.timedelta(days=int(dm.group(1)))
                    if job_date and (now - job_date).days > _stale_days:
                        old_time_count += 1
                except Exception:
                    pass

            # 策略B: 跨关键词 encrypt_job_id 去重
            if eid and eid in self._seen_job_ids:
                existing_count += 1
                id_dup_count += 1
                continue
            if eid:
                self._seen_job_ids.add(eid)

            # 生成与数据库一致的去重 key（MD5(公司+岗位+城市)）
            dedup = _make_dedup_key(name, company, city)

            # 已存在于数据库 → 直接跳过
            if dedup in self._existing_keys:
                self.skipped_existing += 1
                existing_count += 1
                continue

            # 本次爬取内去重
            crawl_key = f"{name}_{company}"
            if crawl_key not in self.all_jobs:
                self.all_jobs[crawl_key] = job
                job['_dedup_key'] = dedup
                new_count += 1
            else:
                existing_count += 1
        return new_count, existing_count, relevant_total, id_dup_count, old_time_count

    def scrape_keyword(self, keyword: str, city_code: str, city_name: str = '') -> int:
        """用 API 拦截 + 翻页模式抓取一个关键词
        策略A: 整页重复率提前终止翻页
        策略F: 动态缩短延迟
        策略P: 自适应翻页数（按城市规模）"""
        keyword_new = 0
        no_new_pages = 0
        is_stale = True  # 跟踪本关键词是否全是旧数据
        max_pages = _max_pages_for_city(city_name)

        for page_num in range(1, max_pages + 1):
            self.page.listen.start('wapi/zpgeek/search/joblist.json')

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

            # 策略F: 动态延迟 — 连续旧数据时缩短等待
            if self._consecutive_stale >= 3:
                random_delay(0.8, 1.5)
            else:
                random_delay(1.5, 3.0)

            if random.random() < 0.2:
                simulate_human(self.page)

            # 收集 API 响应
            page_jobs = collect_api_responses(self.page, timeout=8)
            page_new, page_existing, page_relevant, page_id_dup, page_old_time = self._add_jobs(page_jobs)
            keyword_new += page_new

            if len(page_jobs) == 0:
                self.page.listen.stop()
                break

            # === 策略A+B: 整页重复率判断（合并已有数据 + 跨关键词ID重复） ===
            if page_relevant > 0:
                repeat_rate = page_existing / page_relevant
                id_dup_rate = page_id_dup / page_relevant

                # 策略B增强: 整页全是跨关键词ID重复 → 抽查一页，90%+终止
                if id_dup_rate >= 1.0 and page_relevant >= 3:
                    self.page.listen.stop()
                    print(f'    ↳ 整页 {page_relevant} 条全是ID重复，抽查下一页...')
                    if page_num < max_pages:
                        self.page.listen.start('wapi/zpgeek/search/joblist.json')
                        try:
                            nb = self.page.ele('css:.ui-icon-arrow-right', timeout=3)
                            if nb:
                                nb.click()
                            else:
                                self.page.get(f'https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}&page={page_num+1}')
                        except:
                            self.page.get(f'https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}&page={page_num+1}')
                        random_delay(0.8, 1.5)
                        probe_jobs = collect_api_responses(self.page, timeout=6)
                        probe_new, probe_existing, probe_relevant, probe_id_dup, _ = self._add_jobs(probe_jobs)
                        keyword_new += probe_new
                        self.page.listen.stop()
                        if probe_relevant > 0 and probe_id_dup / probe_relevant >= 0.9:
                            print(f'    ↳ 抽查页ID重复 {probe_id_dup}/{probe_relevant}，跨关键词终止')
                            break
                    else:
                        break
                    continue

                if page_num == 1 and repeat_rate >= 0.9:
                    # 首页 90%+ 是旧数据 → 抽查下一页，不做滚动
                    self.page.listen.stop()
                    print(f'    ↳ 首页 {repeat_rate:.0%} 重复，抽查下一页...')
                    self.page.listen.start('wapi/zpgeek/search/joblist.json')
                    try:
                        nb = self.page.ele('css:.ui-icon-arrow-right', timeout=3)
                        if nb:
                            nb.click()
                        else:
                            self.page.get(f'https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}&page=2')
                    except:
                        self.page.get(f'https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}&page=2')
                    random_delay(0.8, 1.5)
                    probe_jobs = collect_api_responses(self.page, timeout=6)
                    probe_new, probe_existing, probe_relevant, _, _ = self._add_jobs(probe_jobs)
                    keyword_new += probe_new
                    self.page.listen.stop()
                    if probe_relevant > 0 and probe_existing / probe_relevant >= 0.8:
                        print(f'    ↳ 抽查页 {probe_existing}/{probe_relevant} 重复，提前终止')
                        break
                    continue
                elif page_num > 1 and repeat_rate >= 0.8:
                    # 后续页 80%+ 重复 → 直接终止
                    self.page.listen.stop()
                    print(f'    ↳ 第{page_num}页 {repeat_rate:.0%} 重复，终止翻页')
                    break

                # 策略R: 增量时间窗 — 如果本页大部分岗位修改时间 > 7天，提前终止
                if page_old_time > 0 and page_relevant > 0:
                    old_rate = page_old_time / page_relevant
                    if old_rate >= 0.7 and page_num > 1:
                        self.page.listen.stop()
                        print(f'    ↳ 策略R: 第{page_num}页 {page_old_time}/{page_relevant} 岗位超7天未更新，终止翻页')
                        break

            # 有新数据时才滚动加载更多
            if page_new > 0:
                is_stale = False
                scroll_no_new = 0
                for scroll_i in range(MAX_SCROLLS_PER_PAGE):
                    dist = random.randint(300, 700)
                    steps = random.randint(2, 3)
                    for _ in range(steps):
                        self.page.scroll.down(dist // steps + random.randint(-30, 30))
                        time.sleep(random.uniform(0.08, 0.25))
                    random_delay(0.5, 1.2) if self._consecutive_stale >= 3 else random_delay(0.8, 2.0)

                    if random.random() < 0.3:
                        simulate_human(self.page)

                    scroll_jobs = collect_api_responses(self.page, timeout=2)
                    if scroll_jobs:
                        sn, _, _, _, _ = self._add_jobs(scroll_jobs)
                        keyword_new += sn
                        scroll_no_new = 0 if sn > 0 else scroll_no_new + 1
                    else:
                        scroll_no_new += 1
                    if scroll_no_new >= 2:
                        break

            self.page.listen.stop()

            if page_new == 0:
                no_new_pages += 1
                if no_new_pages >= 2:
                    break
            else:
                no_new_pages = 0

            # 策略F: 动态翻页延迟
            if self._consecutive_stale >= 3:
                random_delay(1.0, 2.5)
            else:
                random_delay(2.5, 5.0)

        # 策略F: 更新连续旧数据计数器
        if is_stale:
            self._consecutive_stale += 1
        else:
            self._consecutive_stale = 0

        return keyword_new

    def run(self, keywords: list, cities: dict, headless: bool = False) -> list:
        """完整抓取流程"""
        self.start_browser(headless=headless)
        first_city = list(cities.values())[0]
        if not self.ensure_login(first_city):
            self.page.quit()
            return []

        # 继续用当前浏览器实例抓取（不再重启为 headless，避免冲突）

        total_combos = len(keywords) * len(cities)
        combo_idx = 0
        skipped_combos = 0
        t_start = time.time()

        # 策略J: 加载组合缓存
        combo_cache = _load_combo_cache()

        print(f'\n📊 {len(keywords)} 关键词 × {len(cities)} 城市 = {total_combos} 组')

        # 策略J: 预先统计跳过数
        skip_count = sum(1 for cn, _ in cities.items() for k in keywords if _should_skip_combo(combo_cache, k, cn))
        active_combos = total_combos - skip_count
        if skip_count > 0:
            print(f'💤 策略J: {skip_count} 组连续无新增已跳过，实际执行 {active_combos} 组')
        print(f'⏱  预计 {max(1, active_combos * 15 // 60)}-{active_combos * 25 // 60} 分钟\n')

        # 随机打乱城市顺序，避免固定遍历模式
        city_items = list(cities.items())
        random.shuffle(city_items)

        # 策略Q: 智能关键词排序 — 新/冷门词优先，热门老词后跑
        # 新词跨关键词重叠少 → 新增率高；老词放后面 → 策略B的ID去重更早触发终止
        _HOT_KEYWORDS = {'AI产品经理', 'AIGC产品经理'}  # 热门老词（跳过率极高）
        kw_sorted = sorted(keywords, key=lambda k: (k in _HOT_KEYWORDS, random.random()))
        logger.info(f'策略Q 关键词顺序: {kw_sorted}')

        for city_i, (city_name, city_code) in enumerate(city_items):
            # 策略Q: 新词优先+组内随机（同优先级内随机化避免指纹）
            kw_new = [k for k in kw_sorted if k not in _HOT_KEYWORDS]
            kw_hot = [k for k in kw_sorted if k in _HOT_KEYWORDS]
            random.shuffle(kw_new)
            random.shuffle(kw_hot)
            kw_list = kw_new + kw_hot

            for kw in kw_list:
                combo_idx += 1

                # 策略J: 检查是否跳过
                if _should_skip_combo(combo_cache, kw, city_name):
                    entry = combo_cache.get(f'{kw}@{city_name}', {})
                    print(f'[{combo_idx}/{total_combos}] {kw} @ {city_name}  '
                          f'💤 跳过(连续{entry.get("zero_days",0)}天无新增，{entry.get("skip_until","")}恢复)')
                    skipped_combos += 1
                    if self._progress_cb:
                        try:
                            self._progress_cb(combo_idx, total_combos, kw, city_name, len(self.all_jobs))
                        except:
                            pass
                    continue

                elapsed = time.time() - t_start
                done_real = combo_idx - skipped_combos
                eta = (elapsed / max(done_real, 1)) * (active_combos - done_real) / 60 if done_real > 0 else 0
                print(f'[{combo_idx}/{total_combos}] {kw} @ {city_name}  '
                      f'(已用{elapsed/60:.1f}分 剩余≈{eta:.0f}分)')

                n = self.scrape_keyword(kw, city_code, city_name=city_name)
                print(f'  → +{n} 新增 | 累计 {len(self.all_jobs)} (跳过已有 {self.skipped_existing}, ID去重 {len(self._seen_job_ids)}, 过滤 {self.skipped})')

                # 策略J: 更新组合缓存
                _update_combo_cache(combo_cache, kw, city_name, n)

                # 进度回调
                if self._progress_cb:
                    try:
                        self._progress_cb(combo_idx, total_combos, kw, city_name, len(self.all_jobs))
                    except:
                        pass
                # 策略F: 动态关键词间休息
                if self._consecutive_stale >= 3:
                    random_delay(3, 6)
                else:
                    random_delay(KEYWORD_REST_MIN, KEYWORD_REST_MAX)

            # 策略F: 动态城市间休息
            if combo_idx < total_combos:
                if self._consecutive_stale >= 3:
                    rest = random.uniform(5, 12)
                else:
                    rest = random.uniform(CITY_REST_MIN, CITY_REST_MAX)
                print(f'  ☕ 城市切换休息 {rest:.0f}s...')
                simulate_human(self.page)
                time.sleep(rest)

        # 策略J: 保存缓存
        _save_combo_cache(combo_cache)
        if skipped_combos > 0:
            print(f'\n💤 策略J: 本次跳过 {skipped_combos}/{total_combos} 组')

        # 批量获取完整职位描述
        self.fetch_all_details()

        elapsed_total = (time.time() - t_start) / 60
        results = self._normalize_all()
        self.page.quit()
        # 不再清理 Profile，保留登录状态供下次使用
        print(f'\n✅ 完成! 耗时 {elapsed_total:.1f} 分钟')
        print(f'   新增强相关: {len(results)} 条 | 跳过已有: {self.skipped_existing} 条 | 过滤非相关: {self.skipped} 条')
        return results

    def _cleanup_profile(self):
        """仅清理临时 Profile（安全网），持久化 Profile 不清理"""
        if self._tmp_profile and Path(self._tmp_profile).exists():
            try:
                shutil.rmtree(self._tmp_profile, ignore_errors=True)
                logger.info(f'已清理临时 Profile: {self._tmp_profile}')
            except:
                pass

    def fetch_all_details(self):
        """批量获取新岗位的完整职位描述（已有数据已跳过）"""
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
            sid = job['security_id']
            try:
                # 通过详情页获取（更像真人浏览行为）
                eid = job.get('encrypt_job_id', '')
                got_desc = False

                if eid:
                    detail_page_url = f'https://www.zhipin.com/job_detail/{eid}.html'
                    self.page.listen.start('wapi/zpgeek/job/detail.json')
                    self.page.get(detail_page_url)
                    random_delay(1.5, 3.0)

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
                    self.page.listen.stop()

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

                    # 40% 概率模拟在详情页「阅读」
                    if got_desc and random.random() < 0.4:
                        simulate_human(self.page)

                if not got_desc and not job.get('full_desc'):
                    # 回退：直接用 API
                    try:
                        detail_url = f'{DETAIL_API}?securityId={sid}'
                        self.page.listen.start('wapi/zpgeek/job/detail.json')
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
                        self.page.listen.stop()
                    except:
                        self.page.listen.stop()

                if not job.get('full_desc'):
                    fail += 1
                    consecutive_fail += 1
                else:
                    consecutive_fail = 0

                # 连续失败过多，可能被封了，长休息
                if consecutive_fail >= 5:
                    print(f'  ⚠ 连续 {consecutive_fail} 次失败，休息 30s...')
                    time.sleep(random.uniform(25, 35))
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
                self.page.listen.stop()

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


def main():
    """独立运行入口"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    parser = argparse.ArgumentParser(description='BOSS直聘 AI PM 强相关岗位采集')
    parser.add_argument('--city', type=str, help='只抓指定城市')
    parser.add_argument('--quick', action='store_true', help='快速模式(≈5分钟)')
    parser.add_argument('--merge', action='store_true', help='自动合并到 Dashboard')
    parser.add_argument('--login', action='store_true', help='仅登录保存Cookie（首次使用）')
    parser.add_argument('--headless', action='store_true', help='无头模式（定时任务用）')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(name)s] %(message)s')

    cities = load_cities()
    keywords = QUICK_KEYWORDS if args.quick else SEARCH_KEYWORDS

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

    raw_jobs = spider.run(keywords, cities, headless=args.headless)

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
