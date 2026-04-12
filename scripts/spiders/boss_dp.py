#!/usr/bin/env python3
"""
BOSS直聘爬虫 - API拦截模式 + 强相关过滤
基于 boss-zp-main 的 API 拦截方案，速度快、数据完整

用法:
  python boss_dp.py --merge           # 全量抓取并合并到 Dashboard
  python boss_dp.py --quick --merge   # 快速模式(≈8分钟)
  python boss_dp.py --city 杭州       # 只抓指定城市
"""
import sys, io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import json
import time
import random
import math
import logging
import argparse
from pathlib import Path

logger = logging.getLogger('spider.boss_dp')

# ==================== 配置 ====================

CONFIG_DIR = Path(__file__).parent.parent.parent / 'config'
PROFILE_DIR = Path(__file__).parent.parent.parent / '.chrome_profile'  # 持久化登录

# 翻页与滚动
MAX_PAGES = 4           # 每个关键词最多翻4页，覆盖更全
MAX_SCROLLS_PER_PAGE = 3

# 防封参数 — 风控是红线，完全模拟真人节奏，目标☂50分钟
MIN_DELAY, MAX_DELAY = 1.5, 3.5
KEYWORD_REST_MIN, KEYWORD_REST_MAX = 5, 12
CITY_REST_MIN, CITY_REST_MAX = 8, 18
DETAIL_DELAY_MIN, DETAIL_DELAY_MAX = 1.5, 3.0
DETAIL_BATCH_PAUSE = (8, 15)   # 每批详情后的长休息
DETAIL_BATCH_SIZE = 15         # 每扱15个，更小批次更安全

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


def load_config():
    """加载 keywords.json 全量配置"""
    cfg_file = CONFIG_DIR / 'keywords.json'
    with open(cfg_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_cities():
    return load_config()['cities']


def load_keywords(quick=False):
    """加载关键词：全量读全部，快速随机抽 3-5 个"""
    config = load_config()
    all_kw = config['keywords']
    if quick:
        n = random.randint(3, 5)
        selected = random.sample(all_kw, min(n, len(all_kw)))
        logger.info(f'[快速模式] 随机抽取 {len(selected)} 个关键词: {selected}')
        return selected
    return all_kw


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
            self.page.listen.start('wapi/zpgeek/search/joblist.json')

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
            random_delay(1.5, 3.0)
            # 20% 概率模拟浏览行为
            if random.random() < 0.2:
                simulate_human(self.page)

            # 收集翻页触发的 API
            page_jobs = collect_api_responses(self.page, timeout=8)
            page_new, _, _ = self._add_jobs(page_jobs)
            keyword_new += page_new

            if len(page_jobs) == 0:
                self.page.listen.stop()
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

            self.page.listen.stop()

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
        """贪婪模式：翻到底为止（连续5页0新增判定翻到底）"""
        keyword_new = 0
        page_num = 0
        consecutive_zero = 0
        MAX_CONSECUTIVE_ZERO = 5

        while True:
            page_num += 1
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

            random_delay(1.5, 3.0)
            if random.random() < 0.2:
                simulate_human(self.page)

            page_jobs = collect_api_responses(self.page, timeout=8)

            if len(page_jobs) == 0:
                self.page.listen.stop()
                logger.info(f'    ↳ 第{page_num}页: API返回空，停止')
                break

            page_new, page_existing, page_relevant = self._add_jobs(page_jobs)
            keyword_new += page_new

            logger.info(f'    ↳ 第{page_num}页: +{page_new}新 / {page_relevant}相关 / {page_existing}重复 (原始{len(page_jobs)}条)')

            if page_new == 0:
                consecutive_zero += 1
                if consecutive_zero >= MAX_CONSECUTIVE_ZERO:
                    self.page.listen.stop()
                    logger.info(f'    ↳ 连续{MAX_CONSECUTIVE_ZERO}页无新增，判定已翻到底（共{page_num}页）')
                    break
            else:
                consecutive_zero = 0

            # 滚动加载
            for scroll_i in range(3):
                dist = random.randint(300, 700)
                steps = random.randint(2, 3)
                for _ in range(steps):
                    self.page.scroll.down(dist // steps + random.randint(-30, 30))
                    time.sleep(random.uniform(0.08, 0.25))
                random_delay(0.8, 2.0)
                scroll_jobs = collect_api_responses(self.page, timeout=2)
                if scroll_jobs:
                    sn, _, _ = self._add_jobs(scroll_jobs)
                    keyword_new += sn

            self.page.listen.stop()
            random_delay(1.5, 3.5)

        return keyword_new

    def run(self, keywords: list, cities: dict, headless: bool = False, greedy: bool = False) -> list:
        """完整抓取流程"""
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

        total_combos = len(keywords) * len(cities)
        combo_idx = 0
        t_start = time.time()

        mode_label = '贪婪' if greedy else '标准'
        print(f'\n📊 [{mode_label}] {len(keywords)} 关键词 × {len(cities)} 城市 = {total_combos} 组')
        print(f'⏱  预计 {max(1, total_combos * 15 // 60)}-{total_combos * 25 // 60} 分钟\n')

        # 随机打乱城市顺序，避免固定遍历模式
        city_items = list(cities.items())
        random.shuffle(city_items)

        for city_i, (city_name, city_code) in enumerate(city_items):
            # 每个城市内随机打乱关键词顺序
            kw_list = list(keywords)
            random.shuffle(kw_list)

            for kw in kw_list:
                combo_idx += 1
                elapsed = time.time() - t_start
                eta = (elapsed / max(combo_idx - 1, 1)) * (total_combos - combo_idx) if combo_idx > 1 else 0
                print(f'[{combo_idx}/{total_combos}] {kw} @ {city_name}  '
                      f'(已用{elapsed/60:.1f}分 剩余≈{eta/60:.0f}分)')

                n = self.scrape_keyword_greedy(kw, city_code, city_name) if greedy else self.scrape_keyword(kw, city_code)
                print(f'  → +{n} 强相关 | 累计 {len(self.all_jobs)} (过滤 {self.skipped})')
                # 进度回调
                if self._progress_cb:
                    try:
                        self._progress_cb(combo_idx, total_combos, kw, city_name, len(self.all_jobs))
                    except:
                        pass
                # 关键词间休息
                random_delay(KEYWORD_REST_MIN, KEYWORD_REST_MAX)

            # 城市间休息 + 模拟行为
            if combo_idx < total_combos:
                rest = random.uniform(CITY_REST_MIN, CITY_REST_MAX)
                print(f'  ☕ 城市切换休息 {rest:.0f}s...')
                simulate_human(self.page)
                time.sleep(rest)

        # 批量获取完整职位描述
        self.fetch_all_details()

        elapsed_total = (time.time() - t_start) / 60
        results = self._normalize_all()
        self.page.quit()
        print(f'\n✅ 完成! 耗时 {elapsed_total:.1f} 分钟')
        print(f'   强相关岗位: {len(results)} 条 | 过滤非相关: {self.skipped} 条')
        return results

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
            sid = job['security_id']
            try:
                # 通过详情页获取（更像真人浏览行为）
                eid = job.get('encrypt_job_id', '')
                got_desc = False

                if eid:
                    detail_page_url = f'https://www.zhipin.com/job_detail/{eid}.html'
                    self.page.listen.start('wapi/zpgeek/job/detail.json')
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

                    # 10% 概率模拟阅读
                    if got_desc and random.random() < 0.1:
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
    parser.add_argument('--quick', action='store_true', help='快速模式（随机3-5个关键词）')
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
