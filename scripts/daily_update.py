#!/usr/bin/env python3
"""
每日自动更新入口
用法：
  python3 daily_update.py              # 正常运行（抓取+合并）
  python3 daily_update.py --dry-run    # 仅测试爬虫，不写入文件
  python3 daily_update.py --boss-cookie "xxx"  # 指定 BOSS 直聘 Cookie
"""
import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime

# Setup paths
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

# Logging
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'crawler.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('daily')


def main():
    parser = argparse.ArgumentParser(description='AI PM 岗位每日更新')
    parser.add_argument('--dry-run', action='store_true', help='仅测试抓取，不写入文件')
    parser.add_argument('--quick', action='store_true', help='快速模式：只用核心关键词和TOP5城市')
    args = parser.parse_args()

    logger.info('=' * 50)
    logger.info(f'开始每日更新 {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    logger.info('=' * 50)

    # Load config
    config_file = BASE_DIR / 'config' / 'keywords.json'
    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)

    keywords = config['keywords']
    cities = config['cities']

    if args.quick:
        keywords = ['AI产品经理', 'AIGC产品经理']
        cities = {k: v for i, (k, v) in enumerate(cities.items()) if i < 5}
        logger.info(f'[QUICK] 关键词: {keywords}, 城市: {list(cities.keys())}')

    # === 1. 抓取 ===
    all_raw = []

    # BOSS直聘 (DrissionPage 自动化浏览器)
    try:
        from spiders.boss_dp import BossDPSpider
        spider = BossDPSpider()
        jobs = spider.run(keywords, cities, headless=True)
        all_raw.extend(jobs)
        logger.info(f'BOSS直聘: 抓取 {len(jobs)} 条原始数据')
    except Exception as e:
        logger.error(f'BOSS直聘 爬虫失败: {e}', exc_info=True)

    if not all_raw:
        logger.warning('今日未抓取到任何数据！')
        if not args.dry_run:
            pass  # TODO: send alert notification
        return

    # === 2. 清洗 ===
    from pipeline import process_batch
    cleaned = process_batch(all_raw)
    logger.info(f'清洗后: {len(cleaned)} 条有效岗位')

    if args.dry_run:
        logger.info('[DRY RUN] 不写入文件，打印前 5 条:')
        for j in cleaned[:5]:
            logger.info(f'  {j["title"]} | {j["company"]} | {j["city"]} | {j["salary"]}')
        return

    # === 3. 合并 ===
    from merger import load_existing, merge, save, save_snapshot
    existing_keys, existing_jobs = load_existing()
    merged, added_count = merge(existing_jobs, existing_keys, cleaned)

    # === 4. 保存 ===
    save(merged)
    save_snapshot(cleaned)

    logger.info(f'合并完成: 新增 {added_count} 条, 总计 {len(merged)} 条')

    if added_count == 0:
        logger.warning('⚠️ 今日新增为 0，可能被反爬或无新岗位')

    # === 5. 回填链接 ===
    try:
        logger.info('开始回填链接...')
        import subprocess
        subprocess.run([sys.executable, str(SCRIPT_DIR / 'backfill_csv.py')],
                       cwd=str(BASE_DIR), check=True)
        logger.info('✅ 链接回填完成')
    except Exception as e:
        logger.warning(f'链接回填失败(非致命): {e}')

    # === 6. 补全缺失描述 ===
    try:
        with open(BASE_DIR / 'jobs_data.json', 'r', encoding='utf-8') as f:
            data_check = json.load(f)
        missing = sum(1 for j in data_check.get('jobs', [])
                      if j.get('url') and (not j.get('desc') or len(j['desc'].strip()) < 20))
        if missing > 0:
            logger.info(f'发现 {missing} 条描述缺失，开始追踪补全...')
            subprocess.run([sys.executable, str(SCRIPT_DIR / 'backfill_desc.py')],
                           cwd=str(BASE_DIR), check=True)
            logger.info('✅ 描述补全完成')
        else:
            logger.info('所有岗位描述完整，跳过补全')
    except Exception as e:
        logger.warning(f'描述补全失败(非致命): {e}')

    # === 7. 导出统一总表 ===
    try:
        subprocess.run([sys.executable, str(SCRIPT_DIR / 'export_total.py')],
                       cwd=str(BASE_DIR), check=True)
        logger.info('✅ 统一总表已导出')
    except Exception as e:
        logger.warning(f'总表导出失败(非致命): {e}')

    # === 8. Git 提交 + 推送 ===
    try:
        import subprocess
        today = datetime.now().strftime('%Y-%m-%d')
        subprocess.run(['git', 'add', '-A'], cwd=str(BASE_DIR), check=True)
        subprocess.run(['git', 'commit', '-m',
                         f'daily: {today} 新增{added_count}条 总{len(merged)}条'],
                       cwd=str(BASE_DIR), check=True)
        subprocess.run(['git', 'push', 'origin', 'main'], cwd=str(BASE_DIR), check=True)
        logger.info('✅ Git 提交推送完成')
    except Exception as e:
        logger.warning(f'Git 推送失败(非致命): {e}')

    # === 9. 同步 dist 目录 + Netlify 部署 ===
    try:
        dist_dir = BASE_DIR / 'dist'
        dist_dir.mkdir(exist_ok=True)
        import shutil
        for fname in ['job_dashboard.html', 'jobs_data.json', 'index.html', 'netlify.toml']:
            src = BASE_DIR / fname
            if src.exists():
                shutil.copy2(src, dist_dir / fname)
        logger.info(f'dist 目录已同步')
        result = subprocess.run(['netlify', 'deploy', '--prod', '--dir=dist'],
                                cwd=str(BASE_DIR), capture_output=True, text=True)
        if result.returncode == 0:
            logger.info('✅ Netlify 部署完成')
        else:
            logger.warning(f'Netlify 部署失败: {result.stderr}')
    except Exception as e:
        logger.warning(f'Netlify 部署失败(非致命): {e}')

    # === 10. 最终汇报 ===
    with open(BASE_DIR / 'jobs_data.json', 'r', encoding='utf-8') as f:
        final = json.load(f)
    final_jobs = final.get('jobs', [])
    has_url = sum(1 for j in final_jobs if j.get('url'))
    has_desc = sum(1 for j in final_jobs if j.get('desc') and len(j['desc'].strip()) >= 20)
    logger.info('=' * 50)
    logger.info(f'✅ 每日更新全流程完成')
    logger.info(f'   总岗位: {len(final_jobs)}')
    logger.info(f'   新增: {added_count}')
    logger.info(f'   有链接: {has_url}/{len(final_jobs)}')
    logger.info(f'   有描述: {has_desc}/{len(final_jobs)}')
    logger.info('=' * 50)


if __name__ == '__main__':
    main()
