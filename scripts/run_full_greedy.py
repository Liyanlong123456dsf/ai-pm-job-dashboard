#!/usr/bin/env python3
"""
全量贪婪爬取：10城市×9关键词，禁用所有跳过/省时策略，只保留去重
- 禁用策略A（重复率提前终止） — 翻完所有页
- 禁用策略B终止（整页ID重复终止） — 保留ID去重本身
- 禁用策略F（动态缩短延迟） — 统一正常延迟
- 禁用策略J（combo_cache跳过）
- 禁用策略P（城市分级翻页） — 强制10页
- 禁用策略Q（关键词排序） — 顺序执行
- 禁用策略R（时间窗终止）
- 保留：MD5去重、is_relevant过滤
"""
import sys
import logging
import time as _time
import random
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'full_greedy.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('full_greedy')


def main():
    logger.info('=' * 60)
    logger.info('🚀 全量贪婪爬取：禁用所有省时策略，只保留去重')
    logger.info('=' * 60)

    t0 = _time.time()

    from spiders import boss_dp
    from spiders.boss_dp import (
        BossDPSpider, SEARCH_KEYWORDS, load_cities,
        collect_api_responses, random_delay, simulate_human,
        MAX_SCROLLS_PER_PAGE, KEYWORD_REST_MIN, KEYWORD_REST_MAX,
        CITY_REST_MIN, CITY_REST_MAX,
    )
    import time
    import json

    # === 禁用策略J: combo_cache ===
    boss_dp._load_combo_cache = lambda: {}
    boss_dp._save_combo_cache = lambda cache: None
    boss_dp._should_skip_combo = lambda cache, kw, city: False
    boss_dp._update_combo_cache = lambda cache, kw, city, n: None

    # === 禁用策略P: 强制10页 ===
    boss_dp._max_pages_for_city = lambda city_name: 10

    # === 重写 scrape_keyword: 禁用策略A/B终止/F/R，保留去重 ===
    def scrape_keyword_greedy(self, keyword, city_code, city_name=''):
        """全量翻页，不提前终止，正常延迟"""
        keyword_new = 0
        max_pages = 10

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

            # 统一正常延迟（不缩短）
            random_delay(1.5, 3.0)

            if random.random() < 0.2:
                simulate_human(self.page)

            # 收集 API 响应
            page_jobs = collect_api_responses(self.page, timeout=8)
            page_new, page_existing, page_relevant, _, _ = self._add_jobs(page_jobs)
            keyword_new += page_new

            if len(page_jobs) == 0:
                self.page.listen.stop()
                logger.info(f'    ↳ 第{page_num}页无数据，停止')
                break

            logger.info(f'    ↳ 第{page_num}页: +{page_new}新 / {page_relevant}相关 / {page_existing}重复')

            # 有新数据时滚动加载更多
            if page_new > 0:
                for scroll_i in range(MAX_SCROLLS_PER_PAGE):
                    dist = random.randint(300, 700)
                    steps = random.randint(2, 3)
                    for _ in range(steps):
                        self.page.scroll.down(dist // steps + random.randint(-30, 30))
                        time.sleep(random.uniform(0.08, 0.25))
                    random_delay(0.8, 2.0)

                    if random.random() < 0.3:
                        simulate_human(self.page)

                    scroll_jobs = collect_api_responses(self.page, timeout=2)
                    if scroll_jobs:
                        sn, _, _, _, _ = self._add_jobs(scroll_jobs)
                        keyword_new += sn

            self.page.listen.stop()

            # 统一正常翻页延迟
            random_delay(2.5, 5.0)

        return keyword_new

    # Monkey-patch scrape_keyword
    BossDPSpider.scrape_keyword = scrape_keyword_greedy

    # === 重写 run: 禁用策略Q（顺序执行），禁用策略J ===
    original_run = BossDPSpider.run

    def run_greedy(self, keywords, cities, headless=False):
        """顺序执行，不随机打乱，不跳过"""
        self.start_browser(headless=headless)
        first_city = list(cities.values())[0]
        if not self.ensure_login(first_city):
            self.page.quit()
            return []

        total_combos = len(keywords) * len(cities)
        combo_idx = 0
        t_start = time.time()

        logger.info(f'📊 {len(keywords)} 关键词 × {len(cities)} 城市 = {total_combos} 组')
        logger.info(f'⏱  预计 {total_combos * 20 // 60}-{total_combos * 40 // 60} 分钟')

        # 顺序遍历城市和关键词（不打乱）
        for city_name, city_code in cities.items():
            for kw in keywords:
                combo_idx += 1
                elapsed = time.time() - t_start
                done = combo_idx - 1
                eta = (elapsed / max(done, 1)) * (total_combos - combo_idx) / 60 if done > 0 else 0
                logger.info(f'[{combo_idx}/{total_combos}] {kw} @ {city_name}  '
                      f'(已用{elapsed/60:.1f}分 剩余≈{eta:.0f}分)')

                n = self.scrape_keyword(kw, city_code, city_name=city_name)
                logger.info(f'  → +{n} 新增 | 累计 {len(self.all_jobs)} '
                      f'(跳过已有 {self.skipped_existing}, ID去重 {len(self._seen_job_ids)}, 过滤 {self.skipped})')

                if self._progress_cb:
                    try:
                        self._progress_cb(combo_idx, total_combos, kw, city_name, len(self.all_jobs))
                    except:
                        pass

                # 正常关键词间休息
                random_delay(KEYWORD_REST_MIN, KEYWORD_REST_MAX)

            # 正常城市间休息
            if combo_idx < total_combos:
                rest = random.uniform(CITY_REST_MIN, CITY_REST_MAX)
                logger.info(f'  ☕ 城市切换休息 {rest:.0f}s...')
                simulate_human(self.page)
                time.sleep(rest)

        # 批量获取详情
        self.fetch_all_details()

        elapsed_total = (time.time() - t_start) / 60
        results = self._normalize_all()
        self.page.quit()
        logger.info(f'✅ 完成! 耗时 {elapsed_total:.1f} 分钟')
        logger.info(f'   新增强相关: {len(results)} 条 | 跳过已有: {self.skipped_existing} 条 | 过滤非相关: {self.skipped} 条')
        return results

    BossDPSpider.run = run_greedy

    # === 执行 ===
    cities = load_cities()
    keywords = SEARCH_KEYWORDS

    logger.info(f'关键词({len(keywords)}): {keywords}')
    logger.info(f'城市({len(cities)}): {list(cities.keys())}')
    logger.info(f'翻页: 10 页/关键词')

    spider = BossDPSpider()
    raw_jobs = spider.run(keywords, cities, headless=False)

    if not raw_jobs:
        logger.warning('⚠ 未抓取到任何数据！')
        return

    logger.info(f'✅ 爬取完成: {len(raw_jobs)} 条原始数据')

    # === 清洗 + 合并 ===
    from pipeline import process_batch
    from merger import load_existing, merge, save, save_snapshot

    cleaned = process_batch(raw_jobs)
    logger.info(f'清洗后: {len(cleaned)} 条有效岗位')

    existing_keys, existing_jobs = load_existing()
    old_total = len(existing_jobs)
    merged, added = merge(existing_jobs, existing_keys, cleaned)
    save(merged)
    save_snapshot(cleaned)

    elapsed = (_time.time() - t0) / 60
    logger.info('=' * 60)
    logger.info(f'🎉 全量贪婪爬取完成!')
    logger.info(f'   耗时: {elapsed:.1f} 分钟')
    logger.info(f'   原有: {old_total} 条')
    logger.info(f'   抓取: {len(raw_jobs)} → 清洗: {len(cleaned)} → 新增: {added}')
    logger.info(f'   总计: {len(merged)} 条')
    logger.info(f'   ⚠️  combo_cache.json 未被修改，原爬虫代码未改动')
    logger.info('=' * 60)


if __name__ == '__main__':
    main()
