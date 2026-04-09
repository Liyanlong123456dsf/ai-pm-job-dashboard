#!/usr/bin/env python3
"""追踪原链接补全缺失的岗位描述"""
import json, time, random, re, sys
from pathlib import Path

BASE = Path(__file__).parent.parent
JSON_PATH = BASE / 'jobs_data.json'
PROFILE_DIR = BASE / '.chrome_profile'

def random_delay(lo=0.8, hi=1.8):
    time.sleep(random.uniform(lo, hi))

def main():
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    jobs = data.get('jobs', [])

    # 找出描述缺失或偏短（可能被截断）且有链接的岗位
    need_fix = [(i, j) for i, j in enumerate(jobs)
                if j.get('url') and (not j.get('desc') or len(j['desc'].strip()) < 200)]

    print(f'总岗位: {len(jobs)}, 描述缺失且有链接: {len(need_fix)}')
    if not need_fix:
        print('✅ 无需补全')
        return

    # 启动浏览器
    from DrissionPage import ChromiumPage, ChromiumOptions
    co = ChromiumOptions()
    co.set_user_data_path(str(PROFILE_DIR))
    co.set_argument('--no-first-run')
    page = ChromiumPage(co)
    print('✓ 浏览器已启动')

    success = 0
    fail = 0
    total = len(need_fix)

    for idx, (job_idx, job) in enumerate(need_fix, 1):
        url = job['url']
        try:
            page.get(url)
            random_delay(1.5, 3.0)

            # 从详情页抓取岗位描述
            desc_text = page.run_js('''
                return document.querySelector(".job-sec-text")?.innerText ||
                       document.querySelector(".job-detail-section .text")?.innerText ||
                       document.querySelector(".job-detail .text")?.innerText ||
                       document.querySelector(".job-description")?.innerText || ""
            ''')

            if desc_text and len(desc_text.strip()) > 20:
                jobs[job_idx]['desc'] = desc_text.strip()
                success += 1
            else:
                fail += 1

            if idx % 10 == 0:
                print(f'  进度: {idx}/{total} (成功 {success}, 失败 {fail})')
                # 中间保存，防止中断丢失
                data['jobs'] = jobs
                with open(JSON_PATH, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)

            # 防封
            if idx % 20 == 0:
                for _ in range(random.randint(1, 3)):
                    page.scroll.down(random.randint(100, 300))
                    time.sleep(random.uniform(0.3, 0.8))
                time.sleep(random.uniform(2, 4))
            else:
                random_delay(0.5, 1.2)

        except Exception as e:
            print(f'  ✗ [{idx}] {job["title"]}: {e}')
            fail += 1

    # 最终保存
    data['jobs'] = jobs
    import datetime
    data['meta']['updated'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

    page.quit()
    print(f'\n✅ 完成! 成功 {success}/{total}, 失败 {fail}')
    
    # 统计最终情况
    still_missing = sum(1 for j in jobs if not j.get('desc') or len(j['desc'].strip()) < 20)
    print(f'剩余描述缺失: {still_missing}')

if __name__ == '__main__':
    main()
