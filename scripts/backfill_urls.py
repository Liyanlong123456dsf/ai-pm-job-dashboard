#!/usr/bin/env python3
"""
回填岗位链接：通过 BOSS 搜索 API 为现有 jobs_data.json 补全 url 字段
用法: python3 scripts/backfill_urls.py
需要 DrissionPage + 已登录的 Chrome Profile
"""
import json
import time
import random
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_FILE = BASE_DIR / 'jobs_data.json'
PROFILE_DIR = BASE_DIR / '.chrome_profile'


def main():
    from DrissionPage import ChromiumPage, ChromiumOptions
    from DrissionPage.common import Settings
    Settings.set_singleton_tab_obj(False)

    # 读取现有数据
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    jobs = data.get('jobs', [])
    total = len(jobs)
    already = sum(1 for j in jobs if j.get('url'))
    print(f'总岗位: {total}, 已有链接: {already}, 需补全: {total - already}')

    if already == total:
        print('所有岗位已有链接，无需操作')
        return

    # 启动浏览器
    PROFILE_DIR.mkdir(exist_ok=True)
    co = ChromiumOptions()
    co.set_argument('--disable-blink-features=AutomationControlled')
    co.set_user_data_path(str(PROFILE_DIR))
    page = ChromiumPage(addr_or_opts=co)

    # 按 title 分组搜索（减少请求次数）
    # 收集所有不重复的 title
    titles_to_search = set()
    for j in jobs:
        if not j.get('url'):
            titles_to_search.add(j['title'])

    print(f'需搜索 {len(titles_to_search)} 个不同标题\n')

    # title -> list of {jobName, brandName, encryptJobId}
    search_cache = {}
    searched = 0

    for title in titles_to_search:
        searched += 1
        print(f'[{searched}/{len(titles_to_search)}] 搜索: {title}', end='')

        page.listen.start('wapi/zpgeek/search/joblist.json')
        url = f'https://www.zhipin.com/web/geek/job?query={title}&page=1'
        page.get(url)
        time.sleep(random.uniform(1.5, 3.0))

        try:
            r = page.listen.wait(timeout=8)
            if r and r.response and r.response.body:
                body = r.response.body
                if isinstance(body, str):
                    body = json.loads(body)
                job_list = body.get('zpData', {}).get('jobList', [])
                for item in job_list:
                    name = item.get('jobName', '')
                    company = item.get('brandName', '')
                    eid = item.get('encryptJobId', '')
                    if eid:
                        key = f"{name}_{company}"
                        search_cache[key] = f"https://www.zhipin.com/job_detail/{eid}.html"
                print(f'  → 获取 {len(job_list)} 条')
            else:
                print(f'  → 无响应')
        except Exception as e:
            print(f'  → 错误: {e}')
        page.listen.stop()

        # 每 15 次搜索休息一下
        if searched % 15 == 0:
            rest = random.uniform(3, 6)
            print(f'  💤 休息 {rest:.1f}s')
            time.sleep(rest)

    page.quit()

    # 匹配并回填
    matched = 0
    for j in jobs:
        if j.get('url'):
            continue
        key = f"{j['title']}_{j['company']}"
        if key in search_cache:
            j['url'] = search_cache[key]
            matched += 1
        else:
            # 尝试只用 title 模糊匹配
            for cache_key, cache_url in search_cache.items():
                if cache_key.startswith(j['title'] + '_'):
                    j['url'] = cache_url
                    matched += 1
                    break

    print(f'\n✅ 匹配成功: {matched}/{total - already}')
    print(f'   最终有链接: {sum(1 for j in jobs if j.get("url"))}/{total}')

    # 保存
    data['jobs'] = jobs
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    print(f'💾 已保存到 {DATA_FILE}')


if __name__ == '__main__':
    main()
