#!/usr/bin/env python3
"""
临时全量贪婪爬取 — 关闭所有省时策略，仅保留去重
- 使用 keywords.json 中最新的 18 个关键词 × 10 城市
- 翻到底：连续5页0新增判定翻到底（BOSS API不返回空，会循环旧数据）
- 不修改 combo_cache.json
- 爬取完自动清洗+合并
- 不触发 git push / netlify deploy
"""
import sys
import json
import time
import random
import logging
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

# 日志
LOG_FILE = BASE_DIR / 'full_greedy.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('full_greedy')

from spiders.boss_dp import (
    BossDPSpider, collect_api_responses, random_delay, simulate_human,
    KEYWORD_REST_MIN, KEYWORD_REST_MAX, CITY_REST_MIN, CITY_REST_MAX,
)


def scrape_keyword_greedy(self, keyword, city_code, city_name=''):
    """翻到底为止：连续5页0新增则判定翻到底（BOSS API不返回空，会循环旧数据）"""
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

        page_new, page_existing, page_relevant, _, _ = self._add_jobs(page_jobs)
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
                sn = self._add_jobs(scroll_jobs)
                keyword_new += sn[0] if isinstance(sn, tuple) else sn

        self.page.listen.stop()
        random_delay(1.5, 3.5)

    return keyword_new


def main():
    t0 = time.time()
    logger.info('=' * 60)
    logger.info('🚀 全量贪婪爬取启动（18关键词 × 10城市，无省时策略）')
    logger.info('=' * 60)

    # 加载配置
    config_file = BASE_DIR / 'config' / 'keywords.json'
    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)
    keywords = config['keywords']
    cities = config['cities']
    logger.info(f'关键词: {len(keywords)} 个: {keywords}')
    logger.info(f'城市: {len(cities)} 个: {list(cities.keys())}')
    total_combos = len(keywords) * len(cities)
    logger.info(f'总组合: {total_combos}')

    # 创建爬虫
    spider = BossDPSpider()
    spider.start_browser(headless=False)
    first_city = list(cities.values())[0]
    if not spider.ensure_login(first_city):
        logger.error('登录失败，退出')
        spider.page.quit()
        return

    # Monkey-patch _add_jobs 返回更多信息
    original_add_jobs = spider._add_jobs
    def patched_add_jobs(api_jobs):
        from spiders.boss_dp import is_relevant
        new_count = 0
        existing_count = 0
        relevant_count = 0
        for job in api_jobs:
            name = job.get('job_name', '')
            skills = job.get('skills', '')
            if not is_relevant(name, skills):
                spider.skipped += 1
                continue
            relevant_count += 1
            key = f"{name}_{job.get('company', '')}"
            if key in spider.all_jobs:
                existing_count += 1
            elif name:
                spider.all_jobs[key] = job
                new_count += 1
        return new_count, existing_count, relevant_count, 0, 0
    spider._add_jobs = patched_add_jobs

    # 中间结果保存路径
    CHECKPOINT_FILE = BASE_DIR / 'logs' / 'greedy_checkpoint.json'

    # 加载断点（如果有的话，从上次中断处继续）
    done_combos = set()
    if CHECKPOINT_FILE.exists():
        try:
            cp = json.loads(CHECKPOINT_FILE.read_text(encoding='utf-8'))
            done_combos = set(cp.get('done_combos', []))
            logger.info(f'📌 发现断点文件，已完成 {len(done_combos)} 个组合，将跳过')
        except Exception:
            pass

    def save_checkpoint():
        """每个城市完成后保存中间结果，防止中断丢失"""
        results = spider._normalize_all()
        cp_data = {
            'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_jobs': len(results),
            'done_combos': list(done_combos),
        }
        CHECKPOINT_FILE.write_text(json.dumps(cp_data, ensure_ascii=False, indent=2), encoding='utf-8')
        # 保存原始数据到临时文件
        raw_file = BASE_DIR / 'logs' / 'greedy_raw_jobs.json'
        raw_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        logger.info(f'💾 已保存断点: {len(results)} 条原始数据, {len(done_combos)} 个组合完成')

    # 顺序执行所有组合
    combo_idx = 0
    for city_name, city_code in cities.items():
        logger.info(f'\n🏙 === {city_name} ===')
        city_new = 0
        for kw in keywords:
            combo_idx += 1
            combo_key = f'{kw}@{city_name}'

            # 跳过已完成的组合（断点恢复）
            if combo_key in done_combos:
                logger.info(f'[{combo_idx}/{total_combos}] {combo_key} — 已完成，跳过')
                continue

            elapsed = time.time() - t0
            eta = (elapsed / max(combo_idx - 1, 1)) * (total_combos - combo_idx) / 60 if combo_idx > 1 else 0
            logger.info(f'[{combo_idx}/{total_combos}] {kw} @ {city_name}  (已用{elapsed/60:.1f}分 剩余≈{eta:.0f}分)')

            n = scrape_keyword_greedy(spider, kw, city_code, city_name)
            city_new += n
            logger.info(f'  → +{n} 新增 | 累计 {len(spider.all_jobs)} (过滤 {spider.skipped})')
            done_combos.add(combo_key)

            random_delay(KEYWORD_REST_MIN, KEYWORD_REST_MAX)

        # 每个城市完成后保存断点
        logger.info(f'🏙 {city_name} 完成: +{city_new} 新增')
        save_checkpoint()

        if combo_idx < total_combos:
            rest = random.uniform(CITY_REST_MIN, CITY_REST_MAX)
            logger.info(f'  ☕ 城市切换休息 {rest:.0f}s...')
            time.sleep(rest)

    logger.info(f'\n✅ 完成! 耗时 {(time.time()-t0)/60:.1f} 分钟')
    logger.info(f'   新增强相关: {len(spider.all_jobs)} 条 | 跳过已有: {spider.skipped_existing if hasattr(spider,"skipped_existing") else "N/A"} 条 | 过滤非相关: {spider.skipped} 条')

    # 获取详情
    spider.fetch_all_details()

    # 标准化
    results = spider._normalize_all()
    spider.page.quit()
    logger.info(f'✅ 爬取完成: {len(results)} 条原始数据')

    # 清洗
    from pipeline import process_batch
    cleaned = process_batch(results)
    logger.info(f'清洗后: {len(cleaned)} 条有效岗位')

    # 合并
    from merger import load_existing, merge, save, save_snapshot
    existing_keys, existing_jobs = load_existing()
    old_total = len(existing_jobs)
    merged, added_count = merge(existing_jobs, existing_keys, cleaned)
    save(merged)
    save_snapshot(cleaned)

    logger.info('=' * 60)
    logger.info(f'🎉 全量贪婪爬取完成!')
    logger.info(f'   耗时: {(time.time()-t0)/60:.1f} 分钟')
    logger.info(f'   原有: {old_total} 条')
    logger.info(f'   抓取: {len(results)} → 清洗: {len(cleaned)} → 新增: {added_count}')
    logger.info(f'   总计: {len(merged)} 条')
    logger.info(f'   ⚠️  combo_cache.json 未被修改，原爬虫代码未改动')

    # 清理断点文件
    for f in [CHECKPOINT_FILE, BASE_DIR / 'logs' / 'greedy_raw_jobs.json']:
        if f.exists():
            f.unlink()
            logger.info(f'🗑 已删除临时文件: {f.name}')
    logger.info('=' * 60)


if __name__ == '__main__':
    main()
