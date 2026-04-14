#!/usr/bin/env python3
"""追踪原链接补全缺失的岗位描述"""
import sys, io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import json, time, random, re, datetime
from pathlib import Path
from pipeline import clean_desc, classify, parse_salary, salary_tier

BASE = Path(__file__).parent.parent
JSON_PATH = BASE / 'jobs_data.json'
PROFILE_DIR = BASE / '.chrome_profile'

def random_delay(lo=0.8, hi=1.8):
    time.sleep(random.uniform(lo, hi))

def _need_desc(job):
    return not job.get('desc') or len(str(job.get('desc') or '').strip()) < 30

def _need_salary(job):
    return not str(job.get('salary') or '').strip()

def _extract_salary(text):
    s = re.sub(r'\s+', '', str(text or ''))
    if not s:
        return ''
    patterns = [
        r'\d{1,3}(?:\.\d+)?-\d{1,3}(?:\.\d+)?K(?:·\d+薪)?',
        r'\d{1,3}(?:\.\d+)?K以上',
        r'\d{1,5}-\d{1,5}元/天',
        r'\d{1,5}-\d{1,5}元/月',
    ]
    for pattern in patterns:
        m = re.search(pattern, s, re.IGNORECASE)
        if m:
            return m.group(0).upper()
    return ''

def _refresh_job(job):
    desc = clean_desc(job.get('desc', ''))
    if desc:
        job['desc'] = desc
        cats, kw = classify(f"{job.get('company', '')} {job.get('title', '')} {desc}")
        if cats:
            job['cats'] = cats
        elif not job.get('cats'):
            job['cats'] = ['AI通用']
        if kw:
            job['kw'] = kw
    salary = str(job.get('salary') or '').strip()
    if salary:
        job['salary'] = salary
        avg = parse_salary(salary)
        job['avg'] = avg
        job['tier'] = salary_tier(avg)

def _extract_from_api(page, url):
    desc = ''
    salary = ''
    try:
        page.listen.start('wapi/zpgeek/job/detail.json')
        page.get(url)
        random_delay(1.5, 3.0)
        r = page.listen.wait(timeout=4)
        if r and r.response and r.response.body:
            body = r.response.body
            if isinstance(body, str):
                body = json.loads(body)
            job_info = body.get('zpData', {}).get('jobInfo', {})
            desc = clean_desc(job_info.get('postDescription', ''))
            salary = _extract_salary(
                job_info.get('salaryDesc')
                or job_info.get('salary')
                or job_info.get('showSalary')
                or job_info.get('salaryRange')
                or json.dumps(job_info, ensure_ascii=False)
            )
    except Exception:
        pass
    finally:
        try:
            page.listen.stop()
        except Exception:
            pass
    return desc, salary

def _extract_from_dom(page):
    desc = ''
    salary = ''
    try:
        data = page.run_js('''
            const pick = (...sels) => {
                for (const sel of sels) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText && el.innerText.trim()) return el.innerText.trim();
                }
                return "";
            };
            return {
                desc: pick(".job-sec-text", ".job-detail-section .text", ".job-detail .text", ".job-description"),
                salary: pick(".job-primary .salary", ".job-banner .salary", ".info-primary .salary", ".name .salary", ".job-info .salary"),
                header: pick(".job-primary", ".job-banner", ".job-card-left", ".job-detail-box")
            };
        ''')
        desc = clean_desc((data or {}).get('desc', ''))
        salary = _extract_salary((data or {}).get('salary', '')) or _extract_salary((data or {}).get('header', ''))
    except Exception:
        pass
    return desc, salary

def main():
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    jobs = data.get('jobs', [])

    need_fix = [(i, j) for i, j in enumerate(jobs)
                if j.get('url') and (_need_desc(j) or _need_salary(j))]

    print(f'总岗位: {len(jobs)}, 缺字段且有链接: {len(need_fix)}')
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
    desc_success = 0
    salary_success = 0
    total = len(need_fix)

    for idx, (job_idx, job) in enumerate(need_fix, 1):
        url = job['url']
        try:
            need_desc = _need_desc(job)
            need_salary = _need_salary(job)
            api_desc, api_salary = _extract_from_api(page, url)
            dom_desc, dom_salary = _extract_from_dom(page)
            filled = False

            if need_desc:
                desc_text = api_desc or dom_desc
                if desc_text and len(desc_text.strip()) > 20:
                    jobs[job_idx]['desc'] = desc_text.strip()
                    desc_success += 1
                    filled = True

            if need_salary:
                salary_text = api_salary or dom_salary
                if salary_text:
                    jobs[job_idx]['salary'] = salary_text.strip()
                    salary_success += 1
                    filled = True

            if filled:
                _refresh_job(jobs[job_idx])
                success += 1
            else:
                fail += 1

            if idx % 10 == 0:
                print(f'  进度: {idx}/{total} (岗位成功 {success}, 描述补回 {desc_success}, 薪资补回 {salary_success}, 失败 {fail})')
                data['jobs'] = jobs
                with open(JSON_PATH, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)

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
    data.setdefault('meta', {})
    data['meta']['updated'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

    page.quit()
    print(f'\n✅ 完成! 岗位成功 {success}/{total}, 失败 {fail}')
    print(f'补回描述: {desc_success}')
    print(f'补回薪资: {salary_success}')
    still_missing_desc = sum(1 for j in jobs if _need_desc(j))
    still_missing_salary = sum(1 for j in jobs if _need_salary(j))
    still_missing_desc_with_url = sum(1 for j in jobs if j.get('url') and _need_desc(j))
    still_missing_salary_with_url = sum(1 for j in jobs if j.get('url') and _need_salary(j))
    print(f'剩余描述缺失: {still_missing_desc} (其中有链接 {still_missing_desc_with_url})')
    print(f'剩余薪资缺失: {still_missing_salary} (其中有链接 {still_missing_salary_with_url})')

if __name__ == '__main__':
    main()
