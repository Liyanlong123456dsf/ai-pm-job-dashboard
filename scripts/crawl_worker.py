#!/usr/bin/env python3
import sys, io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import os
import json
import time
import argparse
import logging
import traceback
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
LOG_DIR = BASE_DIR / 'logs'
PARALLEL_DIR = LOG_DIR / 'parallel_crawl'
PARALLEL_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(SCRIPT_DIR))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [worker] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'parallel_worker.log', encoding='utf-8'),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger('crawl_worker')


def _read_json(path: Path, default=None):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        pass
    return default if default is not None else {}


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _filter_salary_jobs(jobs, min_avg=17, max_avg=None):
    filtered = []
    for job in jobs:
        try:
            avg = float(job.get('avg') or 0)
        except Exception:
            avg = 0
        if avg >= min_avg and (max_avg is None or avg < max_avg):
            filtered.append(job)
    return filtered


def _apply_account(alias: str, port: int):
    if port:
        os.environ['AI_PM_CHROME_PORT'] = str(port)
    if not alias:
        return ''
    try:
        import account_pool
        profile = account_pool.get_account_profile_dir(alias)
    except Exception as e:
        logger.warning(f'账号池加载失败: {e}')
        profile = None
    if not profile:
        logger.warning(f'账号 [{alias}] 未找到 Profile，沿用默认 Profile')
        return ''
    p = Path(profile)
    if not p.is_absolute():
        p = BASE_DIR / p
    os.environ['AI_PM_BOSS_PROFILE'] = str(p)
    logger.info(f'使用账号 [{alias}] Profile={p} Port={os.environ.get("AI_PM_CHROME_PORT", "9222")}')
    return str(p)


def _write_state(path: Path, worker_id: str, account: str, phase: str, detail: str, completed: int, total: int, raw_count: int, cleaned_count: int, errors=None):
    _write_json(path, {
        'worker_id': worker_id,
        'account': account,
        'phase': phase,
        'detail': detail,
        'completed': completed,
        'total': total,
        'raw': raw_count,
        'cleaned': cleaned_count,
        'errors': errors or [],
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })


def main():
    parser = argparse.ArgumentParser(description='parallel crawl worker')
    parser.add_argument('--worker-id', required=True)
    parser.add_argument('--account', default='')
    parser.add_argument('--chrome-port', type=int, default=9222)
    parser.add_argument('--tasks-file', required=True)
    parser.add_argument('--output-file', required=True)
    parser.add_argument('--state-file', default='')
    args = parser.parse_args()

    tasks_path = Path(args.tasks_file)
    output_path = Path(args.output_file)
    state_path = Path(args.state_file) if args.state_file else PARALLEL_DIR / f'state_{args.worker_id}.json'
    payload = _read_json(tasks_path, default={})
    tasks = payload.get('tasks') if isinstance(payload, dict) else payload
    tasks = tasks or []
    errors = []
    jobs = []
    raw_count = 0
    cleaned_count = 0

    _apply_account(args.account, args.chrome_port)

    from pipeline import process_batch
    from spiders.boss_dp import BossDPSpider

    _write_state(state_path, args.worker_id, args.account, 'starting', '启动浏览器', 0, len(tasks), 0, 0)
    spider = BossDPSpider()
    started = time.time()
    login_checked = False

    try:
        spider.start_browser(headless=False)
        first_city = ''
        for task in tasks:
            first_city = str(task.get('city_code') or '')
            if first_city:
                break
        if first_city and not spider.ensure_login(first_city):
            try:
                if args.account:
                    import account_pool
                    account_pool.mark_failure(args.account, 'parallel worker 登录未成功')
            except Exception:
                pass
            raise RuntimeError('登录未成功')
        if first_city:
            login_checked = True
            try:
                if args.account:
                    import account_pool
                    account_pool.mark_success(args.account)
            except Exception:
                pass

        for idx, task in enumerate(tasks, 1):
            keyword = str(task.get('keyword') or '').strip()
            city_name = str(task.get('city_name') or '').strip()
            city_code = str(task.get('city_code') or '').strip()
            salary_code = str(task.get('salary_code') or '').strip()
            salary_label = str(task.get('salary_label') or '').strip()
            stage = str(task.get('stage') or '').strip()
            greedy = bool(task.get('greedy', True))
            min_avg = float(task.get('min_avg') or 17)
            max_avg = task.get('max_avg')
            max_avg = float(max_avg) if max_avg is not None else None
            detail = f'{stage} · {keyword} · {city_name} · {salary_label}'
            _write_state(state_path, args.worker_id, args.account, 'running', detail, idx - 1, len(tasks), raw_count, cleaned_count, errors)

            try:
                raw = spider.run_keyword(
                    keyword,
                    {city_name: city_code},
                    greedy=greedy,
                    salary_code=salary_code,
                    salary_label=salary_label,
                    stop_on_no_new=True,
                )
                raw_count += len(raw)
                cleaned_all = process_batch(raw)
                cleaned = _filter_salary_jobs(cleaned_all, min_avg=min_avg, max_avg=max_avg)
                cleaned_count += len(cleaned)
                jobs.extend(cleaned)
                logger.info(f'[{args.worker_id}] {detail}: raw={len(raw)} cleaned={len(cleaned)}')
            except Exception as e:
                msg = f'{detail}: {e}'
                logger.error(msg, exc_info=True)
                errors.append(msg[:300])

            _write_state(state_path, args.worker_id, args.account, 'running', detail, idx, len(tasks), raw_count, cleaned_count, errors)

        ok = len(errors) == 0
    except Exception as e:
        ok = False
        errors.append(str(e)[:300])
        logger.error(f'worker failed: {e}', exc_info=True)
        if not login_checked:
            try:
                if args.account:
                    import account_pool
                    account_pool.mark_failure(args.account, str(e))
            except Exception:
                pass
    finally:
        try:
            if spider.page:
                spider.page.quit()
        except Exception:
            pass

    result = {
        'ok': ok,
        'worker_id': args.worker_id,
        'account': args.account,
        'tasks': len(tasks),
        'raw': raw_count,
        'cleaned': cleaned_count,
        'jobs': jobs,
        'errors': errors,
        'duration_sec': round(time.time() - started),
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    _write_json(output_path, result)
    _write_state(state_path, args.worker_id, args.account, 'done' if ok else 'failed', '完成' if ok else '失败', len(tasks), len(tasks), raw_count, cleaned_count, errors)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
