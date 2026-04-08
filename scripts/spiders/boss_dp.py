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
import logging
import argparse
from pathlib import Path

logger = logging.getLogger('spider.boss_dp')

# ==================== 配置 ====================

# 全量: 5关键词×10城市 ≈ 12分钟
SEARCH_KEYWORDS = [
    'AI产品经理',
    'AIGC产品经理',
    '大模型产品经理',
    '人工智能产品经理',
    '智能体产品经理',
]

# 快速: 2关键词×5城市 ≈ 5分钟
QUICK_KEYWORDS = ['AI产品经理', 'AIGC产品经理']

CONFIG_DIR = Path(__file__).parent.parent.parent / 'config'
PROFILE_DIR = Path(__file__).parent.parent.parent / '.chrome_profile'  # 持久化登录

# 翻页与滚动
MAX_PAGES = 5           # 每个关键词最多翻5页
MAX_SCROLLS_PER_PAGE = 5

# 防封参数
MIN_DELAY, MAX_DELAY = 0.8, 2.0
KEYWORD_REST_MIN, KEYWORD_REST_MAX = 3, 6

# 强相关过滤：岗位名必须命中以下任一关键词才算"AI PM 强相关"
RELEVANT_KEYWORDS = [
    'AI', 'ai', 'AIGC', '人工智能', '大模型', 'LLM', 'GPT',
    '智能', '算法', 'NLP', '机器学习', 'ML', '深度学习',
    '产品经理', '产品负责人', '产品总监', '产品专家',
    '智能体', 'Agent',
]


def load_cities():
    cfg_file = CONFIG_DIR / 'keywords.json'
    with open(cfg_file, 'r', encoding='utf-8') as f:
        return json.load(f)['cities']


def random_delay(lo=MIN_DELAY, hi=MAX_DELAY):
    time.sleep(random.uniform(lo, hi))


def is_relevant(job_name: str, skills: str = '') -> bool:
    """判断岗位是否与 AI 产品经理强相关"""
    text = f'{job_name} {skills}'.upper()
    has_ai = any(kw.upper() in text for kw in [
        'AI', 'AIGC', '人工智能', '大模型', 'LLM', 'GPT', 'NLP',
        '智能', '算法', '机器学习', 'ML', '深度学习', '智能体', 'AGENT',
    ])
    has_pm = any(kw in text for kw in [
        '产品', 'PRODUCT', '产品经理', '产品负责', '产品总监', '产品专家',
    ])
    return has_ai and has_pm


def simulate_human(page):
    """模拟真人浏览：随机滚动、停顿"""
    for _ in range(random.randint(1, 3)):
        act = random.choice(['down', 'up', 'pause'])
        if act == 'down':
            page.scroll.down(random.randint(150, 500))
            time.sleep(random.uniform(0.2, 0.8))
        elif act == 'up':
            page.scroll.up(random.randint(50, 200))
            time.sleep(random.uniform(0.2, 0.6))
        else:
            time.sleep(random.uniform(0.3, 1.0))


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

    def start_browser(self, headless=False):
        from DrissionPage import ChromiumPage, ChromiumOptions
        from DrissionPage.common import Settings
        Settings.set_singleton_tab_obj(False)

        PROFILE_DIR.mkdir(exist_ok=True)
        co = ChromiumOptions()
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_user_agent(
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        )
        co.set_pref('excludeSwitches', ['enable-automation'])
        co.set_pref('useAutomationExtension', False)
        # 持久化 Profile：登录一次，Cookie 永久保存
        co.set_user_data_path(str(PROFILE_DIR))
        if headless:
            co.set_argument('--headless=new')
        self.page = ChromiumPage(addr_or_opts=co)
        print('✓ 浏览器已启动 (Profile:', PROFILE_DIR, ')')

    def ensure_login(self, city_code):
        """检测登录状态，未登录则等待用户操作（仅首次需要）"""
        url = f'https://www.zhipin.com/web/geek/job?query=AI产品经理&city={city_code}'
        self.page.get(url)
        time.sleep(5)

        # 检测是否已登录：多种方式判断
        for attempt in range(8):
            try:
                has_jobs = self.page.run_js(
                    'return document.querySelectorAll("li[class*=job-card]").length > 0'
                )
                if has_jobs:
                    print('✓ 已登录，检测到岗位列表')
                    return True
                # 也检查是否有验证页面，等待自动通过
                is_verify = self.page.run_js(
                    'return document.title.includes("安全") || document.title.includes("验证")'
                )
                if is_verify:
                    print(f'  等待安全验证通过... ({attempt+1}/8)')
            except:
                pass
            time.sleep(3)

        # 未登录 — 如果是交互模式，等用户操作
        if sys.stdin.isatty():
            print('\n' + '=' * 50)
            print('🔐 首次使用，请在 Chrome 中登录 BOSS直聘')
            print('   登录后 Cookie 会自动保存，以后无需再登录')
            print('=' * 50)
            input('\n✅ 登录完成后按 回车键...\n')
            return True
        else:
            # 非交互模式（launchd等），登录已过期
            print('⚠ 登录已过期，请手动运行一次: python3 spiders/boss_dp.py --login')
            return False

    def _add_jobs(self, api_jobs):
        """添加岗位（带强相关过滤和去重）"""
        new_count = 0
        for job in api_jobs:
            name = job.get('job_name', '')
            skills = job.get('skills', '')

            if not is_relevant(name, skills):
                self.skipped += 1
                continue

            key = f"{name}_{job.get('company', '')}"
            if key not in self.all_jobs and name:
                self.all_jobs[key] = job
                new_count += 1
        return new_count

    def scrape_keyword(self, keyword: str, city_code: str) -> int:
        """用 API 拦截 + 翻页模式抓取一个关键词"""
        keyword_new = 0
        no_new_pages = 0

        for page_num in range(1, MAX_PAGES + 1):
            self.page.listen.start('wapi/zpgeek/search/joblist.json')

            url = f'https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}&page={page_num}'
            self.page.get(url)
            random_delay(1, 2)

            # 收集翻页触发的 API
            page_jobs = collect_api_responses(self.page, timeout=8)
            page_new = self._add_jobs(page_jobs)
            keyword_new += page_new

            if len(page_jobs) == 0:
                self.page.listen.stop()
                break

            # 滚动触发更多加载
            scroll_no_new = 0
            for _ in range(MAX_SCROLLS_PER_PAGE):
                self.page.scroll.down(random.randint(500, 900))
                random_delay(0.5, 1.2)

                # 偶尔模拟人类
                if random.random() < 0.2:
                    simulate_human(self.page)

                scroll_jobs = collect_api_responses(self.page, timeout=2)
                if scroll_jobs:
                    sn = self._add_jobs(scroll_jobs)
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

            random_delay(0.5, 1.5)

        return keyword_new

    def run(self, keywords: list, cities: dict, headless: bool = False) -> list:
        """完整抓取流程"""
        self.start_browser(headless=headless)
        first_city = list(cities.values())[0]
        if not self.ensure_login(first_city):
            self.page.quit()
            return []

        total_combos = len(keywords) * len(cities)
        combo_idx = 0
        t_start = time.time()

        print(f'\n📊 {len(keywords)} 关键词 × {len(cities)} 城市 = {total_combos} 组')
        print(f'⏱  预计 {max(1, total_combos * 15 // 60)}-{total_combos * 25 // 60} 分钟\n')

        for city_name, city_code in cities.items():
            for kw in keywords:
                combo_idx += 1
                elapsed = time.time() - t_start
                eta = (elapsed / max(combo_idx - 1, 1)) * (total_combos - combo_idx) if combo_idx > 1 else 0
                print(f'[{combo_idx}/{total_combos}] {kw} @ {city_name}  '
                      f'(已用{elapsed/60:.1f}分 剩余≈{eta/60:.0f}分)')

                n = self.scrape_keyword(kw, city_code)
                print(f'  → +{n} 强相关 | 累计 {len(self.all_jobs)} (过滤 {self.skipped})')
                random_delay(1, 3)

            # 城市间休息 + 模拟行为
            if combo_idx < total_combos:
                rest = random.uniform(KEYWORD_REST_MIN, KEYWORD_REST_MAX)
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

        for idx, (key, job) in enumerate(jobs_needing_detail, 1):
            sid = job['security_id']
            try:
                # 通过 DrissionPage 发起详情 API 请求
                detail_url = f'{DETAIL_API}?securityId={sid}'
                self.page.listen.start('wapi/zpgeek/job/detail.json')
                self.page.get(detail_url)

                # 尝试从 API 响应获取
                try:
                    r = self.page.listen.wait(timeout=5)
                    if r and r.response and r.response.body:
                        body = r.response.body
                        if isinstance(body, str):
                            body = json.loads(body)
                        desc = body.get('zpData', {}).get('jobInfo', {}).get('postDescription', '')
                        if desc:
                            job['full_desc'] = desc
                            success += 1
                except:
                    pass
                self.page.listen.stop()

                # 如果 API 拦截失败，尝试从岗位详情页抓取
                if not job.get('full_desc'):
                    eid = job.get('encrypt_job_id', '')
                    if eid:
                        detail_page_url = f'https://www.zhipin.com/job_detail/{eid}.html'
                        self.page.get(detail_page_url)
                        random_delay(1, 2)
                        try:
                            desc_text = self.page.run_js(
                                'return document.querySelector(".job-sec-text")?.innerText || '
                                'document.querySelector(".job-detail-section .text")?.innerText || ""'
                            )
                            if desc_text and len(desc_text) > 20:
                                job['full_desc'] = desc_text
                                success += 1
                        except:
                            pass

                if not job.get('full_desc'):
                    fail += 1

                if idx % 20 == 0:
                    print(f'  详情进度: {idx}/{total} (成功 {success}, 失败 {fail})')

                random_delay(0.5, 1.2)

                # 每 30 个岗位休息一下防封
                if idx % 30 == 0:
                    simulate_human(self.page)
                    time.sleep(random.uniform(2, 4))

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
